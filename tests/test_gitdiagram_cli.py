from __future__ import annotations

import json
import shutil

from archdiag.cli import main
from conftest import ESTATE


def _estate(tmp_path):
    w = tmp_path / "estate"
    shutil.copytree(str(ESTATE), str(w))
    # these tests start with no gitdiagram file; the fixture's own (the release gate's,
    # tests/test_gitdiagram_gate.py) are removed, and a test that wants one writes it
    for f in (w / "architecture-diagrams").glob("gitdiagram-*.json"):
        f.unlink()
    return w


def test_draw_gitdiagram_all_styles_writes_files(tmp_path, capsys):
    w = _estate(tmp_path)
    rc = main(["draw", "--workspace", str(w), "--level", "gitdiagram", "--scope", "claims-batch",
               "--style", "all"])
    out = capsys.readouterr().out
    assert rc == 0, out
    d = w / "architecture-diagrams"
    for style, ext in (("a", "svg"), ("a", "drawio"), ("b", "svg"), ("b", "md"), ("c", "svg"),
                       ("c", "html"), ("d", "svg"), ("d", "excalidraw")):
        assert (d / ("gitdiagram-claims-batch-%s.%s" % (style, ext))).is_file(), (style, ext)
    assert (d / "gitdiagram-claims-batch-links.md").is_file()
    assert "Traceback" not in out
    assert out.index("Wrote:") < out.index("Summary:") < out.index("Top issues:")


def test_draw_default_style_is_b(tmp_path, capsys):
    w = _estate(tmp_path)
    assert main(["draw", "--workspace", str(w), "--level", "gitdiagram",
                 "--scope", "claims-batch"]) == 0
    d = w / "architecture-diagrams"
    assert (d / "gitdiagram-claims-batch-b.svg").is_file()
    assert not (d / "gitdiagram-claims-batch-a.svg").exists()


def test_draw_without_file_uses_folders_and_says_so(tmp_path, capsys):
    w = _estate(tmp_path)
    main(["draw", "--workspace", str(w), "--level", "gitdiagram", "--scope", "claims-batch"])
    out = capsys.readouterr().out
    assert "Grouped by folder. Ask Copilot to name groups for this repo." in out
    assert out.index("Grouped by folder") < out.index("Wrote:")


