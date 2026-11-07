from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from archdiag.layout import Box, Layout, layout_for
from archdiag.views import VEdge, VGroup, VNode, ViewGraph

from layout_helpers import (app_with_neighbors, claims_job, claims_landscape, contains,
                            count_crossings, crossing_bait, debug_svg, foreign_box_in_group,
                            graph_with_cycle, no_box_overlaps, on_border, random_view,
                            repomap_of)

OUT = Path(__file__).parent / "out"


def _routes_on_borders(v, L):
    assert len(L.routes) == len(v.edges) and len(L.label_at) == len(v.edges)
    for e, r in zip(v.edges, L.routes):
        assert len(r) >= 2
        assert on_border(r[0], L.boxes[e.src]), (e.src, e.dst, r)
        assert on_border(r[-1], L.boxes[e.dst]), (e.src, e.dst, r)


def _inside_canvas(L):
    for b in list(L.boxes.values()) + list(L.groups.values()):
        assert b.x >= 0 and b.y >= 0 and b.x + b.w <= L.width and b.y + b.h <= L.height
    for r in L.routes:
        for x, y in r:
            assert 0 <= x <= L.width and 0 <= y <= L.height


def test_layered_no_overlaps_and_left_to_right():
    v = claims_landscape()
    L = layout_for(v, lambda n: (170, 90))
    assert isinstance(L, Layout) and all(isinstance(b, Box) for b in L.boxes.values())
    assert no_box_overlaps(L.boxes, margin=20)
    _routes_on_borders(v, L)
    assert L.boxes["app:portal"].x < L.boxes["app:api"].x < L.boxes["queue:CLM.REQ"].x
    _inside_canvas(L)


def test_groups_enclose_members():
    v = claims_landscape()
    L = layout_for(v, lambda n: (170, 90))
    for n in v.nodes:
        if n.group:
            assert contains(L.groups[n.group], L.boxes[n.id])


def test_groups_do_not_overlap_each_other():
    v = claims_landscape()
    L = layout_for(v, lambda n: (170, 90))
    assert no_box_overlaps(L.groups, margin=0)


def test_group_across_layers_keeps_outsiders_out():
    v = app_with_neighbors()
    L = layout_for(v, lambda n: (150, 80))
    assert no_box_overlaps(L.boxes, margin=20)
    _routes_on_borders(v, L)
    for n in v.nodes:
        if n.group:
            assert contains(L.groups[n.group], L.boxes[n.id])
    assert not foreign_box_in_group(v, L)


def test_random_graphs_keep_invariants():
    for seed in range(120):
        v = random_view(seed)
        L = layout_for(v, lambda n: (100 + 35 * (len(n.id) % 3), 60 + 30 * (len(n.id) % 2)))
        assert no_box_overlaps(L.boxes, margin=10), seed
        _routes_on_borders(v, L)
        _inside_canvas(L)
        for n in v.nodes:
            if n.group:
                assert contains(L.groups[n.group], L.boxes[n.id]), seed
        assert not foreign_box_in_group(v, L), seed
        assert no_box_overlaps(L.groups, margin=0), seed


def test_dense_graph_is_fast():
    import random
    import time
    R = random.Random(1)
    nodes = [VNode("n%d" % i, "n%d" % i, group="g%d" % (i % 6) if i % 3 else None)
             for i in range(40)]
    edges = [VEdge("n%d" % i, "n%d" % (i + 1)) for i in range(39)]
    edges += [VEdge("n%d" % R.randrange(40), "n%d" % R.randrange(40)) for _ in range(300)]
    v = ViewGraph("dense", "application", None, nodes, edges,
                  [VGroup("g%d" % i, "g%d" % i, "#000000") for i in range(6)])
    t = time.perf_counter()
    L = layout_for(v, lambda n: (150, 80))
    # a generous bound: it catches a blow-up (minutes), not a slow or busy machine
    assert time.perf_counter() - t < 60
    assert len(L.routes) == len(edges)


