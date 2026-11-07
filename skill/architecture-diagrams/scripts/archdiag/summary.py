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


# ends that belong to no repo's code: their repo never makes a shared resource shared (B8)
_NO_REPO_KINDS = ("missing", "utility", "external", "notanalyzed")


def _touch_repos(r: Resolved) -> Dict[str, set]:
    """Repos of the edge ends touching each repo-less node (datasets, queues...); utility,
    external, missing and not-analyzed ends are not counted."""
    t: Dict[str, set] = {}
    for e in r.edges:
        for mine, other in ((e.src, e.dst), (e.dst, e.src)):
            n, o = r.nodes.get(mine), r.nodes.get(other)
            if n is not None and n.repo is None and o is not None and o.repo \
                    and o.kind not in _NO_REPO_KINDS:
                t.setdefault(mine, set()).add(o.repo)
    return t


def _cross(r: Resolved, e: Edge, touch: Dict[str, set]) -> bool:
    """True when both ends have a known, different repo. A repo-less shared resource uses
    the repos of everything that touches it (2 or more repos = shared across repos)."""
    def repos(nid: str) -> Optional[set]:
        n = r.nodes.get(nid)
        if n is None or n.kind in _NO_REPO_KINDS:
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
    tail += ["", "## Not scanned"]
    ns = inv.not_scanned
    tail.append("- " + ("%d place(s) that look like source were not scanned; links to them "
                        "will be missing" % len(ns) if ns else "none"))
    for s in ns[:5]:
        where = "%s/%s" % (s["repo"], s.get("path", "")) if s.get("repo") else s.get("path", "")
        tail.append("  - %s: %s" % (where, s.get("reason", "")))
    if len(ns) > 5:
        tail.append("  - ... %d more (see any links report)" % (len(ns) - 5))

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
    """One line per item of a kind: jobs, transactions, pages, endpoints, applications, repos,
    programs. Each line is ``NAME<TAB>description (repo/path)`` (B11): the program a
    transaction runs, a page's component, an endpoint's handler class, the programs a job's
    steps run; a program has only its path."""
    if what == "applications":
        cnt = _counts(g, r)
        return ["%s\t(%s, %d members)" % (a.name, a.kind, cnt.get(a.name, 0)) for a in g.apps]
    if what == "repos":
        return ["%s\t(%s)" % (repo.name, repo.path) for repo in r.inventory.repos]
    kinds = {"jobs": "job", "transactions": "transaction", "pages": "page",
             "endpoints": "endpoint", "programs": "program"}
    if what not in kinds:
        raise ValueError("unknown listing %r; choose from %s" % (what, ", ".join(sorted(list(kinds) + ["applications", "repos"]))))
    nodes = sorted((n for n in r.nodes.values() if n.kind == kinds[what]), key=lambda n: (n.name, n.id))
    by_src: Dict[str, List[Edge]] = {}
    for e in r.edges:
        by_src.setdefault(e.src, []).append(e)
    steps_of: Dict[str, list] = {}  # job id -> its steps, indexed once
    if what == "jobs":
        for s in r.nodes.values():
            if s.kind == "step" and s.attrs.get("job"):
                steps_of.setdefault(str(s.attrs["job"]), []).append(s)
    lines = []
    for n in nodes:
        desc = _one_line(_describe(r, n, by_src, steps_of))
        lines.append("%s\t%s(%s)" % (_one_line(n.name), desc + " " if desc else "", _path(n)))
    return lines


def _one_line(text: str) -> str:
    return " ".join(str(text).replace("\t", " ").split())


def _end_name(r: Resolved, nid: str) -> str:
    """A target's name, saying when it is not in these repos or not worked out."""
    n = r.nodes.get(nid)
    if n is None:
        return nid.split(":", 1)[-1]
    if n.kind == "missing":
        return "not worked out" if n.name.startswith("?") else \
            "%s, not in these repos" % n.name
    return n.name


_MAX_DESC = 3  # names shown in one description before "+N more"


def _names(items: List[str]) -> str:
    more = " +%d more" % (len(items) - _MAX_DESC) if len(items) > _MAX_DESC else ""
    return ", ".join(items[:_MAX_DESC]) + more


def _describe(r: Resolved, n, by_src: Dict[str, List[Edge]],
              steps_of: Dict[str, list]) -> str:
    out = by_src.get(n.id, [])
    if n.kind == "transaction":
        progs = [_end_name(r, e.dst) for e in out if e.op == "runs"]
        return "runs program %s" % _names(progs) if progs else ""
    if n.kind == "page":
        uses = [e for e in out if e.op == "uses"]
        pages = [_end_name(r, e.dst) for e in uses if e.dst.startswith(("page:", "missing:page:"))]
        if pages:
            return "redirects to %s" % _names(pages)
        comps = [_end_name(r, e.dst) for e in uses]
        return "component %s" % _names(comps) if comps else ""
    if n.kind == "endpoint":
        hs = sorted(set([str(n.attrs.get("handler") or "")] +
                        [str(h) for h in (n.attrs.get("handlers") or [])]) - {""})
        names = [r.nodes[h].name if h in r.nodes else h.split("/")[-1] for h in hs]
        return ("handler class%s %s" % ("es" if len(names) > 1 else "", _names(names))
                if names else "")
    if n.kind == "job":
        steps = sorted(steps_of.get(n.id, []),
                       key=lambda s: (s.attrs.get("order") or 0, s.id))
        runs = []
        for s in steps:
            if s.attrs.get("pgm"):
                runs.append(str(s.attrs["pgm"]))
            elif s.attrs.get("proc"):
                runs.append("proc %s" % s.attrs["proc"])
        return "steps run %s" % _names(runs) if runs else ""
    return ""


