"""Every style and every editable export draws each line in the legend's color and dash."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from conftest import (drawio_edge_encodings, excalidraw_edge_encodings, expected_line,
                      fixture_view, svg_edge_encodings)
from archdiag.render import style_a, style_b, style_c, style_d
from archdiag.render.common import LEGEND_SIZE
from archdiag.views import VEdge, VNode, ViewGraph

LEVELS = (("landscape", None), ("application", "claims-online"), ("flow_job", "CLMD100"),
          ("flow_tx", "claims/:id"))


def _mixed_view():
    nodes = [VNode(i, i.upper(), kind="program") for i in "abcd"]
    nodes.append(VNode("m", "none", kind="missing", status="loose"))
    edges = [VEdge("a", "b", "ok"), VEdge("a", "c", "maybe", status="partial"),
             VEdge("a", "d", "copy", kind="shared_code"),
             VEdge("b", "m", "loose", status="loose")]
    return ViewGraph("T", "application", "x", nodes, edges, [])


def _views():
    yield _mixed_view()
    for level, scope in LEVELS:
        yield fixture_view(level, scope)


def _check(found, v, what):
    assert found, what
    for i, got in found.items():
        e = v.edges[i]
        assert got == expected_line(e.status, e.kind), (what, i, e.status, e.kind, got)


def test_svg_styles_match_legend():
    for v in _views():
        for mod in (style_a, style_b, style_c, style_d):
            _check(svg_edge_encodings(mod.render(v)["svg"]), v, mod.__name__)


def test_drawio_matches_legend_and_has_one():
    for v in _views():
        out = style_a.render(v)["drawio"]
        _check(drawio_edge_encodings(out), v, "drawio")
        ids = {c.get("id") for c in ET.fromstring(out).iter("mxCell")}
        present = {expected_line(e.status, e.kind)[0] for e in v.edges}
        assert len([i for i in ids if i.startswith("lg-text-")]) == len(
            {("loose" if c == "#dc2626" else c) for c in present})


def test_excalidraw_matches_legend_and_has_one():
    for v in _views():
        out = style_d.render(v)["excalidraw"]
        _check(excalidraw_edge_encodings(out), v, "excalidraw")
        els = json.loads(out)["elements"]
        legend = {e["id"]: e for e in els if e["id"].startswith("legend-") and e["type"] == "line"}
        want = {(c, d) for c, d in (expected_line(e.status, e.kind) for e in v.edges)}
        from conftest import EXCALIDRAW_DASH
        have = {(e["strokeColor"], EXCALIDRAW_DASH[e["strokeStyle"]]) for e in legend.values()}
        assert have == want
