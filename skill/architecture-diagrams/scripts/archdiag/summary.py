"""The short Markdown summary Copilot reads, and plain listings of things in the estate."""
from __future__ import annotations

from collections import Counter
from typing import Dict, List, Tuple

from .config import Config
from .groups import Groups, app_of
from .model import CONFIRMED, LOOSE, PARTIAL, Edge, Resolved

MAX_LINES = 120


def _env_pairs(r: Resolved, cfg: Config, kind: str) -> List[Tuple[str, str, int, str]]:
    """(q1, q2, shared tail count, example) for first-qualifier pairs of ``kind`` names that
    share at least two distinct tails and are not already configured."""
    by_tail: Dict[str, Dict[str, str]] = {}
    for n in r.nodes.values():
        if n.kind != kind or "&" in n.name or n.name.startswith("?") or "." not in n.name:
            continue
        q, tail = n.name.split(".", 1)
        by_tail.setdefault(tail, {})[q] = n.name
    known = {q.upper() for q in cfg.environment_qualifiers}
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


def _cross(r: Resolved, e: Edge) -> bool:
    a, b = r.nodes.get(e.src), r.nodes.get(e.dst)
    return (a.repo if a else None) != (b.repo if b else None)


def _edge_line(e: Edge) -> str:
    return "- %s -%s-> %s: %s" % (e.src, e.op, e.dst, e.reason or "no reason recorded")


def _counts(g: Groups, r: Resolved) -> Counter:
    return Counter(app_of(g, r, nid) for nid in r.nodes if not nid.startswith(("missing:", "utility:")))


def _capped(items: List[Tuple[int, str]], cap: int = 25) -> List[str]:
    items = sorted(items, key=lambda x: (-x[0], x[1]))
    lines = [t for _, t in items[:cap]]
    if len(items) > cap:
        lines.append("- ... and %d more" % (len(items) - cap))
    return lines


def build_summary(r: Resolved, g: Groups, cfg: Config) -> str:
    inv = r.inventory
    out: List[str] = ["# Architecture scan summary", ""]
    out.append("## Repos (%d)" % len(inv.repos))
    rows = []
    for repo in inv.repos:
        kinds = Counter(n.kind for n in r.nodes.values() if n.repo == repo.name)
        rows.append((sum(kinds.values()), "- %s: %s" % (repo.name, ", ".join(
            "%d %s" % (c, k) for k, c in sorted(kinds.items())) or "nothing found")))
    out += _capped(rows)
    out += ["", "## Applications (%d)" % len(g.apps)]
    counts = _counts(g, r)
    out += _capped([(counts.get(a.name, 0), "- %s [%s]: %d members" % (a.name, a.kind, counts.get(a.name, 0)))
                    for a in g.apps])
    if g.problems:
        out += ["", "## Problems in groups.json"] + ["- %s" % p for p in g.problems[:10]]
    out += ["", "## Environment qualifier candidates"]
    any_pair = False
    for title, kind in (("Datasets (first qualifier)", "dataset"), ("Tables (schema)", "table")):
        pairs = _env_pairs(r, cfg, kind)
        if pairs:
            any_pair = True
            out.append("%s:" % title)
            out += ["- %s ~ %s (%d shared names, e.g. %s)" % p for p in pairs]
    if any_pair:
        out.append("Accepting a pair makes names that differ only by it count as the same thing "
                   "(solid links). Only accept real environment names.")
    else:
        out.append("- none")
    st = Counter(e.status for e in r.edges)
    out += ["", "## Links", "- confirmed: %d, partial: %d, loose: %d"
            % (st[CONFIRMED], st[PARTIAL], st[LOOSE])]
    for label, status in (("Loose", LOOSE), ("Partial", PARTIAL)):
        items = [e for e in r.edges if e.status == status]
        items.sort(key=lambda e: (not _cross(r, e), e.evidence[0].repo + "/" + e.evidence[0].path
                                  if e.evidence else "", e.src, e.dst))
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
