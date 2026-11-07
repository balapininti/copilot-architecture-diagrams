from __future__ import annotations

import io
import zipfile

import pytest

from archdiag.config import Config
from archdiag.repos import iter_source_files
from archdiag.resolve.names import norm_path
from archdiag.scan import ARCHIVE_READERS, ScanContext, scan_workspace
from archdiag.scan.cics import scan_bms, scan_csd
from archdiag.scan.ddl import scan_ddl
from archdiag.scan.mq import collect_mq, scan_mqsc
from archdiag.scan.other import register_other
from archdiag.textio import classify
from conftest import ESTATE


@pytest.fixture(scope="module")
def inv():
    return scan_workspace(ESTATE, Config())


def refs_from(inv, src):
    return [r for r in inv.refs if r.src == src]


def one_ref(inv, src, op):
    found = [r for r in inv.refs if r.src == src and r.op == op]
    assert len(found) == 1, found
    return found[0]


def mark(root, name):
    (root / name).mkdir(parents=True, exist_ok=True)
    (root / name / ".archdiag-repo").write_text("")
    return root / name


# ---------------------------------------------------------------- CSD and BMS


def test_csd(inv):
    r = one_ref(inv, "transaction:CLMI", "runs")
    assert (r.target_kind, r.target_name) == ("program", "CLMO100")
    assert r.evidence.path == "csd/CLAIMS.csd" and r.evidence.line == 4
    assert one_ref(inv, "transaction:CLMU", "runs").target_name == "CLMO120"
    f = inv.nodes["cicsfile:CLMMAST"]
    assert f.attrs["dsname"] == "PROD.CLM.MASTER.KSDS" and f.repo == "claims-online"
    r = one_ref(inv, "cicsfile:CLMMAST", "file_dataset")
    assert (r.target_kind, r.target_name) == ("dataset", "PROD.CLM.MASTER.KSDS")
    assert inv.nodes["transaction:CLMI"].evidence[0].line == 3


def test_csd_comments_verbs_and_abbreviations():
    text = ("* DEFINE TRANSACTION(FAKE) PROGRAM(NOPE)\n"
            "DEF TRANS(ab12) PROG(xyz1) DESCRIPTION(has (nested) parens PROGRAM(BAD))\n"
            "DEFINE FILE(F1) ADD(YES)\n"
            "DEFINE TRANSACTION(REM1) REMOTESYSTEM(SYSB)\n"
            "ADD GROUP(G) LIST(L)\n")
    nodes, refs = scan_csd("r", "x.csd", text, ScanContext())
    ids = {n.id for n in nodes}
    assert ids == {"transaction:AB12", "cicsfile:F1", "transaction:REM1"}
    assert [(r.src, r.target_name) for r in refs] == [("transaction:AB12", "XYZ1")]
    f = [n for n in nodes if n.id == "cicsfile:F1"][0]
    assert f.attrs["dsname"] is None


def test_bms(inv):
    n = inv.nodes["map:CLMM01"]
    assert n.kind == "map" and n.evidence[0].line == 1 and n.attrs["maps"] == ["CLMM1"]
    nodes, _ = scan_bms("r", "maps/X.bms", "* MAPSET COMMENT DFHMSD\n         DFHMSD TYPE=FINAL\n",
                        ScanContext())
    assert nodes == []


# ---------------------------------------------------------------- DDL


def test_ddl_tables_and_alias(inv):
    for t in ("CLMS.CLAIM", "CLMS.PAYMENT", "CLMS.POLICY", "ARCH.POLICY"):
        n = inv.nodes["table:" + t]
        assert n.repo == "claims-db" and n.attrs["type"] == "table"
        assert n.attrs["schema"] + "." + n.attrs["name"] == t
    a = inv.nodes["table:CLMS.CLM"]
    assert a.attrs["alias_of"] == "CLMS.CLAIM" and a.attrs["type"] == "alias"
    assert not [i for i in inv.nodes if i.startswith("table:FAKE")]


