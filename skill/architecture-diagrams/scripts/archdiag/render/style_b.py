"""Style B: C4-style boxes, with a Mermaid copy.

Looks like diagram 1 of ``docs/samples/mainframe-samples.html`` and option B of
``docs/samples/style-options.html``: solid blue boxes with three lines of text (name in bold,
``[Kind: tech]``, a description), tables and datasets as cylinders, grey dashed repository
boundaries labelled bottom-left, and edge labels of a sentence plus a ``[tech]`` line.
Line types encode certainty exactly as in Style A (see ``common``).

render(view) -> {"svg": ..., "md": ..., "azure.md": ...}; the Markdown holds a Mermaid ``flowchart LR`` and
a legend.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from archdiag.layout import Box, Layout, layout_for, layout_notes
from archdiag.render.common import (LOOSE_COLOR, PARTIAL_COLOR, STARTS_LEGEND, esc, gd_details,
                                    group_colors, legend,
                                    legend_width, line_style, link_wrap, node_href, notes_block,
                                    notes_height, num, overview_block, step_text, svg_doc, text,
                                    text_width, wrap)
from archdiag.render.pills import edge_svg, key_svg, place_pills
from archdiag.views import VEdge, VNode, ViewGraph

NAME_SIZE, NAME_LINE = 13.0, 17.0
KIND_SIZE, KIND_LINE = 10.5, 14.0
DESC_SIZE, DESC_LINE = 10.5, 13.5
MAX_TEXT_W = 190.0
MIN_W = 150.0
PAD_TOP, PAD_BOTTOM = 10.0, 10.0
CYL_RY = 11.0                 # the cylinder's elliptical cap
PERSON_HEAD = 30.0            # a person's head, above the body
TITLE_H = 44.0
MAX_DESC_LINES = 4
MAX_GD_LINES = 12             # a gitdiagram box: files, description and details
GD_KINDS = ("group", "actor", "outside")  # gitdiagram boxes (spec 4.2)

BOX = "#1168bd"
PERSON = "#08427b"
EXTERNAL = "#999999"
QUEUE = "#438dd5"
NOTANALYZED = "#cbd5e1"
CAP = "#2a7fd4"               # a cylinder's top ellipse
SUB_TEXT = "#cfe0f5"
MUTED_ON_DARK = "#dbe4f0"     # a muted line on a coloured box
SHARED_FILL = "#e2e8f0"       # a gitdiagram resource box between groups: neutral
SHARED_CAP = "#cbd5e1"

CYLINDERS = ("table", "dataset", "vsam", "gdg", "datastore")

# (Kind, tech) per real kind; an empty tech gives "[Kind]"
_KIND_TECH = {
    "application": ("Application", ""), "datastore": ("Datastore", ""),
    "program": ("Program", "COBOL"), "copybook": ("Copybook", "COBOL"),
    "utility": ("Utility", ""), "job": ("Job", "JCL"), "step": ("Job step", "JCL"),
    "proc": ("JCL proc", ""), "dataset": ("Dataset", "z/OS"),
    "gdg": ("Generation dataset", "z/OS"), "vsam": ("VSAM dataset", ""),
    "table": ("Table", "DB2"), "queue": ("Queue", "IBM MQ"), "mqprocess": ("MQ process", ""),
    "transaction": ("CICS transaction", ""), "map": ("BMS map", ""),
    "cicsfile": ("CICS file", ""), "external": ("External system", ""),
    "notanalyzed": ("Not analyzed", ""), "repo": ("Repository", ""),
    "page": ("Page", "Angular"), "component": ("Component", "Angular"),
    "class": ("Class", "Java"), "endpoint": ("Endpoint", "REST"),
    "zosapi": ("API", "z/OS Connect"), "person": ("Person", ""), "more": ("More", ""),
    "sysout": ("Output", ""),
}
# what a neighbor box says it is: "[COBOL program · neighbor]"
_FULL = {
    "program": "COBOL program", "copybook": "COBOL copybook", "zosapi": "z/OS Connect API",
    "endpoint": "REST endpoint", "transaction": "CICS transaction", "map": "BMS map",
    "queue": "IBM MQ queue", "table": "DB2 table", "dataset": "dataset",
    "vsam": "VSAM dataset", "gdg": "GDG", "job": "JCL job", "class": "Java class",
    "component": "Angular component", "page": "Angular page", "cicsfile": "CICS file",
    "mqprocess": "MQ process", "proc": "JCL proc", "utility": "utility",
    "application": "application", "external": "external system",
}
_FROM_SUBLABEL = ("application", "datastore", "repo")  # the sublabel is the technology


def real_kind(n: VNode) -> str:
    return n.real_kind or n.kind


# ------------------------------------------------------------------ the three lines of text

def _card(n: VNode) -> Tuple[str, str, List[str]]:
    """(name, ``[Kind: tech]``, description lines) for one box, from its real kind."""
    k = real_kind(n)
    sub = n.sublabel or ""
    if n.kind == "missing":
        return n.label, "", ([sub] if sub else [])
    if n.role == "shared":  # gitdiagram: a resource between groups, name and short kind
        return n.label, "[%s]" % sub if sub else "", []
    if n.kind in GD_KINDS:  # gitdiagram: the sublabel is the [tech] or what the box holds
        kind_line = sub if sub.startswith("[") else ("[%s]" % sub if sub else "")
        return n.label, kind_line, list(n.detail_lines)
    if n.kind == "neighbor":
        owner = sub.split(" · ", 1)[1] if " · " in sub else ""
        return (n.label, "[%s · neighbor]" % _FULL.get(k, k), [owner] if owner else [])
    kind, tech = _KIND_TECH.get(k, (k.title(), ""))
    desc: List[str] = []
    if n.kind in _FROM_SUBLABEL:
        tech = sub
        details = list(n.detail_lines)
        if n.kind == "repo" and len(details) > MAX_DESC_LINES:
            details = details[:MAX_DESC_LINES - 1] + ["+%d more" % (len(details) - MAX_DESC_LINES + 1)]
        desc = details
    elif n.kind == "notanalyzed":
        parts = sub.split(" · ")
        tech = parts[0] if parts and parts[0] != "code" else ""
        desc = [parts[2]] if len(parts) > 2 else []
    else:
        m = re.match(r"^(\S+) program", sub)
        if k == "program" and m:
            tech = m.group(1)
        if " · " in sub:
            rest = sub.split(" · ", 1)[1]
        elif (tech and tech.lower() in sub.lower()) or sub.lower() == kind.lower():
            rest = ""
        else:
            rest = sub
        if rest:
            desc = [rest]
    if tech and tech.lower() in kind.lower():
        tech = ""
    return n.label, "[%s: %s]" % (kind, tech) if tech else "[%s]" % kind, desc


class _Text:
    def __init__(self, n: VNode) -> None:
        name, kind_line, desc = _card(n)
        self.name = wrap(name, MAX_TEXT_W, NAME_SIZE)
        self.kind = [kind_line] if kind_line else []
        self.desc: List[str] = []
        self.muted: Set[int] = set()  # indexes of desc lines drawn muted
        if n.kind == "group":  # gitdiagram: description capped, links-inside line muted
            for k, (d, m) in enumerate(gd_details(n, MAX_TEXT_W, DESC_SIZE)):
                self.desc.append(d)
                if m:
                    self.muted.add(k)
        else:
            for d in desc:
                self.desc.extend(wrap(d, MAX_TEXT_W, DESC_SIZE))
        self.desc = self.desc[:(MAX_GD_LINES if n.kind in GD_KINDS else MAX_DESC_LINES + 1)]
        widths = [text_width(s, NAME_SIZE) + 6 for s in self.name]
        widths += [text_width(s, KIND_SIZE) for s in self.kind]
        widths += [text_width(s, DESC_SIZE) for s in self.desc]
        self.width = max(widths) if widths else 0.0
        self.height = (NAME_LINE * len(self.name) + KIND_LINE * len(self.kind)
                       + DESC_LINE * len(self.desc) + (4 if self.desc else 0))


def _extra_top(n: VNode) -> float:
    if n.kind in CYLINDERS:
        return 2 * CYL_RY - 4
    if n.kind in ("person", "actor"):
        return PERSON_HEAD
    return 0.0


def node_size(n: VNode) -> Tuple[float, float]:
    t = _Text(n)
    w = max(MIN_W, t.width + 24)
    return w, PAD_TOP + t.height + PAD_BOTTOM + _extra_top(n) + (6 if n.kind in CYLINDERS else 0)


# ------------------------------------------------------------------ SVG

def _fill(n: VNode) -> str:
    if n.kind == "person":
        return PERSON
    if n.kind == "external":
        return EXTERNAL
    if n.kind in ("queue",):
        return QUEUE
    if n.kind in ("notanalyzed", "neighbor", "outside"):
        return NOTANALYZED
    return BOX


def _clock_head(cx: float, cy: float, r: float) -> str:
    """The Scheduler's head: a clock face in the person colour."""
    return ('<circle cx="%s" cy="%s" r="%s" fill="%s"/><circle cx="%s" cy="%s" r="%s" '
            'fill="#ffffff"/><path d="M%s,%s V%s L%s,%s" fill="none" stroke="%s" '
            'stroke-width="2.4" stroke-linecap="round"/>'
            % (num(cx), num(cy), num(r), PERSON, num(cx), num(cy), num(r - 3.5),
               num(cx), num(cy - r + 7), num(cy), num(cx + r * 0.45), num(cy + r * 0.3),
               PERSON))


