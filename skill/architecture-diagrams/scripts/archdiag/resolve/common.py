"""Helpers shared by the program and data resolvers."""
from __future__ import annotations

from typing import Dict, List, Optional

from ..model import Evidence, Node


def where(ev: Evidence) -> str:
    """``repo/path`` of a piece of evidence."""
    return "%s/%s" % (ev.repo, ev.path) if ev.repo else ev.path


def join(*reasons: Optional[str]) -> Optional[str]:
    """The non-empty reasons joined with ``"; "``, or None."""
    parts = [r for r in reasons if r]
    return "; ".join(parts) if parts else None


def src_label(src: str) -> str:
    """The source node id without its kind prefix (unique, unlike a bare step name)."""
    return src.split(":", 1)[1] if ":" in src else src


def unknown_name(src: str, ev: Evidence) -> str:
    """The per-site name ``?<src label>:<line>`` for a name that is not worked out."""
    return "?%s:%d" % (src_label(src), ev.line)


def missing(nodes: Dict[str, Node], kind: str, name: str, reason: Optional[str] = None,
            candidates: Optional[List[str]] = None) -> str:
    """Id of the ``missing:<kind>:<name>`` node, creating it on first use. Every ref that
    reaches the node adds its reason and candidates (B7: not only the first one's)."""
    nid = "missing:%s:%s" % (kind, name)
    if nid not in nodes:
        attrs = {"target_kind": kind}
        if reason is not None or candidates is not None:
            attrs["reason"] = reason
            attrs["candidates"] = list(candidates or [])
        nodes[nid] = Node(nid, "missing", name, None, [], attrs)
        return nid
    attrs = nodes[nid].attrs
    if reason:
        have = attrs.get("reason")
        parts = have.split("; ") if have else []
        new = [p for p in reason.split("; ") if p and p not in parts]
        if new:
            attrs["reason"] = "; ".join(parts + new)
    if candidates:
        cands = attrs.setdefault("candidates", [])
        cands.extend(c for c in candidates if c not in cands)
    if (reason or candidates) and "candidates" not in attrs:
        attrs["candidates"] = []
    return nid


def ambiguous(defs: List[Evidence]) -> str:
    """``ambiguous: defined in N places: <repo/path>, ...`` for several definitions."""
    return "ambiguous: defined in %d places: %s" % (len(defs), ", ".join(where(e) for e in defs))
