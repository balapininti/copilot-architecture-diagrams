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


def test_called_proc_has_no_standalone_refs(inv):
    assert "proc:claims-batch/proc/CLMPRC.proc" in inv.nodes
    assert not any(r.src.startswith("step:claims-batch/proc/CLMPRC.proc") for r in inv.refs)
    assert not any(r.target_name == "TEST.PAYMENT.FEED" for r in inv.refs)


def test_uncalled_proc_is_flagged_as_defaults(tmp_path):
    proc = "//P1 PROC ENV=TEST\n//RUN EXEC PGM=X\n//IN DD DSN=&ENV..DS,DISP=SHR\n// PEND\n"
    i = scan_text(tmp_path, "//J1 JOB (A),'X'\n//S EXEC PGM=Y\n", extra={"P1.proc": proc})
    r = one_ref(i, "r/P1.proc#RUN", "read")
    assert r.target_name == "TEST.DS" and r.attrs["proc_default"] is True
    assert r.reason == "PROC default values; no caller in these repos"


def test_fixture_step050_reads_the_extract_dataset(inv):
    r = [x for x in step_refs(inv, J100 + "#STEP050") if x.op == "read"]
    assert len(r) == 1 and r[0].target_name == "PROD.CLAIMS.EXTRACT" and r[0].attrs["via"] == "transfer"
    assert r[0].evidence.line == line_of(BATCH / "jcl/CLMD100.jcl", "SNODE=FINANCE")
    t = one_ref(inv, J100 + "#STEP050", "transfer")
    assert t.attrs["remote_dsn"] == "FIN.IN.CLAIMS"
    assert not any(x.op == "write" and x.target_name == "FIN.IN.CLAIMS" for x in inv.refs)


def test_set_is_snapshotted_per_statement(tmp_path):
    text = ("//J1 JOB (A),'X'\n// SET HLQ=DEV\n//S1 EXEC PGM=P\n//A DD DSN=&HLQ..FILE1,DISP=SHR\n"
            "// SET HLQ=PROD\n//S2 EXEC PGM=P\n//B DD DSN=&HLQ..FILE2,DISP=SHR\n")
    i = scan_text(tmp_path, text)
    assert ("read", "dataset", "DEV.FILE1") in refs_of(i, "r/J1.jcl#S1")
    assert ("read", "dataset", "PROD.FILE2") in refs_of(i, "r/J1.jcl#S2")
    assert ("read", "dataset", "PROD.FILE1") not in refs_of(i, "r/J1.jcl#S1")


def test_set_between_dds_of_one_step(tmp_path):
    text = ("//J1 JOB (A),'X'\n// SET H=A\n//S1 EXEC PGM=P\n//D1 DD DSN=&H..X,DISP=SHR\n"
            "// SET H=B\n//D2 DD DSN=&H..X,DISP=SHR\n")
    got = refs_of(scan_text(tmp_path, text), "r/J1.jcl#S1")
    assert ("read", "dataset", "A.X") in got and ("read", "dataset", "B.X") in got


def test_ndm_pull_and_local_to_side(tmp_path):
    text = ("//J1 JOB (A),'X'\n//S EXEC PGM=DMBATCH\n//SYSIN DD *\n"
            "  COPY FROM (SNODE=REMOTE DSN=R.FILE) -\n     TO (DSN=PROD.LOCAL.IN)\n/*\n")
    i = scan_text(tmp_path, text)
    refs = refs_of(i, "r/J1.jcl#S")
    assert ("transfer", "external", "NDM:REMOTE") in refs
    assert ("write", "dataset", "PROD.LOCAL.IN") in refs
    assert one_ref(i, "r/J1.jcl#S", "transfer").attrs["remote_dsn"] == "R.FILE"


def test_ftp_put_and_get_datasets(tmp_path):
    text = ("//J1 JOB (A),'X'\n//F EXEC PGM=FTP\n//INPUT DD *\nhost.example.com\nuser pw\n"
            "put 'PROD.OUT.FILE' out.txt\nget in.txt 'PROD.IN.FILE'\nput local.txt x\n/*\n")
    i = scan_text(tmp_path, text)
    refs = refs_of(i, "r/J1.jcl#F")
    assert ("transfer", "external", "FTP:host.example.com") in refs
    assert ("read", "dataset", "PROD.OUT.FILE") in refs and ("write", "dataset", "PROD.IN.FILE") in refs
    assert not any(r[2] and r[2].lower().startswith("local") for r in refs)


