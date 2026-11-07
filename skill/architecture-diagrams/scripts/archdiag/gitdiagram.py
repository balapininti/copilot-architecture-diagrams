"""The gitdiagram grouping file: which files of one repo make up each named box (spec 4.1).

``architecture-diagrams/gitdiagram-<repo>.json`` is written by Copilot or the user, never by
the CLI. Reading it is tolerant: every problem is listed in ``GitDiagram.problems`` and
nothing raises. Without the file, files are grouped by top-level folder."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .model import Node, Resolved

FALLBACK_NOTE = "Grouped by folder. Ask Copilot to name groups for this repo."
_GLOB = "*?["
_NO_FILE_NODES = ("dataset:", "missing:", "external:", "utility:")


@dataclass
class GitGroup:
    name: str
    tech: str = ""
    files: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class GitDiagram:
    repo: str
    overview: str
    groups: List[GitGroup]
    suggested_links: List[Dict[str, str]]  # {"from", "to", "label", "note"}
    problems: List[str]
    from_file: bool  # False = folder fallback


def gitdiagram_path(out_dir: Path, repo: str) -> Path:
    return Path(out_dir) / ("gitdiagram-%s.json" % repo)


def repo_files(r: Resolved, repo: str) -> List[Dict[str, str]]:
    return [f for f in r.inventory.files if f.get("repo") == repo]


def _norm(p: str) -> str:
    p = p.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lower()


def _matches(pattern: str, path: str) -> bool:
    """``pattern`` and ``path`` are already normalised. No glob: the file itself or a folder."""
    if any(c in pattern for c in _GLOB):
        return fnmatchcase(path, pattern)
    pat = pattern.rstrip("/")
    return path == pat or path.startswith(pat + "/")


def group_of(gd: GitDiagram, path: str) -> Optional[str]:
    """Name of the first group with a pattern matching ``path``, else None."""
    p = _norm(path)
    for g in gd.groups:
        for pat in g.files:
            if _matches(_norm(pat), p):
                return g.name
    return None


def default_gitdiagram(r: Resolved, repo: str) -> GitDiagram:
    """One group per top-level folder; files at the repo root go to a group named after the repo."""
    folders: Dict[str, List[Dict[str, str]]] = {}
    root: List[Dict[str, str]] = []
    for f in repo_files(r, repo):
        if "/" in f["path"]:
            folders.setdefault(f["path"].split("/", 1)[0], []).append(f)
        else:
            root.append(f)

    def tech(fs: List[Dict[str, str]]) -> str:
        c = Counter(f["kind"] for f in fs)
        return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if c else ""

    groups = [GitGroup(name, tech(fs), [name]) for name, fs in sorted(folders.items())]
    if root:
        name = repo
        while name in folders:
            name += " (root)"
        groups.append(GitGroup(name, tech(root), [f["path"] for f in root]))
    return GitDiagram(repo, "", groups, [], [FALLBACK_NOTE], False)


def _text(v: object, what: str, problems: List[str]) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    problems.append("%s must be text, ignored" % what)
    return ""


def load_gitdiagram(out_dir: Path, r: Resolved, repo: str) -> GitDiagram:
    path = gitdiagram_path(out_dir, repo)
    if not path.is_file():
        return default_gitdiagram(r, repo)
    name = path.name

    def fallback(why: str) -> GitDiagram:
        gd = default_gitdiagram(r, repo)
        gd.problems.insert(0, "%s %s; grouping by folder" % (name, why))
        return gd

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return fallback("could not be read (%s)" % exc)
    if not isinstance(data, dict):
        return fallback("must be an object with \"groups\"")
    problems: List[str] = []
    overview = _text(data.get("overview"), "overview", problems)
    raw_groups = data.get("groups")
    if raw_groups is None:
        raw_groups = []
    if not isinstance(raw_groups, list):
        problems.append("\"groups\" must be a list, ignored")
        raw_groups = []
    groups: List[GitGroup] = []
    seen = set()
    for raw in raw_groups:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not raw["name"].strip():
            problems.append("a group without a text name was ignored")
            continue
        gname = raw["name"]
        if gname in seen:
            problems.append("duplicate group name %r ignored" % gname)
            continue
        seen.add(gname)
        pats = raw.get("files")
        if pats is None:
            pats = []
        if not isinstance(pats, list):
            problems.append("group %r: files must be a list, ignored" % gname)
            pats = []
        files = []
        for p in pats:
            if isinstance(p, str) and p.strip():
                files.append(p)
            else:
                problems.append("group %r: file pattern %r is not text, ignored" % (gname, p))
        groups.append(GitGroup(gname, _text(raw.get("tech"), "group %r tech" % gname, problems), files,
                               _text(raw.get("description"), "group %r description" % gname, problems)))
    gd = GitDiagram(repo, overview, groups, [], problems, True)
    paths = [_norm(f["path"]) for f in repo_files(r, repo)]
    for g in groups:
        if not g.files:
            problems.append("group %r has no files" % g.name)
        for pat in g.files:
            if not any(_matches(_norm(pat), p) for p in paths):
                problems.append("group %r: pattern %r matches no file in %s" % (g.name, pat, repo))
    links = data.get("suggested_links")
    if links is None:
        links = []
    if not isinstance(links, list):
        problems.append("\"suggested_links\" must be a list, ignored")
        links = []
    names = {g.name for g in groups}
    for link in links:
        if not isinstance(link, dict):
            problems.append("a suggested link that is not an object was dropped")
            continue
        ends = [str(link.get("from", "")), str(link.get("to", ""))]
        bad = [e for e in ends if e not in names and e not in r.nodes]
        if bad:
            problems.append("suggested link %s -> %s dropped: unknown %s"
                            % (ends[0], ends[1], ", ".join(repr(b) for b in bad)))
            continue
        gd.suggested_links.append({"from": ends[0], "to": ends[1],
                                   "label": _text(link.get("label"), "link label", problems),
                                   "note": _text(link.get("note"), "link note", problems)})
    return gd


def file_of(node: Node, r: Resolved) -> Optional[Tuple[str, str]]:
    """(repo, path) of the file that defines ``node``; None for nodes the resolver made up
    (dataset, missing, external, utility) and nodes without evidence."""
    if node.id.startswith(_NO_FILE_NODES):
        return None
    src = node
    if node.id.startswith("step:"):
        job = r.nodes.get(str(node.attrs.get("job", "")))
        if job is not None and job.evidence:
            src = job
    if not src.evidence:
        return None
    ev = src.evidence[0]
    repo = ev.repo or src.repo
    return (repo, ev.path) if repo else None
