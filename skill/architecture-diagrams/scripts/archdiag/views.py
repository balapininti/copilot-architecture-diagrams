"""What one diagram shows: nodes, edges and groups, ready to lay out and draw.

build_view() cuts the resolved link graph into one of five views (spec section 5):

* ``landscape``   - one box per application, the data stores and queues shared by two or
  more of them, outside systems and loose ends; lines combined per pair and kind of link.
* ``application`` - one application's members, with what it talks to outside as grey stubs.
* ``flow_job``    - one batch job: its steps in a lane, data read above, data written below.
* ``flow_tx``     - one online path from a transaction, page or endpoint, numbered in order.
* ``repomap``     - one card per repo, one line per link between two repos.

A line is never drawn more certain than the resolver decided. A combined line is
confirmed only if a confirmed edge is under it, otherwise partial if a partial one is,
otherwise loose; folding small items into a ``… N more`` box keeps lines of different
status apart. Every loose end and partly known link reaching the view is drawn, as a
``missing`` box or a dotted line. Copilot's suggested links are added here only, as partial.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from archdiag.model import CONFIRMED, LOOSE, PARTIAL, Edge, Evidence, Node, Resolved

LEVELS = ("landscape", "application", "flow_job", "flow_tx", "repomap")
MAX_NODES = 40
TX_DEPTH = 8  # flow_tx: hops followed from the start (a "runs" hop costs nothing)
GROUP_COLORS = ("#3b82f6", "#16a34a", "#9333ea", "#ca8a04", "#ea580c", "#0891b2", "#db2777",
                "#4f46e5")


@dataclass
class VNode:
    id: str
    label: str
    sublabel: str = ""
    kind: str = "program"
    group: Optional[str] = None
    status: Optional[str] = None
    detail_lines: List[str] = field(default_factory=list)
    row: Optional[str] = None  # "above" | "lane" | "below" for job flows
    highlight: int = 0  # repomap: the first N detail_lines are files holding link evidence
    # resolver edges this box stands for (a job step's "runs" edge), for the links report
    underlying: List[Edge] = field(default_factory=list)


@dataclass
class VEdge:
    src: str
    dst: str
    label: str = ""
    status: str = "confirmed"
    kind: str = "runtime"  # or "shared_code"
    evidence: List[Evidence] = field(default_factory=list)
    number: Optional[int] = None
    # the resolver edges drawn as this line (several when combined), for the links report
    underlying: List[Edge] = field(default_factory=list)


@dataclass
class VGroup:
    id: str
    label: str
    color: str


@dataclass
class ViewGraph:
    title: str
    level: str  # one of LEVELS
    scope: Optional[str]
    nodes: List[VNode]
    edges: List[VEdge]
    groups: List[VGroup]
    notes: List[str] = field(default_factory=list)


class ScopeError(ValueError):
    """A level or scope that names nothing; ``suggestions`` holds close matches."""

    def __init__(self, message: str, suggestions: Optional[List[str]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.suggestions = list(suggestions or [])


# ------------------------------------------------------------------ shared helpers

_RANK = {CONFIRMED: 0, PARTIAL: 1, LOOSE: 2}


def combine_status(statuses: Iterable[str]) -> str:
    """Confirmed if any is confirmed, else partial if any is partial, else loose."""
    s = set(statuses)
    if CONFIRMED in s:
        return CONFIRMED
    if PARTIAL in s:
        return PARTIAL
    return LOOSE


def _least_certain(statuses: Iterable[str]) -> str:
    return max(statuses, key=lambda x: _RANK.get(x, 2), default=CONFIRMED)


_SQL_OPS = ("select", "insert", "update", "delete", "fetch", "sql")
_OP_LABEL = {
    "select": "SELECT", "insert": "INSERT", "delete": "DELETE", "fetch": "FETCH", "sql": "SQL",
    "put": "MQ PUT", "get": "MQ GET", "open": "MQ open", "http": "REST", "read": "read",
    "write": "write", "link": "LINK", "xctl": "XCTL", "call": "CALL", "start": "START",
    "return_transid": "RETURN TRANSID", "send_map": "SEND MAP", "receive_map": "RECEIVE MAP",
    "runs": "runs", "triggers": "triggers", "transfer": "file transfer", "uses": "uses",
    "copy": "COPY", "maybe_same": "maybe the same", "file_dataset": "file",
}
_GAP_LABEL = {"reader": "no reader found", "writer": "no writer found",
              "queue-consumer": "no consumer found", "queue-producer": "no producer found"}
_KIND_MAP = {"zosapi": "endpoint", "mqprocess": "queue", "proc": "job", "copybook": "program"}
_SUB = {"program": "COBOL program", "class": "Java class", "component": "Angular",
        "page": "Angular page", "endpoint": "REST endpoint", "zosapi": "z/OS Connect API",
        "transaction": "CICS transaction", "map": "3270 map", "queue": "IBM MQ queue",
        "table": "DB2 table", "dataset": "dataset", "job": "JCL job", "utility": "utility",
        "copybook": "copybook", "cicsfile": "CICS file", "mqprocess": "MQ process",
        "proc": "JCL proc", "external": "outside these repos", "step": "job step"}
# what each member kind says about an application's technology, in display order
_TECH = (("page", "Angular"), ("component", "Angular"), ("class", "Java"), ("endpoint", "Java"),
         ("transaction", "CICS"), ("job", "JCL"), ("program", "COBOL"), ("map", "BMS"),
         ("table", "DB2"), ("zosapi", "z/OS Connect"), ("copybook", "COBOL copybooks"))
_COUNT_KINDS = ("page", "endpoint", "class", "transaction", "job", "program", "table", "queue",
                "copybook")
# missing targets that are by nature the other side of an exchange between applications
_CROSS_TARGETS = ("endpoint", "zosapi", "queue-consumer", "queue-producer", "reader", "writer")
_GAP_OPS = ("loose", "partial", "maybe_same")


def _is_table(n: Optional[Node]) -> bool:
    return n is not None and (n.kind == "table" or n.attrs.get("target_kind") == "table")


def _op_label(e: Edge, nodes: Dict[str, Node]) -> str:
    """The label of one link in the detailed views (application, flows)."""
    if e.op in ("loose", "partial"):
        d = nodes.get(e.dst)
        kind = d.attrs.get("target_kind") if d is not None else None
        return _GAP_LABEL.get(str(kind), e.reason or "not found")
    if e.op == "suggested":
        note = (e.reason or "").replace("suggested by Copilot", "").lstrip(": ")
        return "suggested: %s" % note if note else "suggested"
    if e.op == "update":
        return "UPDATE" if _is_table(nodes.get(e.dst)) else "update"
    return _OP_LABEL.get(e.op, e.op)


def _family(e: Edge, nodes: Dict[str, Node]) -> str:
    """The landscape's coarser kind of link."""
    if e.op in _SQL_OPS and (e.dst not in nodes or _is_table(nodes.get(e.dst))):
        return "SQL"
    fam = {"read": "reads", "write": "writes", "update": "updates", "open": "MQ",
           "send_map": "3270 map", "receive_map": "3270 map"}
    if e.op in fam:
        return fam[e.op]
    return _op_label(e, nodes)


