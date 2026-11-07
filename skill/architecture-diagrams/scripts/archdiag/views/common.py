"""Types and helpers shared by every view (see ``archdiag.views`` for the levels)."""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from archdiag.model import CONFIRMED, LOOSE, PARTIAL, Edge, Evidence, Node, Resolved

LEVELS = ("landscape", "application", "flow_job", "flow_tx", "repomap", "gitdiagram")
# a Scheduler "starts" line (gitdiagram): the job exists, who schedules it is not in the
# repos. It is not a certainty: combining and least-certain ignore it (Ruling 2)
STRUCTURAL = "structural"
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
    # the resolver's own kind when ``kind`` is the icon kind it is drawn with (copybook is
    # drawn as a program, zosapi as an endpoint, a neighbor keeps what it really is); "" means
    # ``kind`` is the real kind
    real_kind: str = ""
    # gitdiagram: a repo-relative file or folder the box opens; renderers make it an href
    link: str = ""
    # gitdiagram: everything the box stands for in full (a group's file paths, an entry
    # actor's names), for the links report and the completeness check
    members: List[str] = field(default_factory=list)
    # gitdiagram: what the box stands for but does not show (links inside, resources,
    # other repos' uses, temporary datasets), for the links report
    info: List[str] = field(default_factory=list)
    # gitdiagram: the index in detail_lines of the description (drawn in at most 2 lines),
    # and how many trailing detail lines are drawn muted ("+3 links inside")
    desc_line: int = -1
    muted: int = 0
    # gitdiagram: "shared" for a resource box between groups (name and short kind only),
    # "ungrouped" for the "Not yet grouped" box
    role: str = ""
    # a "… N more" box made by the size cap: the boxes it stands for, kept whole so the
    # links report can still list each one (a folded group with all its files)
    folded: List["VNode"] = field(default_factory=list)


@dataclass
class VEdge:
    src: str
    dst: str
    label: str = ""
    status: str = "confirmed"
    # "runtime", "shared_code" or "sequence" (job structure, or a gitdiagram Scheduler
    # "starts" line with status "structural"; no Edge)
    kind: str = "runtime"
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
    overview: str = ""  # gitdiagram: the paragraph drawn above the picture
    repo_path: str = ""  # gitdiagram: the repo folder, relative to the workspace (Repo.path)
    problems: List[str] = field(default_factory=list)  # gitdiagram: problems in the file


class ScopeError(ValueError):
    """A level or scope that names nothing; ``suggestions`` holds close matches."""

    def __init__(self, message: str, suggestions: Optional[List[str]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.suggestions = list(suggestions or [])


# ------------------------------------------------------------------ shared helpers

_RANK = {CONFIRMED: 0, PARTIAL: 1, LOOSE: 2}


def combine_status(statuses: Iterable[str]) -> str:
    """Confirmed if any is confirmed, else partial if any is partial, else loose. Structural
    statuses are ignored; only structural ones give structural."""
    s = set(statuses)
    if s == {STRUCTURAL}:
        return STRUCTURAL
    s.discard(STRUCTURAL)
    if CONFIRMED in s:
        return CONFIRMED
    if PARTIAL in s:
        return PARTIAL
    return LOOSE


def _least_certain(statuses: Iterable[str]) -> str:
    """The least certain status; structural ones are ignored (only structural ones give
    structural)."""
    sts = list(statuses)
    rest = [x for x in sts if x != STRUCTURAL]
    if sts and not rest:
        return STRUCTURAL
    return max(rest, key=lambda x: _RANK.get(x, 2), default=CONFIRMED)


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
    if kind == "missing":
        return "loose ends"
    return kind + ("es" if kind.endswith(("s", "x", "ch", "sh")) else "s")


def _counts_line(kinds: Sequence[str]) -> str:
    parts = []
    for k in _COUNT_KINDS:
        c = sum(1 for x in kinds if x == k)
        if c:
            parts.append("%d %s" % (c, k if c == 1 else _plural(k)))
    return " · ".join(parts[:3])


def _kind_of(es: List[Edge]) -> str:
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
            return VNode(nid, nid.split(":", 1)[-1], "application", "application", group, None,
                         real_kind="application")
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
        return VNode(nid, _display(n), sub, kind, group, None, row=row,
                     real_kind=n.kind if kind == n.kind or n.kind != "dataset" else kind)


def _evidence(es: Iterable[Edge]) -> List[Evidence]:
    seen: Set[Evidence] = set()
    out = []
    for e in es:
        for ev in e.evidence:
            if ev not in seen:
                seen.add(ev)
                out.append(ev)
    return out


def _combine(keyed: List[Tuple[tuple, Edge]], make_label, kind_of=None) -> List[VEdge]:
    """One VEdge per key ``(src, dst, ...)`` in first-seen order, its status combined.
    ``kind_of(key, edges)`` picks the line kind (default: shared code when all are copies)."""
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
                         kind_of(key, es) if kind_of else _kind_of(es), _evidence(es), None,
                         list(es)))
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
        nm = it.split("\t", 1)[0]  # a listing line is NAME<TAB>description (repo/path)
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


def _suggestions(ctx: "_Ctx") -> List[Tuple[Dict[str, str], Edge]]:
    """Each suggested link of groups.json with its partial Edge (view time only)."""
    from archdiag.groups import suggested_edges
    return list(zip(ctx.g.suggested_links, suggested_edges(ctx.g, ctx.r)))


def _suggest_note(raw: Dict[str, str], where: str = "shown on the landscape") -> str:
    note = " (%s)" % raw["note"] if raw.get("note") else ""
    return "Copilot suggests a link %s → %s%s; %s" % (raw["from"], raw["to"], note, where)


def _add_suggested_within(ctx: _Ctx, v: ViewGraph) -> None:
    """Flow views: a suggested link whose two ends are both drawn is added (partial,
    numbered last in flow_tx); one that touches the view but cannot be drawn (one end
    outside it, or an application end) is named in the notes."""
    ids = {n.id for n in v.nodes}
    apps = {"app:%s" % ctx.app[i] for i in ids if ctx.app.get(i)}
    for raw, e in _suggestions(ctx):
        if e.src in ids and e.dst in ids:
            v.edges.append(VEdge(e.src, e.dst, _op_label(e, ctx.nodes), PARTIAL, "runtime", [],
                                 len(v.edges) + 1 if v.level == "flow_tx" else None, [e]))
        elif any(x in ids or x in apps for x in (e.src, e.dst)):
            v.notes.append(_suggest_note(raw))
