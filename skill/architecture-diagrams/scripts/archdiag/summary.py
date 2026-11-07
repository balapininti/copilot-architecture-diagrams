"""The short Markdown summary Copilot reads, and plain listings of things in the estate."""
from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Tuple

from .config import Config
from .groups import Groups, app_of
from .resolve.names import norm_dataset
from .model import CONFIRMED, LOOSE, PARTIAL, Edge, Resolved

MAX_LINES = 120


def count_unanalyzed(inv) -> int:
    """Files a scanner crashed on (as opposed to benign skips such as size or permissions)."""
    return sum(1 for s in inv.skipped if "could not be analyzed" in s.get("reason", ""))


def _env_pairs(r: Resolved, cfg: Config, kind: str) -> List[Tuple[str, str, int, str]]:
    """(q1, q2, shared tail count, example) for first-qualifier pairs of ``kind`` names that
    share at least two distinct tails and are not already configured."""
    by_tail: Dict[str, Dict[str, str]] = {}
    for n in r.nodes.values():
        name = n.name
        if kind == "dataset":
            name = norm_dataset(name, [])[0]  # drop GDG generations: one dataset, one tail
        if n.kind != kind or "&" in name or name.startswith("?") or "." not in name:
            continue
        q, tail = name.split(".", 1)
        by_tail.setdefault(tail, {})[q] = name
    known = {q.strip().upper() for q in cfg.environment_qualifiers}
    pairs: Dict[Tuple[str, str], List[str]] = {}
    for tail, variants in by_tail.items():
        qs = sorted(variants, reverse=True)
        for i, q1 in enumerate(qs):
            for q2 in qs[i + 1:]:
                if q1.upper() in known or q2.upper() in known:
                    continue
                pairs.setdefault((q1, q2), []).append(tail)
    out = []
    for (q1, q2), tails in pairs.items():
        if len(tails) >= 2:
            t = sorted(tails)[0]
            out.append((q1, q2, len(tails), "%s.%s ~ %s.%s" % (q1, t, q2, t)))
    out.sort(key=lambda x: (-x[2], x[0], x[1]))
    return out[:10]


def _touch_repos(r: Resolved) -> Dict[str, set]:
    """Repos of the edge ends touching each repo-less node (datasets, queues...)."""
    t: Dict[str, set] = {}
    for e in r.edges:
        for mine, other in ((e.src, e.dst), (e.dst, e.src)):
            n, o = r.nodes.get(mine), r.nodes.get(other)
            if n is not None and n.repo is None and o is not None and o.repo:
                t.setdefault(mine, set()).add(o.repo)
    return t


def _cross(r: Resolved, e: Edge, touch: Dict[str, set]) -> bool:
    """True when both ends have a known, different repo. A repo-less shared resource uses
    the repos of everything that touches it (2 or more repos = shared across repos)."""
    def repos(nid: str) -> Optional[set]:
        n = r.nodes.get(nid)
        if n is None or n.kind in ("missing", "utility", "external", "notanalyzed"):
            return None
        if n.repo:
            return {n.repo}
        return touch.get(nid) or None
    a, b = repos(e.src), repos(e.dst)
    if a is None or b is None:
        return False
    if n_shared(r, e.src) or n_shared(r, e.dst):
        return len(a | b) > 1
    return a != b


def n_shared(r: Resolved, nid: str) -> bool:
    n = r.nodes.get(nid)
    return n is not None and n.repo is None


def _where(e: Edge) -> str:
    if not e.evidence:
        return ""
    ev = e.evidence[0]
    return "%s/%s" % (ev.repo or "", ev.path or "")


def _edge_line(e: Edge) -> str:
    return "- %s -%s-> %s: %s" % (e.src, e.op, e.dst, e.reason or "no reason recorded")


def _counts(g: Groups, r: Resolved) -> Counter:
    return Counter(app_of(g, r, nid) for nid in r.nodes if not nid.startswith(("missing:", "utility:")))


def _fit(sections: List[Tuple[List[str], int]], avail: int) -> List[List[str]]:
    """Cut each section's lines (cap given per section) so the total, including one
    ``... and K more`` line per cut section, fits in ``avail`` lines."""
    shown = [min(len(items), cap) for items, cap in sections]

    def cost() -> int:
        return sum(n + (1 if n < len(items) else 0) for n, (items, _) in zip(shown, sections))
    while cost() > avail and any(n > 0 for n in shown):
        i = max(range(len(shown)), key=lambda k: shown[k])
        shown[i] -= 1
    out = []
    for n, (items, _) in zip(shown, sections):
        lines = items[:n]
        if n < len(items):
            lines.append("- ... and %d more" % (len(items) - n))
        out.append(lines)
    return out


