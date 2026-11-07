"""Silent drops (final review I4): content sniffing past long comment headers, and a
"Not scanned" list in summary.md and every links report for source the scan left out."""
from __future__ import annotations

from archdiag.config import Config
from archdiag.groups import default_groups
from archdiag.render.report import links_report
from archdiag.resolve import resolve
from archdiag.scan import scan_workspace
from archdiag.summary import build_summary
from archdiag.textio import classify
from archdiag.views import build_view

_COMMENTS = "".join("      * header comment line %d\n" % i for i in range(1, 26))


def test_sniff_skips_comment_headers():
    cobol = _COMMENTS + "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PGMTXT.\n"
    assert classify("src/PGMTXT.txt", cobol) == "cobol"
    jcl = "".join("//* comment %d\n" % i for i in range(30)) + "//J1 JOB (A),'X'\n"
    assert classify("jcl/J1", jcl) == "jcl"
    sql = "".join("-- note %d\n" % i for i in range(30)) + "/* block */\n"
    assert classify("x/NOTES", sql + "hello\n") is None
    rexx = "/* REXX */\nsay 'hi'\n"
    assert classify("x/TOOL", rexx) == "rexx"  # a /* REXX */ first line is not a comment


def test_sniff_recognises_identification_division_alone():
    assert classify("x/MEMBER", "       ID DIVISION.\n       DATA DIVISION.\n") == "cobol"
    # A6: a division header with no other part of a program near it is not COBOL; the
    # scan still reports it as mainframe-looking source it could not type
    assert classify("x/MEMBER2", "       IDENTIFICATION DIVISION.\n") is None


def test_lone_division_header_is_reported_not_dropped(tmp_path):
    from archdiag.config import Config
    from archdiag.scan import scan_workspace
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / ".archdiag-repo").write_text("")
    (repo / "MEMBER2").write_text("       IDENTIFICATION DIVISION.\n")
    inv = scan_workspace(tmp_path, Config())
    assert not inv.nodes
    assert [n["path"] for n in inv.not_scanned] == ["MEMBER2"]


def _workspace(tmp_path):
    repo = tmp_path / "r"
    (repo / "src").mkdir(parents=True)
    (repo / ".archdiag-repo").write_text("")
    (repo / "src" / "PGMTXT.txt").write_text(
        _COMMENTS + "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PGMTXT.\n"
        "       PROCEDURE DIVISION.\n           CALL 'PAYCALC'.\n")
    (repo / "build").mkdir()
    (repo / "build" / "PAYCALC.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PAYCALC.\n")
    (repo / "target").mkdir()
    (repo / "target" / "app.class.txt").write_text("not source\n")
    (repo / "src" / "ODD.cntl").write_text("  SORT FIELDS=(1,10,CH,A)\n")
    (repo / "src" / "NOTES.txt").write_text("meeting notes\n")
    export = tmp_path / "zip-export"
    (export / "jcl").mkdir(parents=True)
    (export / "jcl" / "CLMX.jcl").write_text("//CLMX JOB (A),'X'\n//S EXEC PGM=X\n")
    (tmp_path / "empty-folder").mkdir()
    return scan_workspace(tmp_path, Config())


def test_not_scanned_lists_what_the_scan_left_out(tmp_path):
    inv = _workspace(tmp_path)
    assert "program:PGMTXT" in inv.nodes  # found despite 25 comment lines
    got = {(x["repo"], x["path"]): x["reason"] for x in inv.not_scanned}
    assert "build/PAYCALC.cbl" in got[("r", "build")]
    assert ("r", "target") not in got  # nothing that looks like source there
    assert "mainframe" in got[("r", "src/ODD.cntl")]
    assert ("r", "src/NOTES.txt") not in got
    assert "not a repo" in got[("", "zip-export")] and "1 source file" in got[("", "zip-export")]
    assert ("", "empty-folder") not in got


def test_not_scanned_is_in_summary_and_links_report(tmp_path):
    inv = _workspace(tmp_path)
    r = resolve(inv, Config())
    g = default_groups(r)
    text = build_summary(r, g, Config())
    assert "## Not scanned" in text and "zip-export" in text and "build" in text
    report = links_report(build_view(r, g, "landscape", None), r)
    section = report.split("## Not scanned", 1)[1].split("\n## ", 1)[0]
    assert "zip-export" in section and "r/build" in section and "r/src/ODD.cntl" in section


def test_not_scanned_survives_the_cache(tmp_path):
    from archdiag.store import load_resolved, save_json
    inv = _workspace(tmp_path)
    save_json(tmp_path / "links.json", resolve(inv, Config()))
    back = load_resolved(tmp_path / "links.json")
    assert back.inventory.not_scanned == inv.not_scanned
