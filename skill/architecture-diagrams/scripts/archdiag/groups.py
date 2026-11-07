"""Application groups: which repo members make up a named application (spec section 6)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Dict, List, Optional

from .model import PARTIAL, Edge, Evidence, Node, Resolved

KINDS = ("application", "datastore", "external")
_DDL_KINDS = ("table",)


@dataclass
class App:
    name: str
    kind: str = "application"  # application | datastore | external
    members: List[str] = field(default_factory=list)


@dataclass
class Groups:
    apps: List[App] = field(default_factory=list)
    suggested_links: List[Dict[str, str]] = field(default_factory=list)  # {"from","to","note"}
    # things in groups.json that could not be used (unknown selector, unknown link end)
    problems: List[str] = field(default_factory=list)


def default_groups(r: Resolved) -> Groups:
    """One app per repo, named after the repo. A repo holding only DDL is a datastore."""
    apps = []
    for repo in r.inventory.repos:
        kinds = {n.kind for n in r.nodes.values() if n.repo == repo.name}
        kind = "datastore" if kinds and kinds <= set(_DDL_KINDS) else "application"
        apps.append(App(repo.name, kind, []))
    return Groups(apps, [], [])


def _match(sel: str, node: Node) -> Optional[bool]:
    """True/False whether ``node`` matches ``sel``; None when the selector is malformed."""
    if ":" not in sel:
        return None
    head, rest = sel.split(":", 1)
    if head == "repo":
        return node.repo == rest
    if head == "path":
        return any(fnmatchcase("%s/%s" % (e.repo, e.path) if e.repo else e.path, rest)
                   or fnmatchcase(e.path, rest) for e in node.evidence)
    if not head or not rest:
        return None
    return node.kind == head and (fnmatchcase(node.name, rest) or fnmatchcase(node.name.upper(), rest.upper()))


def _selectors_used(app: App, r: Resolved, problems: List[str]) -> None:
    for sel in app.members:
        res = [_match(sel, n) for n in r.nodes.values()]
        if res and res[0] is None:
            problems.append("app %r: selector %r is not <kind>:<name>, repo:<name> or path:<repo>/<glob>"
                            % (app.name, sel))
        elif not any(res):
            problems.append("app %r: selector %r matches nothing" % (app.name, sel))


def load_groups(path: Path, r: Resolved) -> Groups:
    """Read groups.json. A missing or unreadable file gives the default groups; selectors and
    link ends that match nothing are listed in ``Groups.problems`` and never raise."""
    path = Path(path)
    if not path.is_file():
        return default_groups(r)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("top level must be an object")
    except (OSError, ValueError) as exc:
        g = default_groups(r)
        g.problems.append("groups.json could not be read (%s); using one app per repo" % exc)
        return g
    g = Groups([], [], [])
    for a in data.get("apps", []) if isinstance(data.get("apps", []), list) else []:
        if not isinstance(a, dict) or not a.get("name"):
            g.problems.append("an app without a name was ignored")
            continue
        kind = str(a.get("kind", "application"))
        if kind not in KINDS:
            g.problems.append("app %r: unknown kind %r, using application" % (a["name"], kind))
            kind = "application"
        mem = a.get("members", [])
        g.apps.append(App(str(a["name"]), kind, [str(m) for m in mem] if isinstance(mem, list) else []))
    if isinstance(data, dict) and isinstance(data.get("groups"), list) and not g.apps:
        for a in data["groups"]:  # also accept a bare list of apps under "groups"
            if isinstance(a, dict) and a.get("name"):
                g.apps.append(App(str(a["name"]), str(a.get("kind", "application")),
                                  [str(m) for m in a.get("members", [])]))
    for app in g.apps:
        _selectors_used(app, r, g.problems)
    # repos whose members fall back to the default app get that app added
    have = {a.name for a in g.apps}
    for repo in r.inventory.repos:
        if repo.name not in have and any(
                n.repo == repo.name and app_of(g, r, n.id) == repo.name for n in r.nodes.values()):
            d = [a for a in default_groups(r).apps if a.name == repo.name][0]
            g.apps.append(d)
            have.add(repo.name)
    names = {a.name for a in g.apps}
    for link in data.get("suggested_links", []) if isinstance(data.get("suggested_links", []), list) else []:
        if not isinstance(link, dict):
            g.problems.append("a suggested link that is not an object was dropped")
            continue
        ends = [str(link.get("from", "")), str(link.get("to", ""))]
        bad = [e for e in ends if e not in r.nodes and e not in names]
        if bad:
            g.problems.append("suggested link %s -> %s dropped: unknown %s"
                              % (ends[0], ends[1], ", ".join(repr(b) for b in bad)))
            continue
        g.suggested_links.append({"from": ends[0], "to": ends[1], "note": str(link.get("note", ""))})
    return g


def app_of(groups: Groups, r: Resolved, node_id: str) -> Optional[str]:
    """Name of the app a node belongs to: the first app (in list order) with a matching
    selector, else the node's repo. Nodes without a repo (datasets, queues...) give None
    unless a selector picks them."""
    node = r.nodes.get(node_id)
    if node is None:
        return None
    for app in groups.apps:
        for sel in app.members:
            if _match(sel, node):
                return app.name
    return node.repo


def suggested_edges(groups: Groups, r: Resolved) -> List[Edge]:
    """Copilot's suggestions as partial edges (view time only; never saved in links.json).
    An app name becomes ``app:<name>``; the view draws it at application level."""
    names = {a.name for a in groups.apps}

    def end(x: str) -> str:
        return x if x in r.nodes else "app:%s" % x if x in names else x

    out = []
    for s in groups.suggested_links:
        out.append(Edge(end(s["from"]), "suggested", end(s["to"]), PARTIAL,
                        "suggested by Copilot: %s" % s["note"], []))
    return out
