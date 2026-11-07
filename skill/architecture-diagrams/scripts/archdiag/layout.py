"""Place boxes and route lines for a ViewGraph, using only the standard library.

layout_for() picks one of three methods by view level:

* ``layered``   - left-to-right layers (landscape, application, flow_tx).
* ``job_rows``  - a lane of job steps, the data they read above, what they write below.
* ``card_grid`` - a grid of repo cards, the most linked in the middle (repomap).

The renderer supplies ``node_size`` so each style can size its own boxes. Every
route is a polyline that starts on its source box border and ends on its target
box border; renderers add arrowheads and labels.
"""
from __future__ import annotations

import bisect
import heapq
import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from archdiag.views import VNode, ViewGraph

Point = Tuple[float, float]
SizeFn = Callable[[VNode], Tuple[float, float]]

MARGIN = 30.0          # blank border around the whole picture
COL_GAP = 90.0         # layered: added to the widest box to space columns
ROW_GAP = 50.0         # layered: added to the tallest box in a row to space rows
DUMMY_ROW_H = 8.0     # layered: height of a row that only lines pass through
LINE_ROW_GAP = 10.0    # layered: gap next to a row that only lines pass through
GROUP_PAD = 20.0       # group rectangle padding around its members
GROUP_TITLE = 24.0     # extra padding on top of a group for its title
GROUP_ROW_GAP = 80.0   # layered: row gap where one group ends and another begins
PORT_GAP = 16.0        # layered: least gap between two lines on one box side
PORT_INSET = 10.0      # layered: keep line ends this far from box corners
LAYER_CAP = 4          # layered: most boxes per layer before loose ends move right
SINK_REACH = 3         # layered: how many layers past its feeder a loose end may move
COMPACT_GAIN = 0.8     # layered: rank rows are used when this much shorter than straight ones
SWEEPS = 4             # down/up barycenter sweeps
JOB_ROW_GAP = 60.0     # job_rows: vertical gap between the above row, lane and below row
JOB_SPREAD_GAP = 30.0  # job_rows: least gap between two boxes in the above/below row
JOB_DETOUR = 30.0      # job_rows: how far above the lane a step-skipping line runs
JOB_DETOUR_STEP = 14.0 # job_rows: gap between two step-skipping lines that run side by side
MAZE_STEP = 10.0       # layered: grid step for lines rerouted around a group
MAZE_CLEAR = 8.0       # layered: how far a rerouted line keeps from boxes and groups
MAZE_STUB = 12.0       # layered: straight run out of and into a box before a reroute bends
MAZE_BEND = 60.0       # layered: cost of one bend, in px of length
MAZE_POPS = 40000      # layered: search budget per rerouted line
MAZE_BUDGET = 120000   # layered: search budget for all reroutes in one picture
MAZE_CELLS = 160       # layered: the reroute grid is at most this many steps across
DETOUR_RATIO = 1.6     # layered: a line this much longer than the direct distance...
DETOUR_SLACK = 200.0   # ...plus this, is tried through the middle instead
DETOUR_GAIN = 0.75     # ...and rerouted when that is at most this share of its length
MAZE_LANE = 4.0        # layered: extra cost per px of running along a line already drawn
MAZE_NEAR = 8.5        # ...within this many px of it, across or along
MAZE_LIMIT = 40        # layered: most lines rerouted in one picture
BAND_WIDTH = 1940.0    # layered: a picture wider than this (plus margins: 2000px) wraps its
                       # layers into bands stacked top to bottom
BEND_GAP = 10.0        # layered: least gap between two lines bending in one column gap
CHANNEL_PAD = 16.0     # layered: room above and below the lines in a channel between bands
SPINE_GAP = 14.0       # layered: gap between lines going down the left of the picture
FAN_OUT = 4            # layered: most lines on one box side before some use the top/bottom
FAN_ROOM = 60.0        # layered: room above/below a box with nothing over/under it
FAN_CLEAR = 10.0       # layered: a turn above/below a box keeps this far from the next thing
FAN_MAX = 6            # layered: most lines turning above (or below) one box
TURN_GAP = 10.0        # layered: gap between two lines turning above (or below) a box
CONTEXT_COLS = 5       # context: most columns for the application's own boxes
CONTEXT_GAP = 110.0    # context: gap between the members and an outside column
CONTEXT_ROW_GAP = 30.0 # context: least gap between two boxes in an outside column
CARD_COL_GAP = 120.0   # card_grid gaps
CARD_ROW_GAP = 90.0
CARD_POINTS = 12       # card_grid: points per flattened Bezier
CARD_PARALLEL = 24.0   # card_grid: spacing between lines sharing one card side
CARD_SAMPLE = 10.0     # card_grid: a curve is tested against cards every this many px


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


@dataclass
class Layout:
    width: float
    height: float
    boxes: Dict[str, Box]
    groups: Dict[str, Box]      # only groups with members (draw groups from here). Always
                                # empty for flow_job and repomap: job rows and card grids do
                                # not arrange by group, the views for those levels set none
                                # (tests/test_layout.py checks), and any given are ignored
    routes: List[List[Point]]   # one polyline per view.edges index
    label_at: List[Point]       # one label anchor per edge


def layout_for(view: ViewGraph, node_size: SizeFn) -> Layout:
    ids = set()
    for n in view.nodes:
        if n.id in ids:
            raise ValueError("duplicate node id in view: %s" % n.id)
        ids.add(n.id)
    for e in view.edges:
        if e.src not in ids or e.dst not in ids:
            raise ValueError("edge %s -> %s names a node that is not in the view"
                             % (e.src, e.dst))
    sizes = {}
    for n in view.nodes:
        w, h = node_size(n)
        sizes[n.id] = (float(w), float(h))
    if view.level == "flow_job":
        boxes, routes = job_rows(view, sizes)
        groups: Dict[str, Box] = {}
    elif view.level == "repomap":
        boxes, routes = card_grid(view, sizes)
        groups = {}
    elif view.level == "application" and _has_context(view):
        boxes, routes = context(view, sizes)
        groups = _group_boxes(view, boxes)
        routes = _avoid_groups(view, boxes, groups, routes)
    else:
        boxes, routes = layered(view, sizes)
        right = max([b.right for b in boxes.values()] or [0.0])
        left = min([b.x for b in boxes.values()] or [0.0])
        if right - left > BAND_WIDTH:  # too wide for a page: wrap the layers into bands
            boxes, routes = layered(view, sizes, wrap=True)
        groups = _group_boxes(view, boxes)
        routes = _avoid_groups(view, boxes, groups, routes)
    return _finish(boxes, groups, routes)


# ------------------------------------------------------------------ shared helpers

def _isotonic(vals: Sequence[float]) -> List[float]:
    """Closest non-decreasing sequence (least squares), by pool-adjacent-violators."""
    blocks: List[List[float]] = []  # [sum, count]
    for v in vals:
        blocks.append([v, 1.0])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, c = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += c
    out: List[float] = []
    for s, c in blocks:
        out.extend([s / c] * int(c))
    return out


def _pack(desired: Sequence[float], gaps: Sequence[float],
          lo: Optional[float] = None, hi: Optional[float] = None) -> List[float]:
    """Positions as close as possible to `desired`, keeping order, at least gaps[i]
    between i and i+1, and (when given) all within [lo, hi]."""
    offs = [0.0]
    for g in gaps:
        offs.append(offs[-1] + g)
    fit = _isotonic([d - o for d, o in zip(desired, offs)])
    # clipping the best order-keeping fit to the allowed range is the best bounded fit
    if hi is not None and offs:
        fit = [min(f, hi - offs[-1]) for f in fit]
    if lo is not None:
        fit = [max(f, lo) for f in fit]
    return [f + o for f, o in zip(fit, offs)]


