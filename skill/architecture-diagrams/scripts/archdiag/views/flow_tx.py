"""Level 3, online: one path from a transaction, page or endpoint.

What is followed. An endpoint is followed through its handler *method* only: the calls that
method makes on the class's collaborators and, in each class reached, only the methods
called (the scanner's ``methods`` table on class / component nodes, ``method`` on their
Refs, ``handler_methods`` on endpoints). Where the scan could not tell which method runs,
the whole class is followed as before, and a note says so.

What is numbered. Inside one box the links are in source order (the evidence line in the
box's own file; a call to one of the class's own methods is followed in place). Steps are
numbered walking that order depth first, so a step's number is always higher than the
step that led to it. A loose end, a "which program?" gap, a link whose place in its source
is not known and everything reached only through such a link carry no number.
"""
from __future__ import annotations

from collections import deque
from typing import Dict, Iterator, List, Optional, Set, Tuple

from archdiag.model import CONFIRMED, Edge, Evidence, Node
from archdiag.views.common import (_GAP_OPS, TX_DEPTH, ViewGraph, _add_suggested_within, _combine,
                                   _Ctx, _display, _key_label, _mark_missing, _op_label,
                                   _scope_error)

_TX_FOLLOW = ("uses", "http", "put", "get", "triggers", "runs", "link", "xctl", "call", "select",
              "insert", "update", "delete", "fetch", "sql", "send_map", "receive_map", "start",
              "return_transid", "read", "write", "open", "transfer", "file_dataset") + _GAP_OPS
_MAP_OPS = ("send_map", "receive_map")
LABEL_MAX = 20  # characters of a line label; the layout wraps longer ones into a tall pill
_CODE = ("class", "component")  # boxes with methods
_WHOLE = "*"   # a class followed as a whole: which of its methods runs is not known
_READ = "r"    # a queue reached by a read: nothing follows from reading it
_State = Tuple[str, str]  # (node id, mode: a method name, _WHOLE, _READ or "")


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


class _Link:
    """One link met by the walk, from the state it was followed from to the state it leads
    to. ``src`` and ``dst`` are the boxes the line is drawn between: a link of a folded
    handler class starts at its endpoint's box, a reader found backwards from a queue is
    drawn reader to queue."""

    def __init__(self, e: Edge, near: _State, far: _State, src: str, dst: str, label: str,
                 back: bool = False, meth: Optional[str] = None, ordered: bool = True) -> None:
        self.e, self.near, self.far, self.src, self.dst = e, near, far, src, dst
        self.label, self.back, self.meth, self.ordered = label, back, meth, ordered

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.src, self.dst, self.label)