# ---- gitdiagram context: what Copilot reads to propose groups for one repo (spec 4, 7) ----

_README_LINES = 200
_ENTRY_KINDS = ("job", "transaction", "endpoint", "page", "zosapi")
_NAME_SKIP = ("step", "dataset", "missing", "external", "utility")


def _repo_readme(r: Resolved, repo: str) -> List[str]:
    from pathlib import Path
    from .textio import read_source
    base = next((x.path for x in r.inventory.repos if x.name == repo), repo)
    folder = Path(r.inventory.workspace) / base
    try:
        names = sorted(p.name for p in folder.iterdir()
                       if p.is_file() and p.name.lower().startswith("readme"))
        if not names:
            return []
        text = read_source(folder / names[0])
    except OSError:
        return []
    lines = text.splitlines()
    out = lines[:_README_LINES]
    if len(lines) > _README_LINES:
        out.append("(README cut after %d lines)" % _README_LINES)
    return out


def _clip(lines: List[str], room: int, what: str) -> List[str]:
    room = max(room, 1)
    if len(lines) <= room:
        return lines
    return lines[:room - 1] + ["... %d more %s not listed" % (len(lines) - room + 1, what)]


def gitdiagram_context(r: Resolved, repo: str, max_lines: int = 1500) -> str:
    from .gitdiagram import file_of, repo_files
    files = repo_files(r, repo)
    names: Dict[str, List[str]] = {}
    ends: Dict[str, Optional[Tuple[str, str]]] = {}
    for n in sorted(r.nodes.values(), key=lambda n: (n.kind, n.name, n.id)):
        ends[n.id] = file_of(n, r)
        f = ends[n.id]
        if f and f[0] == repo and n.kind not in _NAME_SKIP:
            lst = names.setdefault(f[1], [])
            tag = "%s:%s" % (n.kind, n.name)
            if tag not in lst:
                lst.append(tag)

    rows = ["%s\t%s\t%s" % (f["path"], f["kind"], " ".join(names.get(f["path"], [])[:3]))
            for f in files]
    links, leaving = set(), Counter()
    for e in r.edges:
        a, b = ends.get(e.src), ends.get(e.dst)
        if not a or a[0] != repo:
            continue
        if b and b[0] == repo:
            if a[1] != b[1]:
                links.add("%s → %s  %s  %s" % (a[1], b[1], e.op, e.status))
        else:
            dn = r.nodes.get(e.dst)
            leaving[b[0] if b else "%s (%s)" % (dn.kind if dn else "unknown", "no file")] += 1
    link_rows = sorted(links)
    leave_rows = ["%d links to %s" % (c, k) for k, c in sorted(leaving.items())]
    entries = sorted({"%s\t%s\t%s" % (n.kind, n.name, ends[n.id][1])
                      for n in r.nodes.values()
                      if n.kind in _ENTRY_KINDS and ends[n.id] and ends[n.id][0] == repo})

    readme = _repo_readme(r, repo)
    readme = readme if readme else ["(no README at the repo root)"]
    other = len(readme) + len(link_rows) + len(leave_rows) + len(entries) + 14
    summarised = len(rows) + other > max_lines
    if summarised:
        folders: Dict[str, List[str]] = {}
        for f in files:
            folders.setdefault(f["path"].split("/", 1)[0] if "/" in f["path"] else "(repo root)",
                               []).append(f["kind"])
        table = []
        for fo, ks in sorted(folders.items()):
            c = Counter(ks)
            kinds = ", ".join("%s %d" % (k, v) for k, v in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))
            table.append("%s/\t%d files\t%s" % (fo, len(ks), kinds) if fo != "(repo root)"
                         else "(repo root)\t%d files\t%s" % (len(ks), kinds))
        table = _clip(table, max_lines // 3, "folders")
        table.append("Too many files to list: summarised per folder.")
    else:
        table = rows
    budget = max_lines - (len(table) + len(readme) + 14)
    each = max(budget // 2, 3)
    link_rows = _clip(link_rows, each, "links")
    entries = _clip(entries, max(budget - len(link_rows) - len(leave_rows), 3), "entry points")
    out = ["# Repo %s" % repo, "", "## Files"] + table + ["", "## README"] + readme + \
          ["", "## Code links between files"] + (link_rows or ["(none)"]) + \
          leave_rows + ["", "## Entry points"] + (entries or ["(none)"])
    return "\n".join(out) + "\n"
