from __future__ import annotations

import json
import os
import shutil
import sys
import time

import pytest

from archdiag import cli
from archdiag.cli import main
from archdiag.config import load_config
from archdiag.repos import iter_source_files
from archdiag.store import load_inventory
from conftest import ESTATE


def _estate(tmp_path, name="estate"):
    w = tmp_path / name
    shutil.copytree(str(ESTATE), str(w))
    return w


def _drop_config(w):
    cfg = w / "architecture-diagrams" / "archdiag.config.json"
    if cfg.exists():
        cfg.unlink()


def test_draw_all_styles_on_fixture(tmp_path, capsys):
    w = _estate(tmp_path)
    rc = main(["draw", "--workspace", str(w), "--level", "flow", "--scope", "CLMD100",
               "--style", "all"])
    out = capsys.readouterr().out
    assert rc == 0
    d = w / "architecture-diagrams"
    for style, ext in (("a", "svg"), ("a", "drawio"), ("b", "svg"), ("b", "md"), ("c", "svg"),
                       ("c", "html"), ("d", "svg"), ("d", "excalidraw")):
        assert (d / ("flow-clmd100-%s.%s" % (style, ext))).is_file(), (style, ext)
    assert (d / "flow-clmd100-links.md").is_file()
    assert "Traceback" not in out
    tail = out[out.index("Wrote:"):]
    assert "flow-clmd100-a.svg" in tail
    assert "Summary: " in tail and "confirmed" in tail and "loose ends" in tail
    assert tail.index("Summary:") < tail.index("Top issues:")


def test_default_style_per_level(tmp_path):
    w = _estate(tmp_path)
    assert main(["draw", "--workspace", str(w), "--level", "landscape"]) == 0
    assert main(["draw", "--workspace", str(w), "--level", "repomap"]) == 0
    d = w / "architecture-diagrams"
    assert (d / "landscape-b.svg").is_file() and (d / "landscape-b.md").is_file()
    assert (d / "repomap-c.html").is_file() and (d / "landscape-links.md").is_file()


def test_rescan_on_change(tmp_path, capsys):
    w = _estate(tmp_path)
    args = ["draw", "--workspace", str(w), "--level", "flow", "--scope", "CLMD100"]
    assert main(args) == 0
    capsys.readouterr()
    assert main(args) == 0
    assert "rescanned" not in capsys.readouterr().out
    cbl = next(w.rglob("*.cbl"))
    cbl.write_text(cbl.read_text(encoding="utf-8") + "\n      * touched\n", encoding="utf-8")
    assert main(args) == 0
    assert "Repos changed since last scan; rescanned." in capsys.readouterr().out


def test_bad_scope(tmp_path, capsys):
    w = _estate(tmp_path)
    rc = main(["draw", "--workspace", str(w), "--level", "flow", "--scope", "CLMD10"])
    out = capsys.readouterr().out
    assert rc == 2 and "Did you mean: CLMD100" in out and "list --what" in out


def test_bad_level(tmp_path, capsys):
    w = _estate(tmp_path)
    rc = main(["draw", "--workspace", str(w), "--level", "landscpe"])
    out = capsys.readouterr().out
    assert rc == 2 and "Did you mean: landscape" in out


def test_no_repos(tmp_path, capsys):
    assert main(["scan", "--workspace", str(tmp_path)]) == 3
    out = capsys.readouterr().out
    assert ("No git repos found under %s. Clone the repos into one folder and run again."
            % tmp_path) in out
    assert not (tmp_path / "architecture-diagrams").exists()


def test_missing_workspace_not_created(tmp_path, capsys):
    missing = tmp_path / "nope"
    assert main(["scan", "--workspace", str(missing)]) == 3
    assert "No git repos found under" in capsys.readouterr().out
    assert not missing.exists()
    assert main(["draw", "--workspace", str(missing), "--level", "landscape"]) == 3
    assert not missing.exists()


