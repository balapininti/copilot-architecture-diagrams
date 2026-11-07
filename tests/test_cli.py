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


def test_long_path_is_read_on_posix(tmp_path):
    deep = tmp_path
    while len(str(deep)) < 270:
        deep = deep / ("d" * 40)
    try:
        deep.mkdir(parents=True)
        (deep / "x.cbl").write_text("x", encoding="utf-8")
    except OSError:
        pytest.skip("filesystem cannot make a path this long")
    skipped = []
    got = list(iter_source_files(tmp_path, (), skipped))
    assert [p.name for p in got] == ["x.cbl"] and skipped == []
    from archdiag.textio import read_source
    assert read_source(got[0]) == "x"


def test_extended_path_helper():
    from archdiag.repos import extended_path
    ident = lambda p: p  # noqa: E731
    assert extended_path("C:\\work\\a.cbl", ident) == "\\\\?\\C:\\work\\a.cbl"
    assert extended_path("\\\\srv\\share\\a.cbl", ident) == "\\\\?\\UNC\\srv\\share\\a.cbl"
    assert extended_path("\\\\?\\C:\\a", ident) == "\\\\?\\C:\\a"


def test_long_path_fallback_only_on_windows_and_long_paths(monkeypatch):
    from archdiag import repos
    calls = []

    def fn(p):
        calls.append(p)
        if not p.startswith("\\\\?\\"):
            raise OSError("too long")
        return "ok"
    long_p = "C:\\" + "a" * 270
    monkeypatch.setattr(repos.os, "name", "posix")
    with pytest.raises(OSError):
        repos.with_long_path(fn, long_p)
    monkeypatch.setattr(repos.os, "name", "nt")
    monkeypatch.setattr(repos, "extended_path", lambda p: "\\\\?\\" + p)
    assert repos.with_long_path(fn, long_p) == "ok"
    with pytest.raises(OSError):
        repos.with_long_path(fn, "C:\\short")