def _display(n: Node) -> str:
    if n.kind == "dataset":
        names = n.attrs.get("names") or []
        return str(names[0]) if names else n.name
    return n.name


def _short(n: Node) -> str:
    if n.kind == "table":
        return str(n.attrs.get("name") or n.name.split(".")[-1])
    return _display(n)


def _where(ev: Evidence) -> str:
    return "%s/%s" % (ev.repo, ev.path) if ev.repo else ev.path


def _missing_label(n: Node) -> Tuple[str, str]:
    kind = str(n.attrs.get("target_kind", ""))
    if kind in _GAP_LABEL:
        return _GAP_LABEL[kind], ("queue %s" % n.name if kind.startswith("queue") else n.name)
    reason = n.attrs.get("reason")
    if n.name.startswith("?"):
        return "which %s?" % (kind or "item"), str(reason or "name not worked out")
    cands = n.attrs.get("candidates") or []
    if cands:
        return n.name, "one of: %s" % ", ".join(cands)
    return n.name, "%s not found in these repos" % (kind or "target")


def _tech(kinds: Set[str]) -> str:
    out: List[str] = []
    for k, t in _TECH:
        if k in kinds and t not in out:
            out.append(t)
    return " · ".join(out[:3])


def _plural(kind: str) -> str:
    return kind + ("es" if kind.endswith(("s", "x", "ch", "sh")) else "s")