def _node_svg(n: VNode, b: Box, ox: float, oy: float, color: str = "") -> str:
    t = _Text(n)
    x, y, w, h = b.x + ox, b.y + oy, b.w, b.h
    cx = x + w / 2
    parts: List[str] = []
    name_fill, kind_fill, desc_fill = "#ffffff", SUB_TEXT, "#ffffff"
    top = y + PAD_TOP
    if n.kind == "missing":
        partial = n.status == "partial"
        c = PARTIAL_COLOR if partial else LOOSE_COLOR
        dash = ' stroke-dasharray="3 4"' if partial else ""
        parts.append('<rect x="%s" y="%s" width="%s" height="%s" rx="6" fill="%s" stroke="%s" '
                     'stroke-width="1.6"%s/>' % (num(x), num(y), num(w), num(h),
                                                 "#fffbeb" if partial else "#fef2f2", c, dash))
        name_fill = kind_fill = desc_fill = "#b45309" if partial else "#b91c1c"
        top = y + (h - t.height) / 2
    elif n.kind in CYLINDERS:
        ry = CYL_RY
        body_fill, cap_fill = BOX, CAP
        if n.role == "shared":  # gitdiagram: neutral, so it never looks like a group
            body_fill, cap_fill = SHARED_FILL, SHARED_CAP
            name_fill, kind_fill, desc_fill = "#1e293b", "#475569", "#334155"
        parts.append('<path d="M%s,%s L%s,%s A%s,%s 0 0,0 %s,%s L%s,%s" fill="%s"/>'
                     % (num(x), num(y + ry), num(x), num(y + h - ry), num(w / 2), num(ry),
                        num(x + w), num(y + h - ry), num(x + w), num(y + ry), body_fill))
        parts.append('<ellipse cx="%s" cy="%s" rx="%s" ry="%s" fill="%s"/>'
                     % (num(cx), num(y + ry), num(w / 2), num(ry), cap_fill))
        top = y + 2 * ry - 2 + PAD_TOP / 2
    elif n.kind in ("person", "actor"):
        if n.id == "act:scheduler":
            parts.append(_clock_head(cx, y + PERSON_HEAD / 2 + 2, PERSON_HEAD / 2 + 2))
        else:
            parts.append('<circle cx="%s" cy="%s" r="%s" fill="%s"/>'
                         % (num(cx), num(y + PERSON_HEAD / 2 + 2), num(PERSON_HEAD / 2 + 2),
                            PERSON))
        parts.append('<rect x="%s" y="%s" width="%s" height="%s" rx="16" fill="%s"/>'
                     % (num(x), num(y + PERSON_HEAD), num(w), num(h - PERSON_HEAD), PERSON))
        top = y + PERSON_HEAD + PAD_TOP
    else:
        fill = color if n.kind == "group" and color else _fill(n)
        stroke = ""
        if n.kind in ("notanalyzed", "neighbor", "outside"):
            stroke = ' stroke="#94a3b8" stroke-width="1.4" stroke-dasharray="4 3"'
            name_fill, kind_fill, desc_fill = "#1e293b", "#475569", "#334155"
        elif n.role == "ungrouped":  # gitdiagram "Not yet grouped": dashed grey, light fill
            fill = "#f8fafc"
            stroke = ' stroke="#64748b" stroke-width="1.4" stroke-dasharray="6 4"'
            name_fill, kind_fill, desc_fill = "#1e293b", "#475569", "#334155"
        elif n.role == "shared":
            fill = SHARED_FILL
            stroke = ' stroke="#94a3b8" stroke-width="1.2"'
            name_fill, kind_fill, desc_fill = "#1e293b", "#475569", "#334155"
        parts.append('<rect x="%s" y="%s" width="%s" height="%s" rx="6" fill="%s"%s/>'
                     % (num(x), num(y), num(w), num(h), fill, stroke))
        if n.kind == "queue":
            kind_fill = "#e3eefa"
    ty = top
    for s in t.name:
        ty += NAME_LINE
        parts.append(text(cx, ty - 4, s, NAME_SIZE, name_fill, "middle", "700"))
    for s in t.kind:
        ty += KIND_LINE
        parts.append(text(cx, ty - 3.5, s, KIND_SIZE, kind_fill, "middle"))
    if t.desc:
        ty += 4
    for k, s in enumerate(t.desc):
        ty += DESC_LINE
        parts.append(text(cx, ty - 3.5, s, DESC_SIZE,
                          (MUTED_ON_DARK if desc_fill == "#ffffff" else "#94a3b8")
                          if k in t.muted else desc_fill, "middle"))
    return "<g>%s</g>" % "".join(parts)