def test_dotted_override_merges_keywords_and_keeps_concatenation(tmp_path):
    proc = ("//P1 PROC\n//RUN EXEC PGM=X\n//IN DD DSN=OLD.DS,DISP=SHR\n// DD DSN=OLD.CONCAT,DISP=SHR\n"
            "//OUT DD DSN=P.OUT,DISP=(NEW,CATLG)\n// PEND\n")
    text = ("//J1 JOB (A),'X'\n//S1 EXEC P1\n//RUN.IN DD DSN=NEW.DS\n//RUN.OUT DD DSN=P.OUT2\n")
    refs = refs_of(scan_text(tmp_path, text, extra={"P1.proc": proc}), "r/J1.jcl#RUN")
    assert ("read", "dataset", "NEW.DS") in refs and ("read", "dataset", "OLD.DS") not in refs
    assert ("read", "dataset", "OLD.CONCAT") in refs
    # DISP comes from the proc DD: no silent switch to write
    assert ("write", "dataset", "P.OUT2") in refs


def test_override_without_disp_keeps_proc_disp(tmp_path):
    proc = "//P1 PROC\n//RUN EXEC PGM=X\n//IN DD DSN=OLD.DS,DISP=SHR\n// PEND\n"
    refs = refs_of(scan_text(tmp_path, "//J1 JOB (A),'X'\n//S1 EXEC P1\n//RUN.IN DD DSN=N.DS\n",
                             extra={"P1.proc": proc}), "r/J1.jcl#RUN")
    assert ("read", "dataset", "N.DS") in refs


def test_unresolved_disp_is_update_with_reason(tmp_path):
    i = scan_text(tmp_path, "//J1 JOB (A),'X'\n//S EXEC PGM=P\n//A DD DSN=A.B,DISP=&MODE\n")
    r = one_ref(i, "r/J1.jcl#S", "update")
    assert r.reason == "symbol &MODE has no value in these repos"


def test_no_disp_is_write_with_visible_none(tmp_path):
    i = scan_text(tmp_path, "//J1 JOB (A),'X'\n//S EXEC PGM=P\n//A DD DSN=A.B\n")
    r = one_ref(i, "r/J1.jcl#S", "write")
    assert r.attrs["disp"] is None


def test_null_proc_default_does_not_shadow_caller_set(tmp_path):
    proc = "//P1 PROC ENV=\n//RUN EXEC PGM=X\n//IN DD DSN=&ENV..DS,DISP=SHR\n// PEND\n"
    text = "//J1 JOB (A),'X'\n// SET ENV=QA\n//S1 EXEC P1\n"
    assert ("read", "dataset", "QA.DS") in refs_of(scan_text(tmp_path, text, extra={"P1.proc": proc}),
                                                     "r/J1.jcl#RUN")


def test_null_proc_default_unset_is_unresolved(tmp_path):
    proc = "//P1 PROC ENV=\n//RUN EXEC PGM=X\n//IN DD DSN=&ENV..DS,DISP=SHR\n// PEND\n"
    i = scan_text(tmp_path, "//J1 JOB (A),'X'\n//S1 EXEC P1\n", extra={"P1.proc": proc})
    r = one_ref(i, "r/J1.jcl#RUN", "read")
    assert r.target_name == "&ENV..DS" and r.reason == "symbol &ENV has no value in these repos"


def test_jobless_jcl_fragment_is_not_scanned_as_job(tmp_path):
    i = scan_text(tmp_path, "//J1 JOB (A),'X'\n// INCLUDE MEMBER=FRAG\n",
                  extra={"FRAG.jcl": "//F1 EXEC PGM=FRAGPGM\n", "LONE.jcl": "//L1 EXEC PGM=LONEPGM\n"})
    assert not any(n.startswith("job:r/FRAG") or n.startswith("job:r/LONE") for n in i.nodes)
    assert "step:r/FRAG.jcl#F1" not in i.nodes and "step:r/LONE.jcl#L1" not in i.nodes
    assert ("runs", "program", "FRAGPGM") in refs_of(i, "r/J1.jcl#F1")


def test_names_are_upper_cased_and_plus_zero_gdg(tmp_path):
    text = "//J1 JOB (A),'X'\n// SET H=prod\n//S EXEC PGM=P\n//A DD DSN=&H..gdg.base(+0),DISP=SHR\n"
    r = one_ref(scan_text(tmp_path, text), "r/J1.jcl#S", "read")
    assert r.target_name == "PROD.GDG.BASE" and r.attrs["gdg"] == "0"


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


# ------------------------------------------------------------------ duplicate PROC names (C1)

