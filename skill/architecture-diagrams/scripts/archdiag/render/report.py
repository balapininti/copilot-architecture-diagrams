"""The links report that sits beside every diagram: every link with its status and evidence,
loose ends, partly known links, names used but defined in no scanned repo, and what was not
analyzed or skipped.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Set, Tuple

from ..model import CONFIRMED, LOOSE, PARTIAL, Edge, Evidence, Node, Resolved
from ..layout import layout_notes
from ..views import ViewGraph
from ..views.common import STRUCTURAL
from .common import href

GAP_KINDS = ("reader", "writer", "queue-consumer")
MISSING_INTRO = ("These names are used but defined in none of the scanned repos — the repo "
                 "that defines them may not have been cloned.")
PREFIX_LEN = 4


def _cell(text: object) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _ev(ev: Evidence) -> str:
    return "%s:%d" % ("%s/%s" % (ev.repo, ev.path) if ev.repo else ev.path, ev.line)


def _evkey(ev: Evidence) -> Tuple[Optional[str], str, int]:
    return (ev.repo, ev.path, ev.line)


def _edges(view: ViewGraph) -> List[Edge]:
    seen: Set[int] = set()
    out: List[Edge] = []
    for lst in [n.underlying for n in view.nodes] + [e.underlying for e in view.edges]:
        for e in lst:
            if id(e) not in seen:
                seen.add(id(e))
                out.append(e)
    return out


def _display(r: Resolved, nid: str) -> str:
    n = r.nodes.get(nid)
    if n is None:
        return nid.split(":", 1)[-1]
    if n.kind == "missing" and n.name.startswith("?"):
        written = n.attrs.get("written_name")
        if not written:
            m = re.search(r"\bto (\S+?),", str(n.attrs.get("reason") or ""))
            written = m.group(1) if m else None
        if written:
            return "dynamic target (%s)" % written
        if ":" in n.name:
            return "dynamic target (name set at run time)"
        return "%s %s (not resolved to one thing)" % (n.attrs.get("target_kind", "target"), n.name[1:])
    if n.kind == "missing":
        return "%s %s" % (n.attrs.get("target_kind", "target"), n.name)
    return "%s %s" % (n.kind, n.name)


def _reason(e: Edge, r: Resolved) -> str:
    n = r.nodes.get(e.dst)
    if e.reason:
        return e.reason
    if n is not None and n.kind == "missing" and n.attrs.get("reason"):
        return str(n.attrs["reason"])
    return ""


def _candidates(e: Edge, r: Resolved) -> List[str]:
    n = r.nodes.get(e.dst)
    if n is not None and n.kind == "missing":
        return [str(c) for c in (n.attrs.get("candidates") or [])]
    return []


def _link_text(e: Edge, r: Resolved) -> str:
    if e.op == "loose":
        return _reason(e, r) or "gap"
    return e.op


def _copy_key(e: Edge, r: Resolved) -> tuple:
    s = r.nodes.get(e.src)
    ev = e.evidence[0] if e.evidence else None
    return (s.kind if s else "", s.name if s else e.src, e.op, e.dst, e.status, e.reason,
            ev.repo if ev else None, os.path.basename(ev.path) if ev else "",
            ev.line if ev else 0, ev.text if ev else "")


def _links(edges: List[Edge], r: Resolved) -> List[List[Edge]]:
    """Edges grouped so that copies of one file in another folder are one link."""
    groups: Dict[tuple, List[Edge]] = {}
    for e in edges:
        groups.setdefault(_copy_key(e, r), []).append(e)
    return list(groups.values())


def _evidence_cell(group: List[Edge], r: Resolved) -> str:
    e = group[0]
    dn = r.nodes.get(e.dst)
    defined = {_evkey(x) for x in (dn.evidence if dn is not None else [])}
    shown: Set[Tuple[Optional[str], str, int]] = set()
    parts: List[str] = []
    for i, ev in enumerate(e.evidence):
        shown.add(_evkey(ev))
        tag = " (here)" if i == 0 else (" (defined)" if _evkey(ev) in defined else " (also)")
        parts.append(_ev(ev) + tag)
    if dn is not None:
        for ev in dn.evidence:
            if _evkey(ev) not in shown:
                shown.add(_evkey(ev))
                parts.append(_ev(ev) + " (defined)")
    extra: List[str] = []
    for c in group[1:]:
        for ev in c.evidence:
            if _evkey(ev) not in shown:
                shown.add(_evkey(ev))
                extra.append(_ev(ev))
    text = "; ".join(parts) if parts else "no evidence recorded"
    if extra:
        text += "; also in: " + ", ".join(extra)
    return text


def _evtext(e: Edge) -> str:
    return "; ".join("`%s`%s" % (_ev(x), " `%s`" % " ".join(x.text.split()).replace("`", "'")
                     if x.text else "") for x in e.evidence) or "no evidence recorded"


def _bullet(group: List[Edge], r: Resolved, default: str) -> str:
    e = group[0]
    cands = _candidates(e, r)
    more = [c for g in group[1:] for c in g.evidence[:1]]
    return "- %s -> %s (%s): %s. Evidence: %s%s%s" % (
        _display(r, e.src), _display(r, e.dst), e.op if e.op != "loose" else "gap",
        _reason(e, r) or default, _evtext(e),
        "; also in: " + ", ".join(_ev(x) for x in more) if more else "",
        ". Candidates: %s" % ", ".join(cands) if cands else "")


def _host_group(name: str) -> str:
    if ":" in name:
        return name
    parts = name.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else name


def _missing_section(edges: List[Edge], r: Resolved) -> List[str]:
    # {(kind, name): set of distinct places}
    # B10: a copy of a file in another folder is the same place (the links table's copy key)
    names: Dict[Tuple[str, str], Set[tuple]] = {}
    repos: Dict[Tuple[str, str], Set[str]] = {}
    for e in edges:
        n = r.nodes.get(e.dst)
        if n is None and e.dst.startswith("missing:"):
            _, k, nm = e.dst.split(":", 2)
            n = Node(e.dst, "missing", nm, None, [], {"target_kind": k})
        if n is None or e.op == "loose":
            continue
        if n.kind == "missing":
            kind = str(n.attrs.get("target_kind", "target"))
            if kind in GAP_KINDS or n.name.startswith("?"):
                continue
        elif n.kind == "external":
            kind = "external"
        else:
            continue
        key = (kind, n.name)
        ev = e.evidence[0] if e.evidence else None
        names.setdefault(key, set())
        repos.setdefault(key, set())
        if ev is not None:
            names[key].add(_copy_key(e, r))
            repos[key].add(ev.repo or "?")
    o = [MISSING_INTRO, ""]
    if not names:
        return o + ["None."]
    found = {n.name for n in r.nodes.values() if n.kind not in ("missing", "external")}
    for (kind, name) in sorted(names, key=lambda k: (k[1], k[0])):
        places = len(names[(kind, name)])
        rs = sorted(repos[(kind, name)])
        o.append("- %s (%s) — referenced from %s (%d place%s)" % (
            name, kind, ", ".join(rs) or "unknown repo", places, "" if places == 1 else "s"))
    groups: Dict[str, Set[str]] = {}
    for (kind, name) in names:
        if kind == "external":
            groups.setdefault(_host_group(name), set()).add(name)
        elif len(name) >= PREFIX_LEN:
            pre = name[:PREFIX_LEN]
            if not any(f.startswith(pre) for f in found):
                groups.setdefault(pre + "*", set()).add(name)
    hits = {g: ns for g, ns in groups.items() if len(ns) >= 2}
    if hits:
        o += ["", "Names that share a prefix or host, so probably one missing repo:"]
        for g in sorted(hits):
            o.append("- %s: %s" % (g, ", ".join(sorted(hits[g]))))
    return o


CLICKABLE = ("The SVG (opened in a browser or VS Code) and the draw.io file are clickable: each "
             "box opens its file or folder. Mermaid click links are switched off on GitHub and "
             "Azure DevOps (strict mode), so the Mermaid picture is not clickable there. "
             "Excalidraw resolves relative links against the app, not the workspace.")


def md(text: object, lines: bool = False) -> str:
    """Text outside a table made safe for Markdown: ``\\ * _ [ ] ` `` and a leading ``#``
    are escaped and ``<`` is ``&lt;`` (table cells use ``_cell``). Newlines and runs of
    white space collapse to one space, so a heading, name or list item stays one line;
    ``lines=True`` keeps the lines (a paragraph such as the overview)."""
    out = []
    for line in (str(text).splitlines() or [""]) if lines else [" ".join(str(text).split())]:
        line = re.sub(r"([\\*_\[\]`])", r"\\\1", line).replace("<", "&lt;")
        out.append(re.sub(r"^(\s*)#", r"\1\\#", line))
    return "\n".join(out)


