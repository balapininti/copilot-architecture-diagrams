from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

CONFIRMED, PARTIAL, LOOSE = "confirmed", "partial", "loose"


@dataclass(frozen=True)
class Evidence:
    repo: str
    path: str
    line: int
    text: str


@dataclass
class Repo:
    name: str
    path: str  # relative to workspace, "." for single-repo


@dataclass
class Node:
    id: str
    kind: str
    name: str
    repo: Optional[str]
    evidence: List[Evidence]
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Ref:
    src: str
    op: str
    target_kind: str
    target_name: Optional[str]
    evidence: Evidence
    reason: Optional[str] = None
    candidates: List[str] = field(default_factory=list)
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    src: str
    op: str
    dst: str
    status: str
    reason: Optional[str]
    evidence: List[Evidence]


@dataclass
class Inventory:
    workspace: str
    repos: List[Repo]
    nodes: Dict[str, Node]
    refs: List[Ref]
    fingerprint: str
    languages_not_analyzed: Dict[str, int]
    # files that could not be read or scanned: {"repo", "path", "reason"} (size, unreadable
    # archive, read error); directory/extension skip lists are intentional and not listed
    skipped: List[Dict[str, str]] = field(default_factory=list)
    # host names (lower case, no port) each repo's config names as its OWN address: Spring
    # server.* / spring.application.* / management.server.address / eureka.instance.hostname
    # and OpenAPI servers[].url; never client base URLs or environment*.ts (Rulings 36, 38)
    config_hosts: Dict[str, List[str]] = field(default_factory=dict)
    # source the scan left out on purpose but that looks like it matters: {"repo" ("" for
    # a workspace folder), "path", "reason"}: default-skipped folders holding source,
    # workspace folders that are not repos, untyped files that look like mainframe code
    not_scanned: List[Dict[str, str]] = field(default_factory=list)
    # the archdiag version and cache schema that wrote this inventory: a cache from another
    # version is rescanned, never served (final review I7)
    archdiag_version: str = ""
    schema_version: int = 0
    # every classified file: {"repo", "path" (repo-relative), "kind"}, sorted; archive
    # members and SYSIN-only members are left out
    files: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class Resolved:
    inventory: Inventory
    nodes: Dict[str, Node]
    edges: List[Edge]