def test_ddl_comments_and_case():
    text = ("-- CREATE TABLE FAKE.T\n"
            "create table clms.x (a int);\n"
            "/* create view FAKE.V as\n select 1 */\n"
            "INSERT INTO T VALUES('CREATE TABLE FAKE.Q');\n"
            'CREATE   VIEW "CLMS"."V_OPEN" AS SELECT * FROM CLMS.X;\n'
            "SET CURRENT SQLID = 'PAY';\n"
            "CREATE TABLE LEDGER (A INT);\n"
            "CREATE SYNONYM CLMX FOR CLMS.X;\n"
            "CREATE OR REPLACE VIEW clms.v2 AS SELECT 1 FROM SYSIBM.SYSDUMMY1;\n")
    nodes, _ = scan_ddl("r", "x.sql", text, ScanContext())
    by = {n.id: n for n in nodes}
    assert set(by) == {"table:CLMS.X", "table:CLMS.V_OPEN", "table:PAY.LEDGER",
                       "table:PAY.CLMX", "table:CLMS.V2"}
    assert by["table:CLMS.X"].evidence[0].line == 2
    assert by["table:CLMS.V_OPEN"].attrs["type"] == "view"
    assert by["table:PAY.CLMX"].attrs["alias_of"] == "CLMS.X"


def test_ddl_unqualified_without_schema():
    nodes, _ = scan_ddl("r", "x.sql", "CREATE TABLE CLAIMX (A INT);", ScanContext())
    assert [(n.id, n.attrs["schema"]) for n in nodes] == [("table:CLAIMX", None)]


# ---------------------------------------------------------------- MQSC


def test_mqsc(inv):
    q = inv.nodes["queue:CLM.REQ"].attrs
    assert q["type"] == "alias" and q["target"] == "CLM.REQ.LQ"
    lq = inv.nodes["queue:CLM.REQ.LQ"]
    assert lq.attrs["type"] == "local" and lq.attrs["process"] == "CLM.PROC"
    assert lq.attrs["initq"] == "CICS01.INITQ" and lq.attrs["trigger"] is True
    assert lq.attrs["bridge"] is False and lq.evidence[0].line == 2
    assert inv.nodes["mqprocess:CLM.PROC"].attrs["applicid"] == "CLMI"
    assert inv.nodes["queue:CLM.RSP"].attrs["type"] == "local"


def test_mq_bridge_flag(inv):
    assert inv.nodes["queue:CLM.BRIDGE.Q"].attrs["bridge"] is True
    assert inv.nodes["mqprocess:CLM.BPROC"].attrs["applicid"] == "CLMB"


def _mq(text, others=()):
    ctx = ScanContext()
    for rel, t in list(others) + [("q.mqsc", text)]:
        collect_mq("r", rel, t, classify(rel, t), ctx)
    nodes, _ = scan_mqsc("r", "q.mqsc", text, ctx)
    return {n.id: n for n in nodes}


def test_mq_bridge_when_process_is_ckbr():
    by = _mq("DEF QL('BR.Q') INITQ('CICS01.INITQ') PROCESS(BR.P) TRIGGER\n")
    assert by["queue:BR.Q"].attrs["bridge"] is False  # the process lives in another file
    by = _mq("DEF QL('BR.Q') INITQ('CICS01.INITQ') PROCESS(BR.P) TRIGGER\n",
             [("p.mqsc", "DEFINE PROCESS(BR.P) APPLICID('CKBR')\n")])
    assert by["queue:BR.Q"].attrs["bridge"] is True


def test_mq_bridge_when_queue_named_in_ckbr_start():
    cob = ("       PROCEDURE DIVISION.\n"
           "           EXEC CICS START TRANSID('CKBR')\n"
           "                FROM('Q=CLM.BRQ,AUTH=LOCAL') LENGTH(22) END-EXEC.\n")
    by = _mq("DEFINE QLOCAL(CLM.BRQ)\nDEFINE QLOCAL(OTHER) INITQ(CLM.BRQ)\nDEFINE QLOCAL(NOT.BR)\n",
             [("cobol/STARTBR.cbl", cob)])
    assert by["queue:CLM.BRQ"].attrs["bridge"] is True
    assert by["queue:OTHER"].attrs["bridge"] is True
    assert by["queue:NOT.BR"].attrs["bridge"] is False


def test_mq_remote_case_and_continuation():
    text = ("* DEFINE QLOCAL(FAKE)\n"
            "define qremote(clm.out) rname('Remote.Q') -\n"
            "  rqmname(QM2) xmitq(QM2.XMIT)\n"
            "DEFINE QA('lower.alias') TARGQ(CLM.RSP) DESCR('has ( paren')\n")
    by = _mq(text)
    assert set(by) == {"queue:CLM.OUT", "queue:lower.alias"}
    r = by["queue:CLM.OUT"].attrs
    assert (r["type"], r["target"], r["rqmname"], r["xmitq"]) == ("remote", "Remote.Q", "QM2", "QM2.XMIT")
    assert by["queue:lower.alias"].attrs["target"] == "CLM.RSP"


