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

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from archdiag.views import VNode, ViewGraph

Point = Tuple[float, float]
SizeFn = Callable[[VNode], Tuple[float, float]]

MARGIN = 30.0          # blank border around the whole picture
COL_GAP = 90.0         # layered: added to the widest box to space columns
ROW_GAP = 50.0         # layered: added to the tallest box to space rows
GROUP_PAD = 20.0       # group rectangle padding around its members
GROUP_TITLE = 24.0     # extra padding on top of a group for its title
GROUP_ROW_GAP = 80.0   # layered: row gap where one group ends and another begins
PORT_GAP = 16.0        # layered: least gap between two lines on one box side
PORT_INSET = 10.0      # layered: keep line ends this far from box corners
SWEEPS = 4             # down/up barycenter sweeps
JOB_ROW_GAP = 60.0     # job_rows: vertical gap between the above row, lane and below row
JOB_SPREAD_GAP = 30.0  # job_rows: least gap between two boxes in the above/below row
JOB_DETOUR = 30.0      # job_rows: how far above the lane a step-skipping line runs
CARD_COL_GAP = 120.0   # card_grid gaps
CARD_ROW_GAP = 90.0
CARD_POINTS = 12       # card_grid: points per flattened Bezier
CARD_PARALLEL = 24.0   # card_grid: spacing between lines sharing one card side


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
    groups: Dict[str, Box]      # only groups with members; none for job rows or card grids,
                                # which do not arrange by group (draw groups from here)
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
    else:
        boxes, routes = layered(view, sizes)
        groups = _group_boxes(view, boxes)
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

