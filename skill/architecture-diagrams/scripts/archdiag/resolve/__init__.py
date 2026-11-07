"""Turn scanner Refs into Edges with a status: confirmed, partial or loose (spec §7)."""
from __future__ import annotations

from typing import Dict, List

from ..config import Config
from ..model import Edge, Evidence, Inventory, Node, Resolved
from .data import repo_link_status, repo_links

__all__ = ["resolve", "repo_links", "repo_link_status"]


def resolve(inv: Inventory, config: Config) -> Resolved:
    """Resolve every Ref of ``inv``. Scanner nodes are kept as they are; the resolver adds
    the nodes it needs (``missing:``, ``utility:`` and so on) to a copy of the node map."""
    from . import data, programs
    nodes: Dict[str, Node] = dict(inv.nodes)
    edges: List[Edge] = []
    programs.resolve_programs(inv, nodes, edges)
    data.resolve_data(inv, config, nodes, edges)
    _add_copy_evidence(inv, edges)
    return Resolved(inv, nodes, edges)


def _add_copy_evidence(inv: Inventory, edges: List[Edge]) -> None:
    """A link made by a statement inside a copybook also shows the program's COPY line, so
    both ends of it are in the evidence."""
    via: Dict[tuple, Evidence] = {}
    for ref in inv.refs:
        d = ref.attrs.get("copy_evidence")
        if isinstance(d, dict):
            via[(ref.src, ref.evidence)] = Evidence(d.get("repo", ""), d.get("path", ""),
                                                    int(d.get("line", 0)), d.get("text", ""))
    if not via:
        return
    for e in edges:
        if e.evidence:
            ev = via.get((e.src, e.evidence[0]))
            if ev is not None and ev not in e.evidence:
                e.evidence.insert(1, ev)