# ---------------------------------------------------------------- z/OS Connect


def test_zosconnect(inv):
    nid = "zosapi:GET /zos/claims/{}/status"
    n = inv.nodes[nid]
    assert n.kind == "zosapi" and n.repo == "claims-online"
    assert n.evidence[0].path == "zosconnect/apis/claimstatus/package.xml"
    assert n.evidence[0].line == 5
    r = one_ref(inv, nid, "runs")
    assert (r.target_kind, r.target_name) == ("program", "CLMO130")
    assert r.attrs["service"] == "ClaimStatus"


PKG = """<?xml version="1.0" encoding="UTF-8"?>
<zosConnectApi xmlns="http://www.ibm.com/zosConnect/2.0/zosConnectApi" id="acct">
  <apiSpec title="acct" basePath="/acct" version="1.0.0">
    <path relativePath="/enquiry/{accno}">
      <method type="GET" zosConnectServiceRef="CSaccenq"
              httpXformFile="api/enquiry/{accno}/GET/mapping.xml"></method>
      <method zosConnectServiceRef="CSaccdel" type="DELETE"></method>
    </path>
    <path relativePath="/">
      <method type="POST" zosConnectServiceRef="NoSuchSvc"></method>
    </path>
  </apiSpec>
</zosConnectApi>
"""

MANIFEST = """---
Manifest-Version: 1.0
name: "%s"
provider: "CICS-1.0"
providerProperties:
- propertyName: "connectionRef"
  value: "cicsConn"
  type: "STRING"
- propertyName: "program"
  value: "%s"
  type: "STRING"
version: "1.0.0"
"""


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
    return buf.getvalue()


def test_zosconnect_archives(tmp_path):
    repo = mark(tmp_path, "zc")
    sar = _zip([("manifest.yml", MANIFEST % ("CSaccdel", "DELACC"))])
    (repo / "deploy").mkdir()
    (repo / "deploy" / "CSaccdel.sar").write_bytes(sar)
    aar = _zip([("package.xml", PKG),
                ("services/CSaccenq/manifest.yml", MANIFEST % ("CSaccenq", "INQACC")),
                ("api-docs/swagger.json", "{}")])
    (repo / "deploy" / "acct.aar").write_bytes(aar)
    (repo / "deploy" / "broken.sar").write_bytes(b"not a zip")
    rels = {p.name for p in iter_source_files(repo)}
    assert {"CSaccdel.sar", "acct.aar"} <= rels
    inv = scan_workspace(tmp_path, Config())
    g = one_ref(inv, "zosapi:GET /acct/enquiry/{}", "runs")
    assert g.target_name == "INQACC"
    assert g.evidence.path == "deploy/acct.aar!/package.xml" and g.evidence.line == 5
    assert g.attrs["service_at"] == "deploy/acct.aar!/services/CSaccenq/manifest.yml:10"
    assert one_ref(inv, "zosapi:DELETE /acct/enquiry/{}", "runs").target_name == "DELACC"
    p = one_ref(inv, "zosapi:POST /acct", "runs")
    assert p.target_name is None and "NoSuchSvc" in p.reason and "not in these repos" in p.reason


def test_archive_reader_hook_registered():
    assert {".sar", ".aar"} <= set(ARCHIVE_READERS)


def test_zosconnect_build_toolkit_properties_and_ambiguity(tmp_path):
    a, b = mark(tmp_path, "a"), mark(tmp_path, "b")
    (a / "svc").mkdir()
    (a / "svc" / "health.properties").write_text(
        "name=Health\nprovider=cics\nprogram=HLTH01\nconnectionRef=cicsConn\n")
    (b / "svc").mkdir()
    (b / "svc" / "health.properties").write_text("name=Health\nprovider=cics\nprogram=HLTH02\n")
    (b / "svc" / "application.properties").write_text("program=NOTZOS\nname=app\n")
    (a / "zosconnect").mkdir()
    (a / "zosconnect" / "package.xml").write_text(PKG.replace("CSaccenq", "Health"))
    (b / "package.xml").write_text(PKG.replace("CSaccenq", "Health"))
    inv = scan_workspace(tmp_path, Config())
    got = [(r.evidence.repo, r.target_name) for r in inv.refs
           if r.src == "zosapi:GET /acct/enquiry/{}"]
    assert sorted(got) == [("a", "HLTH01"), ("b", "HLTH02")]  # same repo wins


