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


# ------------------------------------------------------------------ Batch C (C10)

def test_drawio_legend_lines_match_legend_and_fit_the_page():
    for v in _views():
        out = style_a.render(v)["drawio"]
        root = ET.fromstring(out)
        found = {}
        bottom = right = 0.0
        for c in root.iter("mxCell"):
            cid = c.get("id", "")
            if cid.startswith("lg-line-"):
                st = dict(kv.split("=", 1) for kv in c.get("style").split(";") if "=" in kv)
                found[cid[8:]] = (st["strokeColor"],
                                  st.get("dashPattern", "") if st.get("dashed") == "1" else "")
                for p in c.iter("mxPoint"):
                    bottom = max(bottom, float(p.get("y")))
                    right = max(right, float(p.get("x")))
            g = c.find("mxGeometry")
            if g is not None and g.get("height") is not None and g.get("relative") != "1":
                bottom = max(bottom, float(g.get("y", 0)) + float(g.get("height")))
                right = max(right, float(g.get("x", 0)) + float(g.get("width")))
        want = {}
        from archdiag.render.common import line_style
        for e in v.edges:
            want[line_style(e.status, e.kind)] = expected_line(e.status, e.kind)
        assert found == want, v.title
        model = root.find("diagram/mxGraphModel")
        assert float(model.get("pageHeight")) >= bottom, (v.title, model.get("pageHeight"), bottom)
        assert float(model.get("pageWidth")) >= right, (v.title, model.get("pageWidth"), right)


def test_style_d_heads_match_their_line():
    """Each line's chevron (or loose-end dot) is drawn in the line's own color, undashed."""
    ns = "{http://www.w3.org/2000/svg}"
    for v in _views():
        root = ET.fromstring(style_d.render(v)["svg"])
        kids = [el for el in root.iter() if el.tag in (ns + "path", ns + "circle")]
        seen = 0
        for k, el in enumerate(kids):
            i = el.get("id", "")
            if not i.startswith("edge-"):
                continue
            e = v.edges[int(i[5:])]
            color, _ = expected_line(e.status, e.kind)
            head = kids[k + 1]
            if e.status == "loose":
                assert head.tag == ns + "circle" and head.get("fill") == color, (v.title, i)
            else:
                assert head.tag == ns + "path" and head.get("stroke") == color, (v.title, i)
                assert head.get("stroke-dasharray") is None, (v.title, i)
            seen += 1
        assert seen == len(v.edges)