def _counts_line(kinds: Sequence[str]) -> str:
    parts = []
    for k in _COUNT_KINDS:
        c = sum(1 for x in kinds if x == k)
        if c:
            parts.append("%d %s" % (c, k if c == 1 else _plural(k)))
    return " · ".join(parts[:3])


def _kind_of(key: tuple, es: List[Edge]) -> str:
    return "shared_code" if all(x.op == "copy" for x in es) else "runtime"


class _Ctx:
    """The resolved graph, its groups and the indexes every view needs."""

    def __init__(self, r: Resolved, g) -> None:
        from archdiag.groups import app_of
        self.r, self.g = r, g
        self.nodes = r.nodes
        self.app = {nid: app_of(g, r, nid) for nid in r.nodes}
        self.app_kind = {a.name: a.kind for a in g.apps}
        self.out: Dict[str, List[Edge]] = {}
        self.inn: Dict[str, List[Edge]] = {}
        for e in r.edges:
            self.out.setdefault(e.src, []).append(e)
            self.inn.setdefault(e.dst, []).append(e)
        # GDG generation of each data edge, from the scanner Ref it was made from
        ref_gdg = {(x.src, x.evidence): x.attrs.get("gdg") for x in r.inventory.refs
                   if x.attrs.get("gdg")}
        self.gdg: Dict[int, str] = {}
        for e in r.edges:
            if e.evidence and (e.src, e.evidence[0]) in ref_gdg:
                self.gdg[id(e)] = str(ref_gdg[(e.src, e.evidence[0])])
        self.gdg_sets = {e.dst for e in r.edges if id(e) in self.gdg}
        dsnames = {str(n.attrs.get("dsname")).upper() for n in r.nodes.values()
                   if n.kind == "cicsfile" and n.attrs.get("dsname")}
        self.vsam = {nid for nid, n in r.nodes.items() if n.kind == "dataset" and
                     dsnames & {str(x).upper() for x in (n.attrs.get("names") or [n.name])}}

    def op_label(self, e: Edge) -> str:
        """The detailed label of one link, with its GDG generation (``write (+1)``)."""
        label = _op_label(e, self.nodes)
        return "%s (%s)" % (label, self.gdg[id(e)]) if id(e) in self.gdg else label

    def edges_of(self, nid: str) -> List[Edge]:
        return self.out.get(nid, []) + self.inn.get(nid, [])

    @staticmethod
    def group_of_app(app: Optional[str]) -> Optional[str]:
        return "group:%s" % app if app else None

    def vgroups(self, nodes: List[VNode]) -> List[VGroup]:
        """Groups in use, in groups.json order; colors follow that order across views."""
        order = [a.name for a in self.g.apps]
        used = {n.group for n in nodes if n.group}
        out = []
        for i, name in enumerate(order + sorted({u[len("group:"):] for u in used} - set(order))):
            gid = "group:%s" % name
            if gid in used:
                out.append(VGroup(gid, name, GROUP_COLORS[i % len(GROUP_COLORS)]))
        return out

    def vnode(self, nid: str, group: Optional[str] = None, row: Optional[str] = None) -> VNode:
        n = self.nodes.get(nid)
        if n is None:  # an application end of a suggested link
            return VNode(nid, nid.split(":", 1)[-1], "application", "application", group, None)
        if n.kind == "missing":
            label, sub = _missing_label(n)
            ins = self.inn.get(nid, [])
            st = _least_certain(e.status for e in ins) if ins else LOOSE
            return VNode(nid, label, sub, "missing", group, LOOSE if st == CONFIRMED else st,
                         row=row)
        sub = _SUB.get(n.kind, n.kind)
        if n.kind == "notanalyzed":
            sub = "%s · not analyzed" % n.attrs.get("language", "code")
        if n.kind == "job" and n.evidence:
            sub = "JCL · %s" % _where(n.evidence[0])
        elif n.repo and n.kind not in ("dataset", "queue", "table", "external"):
            sub = "%s · %s" % (sub, n.repo)
        kind = _KIND_MAP.get(n.kind, n.kind)
        if n.kind == "dataset":
            if n.attrs.get("temp"):
                sub = "temporary dataset"
            elif nid in self.vsam:
                kind, sub = "vsam", "VSAM dataset"
            elif nid in self.gdg_sets:
                kind, sub = "gdg", "GDG"
        return VNode(nid, _display(n), sub, kind, group, None, row=row)


