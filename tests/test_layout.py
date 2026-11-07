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
    t = time.time()
    L = layout_for(v, lambda n: (150, 80))
    assert time.time() - t < 5
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