def test_zosconnect_ambiguous_service(tmp_path):
    a, b, c = mark(tmp_path, "a"), mark(tmp_path, "b"), mark(tmp_path, "c")
    a.joinpath("s.properties").write_text("name=Health\nprovider=cics\nprogram=HLTH01\n")
    b.joinpath("s.properties").write_text("name=Health\nprovider=cics\nprogram=HLTH02\n")
    c.joinpath("package.xml").write_text(PKG.replace("CSaccenq", "Health"))
    inv = scan_workspace(tmp_path, Config())
    r = one_ref(inv, "zosapi:GET /acct/enquiry/{}", "runs")
    assert r.target_name is None and r.candidates == ["HLTH01", "HLTH02"]
    assert "Health" in r.reason


def test_zosconnect_openapi3_project(tmp_path):
    repo = mark(tmp_path, "oas3")
    main = repo / "claims-api" / "src" / "main"
    (main / "api").mkdir(parents=True)
    (main / "api" / "openapi.yaml").write_text("openapi: 3.0.0\nservers:\n- url: /\npaths: {}\n")
    asset = main / "zosAssets" / "claimStatus"
    asset.mkdir(parents=True)
    (asset / "zosAsset.yaml").write_text(
        '---\nversion: 1.0\ntype: "cicsCommarea-1.0"\ndescription: ""\nproviderProperties:\n'
        '  language: "COBOL"\n  program: "CLMO130"\n  connectionRef: "cicsConn"\n')
    op = main / "operations" / "%2Fclaims%2F%7Bid%7D%2Fstatus" / "get"
    op.mkdir(parents=True)
    (op / "operation.yaml").write_text('---\nversion: 1\nzasset: "claimStatus"\n')
    op2 = main / "operations" / "%2Fclaims" / "post"
    op2.mkdir(parents=True)
    (op2 / "operation.yaml").write_text('---\nversion: 1\nzasset: "missingAsset"\n')
    inv = scan_workspace(tmp_path, Config())
    r = one_ref(inv, "zosapi:GET /claims/{}/status", "runs")
    assert r.target_name == "CLMO130" and r.evidence.line == 3
    assert r.evidence.path.endswith("operations/%2Fclaims%2F%7Bid%7D%2Fstatus/get/operation.yaml")
    m = one_ref(inv, "zosapi:POST /claims", "runs")
    assert m.target_name is None and "missingAsset" in m.reason


def test_norm_path():
    assert norm_path("https://h:9443/zos/claims/${id}/status/") == "/zos/claims/{}/status"
    assert norm_path("/claims/:id/x/{claimId}") == "/claims/{}/x/{}"
    assert norm_path("http://host/") == "/"
    assert norm_path("/a/{id:[0-9]+}?q=1") == "/a/{}"
    assert norm_path("zos//claims") == "/zos/claims"


# ---------------------------------------------------------------- other languages


def test_not_analyzed_registered(inv):
    n = inv.nodes["notanalyzed:DATEUTIL"]
    assert n.attrs["language"] == "asm" and n.repo == "claims-batch"
    assert n.evidence[0].line == 1
    assert inv.languages_not_analyzed["asm"] == 1


def test_not_analyzed_names():
    asm = ("* COMMENT CSECT\nMAINPGM  CSECT\n         ENTRY ALT1,ALT2\n         END\n")
    nodes, refs = register_other("r", "asm/MEMBER1.asm", asm, ScanContext())
    assert refs == []
    assert {n.id for n in nodes} == {"notanalyzed:MAINPGM", "notanalyzed:ALT1",
                                     "notanalyzed:ALT2", "notanalyzed:MEMBER1"}
    pli = "/* PL/I */\n CLMPLI: PROC OPTIONS(MAIN);\n END;\n"
    nodes, _ = register_other("r", "pli/clmp.pli", pli, ScanContext())
    assert {(n.id, n.attrs["language"]) for n in nodes} == {
        ("notanalyzed:CLMP", "pli"), ("notanalyzed:CLMPLI", "pli")}
    nodes, _ = register_other("r", "rexx/tool.rexx", "/* REXX */\nsay 'hi'\n", ScanContext())
    assert [(n.id, n.attrs["language"]) for n in nodes] == [("notanalyzed:TOOL", "rexx")]
    nodes, _ = register_other("r", "asm/MYMAC.mac", "         MACRO\n", ScanContext())
    assert nodes == []  # an assembler macro is not a callable program