class _Walk:
    """What follows from each box, in source order."""

    def __init__(self, ctx: _Ctx) -> None:
        self.ctx, self.nodes = ctx, ctx.nodes
        # the method each scanned statement sits in, by (source box, evidence)
        self.meth: Dict[Tuple[str, Evidence], str] = {}
        for ref in ctx.r.inventory.refs:
            m = ref.attrs.get("method")
            if m:
                self.meth[(ref.src, ref.evidence)] = str(m)
        self.calls: Dict[Tuple[str, str, str], Edge] = {}  # view-time "calls" edges
        # endpoint -> handler class, method, "runs" edge; page -> component, "", "uses" edge
        self.folded: Dict[str, Tuple[str, str, Edge]] = {}
        self.unsure: Dict[_State, str] = {}  # states whose class is followed whole -> class
        self.unplaced: List[_Link] = []      # "uses" links with no call found in the source

    # ---------------------------------------------------------------- small helpers
    def table(self, nid: str) -> Dict[str, dict]:
        n = self.nodes.get(nid)
        t = n.attrs.get("methods") if n is not None else None
        return t if isinstance(t, dict) else {}

    def method_of(self, e: Edge) -> Optional[str]:
        return self.meth.get((e.src, e.evidence[0])) if e.evidence else None

    def code_state(self, nid: str, method: Optional[str]) -> _State:
        """The state a box is entered in when ``method`` of it is called."""
        n = self.nodes.get(nid)
        if n is None or n.kind not in _CODE:
            return (nid, "")
        return (nid, method if method and method in self.table(nid) else _WHOLE)

    def far(self, e: Edge) -> _State:
        d = self.nodes.get(e.dst)
        if d is not None and d.kind == "queue":
            return (e.dst, _READ if e.op == "get" else "")
        return self.code_state(e.dst, None)

    def line(self, e: Edge, n: Optional[Node]) -> Tuple[int, int]:
        """Where a link sits in its source box's own file: (0, line), or (1, 0) when its
        evidence is elsewhere (those keep their order, after the others)."""
        own = {(ev.repo, ev.path) for ev in n.evidence} if n is not None else set()
        for ev in e.evidence:
            if (ev.repo, ev.path) in own:
                return (0, ev.line)
        return (1, 0)

    def label(self, e: Edge) -> str:
        """Verb plus object: ``MQ PUT CLM.REQ``, ``SELECT CLMS.CLAIM``, ``LINK CLMO110``;
        the verb alone when the name is not worked out. A name that would make the label
        longer than LABEL_MAX stays on the target's box only (a REST call keeps its HTTP
        method: ``REST GET``). A gap keeps its own wording."""
        base = _op_label(e, self.nodes)
        if e.op in _GAP_OPS or e.op == "suggested":
            return base
        n = self.nodes.get(e.dst)
        if n is not None and n.name and not n.name.startswith("?"):
            obj = _display(n)
            if len(base) + 1 + len(obj) > LABEL_MAX:
                bits = obj.split(None, 1)
                obj = bits[0] if e.op == "http" and len(bits) == 2 else ""
            if obj:
                base = "%s %s" % (base, obj)
        gdg = self.ctx.gdg.get(id(e))
        return "%s (%s)" % (base, gdg) if gdg else base

    # ---------------------------------------------------------------- what follows a box
    def links(self, st: _State) -> List[_Link]:
        nid, mode = st
        n = self.nodes.get(nid)
        kind = n.kind if n is not None else ""
        if kind in _CODE:
            return self.code_links(nid, mode, st, nid)
        fwd: List[Tuple[Tuple[int, int], int, _Link]] = []
        out = [e for e in self.ctx.out.get(nid, []) if e.op in _TX_FOLLOW]
        handler: List[_Link] = []
        if kind == "endpoint":
            runs = [e for e in out if e.op == "runs"]
            known = n.attrs.get("handler_methods") or {}  # type: ignore[union-attr]
            meth = str(known.get(runs[0].dst) or "") if len(runs) == 1 else ""
            if meth and runs[0].status == CONFIRMED and meth in self.table(runs[0].dst):
                # one handler method, read reliably: the endpoint's box stands for it and
                # the method's own links start here (the hop is not a step)
                self.folded[nid] = (runs[0].dst, meth, runs[0])
                handler = self.code_links(runs[0].dst, meth, st, nid)
                out = [e for e in out if e.op != "runs"]
        elif kind == "page" and len(out) == 1 and out[0].op == "uses" \
                and out[0].status == CONFIRMED and out[0].dst in self.nodes \
                and self.nodes[out[0].dst].kind == "component":
            # a route to one component: the page's box stands for it. Any of its methods
            # may run while the page is open, so it is followed whole
            self.folded[nid] = (out[0].dst, "", out[0])
            handler = self.code_links(out[0].dst, _WHOLE, st, nid)
            out = []
        for i, e in enumerate(out):
            if kind == "queue" and mode == _READ and e.op not in _GAP_OPS:
                continue
            far = self.far(e)
            if e.op == "runs" and kind == "endpoint":
                known = n.attrs.get("handler_methods") or {}  # type: ignore[union-attr]
                far = self.code_state(e.dst, str(known.get(e.dst) or ""))
            fwd.append((self.line(e, n), i, _Link(e, st, far, nid, e.dst, self.label(e))))
        res = handler + [x[2] for x in sorted(fwd, key=lambda x: x[:2])]
        if kind == "queue" and mode != _READ:
            # who reads what was put: found backwards from the queue
            for e in self.ctx.inn.get(nid, []):
                if e.op == "get":
                    res.append(_Link(e, st, self.code_state(e.src, self.method_of(e)), e.src,
                                     e.dst, self.label(e), back=True))
        return res

    def code_links(self, cid: str, mode: str, near: _State, src: str) -> List[_Link]:
        """The links of class / component ``cid`` entered in ``mode``, drawn from ``src``."""
        n = self.nodes[cid]
        table = self.table(cid)
        ops = [e for e in self.ctx.out.get(cid, []) if e.op in _TX_FOLLOW and e.op != "uses"]
        uses: Dict[str, Edge] = {}
        for e in self.ctx.out.get(cid, []):
            if e.op == "uses":
                uses.setdefault(e.dst, e)
        called = {c.get("class") for m in table.values() for c in m.get("calls", [])}
        path = n.evidence[0].path if n.evidence else ""
        out: List[_Link] = []
        have: Set[int] = set()

        def add(lk: _Link) -> None:
            if id(lk.e) not in have:
                have.add(id(lk.e))
                out.append(lk)

        def op_link(e: Edge, meth: Optional[str], ordered: bool = True) -> _Link:
            return _Link(e, near, self.far(e), src, e.dst, self.label(e), meth=meth,
                         ordered=ordered)

        def call_link(c: dict, meth: Optional[str], ordered: bool = True) -> None:
            u = uses.get(str(c.get("class")))
            if u is None:
                return  # no resolver link to that class: nothing to stand on
            m = c.get("method")
            if not m:  # used, but not as a plain call: which method runs is not known
                add(_Link(u, near, self.code_state(u.dst, None), src, u.dst, self.label(u),
                          meth=meth, ordered=ordered))
                return
            key = (cid, u.dst, str(m))
            if key not in self.calls:
                site = Evidence(n.repo or "", path, int(c.get("line") or 0),
                                str(c.get("text") or ""))
                self.calls[key] = Edge(cid, "calls", u.dst, u.status, u.reason,
                                       [site] + list(u.evidence))
            add(_Link(self.calls[key], near, self.code_state(u.dst, str(m)), src, u.dst,
                      "calls %s()" % m, meth=meth, ordered=ordered))

        def unplaced() -> None:
            """Collaborators no call was found for: the class-level link, as before."""
            for dst, u in uses.items():
                if dst not in called:
                    lk = _Link(u, near, self.code_state(dst, None), src, dst, self.label(u),
                               ordered=False)
                    add(lk)
                    self.unplaced.append(lk)

        if mode != _WHOLE and mode in table:
            seen: Set[str] = set()

            def expand(m: str) -> None:
                if m in seen or m not in table:
                    return
                seen.add(m)
                items: List[Tuple[int, int, int, str, object]] = []
                for i, e in enumerate(ops):
                    if self.method_of(e) == m:
                        items.append((self.line(e, n)[1], 0, i, "op", e))
                for i, c in enumerate(table[m].get("calls", [])):
                    items.append((int(c.get("line") or 0), 1, i, "call", c))
                for i, s in enumerate(table[m].get("self", [])):
                    items.append((int(s.get("line") or 0), 2, i, "self", s))
                for _, _, _, what, x in sorted(items, key=lambda it: it[:3]):
                    if what == "op":
                        add(op_link(x, m))  # type: ignore[arg-type]
                    elif what == "call":
                        call_link(x, m)  # type: ignore[arg-type]
                    else:
                        expand(str(x.get("method")))  # type: ignore[attr-defined]

            expand(mode)
            # class-level code and statements whose method was not read: kept, not numbered
            for e in ops:
                if self.method_of(e) not in table:
                    add(op_link(e, None, False))
            for c in table.get("", {}).get("calls", []):
                call_link(c, None, False)
            unplaced()
            return out
        items = [(self.line(e, n), 0, i, "op", e, self.method_of(e)) for i, e in enumerate(ops)]
        for name in table:
            for i, c in enumerate(table[name].get("calls", [])):
                items.append(((0, int(c.get("line") or 0)), 1, i, "call", c, name or None))
        for _, _, _, what, x, meth in sorted(items, key=lambda it: it[:3]):
            if what == "op":
                add(op_link(x, meth))  # type: ignore[arg-type]
            else:
                call_link(x, meth)  # type: ignore[arg-type]
        unplaced()
        # which method runs is not known: the order holds only inside one method
        real = [lk for lk in out if lk.e.op not in _GAP_OPS]
        if len(real) > 1 and (len({lk.meth for lk in out}) > 1 or out[0].meth is None):
            for lk in out:
                lk.ordered = False
            self.unsure[near] = cid
        return out


