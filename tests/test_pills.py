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