def _midpoint(route: List[Point]) -> Point:
    lengths = [math.hypot(route[i + 1][0] - route[i][0], route[i + 1][1] - route[i][1])
               for i in range(len(route) - 1)]
    half = sum(lengths) / 2
    for i, seg in enumerate(lengths):
        if half <= seg and seg > 0:
            t = half / seg
            (x0, y0), (x1, y1) = route[i], route[i + 1]
            return (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
        half -= seg
    return route[-1]


def _clip(box: Box, toward: Point) -> Point:
    """Where the line from the box center toward a point leaves the box."""
    dx, dy = toward[0] - box.cx, toward[1] - box.cy
    if dx == 0 and dy == 0:
        return (box.right, box.cy)
    tx = (box.w / 2) / abs(dx) if dx else float("inf")
    ty = (box.h / 2) / abs(dy) if dy else float("inf")
    t = min(tx, ty)
    return (box.cx + dx * t, box.cy + dy * t)


def _straight(a: Box, b: Box) -> List[Point]:
    return [_clip(a, (b.cx, b.cy)), _clip(b, (a.cx, a.cy))]


def _self_loop(b: Box) -> List[Point]:
    y0 = b.y + b.h / 4
    return [(b.right, y0), (b.right + 20, y0), (b.right + 20, b.bottom + 20),
            (b.cx, b.bottom + 20), (b.cx, b.bottom)]


def _spread(n: int, lo: float, length: float) -> List[float]:
    return [lo + length * (k + 1) / (n + 1) for k in range(n)]


def _group_boxes(view: ViewGraph, boxes: Dict[str, Box]) -> Dict[str, Box]:
    out: Dict[str, Box] = {}
    order = [g.id for g in view.groups]
    for n in view.nodes:
        if n.group and n.group not in order:
            order.append(n.group)
    for gid in order:
        members = [boxes[n.id] for n in view.nodes if n.group == gid]
        if not members:
            continue
        x0 = min(b.x for b in members) - GROUP_PAD
        y0 = min(b.y for b in members) - GROUP_PAD - GROUP_TITLE
        x1 = max(b.right for b in members) + GROUP_PAD
        y1 = max(b.bottom for b in members) + GROUP_PAD
        out[gid] = Box(x0, y0, x1 - x0, y1 - y0)
    return out


def _seg_hits(a: Point, b: Point, box: Box, pad: float = 1.0) -> bool:
    """Does the axis-aligned segment a-b pass through the inside of box?"""
    x0, x1 = min(a[0], b[0]), max(a[0], b[0])
    y0, y1 = min(a[1], b[1]), max(a[1], b[1])
    return (x0 < box.right - pad and x1 > box.x + pad
            and y0 < box.bottom - pad and y1 > box.y + pad)


def _avoid_groups(view: ViewGraph, boxes: Dict[str, Box], groups: Dict[str, Box],
                  routes: List[List[Point]]) -> List[List[Point]]:
    """Move a line's vertical run out of a group that holds neither of its ends: to just
    left or right of that group, whichever keeps the line clear of every box and every
    other foreign group (and is shorter); else reroute the whole line around it. A line
    that goes far round the outside is first tried through a nearer corridor. Rerouting
    has a fixed search budget per picture; a line it cannot improve stays."""
    group_of = {n.id: n.group for n in view.nodes}
    used: Dict[float, int] = {}
    out: List[List[Point]] = []
    rerouted = 0
    budget = MAZE_BUDGET
    for k, (e, route) in enumerate(zip(view.edges, routes)):
        pts = list(route)

        def lanes() -> List[Tuple[Point, Point]]:
            # the lines already settled and the rest as they stand: a reroute keeps its own lane
            return [seg for r in out + routes[k + 1:] for seg in zip(r, r[1:])]

        mine = {group_of.get(e.src), group_of.get(e.dst)}
        foreign = [g for gid, g in groups.items() if gid not in mine]
        for _ in range(4):
            moved = False
            for i in range(1, len(pts) - 2):
                a, b = pts[i], pts[i + 1]
                if abs(a[0] - b[0]) > 1e-6:
                    continue
                hit = [g for g in foreign if _seg_hits(a, b, g)]
                if not hit:
                    continue
                g = hit[0]
                best = None
                for side in (g.x, g.right):
                    off = PORT_GAP / 2 + PORT_GAP * used.get(round(side), 0)
                    xn = side - off if side == g.x else side + off
                    trial = pts[:i] + [(xn, a[1]), (xn, b[1])] + pts[i + 2:]
                    segs = list(zip(trial[i - 1:i + 3], trial[i:i + 3]))
                    ok = all(not _seg_hits(p, q, bx) for p, q in segs for bx in boxes.values())
                    ok = ok and all(not _seg_hits(p, q, fg) for p, q in segs for fg in foreign)
                    extra = abs(xn - a[0])
                    if ok and (best is None or extra < best[0]):
                        best = (extra, trial, side)
                if best is not None:
                    pts = best[1]
                    used[round(best[2])] = used.get(round(best[2]), 0) + 1
                    moved = True
                    break
            if not moved:
                break
        length = sum(abs(q[0] - p[0]) + abs(q[1] - p[1]) for p, q in zip(pts, pts[1:]))
        direct = abs(pts[-1][0] - pts[0][0]) + abs(pts[-1][1] - pts[0][1])
        detour = length > DETOUR_RATIO * direct + DETOUR_SLACK
        if detour and rerouted < MAZE_LIMIT and budget > 0:
            # a line going round the outside: take a corridor through the middle if one
            # is much shorter
            rerouted += 1
            alt, spent = _maze(pts, list(boxes.values()) + foreign, budget, lanes())
            budget -= spent
            if alt is not None and sum(abs(q[0] - p[0]) + abs(q[1] - p[1])
                                       for p, q in zip(alt, alt[1:])) < DETOUR_GAIN * length:
                pts = alt
        if any(_seg_hits(p, q, g) for p, q in zip(pts, pts[1:]) for g in foreign) \
                and rerouted < MAZE_LIMIT and budget > 0:
            rerouted += 1
            blocks = list(boxes.values()) + foreign
            alt, spent = _maze(pts, blocks, budget, lanes())
            budget -= spent
            if alt is not None:
                pts = alt
        out.append(_simplify(pts))
    return out


def _unit(p: Point, q: Point) -> Tuple[float, float]:
    dx, dy = q[0] - p[0], q[1] - p[1]
    if abs(dx) >= abs(dy):
        return (1.0 if dx >= 0 else -1.0, 0.0)
    return (0.0, 1.0 if dy >= 0 else -1.0)


def _maze(route: List[Point], blocks: List[Box], budget: int,
          lanes: Optional[List[Tuple[Point, Point]]] = None
          ) -> Tuple[Optional[List[Point]], int]:
    """An orthogonal path with few bends from the route's first point to its last, leaving
    and arriving the way the route does, clear of every block (by MAZE_CLEAR), and the
    search steps it took (at most ``budget``; None when none was found within it). Running
    along a segment of ``lanes`` costs extra, horizontally as vertically."""
    return _maze_dirs(route[0], _unit(route[0], route[1]), route[-1],
                      _unit(route[-2], route[-1]), blocks, budget, lanes)


def _maze_dirs(a: Point, da: Tuple[float, float], b: Point, db: Tuple[float, float],
               blocks: List[Box], budget: int,
               lanes: Optional[List[Tuple[Point, Point]]] = None
               ) -> Tuple[Optional[List[Point]], int]:
    """As _maze, from ``a`` leaving in direction ``da`` to ``b`` arriving in direction
    ``db``. Running along a segment of ``lanes`` (lines already drawn) costs extra, so
    lines keep separate lanes; crossing one is free."""
    s = (a[0] + da[0] * MAZE_STUB, a[1] + da[1] * MAZE_STUB)
    t = (b[0] - db[0] * MAZE_STUB, b[1] - db[1] * MAZE_STUB)
    xs_all = [bx.x for bx in blocks] + [bx.right for bx in blocks] + [s[0], t[0]]
    ys_all = [bx.y for bx in blocks] + [bx.bottom for bx in blocks] + [s[1], t[1]]
    lo_x, hi_x = min(xs_all) - 3 * MAZE_STEP, max(xs_all) + 3 * MAZE_STEP
    lo_y, hi_y = min(ys_all) - 3 * MAZE_STEP, max(ys_all) + 3 * MAZE_STEP
    step = max(MAZE_STEP, (hi_x - lo_x) / MAZE_CELLS, (hi_y - lo_y) / MAZE_CELLS)
    xs = sorted(set([lo_x + k * step for k in range(int((hi_x - lo_x) / step) + 1)]
                    + [s[0], t[0]]))
    ys = sorted(set([lo_y + k * step for k in range(int((hi_y - lo_y) / step) + 1)]
                    + [s[1], t[1]]))
    grown = [Box(bx.x - MAZE_CLEAR, bx.y - MAZE_CLEAR, bx.w + 2 * MAZE_CLEAR,
                 bx.h + 2 * MAZE_CLEAR) for bx in blocks]

    # blocked[i][j]: grid point (xs[i], ys[j]) lies inside a grown block
    blocked = [[False] * len(ys) for _ in xs]
    for g in grown:
        i0, i1 = bisect.bisect_right(xs, g.x), bisect.bisect_left(xs, g.right)
        j0, j1 = bisect.bisect_right(ys, g.y), bisect.bisect_left(ys, g.bottom)
        for i in range(i0, i1):
            col = blocked[i]
            for j in range(j0, j1):
                col[j] = True
    xi = {x: i for i, x in enumerate(xs)}
    yi = {y: j for j, y in enumerate(ys)}
    start, goal = (xi[s[0]], yi[s[1]]), (xi[t[0]], yi[t[1]])
    if blocked[start[0]][start[1]] or blocked[goal[0]][goal[1]]:
        return None, 0
    dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))
    sd = (int(da[0]), int(da[1]))
    vlane: set = set()
    hlane: set = set()
    for p, q in lanes or []:
        if abs(p[0] - q[0]) < 1e-6:  # vertical
            i0 = bisect.bisect_left(xs, p[0] - MAZE_NEAR)
            i1 = bisect.bisect_right(xs, p[0] + MAZE_NEAR)
            j0 = bisect.bisect_left(ys, min(p[1], q[1]))
            j1 = bisect.bisect_right(ys, max(p[1], q[1]))
            vlane.update((i, j) for i in range(i0, i1) for j in range(j0, j1))
        elif abs(p[1] - q[1]) < 1e-6:  # horizontal
            j0 = bisect.bisect_left(ys, p[1] - MAZE_NEAR)
            j1 = bisect.bisect_right(ys, p[1] + MAZE_NEAR)
            i0 = bisect.bisect_left(xs, min(p[0], q[0]))
            i1 = bisect.bisect_right(xs, max(p[0], q[0]))
            hlane.update((i, j) for i in range(i0, i1) for j in range(j0, j1))
    h0 = abs(s[0] - t[0]) + abs(s[1] - t[1])
    heap = [(h0, 0.0, start, sd)]
    best: Dict[Tuple[Tuple[int, int], Tuple[int, int]], float] = {(start, sd): 0.0}
    prev: Dict[Tuple[Tuple[int, int], Tuple[int, int]], Tuple[Tuple[int, int], Tuple[int, int]]] = {}
    end_dir = (int(db[0]), int(db[1]))
    found = None
    pops = 0
    while heap and pops < min(MAZE_POPS, budget):
        _, cost, cell, d = heapq.heappop(heap)
        pops += 1
        if cost > best.get((cell, d), float("inf")):
            continue
        if cell == goal and d == end_dir:
            found = (cell, d)
            break
        for nd in dirs:
            if nd == (-d[0], -d[1]):
                continue
            ni, nj = cell[0] + nd[0], cell[1] + nd[1]
            if not (0 <= ni < len(xs) and 0 <= nj < len(ys)):
                continue
            if blocked[ni][nj]:
                continue
            x0, y0, x1, y1 = xs[cell[0]], ys[cell[1]], xs[ni], ys[nj]
            nc = cost + abs(x1 - x0) + abs(y1 - y0) + (MAZE_BEND if nd != d else 0.0)
            if (nd[0] == 0 and (ni, nj) in vlane) or (nd[1] == 0 and (ni, nj) in hlane):
                nc += MAZE_LANE * (abs(x1 - x0) + abs(y1 - y0))
            key = ((ni, nj), nd)
            if nc < best.get(key, float("inf")):
                best[key] = nc
                prev[key] = (cell, d)
                hh = abs(x1 - t[0]) + abs(y1 - t[1])
                heapq.heappush(heap, (nc + hh, nc, (ni, nj), nd))
    if found is None:
        return None, pops
    cells = [found]
    while cells[-1] in prev:
        cells.append(prev[cells[-1]])
    path = [(xs[c[0]], ys[c[1]]) for c, _ in reversed(cells)]
    return _simplify([a] + path + [b]), pops