def layered(view: ViewGraph, sizes: Dict[str, Tuple[float, float]]
            ) -> Tuple[Dict[str, Box], List[List[Point]]]:
    ids = [n.id for n in view.nodes]
    if not ids:
        return {}, []
    group_of: Dict[str, Optional[str]] = {n.id: n.group for n in view.nodes}

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

    # 3. Dummy nodes so long edges get their own slot in every layer they cross.
    chains: Dict[int, List[str]] = {}
    seg_pred: Dict[str, List[str]] = {i: [] for i in ids}
    seg_succ: Dict[str, List[str]] = {i: [] for i in ids}
    dummy_layer: Dict[str, int] = {}
    for u, v, k in dag:
        chain = [u]
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
    nlayers = max(all_layer.values()) + 1 if all_layer else 0
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
    row = _band_rows(layers, row, group_of, real=set(ids))

    # 6. Coordinates.
    maxw = max(w for w, _ in sizes.values())
    maxh = max(h for _, h in sizes.values())
    nrows = max(row.values()) + 1
    big_gap = _group_gaps(layers, row, group_of, set(ids), nrows)
    row_y = [0.0]
    for r in range(nrows - 1):
        row_y.append(row_y[-1] + maxh + (GROUP_ROW_GAP if big_gap[r] else ROW_GAP))
    col_x = [lay * (maxw + COL_GAP) for lay in range(nlayers)]
    boxes: Dict[str, Box] = {}
    for i in ids:
        w, h = sizes[i]
        boxes[i] = Box(col_x[layer[i]] + (maxw - w) / 2, row_y[row[i]] + (maxh - h) / 2, w, h)
    center_y = {d: row_y[row[d]] + maxh / 2 for d in dummy_layer}
    for i in ids:
        center_y[i] = boxes[i].cy

    # 7. Ports: spread the lines on each box side, ordered by where they go.
    out_ports: Dict[str, List[Tuple[float, int]]] = {i: [] for i in ids}
    in_ports: Dict[str, List[Tuple[float, int]]] = {i: [] for i in ids}
    for k, chain in chains.items():
        out_ports[chain[0]].append((center_y[chain[1]], k))
        in_ports[chain[-1]].append((center_y[chain[-2]], k))
    port_out: Dict[int, float] = {}
    port_in: Dict[int, float] = {}
    for i in ids:
        b = boxes[i]
        for ports, dest in ((out_ports[i], port_out), (in_ports[i], port_in)):
            ports.sort()
            for (_, k), y in zip(ports, _ports(b.y, b.h, [t for t, _ in ports])):
                dest[k] = y

    # A lone port lines up with the line it meets when that keeps the line straight.
    for k, chain in chains.items():
        if len(chain) != 2:
            continue
        a, b = boxes[chain[0]], boxes[chain[-1]]
        if len(in_ports[chain[-1]]) == 1 and b.y < port_out[k] < b.bottom:
            port_in[k] = port_out[k]
        elif len(out_ports[chain[0]]) == 1 and a.y < port_in[k] < a.bottom:
            port_out[k] = port_in[k]

    # 8. Routes: border to border, with the bends in the gap between two columns.
    hops: Dict[int, List[Tuple[float, float, int, int]]] = {}  # gap -> (y0, y1, edge, hop)
    paths: Dict[int, List[Tuple[float, float, float, float, int]]] = {}
    for k, chain in chains.items():
        hop_list = []
        for h_i, (a, b) in enumerate(zip(chain, chain[1:])):
            y0 = port_out[k] if h_i == 0 else center_y[a]
            y1 = port_in[k] if h_i == len(chain) - 2 else center_y[b]
            x0 = boxes[a].right if a in boxes else col_x[all_layer[a]] + maxw
            x1 = boxes[b].x if b in boxes else col_x[all_layer[b]]
            gap = all_layer[a]
            hop_list.append((x0, y0, x1, y1, gap))
            if abs(y0 - y1) > 0.01:
                hops.setdefault(gap, []).append((y0, y1, k, h_i))
        paths[k] = hop_list
    bend_x: Dict[Tuple[int, int], float] = {}
    for gap, items in hops.items():
        lo = col_x[gap] + maxw
        # So no two lines share a horizontal run: lines going down bend lowest start
        # first, lines going up bend highest start first.
        items.sort(key=lambda t: (t[1] < t[0], -t[0] if t[1] > t[0] else t[0], t[1]))
        for (_, _, k, h_i), x in zip(items, _spread(len(items), lo, COL_GAP)):
            bend_x[(k, h_i)] = x
    routes: List[List[Point]] = []
    for k, e in enumerate(view.edges):
        if e.src == e.dst:
            routes.append(_self_loop(boxes[e.src]))
            continue
        pts: List[Point] = []
        for h_i, (x0, y0, x1, y1, _) in enumerate(paths[k]):
            if not pts or pts[-1] != (x0, y0):
                pts.append((x0, y0))
            if (k, h_i) in bend_x:
                xm = bend_x[(k, h_i)]
                pts += [(xm, y0), (xm, y1)]
            pts.append((x1, y1))
        routes.append(_simplify(pts[::-1] if k in reversed_edges else pts))
    return boxes, routes


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
    lane_cy = above_h + (JOB_ROW_GAP if above else 0.0) + lane_h / 2
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
        pending = [i for i in members if i not in want]
        while pending:  # chain the rest off row neighbors already placed, else after the lane
            progressed = False
            for i in list(pending):
                ws = [want[m] + (sizes[m][0] + sizes[i][0]) / 2 + JOB_SPREAD_GAP
                      for m in nbrs[i] if m in want]
                if ws:
                    want[i] = max(ws)
                    pending.remove(i)
                    progressed = True
            if not progressed:
                i = pending.pop(0)
                want[i] = max([lane_end] + [v + pitch for v in want.values()])
        order = sorted(members, key=lambda i: (want[i], members.index(i)))
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

    lane_pos = {i: k for k, i in enumerate(lane)}
    lane_top = lane_cy - lane_h / 2
    routes: List[List[Point]] = []
    for k, e in enumerate(view.edges):
        a, b = boxes[e.src], boxes[e.dst]
        if e.src == e.dst:
            routes.append(_self_loop(a))
        elif (k, e.src) in side_of and (k, e.dst) in side_of:
            routes.append([port(k, e.src), port(k, e.dst)])
        elif e.src in lane_pos and e.dst in lane_pos:
            if lane_pos[e.dst] == lane_pos[e.src] + 1:
                routes.append([(a.right, a.cy), (b.x, b.cy)])
            else:  # skips a step or goes back: run just above the lane
                y = lane_top - JOB_DETOUR
                ax = a.cx + a.w / 4 if lane_pos[e.dst] > lane_pos[e.src] else a.cx - a.w / 4
                bx = b.cx - b.w / 4 if lane_pos[e.dst] > lane_pos[e.src] else b.cx + b.w / 4
                routes.append([(ax, a.y), (ax, y), (bx, y), (bx, b.y)])
        else:
            routes.append(_straight(a, b))
    return boxes, routes


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
    _shorten_links(view, cell_of, cells, maxw + CARD_COL_GAP, maxh + CARD_ROW_GAP)
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
        # test the flattened segments at a few points each, against the card shrunk by 2px
        for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
            if any(b.x + 2 < x0 + (x1 - x0) * t < b.right - 2
                   and b.y + 2 < y0 + (y1 - y0) * t < b.bottom - 2 for t in (0.0, 0.5, 1.0)):
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
                   cells: List[Tuple[int, int]], pitch_x: float, pitch_y: float) -> None:
    """Swap cards between cells (or into empty ones) while that shortens the links."""
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
            for cell in cells:
                here = cell_of[i]
                if cell == here:
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