def _file_link(view: ViewGraph, path: str) -> str:
    return "[%s](%s)" % (md(path), href(view.repo_path or view.scope or "", path))


def _boxes(view: ViewGraph) -> List[Tuple[object, Optional[object]]]:
    """Every box with the "… N more" box it was folded into by the size cap (None when it is
    drawn), so a folded group, shared or outside box is still listed in full."""
    out: List[Tuple[object, Optional[object]]] = []
    for n in view.nodes:
        if n.folded:
            out += [(m, n) for m in n.folded]
        else:
            out.append((n, None))
    return out


def _folded_mark(more: Optional[object]) -> List[str]:
    return ["folded into '%s'" % more.label] if more is not None else []  # type: ignore


def _gd_head(view: ViewGraph) -> List[str]:
    """Overview, Groups, Entry points, Job structure and the outside/shared boxes."""
    o: List[str] = ["## Overview", "", md(view.overview.strip(), lines=True) if view.overview.strip() else "No overview was written.", ""]
    o += ["## Groups", ""]
    boxes = _boxes(view)
    groups = [(n, m) for n, m in boxes if n.kind == "group" and n.role != "ungrouped"]
    if not groups:
        o += ["No groups.", ""]
    for n, more in groups:
        o.append("### %s%s" % (md(n.label), " %s" % md(n.sublabel) if n.sublabel else ""))
        o.append("")
        if n.desc_line >= 0 and n.desc_line < len(n.detail_lines):
            o += [md(n.detail_lines[n.desc_line]), ""]
        o += ["- %s" % md(i) for i in _folded_mark(more)]
        o += ["- %s" % md(i) for i in n.info]
        o += ["- %s" % _file_link(view, p) for p in n.members] or ["- No files."]
        o.append("")
    o += ["## Entry points", ""]
    actors = [n for n in view.nodes if n.kind == "actor"]
    if not actors:
        o += ["None.", ""]
    for n in actors:
        o += ["### %s (%s)" % (md(n.label), md(n.sublabel)), ""]
        o += ["- %s" % md(m) for m in n.members] + [""]
    struct = [e for e in view.edges if e.status == STRUCTURAL]
    if struct:
        names = {n.id: n.label for n in view.nodes}
        o += ["## Job structure", "",
              "These lines say a job exists; who schedules it is not in these repos. They are "
              "not links and are not counted above.", ""]
        o += ["- %s %s %s" % (md(names.get(e.src, e.src)), md(e.label), md(names.get(e.dst, e.dst)))
              for e in struct]
        o.append("")
    other = [(n, m) for n, m in boxes if n.role == "shared" or n.id.startswith("out:")]
    if other:
        o += ["## Shared resources and outside this repo", ""]
        for n, more in other:
            o.append("- %s (%s)" % (md(n.label), md(n.sublabel)) if n.sublabel
                     else "- %s" % md(n.label))
            o += ["  - %s" % md(i) for i in _folded_mark(more) + n.info]
            o += ["  - %s" % md(m) for m in (n.members if n.id.startswith("out:") else [])]
        o.append("")
    return o


