from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from conftest import OUT, assert_office_safe, fixture_view
from archdiag.layout import layout_for
from archdiag.render import style_a
from archdiag.render.common import line_style
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


def test_numbered_edges_show_a_drawn_circle_for_every_step():
    """C4: every step number is a small circle with the number as text (the same for 1 and
    for 21), never a Unicode circled digit or a "(21)" fallback."""
    from archdiag.render import style_b, style_c, style_d
    v = fixture_view("flow_tx", "claims/:id")
    numbers = sorted(e.number for e in v.edges if e.number is not None)
    assert numbers and numbers[-1] > 20
    for mod in (style_a, style_b, style_d):
        svg = mod.render(v)["svg"]
        root = ET.fromstring(svg)
        ns = "{http://www.w3.org/2000/svg}"
        marks = [el for el in root.iter(ns + "g") if el.get("id", "").startswith("step-")]
        got = sorted(int(el.get("id")[5:]) for el in marks)
        assert got == numbers, mod.__name__
        for el in marks:
            kids = list(el)
            assert kids[0].tag == ns + "circle" and kids[1].tag == ns + "text"
            assert kids[1].text == el.get("id")[5:]
        text = svg_text(svg)
        assert not any(chr(c) in text for c in range(0x2460, 0x2474)), mod.__name__
        assert "(21)" not in text and "RETURN TRANSID" in text
    # the text-only copies write every number the same way
    out = style_a.render(v)["drawio"] + style_b.render(v)["md"]
    assert "(1) uses" in out and "(21) RETURN TRANSID" in out
    assert not any(chr(c) in out for c in range(0x2460, 0x2474))


def test_drawio_parses_and_has_cells():
    for level, scope in LEVELS:
        v = fixture_view(level, scope)
        root = ET.fromstring(style_a.render(v)["drawio"])
        assert root.tag == "mxfile" and root.find("diagram/mxGraphModel/root") is not None
        cells = list(root.iter("mxCell"))
        vertices = [c for c in cells if c.get("vertex") == "1" and not c.get("id").startswith("lg-")]
        edges = [c for c in cells if c.get("edge") == "1" and not c.get("id").startswith("lg-")]
        L = layout_for(v, style_a.node_size)
        # one container per group drawn (Layout.groups), as in the SVG
        assert len(vertices) == len(v.nodes) + len(L.groups), level
        assert len(edges) == len(v.edges)
        ids = {c.get("id") for c in cells}
        assert len(ids) == len(cells)
        for c in edges:
            assert c.get("source") in ids and c.get("target") in ids
            assert c.find("mxGeometry") is not None


def test_drawio_line_styles():
    v = fixture_view("flow_job", "CLMD100")
    root = ET.fromstring(style_a.render(v)["drawio"])
    styles = [c.get("style") for c in root.iter("mxCell")
              if c.get("edge") == "1" and not c.get("id").startswith("lg-")]
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


@pytest.mark.parametrize("level,scope", [("flow_job", "CLMD100"),
                                         ("application", "claims-online")])
def test_lines_match_certainty(level, scope):
    v = fixture_view(level, scope)
    svg = style_a.render(v)["svg"]
    root = ET.fromstring(svg)
    paths = [p for p in root.iter("{http://www.w3.org/2000/svg}path") if p.get("id", "").startswith("edge-")]
    assert len(paths) == len(v.edges)
    for p in paths:
        e = v.edges[int(p.get("id")[5:])]
        want = {"confirmed": "#334155", "partial": "#d97706", "loose": "#dc2626"}[e.status]
        if e.status == "confirmed" and e.kind == "shared_code":
            want = "#a16207"
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


def _inside(pt, rect, pad=0.0):
    x, y, w, h = rect
    return x - pad <= pt[0] <= x + w + pad and y - pad <= pt[1] <= y + h + pad


def test_no_pill_covers_a_line_end():
    for level, scope in LEVELS:
        v = fixture_view(level, scope)
        L = layout_for(v, style_a.node_size)
        routes = style_a.draw_routes(v, L)
        pills = style_a.place_pills(v, L, [line_style(e.status, e.kind) for e in v.edges],
                                    routes)
        rects = [(p.x, p.y, p.w, p.h) for p in pills]
        for k, r in enumerate(routes):
            (xa, ya), (xb, yb) = r[-2], r[-1]
            d = ((xb - xa) ** 2 + (yb - ya) ** 2) ** 0.5 or 1.0
            ends = [r[0], r[-1]]
            # the last 14px before the end, and the arrowhead or dot around it
            ends += [(xb - (xb - xa) / d * t, yb - (yb - ya) / d * t)
                     for t in (2, 5, 8, 11, 14) if t <= d]
            ends += [(xb + dx, yb + dy) for dx in (-6, 6) for dy in (-6, 6)]
            for rect in rects:
                for pt in ends:
                    assert not _inside(pt, rect), (level, v.edges[k].label, pt, rect)


