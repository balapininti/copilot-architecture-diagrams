"""Level 4: one card per repo, one line per link between two repos."""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from archdiag.model import PARTIAL, Edge
from archdiag.resolve import repo_link_status, repo_links
from archdiag.views.common import (_GAP_OPS, VEdge, VNode, ViewGraph, _combine, _Ctx, _display,
                                   _evidence, _key_label, _kind_of, _mark_missing, _scope_error,
                                   _tech)

MAX_EVIDENCE_FILES = 8  # highlighted evidence files on one card


_NOTABLE = ("job", "transaction", "page", "endpoint", "zosapi", "program", "class", "component",
            "map", "table", "queue", "copybook", "proc", "cicsfile", "mqprocess", "notanalyzed")


def _short_path(path: str) -> str:
    parts = path.split("/")
    return parts[-1] if len(parts) >= 4 else path


def repomap(ctx: _Ctx, scope: Optional[str]) -> ViewGraph:
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
        vedges.append(VEdge("repo:%s" % s, "repo:%s" % d, via, repo_link_status(ctx.r, a, b, es),
                            _kind_of(es), _evidence(es), None, list(es)))
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
    # partly known links with both ends in one repo draw no line here: count them on its
    # card (B9); a repo-less end belongs to the repos touching it
    inside: Dict[str, int] = {}
    for e in ctx.r.edges:
        if e.status != PARTIAL:
            continue
        ends: Set[str] = set()
        ok = True
        for x in (e.src, e.dst):
            n = nodes.get(x)
            if n is None or n.kind in ("missing", "external"):
                ok = False
                break
            ends |= {n.repo} if n.repo else touch.get(x, set())
        if ok and len(ends) == 1:
            inside[next(iter(ends))] = inside.get(next(iter(ends)), 0) + 1
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
        hl_all = sorted(evid.get(repo, []))
        hl = hl_all[:MAX_EVIDENCE_FILES]
        rest = [f for f in files if f not in hl_all]
        shown = hl + rest[:3]
        short = [_short_path(f) for f in shown]
        lines = [short[i] if short.count(short[i]) == 1 else shown[i] for i in range(len(shown))]
        if len(hl_all) > len(hl):
            lines.insert(len(hl), "… %d more evidence files" % (len(hl_all) - len(hl)))
        if len(rest) > 3:
            lines.append("… %d more" % (len(rest) - 3))
        if inside.get(repo):
            lines.append("%d partly known link%s inside" % (inside[repo],
                                                             "" if inside[repo] == 1 else "s"))
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
