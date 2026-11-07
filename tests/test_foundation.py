from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from stdlib39 import STDLIB_39

from archdiag.cli import main
from archdiag.config import load_config
from archdiag.model import Edge, Evidence, Inventory, Node, Ref, Repo, Resolved
from archdiag.repos import discover_repos, iter_source_files
from archdiag.store import load_inventory, load_resolved, save_json
from archdiag.textio import classify, read_source

import dataclasses

SCRIPTS = Path(__file__).resolve().parent.parent / "skill" / "architecture-diagrams" / "scripts"


def test_single_repo_when_workspace_is_git(tmp_path):
    (tmp_path / ".git").mkdir()
    assert [r.path for r in discover_repos(tmp_path)] == ["."]


def test_child_repos(tmp_path):
    for n in ("b-repo", "a repo"):
        (tmp_path / n / ".git").mkdir(parents=True)
    (tmp_path / "notes").mkdir()
    assert [r.name for r in discover_repos(tmp_path)] == ["a repo", "b-repo"]


def test_read_source_falls_back_and_normalizes(tmp_path):
    p = tmp_path / "X.cbl"
    p.write_bytes("      * caf\xe9\r\n".encode("cp1252"))
    assert read_source(p) == "      * café\n"


def test_read_source_never_crashes_on_bad_bytes(tmp_path):
    p = tmp_path / "X.bin"
    p.write_bytes(b"\x81\x8d\xff\xfe abc")
    assert "abc" in read_source(p)