def _gd_tail(view: ViewGraph) -> List[str]:
    o: List[str] = ["", "## Clickable boxes", "", CLICKABLE, "", "## Not yet grouped", ""]
    ung = [n for n in view.nodes if n.role == "ungrouped"]
    if ung and (ung[0].members or ung[0].info):
        o += ["- %s" % md(i) for i in ung[0].info]
        o += ["- %s" % _file_link(view, p) for p in ung[0].members]
    else:
        o.append("None.")
    o += ["", "## Problems in the gitdiagram file", ""]
    o += ["- %s" % md(" ".join(p.split())) for p in view.problems] or ["None."]
    return o


def links_report(view: ViewGraph, r: Resolved) -> str:
    edges = _edges(view)
    links = _links(edges, r)
    count = {s: sum(1 for g in links if g[0].status == s) for s in (CONFIRMED, PARTIAL, LOOSE)}
    head = "%d confirmed · %d partly known · %d loose ends" % (
        count[CONFIRMED], count[PARTIAL], count[LOOSE])
    if len(edges) != len(links):
        head += " (%d rows from %d resolver edges incl. copies)" % (len(links), len(edges))
    struct = sum(1 for e in view.edges if e.status == STRUCTURAL)
    if struct:  # Ruling 10: named apart, never in the link counts
        head += "; %d job-structure line%s" % (struct, "" if struct == 1 else "s")
    gd = view.level == "gitdiagram"
    o: List[str] = ["# Links: %s" % view.title, "", head, ""]
    if gd:
        o += _gd_head(view)
    o += ["## Links on this diagram", ""]
    if links:
        o += ["| From | Link | To | Status | Evidence |", "|---|---|---|---|---|"]
        for g in links:
            e = g[0]
            o.append("| %s | %s | %s | %s | %s |" % (
                _cell(_display(r, e.src)), _cell(_link_text(e, r)), _cell(_display(r, e.dst)),
                e.status, _cell(_evidence_cell(g, r))))
    else:
        o.append("No links are drawn on this diagram.")
    seq = 0 if gd else sum(1 for e in view.edges if e.kind == "sequence")

    for title, status, default in (("Loose ends", LOOSE, "no definition found"),
                                   ("Partly known", PARTIAL, "not fully worked out")):
        o += ["", "## %s" % title, ""]
        gs = [g for g in links if g[0].status == status]
        o += [_bullet(g, r, default) for g in gs] or ["None."]

    o += ["", "## Possibly missing repos", ""] + _missing_section(edges, r)

    o += ["", "## Not analyzed", ""]
    na = r.inventory.languages_not_analyzed
    o += ["- %d %s files: program names registered, contents not analyzed" % (na[k], k)
          for k in sorted(na)] or ["None."]

    o += ["", "## Skipped files", ""]
    sk = r.inventory.skipped
    o += ["- `%s`: %s" % ("%s/%s" % (s["repo"], s.get("path")) if s.get("repo") else s.get("path"),
                         s.get("reason", "")) for s in sk] or ["None."]

    o += ["", "## Not scanned", ""]
    ns = r.inventory.not_scanned
    o += ["- `%s`: %s" % ("%s/%s" % (s["repo"], s.get("path")) if s.get("repo") else s.get("path"),
                         s.get("reason", "")) for s in ns] or ["None."]

    o += ["", "## Notes", ""]
    notes = [n for n in view.notes + layout_notes(view) if not (gd and n in view.problems)]
    o += ["- %s" % (md if gd else str)(" ".join(str(n).split())) for n in notes]
    if seq:
        o.append("- %d job-structure lines (step order, SYSOUT) are drawn but are not links; "
                 "they have no row above" % seq)
    if not notes and not seq:
        o.append("None.")
    if gd:
        o += _gd_tail(view)
    return "\n".join(o) + "\n"