def test_unexpected_error_logged(tmp_path, monkeypatch, capsys):
    w = _estate(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("boom-marker")
    monkeypatch.setattr(cli, "resolve", boom)
    assert main(["scan", "--workspace", str(w)]) == 1
    out = capsys.readouterr()
    log = w / "architecture-diagrams" / "error.log"
    assert log.is_file() and "boom-marker" in log.read_text(encoding="utf-8")
    assert "Traceback" not in out.out + out.err
    assert str(log) in out.out and len(out.out.strip().splitlines()) == 1


def test_path_with_spaces(tmp_path, capsys):
    w = _estate(tmp_path, "client repos")
    assert main(["scan", "--workspace", str(w)]) == 0
    assert main(["draw", "--workspace", str(w), "--level", "application",
                 "--scope", "claims-batch"]) in (0, 2)
    assert main(["draw", "--workspace", str(w), "--level", "landscape"]) == 0
    assert (w / "architecture-diagrams" / "landscape-b.svg").is_file()


def test_init_config(tmp_path, capsys):
    w = _estate(tmp_path)
    _drop_config(w)
    assert main(["scan", "--workspace", str(w)]) == 0
    assert main(["init-config", "--workspace", str(w)]) == 0
    cfg = json.loads((w / "architecture-diagrams" / "archdiag.config.json")
                     .read_text(encoding="utf-8"))
    assert "PROD" in cfg["environment_qualifiers"] and "TEST" in cfg["environment_qualifiers"]


def test_summary_list_and_scan_outputs(tmp_path, capsys):
    w = _estate(tmp_path)
    assert main(["scan", "--workspace", str(w)]) == 0
    assert "repo" in capsys.readouterr().out
    d = w / "architecture-diagrams"
    assert (d / "inventory.json").is_file() and (d / "links.json").is_file()
    assert main(["summary", "--workspace", str(w)]) == 0
    assert "# Architecture scan summary" in capsys.readouterr().out
    assert (d / "summary.md").is_file()
    assert main(["list", "--workspace", str(w), "--what", "jobs"]) == 0
    assert "CLMD100" in capsys.readouterr().out


def test_application_level_draws(tmp_path, capsys):
    w = _estate(tmp_path)
    assert main(["list", "--workspace", str(w), "--what", "applications"]) == 0
    app = [l for l in capsys.readouterr().out.splitlines() if "members)" in l][0].split()[0]
    assert main(["draw", "--workspace", str(w), "--level", "application", "--scope", app]) == 0
    assert any(p.name.startswith("application-") for p in (w / "architecture-diagrams").iterdir())


def test_config_change_reresolves(tmp_path, capsys):
    w = _estate(tmp_path)
    assert main(["scan", "--workspace", str(w)]) == 0
    cfg = w / "architecture-diagrams" / "archdiag.config.json"
    time.sleep(0.05)
    cfg.write_text('{"environment_qualifiers": []}', encoding="utf-8")
    os.utime(str(cfg), (time.time() + 5, time.time() + 5))
    capsys.readouterr()
    assert main(["summary", "--workspace", str(w)]) == 0
    assert "PROD" in capsys.readouterr().out  # candidates reappear once the config is empty


# ---- deferred items: repos / config robustness

def test_skip_dirs_case_insensitive(tmp_path):
    for name in ("Bin", "OBJ", "Target", "Node_modules", "src"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "a.cbl").write_text("x", encoding="utf-8")
    got = sorted(p.parent.name for p in iter_source_files(tmp_path))
    assert got == ["src"]
    got = sorted(p.parent.name for p in iter_source_files(tmp_path, ["SRC"]))
    assert got == []


def test_long_path_is_skipped_not_fatal(tmp_path):
    deep = tmp_path
    while len(str(deep)) < 270:
        deep = deep / ("d" * 40)
    try:
        deep.mkdir(parents=True)
        (deep / "x.cbl").write_text("x", encoding="utf-8")
    except OSError:
        pytest.skip("filesystem cannot make a path this long")
    skipped = []
    assert list(iter_source_files(tmp_path, (), skipped)) == []
    assert skipped and "260" in skipped[0][1]


@pytest.mark.skipif(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="needs POSIX permissions and a non-root user")
def test_unreadable_file_is_recorded_and_scan_continues(tmp_path):
    w = _estate(tmp_path)
    cbl = next(w.rglob("*.cbl"))
    cbl.chmod(0)
    try:
        assert main(["scan", "--workspace", str(w)]) == 0
    finally:
        cbl.chmod(0o644)
    inv = load_inventory(w / "architecture-diagrams" / "inventory.json")
    assert any(cbl.name in s["path"] and "cannot read" in s["reason"] for s in inv.skipped)


def test_malformed_config_uses_defaults(tmp_path, capsys):
    d = tmp_path / "architecture-diagrams"
    d.mkdir()
    for text in ("{not json", "[1, 2]", '"x"', '{"environment_qualifiers": "PROD"}'):
        (d / "archdiag.config.json").write_text(text, encoding="utf-8")
        cfg = load_config(d)
        assert cfg.environment_qualifiers == [] and cfg.exclude_dirs == []
    out = capsys.readouterr().out
    assert out.count("archdiag.config.json is not valid JSON — using defaults") >= 3
