"""The size limit: no more than MAX_NODES boxes on one picture (spec section 8)."""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from archdiag.model import CONFIRMED, Evidence
from archdiag.views.common import (MAX_NODES, VEdge, VNode, ViewGraph, _Ctx, _least_certain,
                                   _plural)


def cap(ctx: _Ctx, v: ViewGraph) -> None:
    """Fold the least linked boxes per (group, kind) into ``… N more <kind>s`` boxes until
    at most MAX_NODES remain. Boxes with a line to another group or anything not confirmed,
    and the job lane, are folded only when nothing else is left; lines are never merged
    across statuses, so a folded loose end still shows red."""
    if len(v.nodes) <= MAX_NODES:
        return
    group = {n.id: n.group for n in v.nodes}
    deg: Dict[str, int] = {n.id: 0 for n in v.nodes}
    keep: Set[str] = set()
    for e in v.edges:
        deg[e.src] += 1
        deg[e.dst] += 1
        if group.get(e.src) != group.get(e.dst) or e.status != CONFIRMED:
            keep.update((e.src, e.dst))
    fixed = {n.id for n in v.nodes if v.level == "flow_job" and n.row in ("lane", None)}
    keep |= fixed | {n.id for n in v.nodes if n.status not in (None, CONFIRMED)}

    fold: Dict[str, Tuple[Optional[str], str]] = {}
    bucket: Dict[tuple, int] = {}

    def count() -> int:
        return len(v.nodes) - len(fold) + len(bucket)

    stages = (([n for n in v.nodes if n.id not in keep], True),
              ([n for n in v.nodes if n.id not in fixed], True),
              (list(v.nodes), False))
    for cands, by_group in stages:
        if count() <= MAX_NODES:
            break
        if not by_group:
            fold, bucket = {}, {}  # last resort: one box per kind across groups
        for n in sorted(cands, key=lambda n: (deg[n.id], n.id)):
            if n.id not in fold:
                k = (n.group if by_group else None, n.kind)
                fold[n.id] = k
                bucket[k] = bucket.get(k, 0) + 1
                if count() <= MAX_NODES:
                    break
    members: Dict[tuple, List[str]] = {}
    for nid, k in fold.items():
        members.setdefault(k, []).append(nid)
    for k, ids in list(members.items()):
        if len(ids) < 2:  # a bucket of one saves nothing
            del fold[ids[0]]
            del members[k]
    if not fold:
        return
    by_id = {n.id: n for n in v.nodes}

    def more_id(k: tuple) -> str:
        return f"more:{k[0] or 'shared'}:{k[1]}"

    new_nodes: List[VNode] = []
    placed: Set[str] = set()
    for n in v.nodes:
        if n.id not in fold:
            new_nodes.append(n)
            continue
        k = fold[n.id]
        if more_id(k) in placed:
            continue
        placed.add(more_id(k))
        ms = [by_id[i] for i in members[k]]
        rows = {m.row for m in ms}
        sts = [m.status for m in ms if m.status]
        kind = "missing" if all(m.kind == "missing" for m in ms) else "more"
        new_nodes.append(VNode(more_id(k), f"… {len(ms)} more {_plural(k[1])}",
                               ", ".join(m.label for m in ms[:3]) + (", …" if len(ms) > 3 else ""),
                               kind, k[0], _least_certain(sts) if sts else None,
                               row=rows.pop() if len(rows) == 1 else None,
                               underlying=[u for m in ms for u in m.underlying],
                               members=[x for m in ms for x in m.members]))
    remap = {nid: more_id(k) for nid, k in fold.items()}
    new_by_id = {n.id: n for n in new_nodes}
    order: List[tuple] = []
    by: Dict[tuple, List[VEdge]] = {}
    for e in v.edges:
        s, d = remap.get(e.src, e.src), remap.get(e.dst, e.dst)
        if s == d and e.status == CONFIRMED and e.src != e.dst:
            # a confirmed line inside one folded box is not drawn; the box keeps its edges
            # so the links report still lists every one
            box = new_by_id.get(s)
            if box is not None:
                for u in e.underlying:
                    if not any(x is u for x in box.underlying):
                        box.underlying.append(u)
            continue
        key = (s, d, e.status, e.kind)
        if key not in by:
            by[key] = []
            order.append(key)
        by[key].append(e)
    new_edges = []
    for key in order:
        es = by[key]
        labels: List[str] = []
        for e in es:
            if e.label and e.label not in labels:
                labels.append(e.label)
        label = ", ".join(labels[:2]) + (" +%d" % (len(labels) - 2) if len(labels) > 2 else "")
        ev: List[Evidence] = []
        for e in es:
            ev += [x for x in e.evidence if x not in ev]
        nums = [e.number for e in es if e.number is not None]
        new_edges.append(VEdge(key[0], key[1], label, key[2], key[3], ev,
                               min(nums) if nums else None, [u for e in es for u in e.underlying]))
    v.nodes, v.edges = new_nodes, new_edges
    v.notes.append(_too_big_note(ctx, v))


def _too_big_note(ctx: _Ctx, v: ViewGraph) -> str:
    grouped = "Too big for one picture: smaller items are grouped as '… N more'; the links " \
              "report lists every one"
    if v.level == "application":
        flows = sorted(n.name for nid, n in ctx.nodes.items()
                       if ctx.app.get(nid) == v.scope and n.kind in ("job", "transaction"))
        return "Too big for one picture: try level flow with scope %s" % flows[0] if flows \
            else grouped
    if v.level in ("flow_job", "flow_tx"):
        return grouped
    if v.level == "gitdiagram":
        return "%s; try fewer groups in gitdiagram-%s.json" % (grouped, v.scope)
    counts: Dict[str, int] = {}
    for nid, a in ctx.app.items():
        if a and not nid.startswith(("missing:", "utility:")):
            counts[a] = counts.get(a, 0) + 1
    biggest = max(sorted(counts), key=lambda a: counts[a]) if counts else "?"
    return "Too big for one picture: try level application with scope %s" % biggest
