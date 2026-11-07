"""Turn scanner Refs into Edges with a status: confirmed, partial or loose (spec §7)."""
from __future__ import annotations

from typing import Dict, List

from ..config import Config
from ..model import Edge, Inventory, Node, Resolved


def resolve(inv: Inventory, config: Config) -> Resolved:
    """Resolve every Ref of ``inv``. Scanner nodes are kept as they are; the resolver adds
    the nodes it needs (``missing:``, ``utility:`` and so on) to a copy of the node map."""
    from . import data, programs
    nodes: Dict[str, Node] = dict(inv.nodes)
    edges: List[Edge] = []
    programs.resolve_programs(inv, nodes, edges)
    data.resolve_data(inv, config, nodes, edges)
    return Resolved(inv, nodes, edges)
