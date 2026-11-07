"""Level 3, online: one path from a transaction, page or endpoint, numbered in order."""
from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from archdiag.model import Edge
from archdiag.views.common import (_GAP_OPS, TX_DEPTH, ViewGraph, _add_suggested_within, _combine,
                                   _Ctx, _key_label, _mark_missing, _scope_error)

_TX_FOLLOW = ("uses", "http", "put", "get", "triggers", "runs", "link", "xctl", "call", "select",
              "insert", "update", "delete", "fetch", "sql", "send_map", "receive_map", "start",
              "return_transid", "read", "write", "open", "transfer", "file_dataset") + _GAP_OPS


def _tx_starts(ctx: _Ctx, scope: str) -> Tuple[List[str], str]:
    """Start nodes for a transaction id, a page route or an endpoint (``GET /a/{id}``,
    ``GET /a/{}`` or just the path)."""
    s = scope.strip()
    up = s.upper()
    nodes = ctx.nodes
    if "transaction:" + up in nodes:
        return ["transaction:" + up], "Transaction %s" % up
    route = s.strip("/")
    pages = sorted(nid for nid, n in nodes.items() if n.kind == "page" and (
        nid == s or n.name.strip("/") == route or str(n.attrs.get("path", "")).strip("/") == route))
    if pages:
        return pages, "Page %s" % s
    parts = s.split(None, 1)
    method, path = (parts[0].upper(), parts[1]) if len(parts) == 2 else (None, s)
    eps = []
    for nid, n in nodes.items():
        if n.kind not in ("endpoint", "zosapi") or nid.startswith("endpoint:?"):
            continue
        bits = n.name.split(None, 1)
        nmeth = str(n.attrs.get("method") or bits[0]).upper()
        paths = {bits[-1], str(n.attrs.get("path") or bits[-1])}
        if nid == s or n.name.upper() == up or (
                path in paths and (method is None or nmeth in (method, "ANY"))):
            eps.append(nid)
    if eps:
        return sorted(eps), "Endpoint %s" % s
    return [], ""


class _Step:
    """One link met by the walk: the box it was followed from and the box it leads to."""

    def __init__(self, e: Edge, near: str, far: str, back: bool, idx: int) -> None:
        self.e, self.near, self.far, self.back, self.idx = e, near, far, back, idx
        self.children: List["_Step"] = []


def flow_tx(ctx: _Ctx, scope: Optional[str]) -> ViewGraph:
    starts, title = _tx_starts(ctx, scope) if scope else ([], "")
    if not starts:
        raise _scope_error(ctx.r, ctx.g, scope, ["transactions", "pages", "endpoints"],
                           "transaction, page or endpoint")
    nodes = ctx.nodes
    # breadth first along runtime links, readers found backwards from a queue; a "runs"
    # hop (endpoint to its handler, transaction to its program) costs no depth
    dist: Dict[str, int] = {s: 0 for s in starts}
    pop: Dict[str, int] = {}
    parent: Dict[str, _Step] = {}
    steps: Dict[int, _Step] = {}
    cut: Dict[int, str] = {}  # links not followed: edge id -> the box past the cut
    dq = deque(starts)

    def record(e: Edge, near: str, far: str, back: bool) -> _Step:
        if id(e) not in steps:
            steps[id(e)] = _Step(e, near, far, back, len(steps))
        return steps[id(e)]

    while dq:
        u = dq.popleft()
        if u in pop:
            continue
        pop[u] = len(pop)
        nexts = [(e, e.dst, False) for e in ctx.out.get(u, []) if e.op in _TX_FOLLOW]
        nexts += [(e, e.src, True) for e in ctx.inn.get(u, []) if e.op == "get"]
        for e, w, back in nexts:
            free = e.op == "runs" and not back
            nd = dist[u] + (0 if free else 1)
            if w in dist and dist[w] <= nd:
                record(e, u, w, back)
                continue
            if nd > TX_DEPTH:
                cut.setdefault(id(e), w)
                continue
            dist[w] = nd
            parent[w] = record(e, u, w, back)
            if free:
                dq.appendleft(w)
            else:
                dq.append(w)
    # the 3270 maps of the programs on the path
    for nid in list(dist):
        n = nodes.get(nid)
        if n is not None and n.kind == "program":
            for e in ctx.out.get(nid, []):
                if e.op in ("send_map", "receive_map"):
                    dist.setdefault(e.dst, dist[nid] + 1)
                    record(e, nid, e.dst, False)
    # number by depth of the box reached (never less than its source's depth + 1), then the
    # order boxes were visited, forward links
    # before readers found backwards; a "runs" hop follows right after the link that
    # reached its source, so the walkthrough reads "triggers CLMI", "runs CLMO100", ...
    top: List[_Step] = []
    for st in steps.values():
        p = parent.get(st.near)
        if st.e.op == "runs" and not st.back and p is not None and p is not st \
                and st.near != st.far:
            p.children.append(st)
        else:
            top.append(st)
    def depth(st: _Step) -> int:  # a link back to a box met earlier counts from its source
        return max(dist.get(st.far, TX_DEPTH + 1), dist.get(st.near, TX_DEPTH) + 1)

    top.sort(key=lambda st: (depth(st), pop.get(st.near, len(pop)), st.back, st.idx))
    ordered: List[Edge] = []

    def emit(st: _Step) -> None:
        ordered.append(st.e)
        for c in sorted(st.children, key=lambda c: c.idx):
            emit(c)

    for st in top:
        emit(st)
    vedges = _combine([((e.src, e.dst, ctx.op_label(e)), e) for e in ordered], _key_label)
    for i, e in enumerate(vedges):
        e.number = i + 1
    order: List[str] = list(starts)
    for e in vedges:
        for x in (e.src, e.dst):
            if x not in order:
                order.append(x)
    vnodes = [ctx.vnode(nid, ctx.group_of_app(ctx.app.get(nid))) for nid in order]
    _mark_missing(vnodes, vedges)
    v = ViewGraph(title, "flow_tx", scope, vnodes, vedges, ctx.vgroups(vnodes))
    # links beyond the cut, counted (not drawn) by walking on from where it stopped
    beyond: Set[int] = set(cut) - set(steps)
    if beyond:
        seen_b = set(dist)
        # walk on from the box each cut link leads to (a forward read leads to its queue,
        # a reader found backwards to the reader), counting distinct links (B9)
        far = [cut[i] for i in sorted(beyond)]
        dq2 = deque(x for x in far if x not in seen_b)
        while dq2:
            u = dq2.popleft()
            if u in seen_b:
                continue
            seen_b.add(u)
            for e, w in ([(e, e.dst) for e in ctx.out.get(u, []) if e.op in _TX_FOLLOW] +
                         [(e, e.src) for e in ctx.inn.get(u, []) if e.op == "get"]):
                if id(e) not in steps:
                    beyond.add(id(e))
                if w not in seen_b:
                    dq2.append(w)
    left = len(beyond)
    if left:
        v.notes.append("Stopped after %d hops; %d more links not drawn" % (TX_DEPTH, left))
    _add_suggested_within(ctx, v)
    return v
