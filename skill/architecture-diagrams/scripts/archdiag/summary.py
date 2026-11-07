"""The short Markdown summary Copilot reads, and plain listings of things in the estate."""
from __future__ import annotations

from collections import Counter, OrderedDict
from typing import Dict, List

from .config import Config
from .groups import Groups, app_of
from .model import CONFIRMED, LOOSE, PARTIAL, Edge, Resolved

MAX_LINES = 120


def _env_candidates(r: Resolved, cfg: Config) -> "OrderedDict[str, List[str]]":
    """First qualifiers that are the only difference between two or more names."""
    by_rest: Dict[str, Dict[str, str]] = {}
    for n in r.nodes.values():
        if n.kind not in ("dataset", "table") or n.name.startswith("&") or "&" in n.name \
                or n.name.startswith("?") or "." not in n.name:
            continue
        q, rest = n.name.split(".", 1)
        by_rest.setdefault("%s|%s" % (n.kind, rest), {})[q] = n.name
    known = {q.upper() for q in cfg.environment_qualifiers}
    cands: Dict[str, List[str]] = {}
    for variants in by_rest.values():
        if len(variants) < 2:
            continue
        for q, name in sorted(variants.items()):
            if q.upper() not in known:
                cands.setdefault(q, []).append(name)
    return OrderedDict((q, sorted(set(v))[:2]) for q, v in sorted(cands.items()))


def _edge_line(e: Edge) -> str:
    return "- %s -%s-> %s: %s" % (e.src, e.op, e.dst, e.reason or "no reason recorded")


def build_summary(r: Resolved, g: Groups, cfg: Config) -> str:
    inv = r.inventory
    out: List[str] = ["# Architecture scan summary", ""]
    out.append("## Repos (%d)" % len(inv.repos))
    for repo in inv.repos:
        kinds = Counter(n.kind for n in r.nodes.values() if n.repo == repo.name)
        out.append("- %s: %s" % (repo.name, ", ".join("%d %s" % (c, k) for k, c in sorted(kinds.items()))
                                 or "nothing found"))
    out += ["", "## Applications (%d)" % len(g.apps)]
    counts = Counter(app_of(g, r, nid) for nid in r.nodes if not nid.startswith(("missing:", "utility:")))
    for a in g.apps:
        out.append("- %s [%s]: %d members" % (a.name, a.kind, counts.get(a.name, 0)))
    if g.problems:
        out += ["", "## Problems in groups.json"] + ["- %s" % p for p in g.problems[:10]]
    cands = _env_candidates(r, cfg)
    out += ["", "## Environment qualifier candidates"]
    if cands:
        out.append("Not in config; add to environment_qualifiers if they mean an environment:")
        for q, ex in list(cands.items())[:10]:
            out.append("- %s (e.g. %s)" % (q, ", ".join(ex)))
    else:
        out.append("- none")
    st = Counter(e.status for e in r.edges)
    out += ["", "## Links", "- confirmed: %d, partial: %d, loose: %d"
            % (st[CONFIRMED], st[PARTIAL], st[LOOSE])]
    for label, status in (("Loose", LOOSE), ("Partial", PARTIAL)):
        items = [e for e in r.edges if e.status == status]
        out += ["", "## Top %s links (%d of %d)" % (label.lower(), min(10, len(items)), len(items))]
        out += [_edge_line(e) for e in items[:10]] or ["- none"]
    out += ["", "## Not analyzed"]
    na = inv.languages_not_analyzed
    out.append("- " + (", ".join("%s: %d files" % (k, v) for k, v in sorted(na.items())) if na else "none"))
    out.append("- Skipped files: %d" % len(inv.skipped))
    for s in inv.skipped[:5]:
        out.append("  - %s/%s (%s)" % (s.get("repo", ""), s.get("path", ""), s.get("reason", "")))
    if len(out) > MAX_LINES:
        out = out[:MAX_LINES - 1] + ["(summary truncated)"]
    return "\n".join(out) + "\n"


def _path(n) -> str:
    if not n.evidence:
        return n.name
    e = n.evidence[0]
    return "%s/%s" % (e.repo, e.path) if e.repo else e.path


def list_items(r: Resolved, g: Groups, what: str) -> List[str]:
    """One line per item of a kind: jobs, transactions, pages, endpoints, applications, repos, programs."""
    if what == "applications":
        cnt = Counter(app_of(g, r, nid) for nid in r.nodes)
        return ["%s (%s, %d members)" % (a.name, a.kind, cnt.get(a.name, 0)) for a in g.apps]
    if what == "repos":
        return [repo.name for repo in r.inventory.repos]
    kinds = {"jobs": "job", "transactions": "transaction", "pages": "page",
             "endpoints": "endpoint", "programs": "program"}
    if what not in kinds:
        raise ValueError("unknown listing %r; choose from %s" % (what, ", ".join(sorted(list(kinds) + ["applications", "repos"]))))
    nodes = sorted((n for n in r.nodes.values() if n.kind == kinds[what]), key=lambda n: (n.name, n.id))
    return ["%s (%s)" % (n.name, _path(n)) for n in nodes]