def group_title(label: str) -> str:
    return "%s [repo]" % label


def _edge_text(e: VEdge) -> str:
    """A sentence, then its ``[tech]`` on a second line (``REST · GET /x`` -> two lines).
    The pill draws the step number itself."""
    label = e.label
    head, tail = (label.split(" · ", 1) + [""])[:2] if " · " in label else (label, "")
    return "%s\n[%s]" % (head, tail) if tail else head


def _title_zone(g, gb) -> Optional[Tuple[float, float, float, float]]:
    w = text_width(group_title(g.label), 11) + 10
    return (gb[0] + 4, gb[1] + gb[3] - 24, w, 22)


def _svg(view: ViewGraph, L: Layout) -> str:
    styles = [line_style(e.status, e.kind) for e in view.edges]
    routes = [list(r) for r in L.routes]
    pills = place_pills(view, L, styles, routes, _edge_text, _title_zone)

    min_x = min([p.x for p in pills] + [0.0])
    min_y = min([p.y for p in pills] + [0.0])
    ox = max(0.0, 14 - min_x) if min_x < 14 else 0.0
    content_w = max([L.width] + [p.x + p.w + 14 for p in pills]) + ox

    present: Set[str] = set(styles)
    title_w = text_width(view.title, 16) + 60
    width = max(content_w, legend_width(present) + 60, title_w, 360.0)
    note_w = max(width - 60, 560.0)
    width = max(width, note_w + 60)
    overview, ov_h = overview_block(view.overview, width)
    oy = TITLE_H + ov_h + (max(0.0, 14 - min_y) if min_y < 14 else 0.0)
    content_h = max([L.height] + [p.y + p.h + 14 for p in pills]) + oy
    key, key_h = key_svg(pills, 30, content_h + 6, width - 60)
    leg_y = content_h + 6 + (key_h + 10 if key_h else 0)
    leg, leg_h = legend(30, leg_y, present)
    notes_y = leg_y + leg_h + (14 if leg_h else 0)
    n_h = notes_height(view.notes + L.notes, note_w)
    height = notes_y + n_h + (16 if n_h else 4)

    body: List[str] = [text(24, 30, view.title, 16, "#0f172a", weight="700")]
    if overview:
        body.append('<g transform="translate(0,%s)">%s</g>' % (num(TITLE_H), overview))
    colors = group_colors(view)
    for g in view.groups:
        gb = L.groups.get(g.id)
        if gb is None:
            continue
        body.append('<rect x="%s" y="%s" width="%s" height="%s" rx="4" fill="none" '
                    'stroke="#888888" stroke-width="1.3" stroke-dasharray="7 5"/>'
                    % (num(gb.x + ox), num(gb.y + oy), num(gb.w), num(gb.h)))
        body.append(text(gb.x + ox + 8, gb.y + oy + gb.h - 8, group_title(g.label), 11,
                         "#555555"))
    for i, e in enumerate(view.edges):
        if i < len(routes):
            body.append(edge_svg(i, routes[i], styles[i], e.status, e.kind, ox, oy))
    for n in view.nodes:
        b = L.boxes.get(n.id)
        if b is not None:
            body.append(link_wrap(view, n, _node_svg(n, b, ox, oy, colors.get(n.id, ""))))
    body.extend(p.svg(ox, oy) for p in pills)
    body.append(key)
    body.append(leg)
    body.append(notes_block(view.notes + L.notes, 30, notes_y, note_w))
    return svg_doc(width, height, "".join(body), title=view.title)