def build_summary(r: Resolved, g: Groups, cfg: Config) -> str:
    inv = r.inventory
    # fixed tail first: it always survives
    st = Counter(e.status for e in r.edges)
    touch = _touch_repos(r)
    tail: List[str] = ["## Links", "- confirmed: %d, partial: %d, loose: %d"
                       % (st[CONFIRMED], st[PARTIAL], st[LOOSE])]
    for label, status in (("Loose", LOOSE), ("Partial", PARTIAL)):
        items = [e for e in r.edges if e.status == status]
        items.sort(key=lambda e: (not _cross(r, e, touch), _where(e), e.src, e.dst))
        tail += ["", "## Top %s links (%d of %d)" % (label.lower(), min(10, len(items)), len(items))]
        tail += [_edge_line(e) for e in items[:10]] or ["- none"]
    tail += ["", "## Not analyzed"]
    na = inv.languages_not_analyzed
    tail.append("- " + (", ".join("%s: %d files" % (k, v) for k, v in sorted(na.items())) if na else "none"))
    tail.append("- Skipped files: %d" % len(inv.skipped))
    bad = count_unanalyzed(inv)
    if bad:
        tail.append("- WARNING: %d file(s) could not be analyzed; links involving them may be "
                    "missing" % bad)
    for s in inv.skipped[:5]:
        tail.append("  - %s/%s (%s)" % (s.get("repo", ""), s.get("path", ""), s.get("reason", "")))

    # variable head sections fill what is left
    rows = []
    for repo in inv.repos:
        kinds = Counter(n.kind for n in r.nodes.values() if n.repo == repo.name)
        rows.append((sum(kinds.values()), "- %s: %s" % (repo.name, ", ".join(
            "%d %s" % (c, k) for k, c in sorted(kinds.items())) or "nothing found")))
    rows.sort(key=lambda x: (-x[0], x[1]))
    counts = _counts(g, r)
    arows = sorted([(counts.get(a.name, 0), "- %s [%s]: %d members" % (a.name, a.kind, counts.get(a.name, 0)))
                    for a in g.apps], key=lambda x: (-x[0], x[1]))
    problems = ["- %s" % p for p in g.problems]
    env: List[str] = []
    for title, kind in (("Datasets (first qualifier)", "dataset"), ("Tables (schema)", "table")):
        pairs = _env_pairs(r, cfg, kind)
        if pairs:
            env.append("%s:" % title)
            env += ["- %s ~ %s (%d shared names, e.g. %s)" % p for p in pairs]
    warn = ["Accepting a pair makes names that differ only by it count as the same thing "
            "(solid links). Only accept real environment names."] if env else []
    env_head = [] if env else ["- none"]
    # title(2) + one header and one blank per head section (4 x 2, problems only when present)
    overhead = 2 + 2 * (3 + (1 if problems else 0)) + len(warn) + len(env_head) + 1
    avail = MAX_LINES - len(tail) - overhead
    rl, al, pl, el = _fit([([t for _, t in rows], 25), ([t for _, t in arows], 25),
                           (problems, 10), (env, 22)], avail)
    out: List[str] = ["# Architecture scan summary", "", "## Repos (%d)" % len(inv.repos)] + rl
    out += ["", "## Applications (%d)" % len(g.apps)] + al
    if problems:
        out += ["", "## Problems in groups.json"] + pl
    out += ["", "## Environment qualifier candidates"] + env_head + el + warn + [""] + tail
    return "\n".join(out) + "\n"


def _path(n) -> str:
    if not n.evidence:
        return n.name
    e = n.evidence[0]
    return "%s/%s" % (e.repo, e.path) if e.repo else e.path


def list_items(r: Resolved, g: Groups, what: str) -> List[str]:
    """One line per item of a kind: jobs, transactions, pages, endpoints, applications, repos, programs."""
    if what == "applications":
        cnt = _counts(g, r)
        return ["%s (%s, %d members)" % (a.name, a.kind, cnt.get(a.name, 0)) for a in g.apps]
    if what == "repos":
        return [repo.name for repo in r.inventory.repos]
    kinds = {"jobs": "job", "transactions": "transaction", "pages": "page",
             "endpoints": "endpoint", "programs": "program"}
    if what not in kinds:
        raise ValueError("unknown listing %r; choose from %s" % (what, ", ".join(sorted(list(kinds) + ["applications", "repos"]))))
    nodes = sorted((n for n in r.nodes.values() if n.kind == kinds[what]), key=lambda n: (n.name, n.id))
    return ["%s (%s)" % (n.name, _path(n)) for n in nodes]