def scan_repos(tmp_path, repos):
    """A workspace of several repos: {repo: {relpath: text}}."""
    for repo, files in repos.items():
        root = tmp_path / repo
        root.mkdir()
        (root / ".archdiag-repo").write_text("")
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
    return scan_workspace(tmp_path, Config())


_PROC_A = "//MYPROC  PROC\n//S1      EXEC PGM=AAAPGM\n//IN      DD DSN=AAA.IN,DISP=SHR\n"
_PROC_B = "//MYPROC  PROC\n//S1      EXEC PGM=BBBPGM\n//IN      DD DSN=BBB.IN,DISP=SHR\n"
_JOB = "//JOBX    JOB (ACCT),'X'\n//STEP1   EXEC MYPROC\n"


def test_duplicate_proc_prefers_the_jobs_own_repo(tmp_path):
    i = scan_repos(tmp_path, {"aaa": {"proc/MYPROC.proc": _PROC_A},
                              "bbb": {"proc/MYPROC.proc": _PROC_B, "jcl/JOBB.jcl": _JOB}})
    refs = step_refs(i, "bbb/jcl/JOBB.jcl#S1")
    assert {(r.op, r.target_name) for r in refs} == {("runs", "BBBPGM"), ("read", "BBB.IN")}
    assert all(r.reason is None for r in refs)
    assert all(r.evidence.repo == "bbb" for r in refs)


def test_duplicate_proc_elsewhere_is_ambiguous(tmp_path):
    i = scan_repos(tmp_path, {"aaa": {"proc/MYPROC.proc": _PROC_A},
                              "bbb": {"proc/MYPROC.proc": _PROC_B},
                              "ccc": {"jcl/JOBC.jcl": _JOB}})
    refs = step_refs(i, "ccc/jcl/JOBC.jcl#S1")
    assert refs
    for r in refs:
        assert r.reason and r.reason.startswith("ambiguous: PROC MYPROC defined in 2 places")
        assert "aaa/proc/MYPROC.proc" in r.reason and "bbb/proc/MYPROC.proc" in r.reason


def test_duplicate_proc_in_own_repo_is_ambiguous(tmp_path):
    i = scan_repos(tmp_path, {"bbb": {"proc/MYPROC.proc": _PROC_B, "stage/MYPROC.proc": _PROC_A,
                                      "jcl/JOBB.jcl": _JOB}})
    refs = step_refs(i, "bbb/jcl/JOBB.jcl#S1")
    assert refs and all(r.reason and "ambiguous: PROC MYPROC defined in 2 places" in r.reason
                        for r in refs)


def test_identical_proc_copies_are_not_ambiguous(tmp_path):
    i = scan_repos(tmp_path, {"aaa": {"proc/MYPROC.proc": _PROC_B},
                              "bbb": {"proc/MYPROC.proc": _PROC_B},
                              "ccc": {"jcl/JOBC.jcl": _JOB}})
    refs = step_refs(i, "ccc/jcl/JOBC.jcl#S1")
    assert {(r.op, r.target_name) for r in refs} == {("runs", "BBBPGM"), ("read", "BBB.IN")}
    assert all(r.reason is None for r in refs)


def test_other_repos_proc_not_chosen_by_a_caller_is_still_scanned(tmp_path):
    # bbb's job uses bbb's PROC, so aaa's MYPROC has no caller: its steps are not dropped
    i = scan_repos(tmp_path, {"aaa": {"proc/MYPROC.proc": _PROC_A},
                              "bbb": {"proc/MYPROC.proc": _PROC_B, "jcl/JOBB.jcl": _JOB}})
    got = {(r.op, r.target_name) for r in i.refs if r.src.startswith("step:aaa/")}
    assert ("runs", "AAAPGM") in got and ("read", "AAA.IN") in got
    assert all(r.attrs.get("proc_default") for r in i.refs if r.src.startswith("step:aaa/"))


def test_java_and_ts_files_starting_with_slashes_are_not_procs(tmp_path):
    java = "// MYPROC helper\npackage x;\nclass MYPROC {}\n"
    ts = "// INCMEM\nexport const x = 1;\n"
    job = "//JOBX    JOB (ACCT),'X'\n//STEP1   EXEC MYPROC\n// INCLUDE MEMBER=INCMEM\n"
    i = scan_repos(tmp_path, {"r": {"src/MYPROC.java": java, "src/INCMEM.ts": ts,
                                    "jcl/JOBX.jcl": job}})
    r = one_ref(i, "r/jcl/JOBX.jcl#STEP1", "runs")
    assert r.target_name is None and "PROC MYPROC is not in these repos" in r.reason


# ------------------------------------------------------------------ IDCAMS control statements (I9)