def test_rejects_edges_to_unknown_nodes():
    v = graph_with_cycle()
    v.edges.append(VEdge("A", "nowhere"))
    with pytest.raises(ValueError):
        layout_for(v, lambda n: (100, 60))


def test_cycles_do_not_hang():
    v = graph_with_cycle()
    L = layout_for(v, lambda n: (100, 60))
    assert len(L.boxes) == len(v.nodes)
    _routes_on_borders(v, L)


def test_job_rows():
    v = claims_job()
    L = layout_for(v, lambda n: (140, 80))
    lane_y = {L.boxes[n.id].y for n in v.nodes if n.row == "lane"}
    assert len(lane_y) == 1
    assert all(L.boxes[n.id].y < min(lane_y) for n in v.nodes if n.row == "above")
    assert all(L.boxes[n.id].y > min(lane_y) for n in v.nodes if n.row == "below")
    steps = [n for n in v.nodes if n.row == "lane"]
    assert [L.boxes[s.id].x for s in steps] == sorted(L.boxes[s.id].x for s in steps)
    assert no_box_overlaps(L.boxes, margin=20)
    _routes_on_borders(v, L)
    _inside_canvas(L)


def test_job_data_sits_over_its_step():
    v = claims_job()
    L = layout_for(v, lambda n: (140, 80))
    cx = lambda i: L.boxes[i].x + L.boxes[i].w / 2  # noqa: E731
    assert cx("table:CLAIM") == cx("step:CLMD100.STEP020")
    # written by STEP020, read by STEP030: between them (spread may nudge it off the mean)
    assert cx("step:CLMD100.STEP020") <= cx("dataset:PROD.CLAIMS.DAILY") \
        < cx("step:CLMD100.STEP030")


def test_repomap_card_grid_no_overlaps():
    v = repomap_of(6)
    L = layout_for(v, lambda n: (260, 150))
    assert no_box_overlaps(L.boxes, 40)
    _routes_on_borders(v, L)
    assert all(len(r) == 12 for r in L.routes)
    # the hub (most links) is in the middle of the 3-column grid
    xs = sorted({b.x for b in L.boxes.values()})
    assert L.boxes["repo:r0"].x == xs[1]
    _inside_canvas(L)


def test_crossings_reduced():
    v = crossing_bait()
    L = layout_for(v, lambda n: (100, 60))
    assert count_crossings(v, L) <= 1


def test_empty_view():
    v = ViewGraph("empty", "landscape", None, [], [], [])
    L = layout_for(v, lambda n: (100, 60))
    assert L.boxes == {} and L.routes == [] and L.width > 0 and L.height > 0


def test_writes_debug_svg(tmp_path):
    OUT.mkdir(exist_ok=True)
    cases = [("landscape", claims_landscape(), (170, 90)),
             ("flow_job", claims_job(), (140, 80)),
             ("application", app_with_neighbors(), (150, 80)),
             ("repomap", repomap_of(6), (260, 150))]
    for name, v, size in cases:
        L = layout_for(v, lambda n, s=size: s)
        svg = debug_svg(v, L)
        root = ET.fromstring(svg)
        tags = {el.tag.split("}")[-1] for el in root.iter()}
        assert tags <= {"svg", "rect", "polyline"}
        (OUT / ("layout-%s.svg" % name)).write_text(svg, encoding="utf-8")
        if name == "landscape":
            (tmp_path / "landscape.svg").write_text(svg, encoding="utf-8")
            ET.parse(str(tmp_path / "landscape.svg"))