def _dfs(starts: List[_State], links_from: Dict[_State, List[_Link]], enter) -> Set[_State]:
    """Depth first from ``starts``, each state's links in order; ``enter(link)`` says
    whether to walk on into the state the link leads to. Returns the states walked."""
    done: Set[_State] = set()
    for s in starts:
        if s in done:
            continue
        done.add(s)
        stack: List[Iterator[_Link]] = [iter(links_from.get(s, ()))]
        while stack:
            lk = next(stack[-1], None)
            if lk is None:
                stack.pop()
            elif enter(lk) and lk.far not in done:
                done.add(lk.far)
                stack.append(iter(links_from.get(lk.far, ())))
    return done


def flow_tx(ctx: _Ctx, scope: Optional[str]) -> ViewGraph:
    starts, title = _tx_starts(ctx, scope) if scope else ([], "")
    if not starts:
        raise _scope_error(ctx.r, ctx.g, scope, ["transactions", "pages", "endpoints"],
                           "transaction, page or endpoint")
    nodes = ctx.nodes
    walk = _Walk(ctx)
    first: List[_State] = [(s, "") for s in starts]
    # 1. what is on the picture: breadth first along runtime links, at most TX_DEPTH hops
    # (a "runs" hop from an endpoint or a transaction costs none)
    dist: Dict[_State, int] = {s: 0 for s in first}
    popped: Set[_State] = set()
    links_from: Dict[_State, List[_Link]] = {}
    every: Dict[_State, List[_Link]] = {}  # each walked state's links, in source order
    steps: Dict[int, _Link] = {}
    cut: Dict[int, str] = {}  # links not followed: edge id -> the box past the cut
    dq = deque(first)
    while dq:
        u = dq.popleft()
        if u in popped:
            continue
        popped.add(u)
        every[u] = walk.links(u)
        for lk in every[u]:
            if id(lk.e) in steps:
                continue
            free = lk.e.op == "runs" and not lk.back
            nd = dist[u] + (0 if free else 1)
            w = lk.far
            if not (w in dist and dist[w] <= nd):
                if nd > TX_DEPTH:
                    if lk.e.op not in _MAP_OPS:  # a program on the path keeps its 3270 maps
                        cut.setdefault(id(lk.e), w[0])
                        continue
                else:
                    dist[w] = nd
                    if free:
                        dq.appendleft(w)
                    else:
                        dq.append(w)
            steps[id(lk.e)] = lk
            links_from.setdefault(u, []).append(lk)

    # a reader found backwards that the path also reaches going forwards: the read is one
    # of the reader's own steps, in its own source order
    ahead = _dfs(first, {u: [lk for lk in ls if not lk.back] for u, ls in links_from.items()},
                 lambda lk: True)
    for u in list(links_from):
        for lk in [x for x in links_from[u] if x.back and x.far in ahead]:
            own = every.get(lk.far, [])
            fl = next((x for x in own if x.e is lk.e), None)
            if fl is None:
                continue
            links_from[u].remove(lk)
            steps[id(lk.e)] = fl
            pos = {id(x): i for i, x in enumerate(own)}
            mine = links_from.setdefault(lk.far, [])
            mine.append(fl)
            mine.sort(key=lambda x: pos.get(id(x), len(pos)))

    # 2. the numbers: only links whose place in the order is known, to a box that exists
    def numbered(lk: _Link) -> bool:
        d = nodes.get(lk.dst if not lk.back else lk.src)
        return lk.ordered and lk.e.op not in _GAP_OPS and d is not None and d.kind != "missing"

    num: Dict[Tuple[str, str, str], int] = {}

    def count(lk: _Link) -> bool:
        if not numbered(lk):
            return False
        num.setdefault(lk.key, len(num) + 1)
        return True

    on_path = _dfs(first, links_from, count)
    if len(num) < 2:  # one step alone says nothing about order
        num.clear()
    # 3. every link, in the same walk; a link without a number leads on only to boxes the
    # numbered path does not reach
    drawn: List[_Link] = []

    def draw(lk: _Link) -> bool:
        drawn.append(lk)
        return (lk.near in on_path and numbered(lk)) or lk.far not in on_path

    _dfs(first, links_from, draw)
    keyed = [(lk.key, lk.e) for lk in drawn]
    ids = set(starts) | {x for lk in drawn for x in (lk.src, lk.dst)}
    # a queue this flow only reads: what it triggers is context, drawn without a number
    for q, mode in sorted(popped):
        if mode == _READ and (q, "") not in popped:
            for e in ctx.out.get(q, []):
                if e.op == "triggers" and e.dst in ids and id(e) not in steps:
                    keyed.append(((e.src, e.dst, walk.label(e)), e))
    vedges = _combine(keyed, _key_label)
    for e in vedges:
        e.number = num.get((e.src, e.dst, e.label))
    order: List[str] = list(starts)
    for e in vedges:
        for x in (e.src, e.dst):
            if x not in order:
                order.append(x)
    vnodes = [ctx.vnode(nid, ctx.group_of_app(ctx.app.get(nid))) for nid in order]
    for vn in vnodes:
        if vn.id in walk.folded:
            cid, meth, runs = walk.folded[vn.id]
            cls = nodes[cid]
            vn.sublabel = "%s%s%s" % (cls.name, ".%s()" % meth if meth else "",
                                      " · %s" % cls.repo if cls.repo else "")
            vn.underlying.append(runs)
    _mark_missing(vnodes, vedges)
    v = ViewGraph(title, "flow_tx", scope, vnodes, vedges, ctx.vgroups(vnodes))
    _notes(ctx, walk, v, starts, on_path, links_from)
    # links beyond the cut, counted (not drawn) by walking on from where it stopped
    beyond: Set[int] = set(cut) - set(steps)
    if beyond:
        seen_b = {s[0] for s in dist}
        # walk on from the box each cut link leads to (a forward read leads to its queue,
        # a reader found backwards to the reader), counting distinct links (B9)
        far = [cut[i] for i in sorted(beyond)]
        dq2 = deque(x for x in far if x not in seen_b)
        while dq2:
            b = dq2.popleft()
            if b in seen_b:
                continue
            seen_b.add(b)
            for e, w2 in ([(e, e.dst) for e in ctx.out.get(b, []) if e.op in _TX_FOLLOW] +
                          [(e, e.src) for e in ctx.inn.get(b, []) if e.op == "get"]):
                if id(e) not in steps:
                    beyond.add(id(e))
                if w2 not in seen_b:
                    dq2.append(w2)
    left = len(beyond)
    if left:
        v.notes.append("Stopped after %d hops; %d more links not drawn" % (TX_DEPTH, left))
    _add_suggested_within(ctx, v)
    for e in v.edges:  # a suggested link is not a proven step: it carries no number
        if e.underlying and e.underlying[0].op == "suggested":
            e.number = None
    return v


