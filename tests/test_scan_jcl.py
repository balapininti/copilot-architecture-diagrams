from __future__ import annotations

from pathlib import Path

import pytest

from archdiag.config import Config
from archdiag.scan import scan_workspace
from conftest import ESTATE

BATCH = ESTATE / "claims-batch"
J100 = "claims-batch/jcl/CLMD100.jcl"


@pytest.fixture(scope="module")
def inv():
    return scan_workspace(ESTATE, Config())


def step_refs(inv, step_suffix):
    sid = "step:" + step_suffix
    return [r for r in inv.refs if r.src == sid]


def refs_of(inv, step_suffix):
    return {(r.op, r.target_kind, r.target_name) for r in step_refs(inv, step_suffix)}


def one_ref(inv, step_suffix, op):
    found = [r for r in step_refs(inv, step_suffix) if r.op == op]
    assert len(found) == 1, found
    return found[0]


def scan_text(tmp_path, text, name="J1.jcl", extra=None):
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / ".archdiag-repo").write_text("")
    (repo / name).write_text(text)
    for n, t in (extra or {}).items():
        (repo / n).write_text(t)
    return scan_workspace(tmp_path, Config())


def line_of(path, needle):
    for i, ln in enumerate(Path(path).read_text().split("\n"), 1):
        if needle in ln:
            return i
    raise AssertionError(needle)


def test_symbols_and_disp(inv):
    assert ("read", "dataset", "PROD.CLM.MASTER.KSDS") in refs_of(inv, J100 + "#STEP010")
    assert ("write", "dataset", "PROD.CLAIMS.DAILY") in refs_of(inv, J100 + "#STEP020")


def test_environment_copy_uses_its_own_symbol(inv):
    assert ("read", "dataset", "TEST.CLM.MASTER.KSDS") in refs_of(
        inv, "claims-batch/jcl/test/CLMD100.jcl#STEP010")


def test_gdg_attr(inv):
    assert one_ref(inv, J100 + "#STEP020", "write").attrs["gdg"] == "+1"
    daily = [r for r in step_refs(inv, J100 + "#STEP030") if r.attrs.get("ddname") == "DAILYIN"][0]
    assert daily.attrs["gdg"] == "0" and daily.target_name == "PROD.CLAIMS.DAILY"


def test_ikjeft01_runs_inner_program(inv):
    refs = refs_of(inv, J100 + "#STEP030")
    assert ("runs", "program", "CLMB300") in refs
    assert not any(r[2] == "IKJEFT01" for r in refs)


def test_utilities_and_transfer(inv):
    assert ("runs", "utility", "IEBGENER") in refs_of(inv, J100 + "#STEP040")
    assert ("transfer", "external", "NDM:FINANCE") in refs_of(inv, J100 + "#STEP050")
    assert ("runs", "program", "CLMB200") in refs_of(inv, J100 + "#STEP020")
    assert ("runs", "utility", "SORT") in refs_of(inv, J100 + "#STEP010")


def test_transfer_evidence_is_the_snode_line(inv):
    r = one_ref(inv, J100 + "#STEP050", "transfer")
    assert r.evidence.line == line_of(BATCH / "jcl/CLMD100.jcl", "SNODE=FINANCE")


def test_mod_is_write(inv):
    assert ("write", "dataset", "PROD.CLAIMS.AUDIT") in refs_of(inv, J100 + "#STEP040")
    assert ("update", "dataset", "PROD.CLAIMS.AUDIT") not in refs_of(inv, J100 + "#STEP040")


def test_temp_dataset_flagged(inv):
    r = [x for x in step_refs(inv, J100 + "#STEP010") if x.attrs.get("ddname") == "SORTOUT"][0]
    assert r.attrs["temp"] is True and r.target_name == "&&SORTED" and r.op == "write"
    c = [x for x in step_refs(inv, J100 + "#STEP020") if x.attrs.get("ddname") == "CLMIN"][0]
    assert c.attrs["temp"] is True and c.op == "read"


def test_sysout_gives_no_ref_but_a_step_attr(inv):
    assert not any(r.attrs.get("ddname") == "REPORT" for r in inv.refs)
    assert inv.nodes["step:" + J100 + "#STEP030"].attrs["sysout"] == ["REPORT (SYSOUT=A)"]


def test_proc_override_beats_default(inv):
    assert ("read", "dataset", "PROD.PAYMENT.FEED") in refs_of(inv, "claims-batch/jcl.pds/CLMD300#RUN")
    assert ("runs", "program", "CLMB400") in refs_of(inv, "claims-batch/jcl.pds/CLMD300#RUN")
    r = one_ref(inv, "claims-batch/jcl.pds/CLMD300#RUN", "read")
    # evidence points at the proc file line
    assert r.evidence.path == "proc/CLMPRC.proc"
    assert r.evidence.line == line_of(BATCH / "proc/CLMPRC.proc", "FEED")


def test_proc_default_used_when_not_overridden(inv):
    assert ("read", "dataset", "TEST.PAYMENT.FEED") in refs_of(inv, "claims-batch/proc/CLMPRC.proc#RUN")


def test_unresolved_symbol_kept_with_reason(inv):
    r = one_ref(inv, "claims-batch/jcl.pds/CLMD300#S2", "write")
    assert r.target_name == "&UNDEF..OUT.FILE"
    assert r.reason == "symbol &UNDEF has no value in these repos"


