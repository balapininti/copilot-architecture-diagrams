"""The links report that sits beside every diagram: every link with its status and evidence,
loose ends, partly known links, names that suggest an unscanned repo, and what was not analyzed.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..model import CONFIRMED, LOOSE, PARTIAL, Edge, Evidence, Resolved
from ..views import ViewGraph

WHY_MISSING = "may live in a repo that wasn't scanned"


def _cell(text: object) -> str:
    s = " ".join(str(text).split())
    return s.replace("|", "\\|")


def _ev(ev: Optional[Evidence]) -> str:
    if ev is None:
        return "-"
    return "%s:%d" % ("%s/%s" % (ev.repo, ev.path) if ev.repo else ev.path, ev.line)


def _evtext(ev: Evidence) -> str:
    return "`%s`" % _ev(ev) + (" `%s`" % " ".join(ev.text.split()).replace("`", "'") if ev.text else "")


def _edges(view: ViewGraph) -> List[Edge]:
    seen = set()
    out: List[Edge] = []
    lists = [n.underlying for n in view.nodes] + [e.underlying for e in view.edges]
    for lst in lists:
        for e in lst:
            if id(e) not in seen:
                seen.add(id(e))
                out.append(e)
    return out


def _name(r: Resolved, nid: str, labels: Dict[str, str]) -> str:
    n = r.nodes.get(nid)
    if n is not None:
        return "%s %s" % (n.kind, n.name)
    return labels.get(nid, nid)


def _reason_and_candidates(e: Edge, r: Resolved) -> Tuple[str, List[str]]:
    reason = e.reason or ""
    cands: List[str] = []
    n = r.nodes.get(e.dst)
    if n is not None and n.kind == "missing":
        if not reason and n.attrs.get("reason"):
            reason = str(n.attrs["reason"])
        cands = [str(c) for c in (n.attrs.get("candidates") or [])]
    return reason, cands


def _group(name: str) -> Optional[str]:
    name = name.strip()
    if not name or name.startswith("?"):
        return None
    if ":" in name:
        return name.split(".")[0]
    if "." in name:
        return name.split(".")[0] + ".*"
    return name[:3] + "*" if len(name) > 3 else name


def _evlines(e: Edge) -> str:
    return "; ".join(_evtext(x) for x in e.evidence) or "no evidence recorded"


def links_report(view: ViewGraph, r: Resolved) -> str:
    edges = _edges(view)
    labels = {n.id: n.label for n in view.nodes}
    nconf = sum(1 for e in edges if e.status == CONFIRMED)
    npart = sum(1 for e in edges if e.status == PARTIAL)
    nloose = sum(1 for e in edges if e.status == LOOSE)
    o: List[str] = ["# Links: %s" % view.title, "",
                    "%d confirmed · %d partly known · %d loose ends" % (nconf, npart, nloose), "",
                    "## Links on this diagram", ""]
    if edges:
        o += ["| From | Link | To | Status | Evidence (from) | Evidence (to) |",
              "|---|---|---|---|---|---|"]
        for e in edges:
            ev = e.evidence
            o.append("| %s | %s | %s | %s | %s | %s |" % (
                _cell(_name(r, e.src, labels)), _cell(e.op), _cell(_name(r, e.dst, labels)),
                e.status, _cell(_ev(ev[0] if ev else None)),
                _cell(" ; ".join(_ev(x) for x in ev[1:]) if len(ev) > 1 else "-")))
    else:
        o.append("No links are drawn on this diagram.")
    seq = sum(1 for e in view.edges if e.kind == "sequence")
    o.append("")

    o += ["## Loose ends", ""]
    loose = [e for e in edges if e.status == LOOSE]
    for e in loose:
        reason, cands = _reason_and_candidates(e, r)
        o.append("- %s %s %s: %s. Evidence: %s%s" % (
            _name(r, e.src, labels), e.op, _name(r, e.dst, labels), reason or "no definition found",
            _evlines(e), ". Candidates: %s" % ", ".join(cands) if cands else ""))
    if not loose:
        o.append("None.")
    o += ["", "## Partly known", ""]
    part = [e for e in edges if e.status == PARTIAL]
    for e in part:
        reason, cands = _reason_and_candidates(e, r)
        o.append("- %s %s %s: %s. Evidence: %s%s" % (
            _name(r, e.src, labels), e.op, _name(r, e.dst, labels), reason or "not fully worked out",
            _evlines(e), ". Candidates: %s" % ", ".join(cands) if cands else ""))
    if not part:
        o.append("None.")

    groups: Dict[str, int] = {}
    for e in edges:
        if e.dst.startswith(("missing:", "external:")):
            n = r.nodes.get(e.dst)
            g = _group(n.name if n is not None else e.dst.split(":", 2)[-1])
            if g:
                groups[g] = groups.get(g, 0) + 1
    o += ["", "## Possibly missing repos", ""]
    hits = sorted((g, c) for g, c in groups.items() if c >= 2)
    for g, c in hits:
        o.append("- `%s` (%d links): %s" % (g, c, WHY_MISSING))
    if not hits:
        o.append("None.")

    o += ["", "## Not analyzed", ""]
    na = r.inventory.languages_not_analyzed
    for lang in sorted(na):
        o.append("- %d %s files: program names registered, contents not analyzed" % (na[lang], lang))
    if not na:
        o.append("None.")

    o += ["", "## Skipped files", ""]
    for s in r.inventory.skipped:
        repo = s.get("repo")
        o.append("- `%s`: %s" % ("%s/%s" % (repo, s.get("path")) if repo else s.get("path"),
                                 s.get("reason", "")))
    if not r.inventory.skipped:
        o.append("None.")

    o += ["", "## Notes", ""]
    for n in view.notes:
        o.append("- %s" % " ".join(str(n).split()))
    if seq:
        o.append("- %d job-structure lines (step order, SYSOUT) are drawn but are not links; "
                 "they have no row above" % seq)
    if not view.notes and not seq:
        o.append("None.")
    return "\n".join(o) + "\n"
