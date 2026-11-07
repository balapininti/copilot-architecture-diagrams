"""Level 2: one application's members, with its neighbors outside drawn grey."""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from archdiag.model import Edge
from archdiag.views.common import (_GAP_OPS, _SUB, VNode, ViewGraph, _Ctx, _combine, _key_label,
                                   _mark_missing, _scope_error, _suggest_note, _suggestions)


def application(ctx: _Ctx, scope: Optional[str]) -> ViewGraph:
    names = [a.name for a in ctx.g.apps]
    name = scope if scope in names else next(
        (a for a in names if scope and a.lower() == scope.lower()), None)
    if name is None:
        raise _scope_error(ctx.r, ctx.g, scope, ["applications"], "application")
    nodes, app = ctx.nodes, ctx.app
    grp = ctx.group_of_app(name)

    def rep(nid: str) -> str:
        """Steps and temporary datasets are drawn as their job."""
        n = nodes.get(nid)
        if n is None:
            return nid
        if n.kind == "step" and n.attrs.get("job") in nodes:
            return str(n.attrs["job"])
        if n.kind == "dataset" and n.attrs.get("temp") and "#" in nid:
            job = "job:" + nid[len("dataset:"):].split("#", 1)[0]
            return job if job in nodes else nid
        return nid

    core = {rep(nid) for nid in nodes if app.get(nid) == name}

    def touching_apps(nid: str) -> Set[str]:
        return {str(app[o]) for e in ctx.edges_of(nid) for o in (e.src, e.dst)
                if o != nid and app.get(o)}

    kept: Dict[str, VNode] = {}

    def classify(nid: str) -> Optional[VNode]:
        if nid in kept:
            return kept[nid]
        n = nodes.get(nid)
        if nid in core:
            vn = ctx.vnode(nid, grp)
        elif n is None:
            if not nid.startswith("app:") or nid[4:] == name:
                return None
            vn = VNode(nid, nid[4:], "application", "neighbor", real_kind="application")
        elif n.kind == "missing":
            vn = ctx.vnode(nid, grp)
        elif n.kind == "external":
            vn = ctx.vnode(nid)
        elif n.kind == "utility" or (app.get(nid) is None and touching_apps(nid) <= {name}):
            vn = ctx.vnode(nid, grp)  # data only this application uses
        else:
            vn = ctx.vnode(nid)
            owner = app.get(nid)
            where = owner or "shared with %s" % ", ".join(sorted(touching_apps(nid) - {name}))
            vn.sublabel = "%s · %s" % (_SUB.get(n.kind, n.kind), where)
            vn.kind = "neighbor"
        kept[nid] = vn
        return vn

    keyed: List[Tuple[tuple, Edge]] = []
    taken: Set[int] = set()
    notes: List[str] = []
    me = "app:%s" % name
    for e in ctx.r.edges:
        s, d = rep(e.src), rep(e.dst)
        if s == d or not (s in core or d in core):
            continue
        if classify(s) is None or classify(d) is None:
            continue
        keyed.append(((s, d, ctx.op_label(e)), e))
        taken.add(id(e))
    for raw, e in _suggestions(ctx):
        s, d = rep(e.src), rep(e.dst)
        if not (s in core or d in core or me in (s, d)):
            continue  # not about this application
        if s == d or me in (s, d) or classify(s) is None or classify(d) is None:
            notes.append(_suggest_note(raw))
            continue
        keyed.append(((s, d, ctx.op_label(e)), e))
    # loose ends and look-alikes ("maybe the same") of the data drawn here
    for e in ctx.r.edges:
        s, d = rep(e.src), rep(e.dst)
        if id(e) in taken or e.op not in _GAP_OPS or s == d or not (s in kept or d in kept):
            continue
        near = s if s in kept else d
        far = d if near == s else s
        new = far not in kept
        if classify(far) is None:
            continue
        if new and kept[far].group == grp and kept[near].kind == "neighbor":
            kept[far].group = None  # the far side of a neighbor sits outside the box
        keyed.append(((s, d, ctx.op_label(e)), e))
    vedges = _combine(keyed, _key_label)
    for nid in sorted(core):  # members with no lines still belong to the application
        classify(nid)
    order = sorted(kept.values(), key=lambda n: (n.group is None, n.kind == "neighbor", n.id))
    _mark_missing(order, vedges)
    return ViewGraph("Application %s" % name, "application", name, order, vedges,
                     ctx.vgroups(order), notes)