def test_context_keeps_a_loose_end_next_to_its_outside_box():
    from archdiag.layout import layout_for as lf
    v = app_with_neighbors()
    v.nodes.append(VNode("missing:writer:CLAIM", "no writer found", kind="missing",
                         status="loose"))
    v.edges.append(VEdge("table:CLAIM", "missing:writer:CLAIM", "no writer found",
                         status="loose"))
    L = lf(v, lambda n: (150, 80))
    assert no_box_overlaps(L.boxes, margin=20)
    _routes_on_borders(v, L)
    g = L.groups["app:claims-online"]
    for n in v.nodes:
        if n.group:
            assert contains(g, L.boxes[n.id])
        else:  # outside boxes stand in a column left or right of the application
            b = L.boxes[n.id]
            assert b.x + b.w < g.x or b.x > g.x + g.w, n.id
    col = sorted((b.y, k) for k, b in L.boxes.items() if L.boxes[k].x > g.x + g.w)
    names = [k for _, k in col]
    # nothing stands between the table and its loose end but other boxes hanging off it
    between = names[names.index("table:CLAIM") + 1:names.index("missing:writer:CLAIM")]
    hangers = {e.src for e in v.edges if e.dst == "table:CLAIM"}
    assert set(between) <= hangers, between


# ------------------------------------------------------------------ Batch C

def _random_repomap(seed):
    import random
    R = random.Random(seed)
    n = R.randint(4, 12)
    ids = ["repo:r%d" % i for i in range(n)]
    edges = [VEdge(R.choice(ids), R.choice(ids), "x") for _ in range(R.randint(n, 3 * n))]
    edges = [e for e in edges if e.src != e.dst]
    return ViewGraph("t", "repomap", None, [VNode(i, i, kind="repo") for i in ids], edges, [])


def test_card_grid_keeps_the_hub_in_the_middle():
    """C7: swapping cards to shorten links never moves the most linked card off centre."""
    import math
    from archdiag.layout import CARD_COL_GAP, CARD_ROW_GAP, card_grid
    for seed in range(60):
        v = _random_repomap(seed)
        ids = [n.id for n in v.nodes]
        deg = {i: 0 for i in ids}
        for e in v.edges:
            deg[e.src] += 1
            deg[e.dst] += 1
        hub = sorted(ids, key=lambda i: (-deg[i], ids.index(i)))[0]
        boxes, _ = card_grid(v, {i: (200.0, 100.0) for i in ids})
        cols = int(math.ceil(math.sqrt(len(ids))))
        rows = int(math.ceil(len(ids) / float(cols)))
        b = boxes[hub]
        c, r = b.x / (200 + CARD_COL_GAP), b.y / (100 + CARD_ROW_GAP)
        mid_r, mid_c = (rows - 1) / 2.0, (cols - 1) / 2.0
        best = min((rr - mid_r) ** 2 + (cc - mid_c) ** 2 for rr in range(rows)
                   for cc in range(cols))
        assert abs((r - mid_r) ** 2 + (c - mid_c) ** 2 - best) < 1e-6, seed


def test_cards_hit_samples_every_10px():
    """C7: a curve segment that passes through a small card between its sample points
    still counts as hitting it."""
    from archdiag.layout import _cards_hit
    card = Box(141, -10, 14, 20)  # a narrow card well clear of 0, 0.5 and 1 of the segment
    assert _cards_hit([(0.0, 0.0), (400.0, 0.0)], [card]) == 1


def test_job_and_repomap_views_set_no_groups():
    """C8: job rows and card grids do not arrange by group (Layout.groups stays empty), so
    the views for those levels must not carry any: a group there would silently vanish."""
    from conftest import fixture_view
    for level, scope in (("flow_job", "CLMD100"), ("repomap", None)):
        v = fixture_view(level, scope)
        assert v.groups == [] and not any(n.group for n in v.nodes), level
        assert layout_for(v, lambda n: (100, 60)).groups == {}


