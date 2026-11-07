"""Fingerprint (cache validity), exclude_dirs and the not-analyzed language counts."""
from __future__ import annotations

import os

from archdiag.config import Config
from archdiag.repos import discover_repos, iter_source_files
from archdiag.scan import scan_workspace
from archdiag.store import fingerprint


def _ws(tmp_path):
    r = tmp_path / "r"
    (r / ".git").mkdir(parents=True)
    (r / "a").mkdir()
    (r / "a" / "X.cbl").write_text("       PROGRAM-ID. X.\n", encoding="utf-8")
    (r / "old").mkdir()
    (r / "old" / "Y.cbl").write_text("       PROGRAM-ID. Y.\n", encoding="utf-8")
    return tmp_path


def _fp(ws, cfg=None):
    return fingerprint(ws, discover_repos(ws), cfg)


def test_fingerprint_is_deterministic(tmp_path):
    ws = _ws(tmp_path)
    assert _fp(ws) == _fp(ws) == _fp(ws, Config())
    assert len(_fp(ws)) == 40


def test_fingerprint_changes_when_a_file_changes_is_added_or_removed(tmp_path):
    ws = _ws(tmp_path)
    base = _fp(ws)
    x = ws / "r" / "a" / "X.cbl"
    x.write_text("       PROGRAM-ID. X.\n       STOP RUN.\n", encoding="utf-8")  # size
    after_edit = _fp(ws)
    assert after_edit != base
    st = x.stat()
    os.utime(str(x), ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))  # mtime only
    after_touch = _fp(ws)
    assert after_touch != after_edit
    (ws / "r" / "a" / "Z.cbl").write_text("       PROGRAM-ID. Z.\n", encoding="utf-8")
    after_add = _fp(ws)
    assert after_add != after_touch
    (ws / "r" / "a" / "Z.cbl").unlink()
    assert _fp(ws) == after_touch
    (ws / "r" / "a" / "X.cbl").rename(ws / "r" / "a" / "W.cbl")
    assert _fp(ws) != after_touch


def test_fingerprint_ignores_unreadable_kinds_and_skipped_folders(tmp_path):
    ws = _ws(tmp_path)
    base = _fp(ws)
    (ws / "r" / "node_modules").mkdir()
    (ws / "r" / "node_modules" / "m.js").write_text("x", encoding="utf-8")
    (ws / "r" / "pic.png").write_bytes(b"\x89PNG")
    assert _fp(ws) == base


def test_exclude_dirs_drop_folders_from_walk_and_fingerprint(tmp_path):
    ws = _ws(tmp_path)
    root = ws / "r"
    names = lambda ex: sorted(p.name for p in iter_source_files(root, ex))  # noqa: E731
    assert names(()) == ["X.cbl", "Y.cbl"]
    assert names(["old"]) == ["X.cbl"]
    assert names(["OLD"]) == ["X.cbl"]  # case-insensitive, like the default skips
    cfg = Config(exclude_dirs=["old"])
    base = _fp(ws, cfg)
    assert base != _fp(ws)
    (root / "old" / "Y.cbl").write_text("       PROGRAM-ID. YY.\n       STOP RUN.\n", encoding="utf-8")
    assert _fp(ws, cfg) == base  # a change in an excluded folder does not invalidate the cache
    assert _fp(ws) != base
    inv = scan_workspace(ws, cfg)
    assert "program:Y" not in inv.nodes and "program:X" in inv.nodes


def test_languages_not_analyzed_counts_files_per_language(tmp_path):
    ws = _ws(tmp_path)
    r = ws / "r" / "asm"
    r.mkdir()
    (r / "A1.asm").write_text("A1       CSECT\n         END\n", encoding="utf-8")
    (r / "A2.asm").write_text("A2       CSECT\n         END\n", encoding="utf-8")
    (r / "M1.mac").write_text("         MACRO\n", encoding="utf-8")
    (r / "P1.pli").write_text("P1: PROC OPTIONS(MAIN);\nEND P1;\n", encoding="utf-8")
    (r / "R1.rexx").write_text("/* REXX */\nsay 1\n", encoding="utf-8")
    inv = scan_workspace(ws, Config())
    # every file of these languages is counted (the .mac macro too, though it names no program)
    assert inv.languages_not_analyzed == {"asm": 3, "pli": 1, "rexx": 1}
    assert sorted(k for k in inv.nodes if k.startswith("notanalyzed:")) == [
        "notanalyzed:A1", "notanalyzed:A2", "notanalyzed:P1", "notanalyzed:R1"]
    assert scan_workspace(_ws_plain(tmp_path / "other"), Config()).languages_not_analyzed == {}


def _ws_plain(path):
    path.mkdir()
    return _ws(path)