def _finish(boxes: Dict[str, Box], groups: Dict[str, Box],
            routes: List[List[Point]]) -> Layout:
    xs: List[float] = []
    ys: List[float] = []
    for b in list(boxes.values()) + list(groups.values()):
        xs += [b.x, b.right]
        ys += [b.y, b.bottom]
    for r in routes:
        xs += [p[0] for p in r]
        ys += [p[1] for p in r]
    if not xs:
        return Layout(2 * MARGIN, 2 * MARGIN, {}, {}, [], [])
    dx, dy = MARGIN - min(xs), MARGIN - min(ys)
    move = lambda b: Box(b.x + dx, b.y + dy, b.w, b.h)  # noqa: E731
    routes = [[(x + dx, y + dy) for x, y in r] for r in routes]
    return Layout(width=max(xs) - min(xs) + 2 * MARGIN,
                  height=max(ys) - min(ys) + 2 * MARGIN,
                  boxes={k: move(b) for k, b in boxes.items()},
                  groups={k: move(b) for k, b in groups.items()},
                  routes=routes,
                  label_at=[_midpoint(r) for r in routes])


# ------------------------------------------------------------------ layered

def layered(view: ViewGraph, sizes: Dict[str, Tuple[float, float]],
            cap: int = 0, reach: int = 0, wrap: bool = False, fan: bool = True
            ) -> Tuple[Dict[str, Box], List[List[Point]]]:
    """Left-to-right layers. With ``wrap``, a picture that would be wider than BAND_WIDTH
    puts its layers in bands stacked top to bottom (cut only where no group spans the cut);
    a line from one band to a later one runs down a column gap, along a channel between
    the bands (and down a spine on the left when it skips a band) and in from the left.
    ``fan=False`` keeps every line on the left and right sides (the context layout puts its
    own lines on the top and bottom of these boxes)."""
    ids = [n.id for n in view.nodes]
    if not ids:
        return {}, []
    group_of: Dict[str, Optional[str]] = {n.id: n.group for n in view.nodes}
    real = set(ids)

    # 1. Break cycles: reverse the back edges of a depth-first search.
    out_adj: Dict[str, List[int]] = {i: [] for i in ids}
    for k, e in enumerate(view.edges):
        if e.src != e.dst:
            out_adj[e.src].append(k)
    reversed_edges = set()
    state: Dict[str, int] = {}  # 1 on stack, 2 done
    for root in ids:
        if root in state:
            continue
        state[root] = 1
        stack = [(root, iter(out_adj[root]))]
        while stack:
            node, it = stack[-1]
            k = next(it, None)
            if k is None:
                state[node] = 2
                stack.pop()
                continue
            nxt = view.edges[k].dst
            if state.get(nxt) == 1:
                reversed_edges.add(k)
            elif nxt not in state:
                state[nxt] = 1
                stack.append((nxt, iter(out_adj[nxt])))
    dag: List[Tuple[str, str, int]] = []  # (from, to, edge index), acyclic
    for k, e in enumerate(view.edges):
        if e.src == e.dst:
            continue
        dag.append((e.dst, e.src, k) if k in reversed_edges else (e.src, e.dst, k))

    # 2. Layers by longest path, then move each source right, next to its nearest
    #    successor, so a feeder does not sit far left of what it feeds.
    preds: Dict[str, List[str]] = {i: [] for i in ids}
    succs: Dict[str, List[str]] = {i: [] for i in ids}
    for u, v, _ in dag:
        succs[u].append(v)
        preds[v].append(u)
    indeg = {i: len(preds[i]) for i in ids}
    ready = [i for i in ids if indeg[i] == 0]
    layer = {i: 0 for i in ids}
    while ready:
        u = ready.pop(0)
        for v in succs[u]:
            layer[v] = max(layer[v], layer[u] + 1)
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)
    for u in ids:
        if not preds[u] and succs[u]:
            layer[u] = min(layer[v] for v in succs[u]) - 1
    _balance_sinks(view, ids, preds, succs, layer, cap, reach)
    maxw = max(w for w, _ in sizes.values())
    nlayers = max(layer.values()) + 1

    # 2b. Bands, and the lines that go from one band to a later one.
    band_of = _bands(dag, layer, group_of, ids, maxw, nlayers) if wrap else [0] * nlayers
    nbands = max(band_of) + 1
    cross = {k for u, v, k in dag if band_of[layer[u]] != band_of[layer[v]]}

    # 3. Dummy nodes so long edges get their own slot in every layer they cross (a line
    #    to a later band gets none: it runs round the outside of the band).
    chains: Dict[int, List[str]] = {}
    seg_pred: Dict[str, List[str]] = {i: [] for i in ids}
    seg_succ: Dict[str, List[str]] = {i: [] for i in ids}
    dummy_layer: Dict[str, int] = {}
    for u, v, k in dag:
        chain = [u]
        if k not in cross:
            for lay in range(layer[u] + 1, layer[v]):
                d = "\x00dummy:%d:%d" % (k, lay)
                dummy_layer[d] = lay
                # a line between two members of one group stays inside that group
                group_of[d] = group_of[u] if group_of[u] == group_of[v] else None
                seg_pred[d], seg_succ[d] = [], []
                chain.append(d)
        chain.append(v)
        chains[k] = chain
        for a, b in zip(chain, chain[1:]):
            seg_succ[a].append(b)
            seg_pred[b].append(a)
    all_layer = dict(layer)
    all_layer.update(dummy_layer)
    layers: List[List[str]] = [[] for _ in range(nlayers)]
    for i in ids:  # input order first, dummies after
        layers[layer[i]].append(i)
    for d, lay in dummy_layer.items():
        layers[lay].append(d)

    # 4. Order within layers: barycenter sweeps, groups kept together, best kept.
    layers = _order_layers(layers, seg_pred, seg_succ, group_of)

    # 5. Rows: straighten lines while keeping the order within each layer.
    row = _assign_rows(layers, seg_pred, seg_succ,
                       [c[1:-1] for c in chains.values() if len(c) > 2])
    # Groups get their own band of rows, so no outside box sits inside a group.
    straight_layers = [list(l) for l in layers]
    row = _band_rows(straight_layers, row, group_of, real=real)
    # Straight lines can stack a busy graph into a tall staircase. Then take rows by
    # rank in each layer instead (lines bend in the column gaps), when much shorter.
    compact_layers = [list(l) for l in layers]
    compact = _band_rows(compact_layers, _rank_rows(layers, real, group_of), group_of, real=real)
    straight_h = _row_coords(straight_layers, row, ids, sizes, group_of)
    compact_h = _row_coords(compact_layers, compact, ids, sizes, group_of)
    if compact_h[0][-1] + compact_h[1][-1] < COMPACT_GAIN * (straight_h[0][-1] + straight_h[1][-1]):
        row, layers = compact, compact_layers
    else:
        layers = straight_layers

    # 6. Heights, band by band; each band below the channel that ends the one above.
    band_layers = [[g for g in range(nlayers) if band_of[g] == b] for b in range(nbands)]
    first_of_band = [bl[0] for bl in band_layers]
    # lines in each channel: (channel, edge); a line skipping bands uses two channels
    chan_edges: List[List[int]] = [[] for _ in range(nbands)]
    for u, v, k in sorted(dag, key=lambda t: (layer[t[0]], layer[t[1]], t[2])):
        if k in cross:
            bu, bv = band_of[layer[u]], band_of[layer[v]]
            chan_edges[bu].append(k)
            if bv - 1 != bu:
                chan_edges[bv - 1].append(k)
    center_y: Dict[str, float] = {}
    box_y: Dict[str, float] = {}
    band_top: List[float] = []
    chan_top: List[float] = []
    top = 0.0
    for b in range(nbands):
        band_top.append(top)
        lays = [layers[g] for g in band_layers[b]]
        members = [n for lay in lays for n in lay]
        used = sorted({row[n] for n in members})
        remap = {r: i for i, r in enumerate(used)}
        brow = {n: remap[row[n]] for n in members}
        ry, rh = _row_coords(lays, brow, [n for n in members if n in real], sizes, group_of) \
            if members else ([0.0], [0.0])
        for n in members:
            center_y[n] = top + ry[brow[n]] + rh[brow[n]] / 2
            if n in real:
                box_y[n] = center_y[n] - sizes[n][1] / 2
        bottom = top + ry[-1] + rh[-1]
        chan_top.append(bottom + GROUP_PAD + CHANNEL_PAD)
        top = (chan_top[-1] + BEND_GAP * (len(chan_edges[b]) + 1) + CHANNEL_PAD
               + GROUP_PAD + GROUP_TITLE)
    chan_y: Dict[Tuple[int, int], float] = {}
    for b, ks in enumerate(chan_edges):
        for idx, k in enumerate(ks):
            chan_y[(b, k)] = chan_top[b] + BEND_GAP * (idx + 1)
    spine = {k: idx for idx, k in enumerate(k for u, v, k in dag if k in cross
                                            and band_of[layer[v]] - band_of[layer[u]] > 1)}

    # 7. Ports: spread the lines on each box side, ordered by where they go. A side with
    #    more than FAN_OUT lines sends the ones heading furthest up out of the top and
    #    the ones heading furthest down out of the bottom, each turning at its own height.
    out_ports: Dict[str, List[Tuple[float, int]]] = {i: [] for i in ids}
    in_ports: Dict[str, List[Tuple[float, int]]] = {i: [] for i in ids}
    for k, chain in chains.items():
        out_ports[chain[0]].append((center_y[chain[1]], k))
        in_ports[chain[-1]].append((center_y[chain[-2]], k))
    fans = {i for i in ids if fan and (len(out_ports[i]) > FAN_OUT
                                       or len(in_ports[i]) > FAN_OUT)}
    # (edge, "out" or "in") -> (x along the box, border y, turn y)
    fanned: Dict[Tuple[int, str], Tuple[float, float, float]] = {}
    for i in sorted(fans, key=ids.index):
        top_y, bot_y = box_y[i], box_y[i] + sizes[i][1]
        w = sizes[i][0]
        lay = layers[layer[i]]
        above = [box_y[n] + sizes[n][1] if n in real else center_y[n] for n in lay
                 if n != i and center_y[n] < center_y[i]]
        below = [box_y[n] if n in real else center_y[n] for n in lay
                 if n != i and center_y[n] > center_y[i]]
        room = {}
        for side, gap, nb in (("top", top_y - max(above) if above else FAN_ROOM, above),
                              ("bottom", min(below) - bot_y if below else FAN_ROOM, below)):
            near = [n for n in lay if n in fans and n != i
                    and ((center_y[n] < center_y[i]) == (side == "top"))]
            if near:
                gap = gap / 2
            room[side] = max(0, min(FAN_MAX, int((gap - FAN_CLEAR) / TURN_GAP)))
        g = group_of[i]
        if g is not None and all(
                layer[m] >= layer[i] and (layer[m] > layer[i] or box_y[m] >= top_y)
                for m in ids if group_of[m] == g):
            room["top"] = 0  # its group's title sits over it: no lines through the title
        picked: Dict[str, Dict[str, List[Tuple[float, int]]]] = {
            "top": {"in": [], "out": []}, "bottom": {"in": [], "out": []}}
        for d, ports in (("out", out_ports[i]), ("in", in_ports[i])):
            if len(ports) <= FAN_OUT:
                continue
            ups = sorted(p for p in ports if p[0] < top_y - 1)
            downs = sorted((p for p in ports if p[0] > bot_y + 1), reverse=True)
            want = len(ports) - FAN_OUT
            while want > 0 and (ups or downs):
                # the most extreme line first, where there is room for it
                up_ok = ups and len(picked["top"][d]) < room["top"]
                down_ok = downs and len(picked["bottom"][d]) < room["bottom"]
                if not up_ok and not down_ok:
                    break
                if up_ok and (not down_ok or top_y - ups[0][0] >= downs[0][0] - bot_y):
                    picked["top"][d].append(ups.pop(0))
                else:
                    picked["bottom"][d].append(downs.pop(0))
                want -= 1
            moved = {k for s in ("top", "bottom") for _, k in picked[s][d]}
            ports[:] = [p for p in ports if p[1] not in moved]
        for side in ("top", "bottom"):
            ins, outs = picked[side]["in"], picked[side]["out"]
            if not ins and not outs:
                continue
            xs = _spread(len(ins) + len(outs), 0.0, w)
            sign, edge_y = (-1.0, top_y) if side == "top" else (1.0, bot_y)
            # top: the out line to the highest target leaves leftmost and turns highest;
            # the in line from the highest source enters rightmost and turns highest
            # (bottom: mirrored). So none of them cross.
            outs.sort(reverse=(side == "bottom"))
            ins.sort(reverse=(side == "bottom"))
            for j, (_, k) in enumerate(ins):
                lv = len(ins) - 1 - j
                fanned[(k, "in")] = (xs[len(ins) - 1 - j], edge_y, edge_y + sign * TURN_GAP * (lv + 1))
            for j, (_, k) in enumerate(outs):
                lv = len(outs) - 1 - j
                fanned[(k, "out")] = (xs[len(ins) + j], edge_y, edge_y + sign * TURN_GAP * (lv + 1))
    port_out: Dict[int, float] = {}
    port_in: Dict[int, float] = {}
    for i in ids:
        for ports, dest in ((out_ports[i], port_out), (in_ports[i], port_in)):
            ports.sort()
            for (_, k), y in zip(ports, _ports(box_y[i], sizes[i][1], [t for t, _ in ports])):
                dest[k] = y

    # A lone port lines up with the line it meets when that keeps the line straight.
    for k, chain in chains.items():
        if len(chain) != 2 or k in cross or (k, "out") in fanned or (k, "in") in fanned:
            continue
        a, b = chain[0], chain[-1]
        a_top, b_top = box_y[a], box_y[b]
        if len(in_ports[b]) == 1 and b_top < port_out[k] < b_top + sizes[b][1]:
            port_in[k] = port_out[k]
        elif len(out_ports[a]) == 1 and a_top < port_in[k] < a_top + sizes[a][1]:
            port_out[k] = port_in[k]

    # 8. The vertical runs of the lines, gap by gap (a gap is after a layer, or before
    #    the first layer of a band), and how wide each gap must be to keep them apart.
    def start_y(k: int) -> float:
        return fanned[(k, "out")][2] if (k, "out") in fanned else port_out[k]

    def end_y(k: int) -> float:
        return fanned[(k, "in")][2] if (k, "in") in fanned else port_in[k]

    hops: Dict[Tuple[str, int], List[Tuple[float, float, int, int]]] = {}
    paths: Dict[int, List[Tuple[str, str, float, float, Tuple[str, int]]]] = {}
    for u, v, k in dag:
        chain = chains[k]
        hop_list = []
        if k in cross:
            bu, bv = band_of[layer[u]], band_of[layer[v]]
            gb = ("after", layer[v] - 1) if layer[v] != first_of_band[bv] else ("pre", bv)
            hop_list = [(u, "", start_y(k), chan_y[(bu, k)], ("after", layer[u])),
                        ("", v, chan_y[(bv - 1, k)], end_y(k), gb)]
        else:
            for h_i, (a, b) in enumerate(zip(chain, chain[1:])):
                y0 = start_y(k) if h_i == 0 else center_y[a]
                y1 = end_y(k) if h_i == len(chain) - 2 else center_y[b]
                hop_list.append((a, b, y0, y1, ("after", all_layer[a])))
        for h_i, (_, _, y0, y1, key) in enumerate(hop_list):
            if abs(y0 - y1) > 0.01:
                hops.setdefault(key, []).append((y0, y1, k, h_i))
        paths[k] = hop_list
    last_of_band = {bl[-1] for bl in band_layers}
    gap_w: Dict[Tuple[str, int], float] = {}
    for g in range(nlayers):
        n = len(hops.get(("after", g), []))
        gap_w[("after", g)] = (BEND_GAP * (n + 1) if n else 0.0) if g in last_of_band \
            else max(COL_GAP, BEND_GAP * (n + 1))
    for b in range(nbands):
        n = len(hops.get(("pre", b), []))
        gap_w[("pre", b)] = BEND_GAP * (n + 1) if n else 0.0

    # 9. Columns, boxes, and the routes: border to border, bends in the gaps.
    col_x = [0.0] * nlayers
    gap_lo: Dict[Tuple[str, int], float] = {}
    for b in range(nbands):
        gap_lo[("pre", b)] = 0.0
        x = gap_w[("pre", b)]
        for g in band_layers[b]:
            col_x[g] = x
            gap_lo[("after", g)] = x + maxw
            x += maxw + gap_w[("after", g)]
    boxes: Dict[str, Box] = {}
    for i in ids:
        w, h = sizes[i]
        boxes[i] = Box(col_x[layer[i]] + (maxw - w) / 2, box_y[i], w, h)
    bend_x: Dict[Tuple[int, int], float] = {}
    for key, items in hops.items():
        # So no two lines share a horizontal run: lines going down bend lowest start
        # first, lines going up bend highest start first.
        items.sort(key=lambda t: (t[1] < t[0], -t[0] if t[1] > t[0] else t[0], t[1]))
        for (_, _, k, h_i), x in zip(items, _spread(len(items), gap_lo[key], gap_w[key])):
            bend_x[(k, h_i)] = x
    routes: List[List[Point]] = [[] for _ in view.edges]
    for k, e in enumerate(view.edges):
        if e.src == e.dst:
            routes[k] = _self_loop(boxes[e.src])
    for u, v, k in dag:
        hop_list = paths[k]
        pts: List[Point] = []
        if (k, "out") in fanned:
            rx, by, ty = fanned[(k, "out")]
            pts = [(boxes[u].x + rx, by), (boxes[u].x + rx, ty)]
        else:
            pts = [(boxes[u].right, port_out[k])]
        if k in cross:
            (_, _, y0, cy1, _), (_, _, cy2, y1, _) = hop_list
            xa, xb = bend_x[(k, 0)], bend_x[(k, 1)]
            pts += [(xa, y0), (xa, cy1)]
            if k in spine:
                xs_ = -SPINE_GAP * (spine[k] + 1)
                pts += [(xs_, cy1), (xs_, cy2)]
            pts += [(xb, cy2), (xb, y1)]
        else:
            for h_i, (a, b, y0, y1, _) in enumerate(hop_list):
                if h_i > 0:
                    x0 = boxes[a].right if a in boxes else col_x[all_layer[a]] + maxw
                    if pts[-1] != (x0, y0):
                        pts.append((x0, y0))
                if (k, h_i) in bend_x:
                    xm = bend_x[(k, h_i)]
                    pts += [(xm, y0), (xm, y1)]
                if h_i < len(hop_list) - 1:
                    pts.append((col_x[all_layer[b]], y1))
        if (k, "in") in fanned:
            rx, by, ty = fanned[(k, "in")]
            pts += [(boxes[v].x + rx, ty), (boxes[v].x + rx, by)]
        else:
            pts.append((boxes[v].x, port_in[k]))
        routes[k] = _simplify(pts[::-1] if k in reversed_edges else pts)
    return boxes, routes


