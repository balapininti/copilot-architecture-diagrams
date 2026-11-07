"""Resolve program, copybook, transaction, map and utility Refs into Edges (spec §7.2-7.4).

The rule: a link is solid only when the name is fully worked out from code in the repos
and exactly one thing matches it. So:

- exactly one definition location gives CONFIRMED;
- a definition in several places gives PARTIAL (``ambiguous: defined in N places: ...``);
- no definition gives LOOSE to ``missing:<kind>:<NAME>``;
- a name not worked out (``target_name=None``) gives PARTIAL to
  ``missing:<kind>:?<src>:<line>``, or to the one defined candidate when there is exactly one;
- any Ref with a reason is at most PARTIAL (Ruling 18): never confirmed, and a name that is
  not fully worked out never draws a red loose end either.

IBM-supplied copybooks and run-time routines (``attrs["system"]``) give no edge (Ruling 9).
Every Edge's evidence is the Ref's evidence first, then the definition's evidence.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..model import CONFIRMED, LOOSE, PARTIAL, Edge, Evidence, Inventory, Node, Ref
from ..scan.cobol import IBM_COPYBOOKS

PROGRAM_OPS = frozenset(["runs", "call", "link", "xctl", "ctg_call"])
TRANSACTION_OPS = frozenset(["start", "return_transid"])

# target_kind -> (ops handled, definition node kinds searched in order)
_RULES: Dict[str, Tuple[frozenset, Tuple[str, ...]]] = {
    "program": (PROGRAM_OPS, ("program", "notanalyzed")),
    "copybook": (frozenset(["copy"]), ("copybook",)),
    "transaction": (TRANSACTION_OPS, ("transaction",)),
    "map": (frozenset(["send_map"]), ("map",)),
}


def _where(ev: Evidence) -> str:
    return "%s/%s" % (ev.repo, ev.path) if ev.repo else ev.path


def _ambiguous(defs: List[Evidence]) -> str:
    return "ambiguous: defined in %d places: %s" % (len(defs), ", ".join(_where(e) for e in defs))


def _join(*reasons: Optional[str]) -> Optional[str]:
    parts = [r for r in reasons if r]
    return "; ".join(parts) if parts else None


def _src_label(src: str) -> str:
    """The source node id without its kind prefix (unique, unlike a bare step name)."""
    return src.split(":", 1)[1] if ":" in src else src


def _missing(nodes: Dict[str, Node], kind: str, name: str, reason: Optional[str] = None,
             candidates: Optional[List[str]] = None) -> str:
    nid = "missing:%s:%s" % (kind, name)
    if nid not in nodes:
        attrs = {"target_kind": kind}
        if reason is not None or candidates is not None:
            attrs["reason"] = reason
            attrs["candidates"] = list(candidates or [])
        nodes[nid] = Node(nid, "missing", name, None, [], attrs)
    return nid


def _definitions(nodes: Dict[str, Node], kinds: Tuple[str, ...],
                 name: str) -> Tuple[Optional[str], List[Evidence]]:
    """(node id to link to, every definition location) for ``name``.

    The first kind that has a node gives the id; the locations of all kinds count, so a
    program that is both COBOL and not-analyzed source is ambiguous.
    """
    dst: Optional[str] = None
    defs: List[Evidence] = []
    for kind in kinds:
        node = nodes.get("%s:%s" % (kind, name))
        if node is None:
            continue
        if dst is None:
            dst = node.id
        defs.extend(node.evidence)
    return dst, defs


def _status_for(defs: List[Evidence], reason: Optional[str]) -> Tuple[str, Optional[str]]:
    if len(defs) > 1:
        return PARTIAL, _join(reason, _ambiguous(defs))
    return (PARTIAL if reason else CONFIRMED), reason


def _resolve_named(ref: Ref, kinds: Tuple[str, ...], nodes: Dict[str, Node],
                   edges: List[Edge]) -> None:
    name = (ref.target_name or "").strip().upper()
    dst, defs = _definitions(nodes, kinds, name)
    if dst is None:
        # nothing defines it: a red loose end, unless the name itself is not fully worked
        # out (unresolved symbol, guessed default), which is only partly known
        missing = _missing(nodes, ref.target_kind, name)
        edges.append(Edge(ref.src, ref.op, missing, PARTIAL if ref.reason else LOOSE,
                          ref.reason, [ref.evidence]))
        return
    status, reason = _status_for(defs, ref.reason)
    edges.append(Edge(ref.src, ref.op, dst, status, reason, [ref.evidence] + defs))


def _resolve_unknown(ref: Ref, kinds: Tuple[str, ...], nodes: Dict[str, Node],
                     edges: List[Edge]) -> None:
    reason = ref.reason or "name not worked out"
    if len(ref.candidates) == 1:
        dst, defs = _definitions(nodes, kinds, ref.candidates[0].strip().upper())
        if dst is not None:
            amb = _ambiguous(defs) if len(defs) > 1 else None
            edges.append(Edge(ref.src, ref.op, dst, PARTIAL, _join(reason, amb),
                              [ref.evidence] + defs))
            return
    missing = _missing(nodes, ref.target_kind,
                       "?%s:%d" % (_src_label(ref.src), ref.evidence.line),
                       reason, ref.candidates)
    edges.append(Edge(ref.src, ref.op, missing, PARTIAL, reason, [ref.evidence]))


def _resolve_utility(ref: Ref, nodes: Dict[str, Node], edges: List[Edge]) -> None:
    if not ref.target_name:
        _resolve_unknown(ref, ("utility",), nodes, edges)
        return
    name = ref.target_name.strip().upper()
    nid = "utility:" + name
    if nid not in nodes:
        nodes[nid] = Node(nid, "utility", name, None, [], {})
    edges.append(Edge(ref.src, ref.op, nid, PARTIAL if ref.reason else CONFIRMED,
                      ref.reason, [ref.evidence]))


def resolve_programs(inv: Inventory, nodes: Dict[str, Node], edges: List[Edge]) -> None:
    """Append edges (and missing / utility nodes) for program, copybook, CICS refs."""
    for ref in inv.refs:
        if ref.attrs.get("system") is True:
            continue  # IBM copybooks and run-time routines (Ruling 9)
        if ref.target_kind == "utility" and ref.op == "runs":
            _resolve_utility(ref, nodes, edges)
            continue
        rule = _RULES.get(ref.target_kind)
        if rule is None or ref.op not in rule[0]:
            continue
        if ref.target_kind == "copybook" and ref.target_name \
                and ref.target_name.strip().upper() in IBM_COPYBOOKS:
            continue
        if ref.target_name is None or not ref.target_name.strip():
            _resolve_unknown(ref, rule[1], nodes, edges)
        else:
            _resolve_named(ref, rule[1], nodes, edges)