def _crosses(a, b, rect):
    """Does segment a-b pass through the inside of rect (axis-aligned or not)?"""
    x, y, w, h = rect
    for t in [i / 40.0 for i in range(41)]:
        px, py = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        if x + 1 < px < x + w - 1 and y + 1 < py < y + h - 1:
            return True
    return False


def test_no_line_runs_through_a_foreign_group():
    for level, scope in LEVELS:
        v = fixture_view(level, scope)
        L = layout_for(v, style_a.node_size)
        for k, (e, r) in enumerate(zip(v.edges, L.routes)):
            for gid, g in L.groups.items():
                rect = (g.x, g.y, g.w, g.h)
                sb, db = L.boxes[e.src], L.boxes[e.dst]
                if _inside((sb.cx, sb.cy), rect) or _inside((db.cx, db.cy), rect):
                    continue
                for a, b in zip(r, r[1:]):
                    assert not _crosses(a, b, rect), (level, e.src, e.dst, gid)


def test_landscape_is_not_a_tall_strip():
    root = ET.fromstring(style_a.render(fixture_view("landscape"))["svg"])
    w, h = float(root.get("width")), float(root.get("height"))
    assert h <= 1.2 * w, (w, h)


def test_drawio_draws_only_laid_out_groups():
    v = ViewGraph("job", "flow_job", "J",
                  [VNode("job:J", "J", kind="job", group="g1"),
                   VNode("step:J#S1", "S1", kind="program", row="lane", group="g1")],
                  [VEdge("job:J", "step:J#S1", kind="sequence")],
                  [VGroup("g1", "app", "#3b82f6")])
    out = style_a.render(v)
    root = ET.fromstring(out["drawio"])
    assert len([c for c in root.iter("mxCell") if c.get("vertex") == "1"
                and not c.get("id").startswith("lg-")]) == 2
    assert "app" not in svg_text(out["svg"])


def test_drawio_partial_missing_box_matches_svg():
    v = fixture_view("application", "claims-online")
    root = ET.fromstring(style_a.render(v)["drawio"])
    styles = {c.get("value", "").split("\n")[0]: c.get("style") for c in root.iter("mxCell")}
    assert "fillColor=#fffbeb" in styles["which program?"]
    assert "fillColor=#fef2f2" in styles["CLMO120"]


def _shared_vertical_runs(routes, longest=200.0):
    """Pairs of lines that run along the same vertical line for more than ``longest``."""
    verts = []
    for k, r in enumerate(routes):
        for (x0, y0), (x1, y1) in zip(r, r[1:]):
            if abs(x0 - x1) < 1e-6:
                verts.append((k, x0, min(y0, y1), max(y0, y1)))
    bad = []
    for i in range(len(verts)):
        for j in range(i + 1, len(verts)):
            a, b = verts[i], verts[j]
            if a[0] != b[0] and abs(a[1] - b[1]) < 1.0 \
                    and min(a[3], b[3]) - max(a[2], b[2]) > longest:
                bad.append((a, b))
    return bad


def test_application_is_a_context_picture():
    v = fixture_view("application", "claims-online")
    root = ET.fromstring(style_a.render(v)["svg"])
    w, h = float(root.get("width")), float(root.get("height"))
    assert h <= 1.3 * w, (w, h)
    L = layout_for(v, style_a.node_size)
    assert not _shared_vertical_runs(L.routes)
    # outside boxes sit in columns left and right of the application's group
    g = L.groups["group:claims-online"]
    for n in v.nodes:
        if not n.group:
            b = L.boxes[n.id]
            assert b.right < g.x or b.x > g.x + g.w, n.id


def test_job_loose_stub_hangs_off_its_dataset():
    v = fixture_view("flow_job", "CLMD100")
    L = layout_for(v, style_a.node_size)
    routes = style_a.draw_routes(v, L)
    for e, r in zip(v.edges, routes):
        if e.dst.startswith("missing:") and e.status == "loose":
            src = L.boxes[e.src]
            # the stub starts at the source's picture, not past the end of its label
            assert abs(r[0][0] - src.cx) <= 40 and src.y < r[0][1] < src.y + 70, (e.src, r)