# ---------------------------------------------------------------- fix round 1


def test_mq_continuation_splits_mid_token():
    by = _mq("DEFINE QLOCAL(CLM.REQ.+\n      LQ) PROCESS(P.+\n   ONE)\n"
             "DEFINE QLOCAL(ABC.-\nDEF) DESCR('two -\n words')\n")
    assert set(by) == {"queue:CLM.REQ.LQ", "queue:ABC.DEF"}
    assert by["queue:CLM.REQ.LQ"].attrs["process"] == "P.ONE"


def test_mq_sequence_area_ignored():
    line = "DEFINE QLOCAL(CLM.SEQ) PROCESS(CLM.PROC)".ljust(72) + "00010000"
    long_line = "DEFINE QLOCAL(A.VERY.LONG.DISTRIBUTED.QUEUE.NAME.THAT.GOES.PAST.COLUMN.SEVENTY.TWO)"
    by = _mq(line + "\n" + long_line + "\n")
    assert by["queue:CLM.SEQ"].attrs["process"] == "CLM.PROC"
    assert "queue:A.VERY.LONG.DISTRIBUTED.QUEUE.NAME.THAT.GOES.PAST.COLUMN.SEVENTY.TWO" in by


def test_mq_alias_targtype():
    by = _mq("DEFINE QALIAS(A1) TARGET(T1)\nDEFINE QALIAS(A2) TARGET(TOPIC1) TARGTYPE(TOPIC)\n")
    assert by["queue:A1"].attrs["targtype"] == "QUEUE"
    assert by["queue:A2"].attrs["targtype"] == "TOPIC"


def test_ckbr_scoped_to_one_statement_and_default_queue():
    cob = ("       PROCEDURE DIVISION.\n"
           "           EXEC CICS START TRANSID('CKBR') END-EXEC.\n"
           "           MOVE 'Q=NOT.BRIDGE' TO WS-X.\n"
           "      *    EXEC CICS START TRANSID('CKBR') FROM('Q=COMMENTED') END-EXEC.\n"
           "           EXEC CICS START TRANSID('CKBR') FROM(WS-PARMS) END-EXEC.\n")
    by = _mq("DEFINE QLOCAL(SYSTEM.CICS.BRIDGE.QUEUE)\nDEFINE QLOCAL(NOT.BRIDGE)\n"
             "DEFINE QLOCAL(COMMENTED)\n", [("cobol/S.cbl", cob)])
    assert by["queue:SYSTEM.CICS.BRIDGE.QUEUE"].attrs["bridge"] is True
    assert by["queue:NOT.BRIDGE"].attrs["bridge"] is False
    assert by["queue:COMMENTED"].attrs["bridge"] is False


def test_ddl_special_registers_do_not_set_schema():
    text = ("SET CURRENT SQLID = 'PAY';\n"
            "SET CURRENT SQLID = USER;\n"
            "CREATE TABLE T1 (A INT);\n"
            "SET SCHEMA = 'OPS';\n"
            "SET CURRENT SCHEMA = CURRENT SQLID;\n"
            "CREATE TABLE T2 (A INT);\n"
            "SET SCHEMA = 'OPS';\n"
            "SET SCHEMA = :HVSCHEMA;\n"
            "CREATE TABLE T3 (A INT);\n")
    nodes, _ = scan_ddl("r", "x.sql", text, ScanContext())
    assert sorted(n.id for n in nodes) == ["table:T1", "table:T2", "table:T3"]


def test_ddl_three_part_names():
    nodes, _ = scan_ddl("r", "x.sql", "CREATE ALIAS LOC1.CLMS.RCLM FOR LOC2.CLMS.CLAIM;\n"
                                      "CREATE TABLE LOC1.CLMS.T (A INT);\n", ScanContext())
    by = {n.id: n for n in nodes}
    assert set(by) == {"table:CLMS.RCLM", "table:CLMS.T"}
    assert by["table:CLMS.RCLM"].attrs["alias_of"] == "CLMS.CLAIM"


def test_csd_blanks_continuation_and_sequence_area():
    head, tail = "DEFINE TRANSACTION (CLX1) GROUP (G)", "PROGRAM (CLMO"
    l1 = head + " " * (71 - len(head) - len(tail)) + tail + "*"  # value runs to column 71
    assert len(l1) == 72
    text = (l1 + "\n100) DESCRIPTION(x)\n"
            + "DEFINE FILE(F2) DSNAME(PROD.F2)".ljust(72) + "00020000\n"
            + "DEFI TRANSAC(CLX2) PROG(CLMO200)\n")
    nodes, refs = scan_csd("r", "x.csd", text, ScanContext())
    got = {(r.src, r.target_name) for r in refs}
    assert got == {("transaction:CLX1", "CLMO100"), ("cicsfile:F2", "PROD.F2"),
                   ("transaction:CLX2", "CLMO200")}


