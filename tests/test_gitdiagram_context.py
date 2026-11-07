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


def _shared_section(out):
    return out.split("### Shared data (no file)")[1].split("## Entry points")[0]


def test_context_shared_data_lists_files_touching_same_dataset():
    out = gitdiagram_context(fixture_resolved(), "claims-batch")
    sec = _shared_section(out)
    assert "jcl/CLMD100.jcl" in sec and "jcl/test/CLMD100.jcl" in sec
    assert "→ dataset " in sec


def test_context_shared_table_across_repos_and_data_as_source():
    from archdiag.model import Edge, Evidence, Node
    ev = lambda p: [Evidence("big", p, 1)] if False else []
    def nd(i, k, n, repo, p):
        return Node(i, k, n, repo, [Evidence(repo, p, 1, "x")] if p else [])
    nodes = {n.id: n for n in (nd("program:A", "program", "A", "big", "a.cbl"),
                               nd("program:B", "program", "B", "big", "b.cbl"),
                               nd("table:T", "table", "CLMS.CLAIM", "db", "ddl/t.sql"),
                               nd("queue:Q", "queue", "QQ", None, None),
                               nd("transaction:X", "transaction", "TX", "big", "b.cbl"))}
    edges = [Edge("program:A", "select", "table:T", "confirmed", None, []),
             Edge("program:B", "insert", "table:T", "confirmed", None, []),
             Edge("queue:Q", "triggers", "transaction:X", "confirmed", None, []),
             Edge("program:A", "put", "queue:Q", "confirmed", None, [])]
    files = [{"repo": "big", "path": "a.cbl", "kind": "cobol"}, {"repo": "big", "path": "b.cbl", "kind": "cobol"}]
    inv = Inventory("/nonexistent", [Repo("big", "big")], nodes, [], "fp", {}, files=files)
    out = gitdiagram_context(Resolved(inv, nodes, edges), "big")
    assert "a.cbl select, b.cbl insert → db: table CLMS.CLAIM" in out
    assert "a.cbl put, b.cbl triggers → queue QQ" in out


def test_context_folder_summary_goes_three_levels_deep():
    files = [{"repo": "big", "path": "src/main/java/p%d/F%d.java" % (i % 10, i), "kind": "java"} for i in range(600)]
    inv = Inventory("/nonexistent", [Repo("big", "big")], {}, [], "fp", {}, files=files)
    out = gitdiagram_context(Resolved(inv, {}, []), "big", max_lines=300)
    assert "src/main/java/\t600 files" in out and "summarised per folder" in out
    out2 = gitdiagram_context(Resolved(inv, {}, []), "big", max_lines=60)
    assert len(out2.splitlines()) <= 60


def test_context_never_exceeds_small_budget():
    out = gitdiagram_context(fixture_resolved(), "claims-batch", max_lines=50)
    assert len(out.splitlines()) <= 50
    tiny = gitdiagram_context(fixture_resolved(), "claims-batch", max_lines=15)
    assert len(tiny.splitlines()) <= 15 and "cut to" in tiny or len(tiny.splitlines()) <= 15


def test_context_readme_prefers_exact_and_survives_bad_bytes(tmp_path):
    (tmp_path / "big").mkdir()
    (tmp_path / "big" / "README-old.txt").write_text("old", encoding="utf-8")
    (tmp_path / "big" / "README.md").write_bytes(b"new \xff\xfe text")
    inv = Inventory(str(tmp_path), [Repo("big", "big")], {}, [], "fp", {}, files=[])
    out = gitdiagram_context(Resolved(inv, {}, []), "big")
    assert "new" in out and "old" not in out