def _bands(dag: List[Tuple[str, str, int]], layer: Dict[str, int],
           group_of: Dict[str, Optional[str]], ids: List[str], maxw: float,
           nlayers: int) -> List[int]:
    """The band of each layer: all 0 when the layers fit in BAND_WIDTH (gaps as wide as
    the lines through them may need); else as many layers per band as fit, cut only
    between layers no group spans (a band grows past the width rather than split one)."""
    span = [0] * max(nlayers - 1, 0)
    for u, v, _ in dag:
        for g in range(layer[u], layer[v]):
            span[g] += 1
    gap = [max(COL_GAP, BEND_GAP * (c + 1)) for c in span]
    out = [0] * nlayers
    if nlayers * maxw + sum(gap) <= BAND_WIDTH:
        return out
    glay: Dict[str, Tuple[int, int]] = {}
    for i in ids:
        g = group_of[i]
        if g is not None:
            lo, hi = glay.get(g, (layer[i], layer[i]))
            glay[g] = (min(lo, layer[i]), max(hi, layer[i]))

    def free(c: int) -> bool:  # may a band start at layer c?
        return all(not (lo < c <= hi) for lo, hi in glay.values())

    starts = [0]
    g, width = 1, maxw
    while g < nlayers:
        width += gap[g - 1] + maxw
        if width > BAND_WIDTH:
            cut = next((c for c in range(g, starts[-1], -1) if free(c)), None)
            if cut is None:
                cut = next((c for c in range(g + 1, nlayers) if free(c)), None)
                if cut is None:
                    break
            starts.append(cut)
            g, width = cut + 1, maxw
            continue
        g += 1
    for b, s in enumerate(starts):
        for g in range(s, nlayers):
            out[g] = b
    return out


