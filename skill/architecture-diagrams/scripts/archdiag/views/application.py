"""Level 2: one application read from what comes in to what goes out, with the outside
things it talks to drawn as what they are."""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from archdiag.model import Edge
from archdiag.views.common import (_GAP_OPS, _SUB, RANK_ENTRY, RANK_GATEWAY, RANK_LOGIC,
                                   RANK_OUTSIDE, RANK_RESOURCE, VNode, ViewGraph, _Ctx,
                                   _combine, _display, _key_label, _mark_missing, _scope_error,
                                   _suggest_note, _suggestions)

# what starts work in an application, what holds data, and the links that reach a resource
_ENTRY_KINDS = ("endpoint", "zosapi", "transaction", "job", "proc", "page")
_RESOURCE_KINDS = ("table", "queue", "dataset", "cicsfile", "map", "mqprocess", "copybook")
_OBJECT_OPS = ("select", "insert", "update", "delete", "fetch", "sql", "put", "get", "open",
               "http", "read", "write", "transfer", "file_dataset", "send_map", "receive_map")
_OBJECT_KINDS = _RESOURCE_KINDS + ("endpoint", "zosapi", "external")


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
            vn = VNode(nid, nid[4:], "application", "application", real_kind="application")
        elif n.kind == "missing":
            vn = ctx.vnode(nid, grp)
        elif n.kind == "external":
            vn = ctx.vnode(nid)
        elif n.kind == "utility" or (app.get(nid) is None and touching_apps(nid) <= {name}):
            vn = ctx.vnode(nid, grp)  # data only this application uses
        else:
            # an outside neighbor keeps what it is (a queue is drawn as a queue); it stands
            # outside the application's box and says whose it is
            vn = ctx.vnode(nid)
            owner = app.get(nid)
            where = owner or "shared with %s" % ", ".join(sorted(touching_apps(nid) - {name}))
            vn.sublabel = "%s · %s" % (_SUB.get(n.kind, n.kind), where)
        kept[nid] = vn
        return vn

    def label(e: Edge) -> str:
        """Verb plus object: ``MQ PUT CLM.REQ.LQ``, ``SELECT CLMS.POLICY``. A link between
        two pieces of code keeps the verb alone (``runs``, ``CALL``): its boxes name them."""
        verb = ctx.op_label(e)
        d = nodes.get(e.dst)
        if e.op not in _OBJECT_OPS or d is None or d.kind not in _OBJECT_KINDS \
                or d.attrs.get("temp"):
            return verb
        return "%s %s" % (verb, _display(d))

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
        keyed.append(((s, d, label(e)), e))
        taken.add(id(e))
    for raw, e in _suggestions(ctx):
        s, d = rep(e.src), rep(e.dst)
        if not (s in core or d in core or me in (s, d)):
            continue  # not about this application
        if s == d or me in (s, d) or classify(s) is None or classify(d) is None:
            notes.append(_suggest_note(raw))
            continue
        keyed.append(((s, d, label(e)), e))
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
        if new and kept[far].group == grp and kept[near].group is None:
            kept[far].group = None  # the far side of a neighbor sits outside the box
        keyed.append(((s, d, label(e)), e))
    vedges = _combine(keyed, _key_label)
    for nid in sorted(core):  # members with no lines still belong to the application
        classify(nid)

    # the reading order: what comes in, the logic it runs, what reaches out, the data
    run_by_entry = {rep(e.dst) for e in ctx.r.edges if e.op in ("runs", "triggers")
                    and nodes.get(rep(e.src)) is not None
                    and nodes[rep(e.src)].kind in _ENTRY_KINDS}
    reaches_out: Set[str] = set()
    for ve in vedges:
        far = kept.get(ve.dst)
        if far is not None and ve.src in kept and any(u.op in _OBJECT_OPS + _GAP_OPS
                                                      for u in ve.underlying) and (
                far.group is None or far.real_kind in _OBJECT_KINDS or far.kind == "missing"):
            reaches_out.add(ve.src)

    triggering = {rep(e.src) for e in ctx.r.edges if e.op == "triggers"}

    def rank(vn: VNode) -> int:
        if vn.group is None:
            return RANK_OUTSIDE
        kind = vn.real_kind or vn.kind
        if kind in _ENTRY_KINDS or vn.id in triggering:  # a queue that starts a transaction
            return RANK_ENTRY
        if kind in _RESOURCE_KINDS or kind in ("vsam", "gdg", "missing", "utility"):
            return RANK_RESOURCE
        if vn.id in reaches_out and vn.id not in run_by_entry:
            return RANK_GATEWAY
        return RANK_LOGIC

    for vn in kept.values():
        vn.rank = rank(vn)
    order = sorted(kept.values(), key=lambda n: (n.rank, n.kind == "missing", n.id))
    _mark_missing(order, vedges)
    return ViewGraph("Application %s" % name, "application", name, order, vedges,
                     ctx.vgroups(order), notes)
