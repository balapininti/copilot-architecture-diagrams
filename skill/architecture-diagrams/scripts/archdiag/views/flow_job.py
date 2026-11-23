"""Level 3, batch: one job's numbered steps in a lane, its inputs above, its outputs below.

A dataset or table is placed by what the job does to it first: read first, it is an input
(above); written first, it is an output (below), and it feeds a later step that reads it
from there."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from archdiag.model import CONFIRMED, PARTIAL, Edge, Node
from archdiag.views.common import (_GAP_LABEL, _GAP_OPS, VEdge, VNode, ViewGraph,
                                   _add_suggested_within, _Ctx, _combine, _count, _evidence,
                                   _key_label, _mark_missing, _missing_label, _scope_error,
                                   _where, combine_status)


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
    for num, st in enumerate(steps, 1):
        runs = [e for e in ctx.out.get(st.id, []) if e.op == "runs"]
        runs_of[st.id] = runs
        tgt = nodes.get(runs[0].dst) if runs else None
        pgm, proc = st.attrs.get("pgm"), st.attrs.get("proc")
        if tgt is None:
            what, kind = str(pgm or proc or "?"), "program"
        else:
            what = tgt.name
            kind = tgt.kind if tgt.kind in ("utility", "notanalyzed", "missing") else "program"
        if pgm and str(pgm) != what:
            what = "%s → %s" % (pgm, what)  # IKJEFT01 → the program it runs
        if proc and str(proc) != what:
            what += " (proc %s)" % proc
        status = combine_status(e.status for e in runs) if runs else PARTIAL
        # the caption reads "3 STEP030 IKJEFT01 → CLMB300": its place in the JCL, its name,
        # what it runs
        add(VNode(st.id, "%d %s" % (num, st.name), what, kind, None,
                  None if status == CONFIRMED else status,
                  row="lane", underlying=list(runs), real_kind=kind))

    # the DD statement behind each data line of a step, from the scanner Ref it was made from
    ref_at = {(x.src, x.evidence): x.attrs for x in ctx.r.inventory.refs
              if x.src in runs_of}

    def data_label(e: Edge) -> str:
        """``CLMOUT write (+1) · NEW,CATLG``: the DD name and DISP when the scan
        has them; a transfer names the remote dataset."""
        base = ctx.op_label(e)
        a = ref_at.get((e.src, e.evidence[0])) if e.evidence else None
        if not a:
            return base
        if e.op == "transfer":
            dsn = a.get("remote_dsn")
            return "%s %s %s" % (base, "from" if a.get("direction") == "receive" else "to",
                                 dsn) if dsn else base
        if a.get("via"):  # named on a control card, not by a DD of its own
            return base
        # kept short, so the label stays on its line: "SYSUT2 write · NEW,CATLG"
        text = "%s %s" % (a["ddname"], base) if a.get("ddname") else base
        disp = str(a.get("disp") or "").strip("()")
        return "%s · %s" % (text, disp) if disp else text

    keyed: List[Tuple[tuple, Edge]] = []
    first: Dict[str, str] = {}  # data -> "above" (read first) or "below" (written first)
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
        touched: List[Tuple[bool, str]] = []
        for e in ctx.out.get(st.id, []) + [x for p in progs for x in ctx.out.get(p, [])]:
            d = nodes.get(e.dst)
            if e.op not in _DATA_OPS or d is None or d.attrs.get("temp"):
                continue
            box = st.id if e.src == st.id or e.src in run_progs else e.src
            if e.op in _READ_OPS:
                keyed.append(((e.dst, box, data_label(e)), e))
            else:
                keyed.append(((box, e.dst, data_label(e)), e))
            touched.append((e.op not in _READ_OPS, e.dst))
        # placed by what the job does to it first; a step that reads and writes one thing
        # reads it first
        for wrote, nid in sorted(touched, key=lambda t: t[0]):
            first.setdefault(nid, "below" if wrote else "above")

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
            keyed.append(((e.src, t, data_label(e)), e))
        for e in rs:
            keyed.append(((t, e.src, data_label(e)), e))
        first[t] = "below" if wi and (not ri or min(wi) < min(ri)) else "above"

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

    # loose ends and look-alikes of the data shown. "No reader found" and "no writer found"
    # are a marker on the dataset itself, which keeps the edge for the links report
    data_ids = {k[0] for k, _ in keyed} | {k[1] for k, _ in keyed}
    marks: Dict[str, List[str]] = {}
    held: Dict[str, List[Edge]] = {}
    for nid in sorted(data_ids - set(lane_ids)):
        for e in ctx.edges_of(nid):
            if e.op not in _GAP_OPS or any(x is e for _, x in keyed) \
                    or any(x is e for es in held.values() for x in es):
                continue
            other = e.dst if e.src == nid else e.src
            on = nodes.get(other)
            if e.src == nid and on is not None and on.kind == "missing" \
                    and on.attrs.get("target_kind") in _GAP_LABEL \
                    and len(ctx.edges_of(other)) == 1:
                text = _missing_label(on)[0]
                if text not in marks.setdefault(nid, []):
                    marks[nid].append(text)
                held.setdefault(nid, []).append(e)
                continue
            keyed.append(((e.src, e.dst, ctx.op_label(e)), e))
            row_hint.setdefault(other, first.get(nid) or row_hint.get(nid, "below"))

    vedges = _combine(keyed, _key_label)
    for e in vedges:
        for nid in (e.src, e.dst):
            if nid in vnodes:
                continue
            row = first.get(nid) or row_hint.get(nid, "below")
            vn = add(ctx.vnode(nid, None, row))
            if vn.kind in ("dataset", "vsam", "gdg"):
                how = (["read"] if any(x.src == nid and x.dst in lane_ids for x in vedges) else []) \
                    + (["written"] if any(x.dst == nid and x.src in lane_ids for x in vedges) else [])
                if row == "below":
                    how.reverse()  # in the order the job does it: written, then read
                if how:
                    vn.sublabel = " · ".join(([vn.sublabel] if vn.sublabel != "dataset" else [])
                                             + how)
            if nid in marks:
                vn.detail_lines = list(marks[nid])
                vn.highlight = len(marks[nid])
                vn.underlying = list(held[nid])
    # SYSOUT outputs of each step (no edge behind them: the DD statement itself)
    for st in steps:
        for so in st.attrs.get("sysout") or []:
            sid = "sysout:%s:%s" % (st.id, str(so).split(" ", 1)[0])
            if sid in vnodes:
                continue
            dd, _, cls = str(so).partition(" ")
            add(VNode(sid, dd, cls.strip("()") or "SYSOUT", "dataset", None, None, row="below"))
            vedges.append(VEdge(st.id, sid, "write", CONFIRMED, "sequence", list(st.evidence[:1])))
    if held:
        n = sum(len(es) for es in held.values())
        notes.append("%s marked on %s (%s), not drawn as %s; the links report lists each one."
                     % (_count(n, "loose end is", "loose ends are"),
                        "its dataset" if n == 1 else "their datasets",
                        ", ".join(sorted({m for ms in marks.values() for m in ms})),
                        "a box" if n == 1 else "boxes"))
    allv = [vnodes[i] for i in order]
    _mark_missing(allv, vedges)
    v = ViewGraph("Job %s" % job.name, "flow_job", job.name, allv, step_edges + vedges, [], notes)
    _add_suggested_within(ctx, v)
    return v
