"""The draw.io (``.drawio``) copy every style writes next to its SVG.

One writer for all four styles: it takes the view and the layout the style's SVG was drawn
from, so the boxes sit where the SVG has them, and writes a file made to be edited:

* lines are orthogonal connectors between their two boxes with no fixed waypoints, so
  draw.io reroutes them when a box is moved. Where the layout's line leaves or enters a box
  on a known side, that side (and the place along it) is kept as ``exitX/exitY`` and
  ``entryX/entryY``; a line whose two ends are in one group belongs to that group;
* boxes are stock draw.io shapes picked by what the thing is (cylinder, queue, actor,
  document, cloud, hexagon, rounded rectangle), with a bold name and a smaller technology
  line; groups are ``swimlane`` containers holding their members, so moving a group moves
  them; every box is on the 10 px grid;
* every box and line is wrapped in ``<object>`` with ``status``, ``kind``, ``evidence``
  (``repo/path:line; ...``) and ``reason``: draw.io shows them as the tooltip and under
  Edit Data;
* four layers: "Diagram", "Loose ends and gaps" (the "nothing found" boxes and every line
  that is loose or touches one), "Shared code" (copybooks and COPY lines) and "Legend" (one
  container: the line types drawn, and the notes). A line is never on a layer below one of
  its boxes, so hiding a layer never leaves a line pointing at nothing. A "nothing found"
  box or a copybook is on its layer even when the SVG draws it inside a group.

``render(view, L, ...)`` returns the file's text; the same input gives the same bytes.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from archdiag.layout import Box, Layout
from archdiag.render.common import (_DEFAULT, _LEGEND, LEGEND_SIZE, LOOSE_COLOR, NOTE_LINE,
                                    NOTE_SIZE, OVERVIEW_LINE, OVERVIEW_SIZE, PARTIAL_COLOR,
                                    REPO_COLORS, esc, line_style, node_href, note_lines,
                                    step_text, text_width, tint, wrap)
from archdiag.views import VEdge, VNode, ViewGraph

GRID = 10
PAGE_W, PAGE_H = 1654, 1169   # A3 landscape at draw.io's 100 px per inch
TITLE_H = 40
EVIDENCE_MAX = 10             # places named in one ``evidence`` attribute
LAYER_DIAGRAM, LAYER_LOOSE, LAYER_SHARED, LAYER_LEGEND = "1", "layer-loose", "layer-shared", \
    "layer-legend"
LAYERS = ((LAYER_DIAGRAM, "Diagram"), (LAYER_LOOSE, "Loose ends and gaps"),
          (LAYER_SHARED, "Shared code"), (LAYER_LEGEND, "Legend"))

EDGE_BASE = ("edgeStyle=orthogonalEdgeStyle;rounded=1;jettySize=auto;html=1;orthogonalLoop=1;"
             "labelBackgroundColor=#ffffff;fontSize=10;")
# the certainty of a line, as the SVGs draw it (render.common)
EDGE_STYLE = {
    "confirmed": "strokeColor=#334155;strokeWidth=2;endArrow=block;endFill=1;"
                 "fontColor=#334155;",
    "partial": "dashed=1;dashPattern=3 4;strokeColor=#d97706;strokeWidth=2;endArrow=block;"
               "endFill=1;fontColor=#b45309;",
    "loose": "strokeColor=#dc2626;strokeWidth=2;endArrow=oval;endFill=1;endSize=10;"
             "fontColor=#b91c1c;",
    "shared_code": "dashed=1;dashPattern=7 4;strokeColor=#a16207;strokeWidth=1.6;"
                   "endArrow=block;endFill=1;fontColor=#a16207;",
    "structural": "strokeColor=#94a3b8;strokeWidth=1.4;endArrow=block;endFill=1;"
                  "fontColor=#64748b;",
}

_CYLINDER = "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=10;"
_QUEUE = "shape=cylinder3;direction=south;size=10;"   # a cylinder on its side
_ACTOR = "shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;outlineConnect=0;"
_DOCUMENT = "shape=document;boundedLbl=1;size=0.2;"
_CLOUD = "ellipse;shape=cloud;"
_HEXAGON = "shape=hexagon;perimeter=hexagonPerimeter2;fixedSize=1;size=12;"
_FOLDER = "shape=folder;tabWidth=40;tabHeight=12;tabPosition=left;boundedLbl=1;"
_ROUNDED = "rounded=1;arcSize=12;"
SHAPES = {
    "table": _CYLINDER, "datastore": _CYLINDER, "vsam": _CYLINDER, "cicsfile": _CYLINDER,
    "queue": _QUEUE, "mqprocess": _QUEUE,
    "person": _ACTOR, "actor": _ACTOR,
    "job": _DOCUMENT, "proc": _DOCUMENT, "dataset": _DOCUMENT, "gdg": _DOCUMENT,
    "sysout": _DOCUMENT,
    "external": _CLOUD, "outside": _CLOUD,
    "endpoint": _HEXAGON, "zosapi": _HEXAGON,
    "repo": _FOLDER,
}
ACTOR_W, ACTOR_H = 40, 60     # the stick figure; its label hangs below it
SKETCH = "sketch=1;curveFitting=1;jiggle=2;"


class Look:
    """How one box is painted: the colours its SVG uses."""

    def __init__(self, fill: str, stroke: str, font: str = "#0f172a", sub: str = "#64748b",
                 dashed: bool = False) -> None:
        self.fill, self.stroke, self.font, self.sub, self.dashed = fill, stroke, font, sub, dashed


LookFn = Callable[[VNode], Look]
LinesFn = Callable[[VNode], Tuple[str, str, Sequence[str]]]

GREY_KINDS = ("neighbor", "notanalyzed", "outside")


def real_kind(n: VNode) -> str:
    """What the box really is (a copybook is drawn as a program, a neighbor keeps its own
    kind in ``real_kind``); a sysout box is told by its id."""
    if n.id.startswith("sysout:"):
        return "sysout"
    return n.real_kind or n.kind


# kinds a box is drawn as whatever the resolver calls the thing behind it
_OWN_SHAPE = ("person", "actor", "outside", "external", "group", "repo")


def shape_of(n: VNode) -> str:
    """The stock draw.io shape (the start of the style) for this box."""
    if n.kind in ("missing", "notanalyzed"):
        return _ROUNDED
    if n.id == "act:scheduler":  # an entry point, but not a person
        return "ellipse;"
    return SHAPES.get(n.kind if n.kind in _OWN_SHAPE else real_kind(n), _ROUNDED)


def is_actor(n: VNode) -> bool:
    """Drawn as the stick figure, its label below it (so on the page, not on a fill)."""
    return shape_of(n) == _ACTOR


def default_look(n: VNode, color: str = "") -> Look:
    """A light tint of ``color`` (the box's group colour, or its kind's own colour) with a
    border in the colour itself; grey and dashed for what is outside or not analyzed."""
    if n.kind in GREY_KINDS or n.role == "ungrouped":
        return Look("#f8fafc", "#94a3b8", "#64748b", "#94a3b8", True)
    c = color or _DEFAULT.get(real_kind(n), _DEFAULT.get(n.kind, "#64748b"))
    return Look(tint(c, 0.18), c)


def missing_look(n: VNode) -> Look:
    """A "nothing found" box: red, or dotted orange when the link is partly known."""
    if n.status == "partial":
        return Look("#fffbeb", PARTIAL_COLOR, "#b45309", "#b45309", True)
    return Look("#fef2f2", LOOSE_COLOR, "#b91c1c", "#b91c1c")


def default_lines(n: VNode) -> Tuple[str, str, Sequence[str]]:
    return n.label, n.sublabel, n.detail_lines


# ------------------------------------------------------------------ text

def _clean(s: object) -> str:
    """``s`` without the control characters XML 1.0 cannot hold."""
    return "".join(ch for ch in str(s) if ch in "\t\n" or ord(ch) >= 0x20)


def attr(s: object) -> str:
    """An XML attribute value: escaped, a line break as a character reference."""
    return esc(_clean(s)).replace("\n", "&#10;").replace("\t", " ")


def html(s: object) -> str:
    """Text inside an ``html=1`` label (escaped once more by ``attr`` when written)."""
    return _clean(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def node_label(name: str, tech: str, details: Sequence[str], look: Look) -> str:
    """The html label: the name in bold, the technology smaller, details smaller still."""
    parts = ["<b>%s</b>" % html(name)]
    if tech:
        parts.append('<font color="%s" style="font-size: 10px">%s</font>' % (look.sub, html(tech)))
    for d in details:
        if d:
            parts.append('<font style="font-size: 10px">%s</font>' % html(d))
    return "<br>".join(parts)


def edge_text(e: VEdge) -> str:
    """``(3) LINK``: the step number stays in the label."""
    num_s = step_text(e.number)
    return "%s %s" % (num_s, e.label) if num_s and e.label else num_s or e.label


def evidence_text(evidence: Sequence[object]) -> str:
    """``repo/path:line; ...``: each place once, in order, at most EVIDENCE_MAX of them."""
    seen: List[str] = []
    for ev in evidence:
        repo, path = getattr(ev, "repo", ""), getattr(ev, "path", "")
        place = "%s/%s" % (repo, path) if repo and repo != "." else str(path)
        line = getattr(ev, "line", 0)
        s = "%s:%s" % (place, line) if line else place
        if s not in seen:
            seen.append(s)
    out = "; ".join(seen[:EVIDENCE_MAX])
    if len(seen) > EVIDENCE_MAX:
        out += "; +%d more" % (len(seen) - EVIDENCE_MAX)
    return out


def _edge_evidence(e: VEdge) -> str:
    ev = list(e.evidence)
    for u in e.underlying:
        ev.extend(u.evidence)
    return evidence_text(ev)


def _edge_reason(e: VEdge) -> str:
    out: List[str] = []
    for u in e.underlying:
        r = " ".join(str(u.reason or "").split())
        if r and r not in out:
            out.append(r)
    return "; ".join(out)


def _node_evidence(n: VNode, nodes: Optional[Dict[str, object]]) -> str:
    ev: List[object] = []
    found = nodes.get(n.id) if nodes else None
    if found is not None:
        ev.extend(getattr(found, "evidence", []) or [])
    for u in n.underlying:
        ev.extend(u.evidence)
    return evidence_text(ev)


# ------------------------------------------------------------------ geometry

def snap(v: float) -> int:
    """``v`` on the grid (halves go up)."""
    return int(math.floor(v / GRID + 0.5)) * GRID


def snap_up(v: float) -> int:
    return int(math.ceil(v / GRID - 1e-9)) * GRID


def snap_down(v: float) -> int:
    return int(math.floor(v / GRID + 1e-9)) * GRID


def _rect(b: Box) -> Tuple[int, int, int, int]:
    return snap(b.x), snap(b.y), max(GRID, snap_up(b.w)), max(GRID, snap_up(b.h))


def _geom(x: float, y: float, w: float, h: float) -> str:
    return '<mxGeometry x="%d" y="%d" width="%d" height="%d" as="geometry"/>' % (x, y, w, h)


def _frac(v: float) -> str:
    s = "%.2f" % min(1.0, max(0.0, v))
    return s.rstrip("0").rstrip(".") if "." in s else s


def side_of(b: Optional[Box], p: Tuple[float, float], tol: float = 1.5
            ) -> Optional[Tuple[str, str]]:
    """Where on the border of ``b`` the point ``p`` is, as draw.io's (x, y) fractions of the
    box: (0, y) the left side, (1, y) the right, (x, 0) the top, (x, 1) the bottom. None when
    the point is not on the border (the layout does not say which side)."""
    if b is None or b.w <= 0 or b.h <= 0:
        return None
    x, y = p
    if not (b.x - tol <= x <= b.right + tol and b.y - tol <= y <= b.bottom + tol):
        return None
    fx, fy = (x - b.x) / b.w, (y - b.y) / b.h
    if abs(x - b.x) <= tol:
        return "0", _frac(fy)
    if abs(x - b.right) <= tol:
        return "1", _frac(fy)
    if abs(y - b.y) <= tol:
        return _frac(fx), "0"
    if abs(y - b.bottom) <= tol:
        return _frac(fx), "1"
    return None


# ------------------------------------------------------------------ cells

def _object(cid: str, label: str, data: Sequence[Tuple[str, str]], cell: str) -> str:
    """``cell`` (an mxCell without id and value) wrapped in ``<object>`` with its data."""
    extra = "".join(' %s="%s"' % (k, attr(v)) for k, v in data)
    return '<object label="%s"%s id="%s">%s</object>' % (attr(label), extra, cid, cell)


def _vertex_style(n: VNode, look: Look, sketch: bool) -> str:
    shape = shape_of(n)
    wrap_ = "" if shape == _ACTOR else "whiteSpace=wrap;"   # an actor's label hangs below it
    dash = "dashed=1;dashPattern=4 3;" if look.dashed else ""
    return "%s%shtml=1;fillColor=%s;strokeColor=%s;fontColor=%s;fontSize=12;%s%s" % (
        shape, wrap_, look.fill, look.stroke, look.font, dash, SKETCH if sketch else "")


def _shade(color: str) -> str:
    """A darker shade of a group colour, for its title."""
    c = color.lstrip("#")
    try:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except (ValueError, IndexError):
        return "#334155"
    return "#%02x%02x%02x" % (int(r * 0.6), int(g * 0.6), int(b * 0.6))


def group_title(gid: str, label: str) -> str:
    return "repo: %s" % label if gid.startswith("repo:") else label


def _layer_of_node(n: VNode) -> str:
    if n.kind == "missing":
        return LAYER_LOOSE
    if real_kind(n) == "copybook":
        return LAYER_SHARED
    return LAYER_DIAGRAM


def _layer_of_edge(style: str, ends: Sequence[str]) -> str:
    """The layer of a line of this type between boxes on the layers ``ends``: the loose-end
    layer when it is loose or touches a box there, else the shared-code one likewise."""
    if style == "loose" or LAYER_LOOSE in ends:
        return LAYER_LOOSE
    if style == "shared_code" or LAYER_SHARED in ends:
        return LAYER_SHARED
    return LAYER_DIAGRAM


def render(view: ViewGraph, L: Layout, look: Optional[LookFn] = None,
           lines: Optional[LinesFn] = None, nodes: Optional[Dict[str, object]] = None,
           sketch: bool = False) -> str:
    """The draw.io file of ``view`` as laid out in ``L``.

    ``look`` gives a box its colours and ``lines`` its (name, technology, details) when a
    style draws them its own way; ``nodes`` (the resolver's nodes by id) adds where each
    thing was found to its ``evidence``; ``sketch`` gives the hand-drawn look."""
    look = look or default_look
    lines = lines or default_lines
    sk = SKETCH if sketch else ""
    cells: List[str] = ['<mxCell id="0"/>']
    for lid, name in LAYERS:
        cells.append('<mxCell id="%s" value="%s" parent="0"/>' % (lid, attr(name)))

    # ---- title and overview, above the picture
    width = max(L.width, text_width(view.title, 16) + 60, 360.0)
    cells.append('<mxCell id="title" value="%s" style="text;html=1;align=left;'
                 'verticalAlign=middle;fontSize=16;fontStyle=1;fontColor=#0f172a;" vertex="1" '
                 'parent="1">%s</mxCell>'
                 % (attr(html(view.title)),
                    _geom(20, 0, snap_up(text_width(view.title, 16) + 40), TITLE_H)))
    oy = TITLE_H
    ov = " ".join(str(view.overview or "").split())
    if ov:
        oh = snap_up(14 + OVERVIEW_LINE * len(wrap(ov, max(200.0, width - 64), OVERVIEW_SIZE)))
        cells.append('<mxCell id="overview" value="%s" style="text;html=1;whiteSpace=wrap;'
                     'align=left;verticalAlign=middle;fontSize=12;fontColor=#334155;'
                     'fillColor=#f8fafc;strokeColor=#e2e8f0;spacingLeft=10;spacingRight=10;" '
                     'vertex="1" parent="1">%s</mxCell>'
                     % (attr(html(ov)), _geom(20, oy, snap_up(max(240.0, width - 40)), oh)))
        oy += oh + 2 * GRID
    right, bottom = float(snap_up(width)), float(oy)

    # ---- groups: swimlane containers on the Diagram layer
    layer = {n.id: _layer_of_node(n) for n in view.nodes}
    rects: Dict[str, Tuple[int, int, int, int]] = {}
    for n in view.nodes:
        b = L.boxes.get(n.id) or Box(0.0, 0.0, 120.0, 60.0)
        x, y, w, h = _rect(b)
        y += oy
        if is_actor(n):
            x, w, h = snap(b.cx - ACTOR_W / 2), ACTOR_W, ACTOR_H
        rects[n.id] = (x, y, w, h)
    group_cell: Dict[str, Tuple[str, int, int]] = {}
    for i, g in enumerate(view.groups):
        gb = L.groups.get(g.id)
        if gb is None:  # not drawn in the SVG either (no members, or a job/card level)
            continue
        x0, y0 = snap_down(gb.x), snap_down(gb.y) + oy
        x1, y1 = snap_up(gb.right), snap_up(gb.bottom) + oy
        for n in view.nodes:  # the snapped members stay inside
            if n.group == g.id and layer[n.id] == LAYER_DIAGRAM:
                x, y, w, h = rects[n.id]
                x0, y0 = min(x0, x - GRID), min(y0, y - 3 * GRID)
                x1, y1 = max(x1, x + w + GRID), max(y1, y + h + GRID)
        c = g.color or REPO_COLORS[i % len(REPO_COLORS)]
        cid = "g%d" % i
        group_cell[g.id] = (cid, x0, y0)
        title = group_title(g.id, g.label)
        cell = ('<mxCell style="swimlane;startSize=24;html=1;whiteSpace=wrap;collapsible=0;'
                'rounded=1;arcSize=8;dashed=1;dashPattern=6 4;fillColor=%s;'
                'swimlaneFillColor=%s;strokeColor=%s;fontColor=%s;fontStyle=1;align=left;'
                'spacingLeft=10;%s" vertex="1" parent="1">%s</mxCell>'
                % (tint(c, 0.2), tint(c, 0.06), c, _shade(c), sk,
                   _geom(x0, y0, x1 - x0, y1 - y0)))
        cells.append(_object(cid, html(title), (("kind", "group"),), cell))
        right, bottom = max(right, x1), max(bottom, y1)

    # ---- boxes
    node_cell: Dict[str, str] = {}
    parent_of: Dict[str, str] = {}
    for i, n in enumerate(view.nodes):
        cid = "n%d" % i
        node_cell[n.id] = cid
        x, y, w, h = rects[n.id]
        right, bottom = max(right, x + w), max(bottom, y + h)
        parent = layer[n.id]
        if parent == LAYER_DIAGRAM and n.group in group_cell:
            parent, gx, gy = group_cell[n.group]
            x, y = x - gx, y - gy
        parent_of[n.id] = parent
        lk = missing_look(n) if n.kind == "missing" else look(n)
        name, tech, details = lines(n)
        data: List[Tuple[str, str]] = [("kind", real_kind(n))]
        if tech:
            data.append(("technology", tech))
        if n.status:
            data.append(("status", n.status))
        ev = _node_evidence(n, nodes)
        if ev:
            data.append(("evidence", ev))
        if n.members:
            shown = list(n.members[:EVIDENCE_MAX])
            if len(n.members) > EVIDENCE_MAX:
                shown.append("+%d more" % (len(n.members) - EVIDENCE_MAX))
            data.append(("files", "; ".join(shown)))
        url = node_href(view, n)
        if url:  # draw.io opens an object's ``link`` when the box is clicked
            data.append(("link", url))
        cell = '<mxCell style="%s" vertex="1" parent="%s">%s</mxCell>' % (
            _vertex_style(n, lk, sketch), parent, _geom(x, y, w, h))
        cells.append(_object(cid, node_label(name, tech, details, lk), data, cell))

    # ---- lines: connectors with no waypoints
    present: List[str] = []
    for i, e in enumerate(view.edges):
        style = line_style(e.status, e.kind)
        if style not in present:
            present.append(style)
        parent = _layer_of_edge(style, (layer[e.src], layer[e.dst]))
        if parent == LAYER_DIAGRAM and parent_of[e.src] == parent_of[e.dst]:
            parent = parent_of[e.src]  # both ends in one group: the line moves with it
        ports = ""
        route = L.routes[i] if i < len(L.routes) else []
        if len(route) >= 2 and e.src != e.dst:
            out_ = side_of(L.boxes.get(e.src), route[0])
            in_ = side_of(L.boxes.get(e.dst), route[-1])
            if out_:
                ports += "exitX=%s;exitY=%s;exitDx=0;exitDy=0;" % out_
            if in_:
                ports += "entryX=%s;entryY=%s;entryDx=0;entryDy=0;" % in_
        data = [("status", e.status), ("kind", e.kind), ("evidence", _edge_evidence(e)),
                ("reason", _edge_reason(e))]
        if e.number is not None:
            data.append(("step", str(e.number)))
        cell = ('<mxCell style="%s%s%s%s" edge="1" parent="%s" source="%s" target="%s">'
                '<mxGeometry relative="1" as="geometry"/></mxCell>'
                % (EDGE_BASE, EDGE_STYLE[style], ports, sk, parent, node_cell[e.src],
                   node_cell[e.dst]))
        cells.append(_object("e%d" % i, html(edge_text(e)), data, cell))

    # ---- the legend and the notes: one container on the Legend layer
    rows = [(k, label) for k, label in _LEGEND if k in present]
    all_notes = [" ".join(str(s).split()) for s in list(view.notes) + list(L.notes)]
    notes = note_lines(all_notes, min(max(width - 60, 560.0), 900.0))
    if rows or notes:
        inner_w = max([text_width(label, LEGEND_SIZE) + 70 for _, label in rows]
                      + [text_width(s, NOTE_SIZE) + 20 for s in notes] + [160.0])
        lw = snap_up(inner_w + 20)
        notes_h = snap_up(NOTE_LINE * len(notes) + 10) if notes else 0
        lh = 30 + 30 * len(rows) + (notes_h + 10 if notes else 0) + 10
        lx, ly = 30, snap_up(bottom) + 3 * GRID
        cells.append('<mxCell id="legend" value="Legend" style="swimlane;startSize=24;html=1;'
                     'collapsible=0;rounded=1;arcSize=8;fillColor=#f8fafc;'
                     'swimlaneFillColor=#ffffff;strokeColor=#cbd5e1;fontColor=#334155;'
                     'fontSize=11;align=left;spacingLeft=10;" vertex="1" parent="%s">%s</mxCell>'
                     % (LAYER_LEGEND, _geom(lx, ly, lw, lh)))
        y = 30
        for key, label in rows:
            line = EDGE_STYLE[key].split("endArrow=")[0]
            color = line.split("strokeColor=")[1].split(";")[0]
            cells.append('<mxCell id="lg-line-%s" value="" style="line;html=1;%s" vertex="1" '
                         'parent="legend">%s</mxCell>' % (key, line, _geom(10, y, 40, 30)))
            head = "ellipse;" if key == "loose" else "triangle;direction=east;"
            cells.append('<mxCell id="lg-head-%s" value="" style="%shtml=1;fillColor=%s;'
                         'strokeColor=%s;" vertex="1" parent="legend">%s</mxCell>'
                         % (key, head, color, color, _geom(40, y + 10, 10, 10)))
            cells.append('<mxCell id="lg-text-%s" value="%s" style="text;html=1;align=left;'
                         'verticalAlign=middle;fontSize=11;fontColor=#334155;" vertex="1" '
                         'parent="legend">%s</mxCell>'
                         % (key, attr(html(label)), _geom(60, y, lw - 70, 30)))
            y += 30
        if notes:
            cells.append('<mxCell id="notes" value="%s" style="text;html=1;whiteSpace=wrap;'
                         'align=left;verticalAlign=top;fontSize=10;fontColor=#475569;" '
                         'vertex="1" parent="legend">%s</mxCell>'
                         % (attr("<br>".join("\u2022 " + html(s) for s in all_notes)),
                            _geom(10, y + 10, lw - 20, notes_h)))
        right, bottom = max(right, lx + lw), max(bottom, ly + lh)

    page_w = max(PAGE_W, snap_up(right + 3 * GRID))
    page_h = max(PAGE_H, snap_up(bottom + 3 * GRID))
    return ('<mxfile host="archdiag" type="device">\n<diagram id="archdiag" name="%s">\n'
            '<mxGraphModel dx="0" dy="0" grid="1" gridSize="%d" guides="1" tooltips="1" '
            'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="%d" '
            'pageHeight="%d" math="0" shadow="0">\n<root>\n%s\n</root>\n</mxGraphModel>\n'
            '</diagram>\n</mxfile>\n'
            % (attr(view.title), GRID, page_w, page_h, "\n".join(cells)))