def _evidence(es: Iterable[Edge]) -> List[Evidence]:
    seen: Set[Evidence] = set()
    out = []
    for e in es:
        for ev in e.evidence:
            if ev not in seen:
                seen.add(ev)
                out.append(ev)
    return out


def _combine(keyed: List[Tuple[tuple, Edge]], make_label, kind_of=_kind_of) -> List[VEdge]:
    """One VEdge per key ``(src, dst, ...)`` in first-seen order, its status combined."""
    order: List[tuple] = []
    by: Dict[tuple, List[Edge]] = {}
    for key, e in keyed:
        if key not in by:
            by[key] = []
            order.append(key)
        if not any(x is e for x in by[key]):
            by[key].append(e)
    out = []
    for key in order:
        es = by[key]
        out.append(VEdge(key[0], key[1], make_label(key, es), combine_status(x.status for x in es),
                         kind_of(key, es), _evidence(es), None, list(es)))
    return out


def _key_label(key: tuple, es: List[Edge]) -> str:
    return key[2]


def _mark_missing(vnodes: Iterable[VNode], vedges: List[VEdge]) -> None:
    """A missing box shows the least certain status of the lines that reach it."""
    for vn in vnodes:
        if vn.kind == "missing":
            sts = [e.status for e in vedges if vn.id in (e.src, e.dst)]
            vn.status = _least_certain(sts) if sts else LOOSE
            if vn.status == CONFIRMED:
                vn.status = PARTIAL


def _names(scope: str, items: List[str]) -> List[str]:
    """Close matches to ``scope`` among the names of listing ``items`` (any case); every
    name when ``scope`` is empty."""
    names: List[str] = []
    for it in items:
        nm = it.rsplit(" (", 1)[0] if it.endswith(")") else it
        if nm not in names:
            names.append(nm)
    if not scope:
        return names
    up: Dict[str, str] = {}
    for nm in names:
        up.setdefault(nm.upper(), nm)
    return [up[h] for h in difflib.get_close_matches(scope.upper(), list(up), n=5, cutoff=0.6)]


def _scope_error(r: Resolved, g, scope: Optional[str], whats: Sequence[str], noun: str) -> ScopeError:
    from archdiag.summary import list_items
    items: List[str] = []
    for w in whats:
        items += list_items(r, g, w)
    if not scope:
        some = _names("", items)[:10]
        return ScopeError("this level needs a %s, for example: %s"
                          % (noun, ", ".join(some[:5]) or "none found"), some)
    sugg = _names(scope, items)
    msg = "no %s named %r" % (noun, scope)
    if sugg:
        msg += "; did you mean: %s" % ", ".join(sugg)
    return ScopeError(msg, sugg)


# ------------------------------------------------------------------ entry point

def build_view(r: Resolved, g, level: str, scope: Optional[str]) -> ViewGraph:
    """The view ``level`` of the resolved graph for ``scope`` (an application, a job name or
    id, a transaction, page route or endpoint, or a repo, by level; none for the landscape).
    Raises ScopeError for an unknown level or a scope that names nothing."""
    if level not in LEVELS:
        hits = difflib.get_close_matches(str(level), list(LEVELS), n=3, cutoff=0.5)
        raise ScopeError("unknown level %r; choose from %s" % (level, ", ".join(LEVELS)),
                         hits or list(LEVELS))
    ctx = _Ctx(r, g)
    if level == "landscape":
        v = _landscape(ctx)
        if scope:
            v.notes.append("The landscape shows the whole estate; scope %r was not used." % scope)
    elif level == "application":
        v = _application(ctx, scope)
    elif level == "flow_job":
        v = _flow_job(ctx, scope)
    elif level == "flow_tx":
        v = _flow_tx(ctx, scope)
    else:
        v = _repomap(ctx, scope)
    _cap(ctx, v)
    return v


# ------------------------------------------------------------------ landscape

_RESOURCE_KINDS = ("dataset", "queue", "table")