def _rank_rows(layers: List[List[str]], real: set,
               group_of: Dict[str, Optional[str]]) -> Dict[str, int]:
    """Rows by rank: boxes take rows in each layer's order, row after row, and the
    lines passing between two boxes of a layer get thin rows of their own just before
    the later box's row. A group spread over several layers waits until it heads every
    one of its layers, so its members share rows (no staircase)."""
    seqs = [[n for n in lay if n in real] for lay in layers]
    ptr = [0] * len(layers)
    row_of: Dict[str, int] = {}
    r = 0
    while any(ptr[k] < len(seqs[k]) for k in range(len(seqs))):
        heads = {k: seqs[k][ptr[k]] for k in range(len(seqs)) if ptr[k] < len(seqs[k])}
        placed = []
        for k, n in heads.items():
            g = group_of[n]
            if g is not None:
                # every layer still holding members of g must have one at its head
                ok = all(group_of[heads[j]] == g for j in heads
                         if any(group_of[m] == g for m in seqs[j][ptr[j]:]))
                if not ok:
                    continue
            placed.append(k)
        if not placed:
            placed = [min(heads)]
        for k in placed:
            row_of[heads[k]] = r
            ptr[k] += 1
        r += 1
    # thin rows for lines: before box row R, as many as any layer needs there
    want: Dict[str, int] = {}
    width: Dict[int, int] = {}
    for lay in layers:
        pending: List[str] = []
        for n in lay:
            if n in real:
                for c, d in enumerate(pending):
                    want[d] = c
                    row_of[d] = row_of[n]
                width[row_of[n]] = max(width.get(row_of[n], 0), len(pending)) if pending \
                    else width.get(row_of[n], 0)
                pending = []
            else:
                pending.append(n)
        for c, d in enumerate(pending):
            want[d] = c
            row_of[d] = r
        if pending:
            width[r] = max(width.get(r, 0), len(pending))
    start: Dict[int, int] = {}
    g_row = 0
    for R in range(r + 1):
        start[R] = g_row
        g_row += width.get(R, 0) + 1
    return {n: start[row_of[n]] + (want[n] if n in want else width.get(row_of[n], 0))
            for lay in layers for n in lay}


def _row_coords(layers: List[List[str]], row: Dict[str, int], ids: List[str],
                sizes: Dict[str, Tuple[float, float]], group_of: Dict[str, Optional[str]]
                ) -> Tuple[List[float], List[float]]:
    """Top and height of every row. A row is as tall as its tallest box; a row that only
    lines pass through is DUMMY_ROW_H tall and sits closer to its neighbors, though never
    inside the padding or title of a group in the row next to it."""
    nrows = max(row.values()) + 1
    big_gap = _group_gaps(layers, row, group_of, set(ids), nrows)
    row_h = [DUMMY_ROW_H] * nrows
    has_box = [False] * nrows
    grouped = [False] * nrows
    for i in ids:
        r = row[i]
        row_h[r] = max(row_h[r], sizes[i][1])
        has_box[r] = True
        grouped[r] = grouped[r] or group_of[i] is not None
    row_y = [0.0]
    for r in range(nrows - 1):
        if has_box[r] and has_box[r + 1]:
            gap = GROUP_ROW_GAP if big_gap[r] else ROW_GAP
        else:
            gap = LINE_ROW_GAP
            if grouped[r]:
                gap = max(gap, GROUP_PAD + LINE_ROW_GAP)
            if grouped[r + 1]:
                gap = max(gap, GROUP_PAD + GROUP_TITLE + LINE_ROW_GAP)
        row_y.append(row_y[-1] + row_h[r] + gap)
    return row_y, row_h


def _balance_sinks(view: ViewGraph, ids: List[str], preds: Dict[str, List[str]],
                   succs: Dict[str, List[str]], layer: Dict[str, int],
                   cap: int = 0, reach: int = 0) -> None:
    """Keep layers to ``cap`` (LAYER_CAP) boxes where it is cheap: move a box one layer
    right when everything it feeds is further right still (those whose lines grow least
    first, outside systems before others; a member of a small group only within
    the layers its group already spans), at most ``reach`` (SINK_REACH) layers past its
    farthest feeder, so one crowded column does not become a tall stack. A missing box
    (a loose end) never moves: its dot stays next to what it hangs off."""
    cap = cap or LAYER_CAP
    reach = reach or SINK_REACH
    kind = {n.id: n.kind for n in view.nodes}
    group = {n.id: n.group for n in view.nodes}
    order = {i: k for k, i in enumerate(ids)}
    # a box with no lines goes to the least crowded layer (of its group's layers)
    count: Dict[int, int] = {}
    for i in ids:
        count[layer[i]] = count.get(layer[i], 0) + 1
    for i in ids:
        if preds[i] or succs[i]:
            continue
        mates = [layer[j] for j in ids if j != i and group[i] is not None and group[j] == group[i]]
        lo, hi = (min(mates), max(mates)) if mates else (0, max(count))
        best = min(range(lo, hi + 1), key=lambda k: (count.get(k, 0), k))
        if count.get(best, 0) + 1 < count[layer[i]]:
            count[layer[i]] -= 1
            layer[i] = best
            count[best] = count.get(best, 0) + 1
    size: Dict[str, int] = {}
    for i in ids:
        if group[i] is not None:
            size[group[i]] = size.get(group[i], 0) + 1
    k = 0
    while k <= max(layer.values()):
        here = [i for i in ids if layer[i] == k]
        span: Dict[str, int] = {}  # each group's last layer
        for i in ids:
            if group[i] is not None:
                span[group[i]] = max(span.get(group[i], 0), layer[i])
        movable = [i for i in here if preds[i] and kind[i] != "missing"
                   and all(layer[v] > k + 1 for v in succs[i])
                   and (group[i] is None or span[group[i]] >= k + 1
                        or size[group[i]] > 2 * cap)
                   and k + 1 <= max(layer[p] for p in preds[i]) + reach]
        # cheapest first: each line in is one more slot of line, each line out one fewer
        movable.sort(key=lambda i: (len(preds[i]) - len(succs[i]), kind[i] != "external",
                                    -order[i]))
        excess = len(here) - cap
        for i in movable[:max(0, excess)]:
            layer[i] = k + 1
        k += 1


def _extents(layers: List[List[str]], row: Dict[str, int],
             group_of: Dict[str, Optional[str]], real: set) -> List[Tuple[object, int, int, int, int]]:
    """(key, first layer, last layer, top row, bottom row) for each group and each
    ungrouped real node."""
    span: Dict[object, List[int]] = {}
    for k, lay in enumerate(layers):
        for n in lay:
            g = group_of[n]
            if g is None and n not in real:
                continue
            key = ("g", g) if g is not None else ("n", n)
            e = span.setdefault(key, [k, k, row[n], row[n]])
            e[0], e[1] = min(e[0], k), max(e[1], k)
            e[2], e[3] = min(e[2], row[n]), max(e[3], row[n])
    return [(key, a, b, t, u) for key, (a, b, t, u) in span.items()]


def _group_gaps(layers: List[List[str]], row: Dict[str, int],
                group_of: Dict[str, Optional[str]], real: set, nrows: int) -> List[bool]:
    """Rows after which a group edge meets something else, needing a wider gap for
    the group padding and title."""
    big = [False] * nrows
    ext = _extents(layers, row, group_of, real)
    for kx, ax, bx, _, ux in ext:
        for ky, ay, by, ty, _ in ext:
            if kx != ky and (kx[0] == "g" or ky[0] == "g") and ax <= by and ay <= bx \
                    and ux + 1 == ty:
                big[ux] = True
    return big


def _band_rows(layers: List[List[str]], row: Dict[str, int],
               group_of: Dict[str, Optional[str]], real: set) -> Dict[str, int]:
    """Give each group one block of rows across every layer it spans, and stack the
    blocks so none shares rows with anything else in those layers. Items keep their
    rows where they can and their order within each layer where it is consistent."""
    layer_of = {n: k for k, lay in enumerate(layers) for n in lay}
    pos = {n: i for lay in layers for i, n in enumerate(lay)}

    def key(n: str) -> object:
        return ("g", group_of[n]) if group_of[n] is not None else ("n", n)

    items: Dict[object, List[str]] = {}
    for lay in layers:
        for n in lay:
            items.setdefault(key(n), []).append(n)
    span = {k: (min(layer_of[n] for n in ms), max(layer_of[n] for n in ms))
            for k, ms in items.items()}
    height = {}
    for k, ms in items.items():
        per_layer: Dict[int, int] = {}
        for n in ms:
            per_layer[layer_of[n]] = per_layer.get(layer_of[n], 0) + 1
        height[k] = max(per_layer.values())
    want = {k: min(row[n] for n in ms) for k, ms in items.items()}
    # "below" pairs from neighbors within each layer; place items above first
    below: Dict[object, set] = {k: set() for k in items}
    for lay in layers:
        seq: List[object] = []
        for n in lay:
            if not seq or seq[-1] != key(n):
                seq.append(key(n))
        for a, b in zip(seq, seq[1:]):
            if a != b:
                below[a].add(b)
    waiting_on = {k: 0 for k in items}
    for k in items:
        for b in below[k]:
            waiting_on[b] += 1
    first = {k: i for i, k in enumerate(items)}
    floor = [0] * len(layers)  # first free row in each layer
    placed: Dict[object, int] = {}
    waiting = set(items)
    while waiting:
        ready = [k for k in waiting if waiting_on[k] == 0] or list(waiting)  # cycle: any
        k = min(ready, key=lambda q: (want[q], first[q]))
        waiting.discard(k)
        a, b = span[k]
        top = max([want[k]] + floor[a:b + 1])
        placed[k] = top
        for lay in range(a, b + 1):
            floor[lay] = top + height[k]
        for q in below[k]:
            waiting_on[q] -= 1
    out: Dict[str, int] = {}
    for k, ms in items.items():
        by_layer: Dict[int, List[str]] = {}
        for n in ms:
            by_layer.setdefault(layer_of[n], []).append(n)
        for lay_ms in by_layer.values():
            lay_ms.sort(key=lambda n: pos[n])
            fit = _pack([float(row[n] - placed[k]) for n in lay_ms], [1.0] * (len(lay_ms) - 1),
                        0.0, float(height[k] - 1))
            for i, (n, f) in enumerate(zip(lay_ms, fit)):
                out[n] = placed[k] + i + int(round(f - i))
    # keep each layer's order matching the rows (it changes only where a cycle broke)
    for lay in layers:
        lay.sort(key=lambda n: out[n])
    used = sorted(set(out.values()))
    remap = {r: i for i, r in enumerate(used)}
    return {n: remap[r] for n, r in out.items()}


