from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from conftest import OUT, assert_office_safe, fixture_view
from archdiag.render import style_a
from archdiag.views import VEdge, VGroup, VNode, ViewGraph

LEVELS = (("landscape", None), ("application", "claims-online"), ("flow_job", "CLMD100"),
          ("flow_tx", "claims/:id"), ("flow_tx", "CLMI"), ("repomap", None))


def svg_text(svg):
    root = ET.fromstring(svg)
    return " ".join("".join(t.itertext()) for t in root.iter("{http://www.w3.org/2000/svg}text"))


def test_svg_is_office_safe_and_parses():
    out = style_a.render(fixture_view("flow_job", "CLMD100"))
    root = ET.fromstring(out["svg"])
    tags = {el.tag.split("}")[-1] for el in root.iter()}
    assert not tags & {"filter", "style", "use", "marker", "foreignObject", "image"}
    assert "http://" not in out["svg"].replace("http://www.w3.org", "")
    assert "https://" not in out["svg"]
    for level, scope in LEVELS:
        assert_office_safe(style_a.render(fixture_view(level, scope))["svg"])


def _special_view():
    nodes = [VNode("dataset:&&SORTED", "&&SORTED", "temp <dataset>", kind="dataset", group="g1"),
             VNode("program:CLM#01", "CLM#01", "it's \"quoted\"", kind="program", group="g1"),
             VNode("missing:x", "no reader found", "&&SORTED", kind="missing", status="loose")]
    edges = [VEdge("program:CLM#01", "dataset:&&SORTED", "write <&>", number=1),
             VEdge("dataset:&&SORTED", "missing:x", "no reader found", status="loose")]
    return ViewGraph("Job <&> \"x\"", "application", "g1", nodes, edges,
                     [VGroup("g1", "a&b", "#3b82f6")], notes=["note with <&> 'q'"])


def test_special_names_escaped():
    out = style_a.render(_special_view())
    assert_office_safe(out["svg"])
    root = ET.fromstring(out["drawio"])
    values = [c.get("value") or "" for c in root.iter("mxCell")]
    assert any("&&SORTED" in v for v in values) and any("CLM#01" in v for v in values)
    text = svg_text(out["svg"])
    assert "&&SORTED" in text and "CLM#01" in text and "write <&>" in text


def test_every_node_and_label_present():
    for level, scope in LEVELS:
        v = fixture_view(level, scope)
        text = svg_text(style_a.render(v)["svg"])
        flat = text.replace(" ", "")
        for n in v.nodes:
            assert n.label.replace(" ", "") in flat, (level, n.label)
        for e in v.edges:
            if e.label:
                assert e.label.replace(" ", "") in flat, (level, e.label)


def test_numbered_edges_show_circled_digits():
    v = fixture_view("flow_tx", "claims/:id")
    text = svg_text(style_a.render(v)["svg"])
    assert "① uses" in text and "⑳ SEND MAP" in text and "(21) RETURN TRANSID" in text


def test_drawio_parses_and_has_cells():
    for level, scope in LEVELS:
        v = fixture_view(level, scope)
        root = ET.fromstring(style_a.render(v)["drawio"])
        assert root.tag == "mxfile" and root.find("diagram/mxGraphModel/root") is not None
        cells = list(root.iter("mxCell"))
        vertices = [c for c in cells if c.get("vertex") == "1"]
        edges = [c for c in cells if c.get("edge") == "1"]
        assert len(vertices) == len(v.nodes) + len(v.groups), level
        assert len(edges) == len(v.edges)
        ids = {c.get("id") for c in cells}
        assert len(ids) == len(cells)
        for c in edges:
            assert c.get("source") in ids and c.get("target") in ids
            assert c.find("mxGeometry") is not None


def test_drawio_line_styles():
    v = fixture_view("flow_job", "CLMD100")
    root = ET.fromstring(style_a.render(v)["drawio"])
    styles = [c.get("style") for c in root.iter("mxCell") if c.get("edge") == "1"]
    by = {}
    for e, s in zip(v.edges, styles):
        by.setdefault(e.status, []).append(s)
    assert all("dashed=1;dashPattern=3 4;strokeColor=#d97706" in s for s in by["partial"])
    assert all("strokeColor=#dc2626" in s for s in by["loose"])
    assert all("dashed=1" not in s and "strokeColor=#334155" in s for s in by["confirmed"])
    vstyles = {c.get("value", "").split("\n")[0]: c.get("style") for c in root.iter("mxCell")
               if c.get("vertex") == "1"}
    assert "shape=cylinder3" in vstyles["CLMS.CLAIM"]


def test_legend_lists_only_present_statuses():
    text = svg_text(style_a.render(fixture_view("flow_job", "CLMD100"))["svg"])
    assert "confirmed (both ends found in code)" in text
    assert "partly known / suggested" in text
    assert "loose end (only one side found)" in text
    assert "shared code" not in text
    text = svg_text(style_a.render(fixture_view("landscape"))["svg"])
    assert "shared code (copybook, package)" in text


def test_lines_match_certainty():
    v = fixture_view("flow_job", "CLMD100")
    svg = style_a.render(v)["svg"]
    root = ET.fromstring(svg)
    paths = [p for p in root.iter("{http://www.w3.org/2000/svg}path") if p.get("id", "").startswith("edge-")]
    assert len(paths) == len(v.edges)
    for p in paths:
        e = v.edges[int(p.get("id")[5:])]
        want = {"confirmed": "#334155", "partial": "#d97706", "loose": "#dc2626"}[e.status]
        assert p.get("stroke") == want
    dots = [c for c in root.iter("{http://www.w3.org/2000/svg}circle")
            if c.get("fill") == "#dc2626" and c.get("r") == "6"]
    assert len(dots) >= sum(1 for e in v.edges if e.status == "loose")


def test_canvas_holds_everything():
    for level, scope in LEVELS:
        svg = style_a.render(fixture_view(level, scope))["svg"]
        root = ET.fromstring(svg)
        w, h = float(root.get("width")), float(root.get("height"))
        for el in root.iter("{http://www.w3.org/2000/svg}rect"):
            if el.get("id", "").startswith("pill-"):
                x, y = float(el.get("x")), float(el.get("y"))
                assert 0 <= x and x + float(el.get("width")) <= w, level
                assert 0 <= y and y + float(el.get("height")) <= h, level


def test_notes_at_bottom():
    v = fixture_view("flow_job", "CLMD100")
    assert v.notes
    svg = style_a.render(v)["svg"]
    assert "Also exists as: claims-batch/jcl/test/CLMD100.jcl" in svg_text(svg)


def test_writes_samples_for_eyeballing(tmp_path):
    OUT.mkdir(exist_ok=True)
    for level, scope in LEVELS:
        out = style_a.render(fixture_view(level, scope))
        name = "style_a-%s%s" % (level, "-" + re.sub(r"[^A-Za-z0-9]+", "-", scope) if scope else "")
        (OUT / (name + ".svg")).write_text(out["svg"], encoding="utf-8")
        (OUT / (name + ".drawio")).write_text(out["drawio"], encoding="utf-8")
        ET.parse(str(OUT / (name + ".svg")))
