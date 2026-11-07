from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from archdiag.cli import main
from archdiag.config import load_config
from archdiag.model import Edge, Evidence, Inventory, Node, Ref, Repo, Resolved
from archdiag.repos import discover_repos, iter_source_files
from archdiag.store import load_inventory, load_resolved, save_json
from archdiag.textio import classify, read_source

import dataclasses

SCRIPTS = Path(__file__).resolve().parent.parent / "skill" / "architecture-diagrams" / "scripts"

STDLIB_39 = {
    "__future__", "argparse", "ast", "collections", "contextlib", "copy", "dataclasses",
    "datetime", "difflib", "enum", "fnmatch", "functools", "hashlib", "html", "io",
    "itertools", "json", "math", "os", "pathlib", "random", "re", "shutil", "string",
    "sys", "textwrap", "time", "typing", "unicodedata", "urllib", "xml", "zipfile",
}


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


def test_runtime_imports_are_stdlib_only():
    files = list((SCRIPTS / "archdiag").rglob("*.py"))
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