def _ports(lo: float, length: float, targets: List[float]) -> List[float]:
    """Spots on one box side for lines heading to sorted `targets`: each as level with
    its target as the side allows, at least PORT_GAP apart (less on a crowded side)."""
    n = len(targets)
    inset = min(PORT_INSET, length / 4)
    room = length - 2 * inset
    gap = min(PORT_GAP, room / (n - 1)) if n > 1 else 0.0
    return _pack(targets, [gap] * (n - 1), lo + inset, lo + length - inset)


def _simplify(pts: List[Point]) -> List[Point]:
    """Drop repeated points and middle points of straight runs."""
    out: List[Point] = []
    for p in pts:
        if out and abs(out[-1][0] - p[0]) < 1e-6 and abs(out[-1][1] - p[1]) < 1e-6:
            continue
        if len(out) >= 2:
            (ax, ay), (bx, by) = out[-2], out[-1]
            if abs((bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)) < 1e-6:
                out[-1] = p
                continue
        out.append(p)
    return out if len(out) >= 2 else pts[:1] + pts[-1:]


def _crossings(layers: List[List[str]], seg_succ: Dict[str, List[str]]) -> int:
    total = 0
    for upper, lower in zip(layers, layers[1:]):
        pos = {n: i for i, n in enumerate(lower)}
        segs = [(i, pos[v]) for i, u in enumerate(upper) for v in seg_succ[u] if v in pos]
        for a in range(len(segs)):
            for b in range(a + 1, len(segs)):
                if (segs[a][0] - segs[b][0]) * (segs[a][1] - segs[b][1]) < 0:
                    total += 1
    return total


def _order_layers(layers: List[List[str]], seg_pred: Dict[str, List[str]],
                  seg_succ: Dict[str, List[str]],
                  group_of: Dict[str, Optional[str]]) -> List[List[str]]:
    def reorder(lay: List[str], ref: List[str], nbrs: Dict[str, List[str]],
                other: List[str], other_nbrs: Dict[str, List[str]]) -> List[str]:
        pos = {n: i for i, n in enumerate(ref)}
        opos = {n: i for i, n in enumerate(other)}
        bary: Dict[str, Tuple[float, float]] = {}
        for i, n in enumerate(lay):
            ps = [pos[m] for m in nbrs[n] if m in pos]
            # scale own index into the reference layer's range when it has no neighbors
            b = sum(ps) / len(ps) if ps else i * max(len(ref) - 1, 1) / max(len(lay) - 1, 1)
            # ties are settled by the layer on the other side
            os_ = [opos[m] for m in other_nbrs[n] if m in opos]
            bary[n] = (b, sum(os_) / len(os_) if os_ else float(i))
        blocks: Dict[object, List[str]] = {}
        first: Dict[object, int] = {}
        for i, n in enumerate(lay):
            key = ("g", group_of[n]) if group_of[n] else ("n", n)
            blocks.setdefault(key, []).append(n)
            first.setdefault(key, i)
        keyed = []
        for key, members in blocks.items():
            members.sort(key=lambda m: bary[m])
            keyed.append((sum(bary[m][0] for m in members) / len(members),
                          sum(bary[m][1] for m in members) / len(members), first[key], members))
        keyed.sort(key=lambda t: (t[0], t[1], t[2]))
        return [m for _, _, _, members in keyed for m in members]

    best = [list(l) for l in layers]
    best_score = _crossings(best, seg_succ)
    cur = [list(l) for l in layers]
    for _ in range(SWEEPS):
        for i in range(1, len(cur)):
            nxt = cur[i + 1] if i + 1 < len(cur) else []
            cur[i] = reorder(cur[i], cur[i - 1], seg_pred, nxt, seg_succ)
        score = _crossings(cur, seg_succ)
        if score < best_score:
            best, best_score = [list(l) for l in cur], score
        for i in range(len(cur) - 2, -1, -1):
            prv = cur[i - 1] if i > 0 else []
            cur[i] = reorder(cur[i], cur[i + 1], seg_succ, prv, seg_pred)
        score = _crossings(cur, seg_succ)
        if score < best_score:
            best, best_score = [list(l) for l in cur], score
    return best