def _landscape(ctx: _Ctx) -> ViewGraph:
    from archdiag.groups import suggested_edges
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
    for e in list(ctx.r.edges) + suggested_edges(ctx.g, ctx.r):
        s, d = rep(e.src), rep(e.dst)
        if s is None or d is None or s == d:
            if e.status != CONFIRMED and (s is None or d is None):
                dropped += 1
            continue
        fam = _family(e, nodes)
        if e.op == "copy" and not d.startswith("missing:"):
            s, d = d, s  # shared code is drawn from the copybook's owner to its users
        keyed.append(((s, d, fam), e))

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

    vedges = _combine(keyed, label, lambda k, es: "shared_code" if k[2] == "COPY" else "runtime")

    vnodes: List[VNode] = []
    for a in ctx.g.apps:
        kinds = [n.kind for nid, n in nodes.items() if app.get(nid) == a.name]
        vnodes.append(VNode("app:%s" % a.name, a.name, _tech(set(kinds)) or a.kind, a.kind,
                            ctx.group_of_app(a.name), None,
                            [x for x in [_counts_line(kinds)] if x]))
    used = {x for e in vedges for x in (e.src, e.dst)}
    for nid in sorted(shared & used):
        vnodes.append(ctx.vnode(nid))
    for nid in sorted(used):
        n = nodes.get(nid)
        if n is None or n.kind not in ("external", "missing"):
            continue
        vn = ctx.vnode(nid)
        if n.kind == "missing":
            # a loose end of one application sits in its box; the far side of an exchange,
            # or one reached from several places, stands on its own
            srcs = {e.src for e in vedges if e.dst == nid}
            if len(srcs) == 1 and n.attrs.get("target_kind") not in _CROSS_TARGETS:
                s = next(iter(srcs))
                if s.startswith("app:"):
                    vn.group = ctx.group_of_app(s[4:])
        vnodes.append(vn)
    _mark_missing(vnodes, vedges)
    v = ViewGraph("Landscape", "landscape", None, vnodes, vedges, ctx.vgroups(vnodes))
    if dropped:
        v.notes.append("%d partly known or loose links have no application at one end; the "
                       "links report lists them." % dropped)
    return v


# ------------------------------------------------------------------ application

def _application(ctx: _Ctx, scope: Optional[str]) -> ViewGraph:
    from archdiag.groups import suggested_edges
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
            vn = VNode(nid, nid[4:], "application", "neighbor")
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
    for e in list(ctx.r.edges) + suggested_edges(ctx.g, ctx.r):
        s, d = rep(e.src), rep(e.dst)
        if s == d or not (s in core or d in core):
            continue
        if classify(s) is None or classify(d) is None:
            continue
        keyed.append(((s, d, ctx.op_label(e)), e))
        taken.add(id(e))
    # loose ends and look-alikes ("maybe the same") of the data drawn here
    for e in ctx.r.edges:
        if id(e) in taken or e.op not in _GAP_OPS or not (e.src in kept or e.dst in kept):
            continue
        near = e.src if e.src in kept else e.dst
        far = e.dst if near == e.src else e.src
        new = far not in kept
        if classify(far) is None:
            continue
        if new and kept[far].group == grp and kept[near].kind == "neighbor":
            kept[far].group = None  # the far side of a neighbor sits outside the box
        keyed.append(((e.src, e.dst, ctx.op_label(e)), e))
    vedges = _combine(keyed, _key_label)
    for nid in sorted(core):  # members with no lines still belong to the application
        classify(nid)
    order = sorted(kept.values(), key=lambda n: (n.group is None, n.kind == "neighbor", n.id))
    _mark_missing(order, vedges)
    return ViewGraph("Application %s" % name, "application", name, order, vedges,
                     ctx.vgroups(order))


# ------------------------------------------------------------------ flow_job

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


def _flow_job(ctx: _Ctx, scope: Optional[str]) -> ViewGraph:
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
    # what each step touches: its DD statements, the data of the program it runs, and the
    # programs that one calls (drawn below, their data drawn on the step)
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
            if _is_table(d):
                row_hint[e.dst] = "above"  # the databases sit over the steps
                if e.op in _READ_OPS:
                    keyed.append(((e.dst, st.id, ctx.op_label(e)), e))
                else:
                    keyed.append(((st.id, e.dst, ctx.op_label(e)), e))
            elif e.op in _READ_OPS:
                keyed.append(((e.dst, st.id, ctx.op_label(e)), e))
                row_hint.setdefault(e.dst, "above")
            else:
                keyed.append(((st.id, e.dst, ctx.op_label(e)), e))
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
        step_edges.append(VEdge(prev, st.id, label, CONFIRMED, "runtime", ev, None, list(temps)))
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
            vedges.append(VEdge(st.id, sid, "write", CONFIRMED, "runtime", list(st.evidence[:1])))
    allv = [vnodes[i] for i in order]
    _mark_missing(allv, vedges)
    return ViewGraph("Job %s" % job.name, "flow_job", job.name, allv, step_edges + vedges, [],
                     notes)


