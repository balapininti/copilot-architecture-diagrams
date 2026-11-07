"""Level 1: one box per application, shared data and queues, outside systems."""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from archdiag.model import CONFIRMED, Edge
from archdiag.views.common import (_CROSS_TARGETS, VEdge, VNode, ViewGraph, _Ctx, _combine,
                                   _counts_line, _evidence, _family, _least_certain,
                                   _mark_missing, _short, _suggest_note, _suggestions, _tech)

_RESOURCE_KINDS = ("dataset", "queue", "table")


def landscape(ctx: _Ctx) -> ViewGraph:
    nodes, app = ctx.nodes, ctx.app
    # the apps at the other end of each node's edges
    touch: Dict[str, Set[str]] = {}
    for e in ctx.r.edges:
        for mine, other in ((e.src, e.dst), (e.dst, e.src)):
            a = app.get(other)
            if a:
                touch.setdefault(mine, set()).add(a)
    shared: Set[str] = set()
    for nid, n in nodes.items():
        if n.kind not in _RESOURCE_KINDS or n.attrs.get("temp"):
            continue
        if n.kind == "table" and ctx.app_kind.get(app.get(nid) or "") == "datastore":
            continue
        apps = set(touch.get(nid, set()))
        if app.get(nid):
            apps.add(str(app[nid]))
        if len(apps) >= 2:
            shared.add(nid)

    def rep(nid: str) -> Optional[str]:
        n = nodes.get(nid)
        if n is None:
            return nid if nid.startswith("app:") and nid[4:] in ctx.app_kind else None
        if nid in shared or n.kind in ("external", "missing"):
            return nid
        a = app.get(nid)
        if a:
            return "app:%s" % a
        t = touch.get(nid, set())
        return "app:%s" % next(iter(t)) if len(t) == 1 else None

    keyed: List[Tuple[tuple, Edge]] = []
    dropped = 0
    inside: Dict[str, int] = {}  # partly known / loose links inside one application
    notes: List[str] = []
    sugg = {id(e): raw for raw, e in _suggestions(ctx)}
    for e in list(ctx.r.edges) + [e for _, e in _suggestions(ctx)]:
        s, d = rep(e.src), rep(e.dst)
        if s is None or d is None or s == d:
            if id(e) in sugg:
                notes.append(_suggest_note(sugg[id(e)], "both ends are inside one application; "
                                           "shown at level application"))
            elif e.status != CONFIRMED and s is not None and s == d and s.startswith("app:"):
                inside[s] = inside.get(s, 0) + 1
            elif e.status != CONFIRMED and (s is None or d is None):
                dropped += 1
            continue
        fam = _family(e, nodes)
        if e.op == "copy" and not d.startswith("missing:"):
            s, d = d, s  # shared code is drawn from the copybook's owner to its users
        keyed.append(((s, d, fam), e))

    # an application's own loose ends fold into one "N loose ends" box; the far sides of
    # exchanges, and ends reached from several places, keep their own box
    srcs: Dict[str, Set[str]] = {}
    for (s, d, _), e in keyed:
        srcs.setdefault(d, set()).add(s)
    folded: Dict[str, List[str]] = {}  # app rep -> missing ids
    for d, ss in srcs.items():
        n = nodes.get(d)
        if n is None or n.kind != "missing" or n.attrs.get("target_kind") in _CROSS_TARGETS:
            continue
        if len(ss) == 1 and next(iter(ss)).startswith("app:"):
            folded.setdefault(next(iter(ss)), []).append(d)
    fold_of = {m: a for a, ms in folded.items() for m in ms}
    loose_edges: Dict[str, List[Edge]] = {}
    rest: List[Tuple[tuple, Edge]] = []
    for key, e in keyed:
        if key[1] in fold_of:
            loose_edges.setdefault(key[0], []).append(e)
        else:
            rest.append((key, e))

    def label(key: tuple, es: List[Edge]) -> str:
        s, d, fam = key
        if fam == "COPY":
            return "COPY ×%d" % len({(x.src, x.dst) for x in es})
        if not d.startswith("app:"):
            return fam
        names: List[str] = []
        for x in es:
            n = nodes.get(x.dst)
            if n is not None and _short(n) not in names:
                names.append(_short(n))
        if not names:
            return fam
        more = " +%d" % (len(names) - 2) if len(names) > 2 else ""
        return "%s · %s%s" % (fam, ", ".join(names[:2]), more)

    vedges = _combine(rest, label, lambda k, es: "shared_code" if k[2] == "COPY" else "runtime")

    vnodes: List[VNode] = []
    for a in ctx.g.apps:
        rid = "app:%s" % a.name
        kinds = [n.kind for nid, n in nodes.items() if app.get(nid) == a.name]
        lines = [x for x in [_counts_line(kinds)] if x]
        if inside.get(rid):
            lines.append("%d partly known link%s inside" % (inside[rid], "" if inside[rid] == 1 else "s"))
        vnodes.append(VNode(rid, a.name, _tech(set(kinds)) or a.kind, a.kind,
                            ctx.group_of_app(a.name), None, lines))
    used = {x for e in vedges for x in (e.src, e.dst)}
    for nid in sorted(shared & used):
        vnodes.append(ctx.vnode(nid))
    for nid in sorted(used):
        n = nodes.get(nid)
        if n is not None and n.kind in ("external", "missing"):
            vnodes.append(ctx.vnode(nid))
    _mark_missing(vnodes, vedges)
    for a in ctx.g.apps:
        rid = "app:%s" % a.name
        if rid not in folded:
            continue
        ms = sorted(folded[rid])
        es = loose_edges[rid]
        names = [ctx.vnode(m).label for m in ms]
        st = _least_certain(e.status for e in es)
        mid = "missing:app:%s" % a.name
        more = " … +%d" % (len(names) - 3) if len(names) > 3 else ""
        vnodes.append(VNode(mid, "%d loose end%s" % (len(ms), "" if len(ms) == 1 else "s"),
                            "in %s" % a.name, "missing", ctx.group_of_app(a.name), st,
                            [" · ".join(names[:3]) + more]))
        # the least certain status: a loose end never looks like a partly known one
        vedges.append(VEdge(rid, mid, "", st, "runtime", _evidence(es), None, list(es)))
    v = ViewGraph("Landscape", "landscape", None, vnodes, vedges, ctx.vgroups(vnodes), notes)
    if dropped:
        v.notes.append("%d partly known or loose links have no application at one end; the "
                       "links report lists them." % dropped)
    return v
