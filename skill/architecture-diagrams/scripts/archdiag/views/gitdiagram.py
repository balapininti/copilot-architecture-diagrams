"""Level gitdiagram: one repo drawn as the named groups of files of its gitdiagram file
(spec 4.2 and 10).

Every resolved node is mapped to one box by the file that defines it (``file_of``):

* ``grp:<name>`` - the first group whose pattern matches the file; ``grp:?`` ("Not yet
  grouped") when none does. A table, copybook, queue or map whose definition is in a group
  is part of that group (10.2).
* ``act:<kind>`` - CICS transactions, REST endpoints, Angular pages and z/OS Connect APIs of
  this repo, folded into one entry-point box per kind (10.3). ``act:scheduler`` starts each
  job that nothing in the repo submits, with a ``structural`` line (Ruling 2).
* ``out:<repo>``, ``out:external``, ``out:missing`` - anything defined in another repo,
  outside systems and loose ends, one stub each.
* a resource with no defining file (datasets, tables without DDL, undefined queues) is its
  own shared box when two boxes of this repo touch it, else a detail line on its group.

A step's dataset use is drawn from the group of the program it runs when that program opens
the DD (10.1); the line is then no more certain than the step's ``runs`` edge. Lines between
boxes of this repo follow the landscape rule (one line per family and status, so a target
known only partly gets its own dotted line); a line to or from an outside stub takes the
least certain edge under it. Links inside one group are counted on the box and kept in its
``underlying`` for the links report.
"""
from __future__ import annotations

import posixpath
from typing import Dict, List, Optional, Set, Tuple

from archdiag.gitdiagram import (ACTOR_NAMES, FALLBACK_NOTE, GitDiagram, actor_kind, file_of,
                                 group_of, repo_files)
from archdiag.model import CONFIRMED, PARTIAL, Edge, Evidence
from archdiag.views.common import (_RANK, STRUCTURAL, VEdge, VNode, ViewGraph, _Ctx, _evidence,
                                   _family, _least_certain, _missing_label, _plural, _short)

UNGROUPED = "grp:?"
SCHEDULER = "act:scheduler"
MAX_FILES = 4  # file names shown in a group box
MAX_NAMES = 6  # entry names shown in an actor box
_ENTRY_LABEL = {k: label for k, label in ACTOR_NAMES if k != "job"}
_ACTOR_ORDER = [SCHEDULER] + ["act:%s" % k for k, _ in ACTOR_NAMES if k != "job"]
_LOOSE_STUBS = ("out:missing", "out:external")
_RES = "<resource>"  # a node with no defining file, placed after every edge is seen
_UTIL = "<utility>"  # a utility a step runs: the job's own work


def _gid(name: str) -> str:
    return "grp:%s" % name


def _s(n: int) -> str:
    return "" if n == 1 else "s"


def _file_lines(paths: List[str], more: str) -> List[str]:
    """Up to MAX_FILES base names (with the parent folder when two base names collide), then
    ``… N more`` + ``more``."""
    base = [posixpath.basename(p) for p in paths]
    out = []
    for p, b in zip(paths, base):
        if base.count(b) > 1:
            parent = posixpath.basename(posixpath.dirname(p))
            b = "%s/%s" % (parent, b) if parent else b
        out.append(b)
    if len(out) > MAX_FILES:
        return out[:MAX_FILES] + ["… %d more%s" % (len(out) - MAX_FILES, more)]
    return out


def _folder_link(paths: List[str]) -> str:
    """The folder every file is under, else the first file; one file links to itself."""
    if not paths:
        return ""
    if len(paths) == 1:
        return paths[0]
    common = posixpath.commonpath([posixpath.dirname(p) for p in paths])
    return common if common else paths[0]


def _names_line(names: List[str], keep: int) -> str:
    more = " +%d" % (len(names) - keep) if len(names) > keep else ""
    return ", ".join(names[:keep]) + more