# ------------------------------------------------------------------ flow_tx

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


def _flow_tx(ctx: _Ctx, scope: Optional[str]) -> ViewGraph:
    from collections import deque
    starts, title = _tx_starts(ctx, scope) if scope else ([], "")
    if not starts:
        raise _scope_error(ctx.r, ctx.g, scope, ["transactions", "pages", "endpoints"],
                           "transaction, page or endpoint")
    nodes = ctx.nodes
    # breadth first along runtime links, readers found backwards from a queue; a "runs"
    # hop (endpoint to its handler, transaction to its program) costs no depth
    dist: Dict[str, int] = {s: 0 for s in starts}
    done: Set[str] = set()
    dq = deque(starts)
    recorded: List[Edge] = []
    seen: Set[int] = set()

    def record(e: Edge) -> None:
        if id(e) not in seen:
            seen.add(id(e))
            recorded.append(e)

    while dq:
        u = dq.popleft()
        if u in done:
            continue
        done.add(u)
        nexts = [(e, e.dst) for e in ctx.out.get(u, []) if e.op in _TX_FOLLOW]
        nexts += [(e, e.src) for e in ctx.inn.get(u, []) if e.op == "get"]
        for e, w in nexts:
            nd = dist[u] + (0 if e.op == "runs" else 1)
            if w in dist and dist[w] <= nd:
                record(e)
                continue
            if nd > TX_DEPTH:
                continue
            dist[w] = nd
            record(e)
            if e.op == "runs":
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
                    record(e)
    vedges = _combine([((e.src, e.dst, ctx.op_label(e)), e) for e in recorded], _key_label)
    for i, e in enumerate(vedges):
        e.number = i + 1
    order: List[str] = list(starts)
    for e in vedges:
        for x in (e.src, e.dst):
            if x not in order:
                order.append(x)
    vnodes = []
    for nid in order:
        vn = ctx.vnode(nid, ctx.group_of_app(ctx.app.get(nid)))
        vnodes.append(vn)
    _mark_missing(vnodes, vedges)
    v = ViewGraph(title, "flow_tx", scope, vnodes, vedges, ctx.vgroups(vnodes))
    _add_suggested_within(ctx, v)
    return v


def _add_suggested_within(ctx: _Ctx, v: ViewGraph) -> None:
    """Suggested links whose two ends are both drawn already (partial, numbered last)."""
    from archdiag.groups import suggested_edges
    ids = {n.id for n in v.nodes}
    for e in suggested_edges(ctx.g, ctx.r):
        if e.src in ids and e.dst in ids:
            v.edges.append(VEdge(e.src, e.dst, _op_label(e, ctx.nodes), PARTIAL, "runtime", [],
                                 len(v.edges) + 1, [e]))


# ------------------------------------------------------------------ repomap

_NOTABLE = ("job", "transaction", "page", "endpoint", "zosapi", "program", "class", "component",
            "map", "table", "queue", "copybook", "proc", "cicsfile", "mqprocess", "notanalyzed")


def _short_path(path: str) -> str:
    parts = path.split("/")
    return parts[-1] if len(parts) >= 4 else path


