from __future__ import annotations

import re

from conftest import OUT, fixture_resolved, fixture_view
from archdiag.model import CONFIRMED, LOOSE, PARTIAL, Edge, Evidence, Inventory, Node, Repo, Resolved
from archdiag.render.report import links_report
from archdiag.views import VEdge, VNode, ViewGraph

CASES = [("landscape", None), ("application", "claims-online"), ("flow_job", "CLMD100"),
         ("flow_tx", "CLMI"), ("flow_tx", "claims/:id"), ("repomap", None)]


def rep(level, scope=None):
    v = fixture_view(level, scope)
    return links_report(v, fixture_resolved())


def section(t, name):
    return t.split("## %s\n" % name, 1)[1].split("\n## ", 1)[0]


def _reachable(v):
    out = {}
    for lst in [n.underlying for n in v.nodes] + [e.underlying for e in v.edges]:
        for e in lst:
            out[id(e)] = e
    return list(out.values())


def _p(ev):
    return "%s/%s:%d" % (ev.repo, ev.path, ev.line) if ev.repo else "%s:%d" % (ev.path, ev.line)


def _table_rows(t):
    rows = [l for l in section(t, "Links on this diagram").splitlines() if l.startswith("| ")]
    return rows[1:]


def synth(edges, nodes=(), skipped=()):
    ns = {n.id: n for n in nodes}
    inv = Inventory("w", [Repo("r", ".")], dict(ns), [], "f", {}, list(skipped))
    r = Resolved(inv, ns, list(edges))
    vn = [VNode("a", "A")]
    ve = [VEdge("a", "b", "", "confirmed", "runtime", [], None, list(edges))]
    return links_report(ViewGraph("T", "landscape", None, vn, ve, [], []), r)


def test_sections_in_order():
    t = rep("flow_job", "CLMD100")
    names = [h.lstrip("# ") for h in re.findall(r"^#+ .*$", t, re.M)]
    assert names[0].startswith("Links: ")
    assert names[1:] == ["Links on this diagram", "Loose ends", "Partly known",
                         "Possibly missing repos", "Not analyzed", "Skipped files", "Notes"]
    assert re.search(r"\d+ confirmed · \d+ partly known · \d+ loose ends", t)


def test_every_edge_listed():
    for level, scope in CASES:
        v = fixture_view(level, scope)
        t = rep(level, scope)
        edges = _reachable(v)
        for e in edges:
            for ev in e.evidence:
                assert _p(ev) in t, (level, scope, _p(ev))
        rows = _table_rows(t)
        r = fixture_resolved()
        for e in edges:
            assert r.nodes[e.src].name in t and r.nodes[e.dst].name.lstrip("?").split(":")[0] in t \
                or r.nodes[e.dst].name.startswith("?"), (level, e.src, e.op, e.dst)
        # one row per distinct link; copies in another file fold into "also in"
        assert 0 < len(rows) <= len(edges) or not edges
        text = "\n".join(rows)
        assert text.count("also in:") >= len(edges) - len(rows)
        assert re.search(r"\(%d resolver edges incl\. copies\)" % len(edges), t) or len(rows) == len(edges)


def test_edges_without_evidence_listed():
    a = Edge("program:A", "call", "program:B", CONFIRMED, None, [])
    t = synth([a], [Node("program:A", "program", "A", None, []), Node("program:B", "program", "B", None, [])])
    assert len(_table_rows(t)) == 1 and "program A" in t and "program B" in t


def test_folded_node_expands_all():
    es = [Edge("program:P%d" % i, "copy", "missing:copybook:C%d" % i, LOOSE, None,
               [Evidence("r", "cbl/P%d.cbl" % i, 3, "COPY C%d" % i)]) for i in range(5)]
    t = synth(es)
    assert len(_table_rows(t)) == 5
    for i in range(5):
        assert "r/cbl/P%d.cbl:3" % i in t


def test_pipe_escaped_and_one_line():
    e = Edge("program:A", "call", "missing:program:X|Y", LOOSE, "bad | reason\nsecond",
             [Evidence("r", "a|b.cbl", 1, "CALL 'X|Y'\nmore")])
    t = synth([e])
    for row in _table_rows(t):
        assert len(re.split(r"(?<!\\)\|", row)) == 7, row
    assert "a\\|b.cbl:1" in t
    assert "\n  " not in section(t, "Loose ends") and "second" in section(t, "Loose ends")


def test_skipped_section_nonempty():
    t = synth([], skipped=[{"repo": "claims-batch", "path": "big/FILE.cbl", "reason": "too large"}])
    assert "claims-batch/big/FILE.cbl" in section(t, "Skipped files")
    assert "too large" in section(t, "Skipped files")


def test_evidence_column_labels():
    t = rep("flow_job", "CLMD100")
    assert "| Evidence |" in t and "Evidence (from)" not in t
    row = [r for r in _table_rows(t) if "CLMB200 | confirmed" in r and "step STEP020" in r][0]
    assert "(here)" in row and "(defined)" in row and "CLMB200.cbl:2" in row


def test_partial_shows_candidates():
    t = rep("flow_tx", "CLMI")
    assert "CLMO110" in t and "ambiguous" in t
    assert t.count("claims-online/") >= 2


def test_not_analyzed():
    assert "1 asm files: program names registered, contents not analyzed" in rep("landscape")


def test_gap_link_text_and_no_internal_ids():
    t = rep("flow_job", "CLMD100")
    assert "written but never read in these repos" in "\n".join(_table_rows(t))
    assert not [r for r in _table_rows(t) if r.split(" | ")[1] in ("loose", "gap")]
    assert "?CLMO" not in rep("landscape")
    assert "dynamic target (WS-NEXT-PGM)" in rep("landscape")
    assert "missing:" not in rep("landscape")


def test_copies_grouped():
    t = rep("landscape")
    rows = _table_rows(t)
    step50 = [r for r in rows if "NDM:FINANCE" in r]
    assert len(step50) == 1 and "also in:" in step50[0] and "jcl/test/CLMD100.jcl" in step50[0]
    assert "incl. copies" in t


def test_missing_repo_section():
    t = rep("landscape")
    s = section(t, "Possibly missing repos")
    assert "defined in none of the scanned repos" in s
    assert s.count("ERRMSG") == 1 and "ERRMSG (copybook)" in s and "claims-online" in s
    for n in ("CLMO120", "CLMX", "CLMB"):
        assert n in s
    assert "CLM*" not in s and "CLM.*" not in s
    assert "CLAIMS.AUDIT" not in s and "PAYMENT.FEED" not in s and "?" not in s
    assert "NDM:FINANCE" in s and s.count("NDM:FINANCE") == 1


def test_prefix_group_only_for_unfound_prefix():
    def e(n):
        return Edge("program:A", "call", "missing:program:%s" % n, LOOSE, None,
                    [Evidence("r", "a.cbl", 1, "")])
    t = synth([e("ZZZA1"), e("ZZZA2"), e("QQ1"), e("QQ2")])
    s = section(t, "Possibly missing repos")
    assert "ZZZA*" in s and "QQ*" not in s


def test_write_reports():
    OUT.mkdir(exist_ok=True)
    for level, scope in CASES:
        name = "report-%s%s.md" % (level, "" if scope is None else "-" + re.sub(r"\W", "_", scope))
        (OUT / name).write_text(rep(level, scope), encoding="utf-8")
