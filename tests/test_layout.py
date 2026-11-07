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