def test_context_anchors_a_loose_end_next_to_its_left_column_source():
    """C11: a missing box fed only by a left-column box stands right next to that box in
    its column, not at the bottom of the right column."""
    v = app_with_neighbors()
    v.nodes.append(VNode("missing:reader:X", "no reader found", kind="missing",
                         status="loose"))
    v.edges.append(VEdge("queue:CLM.REQ.LQ", "missing:reader:X", "no reader found",
                         status="loose"))
    L = layout_for(v, lambda n: (150, 80))
    assert no_box_overlaps(L.boxes, margin=20)
    _routes_on_borders(v, L)
    src, miss = L.boxes["queue:CLM.REQ.LQ"], L.boxes["missing:reader:X"]
    g = L.groups["app:claims-online"]
    assert miss.x + miss.w < g.x  # the left column, with its source
    col = sorted((b.y, k) for k, b in L.boxes.items() if b.x + b.w < g.x)
    names = [k for _, k in col]
    assert abs(names.index("missing:reader:X") - names.index("queue:CLM.REQ.LQ")) == 1


def _crosses_box(route, box, pad=2.0):
    """Does the polyline pass through the inside of ``box`` (sampled every 2px)?"""
    for (x0, y0), (x1, y1) in zip(route, route[1:]):
        n = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) / 2))
        for k in range(n + 1):
            x, y = x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n
            if box.x + pad < x < box.x + box.w - pad and box.y + pad < y < box.y + box.h - pad:
                return True
    return False


def test_job_rows_stagger_step_skipping_lines():
    """C6: lines that skip steps (or go back) each run at their own height above the lane,
    clear of the boxes above it."""
    v = claims_job()
    v.edges += [VEdge("step:CLMD100.STEP010", "step:CLMD100.STEP030", "skip"),
                VEdge("step:CLMD100.STEP020", "step:CLMD100.STEP040", "skip"),
                VEdge("step:CLMD100.STEP010", "step:CLMD100.STEP040", "skip"),
                VEdge("step:CLMD100.STEP040", "step:CLMD100.STEP020", "again")]
    L = layout_for(v, lambda n: (140, 80))
    runs = []
    for k in range(len(v.edges) - 4, len(v.edges)):
        r = L.routes[k]
        assert len(r) == 4
        runs.append((r[1][1], min(r[1][0], r[2][0]), max(r[1][0], r[2][0])))
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            (ya, la, ha), (yb, lb, hb) = runs[i], runs[j]
            if min(ha, hb) > max(la, lb):  # they run side by side: keep apart
                assert abs(ya - yb) >= 8, (runs[i], runs[j])
    for k in range(len(v.edges)):
        e = v.edges[k]
        for nid, b in L.boxes.items():
            if nid not in (e.src, e.dst):
                assert not _crosses_box(L.routes[k], b), (e.src, e.dst, nid)


def test_job_rows_route_row_lines_around_boxes():
    """C6: a line between the rows and a box outside the lane (the job, the scheduler, a
    box in the same row) goes around the boxes between them."""
    v = claims_job()
    v.edges += [VEdge("dataset:PROD.CLAIMS.DAILY", "job:CLMD100", "x"),
                VEdge("table:PAYMENT", "dataset:PROD.CLAIMS.EXTRACT", "y"),
                VEdge("dataset:CLM.MASTER.KSDS", "table:PAYMENT", "z")]
    L = layout_for(v, lambda n: (140, 80))
    _routes_on_borders(v, L)
    for k, e in enumerate(v.edges):
        for nid, b in L.boxes.items():
            if nid not in (e.src, e.dst):
                assert not _crosses_box(L.routes[k], b), (e.src, e.dst, nid)


FIXTURE_LEVELS = (("landscape", None), ("application", "claims-online"), ("flow_job", "CLMD100"),
                  ("flow_tx", "claims/:id"), ("flow_tx", "CLMI"), ("repomap", None))


def _style_sizes():
    from archdiag.render import style_a, style_b, style_c, style_d
    return [m.node_size for m in (style_a, style_b, style_c, style_d)]


