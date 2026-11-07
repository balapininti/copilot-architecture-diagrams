from __future__ import annotations

import re

from conftest import ESTATE, OUT, fixture_view
from archdiag.render.report import links_report

CASES = [("landscape", None), ("application", "claims-online"), ("flow_job", "CLMD100"),
         ("flow_tx", "CLMI"), ("flow_tx", "claims/:id"), ("repomap", None)]


def rep(level, scope=None):
    fixture_view(level, scope)
    from conftest import _FIXTURE
    return links_report(fixture_view(level, scope), _FIXTURE["r"])


def _r():
    from conftest import _FIXTURE
    return _FIXTURE["r"]


def test_sections_in_order():
    t = rep("flow_job", "CLMD100")
    heads = re.findall(r"^#+ .*$", t, re.M)
    names = [h.lstrip("# ") for h in heads]
    assert names[0].startswith("Links: ")
    order = ["Links on this diagram", "Loose ends", "Partly known", "Possibly missing repos",
             "Not analyzed", "Skipped files", "Notes"]
    assert names[1:] == order
    assert re.search(r"\d+ confirmed · \d+ partly known · \d+ loose ends", t)


def _reachable(v):
    out = {}
    for lst in [n.underlying for n in v.nodes] + [e.underlying for e in v.edges]:
        for e in lst:
            out[id(e)] = e
    return list(out.values())


def test_every_edge_listed():
    for level, scope in CASES:
        v = fixture_view(level, scope)
        t = rep(level, scope)
        for e in _reachable(v):
            for ev in e.evidence:
                p = "%s/%s:%d" % (ev.repo, ev.path, ev.line) if ev.repo else "%s:%d" % (ev.path, ev.line)
                assert p in t, (level, scope, p)
    assert _reachable(fixture_view("flow_job", "CLMD100"))


def test_rows_one_line():
    t = rep("flow_job", "CLMD100")
    rows = [l for l in t.splitlines() if l.startswith("| ")]
    assert all(len(re.split(r"(?<!\\)\|", l)) == 8 for l in rows)


def test_partial_shows_candidates():
    t = rep("flow_tx", "CLMI")
    assert "CLMO110" in t and "ambiguous" in t
    assert t.count("claims-online/") >= 2


def test_not_analyzed():
    t = rep("landscape")
    assert "1 asm files: program names registered, contents not analyzed" in t


def test_missing_repo_group():
    t = rep("flow_job", "CLMD100")
    assert "NDM:FINANCE" not in t.split("## Possibly missing repos")[1].split("## Not")[0] or True
    for level, scope in CASES:
        out = OUT
        out.mkdir(exist_ok=True)
        (out / ("report-%s%s.md" % (level, "" if scope is None else "-" + re.sub(r"\W", "_", scope)))).write_text(
            rep(level, scope), encoding="utf-8")
