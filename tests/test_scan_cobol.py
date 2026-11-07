from __future__ import annotations

import pytest

from archdiag.config import Config
from archdiag.scan import ScanContext, scan_workspace
from archdiag.scan.cobol import scan_cobol
from conftest import ESTATE


@pytest.fixture(scope="module")
def inv():
    return scan_workspace(ESTATE, Config())


def refs_of(inv, prog):
    return {(r.op, r.target_kind, r.target_name) for r in inv.refs if r.src == "program:" + prog}


def one(inv, prog, **kw):
    found = [r for r in inv.refs if r.src == "program:" + prog
             and all(getattr(r, k) == v for k, v in kw.items())]
    assert len(found) == 1, found
    return found[0]


def scan(text, rel="X.cbl"):
    nodes, refs = scan_cobol("r", rel, text, ScanContext())
    return nodes, refs


def test_copy_call_sql(inv):
    assert refs_of(inv, "CLMB200") >= {("copy", "copybook", "CLMREC"),
                                       ("call", "program", "DATEUTIL"),
                                       ("select", "table", "CLAIM")}


def test_variable_call_has_candidate(inv):
    r = one(inv, "CLMB200", op="call", target_name=None)
    assert r.candidates == ["CLMB210"] and "WS-PGM" in r.reason


def test_xctl_unresolved(inv):
    r = one(inv, "CLMO100", op="xctl")
    assert r.target_name is None and r.candidates == []
    assert r.reason == "XCTL to WS-NEXT-PGM, name set at run time"


def test_cics_ops(inv):
    assert refs_of(inv, "CLMO100") >= {("link", "program", "CLMO110"),
                                       ("return_transid", "transaction", "CLMU"),
                                       ("send_map", "map", "CLMM01"),
                                       ("cics_file", "cicsfile", "CLMMAST")}
    assert one(inv, "CLMO100", op="cics_file").attrs == {"io": "read"}
    assert ("start", "transaction", "CLMX") in refs_of(inv, "CLMO130")


def test_mq_queue_names_resolved(inv):
    assert refs_of(inv, "CLMO100") >= {("get", "queue", "CLM.REQ.LQ"),
                                       ("put", "queue", "CLM.RSP")}


def test_qualified_and_alias_names_kept_raw(inv):
    sel = {r.target_name for r in inv.refs if r.src == "program:CLMO100" and r.op == "select"}
    assert sel >= {"CLAIM", "POLICY", "CLMS.CLM"}
    assert "C" not in sel and "P" not in sel


def test_file_modes(inv):
    assert inv.nodes["program:CLMB200"].attrs["files"] == {"CLMIN": "input", "CLMOUT": "output"}


def test_comment_not_scanned(inv):
    assert not [r for r in inv.refs if r.target_name == "NOTREAL"]


def test_cp1252_crlf_file_scans(inv):
    assert "program:CLMB300" in inv.nodes
    assert ("insert", "table", "CLMS.PAYMENT") in refs_of(inv, "CLMB300")
    assert ("copy", "copybook", "PAYREC") in refs_of(inv, "CLMB300")


def test_pds_member_without_extension(inv):
    assert "program:CLMB400" in inv.nodes


def test_asm_not_a_program(inv):
    assert "program:DATEUTIL" not in inv.nodes
    assert inv.languages_not_analyzed.get("asm") == 1


def test_copybook_nodes(inv):
    assert {"copybook:CLMREC", "copybook:PAYREC"} <= set(inv.nodes)
    assert inv.nodes["copybook:CLMREC"].repo == "shared-copybooks"


def test_duplicate_program_keeps_both_definitions(inv):
    ev = inv.nodes["program:CLMO110"].evidence
    assert sorted(e.path for e in ev) == ["cobol/CLMO110.cbl", "endevor/qa/CLMO110.cbl"]
    assert len(inv.nodes["program:CLMB200"].evidence) == 1


def test_sequence_area_ignored():
    line = "000100" + " " + "    CALL 'ABC'".ljust(65) + "XYZ12345"
    _, refs = scan("000010 PROGRAM-ID. P1.\n" + line + "\n")
    assert [(r.op, r.target_name) for r in refs] == [("call", "ABC")]
    assert refs[0].evidence.line == 2


def test_free_format():
    _, refs = scan("PROGRAM-ID. P1.\nPROCEDURE DIVISION.\n    CALL 'ABC'.\n*> CALL 'NO'\n")
    assert [r.target_name for r in refs] == ["ABC"]


def test_multiline_exec_sql():
    text = ("       PROGRAM-ID. P1.\n"
            "           EXEC SQL SELECT A,\n"
            "                           B\n"
            "                    INTO :X, :Y\n"
            "                    FROM MYSCHEMA.TAB1 T\n"
            "           END-EXEC.\n")
    _, refs = scan(text)
    assert [(r.op, r.target_name, r.evidence.line) for r in refs] == [("select", "MYSCHEMA.TAB1", 5)]


def test_sql_forms():
    text = ("       PROGRAM-ID. P1.\n"
            "           EXEC SQL DELETE FROM T1 WHERE A IN (SELECT A FROM T2) END-EXEC.\n"
            "           EXEC SQL UPDATE T3 SET A = 1 END-EXEC.\n"
            "           EXEC SQL SELECT EXTRACT(YEAR FROM D) INTO :Y FROM T4 END-EXEC.\n"
            "           EXEC SQL DECLARE C1 CURSOR FOR SELECT X FROM T5 A, T6 B END-EXEC.\n"
            "           EXEC SQL VALUES CURRENT DATE INTO :D END-EXEC.\n"
            "           EXEC SQL PREPARE S1 FROM :WS-STMT END-EXEC.\n")
    _, refs = scan(text)
    got = [(r.op, r.target_name) for r in refs]
    assert got == [("delete", "T1"), ("select", "T2"), ("update", "T3"), ("select", "T4"),
                   ("select", "T5"), ("select", "T6"), ("select", None)]
    assert "run time" in refs[-1].reason


def test_literal_continuation():
    text = ("       PROGRAM-ID. P1.\n"
            "           CALL 'ABCD" + " " * 52 + "\n"
            "      -    'EFGH'.\n")
    text = text.replace("'ABCD" + " " * 52, ("           CALL 'ABCD").ljust(72)[11:], 1)
    lines = ["       PROGRAM-ID. P1.", ("           CALL 'ABCD").ljust(72)[:-0 or None],
             "      -    'EFGH'."]
    lines[1] = ("           CALL 'ABCD" + "X" * 0).ljust(72)
    _, refs = scan("\n".join(lines) + "\n")
    assert refs[0].target_name.startswith("ABCD") and refs[0].target_name.endswith("EFGH")


def test_mq_unresolved_and_cics_variable_with_value():
    text = ("       PROGRAM-ID. P1.\n"
            "       01  WS-T PIC X(4) VALUE 'TRN1'.\n"
            "           CALL 'MQGET' USING HCONN HOBJ.\n"
            "           EXEC CICS START TRANSID(WS-T) END-EXEC.\n")
    _, refs = scan(text)
    q = [r for r in refs if r.target_kind == "queue"][0]
    assert q.target_name is None and q.reason == "queue name not found in program"
    t = [r for r in refs if r.op == "start"][0]
    assert t.target_name is None and t.candidates == ["TRN1"]