def shared_runs(routes, horizontal=True, near=8.0, longest=200.0):
    """Pairs of different lines whose horizontal (or vertical) runs lie within ``near`` px
    of each other along more than ``longest`` px."""
    runs = []
    for k, r in enumerate(routes):
        for (x0, y0), (x1, y1) in zip(r, r[1:]):
            if horizontal and abs(y0 - y1) < 1e-6:
                runs.append((k, y0, min(x0, x1), max(x0, x1)))
            elif not horizontal and abs(x0 - x1) < 1e-6:
                runs.append((k, x0, min(y0, y1), max(y0, y1)))
    bad = []
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            a, b = runs[i], runs[j]
            if a[0] != b[0] and abs(a[1] - b[1]) <= near \
                    and min(a[3], b[3]) - max(a[2], b[2]) > longest:
                bad.append((a, b))
    return bad


def test_no_two_lines_share_a_horizontal_run():
    """C1: two lines never run side by side within 8px for more than 200px."""
    from conftest import fixture_view
    views = [fixture_view(lv, sc) for lv, sc in FIXTURE_LEVELS]
    views += [claims_landscape(), app_with_neighbors(), claims_job()]
    for v in views:
        for size in _style_sizes():
            L = layout_for(v, size)
            assert not shared_runs(L.routes), (v.title, size.__module__)


def _side_gaps(v, L):
    """The least gap between two line ends on one side of one box."""
    ends = {}
    for e, r in zip(v.edges, L.routes):
        if e.src == e.dst:
            continue
        for nid, p in ((e.src, r[0]), (e.dst, r[-1])):
            b = L.boxes[nid]
            side = ("l" if abs(p[0] - b.x) < .5 else "r" if abs(p[0] - b.x - b.w) < .5
                    else "t" if abs(p[1] - b.y) < .5 else "b")
            ends.setdefault((nid, side), []).append(p[1] if side in "lr" else p[0])
    least = float("inf")
    for xs in ends.values():
        xs.sort()
        least = min([least] + [b - a for a, b in zip(xs, xs[1:])])
    return least


def test_layered_fan_out_spreads_ports_and_gaps():
    """C5: in layered views a busy box side sends lines out of its top and bottom too, and
    column gaps widen, so line ends stay apart and no two lines run down one gap within
    8px of each other for more than 200px."""
    from conftest import fixture_view
    for lv, sc in (("landscape", None), ("flow_tx", "claims/:id"), ("flow_tx", "CLMI")):
        v = fixture_view(lv, sc)
        for size in _style_sizes():
            L = layout_for(v, size)
            assert _side_gaps(v, L) >= 8.0, (lv, sc, size.__module__, _side_gaps(v, L))
            assert not shared_runs(L.routes, horizontal=False), (lv, sc, size.__module__)


def test_wide_flow_wraps_into_bands():
    """C3: a layered view wider than 2000px wraps its layers into bands; the claims/:id
    page flow fits in 2200px in every style, with every line still border to border."""
    import re
    from conftest import fixture_view
    from archdiag.render import style_a, style_b, style_c, style_d
    v = fixture_view("flow_tx", "claims/:id")
    for mod in (style_a, style_b, style_c, style_d):
        svg = mod.render(v)["svg"]
        w = float(re.search(r'width="([\d.]+)"', svg).group(1))
        assert w <= 2200, (mod.__name__, w)
        L = layout_for(v, mod.node_size)
        _routes_on_borders(v, L)
        _inside_canvas(L)
        assert no_box_overlaps(L.boxes, 10)
        for n in v.nodes:
            if n.group:
                assert contains(L.groups[n.group], L.boxes[n.id])
        assert not foreign_box_in_group(v, L)