# ------------------------------------------------------------------ Mermaid

_LINE_STYLE = {
    "confirmed": "stroke:#334155,stroke-width:2px",
    "partial": "stroke:#d97706,stroke-width:2px",
    "loose": "stroke:#dc2626,stroke-width:2px",
    "shared_code": "stroke:#a16207,stroke-width:2px,stroke-dasharray:7 4",
    "structural": "stroke:#94a3b8,stroke-width:1.4px",
}
_ARROW = {"confirmed": "-->", "partial": "-.->", "loose": "--x", "shared_code": "-->",
          "structural": "-->"}

_CLASSES = (
    ("box", "fill:#1168bd,stroke:#0b4884,color:#ffffff"),
    ("person", "fill:#08427b,stroke:#052e56,color:#ffffff"),
    ("external", "fill:#999999,stroke:#6b6b6b,color:#ffffff"),
    ("queue", "fill:#438dd5,stroke:#2e6295,color:#ffffff"),
    ("notanalyzed", "fill:#cbd5e1,stroke:#94a3b8,color:#1e293b,stroke-dasharray:4 3"),
    ("missingLoose", "fill:#fef2f2,stroke:#dc2626,color:#b91c1c"),
    ("missingPartial", "fill:#fffbeb,stroke:#d97706,color:#b45309,stroke-dasharray:3 4"),
)