def test_skips_non_source(tmp_path):
    for rel in (".git/HEAD", "node_modules/a.ts", "target/A.class", "bin/x.jar",
                "img/a.png", "src/A.java"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    assert [p.relative_to(tmp_path).as_posix() for p in iter_source_files(tmp_path)] == ["src/A.java"]


def test_skips_big_files(tmp_path):
    (tmp_path / "big.txt").write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    (tmp_path / "ok.txt").write_text("x")
    assert [p.name for p in iter_source_files(tmp_path)] == ["ok.txt"]


def test_classify_by_content_without_extension():
    assert classify("cobol.pds/CLMB400", "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CLMB400.\n") == "cobol"
    assert classify("jcl.pds/CLMD300", "//CLMD300 JOB (ACCT),'X'\n") == "jcl"
    assert classify("x/README", "hello") is None


def test_classify_by_extension_and_proc_sniff():
    assert classify("a/B.cpy", "") == "copybook"
    assert classify("a/B.yml", "") == "yaml"
    assert classify("a/B.ts", "") == "angular_ts"
    assert classify("a/zosconnect/thing.json", "{}") == "zosconnect"
    assert classify("p/MYPROC", "//MYPROC PROC\n") == "proc"
    assert classify("p/R", "/* REXX */\nsay 1\n") == "rexx"
    assert classify("p/P", "X: PROCEDURE OPTIONS(MAIN);\n") == "pli"
    assert classify("p/M", "MAP1 DFHMSD TYPE=MAP\n") == "bms"
    assert classify("p/A", "SUB CSECT\n") == "asm"


def test_stdlib_list_is_the_fixed_3_9_one():
    assert len(STDLIB_39) > 200
    assert {"os", "json", "dataclasses", "zoneinfo", "graphlib", "asyncore", "distutils"} <= STDLIB_39
    # E10: 3.9 public modules missing from the macOS build (Windows/Linux only, or removed
    # since 3.13) are listed too
    assert {"msilib", "spwd", "ossaudiodev", "xxlimited"} <= STDLIB_39
    assert not {"tomllib", "annotationlib", "compression", "_colorize", "yaml", "setuptools"} & STDLIB_39
    assert all(n == n.strip() and "." not in n for n in STDLIB_39)


def test_runtime_imports_are_stdlib_only():
    files = list((SCRIPTS / "archdiag").rglob("*.py")) + [SCRIPTS / "run.py"]
    assert files
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"), feature_version=(3, 9))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for n in names:
                assert n == "archdiag" or n in STDLIB_39, "%s imports %s" % (f, n)


def test_cli_scan_writes_inventory(tmp_path):
    (tmp_path / "r" / ".git").mkdir(parents=True)
    assert main(["scan", "--workspace", str(tmp_path)]) == 0
    inv = tmp_path / "architecture-diagrams" / "inventory.json"
    assert inv.exists()
    loaded = load_inventory(inv)
    assert [r.name for r in loaded.repos] == ["r"]
    assert loaded.nodes == {} and loaded.refs == []


def test_config_defaults_and_load(tmp_path):
    assert load_config(tmp_path).environment_qualifiers == []
    (tmp_path / "archdiag.config.json").write_text(
        json.dumps({"environment_qualifiers": ["PROD"], "exclude_dirs": ["old"]}))
    c = load_config(tmp_path)
    assert c.environment_qualifiers == ["PROD"] and c.exclude_dirs == ["old"]


def test_inventory_and_resolved_round_trip(tmp_path):
    ev = Evidence("r", "a/B.cbl", 3, "CALL 'X'")
    n = Node("program:B", "program", "B", "r", [ev], {"k": 1})
    ref = Ref("program:B", "calls", "program", "X", ev, reason="r", candidates=["program:X"], attrs={"a": 1})
    inv = Inventory("ws", [Repo("r", ".")], {n.id: n}, [ref], "fp", {"asm": 2})
    res = Resolved(inv, {n.id: n}, [Edge("program:B", "calls", "program:X", "partial", "why", [ev])])
    save_json(tmp_path / "i.json", inv)
    save_json(tmp_path / "r.json", res)
    assert load_inventory(tmp_path / "i.json") == inv
    assert load_resolved(tmp_path / "r.json") == res


def test_marker_file_makes_a_repo(tmp_path):
    (tmp_path / "r1").mkdir()
    (tmp_path / "r1" / ".archdiag-repo").write_text("")
    (tmp_path / "plain").mkdir()
    assert [r.name for r in discover_repos(tmp_path)] == ["r1"]
    (tmp_path / ".archdiag-repo").write_text("")
    assert [r.path for r in discover_repos(tmp_path)] == ["."]


def test_comment_lines_are_not_job_or_proc_cards():
    assert classify("x/README", "//* JOB TO RUN NIGHTLY\n//* MYPROC PROC\n") is None
    assert classify("x/J", "//* header\n//MYJOB JOB (A),'X'\n") == "jcl"


# ------------------------------------------------------------------ Batch A fixes (A6)

def test_prose_mentioning_cobol_divisions_is_not_cobol():
    prose = ("Design notes\n\nEvery program starts with the IDENTIFICATION DIVISION and the\n"
             "PROGRAM-ID paragraph names it; the DATA DIVISION holds the records.\n")
    assert classify("docs/notes.txt", prose) is None
    assert classify("docs/NOTES", prose) is None
    # a header that looks like code, but nothing else of a program near it
    assert classify("docs/notes.txt", "IDENTIFICATION DIVISION.\nis the first part.\n") is None
    assert classify("docs/notes.txt", "  PROGRAM-ID. is where the name goes\n") is None


def test_code_shaped_divisions_are_cobol():
    fixed = ("000100 IDENTIFICATION DIVISION.\n000200 PROGRAM-ID. P1.\n"
             "000300 PROCEDURE DIVISION.\n000400     GOBACK.\n")
    assert classify("src/P1.txt", fixed) == "cobol"
    free = "IDENTIFICATION DIVISION.\nPROGRAM-ID. P2.\nPROCEDURE DIVISION.\n    GOBACK.\n"
    assert classify("src/P2", free) == "cobol"
    no_id = ("       ID DIVISION.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
             "       01  WS-A PIC X.\n")
    assert classify("src/P3", no_id) == "cobol"
    only_progid = "       PROGRAM-ID. P4.\n       PROCEDURE DIVISION.\n           GOBACK.\n"
    assert classify("src/P4", only_progid) == "cobol"


def test_numbered_list_prose_is_not_cobol():
    # review of A6: "Step 1" / "1. The" in columns 1-6 are not a sequence area
    steps = ("Step 1 IDENTIFICATION DIVISION. names the program\n"
             "Step 2 DATA DIVISION holds records\n"
             "Then   CALL 'PROSEPGM' is how programs call.\n")
    listed = ("1. The IDENTIFICATION DIVISION. comes first.\n"
              "2. The PROCEDURE DIVISION has the code.\n")
    assert classify("docs/notes.txt", steps) is None
    assert classify("docs/list.txt", listed) is None
    assert classify("docs/LIST", listed) is None
    # a real alphanumeric sequence area still counts
    assert classify("src/P5", "PRG001 IDENTIFICATION DIVISION.\nPRG002 PROGRAM-ID. P5.\n") \
        == "cobol"


def test_tab_indented_cobol_member_is_cobol(tmp_path):
    from archdiag.config import Config
    from archdiag.scan import scan_workspace
    text = ("\tIDENTIFICATION DIVISION.\n\tPROGRAM-ID. TABBED.\n\tPROCEDURE DIVISION.\n"
            "\t    CALL 'TABSUB'.\n")
    assert classify("src/TABBED", text) == "cobol"
    repo = tmp_path / "r"
    (repo / "src").mkdir(parents=True)
    (repo / ".archdiag-repo").write_text("")
    (repo / "src" / "TABBED").write_text(text)
    inv = scan_workspace(tmp_path, Config())
    assert any(r.src == "program:TABBED" and r.target_name == "TABSUB" for r in inv.refs)


def test_tab_indented_mainframe_text_is_reported_when_untyped(tmp_path):
    from archdiag.config import Config
    from archdiag.scan import scan_workspace
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / ".archdiag-repo").write_text("")
    (repo / "MEMBER").write_text("\tPROCEDURE DIVISION.\n\t    CALL 'X'.\n")
    inv = scan_workspace(tmp_path, Config())
    assert [n["path"] for n in inv.not_scanned] == ["MEMBER"]