def _repomap(ctx: _Ctx, scope: Optional[str]) -> ViewGraph:
    from archdiag.resolve import repo_links
    nodes = ctx.nodes
    repos = [x.name for x in ctx.r.inventory.repos]
    if scope is not None and scope not in repos:
        hit = next((x for x in repos if x.lower() == scope.lower()), None)
        if hit is None:
            raise _scope_error(ctx.r, ctx.g, scope, ["repos"], "repo")
        scope = hit
    evid: Dict[str, List[str]] = {x: [] for x in repos}

    def note_files(e: Edge, only: Optional[Set[str]] = None) -> None:
        for ev in e.evidence:
            if ev.repo in evid and (only is None or ev.repo in only) and ev.path not in evid[ev.repo]:
                evid[ev.repo].append(ev.path)

    vedges: List[VEdge] = []
    for a, b, via, es in repo_links(ctx.r):
        if scope is not None and scope not in (a, b):
            continue
        for e in es:
            note_files(e)
        # drawn from the side whose code makes the call (alphabetical when even)
        from_a = sum(1 for e in es if nodes.get(e.src) is not None and nodes[e.src].repo == a)
        from_b = sum(1 for e in es if nodes.get(e.src) is not None and nodes[e.src].repo == b)
        s, d = (b, a) if from_b > from_a else (a, b)
        vedges.append(VEdge("repo:%s" % s, "repo:%s" % d, via, combine_status(e.status for e in es),
                            _kind_of((), es), _evidence(es), None, list(es)))
    # loose and partly known links out of a repo: stubs to missing and outside nodes
    touch: Dict[str, Set[str]] = {}
    for e in ctx.r.edges:
        for mine, other in ((e.src, e.dst), (e.dst, e.src)):
            o = nodes.get(other)
            if o is not None and o.repo and o.kind not in ("missing", "external"):
                touch.setdefault(mine, set()).add(o.repo)
    keyed: List[Tuple[tuple, Edge]] = []
    unplaced = 0
    for e in ctx.r.edges:
        d, s = nodes.get(e.dst), nodes.get(e.src)
        if d is None or s is None or d.kind not in ("missing", "external"):
            continue
        srcs = {s.repo} if s.repo else touch.get(e.src, set())
        if not srcs and scope is None:
            unplaced += 1
        label = ("%s %s" % (s.kind, _display(s)) if e.op in _GAP_OPS
                 else "%s · %s" % (ctx.op_label(e), _display(s)))
        for repo in sorted(srcs):
            if scope is None or repo == scope:
                keyed.append((("repo:%s" % repo, e.dst, label), e))
                note_files(e, {repo})
    stubs = _combine(keyed, _key_label)
    vedges += stubs
    used = {x for e in vedges for x in (e.src, e.dst)}
    vnodes: List[VNode] = []
    for repo in repos:
        rid = "repo:%s" % repo
        if scope is not None and rid not in used and repo != scope:
            continue
        mine = [n for n in nodes.values() if n.repo == repo]
        files: List[str] = []
        for k in _NOTABLE:
            for n in sorted((n for n in mine if n.kind == k), key=lambda n: n.id):
                for ev in n.evidence:
                    if ev.repo == repo and ev.path not in files:
                        files.append(ev.path)
        hl = sorted(evid.get(repo, []))
        rest = [f for f in files if f not in hl]
        shown = hl + rest[:3]
        short = [_short_path(f) for f in shown]
        lines = [short[i] if short.count(short[i]) == 1 else shown[i] for i in range(len(shown))]
        if len(rest) > 3:
            lines.append("… %d more" % (len(rest) - 3))
        vnodes.append(VNode(rid, repo, _tech({n.kind for n in mine}), "repo", None, None, lines,
                            highlight=len(hl)))
    for nid in sorted(used):
        if not nid.startswith("repo:"):
            vnodes.append(ctx.vnode(nid))
    _mark_missing(vnodes, vedges)
    title = "Repo link map" + (" for %s" % scope if scope else "")
    v = ViewGraph(title, "repomap", scope, vnodes, vedges, [])
    if unplaced:
        v.notes.append("%d loose or partly known links start from something no repo holds; "
                       "the links report lists them." % unplaced)
    return v


# ------------------------------------------------------------------ size limit

def _cap(ctx: _Ctx, v: ViewGraph) -> None:
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
        return f"more:{k[0]}:{k[1]}"

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
        new_nodes.append(VNode(more_id(k), f"… {len(ms)} more {_plural(k[1])}",
                               ", ".join(m.label for m in ms[:3]) + (", …" if len(ms) > 3 else ""),
                               "more", k[0], _least_certain(sts) if sts else None,
                               row=rows.pop() if len(rows) == 1 else None,
                               underlying=[u for m in ms for u in m.underlying]))
    remap = {nid: more_id(k) for nid, k in fold.items()}
    order: List[tuple] = []
    by: Dict[tuple, List[VEdge]] = {}
    for e in v.edges:
        s, d = remap.get(e.src, e.src), remap.get(e.dst, e.dst)
        if s == d and e.status == CONFIRMED and e.src != e.dst:
            continue  # a confirmed line inside one folded box
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
    counts: Dict[str, int] = {}
    for nid, a in ctx.app.items():
        if a and not nid.startswith(("missing:", "utility:")):
            counts[a] = counts.get(a, 0) + 1
    biggest = max(sorted(counts), key=lambda a: counts[a]) if counts else "?"
    return "Too big for one picture: try level application with scope %s" % biggest