def test_idcams_repro_define_delete(tmp_path):
    text = ("//J1 JOB (A),'X'\n//S1 EXEC PGM=IDCAMS\n"
            "//IN DD DSN=CLM.SRC,DISP=OLD\n//OUT DD DSN=CLM.TGT,DISP=OLD\n"
            "//SYSIN DD *\n"
            "  DELETE CLM.KSDS CLUSTER PURGE\n"
            "  DEFINE CLUSTER (NAME(CLM.KSDS) INDEXED -\n"
            "         KEYS(10 0)) DATA (NAME(CLM.KSDS.DATA))\n"
            "  REPRO INDATASET(CLM.FLAT) OUTDATASET(CLM.KSDS)\n"
            "  REPRO INFILE(IN) OUTFILE(OUT)\n"
            "  REPRO IDS(CLM.A) ODS(CLM.B) /* short forms */\n"
            "/*\n")
    i = scan_text(tmp_path, text)
    got = refs_of(i, "r/J1.jcl#S1")
    assert {("read", "dataset", "CLM.FLAT"), ("write", "dataset", "CLM.KSDS"),
            ("delete", "dataset", "CLM.KSDS"), ("read", "dataset", "CLM.A"),
            ("write", "dataset", "CLM.B"), ("read", "dataset", "CLM.SRC"),
            ("write", "dataset", "CLM.TGT")} <= got
    assert ("write", "dataset", "CLM.KSDS.DATA") not in got
    assert ("update", "dataset", "CLM.SRC") not in got  # INFILE says it is read
    rep = [r for r in step_refs(i, "r/J1.jcl#S1") if r.target_name == "CLM.FLAT"][0]
    assert rep.evidence.line == 9 and "INDATASET" in rep.evidence.text


# ------------------------------------------------------------------ Batch A fixes

_INSTREAM_JOB = ("//JOBX    JOB (ACCT),'X'\n//MYPROC  PROC\n//S1      EXEC PGM=LOCPGM\n"
                 "//IN      DD DSN=LOC.IN,DISP=SHR\n//        PEND\n//STEP1   EXEC MYPROC\n")


def test_instream_proc_call_does_not_mark_a_cataloged_proc_called(tmp_path):
    # A1: bbb's job runs its own in-stream MYPROC; aaa's cataloged MYPROC has no caller
    i = scan_repos(tmp_path, {"aaa": {"proc/MYPROC.proc": _PROC_A},
                              "bbb": {"jcl/JOBB.jcl": _INSTREAM_JOB}})
    got = {(r.op, r.target_name) for r in i.refs if r.src.startswith("step:aaa/")}
    assert ("runs", "AAAPGM") in got and ("read", "AAA.IN") in got
    for r in i.refs:
        if r.src.startswith("step:aaa/"):
            assert r.attrs.get("proc_default") and "no caller in these repos" in r.reason
    job = {(r.op, r.target_name) for r in step_refs(i, "bbb/jcl/JOBB.jcl#S1")}
    assert job == {("runs", "LOCPGM"), ("read", "LOC.IN")}


_JCLLIB_JOB = ("//JOBX    JOB (ACCT),'X'\n//LIBS    JCLLIB ORDER=(PROD.PROCLIB,'SYS1.PROCLIB')\n"
               "//STEP1   EXEC MYPROC\n")


def test_jcllib_order_with_proc_from_another_repo_is_partial(tmp_path):
    # A2
    i = scan_repos(tmp_path, {"aaa": {"proc/MYPROC.proc": _PROC_A},
                              "bbb": {"jcl/JOBB.jcl": _JCLLIB_JOB}})
    refs = step_refs(i, "bbb/jcl/JOBB.jcl#S1")
    assert {(r.op, r.target_name) for r in refs} == {("runs", "AAAPGM"), ("read", "AAA.IN")}
    for r in refs:
        assert r.reason and ("JCLLIB ORDER not mapped to repos; PROC MYPROC taken from "
                             "aaa/proc/MYPROC.proc") in r.reason
    assert i.nodes["job:bbb/jcl/JOBB.jcl"].attrs["jcllib"] == ["PROD.PROCLIB", "SYS1.PROCLIB"]
    assert i.nodes["step:bbb/jcl/JOBB.jcl#S1"].attrs["jcllib"] == ["PROD.PROCLIB",
                                                                   "SYS1.PROCLIB"]