def test_cond_and_order(inv):
    n = inv.nodes
    assert n["step:" + J100 + "#STEP020"].attrs["cond"] == "COND=(0,NE)"
    assert n["step:" + J100 + "#STEP040"].attrs["cond"] == "RC <= 4"
    assert n["step:" + J100 + "#STEP010"].attrs["cond"] is None
    assert [n["step:%s#STEP0%d0" % (J100, i)].attrs["order"] for i in range(1, 6)] == [1, 2, 3, 4, 5]
    assert n["step:" + J100 + "#STEP050"].attrs["pgm"] == "DMBATCH"
    assert n["step:claims-batch/jcl.pds/CLMD300#RUN"].attrs["proc"] == "CLMPRC"
    assert n["job:" + J100].kind == "job" and n["job:" + J100].name == "CLMD100"


def test_comment_lines_ignored(inv):
    for r in inv.refs:
        assert r.target_name not in ("FAKE.DS", "FAKEPGM")


def test_extensionless_member_is_scanned(inv):
    assert "job:claims-batch/jcl.pds/CLMD300" in inv.nodes


def test_continuation_lines(tmp_path):
    text = ("//J1 JOB (A),'X'\n"
            "//S1 EXEC PGM=MYPGM,\n"
            "//   REGION=0M\n"
            "//OUT DD DSN=PROD.A.B,\n"
            "//*  a comment in the middle\n"
            "//     DISP=(NEW,\n"
            "//     CATLG),UNIT=SYSDA\n")
    i = scan_text(tmp_path, text)
    refs = refs_of(i, "r/J1.jcl#S1")
    assert ("write", "dataset", "PROD.A.B") in refs and ("runs", "program", "MYPGM") in refs
    r = one_ref(i, "r/J1.jcl#S1", "write")
    assert r.evidence.line == 4


def test_evidence_points_to_line(inv):
    r = one_ref(inv, J100 + "#STEP020", "write")
    assert r.evidence.line == line_of(BATCH / "jcl/CLMD100.jcl", "CLMOUT")
    assert r.evidence.path == "jcl/CLMD100.jcl" and r.evidence.repo == "claims-batch"
    assert "CLMOUT" in r.evidence.text


def test_include_member_without_job_card(tmp_path):
    inc = "//I1 EXEC PGM=INCPGM\n//D DD DSN=&HLQ..INC.DS,DISP=SHR\n"
    text = "//J1 JOB (A),'X'\n// SET HLQ=PROD\n// INCLUDE MEMBER=MYINC\n"
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / ".archdiag-repo").write_text("")
    (repo / "J1.jcl").write_text(text)
    (repo / "MYINC.jcl").write_text(inc)
    i = scan_workspace(tmp_path, Config())
    assert ("read", "dataset", "PROD.INC.DS") in refs_of(i, "r/J1.jcl#I1")
    r = one_ref(i, "r/J1.jcl#I1", "read")
    assert r.evidence.path == "MYINC.jcl" and r.evidence.line == 2


def test_ftp_step(tmp_path):
    text = ("//J1 JOB (A),'X'\n//F EXEC PGM=FTP,PARM='ftp.example.com (EXIT'\n"
            "//INPUT DD *\nuser pw\n/*\n")
    i = scan_text(tmp_path, text)
    assert ("transfer", "external", "FTP:ftp.example.com") in refs_of(i, "r/J1.jcl#F")


def test_dotted_dd_overrides_proc_dd(tmp_path):
    proc = "//P1 PROC\n//RUN EXEC PGM=X\n//IN DD DSN=OLD.DS,DISP=SHR\n// PEND\n"
    text = "//J1 JOB (A),'X'\n//S1 EXEC P1\n//RUN.IN DD DSN=NEW.DS,DISP=SHR\n"
    i = scan_text(tmp_path, text, extra={"P1.proc": proc})
    refs = refs_of(i, "r/J1.jcl#RUN")
    assert ("read", "dataset", "NEW.DS") in refs and ("read", "dataset", "OLD.DS") not in refs


def test_unknown_proc_is_kept_as_flagged_ref(tmp_path):
    i = scan_text(tmp_path, "//J1 JOB (A),'X'\n//S1 EXEC SYSPROC\n//D DD DSN=A.B,DISP=SHR\n")
    r = one_ref(i, "r/J1.jcl#S1", "runs")
    assert r.target_name is None and "SYSPROC" in r.reason
    assert ("read", "dataset", "A.B") in refs_of(i, "r/J1.jcl#S1")


def test_else_negates_and_nests(tmp_path):
    text = ("//J1 JOB (A),'X'\n// IF (RC = 0) THEN\n//A EXEC PGM=P1\n// ELSE\n//B EXEC PGM=P2\n"
            "// ENDIF\n//C EXEC PGM=P3\n")
    i = scan_text(tmp_path, text)
    assert i.nodes["step:r/J1.jcl#A"].attrs["cond"] == "RC = 0"
    assert i.nodes["step:r/J1.jcl#B"].attrs["cond"] == "NOT (RC = 0)"
    assert i.nodes["step:r/J1.jcl#C"].attrs["cond"] is None


def test_gdg_and_member_forms(tmp_path):
    text = ("//J1 JOB (A),'X'\n//S EXEC PGM=P\n//A DD DSN=P.GDG(-1),DISP=SHR\n"
            "//B DD DSN=P.LIB(MEM),DISP=SHR\n//C DD DSN=P.NEW,DISP=(,CATLG)\n//D DD DUMMY\n")
    i = scan_text(tmp_path, text)
    by = {r.attrs["ddname"]: r for r in step_refs(i, "r/J1.jcl#S") if r.op != "runs"}
    assert by["A"].attrs["gdg"] == "-1" and by["A"].target_name == "P.GDG"
    assert by["B"].target_name == "P.LIB" and by["B"].attrs["gdg"] is None
    assert by["C"].op == "write" and "D" not in by
