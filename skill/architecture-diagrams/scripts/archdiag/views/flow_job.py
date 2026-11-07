"""Level 3, batch: one job's steps in a lane, data read above, data written below."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from archdiag.model import CONFIRMED, PARTIAL, Edge, Node
from archdiag.views.common import (_GAP_OPS, VEdge, VNode, ViewGraph, _add_suggested_within, _Ctx,
                                   _combine, _evidence, _is_table, _key_label, _mark_missing,
                                   _scope_error, _where, combine_status)


_RUN_IF = {"GT": "≥", "GE": ">", "EQ": "≠", "NE": "=", "LT": "≤", "LE": "<"}
_ABEND = {"EVEN": "even after an abend", "ONLY": "only after an abend"}


def cond_label(cond: Optional[str]) -> str:
    """When a step runs, in plain words: ``COND=(0,NE)`` gives ``"if RC = 0"`` (COND names
    when to skip a step, so each test is turned round), ``RC <= 4`` gives ``"if RC ≤ 4"``."""
    if not cond:
        return ""
    parts = []
    for part in re.split(r"\s+AND\s+", cond.strip()):
        part = part.strip()
        m = re.match(r"^COND=(.*)$", part, re.I)
        if not m:
            for a, b in (("<=", "≤"), (">=", "≥"), ("¬=", "≠"), ("!=", "≠")):
                part = part.replace(a, b)
            parts.append(part)
            continue
        body = m.group(1).strip().upper()
        if body in _ABEND:
            parts.append(_ABEND[body])
            continue
        tests = re.findall(r"\(\s*(\d+)\s*,\s*([A-Z]{2})\s*(?:,\s*([A-Z0-9#@$.]+))?\s*\)", body)
        words = ["%sRC %s %d" % ("%s " % step if step else "", _RUN_IF[op], int(code))
                 for code, op, step in tests if op in _RUN_IF]
        if not words or len(words) != len(tests):
            parts.append(part)  # not understood: shown as written
            continue
        words += [_ABEND[x] for x in re.findall(r"\b(EVEN|ONLY)\b", body)]
        parts.append(" and ".join(words))
    text = " and ".join(parts)
    return text if text.startswith(("even ", "only ")) else "if %s" % text


_DATA_OPS = ("select", "insert", "update", "delete", "fetch", "sql", "read", "write", "put",
             "get", "open", "http", "transfer", "file_dataset")
_READ_OPS = ("read", "get", "select", "fetch")
_CALL_OPS = ("call", "link", "xctl")


def flow_job(ctx: _Ctx, scope: Optional[str]) -> ViewGraph:
    nodes = ctx.nodes
    jobs = sorted((n for n in nodes.values() if n.kind == "job"),
                  key=lambda n: (_where(n.evidence[0]) if n.evidence else n.id, n.id))
    pick: List[Node] = []
    if scope:
        sid = scope if scope.startswith("job:") else "job:" + scope
        pick = [n for n in jobs if n.id == sid] or \
            [n for n in jobs if n.name.upper() == scope.strip().upper()]
    if not pick:
        raise _scope_error(ctx.r, ctx.g, scope, ["jobs"], "job")
    job = pick[0]
    notes = []
    same = [n for n in jobs if n.name == job.name and n.id != job.id]
    if same:
        notes.append("Also exists as: %s" % ", ".join(
            _where(n.evidence[0]) if n.evidence else n.id for n in same))
    steps = sorted((n for n in nodes.values() if n.kind == "step" and n.attrs.get("job") == job.id),
                   key=lambda n: (n.attrs.get("order") or 0, n.id))
    lane_ids = [s.id for s in steps]
    vnodes: Dict[str, VNode] = {}
    order: List[str] = []

    def add(vn: VNode) -> VNode:
        if vn.id not in vnodes:
            vnodes[vn.id] = vn
            order.append(vn.id)
        return vnodes[vn.id]

    add(ctx.vnode(job.id))
    # the lane: one box per step, labeled with what it runs; the box stands for that edge
    runs_of: Dict[str, List[Edge]] = {}
    for st in steps:
        runs = [e for e in ctx.out.get(st.id, []) if e.op == "runs"]
        runs_of[st.id] = runs
        tgt = nodes.get(runs[0].dst) if runs else None
        if tgt is None:
            label, kind = str(st.attrs.get("pgm") or st.attrs.get("proc") or "?"), "program"
        else:
            label = tgt.name
            kind = tgt.kind if tgt.kind in ("utility", "notanalyzed", "missing") else "program"
        sub = st.name + (" (proc %s)" % st.attrs["proc"] if st.attrs.get("proc") else "")
        status = combine_status(e.status for e in runs) if runs else PARTIAL
        add(VNode(st.id, label, sub, kind, None, None if status == CONFIRMED else status,
                  row="lane", underlying=list(runs)))

    keyed: List[Tuple[tuple, Edge]] = []
    written: Set[str] = set()
    row_hint: Dict[str, str] = {}
    # what each step touches: its DD statements, the data of the program it runs (drawn on
    # the step box), and the programs that one calls (drawn below, with their own data)
    for st in steps:
        run_progs = [e.dst for e in runs_of[st.id]
                     if nodes.get(e.dst) is not None and nodes[e.dst].kind == "program"]
        progs = list(run_progs)
        frontier, depth = list(progs), 0
        while frontier and depth < 3:
            nxt = []
            for p in frontier:
                for e in ctx.out.get(p, []):
                    if e.op not in _CALL_OPS:
                        continue
                    keyed.append((((st.id if p in run_progs else p), e.dst, ctx.op_label(e)), e))
                    row_hint.setdefault(e.dst, "below")
                    dn = nodes.get(e.dst)
                    if dn is not None and dn.kind == "program" and e.dst not in progs:
                        progs.append(e.dst)
                        nxt.append(e.dst)
            frontier, depth = nxt, depth + 1
        for e in ctx.out.get(st.id, []) + [x for p in progs for x in ctx.out.get(p, [])]:
            d = nodes.get(e.dst)
            if e.op not in _DATA_OPS or d is None or d.attrs.get("temp"):
                continue
            box = st.id if e.src == st.id or e.src in run_progs else e.src
            if _is_table(d):
                row_hint[e.dst] = "above"  # the databases sit over the steps
                if e.op in _READ_OPS:
                    keyed.append(((e.dst, box, ctx.op_label(e)), e))
                else:
                    keyed.append(((box, e.dst, ctx.op_label(e)), e))
            elif e.op in _READ_OPS:
                keyed.append(((e.dst, box, ctx.op_label(e)), e))
                row_hint.setdefault(e.dst, "above")
            else:
                keyed.append(((box, e.dst, ctx.op_label(e)), e))
                written.add(e.dst)

    # temporary datasets passed straight to the next step become that line's label
    temp_w: Dict[str, List[Edge]] = {}
    temp_r: Dict[str, List[Edge]] = {}
    for st in steps:
        for e in ctx.out.get(st.id, []):
            d = nodes.get(e.dst)
            if d is not None and d.kind == "dataset" and d.attrs.get("temp"):
                (temp_r if e.op in _READ_OPS else temp_w).setdefault(e.dst, []).append(e)
    between: Dict[Tuple[str, str], List[Edge]] = {}
    for t in sorted(set(temp_w) | set(temp_r)):
        ws, rs = temp_w.get(t, []), temp_r.get(t, [])
        wi = {lane_ids.index(e.src) for e in ws}
        ri = {lane_ids.index(e.src) for e in rs}
        if len(wi) == 1 and len(ri) == 1 and min(ri) == min(wi) + 1 and \
                all(e.status == CONFIRMED for e in ws + rs):
            between.setdefault((lane_ids[min(wi)], lane_ids[min(ri)]), []).extend(ws + rs)
            continue
        for e in ws:
            keyed.append(((e.src, t, ctx.op_label(e)), e))
            written.add(t)
        for e in rs:
            keyed.append(((t, e.src, ctx.op_label(e)), e))
            row_hint.setdefault(t, "above")

    # step-to-step lines, labeled with when the step they lead to runs
    step_edges: List[VEdge] = []
    prev = job.id
    for st in steps:
        temps = between.get((prev, st.id), [])
        names: List[str] = []
        for e in temps:
            nm = nodes[e.dst].name if e.dst in nodes else e.dst
            if nm not in names:
                names.append(nm)
        label = " · ".join(x for x in [cond_label(st.attrs.get("cond"))] + names if x)
        ev = _evidence(temps)
        ev += [x for x in st.evidence[:1] if x not in ev]
        step_edges.append(VEdge(prev, st.id, label, CONFIRMED, "sequence", ev, None, list(temps)))
        prev = st.id

    # loose ends and look-alikes of the data shown
    data_ids = {k[0] for k, _ in keyed} | {k[1] for k, _ in keyed}
    for nid in sorted(data_ids - set(lane_ids)):
        for e in ctx.edges_of(nid):
            if e.op in _GAP_OPS and not any(x is e for _, x in keyed):
                keyed.append(((e.src, e.dst, ctx.op_label(e)), e))
                other = e.dst if e.src == nid else e.src
                row_hint.setdefault(other, "below" if nid in written or
                                    row_hint.get(nid, "below") == "below" else "above")

    vedges = _combine(keyed, _key_label)
    for e in vedges:
        for nid in (e.src, e.dst):
            if nid in vnodes:
                continue
            # written by any step is below (even if read later); only read is above
            row = "above" if _is_table(nodes.get(nid)) else \
                "below" if nid in written else row_hint.get(nid, "below")
            vn = add(ctx.vnode(nid, None, row))
            if vn.kind in ("dataset", "vsam", "gdg"):
                how = (["read"] if any(x.src == nid and x.dst in lane_ids for x in vedges) else []) \
                    + (["written"] if any(x.dst == nid and x.src in lane_ids for x in vedges) else [])
                if how:
                    vn.sublabel = " · ".join(([vn.sublabel] if vn.sublabel != "dataset" else [])
                                             + how)
    # SYSOUT outputs of each step (no edge behind them: the DD statement itself)
    for st in steps:
        for so in st.attrs.get("sysout") or []:
            sid = "sysout:%s:%s" % (st.id, str(so).split(" ", 1)[0])
            if sid in vnodes:
                continue
            dd, _, cls = str(so).partition(" ")
            add(VNode(sid, dd, cls.strip("()") or "SYSOUT", "dataset", None, None, row="below"))
            vedges.append(VEdge(st.id, sid, "write", CONFIRMED, "sequence", list(st.evidence[:1])))
    allv = [vnodes[i] for i in order]
    _mark_missing(allv, vedges)
    v = ViewGraph("Job %s" % job.name, "flow_job", job.name, allv, step_edges + vedges, [], notes)
    _add_suggested_within(ctx, v)
    return v