def test_bands_never_split_a_group():
    """C3: bands are cut only between layers no group spans."""
    from archdiag.layout import _bands
    ids = ["a", "b", "c", "d"]
    layer = {"a": 0, "b": 1, "c": 2, "d": 3}
    dag = [("a", "b", 0), ("b", "c", 1), ("c", "d", 2)]
    out = _bands(dag, layer, {"a": None, "b": "g", "c": "g", "d": None}, ids, 900.0, 4)
    assert out[1] == out[2] and out != [0, 0, 0, 0]


def test_line_skipping_a_band_runs_down_the_left():
    """C3: a line from the first band to the third goes down a spine left of the bands,
    clear of every box, and still ends on both borders."""
    names = ["n%d" % i for i in range(26)]
    nodes = [VNode(n, n) for n in names]
    edges = [VEdge(a, b) for a, b in zip(names, names[1:])] + [VEdge("n0", "n25", "far")]
    v = ViewGraph("chain", "flow_tx", None, nodes, edges, [])
    L = layout_for(v, lambda n: (150, 60))
    assert L.width <= 2000 + 1
    _routes_on_borders(v, L)
    _inside_canvas(L)
    far = L.routes[-1]
    assert min(x for x, _ in far) < min(b.x for b in L.boxes.values())
    for nid, b in L.boxes.items():
        if nid not in ("n0", "n25"):
            assert not _crosses_box(far, b), nid
    for k, e in enumerate(v.edges):
        for nid, b in L.boxes.items():
            if nid not in (e.src, e.dst):
                assert not _crosses_box(L.routes[k], b), (k, nid)


def _layout_snapshot(L):
    return (L.width, L.height,
            sorted((k, b.x, b.y, b.w, b.h) for k, b in L.boxes.items()),
            sorted((k, b.x, b.y, b.w, b.h) for k, b in L.groups.items()),
            [[tuple(p) for p in r] for r in L.routes],
            [tuple(p) for p in L.label_at])


def test_layout_is_deterministic():
    # the same view laid out twice gives the same boxes, routes and label anchors, so a
    # redraw of unchanged links is an unchanged picture
    size = lambda n: (100 + 35 * (len(n.id) % 3), 60 + 30 * (len(n.id) % 2))  # noqa: E731
    for seed in range(15):
        assert _layout_snapshot(layout_for(random_view(seed), size)) == \
            _layout_snapshot(layout_for(random_view(seed), size)), seed
    for make in (claims_job, claims_landscape, app_with_neighbors):
        assert _layout_snapshot(layout_for(make(), lambda n: (140, 80))) == \
            _layout_snapshot(layout_for(make(), lambda n: (140, 80))), make.__name__


def _cross_band_pairs_that_cross(v, L):
    """Pairs of lines that each go from one band to a later one (source box wholly above
    the target box, with a channel run between) and cross each other, where they could
    nest: a line whose source is left of the other's and whose target is right of it
    (one span inside the other) must cross it once going down, so it is not counted."""
    from layout_helpers import _proper_cross, _segments
    cross = []
    for k, e in enumerate(v.edges):
        a, b = L.boxes[e.src], L.boxes[e.dst]
        r = L.routes[k]
        lane = [p for p, q in zip(r, r[1:]) if abs(p[1] - q[1]) < 1e-6
                and a.y + a.h < p[1] < b.y and abs(p[0] - q[0]) > 300]
        if lane:
            cross.append(k)
    bad = []
    for i in cross:
        for j in cross:
            si, sj = L.boxes[v.edges[i].src], L.boxes[v.edges[j].src]
            di, dj = L.boxes[v.edges[i].dst], L.boxes[v.edges[j].dst]
            if (si.x - sj.x) * (di.x - dj.x) < 0:
                continue
            if i < j and any(_proper_cross(s, t) for s in _segments(L.routes[i])
                             for t in _segments(L.routes[j])):
                bad.append((v.edges[i].label, v.edges[j].label))
    return cross, bad


