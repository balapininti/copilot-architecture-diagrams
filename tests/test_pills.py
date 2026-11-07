"""Line labels (C2): a pill never lies over a line other than its own; when no spot is
free, the line gets a small numbered marker and the label goes in a key under the
picture."""
from __future__ import annotations

from conftest import fixture_view
from archdiag.layout import Box, Layout, layout_for
from archdiag.render import pills as P
from archdiag.render import style_a, style_b, style_c, style_d
from archdiag.render.common import line_style
from archdiag.views import VEdge, VNode, ViewGraph

LEVELS = (("landscape", None), ("application", "claims-online"), ("flow_job", "CLMD100"),
          ("flow_tx", "claims/:id"), ("flow_tx", "CLMI"), ("repomap", None))


def _seg_in_rect(a, b, rect):
    """Does segment a-b pass through the inside of rect (Liang-Barsky clip)?"""
    x, y, w, h = rect
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - x), (dx, x + w - a[0]), (-dy, a[1] - y), (dy, y + h - a[1])):
        if abs(p) < 1e-12:
            if q <= 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
    return t0 < t1


def _placed(mod, v):
    L = layout_for(v, mod.node_size)
    styles = [line_style(e.status, e.kind) for e in v.edges]
    if mod is style_a:
        routes = style_a.draw_routes(v, L)
        return routes, style_a.place_pills(v, L, styles, routes)
    routes = [list(r) for r in L.routes]
    text = {style_b: style_b._edge_text, style_c: lambda e: e.label,
            style_d: style_d._edge_text}[mod]
    zone = {style_b: style_b._title_zone, style_c: lambda g, gb: None,
            style_d: style_d._title_zone}[mod]
    return routes, P.place_pills(v, L, styles, routes, text, zone)


def test_no_label_lies_over_another_line():
    for level, scope in LEVELS:
        v = fixture_view(level, scope)
        for mod in (style_a, style_b, style_c, style_d):
            routes, pills = _placed(mod, v)
            for p in pills:
                rect = (p.x + 1, p.y + 1, p.w - 2, p.h - 2)
                if p.marker and not _free_marker_spot_exists(p, routes):
                    continue  # no spot on its line is clear: the least crowded is taken
                for j, r in enumerate(routes):
                    if j == p.i:
                        continue
                    for a, b in zip(r, r[1:]):
                        assert not _seg_in_rect(a, b, rect), (
                            level, mod.__name__, v.edges[p.i].label, v.edges[j].label)


def _free_marker_spot_exists(p, routes):
    """Is there a point on the marker's line (every 1px, off its ends) where a marker of
    its size lies over no other line?"""
    r = routes[p.i]
    segs = [(a, b) for j, q in enumerate(routes) if j != p.i for a, b in zip(q, q[1:])]
    length = sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(r, r[1:]))
    for k in range(int(length * 0.08), int(length * 0.92)):
        (x, y), _ = P.seg_at(r, k / length)
        rect = (x - p.w / 2 + 1, y - p.h / 2 + 1, p.w - 2, p.h - 2)
        if not any(_seg_in_rect(a, b, rect) for a, b in segs):
            return True
    return False


def _crowded_view():
    nodes = [VNode("a", "a"), VNode("b", "b")]
    edges = [VEdge("a", "b", "LONG LABEL TEXT")]
    boxes = {"a": Box(0, 40, 60, 40), "b": Box(300, 40, 60, 40)}
    routes = [[(60.0, 60.0), (300.0, 60.0)]]
    xs = list(range(100, 197, 8)) + list(range(232, 297, 8))
    for k, x in enumerate(xs):
        c, d = "c%d" % k, "d%d" % k
        nodes += [VNode(c, c), VNode(d, d)]
        edges.append(VEdge(c, d, ""))
        boxes[c] = Box(x - 3, -320, 6, 20)
        boxes[d] = Box(x - 3, 400, 6, 20)
        routes.append([(float(x), -300.0), (float(x), 400.0)])
    v = ViewGraph("t", "application", None, nodes, edges, [])
    L = Layout(400, 800, boxes, {}, routes, [P.seg_at(r, 0.5)[0] for r in routes])
    return v, L, routes