def gitdiagram_view(ctx: _Ctx, gd: GitDiagram, repo: str) -> ViewGraph:
    r, nodes = ctx.r, ctx.nodes
    repo_path = next((x.path for x in r.inventory.repos if x.name == repo), repo)
    notes: List[str] = []
    for p in gd.problems:
        if p not in notes:
            notes.append(p)
    if not gd.from_file and FALLBACK_NOTE not in notes:
        notes.append(FALLBACK_NOTE)

    # ---------------------------------------------------------------- files to boxes
    files = [f["path"] for f in repo_files(r, repo)]
    members: Dict[str, List[str]] = {}
    for p in files:
        name = group_of(gd, p)
        members.setdefault(_gid(name) if name is not None else UNGROUPED, []).append(p)

    fcache: Dict[str, Optional[Tuple[str, str]]] = {}

    def file(nid: str) -> Optional[Tuple[str, str]]:
        if nid not in fcache:
            n = nodes.get(nid)
            fcache[nid] = file_of(n, r) if n is not None else None
        return fcache[nid]

    bcache: Dict[str, Optional[str]] = {}

    def base(nid: str) -> Optional[str]:
        if nid in bcache:
            return bcache[nid]
        n = nodes.get(nid)
        b: Optional[str]
        if n is None:
            b = None
        elif n.kind == "missing":
            b = "out:missing"
        elif n.kind == "external":
            b = "out:external"
        elif n.kind == "utility":
            b = _UTIL
        else:
            f = file(nid)
            if f is None:
                b = _RES
            elif f[0] != repo:
                b = "out:%s" % f[0]
            elif n.kind in _ENTRY_LABEL:
                b = "act:%s" % n.kind
            else:
                name = group_of(gd, f[1])
                b = _gid(name) if name is not None else UNGROUPED
        bcache[nid] = b
        return b

    # ---------------------------------------------------------------- dataset attribution
    ddname: Dict[Tuple[str, Evidence], Optional[str]] = {}
    for ref in r.inventory.refs:
        dd = ref.attrs.get("ddname")
        if not dd:
            continue
        key = (ref.src, ref.evidence)
        dd = str(dd).strip().upper()
        ddname[key] = dd if ddname.get(key, dd) == dd else None  # two DDs on one line: unknown
    runs: Dict[str, List[Edge]] = {}
    for e in r.edges:
        if e.op == "runs" and e.src.startswith("step:"):
            runs.setdefault(e.src, []).append(e)

    def program_run(e: Edge) -> Optional[Edge]:
        """The confirmed ``runs`` edge of ``e``'s step to a program of this repo that opens
        ``e``'s DD; None when there is no such single program (utilities, other repos, a
        DD the program does not name)."""
        if e.op == "runs" or not e.src.startswith("step:") or not e.evidence:
            return None
        dd = ddname.get((e.src, e.evidence[0]))
        if not dd:
            return None
        progs = [x for x in runs.get(e.src, [])
                 if nodes.get(x.dst) is not None and nodes[x.dst].kind == "program"]
        if len(progs) != 1 or progs[0].status != CONFIRMED:
            return None
        b = base(progs[0].dst)
        if b is None or not b.startswith("grp:"):
            return None
        opened = {str(k).strip().upper() for k in (nodes[progs[0].dst].attrs.get("files") or {})}
        return progs[0] if dd in opened else None

    def ends(e: Edge) -> Tuple[Optional[str], Optional[str], str, List[Edge]]:
        s, d = base(e.src), base(e.dst)
        if d == _UTIL:
            d = s
        if s == _UTIL:
            s = d
        st, extra = e.status, []  # type: Tuple[str, List[Edge]]
        run = program_run(e)
        if run is not None:
            s = base(run.dst)
            st = _least_certain([e.status, run.status])
            extra = [run]
        return s, d, st, extra

    def mine(b: Optional[str]) -> bool:
        return b is not None and b.startswith(("grp:", "act:"))

    mapped = [(e,) + ends(e) for e in r.edges]

    # ---------------------------------------------------------------- resources with no file
    touch: Dict[str, Set[str]] = {}
    elsewhere: Dict[str, Set[str]] = {}  # resource -> other repos using it
    for e, s, d, _, _ in mapped:
        for b, nid, other in ((s, e.src, d), (d, e.dst, s)):
            if b != _RES:
                continue
            if mine(other):
                touch.setdefault(nid, set()).add(str(other))
            elif other is not None and other.startswith("out:") and other not in _LOOSE_STUBS:
                elsewhere.setdefault(nid, set()).add(other[4:])
    res_box: Dict[str, str] = {}
    for nid, boxes in touch.items():
        if len(boxes) == 1 and next(iter(boxes)).startswith("grp:"):
            res_box[nid] = next(iter(boxes))  # a detail line on its only group
        else:
            res_box[nid] = nid  # its own shared box
    shared = {nid for nid, b in res_box.items() if b == nid}

    def here(b: Optional[str]) -> bool:
        return mine(b) or b in shared

    # ---------------------------------------------------------------- lines
    inside: Dict[str, List[Tuple[Edge, str, List[Edge]]]] = {}
    stray: Dict[str, List[Edge]] = {}  # links inside one non-group box (kept for the report)
    drawn: List[Tuple[str, str, str, Edge, str, List[Edge]]] = []
    res_lines: Dict[str, List[str]] = {}  # group -> resources shown as its detail lines
    for e, s0, d0, st, extra in mapped:
        s = res_box.get(e.src) if s0 == _RES else s0
        d = res_box.get(e.dst) if d0 == _RES else d0
        if s is None or d is None or not (here(s) or here(d)):
            continue
        # another repo's use of a resource with no definition is named on the resource,
        # never drawn as a line into this repo's group
        if (s0 == _RES and d.startswith("out:") and d not in _LOOSE_STUBS) or \
                (d0 == _RES and s.startswith("out:") and s not in _LOOSE_STUBS):
            continue
        for b0, b, nid in ((s0, s, e.src), (d0, d, e.dst)):
            if b0 == _RES and b != nid and nid not in res_lines.setdefault(b, []):
                res_lines[b].append(nid)
        if s == d:
            if s.startswith("grp:"):
                inside.setdefault(s, []).append((e, st, extra))
            else:
                stray.setdefault(s, []).append(e)
            continue
        drawn.append((s, d, _family(e, nodes), e, st, extra))

    best: Dict[tuple, str] = {}
    for s, d, fam, e, st, _ in drawn:
        t = (s, d, fam, e.dst)
        if t not in best or _RANK.get(st, 2) < _RANK.get(best[t], 2):
            best[t] = st
    order: List[tuple] = []
    by: Dict[tuple, List[Tuple[Edge, str, List[Edge]]]] = {}
    for s, d, fam, e, st, extra in drawn:
        outside = s.startswith("out:") or d.startswith("out:")
        key = (s, d, fam, None if outside else best[(s, d, fam, e.dst)])
        if key not in by:
            by[key] = []
            order.append(key)
        by[key].append((e, st, extra))

    def target_name(nid: str) -> str:
        n = nodes[nid]
        if n.kind == "missing":
            return _missing_label(n)[0] if n.name.startswith("?") else n.name
        return _short(n)

    vedges: List[VEdge] = []
    for key in order:
        s, d, fam, st = key
        items = by[key]
        status = st if st is not None else _least_certain(x[1] for x in items)
        under: List[Edge] = []
        for e, _, extra in items:
            for u in [e] + extra:
                if not any(u is x for x in under):
                    under.append(u)
        label = fam
        if d not in shared:
            names: List[str] = []
            for e, _, _ in items:
                nm = target_name(e.dst)
                if nm not in names:
                    names.append(nm)
            if names:
                label = "%s · %s" % (fam, _names_line(names, 2))
        vedges.append(VEdge(s, d, label, status, "shared_code" if fam == "COPY" else "runtime",
                            _evidence(under), None, under))

    # ---------------------------------------------------------------- the Scheduler
    jobs = sorted((n for nid, n in nodes.items() if n.kind == "job" and mine(base(nid))),
                  key=lambda n: (n.name, n.id))
    job_ids = {n.id for n in jobs}
    submitted: Set[str] = set()
    for e in r.edges:
        if e.dst in job_ids and here(base(e.src)) and \
                nodes.get(e.src) is not None and nodes[e.src].attrs.get("job") != e.dst:
            submitted.add(e.dst)
    started = [n for n in jobs if n.id not in submitted]
    for b in dict.fromkeys(str(base(n.id)) for n in started):
        vedges.append(VEdge(SCHEDULER, b, "starts", STRUCTURAL, "sequence", [], None, []))

    # ---------------------------------------------------------------- boxes
    def entry_names(ns: list) -> List[str]:
        out = []
        for n in ns:
            dup = sum(1 for x in ns if x.name == n.name) > 1
            f = file(n.id)
            out.append("%s (%s)" % (n.name, f[1]) if dup and f else n.name)
        return out

    def name_lines(names: List[str]) -> List[str]:
        if len(names) > MAX_NAMES:
            return names[:MAX_NAMES] + ["… %d more" % (len(names) - MAX_NAMES)]
        return list(names)

    actors: Dict[str, VNode] = {}
    if started:
        nm = entry_names(started)
        actors[SCHEDULER] = VNode(SCHEDULER, "Scheduler", "%d job%s" % (len(started), _s(len(started))),
                                  "actor", None, None, name_lines(nm), real_kind="job",
                                  members=nm)
    for kind, label in _ENTRY_LABEL.items():
        aid = "act:%s" % kind
        ns = sorted((n for nid, n in nodes.items() if n.kind == kind and base(nid) == aid),
                    key=lambda n: (n.name, n.id))
        if not ns:
            continue
        nm = entry_names(ns)
        paths = [f[1] for f in (file(n.id) for n in ns) if f]
        link = paths[0] if paths else ""
        actors[aid] = VNode(aid, "%s (%d)" % (label, len(ns)), "entry points", "actor", None,
                            None, name_lines(nm), real_kind=kind, link=link, members=nm,
                            underlying=list(stray.get(aid, [])))

    used = {x for e in vedges for x in (e.src, e.dst)}

    def res_detail(gid: str) -> List[str]:
        out: List[str] = []
        by_kind: Dict[str, List[str]] = {}
        for nid in res_lines.get(gid, []):
            by_kind.setdefault(nodes[nid].kind, []).append(_short(nodes[nid]))
        for kind in sorted(by_kind):
            out.append("%s: %s" % (_plural(kind), _names_line(by_kind[kind], 3)))
        also = ["%s (%s)" % (_short(nodes[nid]), ", ".join(sorted(elsewhere[nid])))
                for nid in res_lines.get(gid, []) if nid in elsewhere]
        if also:
            out.append("also used by other repos: %s" % _names_line(also, 2))
        return out

    def inside_detail(gid: str) -> Tuple[List[str], List[Edge]]:
        items = inside.get(gid, [])
        under: List[Edge] = []
        for e, _, extra in items:
            for u in [e] + extra:
                if not any(u is x for x in under):
                    under.append(u)
        if not items:
            return [], under
        out = ["%d link%s inside" % (len(items), _s(len(items)))]
        partly = sum(1 for _, st, _ in items if st != CONFIRMED)
        if partly:
            out.append("%d partly known link%s inside" % (partly, _s(partly)))
        return out, under

    groups: List[VNode] = []
    for g in gd.groups:
        gid = _gid(g.name)
        paths = members.get(gid, [])
        if not paths and gid not in used and gid not in inside:
            continue
        lines = _file_lines(paths, " files")
        if g.description:
            lines.append(g.description)
        more, under = inside_detail(gid)
        groups.append(VNode(gid, g.name, "[%s]" % g.tech if g.tech else "", "group", None, None,
                            lines + more + res_detail(gid), underlying=under,
                            link=_folder_link(paths), members=list(paths)))
    if members.get(UNGROUPED) or UNGROUPED in used or UNGROUPED in inside:
        paths = members.get(UNGROUPED, [])
        more, under = inside_detail(UNGROUPED)
        groups.append(VNode(UNGROUPED, "Not yet grouped", "", "group", None, None,
                            _file_lines(paths, "") + more + res_detail(UNGROUPED),
                            underlying=under, members=list(paths)))
        if paths:
            notes.append("%d file%s not yet grouped" % (len(paths), _s(len(paths))))
    if gd.from_file and files and not any(g.id != UNGROUPED and g.members for g in groups):
        notes.append("No group in gitdiagram-%s.json matches any file of the repo; every file "
                     "is under 'Not yet grouped'" % repo)

    shared_nodes: List[VNode] = []
    for nid in sorted(shared):
        vn = ctx.vnode(nid)
        if nodes[nid].attrs.get("temp") and "#" in nid:  # one per job: say which
            job = nid.split(":", 1)[1].split("#", 1)[0]
            vn.sublabel = "%s · %s" % (vn.sublabel, job[len(repo) + 1:] if
                                       job.startswith(repo + "/") else job)
        if nid in elsewhere:
            vn.sublabel = "%s · also used by %s" % (vn.sublabel, ", ".join(sorted(elsewhere[nid])))
        vn.underlying = list(stray.get(nid, []))
        shared_nodes.append(vn)

    stubs: List[VNode] = []
    out_ids = sorted((x for x in used if x.startswith("out:")),
                     key=lambda x: (x in _LOOSE_STUBS, x == "out:missing", x))
    for oid in out_ids:
        far: List[str] = []
        sts: List[str] = []
        for ve in vedges:
            if oid not in (ve.src, ve.dst):
                continue
            sts.append(ve.status)
            for u in ve.underlying:
                for x in (u.src, u.dst):
                    if base(x) == oid and x not in far:
                        far.append(x)
        status = _least_certain(sts) if sts else None
        far_nodes = sorted((nodes[x] for x in far), key=lambda n: (n.kind, n.name, n.id))
        names = [target_name(n.id) for n in far_nodes]
        if oid == "out:missing":
            label, sub, kind = "%d loose end%s" % (len(far), _s(len(far))), \
                "not found in these repos", "missing"
            if status == CONFIRMED:
                status = PARTIAL  # a loose end never looks solid
        elif oid == "out:external":
            label, sub, kind = "%d outside system%s" % (len(far), _s(len(far))), \
                "outside these repos", "outside"
        else:
            counts: Dict[str, int] = {}
            for n in far_nodes:
                counts[n.kind] = counts.get(n.kind, 0) + 1
            what = " · ".join("%d %s" % (c, k if c == 1 else _plural(k))
                              for k, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3])
            label, sub, kind = "%s (%s)" % (oid[4:], what), "another repo", "outside"
        stubs.append(VNode(oid, label, sub, kind, None, status, name_lines(names),
                           real_kind="repo" if kind == "outside" and oid not in _LOOSE_STUBS else "",
                           members=names))

    # ---------------------------------------------------------------- suggested links
    boxes = {n.id for n in groups} | set(actors)
    group_names = {g.name for g in gd.groups}

    def box_of(name: str) -> Optional[str]:
        if name in group_names and _gid(name) in boxes:
            return _gid(name)
        k = actor_kind(name)
        if k is not None:
            aid = SCHEDULER if k == "job" else "act:%s" % k
            return aid if aid in boxes else None
        return None

    for link in gd.suggested_links:
        s, d = box_of(link["from"]), box_of(link["to"])
        if s is None or d is None or s == d:
            bad = [x for x, b in ((link["from"], s), (link["to"], d)) if b is None]
            why = ("%s names no group or entry point in this picture"
                   % " and ".join(repr(x) for x in bad)) if bad else "both ends are one box"
            notes.append("Copilot suggests a link %s → %s; not drawn: %s"
                         % (link["from"], link["to"], why))
            continue
        reason = "suggested by Copilot: %s" % link["note"] if link.get("note") else \
            "suggested by Copilot"
        u = Edge(s, "suggested", d, PARTIAL, reason, [])
        vedges.append(VEdge(s, d, link.get("label") or "suggested", PARTIAL, "runtime", [], None,
                            [u]))

    dropped = sum(1 for es in stray.values() for e in es if e.status != CONFIRMED)
    if dropped:
        notes.append("%d partly known or loose link%s inside one entry-point or shared box are "
                     "not drawn; the links report lists them" % (dropped, _s(dropped)))

    vnodes = [actors[a] for a in _ACTOR_ORDER if a in actors] + groups + shared_nodes + stubs
    v = ViewGraph("Gitdiagram %s" % repo, "gitdiagram", repo, vnodes, vedges, [], notes)
    v.overview = gd.overview
    v.repo_path = repo_path
    return v
