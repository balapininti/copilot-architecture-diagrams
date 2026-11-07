from __future__ import annotations

import json

from conftest import ESTATE
from archdiag.config import Config, load_config
from archdiag.groups import default_groups, load_groups, app_of, suggested_edges
from archdiag.resolve import resolve
from archdiag.scan import scan_workspace
from archdiag.summary import build_summary, list_items

_C = {}


def res(qualifiers=True):
    if qualifiers not in _C:
        cfg = load_config(ESTATE / "architecture-diagrams") if qualifiers else Config()
        _C[qualifiers] = (resolve(scan_workspace(ESTATE, cfg), cfg), cfg)
    return _C[qualifiers]


def write(tmp_path, data):
    p = tmp_path / "groups.json"
    p.write_text(json.dumps(data))
    return p


def test_default_groups_one_per_repo():
    g = default_groups(res()[0])
    assert len(g.apps) == 6
    assert {a.name: a.kind for a in g.apps}["claims-db"] == "datastore"


def test_selector_precedence(tmp_path):
    r = res()[0]
    g = load_groups(write(tmp_path, {"apps": [{"name": "Claims Online",
                     "members": ["program:CLMO1*", "transaction:CLMI"]}]}), r)
    assert app_of(g, r, "program:CLMO100") == "Claims Online"
    assert app_of(g, r, "transaction:CLMI") == "Claims Online"
    assert app_of(g, r, "program:CLMB200") == "claims-batch"
    assert app_of(g, r, "dataset:PROD.CLAIMS.DAILY") is None
    assert not g.problems


def test_unknown_selector_and_link_end_reported(tmp_path):
    r = res()[0]
    g = load_groups(write(tmp_path, {"apps": [{"name": "X", "members": ["program:NOPE*", "bad"]}],
                     "suggested_links": [{"from": "dataset:CLAIMS.EXTRACT", "to": "nowhere", "note": "n"}]}), r)
    assert len(g.problems) == 3 and not g.suggested_links


def test_missing_file_is_default(tmp_path):
    assert len(load_groups(tmp_path / "none.json", res()[0]).apps) == 6


def test_suggested_link_is_partial(tmp_path):
    r = res()[0]
    g = load_groups(write(tmp_path, {"suggested_links": [
        {"from": "dataset:CLAIMS.EXTRACT", "to": "external:NDM:FINANCE", "note": "x"},
        {"from": "claims-batch", "to": "claims-db", "note": "y"}]}), r)
    e = suggested_edges(g, r)
    assert e[0].status == "partial" and e[0].reason == "suggested by Copilot: x" and e[0].op == "suggested"
    assert e[1].src == "app:claims-batch"


def test_summary_env_candidates():
    r, _ = res(False)
    s = build_summary(r, default_groups(r), Config())
    assert "TEST ~ PROD (" in s and "shared names, e.g." in s
    assert "Only accept real environment names." in s
    assert "ARCH" not in s.split("## Links")[0] and "CLMS ~" not in s
    r2, cfg2 = res(True)
    cand = build_summary(r2, default_groups(r2), cfg2).split("## Links")[0].split("candidates")[1]
    assert "PROD" not in cand and "TEST" not in cand and "ARCH" not in cand


def test_summary_size():
    r, cfg = res()
    assert len(build_summary(r, default_groups(r), cfg).splitlines()) <= 120


def test_list_jobs():
    r = res()[0]
    jobs = list_items(r, default_groups(r), "jobs")
    assert "CLMD100 (claims-batch/jcl/CLMD100.jcl)" in jobs
    assert "CLMD100 (claims-batch/jcl/test/CLMD100.jcl)" in jobs
    for w in ("transactions", "pages", "endpoints", "applications", "repos", "programs"):
        assert list_items(r, default_groups(r), w)


def test_malformed_groups_json_never_raises(tmp_path):
    r = res()[0]
    p = tmp_path / "groups.json"
    p.write_text("{not json")
    g = load_groups(p, r)
    assert len(g.apps) == 6 and g.problems
    p.write_text("[1, 2]")
    assert len(load_groups(p, r).apps) == 6
    g = load_groups(write(tmp_path, {"apps": [{"name": "A", "members": None}, {"name": "B", "members": 5},
                                             {"name": "C", "members": ["repo:claims-db", 7]}, 3, {"name": 4}],
                                     "suggested_links": [5, "x"]}), r)
    assert [a.name for a in g.apps][:3] == ["A", "B", "C"]
    assert g.problems and not g.suggested_links


def test_duplicate_app_and_uncovered_repo(tmp_path):
    r = res()[0]
    g = load_groups(write(tmp_path, {"apps": [{"name": "A", "members": ["repo:claims-db"]},
                                              {"name": "A"}]}), r)
    assert any("duplicate" in p for p in g.problems)
    assert "claims-batch" in [a.name for a in g.apps]


def test_path_repo_selectors_and_case(tmp_path):
    r = res()[0]
    g = load_groups(write(tmp_path, {"apps": [
        {"name": "P", "members": ["path:claims-online/cobol/*"]},
        {"name": "Q", "members": ["program:clmb2*", "repo:claims-portal", "path:*/*"]}]}), r)
    assert app_of(g, r, "program:CLMO100") == "P"
    assert app_of(g, r, "program:CLMB200") == "Q"
    assert app_of(g, r, "page:claims-portal/claims/:id") == "Q"
    assert app_of(g, r, "dataset:PROD.CLAIMS.DAILY") is None


