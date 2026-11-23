"""Level 1: one box per system, the lines between them named by protocol and target."""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from archdiag.model import CONFIRMED, Edge
from archdiag.views.common import (_RANK, VNode, ViewGraph, _Ctx, _combine, _count,
                                   _counts_line, _family, _missing_label, _short,
                                   _suggest_note, _suggestions, _tech)

_RESOURCE_KINDS = ("dataset", "queue", "table")
_MQ_OPS = ("put", "get", "open")
_FILE_OPS = ("read", "write", "update")
LABEL_NAMES = 3  # most target names on one line's label before "+N"
LABEL_CHARS = 48  # ...and the most characters: a label has to fit on its line


def landscape(ctx: _Ctx) -> ViewGraph:
    """One box per system and one line per pair of systems, protocol and certainty.

    * A queue, dataset or table that an application owns is part of that application's box:
      a line to it is a line to its owner, labelled with its name (``MQ CLM.REQ.LQ``,
      ``SQL CLAIM, POLICY``). Only a resource no application owns that two or more use
      keeps its own box.
    * Loose ends are not drawn: each is counted on the box it hangs off (``3 loose ends, see
      links report``; a resource box says ``no writer found``), and that box keeps the
      edges so the links report still lists every one.
    * Shared code is not drawn: COPY links and the applications that hold only copybooks
      are left out, counted in a note, and listed in the links report."""
    nodes, app = ctx.nodes, ctx.app
    kinds_of: Dict[str, List[str]] = {a.name: [] for a in ctx.g.apps}
    for nid, n in nodes.items():
        if app.get(nid) in kinds_of:
            kinds_of[str(app[nid])].append(n.kind)
    # an application that holds only copybooks is shared code, not a running system
    code_only = {a for a, ks in kinds_of.items() if ks and set(ks) <= {"copybook"}}
    # the apps at the other end of each node's edges
    touch: Dict[str, Set[str]] = {}
    for e in ctx.r.edges:
        for mine, other in ((e.src, e.dst), (e.dst, e.src)):
            a = app.get(other)
            if a:
                touch.setdefault(mine, set()).add(a)
    shared: Set[str] = set()
    for nid, n in nodes.items():
        if n.kind not in _RESOURCE_KINDS or n.attrs.get("temp") or app.get(nid):
            continue
        if len(touch.get(nid, set())) >= 2:
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

    # how each system uses each free-standing dataset: one that it both writes and reads
    # gets one line for the two
    file_ops: Dict[Tuple[str, str], Set[str]] = {}
    for e in ctx.r.edges:
        if e.dst in shared and nodes[e.dst].kind == "dataset" and e.op in _FILE_OPS \
                and rep(e.src):
            file_ops.setdefault((str(rep(e.src)), e.dst), set()).add(e.op)
    fed = {d for (_, d), ops in file_ops.items() if ops - {"read"}}  # some system writes it

    keyed: List[Tuple[tuple, Edge]] = []
    dropped = 0
    inside: Dict[str, int] = {}  # partly known / loose links inside one application
    held: Dict[str, List[Edge]] = {}  # box -> edges it stands for (not drawn as lines)
    ends: Dict[str, List[str]] = {}  # box -> the missing targets counted on it
    copies: List[Edge] = []
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
        if d.startswith("missing:") or s.startswith("missing:"):
            # a loose end is counted on the box it hangs off, never a box of its own
            box, end = (s, d) if d.startswith("missing:") else (d, s)
            if box.startswith("missing:"):
                dropped += 1
                continue
            held.setdefault(box, []).append(e)
            if end not in ends.setdefault(box, []):
                ends[box].append(end)
            continue
        if e.op == "copy":
            copies.append(e)
            held.setdefault(s if s.startswith("app:") else d, []).append(e)
            continue
        fam = _family(e, nodes)
        dn = nodes.get(e.dst)
        if dn is not None and dn.kind == "queue" and e.op in _MQ_OPS and d.startswith("app:"):
            # one MQ line from the system that uses the queues to the system that owns
            # them, naming request and reply queue alike (as a SQL line names its tables)
            fam = "MQ"
        elif e.op in _FILE_OPS and len(file_ops.get((s, d), ())) > 1:
            fam = "reads and writes"
        elif e.op == "read" and d in fed:
            s, d = d, s  # a dataset one system writes feeds the systems that read it
        keyed.append(((s, d, fam), e))
    # one line per (ends, protocol, certainty): the label names its targets, so a target
    # known only partly gets its own dotted line instead of riding on a solid one. Each
    # target goes on the line of the most certain edge that reaches it.
    best: Dict[tuple, str] = {}
    for key, e in keyed:
        t = key + (e.dst,)
        if t not in best or _RANK[e.status] < _RANK[best[t]]:
            best[t] = e.status
    keyed = [(key + (best[key + (e.dst,)],), e) for key, e in keyed]

    def label(key: tuple, es: List[Edge]) -> str:
        s, d, fam = key[:3]
        if not (s.startswith("app:") and d.startswith("app:")):
            return fam  # the box at the other end names the target
        names: List[str] = []
        for x in es:
            n = nodes.get(x.dst)
            if n is not None and _short(n) not in names:
                names.append(_short(n))
        if not names:
            return fam
        keep = 1  # as many names as fit a label, the first always
        while keep < min(len(names), LABEL_NAMES) and \
                len(fam) + 1 + len(", ".join(names[:keep + 1])) <= LABEL_CHARS:
            keep += 1
        more = " +%d" % (len(names) - keep) if len(names) > keep else ""
        return "%s %s%s" % (fam, ", ".join(names[:keep]), more)

    vedges = _combine(keyed, label, lambda k, es: "runtime")
    used = {x for e in vedges for x in (e.src, e.dst)}

    vnodes: List[VNode] = []
    left_out: List[str] = []
    for a in ctx.g.apps:
        rid = "app:%s" % a.name
        if a.name in code_only and rid not in used and rid not in ends:
            left_out.append(a.name)
            continue
        kinds = kinds_of[a.name]
        lines = [x for x in [_counts_line(kinds)] if x]
        if inside.get(rid):
            lines.append("%s inside" % _count(inside[rid], "partly known link"))
        if ends.get(rid):
            lines.append("%s, see links report" % _count(len(ends[rid]), "loose end"))
        # one box per system: no group around it (a group would be a second box, same name)
        vnodes.append(VNode(rid, a.name, _tech(set(kinds)) or a.kind, a.kind, None, None,
                            lines, underlying=list(held.get(rid, []))))
    for nid in sorted(n for n in used | set(ends) if n in nodes):
        vn = ctx.vnode(nid)
        # what is missing on a resource is said on its own box ("no writer found")
        marks: List[str] = []
        for m in ends.get(nid, []):
            text = _missing_label(nodes[m])[0] if m in nodes else "loose end"
            if text not in marks:
                marks.append(text)
        vn.detail_lines = marks
        vn.highlight = len(marks)
        vn.underlying = list(held.get(nid, []))
        vnodes.append(vn)
    # a box left out of the picture hands its edges to the box at their other end
    by_id = {n.id: n for n in vnodes}
    for box, es in held.items():
        if box in by_id:
            continue
        for e in es:
            other = next((x for x in (rep(e.src), rep(e.dst)) if x in by_id), None)
            if other is None:
                dropped += e.status != CONFIRMED
            elif not any(x is e for x in by_id[other].underlying):
                by_id[other].underlying.append(e)
    # the systems in the order work passes through them (a caller before what it calls,
    # groups.json order otherwise), then the resources and outside systems
    after: Dict[str, List[str]] = {}
    for e in vedges:
        if e.src.startswith("app:") and e.dst.startswith("app:"):
            after.setdefault(e.src, []).append(e.dst)
    seen: Set[str] = set()
    flow: List[str] = []

    def visit(rid: str) -> None:
        if rid in seen:
            return
        seen.add(rid)
        for nxt in after.get(rid, []):
            visit(nxt)
        flow.append(rid)

    called = {d for ds in after.values() for d in ds}
    apps = [n.id for n in vnodes if n.id.startswith("app:")]
    for rid in [a for a in apps if a not in called] + apps:
        visit(rid)
    place = {rid: i for i, rid in enumerate(reversed(flow))}
    vnodes.sort(key=lambda n: place.get(n.id, len(place)))  # stable: the rest keep their order
    v = ViewGraph("Landscape", "landscape", None, vnodes, vedges, [], notes)
    total = sum(len(x) for x in ends.values())
    if total:
        v.notes.append("%s counted on the box each hangs off, not drawn; the links report "
                       "lists each one." % _count(total, "loose end is", "loose ends are"))
    if copies:
        v.notes.append("Shared code is not drawn: %s to %s%s left out; the repo link map "
                       "(level repomap) shows them and the links report lists each one."
                       % (_count(len(copies), "COPY link"),
                          _count(len({e.dst for e in copies}), "copybook"),
                          " (%s)" % ", ".join(left_out) if left_out else ""))
    elif left_out:
        v.notes.append("Shared code is not drawn: %s left out; nothing here copies from it."
                       % ", ".join(left_out))
    if dropped:
        v.notes.append("%d partly known or loose links have no application at one end; the "
                       "links report lists them." % dropped)
    return v