def test_draw_with_fixture_grouping_file_has_no_fallback(tmp_path, capsys):
    """The fixture's own gitdiagram-claims-batch.json (the release gate's) is used as is:
    no folder-fallback or unusable-file line, only the two files it leaves ungrouped."""
    w = tmp_path / "estate"
    shutil.copytree(str(ESTATE), str(w))
    assert (w / "architecture-diagrams" / "gitdiagram-claims-batch.json").is_file()
    rc = main(["draw", "--workspace", str(w), "--level", "gitdiagram", "--scope", "claims-batch"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Grouped by folder" not in out and "Ask Copilot to name groups" not in out
    assert "couldn't be used" not in out and "folders were used instead" not in out
    assert "Problem in gitdiagram-claims-batch.json" not in out
    assert "Not yet grouped: 2 files" in out
    assert (w / "architecture-diagrams" / "gitdiagram-claims-batch-b.svg").is_file()


def test_unusable_file_says_so(tmp_path, capsys):
    w = _estate(tmp_path)
    (w / "architecture-diagrams" / "gitdiagram-claims-batch.json").write_text(
        "{not json", encoding="utf-8")
    rc = main(["draw", "--workspace", str(w), "--level", "gitdiagram", "--scope", "claims-batch"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Ask Copilot to name groups" not in out
    assert "couldn't be used" in out and "folders were used instead" in out
    assert "Problem in gitdiagram-claims-batch.json:" in out
    assert "Traceback" not in out


def test_not_yet_grouped_line(tmp_path, capsys):
    w = _estate(tmp_path)
    gd = {"repo": "claims-batch", "overview": "x",
          "groups": [{"name": "Only one", "files": ["no/such/path.txt"]}]}
    (w / "architecture-diagrams" / "gitdiagram-claims-batch.json").write_text(
        json.dumps(gd), encoding="utf-8")
    rc = main(["draw", "--workspace", str(w), "--level", "gitdiagram", "--scope", "claims-batch"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Not yet grouped: " in out and "files (see " in out
    assert "gitdiagram-claims-batch-links.md" in out.split("Not yet grouped: ")[1].split("\n")[0]
    assert "Problem in gitdiagram-claims-batch.json:" in out
    assert out.count("Problem in gitdiagram-claims-batch.json:") <= 5
    assert "files not yet grouped" not in out and "file not yet grouped" not in out
    n = out.count("Problem in gitdiagram-claims-batch.json:")
    assert (n < 5) or "... and " in out
    assert "Grouped by folder" not in out
    assert out.index("Not yet grouped:") < out.index("Wrote:")


def test_bad_repo_scope_suggests(tmp_path, capsys):
    w = _estate(tmp_path)
    rc = main(["draw", "--workspace", str(w), "--level", "gitdiagram", "--scope", "claims-bach"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "Did you mean" in out and "claims-batch" in out
    assert "Traceback" not in out


def test_context_command_stdout_clean(tmp_path, capsys):
    w = _estate(tmp_path)
    rc = main(["gitdiagram-context", "--workspace", str(w), "--repo", "claims-batch"])
    cap = capsys.readouterr()
    assert rc == 0
    assert "claims-batch" in cap.out
    for noise in ("No earlier scan", "Scanned:", "Repos changed", "Note:"):
        assert noise not in cap.out
    assert "Scanned:" in cap.err


def test_context_bad_repo(tmp_path, capsys):
    w = _estate(tmp_path)
    rc = main(["gitdiagram-context", "--workspace", str(w), "--repo", "claims-bach"])
    cap = capsys.readouterr()
    assert rc == 2
    assert "Did you mean" in cap.err and "claims-batch" in cap.err
    assert cap.out == ""


def test_cli_never_writes_gitdiagram_file(tmp_path, capsys):
    w = _estate(tmp_path)
    main(["gitdiagram-context", "--workspace", str(w), "--repo", "claims-batch"])
    main(["draw", "--workspace", str(w), "--level", "gitdiagram", "--scope", "claims-batch",
          "--style", "all"])
    main(["draw", "--workspace", str(w), "--level", "gitdiagram", "--scope", "nope"])
    assert not list((w / "architecture-diagrams").glob("gitdiagram-*.json"))


def test_more_than_five_problems_are_summarised(tmp_path, capsys):
    w = _estate(tmp_path)
    gd = {"repo": "claims-batch", "overview": "x",
          "groups": [{"name": "G%d" % i, "files": ["no/such/p%d.txt" % i]} for i in range(8)]}
    (w / "architecture-diagrams" / "gitdiagram-claims-batch.json").write_text(
        json.dumps(gd), encoding="utf-8")
    assert main(["draw", "--workspace", str(w), "--level", "gitdiagram", "--scope", "claims-batch"]) == 0
    out = capsys.readouterr().out
    assert out.count("Problem in gitdiagram-claims-batch.json:") == 5
    assert "... and 3 more (see " in out and "gitdiagram-claims-batch-links.md" in out.split("... and 3 more")[1].split("\n")[0]
    assert "not yet grouped" not in out.replace("Not yet grouped", "")


def test_top_issues_leave_out_the_scheduler_starts_line(tmp_path, capsys):
    """The grey "starts" line is structure, not an issue (Ruling 2): it is never listed under
    "Top issues" as "nothing found at the other end", and never crowds out a real one."""
    w = tmp_path / "estate"
    shutil.copytree(str(ESTATE), str(w))
    rc = main(["draw", "--workspace", str(w), "--level", "gitdiagram", "--scope", "claims-batch"])
    out = capsys.readouterr().out
    assert rc == 0
    issues = out[out.index("Top issues:"):]
    assert "structural" not in issues
    assert "Scheduler ->" not in issues


def test_summary_counts_starts_lines_apart_from_links(tmp_path, capsys):
    """Ruling 10: the grey Scheduler "starts" line is not a link; the total adds up and the
    line is named in its own clause, in stdout and at the top of the links report."""
    w = tmp_path / "estate"
    shutil.copytree(str(ESTATE), str(w))
    assert main(["draw", "--workspace", str(w), "--level", "gitdiagram",
                 "--scope", "claims-batch"]) == 0
    out = capsys.readouterr().out
    assert ("Summary: 11 nodes, 17 links: 13 confirmed, 2 partly known, 2 loose ends; "
            "1 job-structure line\n") in out
    rep = (w / "architecture-diagrams" / "gitdiagram-claims-batch-links.md").read_text("utf-8")
    assert rep.splitlines()[2].endswith("; 1 job-structure line")
    # claims-api has no Scheduler: no clause
    assert main(["draw", "--workspace", str(w), "--level", "gitdiagram",
                 "--scope", "claims-api"]) == 0
    out = capsys.readouterr().out
    assert "job-structure" not in out
    assert "Summary: 12 nodes, 13 links: 7 confirmed, 5 partly known, 1 loose ends\n" in out


def test_group_named_question_mark_draws_every_style(tmp_path, capsys):
    w = _estate(tmp_path)
    (w / "architecture-diagrams" / "gitdiagram-claims-batch.json").write_text(json.dumps(
        {"repo": "claims-batch", "groups": [{"name": "?", "files": ["jcl/"]},
                                            {"name": "??", "files": ["proc/"]}]}),
        encoding="utf-8")
    rc = main(["draw", "--workspace", str(w), "--level", "gitdiagram", "--scope", "claims-batch",
               "--style", "all"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "Traceback" not in out and "Summary:" in out


def test_undrawn_suggested_links_are_problems(tmp_path, capsys):
    """A suggested link the view cannot draw (an entry box the repo does not have, or both
    ends one box) is a problem in the file: printed and listed in the report's section."""
    w = _estate(tmp_path)
    d = w / "architecture-diagrams"
    (d / "gitdiagram-claims-batch.json").write_text(json.dumps(
        {"repo": "claims-batch", "groups": [{"name": "Jobs", "files": ["jcl/", "proc/"]},
                                            {"name": "Code", "files": ["cobol/"]}],
         "suggested_links": [{"from": "CICS transactions", "to": "Code", "note": "n"},
                             {"from": "Jobs", "to": "Jobs", "note": "n"}]}), encoding="utf-8")
    assert main(["draw", "--workspace", str(w), "--level", "gitdiagram",
                 "--scope", "claims-batch"]) == 0
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if "Copilot suggests a link" in ln]
    assert len(lines) == 2, out
    assert all(ln.startswith("Problem in gitdiagram-claims-batch.json: ") for ln in lines), lines
    report = (d / "gitdiagram-claims-batch-links.md").read_text(encoding="utf-8")
    sec = report.split("## Problems in the gitdiagram file")[1]
    assert "CICS transactions → Code" in sec and "Jobs → Jobs" in sec
    assert "Copilot suggests" not in report.split("## Notes")[1].split("## Clickable")[0]


def test_grouping_file_for_a_repo_not_in_the_scan_is_named(tmp_path, capsys):
    w = _estate(tmp_path)
    d = w / "architecture-diagrams"
    (d / "gitdiagram-claims-old.json").write_text('{"groups": []}', encoding="utf-8")
    assert main(["draw", "--workspace", str(w), "--level", "gitdiagram",
                 "--scope", "claims-batch"]) == 0
    out = capsys.readouterr().out
    note = ("Note: gitdiagram-claims-old.json is for a repo that is not in the scan "
            "(claims-old); was it renamed?")
    assert note in out, out
    report = (d / "gitdiagram-claims-batch-links.md").read_text(encoding="utf-8")
    assert "gitdiagram-claims-old.json is for a repo" in report.split("## Notes")[1]