def test_crashed_rescan_never_serves_stale_links(tmp_path, monkeypatch, capsys):
    w = _estate(tmp_path)
    assert main(["scan", "--workspace", str(w)]) == 0
    cbl = next(w.rglob("*.cbl"))
    cbl.write_text(cbl.read_text(encoding="utf-8") + "\n      * touched\n", encoding="utf-8")
    real = cli.resolve
    monkeypatch.setattr(cli, "resolve", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert main(["list", "--workspace", str(w), "--what", "jobs"]) == 1
    monkeypatch.setattr(cli, "resolve", real)
    capsys.readouterr()
    assert main(["list", "--workspace", str(w), "--what", "jobs"]) == 0
    cap = capsys.readouterr()
    assert "Repos changed since last scan; rescanned." in cap.err
    assert "rescanned" not in cap.out


def test_stale_links_json_alone_triggers_rescan(tmp_path, capsys):
    w = _estate(tmp_path)
    assert main(["scan", "--workspace", str(w)]) == 0
    (w / "architecture-diagrams" / "inventory.json").unlink()
    cbl = next(w.rglob("*.cbl"))
    cbl.write_text(cbl.read_text(encoding="utf-8") + "\n      * t\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["list", "--workspace", str(w), "--what", "jobs"]) == 0
    assert "rescanned" in capsys.readouterr().err


def test_save_json_is_atomic(tmp_path, monkeypatch):
    from archdiag import store
    target = tmp_path / "a.json"
    store.save_json(target, {"a": 1})
    monkeypatch.setattr(store.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(OSError):
        store.save_json(target, {"a": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}


def test_unanalyzed_warning_in_scan_draw_and_summary(tmp_path, monkeypatch, capsys):
    import archdiag.scan as sc
    w = _estate(tmp_path)

    def bad(repo, rel, text, ctx):
        raise ValueError("odd file")
    monkeypatch.setitem(sc.SCANNERS, "bms", bad)
    assert main(["scan", "--workspace", str(w)]) == 0
    out = capsys.readouterr().out
    assert "WARNING: 1 file(s) could not be analyzed; links involving them may be missing" in out
    assert main(["draw", "--workspace", str(w), "--level", "landscape"]) == 0  # from cache
    out = capsys.readouterr().out
    assert "WARNING: 1 file(s) could not be analyzed" in out and "landscape-links.md" in out
    assert out.index("WARNING") < out.index("Wrote:")
    assert main(["summary", "--workspace", str(w)]) == 0
    out = capsys.readouterr().out
    assert out.count("could not be analyzed") >= 2
    assert "(see " in out or "WARNING" in out


def test_notices_go_to_stderr_and_list_stdout_is_clean(tmp_path, capsys):
    w = _estate(tmp_path)
    assert main(["list", "--workspace", str(w), "--what", "jobs"]) == 0
    cap = capsys.readouterr()
    assert "scanning" in cap.err and "Scanned:" in cap.err
    assert cap.out.splitlines()[0].startswith("CLMD100")


def test_error_message_is_one_line(tmp_path, monkeypatch, capsys):
    w = _estate(tmp_path)
    monkeypatch.setattr(cli, "resolve", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("line one\nline two\n  line three")))
    assert main(["scan", "--workspace", str(w)]) == 1
    out = capsys.readouterr().out
    assert len(out.strip().splitlines()) == 1 and "line one line two line three" in out


def test_txt_exports_and_xml_json_are_read(tmp_path):
    from archdiag.textio import needs_text
    assert needs_text("a/x.xml") and needs_text("a/x.json") and needs_text("a/export.txt")
    w = tmp_path / "ws"
    (w / "r" / ".git").mkdir(parents=True)
    (w / "r" / "export.txt").write_text(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. TXTPGM.\n"
        "       PROCEDURE DIVISION.\n           STOP RUN.\n", encoding="utf-8")
    (w / "r" / "job.txt").write_text("//TXTJOB JOB (A),'X'\n//S1 EXEC PGM=TXTPGM\n",
                                     encoding="utf-8")
    assert main(["scan", "--workspace", str(w)]) == 0
    inv = load_inventory(w / "architecture-diagrams" / "inventory.json")
    ids = set(inv.nodes)
    assert any("TXTPGM" in i for i in ids) and any(i.startswith("job:") for i in ids)


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


def test_walk_suffix_strips_extended_prefix():
    from archdiag.repos import walk_suffix
    root = "\\\\?\\C:\\ws\\repo"
    assert walk_suffix(root, root) == ""
    assert walk_suffix(root + "\\src\\deep", root) == "src\\deep"
    unc = "\\\\?\\UNC\\srv\\share\\r"
    assert walk_suffix(unc + "\\a", unc) == "a"
    assert walk_suffix("/ws/r/a/b", "/ws/r") == "a/b"


def test_missing_long_path_file_is_recorded(tmp_path, monkeypatch):
    from archdiag import repos
    (tmp_path / "a.cbl").write_text("x", encoding="utf-8")
    monkeypatch.setattr(repos, "MAX_PATH", 5)  # every path counts as long
    real = os.stat

    def gone(path, *a, **k):
        raise FileNotFoundError(2, "No such file or directory", path)
    monkeypatch.setattr(repos.os, "stat", gone)
    skipped = []
    assert list(repos.iter_source_files(tmp_path, (), skipped)) == []
    assert skipped and "cannot read file" in skipped[0][1]
    monkeypatch.setattr(repos.os, "stat", real)


def test_list_sends_every_notice_to_stderr(tmp_path, capsys):
    w = _estate(tmp_path)
    (w / "architecture-diagrams" / "groups.json").write_text(
        json.dumps({"apps": [{"name": "x", "members": [5]}]}), encoding="utf-8")
    (w / "architecture-diagrams" / "archdiag.config.json").write_text("{bad", encoding="utf-8")
    assert main(["list", "--workspace", str(w), "--what", "jobs"]) == 0
    cap = capsys.readouterr()
    assert all(l.split()[0].startswith("CLM") for l in cap.out.splitlines())
    assert "groups.json" in cap.err and "not valid JSON" in cap.err
    assert main(["draw", "--workspace", str(w), "--level", "landscape"]) == 0
    assert "groups.json" in capsys.readouterr().out


def test_failed_replace_leaves_no_tmp(tmp_path, monkeypatch):
    from archdiag import store
    monkeypatch.setattr(store.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(OSError):
        store.save_json(tmp_path / "a.json", {"a": 1})
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("fname", ["start.xml", "start.json"])
def test_ckbr_start_in_xml_or_json_marks_queue_bridged(tmp_path, fname):
    w = tmp_path / "ws"
    (w / "r" / ".git").mkdir(parents=True)
    (w / "r" / "q.mqsc").write_text("DEFINE QLOCAL(CLM.BRQ)\n", encoding="utf-8")
    (w / "r" / fname).write_text(
        "<step>EXEC CICS START TRANSID('CKBR')\n FROM('Q=CLM.BRQ,AUTH=LOCAL') LENGTH(22) "
        "END-EXEC.</step>\n", encoding="utf-8")
    assert main(["scan", "--workspace", str(w)]) == 0
    inv = load_inventory(w / "architecture-diagrams" / "inventory.json")
    assert inv.nodes["queue:CLM.BRQ"].attrs["bridge"] is True
