from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from conftest import OUT, assert_office_safe, fixture_view
from archdiag.layout import layout_for
from archdiag.render import style_b
from archdiag.views import VEdge, VGroup, VNode, ViewGraph

CASES = [("landscape", None), ("application", "claims-online"), ("flow_job", "CLMD100"),
         ("flow_tx", "claims/:id"), ("repomap", None)]


def _fence(md):
    return md.split("```mermaid", 1)[1].split("```", 1)[0]


def _texts(svg):
    return [(t.text or "") for t in ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}text")]


def test_svg_office_safe():
    for level, scope in CASES:
        assert_office_safe(style_b.render(fixture_view(level, scope))["svg"])


def test_mermaid_structure():
    v = fixture_view("landscape", None)
    md = style_b.render(v)["md"]
    assert md.startswith("# ")
    assert "```mermaid\nflowchart LR" in md
    assert md.count("subgraph") == len(v.groups)
    assert md.count("\n  end\n") == len(v.groups)
    assert "-.->" in md and "--x" in md
    assert "linkStyle" in md and "stroke:#dc2626" in md
    assert "classDef" in md
    assert "confirmed" in md.split("```", 2)[2]  # the legend follows the fence


def test_link_style_indexes_follow_link_order():
    v = fixture_view("landscape", None)
    md = style_b.render(v)["md"]
    links = [ln for ln in _fence(md).splitlines() if re.search(r"-->|-\.->|--x", ln)]
    assert len(links) == len(v.edges)
    for i, ln in enumerate(links):
        want = {"loose": "--x", "partial": "-.->"}.get(
            style_b.line_style(v.edges[i].status, v.edges[i].kind), "-->")
        assert want in ln
        if want == "--x":
            assert "linkStyle %d stroke:#dc2626" % i in md


def _tricky():
    return ViewGraph(
        title='Tricky "title"', level="landscape", scope=None,
        nodes=[VNode(id="program:A/B:C", label='say "hi"', sublabel="x <y> & z",
                     kind="program", group="g:1"),
               VNode(id="table:CLM#01", label="CLM#01", kind="table", group="g:1"),
               VNode(id="missing:x/y", label="&&SORTED", kind="missing", status="loose")],
        edges=[VEdge("program:A/B:C", "table:CLM#01", 'reads "it"'),
               VEdge("program:A/B:C", "missing:x/y", "calls", status="loose")],
        groups=[VGroup("g:1", 'grp "q"', "#3b82f6")], notes=[])


def test_mermaid_escapes_quotes_and_ids():
    out = style_b.render(_tricky())
    md = out["md"]
    fence = _fence(md)
    assert "say #quot;hi#quot;" in md
    assert 'say "hi"' not in md
    ids = re.findall(r"^\s*(n\d+)[\[\(]", md, re.M)
    assert ids == ["n0", "n1", "n2"]
    for ln in fence.splitlines():
        if "-->" in ln or "--x" in ln:
            assert ":" not in ln.split("|")[0] and "/" not in ln.split("|")[0]
    assert_office_safe(out["svg"])


def test_cylinders_for_tables():
    for level, scope in CASES:
        v = fixture_view(level, scope)
        svg = style_b.render(v)["svg"]
        n = sum(1 for x in v.nodes if x.kind in ("table", "dataset", "vsam", "gdg", "datastore"))
        assert len(re.findall("<ellipse", svg)) >= n
    v = fixture_view("flow_job", "CLMD100")
    assert "<ellipse" in style_b.render(v)["svg"]


def test_c4_boxes_and_three_lines():
    svg = style_b.render(fixture_view("landscape", None))["svg"]
    for c in ("#1168bd", "#999999", "#438dd5"):
        assert c in svg
    ts = _texts(svg)
    assert any(t.startswith("[Application: ") for t in ts)
    assert any(t.endswith(" [repo]") for t in ts)


def test_lines_keep_certainty_types():
    svg = style_b.render(fixture_view("landscape", None))["svg"]
    assert 'stroke-dasharray="3 4"' in svg and "#d97706" in svg
    assert 'stroke="#dc2626"' in svg and "<circle" in svg
    assert 'stroke-dasharray="7 4"' in svg


def test_no_node_overlap_and_pills_inside_canvas():
    for level, scope in CASES:
        v = fixture_view(level, scope)
        root = ET.fromstring(style_b.render(v)["svg"])
        w, h = float(root.get("width")), float(root.get("height"))
        for r in root.iter("{http://www.w3.org/2000/svg}rect"):
            if r.get("id", "").startswith("pill-"):
                x, y = float(r.get("x")), float(r.get("y"))
                assert 0 <= x and x + float(r.get("width")) <= w
                assert 0 <= y and y + float(r.get("height")) <= h


def test_writes_samples():
    OUT.mkdir(exist_ok=True)
    for level, scope in CASES:
        out = style_b.render(fixture_view(level, scope))
        name = "style_b-%s%s" % (level.split("_")[0], "-" + re.sub(r"\W", "_", scope) if scope else "")
        (OUT / (name + ".svg")).write_text(out["svg"], encoding="utf-8")
        (OUT / (name + ".md")).write_text(out["md"], encoding="utf-8")


def test_person_and_external_colors():
    v = ViewGraph(title="P", level="landscape", scope=None,
                  nodes=[VNode(id="person:u", label="User", sublabel="Uses it", kind="person"),
                         VNode(id="external:x", label="X", sublabel="outside", kind="external"),
                         VNode(id="program:a", label="A", kind="program")],
                  edges=[VEdge("person:u", "program:a", "uses")], groups=[], notes=[])
    svg = style_b.render(v)["svg"]
    assert "#08427b" in svg and "#999999" in svg and "#1168bd" in svg
    assert_office_safe(svg)
