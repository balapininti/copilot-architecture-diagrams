"""What one diagram shows: nodes, edges and groups, ready to lay out and draw.

This file holds the types only; build_view is added later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from archdiag.model import Evidence

LEVELS = ("landscape", "application", "flow_job", "flow_tx", "repomap")


@dataclass
class VNode:
    id: str
    label: str
    sublabel: str = ""
    kind: str = "program"
    group: Optional[str] = None
    status: Optional[str] = None
    detail_lines: List[str] = field(default_factory=list)
    row: Optional[str] = None  # "above" | "lane" | "below" for job flows


@dataclass
class VEdge:
    src: str
    dst: str
    label: str = ""
    status: str = "confirmed"
    kind: str = "runtime"  # or "shared_code"
    evidence: List[Evidence] = field(default_factory=list)
    number: Optional[int] = None


@dataclass
class VGroup:
    id: str
    label: str
    color: str


@dataclass
class ViewGraph:
    title: str
    level: str  # one of LEVELS
    scope: Optional[str]
    nodes: List[VNode]
    edges: List[VEdge]
    groups: List[VGroup]
    notes: List[str] = field(default_factory=list)