def mm(s: str) -> str:
    """Text safe inside a double-quoted Mermaid label: ``#`` first, then the characters
    Mermaid reads as syntax, as ``#name;`` entity codes."""
    s = " ".join(str(s).split())
    for ch, code in (("#", "#35;"), ('"', "#quot;"), ("<", "#lt;"), (">", "#gt;"),
                     ("&", "#amp;"), ("`", "#96;"), ("[", "#91;"), ("]", "#93;"),
                     ("|", "#124;")):
        s = s.replace(ch, code)
    return s


def _node_class(n: VNode) -> str:
    if n.kind == "missing":
        return "missingPartial" if n.status == "partial" else "missingLoose"
    if n.kind == "person":
        return "person"
    if n.kind == "external":
        return "external"
    if n.kind == "queue":
        return "queue"
    if n.kind in ("notanalyzed", "neighbor"):
        return "notanalyzed"
    return "box"


def _node_mermaid(i: int, n: VNode) -> str:
    name, kind_line, desc = _card(n)
    label = "<br/>".join(["<b>%s</b>" % mm(name)]
                         + ([mm(kind_line)] if kind_line else []) + [mm(d) for d in desc])
    if n.kind in CYLINDERS:
        return 'n%d[("%s")]' % (i, label)
    return 'n%d["%s"]' % (i, label)