def _assign_rows(layers: List[List[str]], seg_pred: Dict[str, List[str]],
                 seg_succ: Dict[str, List[str]],
                 dummy_chains: List[List[str]]) -> Dict[str, int]:
    row: Dict[str, int] = {}
    for lay in layers:
        for i, n in enumerate(lay):
            row[n] = i

    def settle(lay: List[str], nbr_lists: Sequence[Dict[str, List[str]]]) -> None:
        desired = []
        for n in lay:
            ns = sorted(row[m] for nb in nbr_lists for m in nb[n])
            # lower median: a node follows its main line rather than splitting the
            # difference between two, and the picture stays compact at the top
            desired.append(float(ns[(len(ns) - 1) // 2]) if ns else float(row[n]))
        fit = _pack(desired, [1.0] * (len(lay) - 1), lo=0.0)
        # whole rows; rounding f - i keeps it non-decreasing, so rows stay apart
        for i, (n, f) in enumerate(zip(lay, fit)):
            row[n] = i + int(round(f - i))

    for _ in range(2):
        for lay in layers[1:]:
            settle(lay, [seg_pred])
        for lay in reversed(layers[:-1]):
            settle(lay, [seg_succ])
    for lay in layers:
        settle(lay, [seg_pred, seg_succ])
    # A long line runs straight along one row: lift none of its slots, sink each to
    # the lowest of them, and push whatever sits below it in that layer further down.
    layer_of = {n: k for k, lay in enumerate(layers) for n in lay}
    for _ in range(2):
        for chain in sorted(dummy_chains, key=len, reverse=True):
            target = max(row[d] for d in chain)
            for d in chain:
                lay = layers[layer_of[d]]
                row[d] = target
                for a, b in zip(lay[lay.index(d):], lay[lay.index(d) + 1:]):
                    row[b] = max(row[b], row[a] + 1)
    used = sorted(set(row.values()))
    remap = {r: i for i, r in enumerate(used)}
    return {n: remap[r] for n, r in row.items()}


# ------------------------------------------------------------------ context (application)

def _has_context(view: ViewGraph) -> bool:
    """An application view with both members (boxes in a group) and outside boxes."""
    grouped = sum(1 for n in view.nodes if n.group)
    return 0 < grouped < len(view.nodes)


def context(view: ViewGraph, sizes: Dict[str, Tuple[float, float]]
            ) -> Tuple[Dict[str, Box], List[List[Point]]]:
    """One application in its context: its members (grouped boxes) in the middle, laid
    out left to right by ``layered`` in at most CONTEXT_COLS columns; outside boxes in one
    column on the left (lines into the application) and one on the right (lines out,
    and missing or external boxes), each stacked level with the members it meets. Lines
    to and from the columns are routed one by one in their own lanes, leaving and
    entering members through spread ports on the top or bottom."""
    by_id = {n.id: n for n in view.nodes}
    members = [n for n in view.nodes if n.group]
    member_ids = {n.id for n in members}
    inner_edges = [k for k, e in enumerate(view.edges)
                   if e.src in member_ids and e.dst in member_ids]
    sub = ViewGraph(view.title, view.level, view.scope, members,
                    [view.edges[k] for k in inner_edges], view.groups)
    cap = max(LAYER_CAP, int(math.ceil(len(members) / float(CONTEXT_COLS))))
    mboxes, mroutes = layered(sub, {i: sizes[i] for i in member_ids}, cap=cap,
                              reach=CONTEXT_COLS, fan=False)

    # which column each outside box goes to
    ins: Dict[str, int] = {}
    outs: Dict[str, int] = {}
    for e in view.edges:
        if e.src not in member_ids and e.dst in member_ids:
            ins[e.src] = ins.get(e.src, 0) + 1
        elif e.src in member_ids and e.dst not in member_ids:
            outs[e.dst] = outs.get(e.dst, 0) + 1
    left: List[str] = []
    right: List[str] = []
    for n in view.nodes:
        if n.id in member_ids:
            continue
        if n.kind not in ("missing", "external") and ins.get(n.id, 0) > outs.get(n.id, 0):
            left.append(n.id)
        else:
            right.append(n.id)
    # a box that meets no member and hangs only off left-column boxes (a loose end fed by
    # one) stands in the left column, right next to what it hangs off
    for _ in range(len(right)):
        moved = False
        for i in list(right):
            nb = {m for e in view.edges for m in (e.src, e.dst)
                  if i in (e.src, e.dst) and m != i}
            if nb and not (nb & member_ids) and nb <= set(left):
                right.remove(i)
                left.append(i)
                moved = True
        if not moved:
            break

    # members' extent, with room for group padding and titles
    gx0 = min(b.x for b in mboxes.values()) - GROUP_PAD
    gx1 = max(b.right for b in mboxes.values()) + GROUP_PAD
    gy0 = min(b.y for b in mboxes.values()) - GROUP_PAD - GROUP_TITLE
    gy1 = max(b.bottom for b in mboxes.values()) + GROUP_PAD
    boxes: Dict[str, Box] = dict(mboxes)

    def place_column(ids: List[str], x_of: Callable[[float], float]) -> None:
        want: Dict[str, float] = {}
        key: Dict[str, Tuple[float, int, int]] = {}  # (anchor's place, anchor, depth)
        for i in ids:
            ys = [mboxes[m].cy for e in view.edges for m in (e.src, e.dst)
                  if i in (e.src, e.dst) and m in mboxes]
            if ys:
                want[i] = sum(ys) / len(ys)
                key[i] = (want[i], ids.index(i), 0)
        for _ in range(len(ids)):  # hangs off another outside box: right after it
            for i in ids:
                if i in want:
                    continue
                ms = [m for e in view.edges for m in (e.src, e.dst)
                      if i in (e.src, e.dst) and m in key and m != i]
                if ms:
                    m = max(ms, key=lambda q: key[q])
                    want[i] = want[m] + 1.0
                    key[i] = (key[m][0], key[m][1], key[m][2] + 1)
        for i in ids:
            if i not in want:
                want[i] = gy1
                key[i] = (gy1, ids.index(i), 0)
        order = sorted(ids, key=lambda i: key[i])
        gaps = [(sizes[a][1] + sizes[b][1]) / 2 + CONTEXT_ROW_GAP
                for a, b in zip(order, order[1:])]
        ys = _pack([want[i] for i in order], gaps)
        for i, cy in zip(order, ys):
            w, h = sizes[i]
            boxes[i] = Box(x_of(w), cy - h / 2, w, h)

    lw = max([sizes[i][0] for i in left] or [0.0])
    place_column(left, lambda w: gx0 - CONTEXT_GAP - lw + (lw - w) / 2)
    rw = max([sizes[i][0] for i in right] or [0.0])
    place_column(right, lambda w: gx1 + CONTEXT_GAP + (rw - w) / 2)

    # routes: inner ones from layered, the rest one by one in lanes
    routes: List[Optional[List[Point]]] = [None] * len(view.edges)
    for k, r in zip(inner_edges, mroutes):
        routes[k] = r
    lanes: List[Tuple[Point, Point]] = []
    for r in mroutes:
        lanes.extend(zip(r, r[1:]))
    side_of = {i: "left" for i in left}
    side_of.update({i: "right" for i in right})
    # ports: outside boxes on the side facing the members; members on top or bottom
    plan: Dict[int, Tuple[Tuple[str, str], Tuple[str, str]]] = {}
    want_x: Dict[Tuple[str, str], List[Tuple[float, int]]] = {}

    def end_side(me: str, other: str) -> str:
        if me in member_ids:
            return "top" if boxes[other].cy < boxes[me].cy else "bottom"
        if other in member_ids:
            return "right" if side_of[me] == "left" else "left"
        # two outside boxes
        if side_of[me] == side_of[other]:
            return "bottom" if boxes[other].cy > boxes[me].cy else "top"
        return "right" if side_of[me] == "left" else "left"

    for k, e in enumerate(view.edges):
        if routes[k] is not None or e.src == e.dst:
            continue
        ss, ds = end_side(e.src, e.dst), end_side(e.dst, e.src)
        plan[k] = ((e.src, ss), (e.dst, ds))
        for me, side, other in ((e.src, ss, e.dst), (e.dst, ds, e.src)):
            key = (me, side)
            along = boxes[other].cx if side in ("top", "bottom") else boxes[other].cy
            want_x.setdefault(key, []).append((along, k))
    port: Dict[Tuple[int, str], Point] = {}
    for (me, side), items in want_x.items():
        items.sort()
        b = boxes[me]
        if side in ("top", "bottom"):
            xs = _spread(len(items), b.x, b.w)
            for (_, k), x in zip(items, xs):
                port[(k, me)] = (x, b.y if side == "top" else b.bottom)
        else:
            ys = _spread(len(items), b.y, b.h)
            for (_, k), y in zip(items, ys):
                port[(k, me)] = (b.x if side == "left" else b.right, y)
    blocks = list(boxes.values())
    budget = MAZE_BUDGET * 2
    # long lines first, so short ones fit around them
    order = sorted(plan, key=lambda k: -abs(boxes[view.edges[k].src].cy
                                             - boxes[view.edges[k].dst].cy))
    for k in order:
        e = view.edges[k]
        (_, ss), (_, ds) = plan[k]
        a, b = port[(k, e.src)], port[(k, e.dst)]
        da = _SIDES[ss]
        db = (-_SIDES[ds][0], -_SIDES[ds][1])
        r, spent = (None, 0)
        if budget > 0:
            r, spent = _maze_dirs(a, da, b, db, blocks, min(budget, MAZE_POPS), lanes)
            budget -= spent
        if r is None:
            r = [a, b]
        routes[k] = r
        lanes.extend(zip(r, r[1:]))
    for k, e in enumerate(view.edges):
        if routes[k] is None:
            routes[k] = _self_loop(boxes[e.src]) if e.src == e.dst else \
                _straight(boxes[e.src], boxes[e.dst])
    return boxes, [r for r in routes if r is not None]


# ------------------------------------------------------------------ job rows

def job_rows(view: ViewGraph, sizes: Dict[str, Tuple[float, float]]
             ) -> Tuple[Dict[str, Box], List[List[Point]]]:
    lane = [n.id for n in view.nodes if n.row == "lane"]
    above = [n.id for n in view.nodes if n.row == "above"]
    below = [n.id for n in view.nodes if n.row == "below"]
    other = [n.id for n in view.nodes if n.row not in ("lane", "above", "below")]
    nbrs: Dict[str, List[str]] = {n.id: [] for n in view.nodes}
    for e in view.edges:
        if e.src != e.dst:
            nbrs[e.src].append(e.dst)
            nbrs[e.dst].append(e.src)

    def band_h(group: List[str]) -> float:
        return max([sizes[i][1] for i in group] or [0.0])

    lane_w = max([sizes[i][0] for i in lane] or [0.0])
    pitch = lane_w + COL_GAP
    other_w = max([sizes[i][0] for i in other] or [0.0])
    lane_x0 = other_w + COL_GAP if other else 0.0
    above_h, lane_h = band_h(above), band_h(lane)
    # Lines that skip a step or go back run above the lane, each at its own height: the
    # lowest level where nothing else runs over the same stretch (short ones lowest).
    lane_pos = {i: k for k, i in enumerate(lane)}
    skips = [k for k, e in enumerate(view.edges)
             if e.src in lane_pos and e.dst in lane_pos and e.src != e.dst
             and lane_pos[e.dst] != lane_pos[e.src] + 1]
    skips.sort(key=lambda k: (abs(lane_pos[view.edges[k].dst] - lane_pos[view.edges[k].src]),
                              k))
    level: Dict[int, int] = {}
    taken: List[List[Tuple[int, int]]] = []
    for k in skips:
        e = view.edges[k]
        lo, hi = sorted((lane_pos[e.src], lane_pos[e.dst]))
        lv = 0
        while lv < len(taken) and any(lo <= b and a <= hi for a, b in taken[lv]):
            lv += 1
        if lv == len(taken):
            taken.append([])
        taken[lv].append((lo, hi))
        level[k] = lv
    detour_room = JOB_DETOUR + JOB_DETOUR_STEP * (len(taken) - 1) + JOB_DETOUR if taken else 0.0
    lane_cy = above_h + (max(JOB_ROW_GAP, detour_room) if above else detour_room) + lane_h / 2
    boxes: Dict[str, Box] = {}
    lane_cx: Dict[str, float] = {}
    for k, i in enumerate(lane):
        w, h = sizes[i]
        cx = lane_x0 + k * pitch + lane_w / 2
        lane_cx[i] = cx
        boxes[i] = Box(cx - w / 2, lane_cy - h / 2, w, h)
    lane_end = lane_x0 + len(lane) * pitch

    def place_row(members: List[str], cy: float) -> None:
        if not members:
            return
        want: Dict[str, float] = {}
        for i in members:
            xs = [lane_cx[m] for m in nbrs[i] if m in lane_cx]
            if xs:
                want[i] = sum(xs) / len(xs)
        # sort key: a box chained off a row neighbor sits right after that neighbor (its
        # chain root's place, then its depth), so its line crosses no other box
        key: Dict[str, Tuple[float, int]] = {i: (want[i], 0) for i in want}
        pending = [i for i in members if i not in want]
        while pending:  # chain the rest off row neighbors already placed, else after the lane
            progressed = False
            for i in list(pending):
                ws = [(want[m] + (sizes[m][0] + sizes[i][0]) / 2 + JOB_SPREAD_GAP, m)
                      for m in nbrs[i] if m in want]
                if ws:
                    want[i], m = max(ws)
                    key[i] = (key[m][0], key[m][1] + 1)
                    pending.remove(i)
                    progressed = True
            if not progressed:
                i = pending.pop(0)
                want[i] = max([lane_end] + [v + pitch for v in want.values()])
                key[i] = (want[i], 0)
        order = sorted(members, key=lambda i: (key[i], members.index(i)))
        gaps = [(sizes[a][0] + sizes[b][0]) / 2 + JOB_SPREAD_GAP for a, b in zip(order, order[1:])]
        # never spread back over the column left of the lane
        xs = _pack([want[i] for i in order], gaps, lo=lane_x0 + sizes[order[0]][0] / 2)
        for i, cx in zip(order, xs):
            w, h = sizes[i]
            boxes[i] = Box(cx - w / 2, cy - h / 2, w, h)

    place_row(above, above_h / 2)
    place_row(below, lane_cy + lane_h / 2 + JOB_ROW_GAP + band_h(below) / 2)
    # Nodes in no row (scheduler, job): a column left of the lane, the last one level
    # with the lane, the rest stacked upward.
    other.sort(key=lambda i: any(m in lane_cx for m in nbrs[i]))
    y = lane_cy
    for i in reversed(other):
        w, h = sizes[i]
        boxes[i] = Box(other_w / 2 - w / 2, y - h / 2, w, h)
        y -= h / 2 + ROW_GAP + (max(sizes[j][1] for j in other)) / 2

    # Ports on the top and bottom of boxes for lines to the rows above and below.
    side_of: Dict[Tuple[int, str], str] = {}
    lane_set, row_set = set(lane), set(above) | set(below)
    for k, e in enumerate(view.edges):
        a, b = e.src, e.dst
        for me, you in ((a, b), (b, a)):
            if me in lane_set and you in row_set:
                side_of[(k, me)] = "top" if you in above else "bottom"
            elif me in row_set and you in lane_set:
                side_of[(k, me)] = "bottom" if me in above else "top"
    ports: Dict[Tuple[str, str], List[Tuple[float, int]]] = {}
    for (k, me), side in side_of.items():
        e = view.edges[k]
        you = e.dst if me == e.src else e.src
        ports.setdefault((me, side), []).append((boxes[you].cx, k))
    port_x: Dict[Tuple[int, str], float] = {}
    for (me, side), items in ports.items():
        items.sort()
        b = boxes[me]
        for (_, k), x in zip(items, _spread(len(items), b.x, b.w)):
            port_x[(k, me)] = x

    def port(k: int, me: str) -> Point:
        b = boxes[me]
        return (port_x[(k, me)], b.y if side_of[(k, me)] == "top" else b.bottom)

    lane_top = lane_cy - lane_h / 2
    routes: List[List[Point]] = []
    blocks = list(boxes.values())
    budget = MAZE_BUDGET
    for k, e in enumerate(view.edges):
        a, b = boxes[e.src], boxes[e.dst]
        if e.src == e.dst:
            routes.append(_self_loop(a))
        elif (k, e.src) in side_of and (k, e.dst) in side_of:
            routes.append([port(k, e.src), port(k, e.dst)])
        elif e.src in lane_pos and e.dst in lane_pos and k not in level:
            routes.append([(a.right, a.cy), (b.x, b.cy)])
        elif k in level:  # skips a step or goes back: run above the lane at its own level
            lv = level[k]
            y = lane_top - JOB_DETOUR - JOB_DETOUR_STEP * lv
            na = max(0.0, min(JOB_DETOUR_STEP / 2 * lv, a.w / 4 - 4))
            nb = max(0.0, min(JOB_DETOUR_STEP / 2 * lv, b.w / 4 - 4))
            fwd = lane_pos[e.dst] > lane_pos[e.src]
            ax = a.cx + a.w / 4 + na if fwd else a.cx - a.w / 4 - na
            bx = b.cx - b.w / 4 - nb if fwd else b.cx + b.w / 4 + nb
            routes.append([(ax, a.y), (ax, y), (bx, y), (bx, b.y)])
        else:
            r = _straight(a, b)
            others = [x for i, x in boxes.items() if i not in (e.src, e.dst)]
            if any(_line_hits(r, x) for x in others) and budget > 0:
                # around the boxes between them, leaving and entering the facing sides
                sa, sb = _closest_sides(a, b)
                pa, pb = _side_point(a, sa), _side_point(b, sb)
                alt, spent = _maze_dirs(pa, _SIDES[sa], pb,
                                        (-_SIDES[sb][0], -_SIDES[sb][1]), blocks,
                                        min(budget, MAZE_POPS),
                                        [seg for q in routes for seg in zip(q, q[1:])])
                budget -= spent
                if alt is not None:
                    r = alt
            routes.append(r)
    return boxes, routes


def _line_hits(route: List[Point], box: Box, pad: float = 2.0) -> bool:
    """Does the polyline (any direction) pass through the inside of the box? Tested every
    CARD_SAMPLE px along each segment."""
    for (x0, y0), (x1, y1) in zip(route, route[1:]):
        if max(x0, x1) <= box.x + pad or min(x0, x1) >= box.right - pad \
                or max(y0, y1) <= box.y + pad or min(y0, y1) >= box.bottom - pad:
            continue
        n = max(1, int(math.ceil(math.hypot(x1 - x0, y1 - y0) / (CARD_SAMPLE / 2))))
        for q in range(n + 1):
            x, y = x0 + (x1 - x0) * q / n, y0 + (y1 - y0) * q / n
            if box.x + pad < x < box.right - pad and box.y + pad < y < box.bottom - pad:
                return True
    return False


# ------------------------------------------------------------------ card grid

_SIDES = {"left": (-1.0, 0.0), "right": (1.0, 0.0), "top": (0.0, -1.0), "bottom": (0.0, 1.0)}


def _side_point(b: Box, side: str, offset: float = 0.0) -> Point:
    if side in ("left", "right"):
        y = min(max(b.cy + offset, b.y), b.bottom)
        return (b.x if side == "left" else b.right, y)
    x = min(max(b.cx + offset, b.x), b.right)
    return (x, b.y if side == "top" else b.bottom)


def card_grid(view: ViewGraph, sizes: Dict[str, Tuple[float, float]]
              ) -> Tuple[Dict[str, Box], List[List[Point]]]:
    ids = [n.id for n in view.nodes]
    if not ids:
        return {}, []
    n = len(ids)
    cols = int(math.ceil(math.sqrt(n)))
    rows = int(math.ceil(n / float(cols)))
    degree = {i: 0 for i in ids}
    for e in view.edges:
        if e.src != e.dst:
            degree[e.src] += 1
            degree[e.dst] += 1
    by_links = sorted(ids, key=lambda i: (-degree[i], ids.index(i)))
    mid_c, mid_r = (cols - 1) / 2.0, (rows - 1) / 2.0
    cells = sorted(((r, c) for r in range(rows) for c in range(cols)),
                   key=lambda rc: ((rc[0] - mid_r) ** 2 + (rc[1] - mid_c) ** 2, rc[0], rc[1]))
    maxw = max(w for w, _ in sizes.values())
    maxh = max(h for _, h in sizes.values())
    cell_of = dict(zip(by_links, cells))
    _shorten_links(view, cell_of, cells, maxw + CARD_COL_GAP, maxh + CARD_ROW_GAP,
                   fixed=by_links[0])
    boxes: Dict[str, Box] = {}
    for i, (r, c) in cell_of.items():
        w, h = sizes[i]
        x = c * (maxw + CARD_COL_GAP) + (maxw - w) / 2
        y = r * (maxh + CARD_ROW_GAP) + (maxh - h) / 2
        boxes[i] = Box(x, y, w, h)

    # Pick the facing sides, then spread the lines that share a side along it, ordered
    # by where they go, so no two lines (A->B and B->A included) share an end point.
    sides: Dict[int, Tuple[str, str]] = {}
    bend: Dict[int, float] = {}
    on_side: Dict[Tuple[str, str], List[Tuple[float, int, int]]] = {}
    for k, e in enumerate(view.edges):
        a, b = boxes[e.src], boxes[e.dst]
        if e.src == e.dst:
            sides[k], bend[k] = ("right", "top"), 1.0
        else:
            sides[k], bend[k] = _clear_sides(a, b, [x for i, x in boxes.items()
                                                    if i not in (e.src, e.dst)])
        for end, (me, you) in enumerate(((a, b), (b, a))):
            side = sides[k][end]
            along = you.cy if side in ("left", "right") else you.cx
            on_side.setdefault(((e.src, e.dst)[end], side), []).append((along, k, end))
    offset: Dict[Tuple[int, int], float] = {}
    for (nid, side), items in on_side.items():
        items.sort()
        b = boxes[nid]
        length = b.h if side in ("left", "right") else b.w
        step = min(CARD_PARALLEL, 0.8 * length / (len(items) - 1)) if len(items) > 1 else 0.0
        for idx, (_, k, end) in enumerate(items):
            offset[(k, end)] = (idx - (len(items) - 1) / 2.0) * step
    routes: List[List[Point]] = []
    for k, e in enumerate(view.edges):
        a, b = boxes[e.src], boxes[e.dst]
        sa, sb = sides[k]
        p0, p3 = _side_point(a, sa, offset[(k, 0)]), _side_point(b, sb, offset[(k, 1)])
        routes.append(_card_curve(p0, sa, p3, sb, bend[k]))
    return boxes, routes


def _card_curve(p0: Point, sa: str, p3: Point, sb: str, bend: float) -> List[Point]:
    """A cubic Bezier leaving and entering square to the card sides, flattened."""
    dist = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
    reach = max(40.0, dist / 3) * bend
    n0, n3 = _SIDES[sa], _SIDES[sb]
    p1 = (p0[0] + n0[0] * reach, p0[1] + n0[1] * reach)
    p2 = (p3[0] + n3[0] * reach, p3[1] + n3[1] * reach)
    return [_bezier(p0, p1, p2, p3, t / (CARD_POINTS - 1.0)) for t in range(CARD_POINTS)]


def _cards_hit(curve: List[Point], others: List[Box]) -> int:
    hit = 0
    for b in others:
        # test the flattened segments every CARD_SAMPLE px, against the card shrunk by 2px
        for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
            if max(x0, x1) <= b.x + 2 or min(x0, x1) >= b.right - 2 \
                    or max(y0, y1) <= b.y + 2 or min(y0, y1) >= b.bottom - 2:
                continue
            n = max(1, int(math.ceil(math.hypot(x1 - x0, y1 - y0) / CARD_SAMPLE)))
            if any(b.x + 2 < x0 + (x1 - x0) * t < b.right - 2
                   and b.y + 2 < y0 + (y1 - y0) * t < b.bottom - 2
                   for t in (k / float(n) for k in range(n + 1))):
                hit += 1
                break
    return hit


def _clear_sides(a: Box, b: Box, others: List[Box]) -> Tuple[Tuple[str, str], float]:
    """The closest facing sides, unless that curve crosses another card: then the
    side pair and bend that cross the fewest cards, shortest first."""
    first = _closest_sides(a, b)
    if not others or not _cards_hit(_card_curve(_side_point(a, first[0]), first[0],
                                                _side_point(b, first[1]), first[1], 1.0),
                                    others):
        return first, 1.0
    best = None
    for sa in _SIDES:
        for sb in _SIDES:
            pa, pb = _side_point(a, sa), _side_point(b, sb)
            for bend in (1.0, 2.0):
                curve = _card_curve(pa, sa, pb, sb, bend)
                length = sum(math.hypot(q[0] - p[0], q[1] - p[1])
                             for p, q in zip(curve, curve[1:]))
                score = (_cards_hit(curve, others), length)
                if best is None or score < best[0]:
                    best = (score, (sa, sb), bend)
    return best[1], best[2]


def _shorten_links(view: ViewGraph, cell_of: Dict[str, Tuple[int, int]],
                   cells: List[Tuple[int, int]], pitch_x: float, pitch_y: float,
                   fixed: Optional[str] = None) -> None:
    """Swap cards between cells (or into empty ones) while that shortens the links. The
    ``fixed`` card (the most linked, in the middle) never moves and nothing takes its cell."""
    links = [(e.src, e.dst) for e in view.edges if e.src != e.dst]

    def cost() -> float:
        total = 0.0
        for a, b in links:
            (ra, ca), (rb, cb) = cell_of[a], cell_of[b]
            total += math.hypot((ca - cb) * pitch_x, (ra - rb) * pitch_y)
        return total

    best = cost()
    for _ in range(3):
        improved = False
        for i in list(cell_of):
            if i == fixed:
                continue
            for cell in cells:
                here = cell_of[i]
                if cell == here or (fixed is not None and cell == cell_of[fixed]):
                    continue
                other = next((j for j, c in cell_of.items() if c == cell), None)
                cell_of[i] = cell
                if other is not None:
                    cell_of[other] = here
                now = cost()
                if now < best - 1e-6:
                    best, improved = now, True
                else:
                    cell_of[i] = here
                    if other is not None:
                        cell_of[other] = cell
        if not improved:
            break


def _closest_sides(a: Box, b: Box) -> Tuple[str, str]:
    best = None
    for facing_only in (True, False):
        for sa, na in _SIDES.items():
            pa = _side_point(a, sa)
            for sb, nb in _SIDES.items():
                pb = _side_point(b, sb)
                if facing_only and (na[0] * (b.cx - pa[0]) + na[1] * (b.cy - pa[1]) <= 0
                                    or nb[0] * (a.cx - pb[0]) + nb[1] * (a.cy - pb[1]) <= 0):
                    continue
                d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
                if best is None or d < best[0]:
                    best = (d, sa, sb)
        if best is not None:
            break
    return best[1], best[2]


def _bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])