def test_channel_lanes_nest_without_crossing():
    """E2: lines running along the channel between two bands are stacked so they nest:
    the line coming down furthest right takes the lowest lane, and none of them cross."""
    from conftest import fixture_view
    v = fixture_view("flow_tx", "claims/:id")
    for size in _style_sizes():
        L = layout_for(v, size)
        cross, bad = _cross_band_pairs_that_cross(v, L)
        assert len(cross) >= 3, (size.__module__, cross)
        assert not bad, (size.__module__, bad)


def test_channel_lanes_nest_in_a_synthetic_wrap():
    """E2: several lines from the end of the first band to different boxes of the second
    never cross one another in the channel."""
    names = ["n%d" % i for i in range(26)]
    nodes = [VNode(n, n) for n in names]
    edges = [VEdge(a, b) for a, b in zip(names, names[1:])]
    v0 = ViewGraph("chain", "flow_tx", None, nodes, edges, [])
    L0 = layout_for(v0, lambda n: (150, 60))
    top = min(b.y for b in L0.boxes.values())
    band0 = [n for n in names if L0.boxes[n].y == top]
    band1 = [n for n in names if L0.boxes[n].y > top]
    extra = [VEdge(band0[-2], band1[1], "x1"), VEdge(band0[-3], band1[3], "x2"),
             VEdge(band0[-2], band1[5], "x3"), VEdge(band0[-4], band1[2], "x4")]
    v = ViewGraph("chain", "flow_tx", None, nodes, edges + extra, [])
    L = layout_for(v, lambda n: (150, 60))
    cross, bad = _cross_band_pairs_that_cross(v, L)
    assert len(cross) >= 4, cross
    assert not bad, bad


def test_groups_on_a_job_flow_or_repomap_are_reported_not_dropped_silently():
    """E5: layout_for draws no groups on a job flow or repo map; when a view gives some,
    it says so in the view's notes (once, however often the view is laid out)."""
    for level in ("flow_job", "repomap"):
        v = ViewGraph("t", level, "J",
                      [VNode("job:J", "J", kind="job", group="g1"),
                       VNode("step:J#S1", "S1", kind="program", row="lane", group="g1")],
                      [VEdge("job:J", "step:J#S1", kind="sequence")],
                      [VGroup("g1", "app", "#3b82f6")])
        L = layout_for(v, lambda n: (140, 80))
        layout_for(v, lambda n: (140, 80))
        assert L.groups == {}
        notes = [n for n in v.notes if "group" in n.lower()]
        assert len(notes) == 1 and "not drawn" in notes[0], v.notes
    v = ViewGraph("t", "flow_job", "J", [VNode("job:J", "J", kind="job")], [], [])
    layout_for(v, lambda n: (140, 80))
    assert v.notes == []


def test_repomap_loose_stubs_go_straight_to_the_missing_box():
    """E7: a line to or from a missing box leaves the nearest card side and goes straight
    (or round the cards at right angles) to it: it never overshoots past either box and
    comes back, and crosses no card on the way."""
    from conftest import fixture_view
    v = fixture_view("repomap", None)
    kinds = {n.id: n.kind for n in v.nodes}
    for size in _style_sizes():
        L = layout_for(v, size)
        stubs = 0
        for k, e in enumerate(v.edges):
            if "missing" not in (kinds[e.src], kinds[e.dst]) or e.src == e.dst:
                continue
            stubs += 1
            a, b, r = L.boxes[e.src], L.boxes[e.dst], L.routes[k]
            lo_y, hi_y = min(a.y, b.y) - 40, max(a.y + a.h, b.y + b.h) + 40
            lo_x, hi_x = min(a.x, b.x) - 40, max(a.x + a.w, b.x + b.w) + 40
            assert all(lo_x <= x <= hi_x and lo_y <= y <= hi_y for x, y in r), \
                (size.__module__, e.label)
            for nid, box in L.boxes.items():
                if nid not in (e.src, e.dst):
                    assert not _crosses_box(r, box), (size.__module__, e.label, nid)
        assert stubs >= 8