# Clickable boxes: the ``click`` lines work in the VS Code Mermaid preview and mermaid.live.
# GitHub and Azure DevOps render Mermaid in strict mode, so boxes are not clickable there.
# (Excalidraw resolves relative links against the app, not the file, so they rarely open.)
# The SVG (browser / VS Code) and draw.io outputs are the clickable ones.
def _mermaid(view: ViewGraph) -> str:
    index = {n.id: i for i, n in enumerate(view.nodes)}
    lines = ["flowchart LR"]
    members: Dict[str, List[int]] = {g.id: [] for g in view.groups}
    loose_nodes: List[int] = []
    for i, n in enumerate(view.nodes):
        if n.group in members:
            members[n.group].append(i)
        else:
            loose_nodes.append(i)
    for k, g in enumerate(view.groups):
        lines.append('  subgraph sg%d["%s"]' % (k, mm(group_title(g.label))))
        for i in members[g.id]:
            lines.append("    " + _node_mermaid(i, view.nodes[i]))
        lines.append("  end")
    for i in loose_nodes:
        lines.append("  " + _node_mermaid(i, view.nodes[i]))
    styles: List[str] = []
    for e in view.edges:
        st = line_style(e.status, e.kind)
        styles.append(st)
        num_s = step_text(e.number)
        label = ("%s %s" % (num_s, e.label)).strip() if num_s else e.label
        arrow = _ARROW[st]
        a, b = "n%d" % index[e.src], "n%d" % index[e.dst]
        if label:
            lines.append('  %s %s|"%s"| %s' % (a, arrow, mm(label), b))
        else:
            lines.append("  %s %s %s" % (a, arrow, b))
    for i, n in enumerate(view.nodes):
        if n.link:
            lines.append('  click n%d "%s"' % (i, node_href(view, n)))
    for i, st in enumerate(styles):
        lines.append("  linkStyle %d %s" % (i, _LINE_STYLE[st]))
    for name, style in _CLASSES:
        lines.append("  classDef %s %s" % (name, style))
    by_class: Dict[str, List[str]] = {}
    for i, n in enumerate(view.nodes):
        by_class.setdefault(_node_class(n), []).append("n%d" % i)
    for name, _ in _CLASSES:
        if name in by_class:
            lines.append("  class %s %s" % (",".join(by_class[name]), name))
    return "\n".join(lines)


_MD_LEGEND = (
    ("confirmed", "Solid dark line (`-->`): confirmed, both ends found in code"),
    ("partial", "Dotted amber line (`-.->`): partly known or suggested"),
    ("loose", "Red line ending in a cross (`--x`): loose end, only one side found"),
    ("shared_code", "Dashed brown line: shared code (copybook, package)"),
    ("structural", "Thin grey line: %s" % STARTS_LEGEND),
)


def _markdown(view: ViewGraph, azure: bool = False) -> str:
    """The Mermaid Markdown: fenced with ```mermaid for GitHub and VS Code, or with the
    ``::: mermaid`` block Azure DevOps wikis need (``azure=True``, the ``.azure.md`` copy)."""
    styles = {line_style(e.status, e.kind) for e in view.edges}
    fence = ("::: mermaid", ":::") if azure else ("```mermaid", "```")
    ov = " ".join(str(view.overview or "").split())
    out = ["# %s" % " ".join(view.title.split()), ""]
    if ov:
        out += [ov, ""]
    out += [fence[0], _mermaid(view), fence[1], "", "## Legend", ""]
    for key, label in _MD_LEGEND:
        if key in styles:
            out.append("- %s" % label)
    out.append("- Blue box: a thing found in the repositories; grey box: outside them; "
               "light grey: not analyzed; red or amber outline: not found / partly known")
    out.append("- Cylinder: a table or dataset; a dashed box groups one repository")
    notes = view.notes + layout_notes(view)
    if notes:
        out += ["", "## Notes", ""] + ["- %s" % n for n in notes]
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ entry point

def render(view: ViewGraph) -> Dict[str, str]:
    """The C4-style SVG and its Mermaid Markdown (GitHub ``.md`` and Azure DevOps wiki
    ``.azure.md``), from one layout of ``view``."""
    L = layout_for(view, node_size)
    return {"svg": _svg(view, L), "md": _markdown(view), "azure.md": _markdown(view, True)}