def test_zosconnect_project_and_its_build_in_one_repo(tmp_path):
    repo = mark(tmp_path, "zc")
    (repo / "zosconnect" / "apis" / "acct").mkdir(parents=True)
    (repo / "zosconnect" / "apis" / "acct" / "package.xml").write_text(PKG)
    (repo / "zosconnect" / "services").mkdir()
    (repo / "zosconnect" / "services" / "e.properties").write_text(
        "name=CSaccenq\nprovider=cics\nprogram=INQACC\n")
    (repo / "zosconnect" / "services" / "d.properties").write_text(
        "name=CSaccdel\nprovider=cics\nprogram=DELACC\n")
    (repo / "deploy").mkdir()
    (repo / "deploy" / "acct.aar").write_bytes(_zip([
        ("package.xml", PKG),
        ("services/CSaccenq/manifest.yml", MANIFEST % ("CSaccenq", "INQACC")),
        ("services/CSaccdel/manifest.yml", MANIFEST % ("CSaccdel", "DELOLD"))]))
    inv = scan_workspace(tmp_path, Config())
    nid = "zosapi:GET /acct/enquiry/{}"
    n = inv.nodes[nid]
    assert [e.path for e in n.evidence] == ["zosconnect/apis/acct/package.xml"]
    assert n.attrs["also_built_as"] == ["deploy/acct.aar!/package.xml"]
    r = one_ref(inv, nid, "runs")
    assert r.evidence.path == "zosconnect/apis/acct/package.xml" and r.target_name == "INQACC"
    # DELETE: the aar's own service maps to another program -> real ambiguity, both kept
    d = refs_from(inv, "zosapi:DELETE /acct/enquiry/{}")
    assert len(d) == 2 and len(inv.nodes["zosapi:DELETE /acct/enquiry/{}"].evidence) == 2


def test_skipped_files_recorded_and_round_trip(tmp_path, monkeypatch):
    from archdiag import repos
    from archdiag.store import load_inventory, save_json
    repo = mark(tmp_path, "r")
    (repo / "bad.aar").write_bytes(b"not a zip")
    (repo / "big.cbl").write_text("x" * 200)
    (repo / "ok.cbl").write_text("       PROGRAM-ID. OK.\n")
    monkeypatch.setattr(repos, "MAX_BYTES", 100)
    inv = scan_workspace(tmp_path, Config())
    by = {s["path"]: s for s in inv.skipped}
    assert set(by) == {"bad.aar", "big.cbl"}
    assert by["bad.aar"]["repo"] == "r" and "unreadable archive" in by["bad.aar"]["reason"]
    assert "larger than" in by["big.cbl"]["reason"]
    save_json(tmp_path / "inv.json", inv)
    assert load_inventory(tmp_path / "inv.json").skipped == inv.skipped


def test_oversized_archive_member_recorded(tmp_path, monkeypatch):
    from archdiag.scan import zosconnect
    repo = mark(tmp_path, "r")
    (repo / "a.aar").write_bytes(_zip([("package.xml", PKG),
                                       ("services/x/manifest.yml", "y" * 5000)]))
    monkeypatch.setattr(zosconnect, "MAX_MEMBER_BYTES", 2000)
    inv = scan_workspace(tmp_path, Config())
    assert [s["path"] for s in inv.skipped] == ["a.aar!/services/x/manifest.yml"]


def test_oas3_base_url_kept_out_of_id(tmp_path):
    repo = mark(tmp_path, "o")
    main = repo / "src" / "main"
    (main / "api").mkdir(parents=True)
    (main / "api" / "openapi.yaml").write_text(
        "openapi: 3.0.0\nservers:\n  - url: https://zos.example.com/claimsapi\npaths: {}\n")
    op = main / "operations" / "%2Fclaims" / "get"
    op.mkdir(parents=True)
    (op / "operation.yaml").write_text('zasset: "a"\n')
    inv = scan_workspace(tmp_path, Config())
    assert inv.nodes["zosapi:GET /claims"].attrs["base_url"] == "https://zos.example.com/claimsapi"