def test_no_free_spot_gives_a_marker_and_a_key_entry():
    v, L, routes = _crowded_view()
    pills = P.place_pills(v, L, ["confirmed"] * len(v.edges), routes, lambda e: e.label,
                          lambda g, gb: None)
    assert len(pills) == 1
    p = pills[0]
    assert p.marker and p.key == 1
    # the marker sits on its own line, in the free stretch, over no other line
    assert abs(p.y + p.h / 2 - 60) < 0.01 and 196 < p.x and p.x + p.w < 232
    svg, h = P.key_svg(pills, 30, 500, 600)
    assert h > 0 and "LONG LABEL TEXT" in svg and 'id="key-1"' in svg
    assert 'id="mark-1"' in p.svg(0, 0)


def test_markers_in_every_style_are_keyed():
    """Every style draws a marker's label in the key under the picture."""
    import xml.etree.ElementTree as ET
    for level, scope in LEVELS:
        v = fixture_view(level, scope)
        for mod in (style_a, style_b, style_c, style_d):
            _, pills = _placed(mod, v)
            svg = mod.render(v)["svg"]
            text = " ".join(t.text or "" for t in ET.fromstring(svg).iter(
                "{http://www.w3.org/2000/svg}text"))
            for p in pills:
                if p.marker:
                    assert " ".join(p.lines) in text, (level, mod.__name__)


def _keyed(mod, v):
    return [p for p in _placed(mod, v)[1] if p.marker]


def test_channel_and_bundle_lines_carry_their_own_labels():
    """E1: channel lanes are a pill apart and a gap with a bundle of bends keeps a free
    stretch before the targets, so the claims/:id page flow keys few labels (it keyed 18
    over the four styles) and never a line running along the channel between bands."""
    v = fixture_view("flow_tx", "claims/:id")
    total = 0
    for mod in (style_a, style_b, style_c, style_d):
        keyed = _keyed(mod, v)
        total += len(keyed)
        assert len(keyed) <= 2, (mod.__name__, [v.edges[p.i].label for p in keyed])
        for p in keyed:
            e = v.edges[p.i]
            assert not (e.src.startswith("class:claims-api") and "claims-online" in e.dst
                        or e.dst.startswith(("queue:", "zosapi:"))), (mod.__name__, e.label)
    assert total <= 4, total


def _rect_gap(a, b, rect):
    """Least distance from segment a-b to rect (sampled every px)."""
    x, y, w, h = rect
    n = max(1, int(abs(b[0] - a[0]) + abs(b[1] - a[1])))
    best = float("inf")
    for k in range(n + 1):
        px, py = a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n
        dx, dy = max(x - px, 0, px - x - w), max(y - py, 0, py - y - h)
        best = min(best, (dx * dx + dy * dy) ** 0.5)
    return best


def test_markers_keep_clear_of_other_lines():
    """E1: a marker sits where it keeps at least 4px from every other line (it had 2px
    on lines 10px apart)."""
    for level, scope in LEVELS:
        v = fixture_view(level, scope)
        for mod in (style_a, style_b, style_c, style_d):
            routes, pills = _placed(mod, v)
            for p in pills:
                if not p.marker:
                    continue
                rect = (p.x, p.y, p.w, p.h)
                gap = min([_rect_gap(a, b, rect) for j, r in enumerate(routes) if j != p.i
                           for a, b in zip(r, r[1:])] or [99.0])
                assert gap >= 4.0, (level, mod.__name__, v.edges[p.i].label, gap)


def test_a_line_free_pill_beats_a_marker_that_touches_a_line():
    """E4: the marker replaces the pill only on fewer other-line hits, or on equal (zero)
    hits and less box overlap: a marker touching a line never beats a line-free pill
    that overlaps a box more."""
    # costs are (box/end overlap, other-line hits)
    assert not P.prefer_marker(pill=(120.0, 0.0), marker=(0.0, 1.0))
    assert P.prefer_marker(pill=(0.0, 1.0), marker=(500.0, 1.0))  # a pill on a line: never
    assert P.prefer_marker(pill=(0.0, 2.0), marker=(0.0, 0.0))
    assert P.prefer_marker(pill=(120.0, 0.0), marker=(10.0, 0.0))
    assert not P.prefer_marker(pill=(10.0, 0.0), marker=(120.0, 0.0))


