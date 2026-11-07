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


@dataclass
class Resolved:
    inventory: Inventory
    nodes: Dict[str, Node]
    edges: List[Edge]