def test_jcllib_order_with_proc_in_own_repo_stays_certain(tmp_path):
    i = scan_repos(tmp_path, {"bbb": {"proc/MYPROC.proc": _PROC_B,
                                      "jcl/JOBB.jcl": _JCLLIB_JOB.replace("ORDER=(PROD.PROCLIB,'SYS1.PROCLIB')", "ORDER=PROD.PROCLIB")}})
    refs = step_refs(i, "bbb/jcl/JOBB.jcl#S1")
    assert refs and all(r.reason is None for r in refs)
    assert i.nodes["job:bbb/jcl/JOBB.jcl"].attrs["jcllib"] == ["PROD.PROCLIB"]


def test_jcllib_order_with_include_from_another_repo_is_partial(tmp_path):
    inc = "//S9      EXEC PGM=INCPGM\n"
    job = _JCLLIB_JOB.replace("//STEP1   EXEC MYPROC\n", "//        INCLUDE MEMBER=INCMEM\n")
    i = scan_repos(tmp_path, {"aaa": {"jcl/INCMEM": inc}, "bbb": {"jcl/JOBB.jcl": job}})
    r = one_ref(i, "bbb/jcl/JOBB.jcl#S9", "runs")
    assert r.target_name == "INCPGM"
    assert "JCLLIB ORDER not mapped to repos; INCLUDE member INCMEM taken from aaa/jcl/INCMEM" \
        in r.reason


_IDC_JOB = ("//J1      JOB (A),'X'\n//S1      EXEC PGM=IDCAMS\n"
            "//SYSIN   DD DSN=CTL.CNTLLIB(IDCDEF),DISP=SHR\n")
_IDC_CARDS = ("  DELETE CLM.KSDS CLUSTER PURGE\n"
              "  DEFINE CLUSTER (NAME(CLM.KSDS) INDEXED -\n"
              "         KEYS(10 0))\n"
              "  REPRO INDATASET(CLM.FLAT) OUTDATASET(CLM.KSDS)\n")


def test_idcams_sysin_member_in_the_repo_is_read(tmp_path):
    # A3: the control statements live in a file named after the member
    i = scan_repos(tmp_path, {"r": {"jcl/J1.jcl": _IDC_JOB, "cntl/IDCDEF": _IDC_CARDS}})
    refs = step_refs(i, "r/jcl/J1.jcl#S1")
    got = {(r.op, r.target_name) for r in refs}
    assert {("delete", "CLM.KSDS"), ("write", "CLM.KSDS"), ("read", "CLM.FLAT")} <= got
    flat = [r for r in refs if r.target_name == "CLM.FLAT"][0]
    assert (flat.evidence.repo, flat.evidence.path, flat.evidence.line) == ("r", "cntl/IDCDEF", 4)
    assert "INDATASET" in flat.evidence.text and flat.reason is None
    assert not any(r.target_name is None and r.op != "runs" for r in refs)
    assert not any(n["path"] == "cntl/IDCDEF" for n in i.not_scanned)


def test_idcams_sysin_member_found_once_in_another_repo_is_read(tmp_path):
    i = scan_repos(tmp_path, {"r": {"jcl/J1.jcl": _IDC_JOB},
                              "s": {"cntl/IDCDEF.cntl": _IDC_CARDS}})
    flat = [r for r in step_refs(i, "r/jcl/J1.jcl#S1") if r.target_name == "CLM.FLAT"][0]
    assert (flat.evidence.repo, flat.evidence.path) == ("s", "cntl/IDCDEF.cntl")


def test_idcams_sysin_dataset_not_in_the_repos_is_a_partial_note(tmp_path):
    i = scan_repos(tmp_path, {"r": {"jcl/J1.jcl": _IDC_JOB}})
    notes = [r for r in step_refs(i, "r/jcl/J1.jcl#S1") if r.target_name is None]
    assert len(notes) == 1
    assert notes[0].reason == "IDCAMS control statements in CTL.CNTLLIB(IDCDEF) not in these repos"
    assert notes[0].evidence.line == 3


def test_idcams_sysin_member_in_two_other_repos_is_a_partial_note(tmp_path):
    i = scan_repos(tmp_path, {"r": {"jcl/J1.jcl": _IDC_JOB},
                              "s": {"cntl/IDCDEF": _IDC_CARDS},
                              "t": {"cntl/IDCDEF": "  DELETE OTHER.KSDS\n"}})
    refs = step_refs(i, "r/jcl/J1.jcl#S1")
    notes = [r for r in refs if r.target_name is None]
    assert len(notes) == 1 and "found in 2 places" in notes[0].reason
    assert "s/cntl/IDCDEF" in notes[0].reason and "t/cntl/IDCDEF" in notes[0].reason
    assert not any(r.target_name in ("CLM.FLAT", "OTHER.KSDS") for r in refs)