def test_empty_note_reason(tmp_path):
    r = res()[0]
    g = load_groups(write(tmp_path, {"suggested_links": [
        {"from": "claims-batch", "to": "claims-db"}]}), r)
    assert suggested_edges(g, r)[0].reason == "suggested by Copilot"


def test_counts_consistent_and_skipped_line():
    import copy
    r, cfg = res()
    g = default_groups(r)
    r2 = copy.copy(r)
    r2.inventory = copy.copy(r.inventory)
    r2.inventory.skipped = [{"repo": "x", "path": "p%d" % i, "reason": "size"} for i in range(8)]
    s = build_summary(r2, g, cfg)
    assert "Skipped files: 8" in s and "x/p4 (size)" in s and "x/p5" not in s
    n = [l for l in s.splitlines() if l.startswith("- claims-batch [")][0]
    assert n.split(": ")[1] == [i for i in list_items(r, g, "applications")
                                if i.startswith("claims-batch")][0].split(", ")[1].rstrip(")")


def test_large_input_keeps_tail_sections():
    from archdiag.model import Inventory, Node, Repo, Resolved, Edge, Evidence
    repos = [Repo("r%d" % i, "r%d" % i) for i in range(80)]
    nodes = {}
    for i in range(80):
        nodes["program:P%d" % i] = Node("program:P%d" % i, "program", "P%d" % i, "r%d" % i,
                                        [Evidence("r%d" % i, "a.cbl", 1, "")])
    edges = [Edge("program:P%d" % i, "call", "missing:program:X%d" % i, "loose", "why", [])
             for i in range(30)]
    inv = Inventory("w", repos, nodes, [], "f", {"asm": 2},
                    [{"repo": "r1", "path": "big", "reason": "size"}])
    r = Resolved(inv, nodes, edges)
    s = build_summary(r, default_groups(r), Config())
    assert len(s.splitlines()) <= 120 and "truncated" not in s
    assert "and 55 more" in s and "## Links" in s and "Skipped files: 1" in s and "asm: 2" in s


def _synth(nrepo=40, nproblem=15):
    from archdiag.model import Inventory, Node, Repo, Resolved, Edge, Evidence
    nodes, edges = {}, []
    for i in range(nrepo):
        nodes["program:P%d" % i] = Node("program:P%d" % i, "program", "P%d" % i, "r%d" % i,
                                        [Evidence("r%d" % i, "a.cbl", 1, "")])
    for q in ("A%d" % i for i in range(12)):
        for t in ("T1", "T2"):
            for kind in ("dataset", "table"):
                nid = "%s:%s.%s" % (kind, q, t)
                nodes[nid] = Node(nid, kind, "%s.%s" % (q, t), None, [])
    for i in range(30):
        edges.append(Edge("program:P%d" % i, "call", "missing:program:X%d" % i, "loose", "why", []))
        edges.append(Edge("program:P%d" % i, "call", "program:P%d" % (i + 1), "partial", "why", []))
    inv = Inventory("w", [Repo("r%d" % i, "r%d" % i) for i in range(nrepo)], nodes, [], "f",
                    {"asm": 2, "pli": 1}, [{"repo": "r1", "path": "f%d" % i, "reason": "size"} for i in range(9)])
    r = Resolved(inv, nodes, edges)
    g = default_groups(r)
    g.problems = ["problem %d" % i for i in range(nproblem)]
    return r, g


def test_maxed_sections_keep_tail():
    r, g = _synth()
    s = build_summary(r, g, Config())
    lines = s.splitlines()
    assert len(lines) <= 120 and "truncated" not in s
    assert "## Not analyzed" in s and "asm: 2 files" in s and "Skipped files: 9" in s
    assert "  - r1/f4 (size)" in s and "and " in s


def test_cross_repo_and_guards():
    from archdiag.model import Edge, Evidence
    r, g = _synth(3, 0)
    r.edges = [
        Edge("program:P0", "call", "missing:program:X", "loose", "a", [Evidence("r0", "z", 1, "")]),
        Edge("program:P0", "call", "program:P1", "loose", "b", [Evidence(None, None, 1, "")]),
        Edge("program:P2", "call", "program:P1", "loose", "c", []),
    ]
    s = build_summary(r, g, Config())
    loose = s.split("## Top loose links")[1].splitlines()
    assert "-> program:P1: b" in loose[1] or "-> program:P1: c" in loose[1]
    assert "missing:program:X" in loose[3]


def test_gdg_generations_one_tail():
    from archdiag.model import Inventory, Node, Resolved
    names = ["TEST.A.G0001V00", "TEST.A.G0002V00", "PROD.A", "TEST.B", "PROD.B"]
    nodes = {"dataset:" + n: Node("dataset:" + n, "dataset", n, None, []) for n in names}
    r = Resolved(Inventory("w", [], nodes, [], "f", {}, []), nodes, [])
    s = build_summary(r, default_groups(r), Config(environment_qualifiers=["dev"]))
    assert "TEST ~ PROD (2 shared names" in s


def test_case_insensitive_config_and_bad_kind(tmp_path):
    r, _ = res(False)
    s = build_summary(r, default_groups(r), Config(environment_qualifiers=["test", "prod"]))
    assert "TEST ~ PROD" not in s
    g = load_groups(write(tmp_path, {"apps": [{"name": "A", "kind": ["x"]}, {"name": "B", "kind": {}}]}), r)
    assert [a.kind for a in g.apps][:2] == ["application", "application"] and len(g.problems) >= 2
