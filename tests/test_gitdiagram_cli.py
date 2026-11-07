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