# ------------------------------------------------------------------ B12: any 6-char sequence area

_SEQ6 = ("PRGABC IDENTIFICATION DIVISION.\n"
         "PRGABC PROGRAM-ID. P6.\n"
         "PRGABC*A COMMENT LINE\n"
         "PRGABC PROCEDURE DIVISION.\n"
         "PRGABC     CALL 'SUB6'.\n"
         "PRGABC     GOBACK.\n")


def test_b12_any_six_char_sequence_area_when_strongly_cobol(tmp_path):
    assert classify("src/P6", _SEQ6) == "cobol"
    punct = _SEQ6.replace("PRGABC", "AB-123")
    assert classify("src/P7", punct) == "cobol"
    from archdiag.config import Config
    from archdiag.scan import scan_workspace
    repo = tmp_path / "r"
    (repo / "src").mkdir(parents=True)
    (repo / ".archdiag-repo").write_text("")
    (repo / "src" / "P6").write_text(_SEQ6)
    inv = scan_workspace(tmp_path, Config())
    assert "program:P6" in inv.nodes
    assert any(r.src == "program:P6" and r.target_name == "SUB6" for r in inv.refs)


def test_b12_six_char_area_needs_the_whole_file_cobol_shaped():
    # one line with a 6-char area is not enough; prose lines stay prose
    mixed = ("PRGABC IDENTIFICATION DIVISION.\nsome prose follows here and more\n"
             "PRGABC PROGRAM-ID. P8.\nanother line of prose without code\n"
             "and a third line of prose here\n")
    assert classify("src/P8", mixed) is None
    # the alnum-with-digit branch is exactly six characters
    assert classify("src/P9", "PRG0012 IDENTIFICATION DIVISION.\nPRG0012 PROGRAM-ID. P9.\n") \
        is None


def test_b12_not_scanned_reasons_are_specific(tmp_path):
    from archdiag.config import Config
    from archdiag.scan import scan_workspace
    repo = tmp_path / "r"
    (repo / "docs").mkdir(parents=True)
    (repo / ".archdiag-repo").write_text("")
    (repo / "docs" / "notes.txt").write_text(
        "Step 1 IDENTIFICATION DIVISION. names the program\nStep 2 DATA DIVISION holds it\n")
    (repo / "MEMBER2").write_text("       IDENTIFICATION DIVISION.\n")
    inv = scan_workspace(tmp_path, Config())
    why = {n["path"]: n["reason"] for n in inv.not_scanned}
    assert why["docs/notes.txt"].startswith("prose mentioning COBOL divisions")
    assert why["MEMBER2"].startswith("looks like COBOL but its type was not recognised")


def test_fix2_six_letter_word_prose_is_not_cobol():
    prose = ("Before PROGRAM-ID. YOU write the header\n"
             "Within PROCEDURE DIVISION the code goes\n"
             "Notice that IDENTIFICATION DIVISION. comes first\n"
             "Always DATA DIVISION after it\n"
             "Except when nested programs are used\n")
    assert classify("docs/NOTES", prose) is None
    steps = ("Step01 IDENTIFICATION DIVISION. names the program\n"
             "Step02 DATA DIVISION holds records\n"
             "and some more prose follows here\n")
    assert classify("docs/STEPS", steps) is None
    # a real lettered area with code still counts
    assert classify("src/P5", "PRG001 IDENTIFICATION DIVISION.\nPRG002 PROGRAM-ID. P5.\n") \
        == "cobol"


def test_fix3_prose_starting_with_a_division_name_is_prose(tmp_path):
    from archdiag.config import Config
    from archdiag.scan import scan_workspace
    from archdiag.textio import unscanned_reason
    assert unscanned_reason("Data division holds the records of the program\n") \
        .startswith("prose mentioning COBOL divisions")
    assert unscanned_reason("       DATA DIVISION.\n").startswith("looks like COBOL")
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / ".archdiag-repo").write_text("")
    (repo / "NOTES").write_text("Before PROGRAM-ID. YOU write the header\n"
                                "Within PROCEDURE DIVISION the code goes\n"
                                "Notice that IDENTIFICATION DIVISION. comes\n")
    inv = scan_workspace(tmp_path, Config())
    assert "program:YOU" not in inv.nodes
