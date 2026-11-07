from __future__ import annotations

from conftest import fixture_resolved

from archdiag.model import Inventory, Repo, Resolved
from archdiag.summary import gitdiagram_context


def test_context_lists_files_and_names():
    out = gitdiagram_context(fixture_resolved(), "claims-batch")
    assert "cobol/CLMB200.cbl\tcobol\tprogram:CLMB200" in out.splitlines()
    assert out.startswith("# Repo claims-batch")


def test_context_links_between_files():
    out = gitdiagram_context(fixture_resolved(), "claims-batch")
    assert "jcl/CLMD100.jcl → cobol/CLMB200.cbl  runs  confirmed" in out.splitlines()
    assert out == gitdiagram_context(fixture_resolved(), "claims-batch")


def test_context_entry_points():
    out = gitdiagram_context(fixture_resolved(), "claims-batch")
    assert "job\tCLMD100\tjcl/CLMD100.jcl" in out.split("## Entry points")[1]


def test_context_summarises_huge_repo():
    files = [{"repo": "big", "path": "d%d/f%d.cbl" % (i % 50, i), "kind": "cobol"} for i in range(3000)]
    inv = Inventory("/nonexistent", [Repo("big", "big")], {}, [], "fp", {}, files=files)
    out = gitdiagram_context(Resolved(inv, {}, []), "big")
    assert len(out.splitlines()) <= 1500 and "summarised per folder" in out
    assert "d0/\t60 files\tcobol 60" in out


def test_context_readme_capped_at_200_lines(tmp_path):
    (tmp_path / "big").mkdir()
    (tmp_path / "big" / "README.md").write_text("\n".join("line%d" % i for i in range(500)), encoding="utf-8")
    inv = Inventory(str(tmp_path), [Repo("big", "big")], {}, [], "fp", {}, files=[])
    out = gitdiagram_context(Resolved(inv, {}, []), "big")
    assert "line199" in out and "line200" not in out