def _crossings_of(i, routes):
    """Points where line i crosses another line: (point, other line)."""
    out = []
    for j, r in enumerate(routes):
        if j == i:
            continue
        for p1, p2 in zip(routes[i], routes[i][1:]):
            for p3, p4 in zip(r, r[1:]):
                d = (p2[0] - p1[0]) * (p4[1] - p3[1]) - (p2[1] - p1[1]) * (p4[0] - p3[0])
                if abs(d) < 1e-9:
                    continue
                t = ((p3[0] - p1[0]) * (p4[1] - p3[1]) - (p3[1] - p1[1]) * (p4[0] - p3[0])) / d
                u = ((p3[0] - p1[0]) * (p2[1] - p1[1]) - (p3[1] - p1[1]) * (p2[0] - p1[0])) / d
                if 0 < t < 1 and 0 < u < 1:
                    out.append(((p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])), j))
    return out


def test_job_flow_pills_keep_off_crossings():
    """E6: on the CLMD100 job flow no pill sits at a crossing of its line with another
    (within 8px), where "write" and "read (0)" under CLMB300/IEBGENER could be read as
    either line's: the row moves further off the lane and the pill away from the X."""
    v = fixture_view("flow_job", "CLMD100")
    for mod in (style_a, style_b, style_c, style_d):
        routes, pills = _placed(mod, v)
        for p in pills:
            if p.marker:
                continue
            for (x, y), j in _crossings_of(p.i, routes):
                assert not (p.x - 8 < x < p.x + p.w + 8 and p.y - 8 < y < p.y + p.h + 8), \
                    (mod.__name__, v.edges[p.i].label, v.edges[j].label)


def test_key_wraps_a_label_wider_than_the_key():
    """E9: key_entries is public; one label wider than the key wraps onto more rows
    (inside the width), and the next entry starts below it."""
    long = P.Pill(0, "dataset " + "VERY.LONG.QUALIFIER." * 12 + "END", (0, 0), "confirmed")
    long.as_marker((0, 0))
    long.key = 1
    short = P.Pill(1, "reads", (0, 0), "partial")
    short.as_marker((0, 0))
    short.key = 2
    entries = P.key_entries([long, short], 400.0)
    (p1, lines1, x1, row1), (p2, lines2, x2, row2) = entries
    assert len(lines1) > 1 and "".join(lines1).replace(" ", "") == \
        " ".join(long.lines).replace(" ", "")
    from archdiag.render.common import text_width
    assert all(2 * P.KEY_R + 8 + text_width(s, P.KEY_SIZE) <= 400.0 for s in lines1)
    assert row2 >= row1 + len(lines1)
    svg, h = P.key_svg([long, short], 30, 0, 400.0)
    assert h >= 18 + P.KEY_LINE * (row2 + 1)


def _on_route(c, r):
    for a, b in zip(r, r[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0.0, min(1.0, ((c[0] - a[0]) * dx + (c[1] - a[1]) * dy) / (dx * dx + dy * dy or 1)))
        if ((a[0] + t * dx - c[0]) ** 2 + (a[1] + t * dy - c[1]) ** 2) ** 0.5 < 1.0:
            return True
    return False


def test_the_clearance_preference_never_moves_a_pill_off_a_free_spot_on_its_line():
    """E6 follow-up: keeping clear of other lines is weighed only between spots on the
    line (or only between spots beside it): a pill goes beside its line only when no spot
    on it is free. In the landscape every pill sits on its own line (the "SQL" pill had
    moved beside it)."""
    v = fixture_view("landscape", None)
    for mod in (style_a, style_b, style_c, style_d):
        routes, pills = _placed(mod, v)
        off = [v.edges[p.i].label for p in pills
               if not p.marker and not _on_route((p.x + p.w / 2, p.y + p.h / 2), routes[p.i])]
        assert not off, (mod.__name__, off)
