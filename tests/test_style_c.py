from __future__ import annotations

import json
import re

from conftest import OUT, assert_office_safe, fixture_view
from archdiag.render import style_c
from archdiag.views import VEdge, VNode, ViewGraph
from archdiag.model import Evidence

CASES = [("repomap", None), ("repomap", "claims-batch")]


def _json(html):
    m = re.search(r'<script type="application/json" id="edge-data">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


def test_svg_office_safe():
    for level, scope in CASES:
        assert_office_safe(style_c.render(fixture_view(level, scope))["svg"])


def test_html_offline():
    for level, scope in CASES:
        html = style_c.render(fixture_view(level, scope))["html"]
        assert "<script" in html and "src=" not in html
        assert "https://" not in html.replace("http://www.w3.org", "")
        assert "href=" not in html


def test_html_has_every_evidence():
    v = fixture_view("repomap", None)
    html = style_c.render(v)["html"]
    data = _json(html)
    assert len(data) == len(v.edges)
    for e, d in zip(v.edges, data):
        assert len(d["evidence"]) == len(e.evidence)
        for x in e.evidence:
            assert "%s:%s" % (x.path, x.line) in html
            assert any(r["path"] == x.path and r["line"] == x.line and r["text"] == x.text
                       for r in d["evidence"])


def test_every_edge_group_is_clickable():
    v = fixture_view("repomap", None)
    html = style_c.render(v)["html"]
    for i in range(len(v.edges)):
        assert 'data-edge="%d"' % i in html
    assert "confirmed (both ends found in code)" in html


def test_evidence_strip():
    svg = style_c.render(fixture_view("repomap", None))["svg"]
    assert "MqClaimGateway.java:" in svg and "CLMO100.cbl:" in svg
    assert "↔" in svg


def test_line_types_and_cards():
    svg = style_c.render(fixture_view("repomap", None))["svg"]
    assert 'stroke="#cbd5e1"' in svg and 'fill-opacity="0.08"' in svg
    assert "⎇ claims-api" in svg
    for part in ('stroke="#334155"', 'stroke-dasharray="3 4"', 'stroke="#dc2626"',
                 'stroke-dasharray="7 4"'):
        assert part in svg


def test_hostile_evidence_cannot_break_out():
    n1 = VNode(id="repo:a", label="a", kind="repo", detail_lines=["x.cbl"], highlight=1)
    n2 = VNode(id="repo:b", label="b", kind="repo", detail_lines=["y.cbl"], highlight=1)
    ev = [Evidence(repo=None, path="z.aar!/</script><b>.xml", line=3,
                   text="</script><script>alert(1)</script> <!-- &")]
    v = ViewGraph("t", "repomap", None, [n1, n2],
                  [VEdge("repo:a", "repo:b", "x</script>", evidence=ev)], [])
    out = style_c.render(v)
    assert_office_safe(out["svg"])
    html = out["html"]
    assert html.count("</script>") == 2  # the data block and the code, nothing more
    assert _json(html)[0]["evidence"][0]["text"].startswith("</script>")
    assert "textContent" in html and "innerHTML" not in html


def test_empty_and_no_evidence():
    v = ViewGraph("t", "repomap", None, [], [], [])
    assert "<svg" in style_c.render(v)["svg"]


def test_visual_outputs():
    OUT.mkdir(exist_ok=True)
    for name, (level, scope) in (("all", CASES[0]), ("claims-batch", CASES[1])):
        out = style_c.render(fixture_view(level, scope))
        (OUT / ("style_c-%s.svg" % name)).write_text(out["svg"], encoding="utf-8")
        (OUT / ("style_c-%s.html" % name)).write_text(out["html"], encoding="utf-8")
