from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

from conftest import OUT, assert_office_safe, fixture_view
from archdiag.render import style_d
from archdiag.views import VEdge, VGroup, VNode, ViewGraph

LEVELS = (("landscape", None), ("application", "claims-online"), ("flow_job", "CLMD100"),
          ("flow_tx", "claims/:id"), ("flow_tx", "CLMI"), ("repomap", None))
V = lambda: fixture_view("flow_tx", "claims/:id")  # noqa: E731


def svg_text(svg):
    root = ET.fromstring(svg)
    return " ".join("".join(t.itertext()) for t in root.iter("{http://www.w3.org/2000/svg}text"))


def test_office_safe_no_filter():
    for level, scope in LEVELS:
        svg = style_d.render(fixture_view(level, scope))["svg"]
        assert_office_safe(svg)
        assert "<filter" not in svg and "feTurbulence" not in svg
        assert 'font-family="Segoe Print, Comic Sans MS, cursive"' in svg
        assert 'fill="#fffdf7"' in svg


def test_deterministic():
    a, b = style_d.render(V()), style_d.render(V())
    assert a == b


def test_jitter_present():
    v = V()
    d1 = re.findall(r'<path d="([^"]+)"', style_d.render(v, seed=1)["svg"])
    d2 = re.findall(r'<path d="([^"]+)"', style_d.render(v, seed=2)["svg"])
    assert d1 and d1 != d2
    # rectangles are paths, never <rect> shapes (apart from the background and label pills)
    root = ET.fromstring(style_d.render(v)["svg"])
    assert not [r for r in root.iter("{http://www.w3.org/2000/svg}ellipse")]


def test_rect_edges_are_split():
    pts = style_d.Rough(1).rect(0, 0, 200, 90)
    assert len(pts) >= 4 + 2 * 5 + 2 * 2


def test_line_types_stay_distinct():
    nodes = [VNode("a", "A", kind="program"), VNode("b", "B", kind="program"),
             VNode("c", "C", kind="program"), VNode("d", "D", kind="program"),
             VNode("m", "no reader", kind="missing", status="loose", detail_lines=["why"])]
    edges = [VEdge("a", "b", "ok"), VEdge("a", "c", "maybe", status="partial"),
             VEdge("a", "d", "copy", kind="shared_code"),
             VEdge("b", "m", "loose", status="loose")]
    v = ViewGraph("T", "application", "x", nodes, edges, [VGroup("g", "G", "#3b82f6")])
    out = style_d.render(v)
    svg = out["svg"]
    assert 'stroke="#d97706"' in svg and 'stroke-dasharray="3 4"' in svg
    assert 'stroke-dasharray="7 4"' in svg and '<circle' in svg
    ex = json.loads(out["excalidraw"])
    arrows = [e for e in ex["elements"] if e["type"] == "arrow"]
    assert {a["strokeStyle"] for a in arrows} >= {"solid", "dotted", "dashed"}
    assert any(a["strokeColor"] == "#dc2626" and a["endArrowhead"] == "circle" for a in arrows)


def test_excalidraw_valid():
    for level, scope in LEVELS:
        j = json.loads(style_d.render(fixture_view(level, scope))["excalidraw"])
        assert j["type"] == "excalidraw" and j["appState"]["viewBackgroundColor"] == "#fffdf7"
        els = j["elements"]
        assert {e["type"] for e in els} >= {"rectangle", "arrow", "text"} or level == "repomap"
        ids = {e["id"] for e in els}
        assert len(ids) == len(els)
        for e in els:
            assert e["roughness"] == 1
            if e["type"] == "text":
                assert e["fontFamily"] == 1
                if e["containerId"]:
                    assert e["containerId"] in ids
            if e["type"] == "arrow":
                assert e["points"][0] == [0, 0]
                for k in ("startBinding", "endBinding"):
                    assert e[k]["elementId"] in ids
                    host = next(x for x in els if x["id"] == e[k]["elementId"])
                    assert {"id": e["id"], "type": "arrow"} in host["boundElements"]


def test_every_node_and_label_present():
    for level, scope in LEVELS:
        v = fixture_view(level, scope)
        flat = svg_text(style_d.render(v)["svg"]).replace(" ", "")
        for n in v.nodes:
            assert n.label.replace(" ", "") in flat, (level, n.label)


def test_notes_become_sticky_notes():
    v = V()
    v.notes = ["something to know"]
    out = style_d.render(v)
    assert "something to know" in svg_text(out["svg"])
    assert "#ffec99" in out["svg"] and "rotate(" in out["svg"]


def test_writes_samples():
    OUT.mkdir(exist_ok=True)
    for level, scope in LEVELS:
        name = "style_d-%s-%s" % (level, (scope or "all").replace("/", "_").replace(":", ""))
        out = style_d.render(fixture_view(level, scope))
        (OUT / (name + ".svg")).write_text(out["svg"], encoding="utf-8")
        (OUT / (name + ".excalidraw")).write_text(out["excalidraw"], encoding="utf-8")