def _notes(ctx: _Ctx, walk: _Walk, v: ViewGraph, starts: List[str], on_path: Set[_State],
           links_from: Dict[_State, List[_Link]]) -> None:
    """Say where the scan could not tell which calls belong to this flow."""
    nodes = ctx.nodes
    kind = nodes[starts[0]].kind if starts[0] in nodes else ""
    this = "this page" if kind == "page" else "this flow"
    if len(starts) > 1:
        v.notes.append("%d entry points match this scope; their steps are numbered one after "
                       "the other, not in time order" % len(starts))
    told: Set[str] = set()
    for st in sorted(walk.unsure):
        lks = [lk for lk in links_from.get(st, []) if lk.e.op not in _GAP_OPS]
        cid = walk.unsure[st]
        if len(lks) < 2 or cid in told:
            continue
        told.add(cid)
        name = nodes[cid].name
        note = ("%s makes %d different calls and the scan cannot tell which of them %s makes: "
                "all are drawn, and nothing from %s on is numbered"
                % (name, len(lks), this, name))
        eps = [nodes[lk.dst].name for lk in lks
               if lk.dst in nodes and nodes[lk.dst].kind in ("endpoint", "zosapi")]
        if eps:
            note += ". Each endpoint can be drawn as its own flow, for example --scope \"%s\"" \
                % eps[0]
        v.notes.append(note)
    for lk in walk.unplaced:
        if lk.dst in told or lk.dst not in nodes or id(lk.e) not in {
                id(x.e) for x in links_from.get(lk.near, [])}:
            continue
        told.add(lk.dst)
        v.notes.append("No call from %s to %s was found in the source (it is only handed "
                       "one): that link and what follows it carry no step number"
                       % (nodes[lk.e.src].name if lk.e.src in nodes else lk.e.src,
                          nodes[lk.dst].name))
