"""Style A: pictorial icons grouped by repo or application, with a ``.drawio`` copy.

Looks like diagram 2 of ``docs/samples/mainframe-samples.html`` and option A of
``docs/samples/style-options.html``: a picture per kind of thing, its name in bold and a
grey line under it, groups as dashed rounded rectangles in the group color, numbered steps
on the lines. Labels sit on opaque pills and the canvas grows to hold them; the legend
(only the line types drawn) and the notes go at the bottom.

render(view) -> {"svg": ..., "drawio": ...}. Both come from the same Layout.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from archdiag.layout import Box, Layout, layout_for
from archdiag.render.common import (FIXED_COLOR_KINDS, ICON_H, ICONS, LOOSE_COLOR, PARTIAL_COLOR,
                                    REPO_COLORS, arrowhead, esc, legend, legend_width,
                                    line_attrs, line_color, line_style, loose_dot, notes_block,
                                    notes_height, num, path_d, svg_doc, text, text_width, tint,
                                    wrap)
from archdiag.views import VNode, ViewGraph

MIN_W, MIN_H = 120.0, 110.0
MAX_TEXT_W = 170.0         # label text wraps at this width
LABEL_SIZE, LABEL_LINE = 12.5, 15.0
SUB_SIZE, SUB_LINE = 10.0, 13.0
DETAIL_SIZE, DETAIL_LINE = 10.0, 13.0
TOP_PAD = 6.0              # box top to icon area
ICON_GAP = 8.0             # icon area to first label line
PILL_SIZE, PILL_LINE = 10.5, 13.5
PILL_MAX_W = 230.0
TITLE_H = 44.0
ARROW_LEN = 10.0

_PILL_STROKE = {"confirmed": "#cbd5e1", "partial": "#fcd34d", "loose": "#fca5a5",
                "shared_code": "#fde68a"}
_PILL_TEXT = {"confirmed": "#334155", "partial": "#b45309", "loose": "#b91c1c",
              "shared_code": "#a16207"}


def circled(n: Optional[int]) -> str:
    """``①``…``⑳`` for 1-20, then ``(21)``; empty for no number."""
    if n is None:
        return ""
    if 1 <= n <= 20:
        return chr(0x2460 + n - 1)
    return "(%d)" % n


def shade(color: str) -> str:
    """A darker shade of a group color, for its title."""
    c = color.lstrip("#")
    try:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except (ValueError, IndexError):
        return "#334155"
    return "#%02x%02x%02x" % (int(r * 0.7), int(g * 0.7), int(b * 0.7))


# ------------------------------------------------------------------ node text and size

class _NodeText:
    def __init__(self, n: VNode) -> None:
        mono = n.kind == "repo"
        self.label = wrap(n.label, MAX_TEXT_W, LABEL_SIZE)
        self.sub = wrap(n.sublabel, MAX_TEXT_W, SUB_SIZE) if n.sublabel else []
        self.detail: List[Tuple[str, bool]] = []  # (line, highlighted)
        for i, d in enumerate(n.detail_lines):
            for s in wrap(d, MAX_TEXT_W, DETAIL_SIZE, mono=mono):
                self.detail.append((s, i < n.highlight))
        self.mono = mono
        widths = [text_width(s, LABEL_SIZE) for s in self.label]
        widths += [text_width(s, SUB_SIZE) for s in self.sub]
        widths += [text_width(s, DETAIL_SIZE, mono) for s, _ in self.detail]
        self.width = max(widths) if widths else 0.0
        self.height = (LABEL_LINE * len(self.label) + SUB_LINE * len(self.sub)
                       + (3 + DETAIL_LINE * len(self.detail) if self.detail else 0))


def _has_icon(n: VNode) -> bool:
    return n.kind != "missing"


def node_size(n: VNode) -> Tuple[float, float]:
    """Icon area plus wrapped label, at least 120 x 110. A missing box has no icon (its
    line ends in the dot), so it is only as tall as its text."""
    t = _NodeText(n)
    w = max(MIN_W, t.width + 16)
    if not _has_icon(n):
        return w, max(44.0, t.height + 16)
    return w, max(MIN_H, TOP_PAD + ICON_H + ICON_GAP + t.height + 8)


# ------------------------------------------------------------------ SVG

def _group_colors(view: ViewGraph) -> Dict[str, str]:
    return {g.id: (g.color or REPO_COLORS[i % len(REPO_COLORS)])
            for i, g in enumerate(view.groups)}


def _icon_kind(n: VNode) -> str:
    if n.id.startswith("sysout:"):
        return "sysout"
    return n.kind if n.kind in ICONS else "step"


def _node_color(n: VNode, colors: Dict[str, str]) -> str:
    if n.kind in FIXED_COLOR_KINDS:
        return ""
    return colors.get(n.group or "", "")


def group_title(gid: str, label: str) -> str:
    return "repo: %s" % label if gid.startswith("repo:") else label


def _edge_text(e) -> str:
    num_s = circled(e.number)
    if num_s and e.label:
        return "%s %s" % (num_s, e.label)
    return num_s or e.label


class _Pill:
    def __init__(self, i: int, s: str, at: Tuple[float, float], style: str,
                 max_w: float = PILL_MAX_W) -> None:
        self.i = i
        self.lines = wrap(s, max_w, PILL_SIZE)
        self.w = max(text_width(x, PILL_SIZE) for x in self.lines) + 14
        self.h = 5 + PILL_LINE * len(self.lines)
        self.x = at[0] - self.w / 2
        self.y = at[1] - self.h / 2
        self.style = style

    def svg(self, ox: float, oy: float) -> str:
        x, y = self.x + ox, self.y + oy
        parts = ['<rect id="pill-%d" x="%s" y="%s" width="%s" height="%s" rx="%s" '
                 'fill="#ffffff" stroke="%s" stroke-width="1"/>'
                 % (self.i, num(x), num(y), num(self.w), num(self.h),
                    num(min(9.0, self.h / 2)), _PILL_STROKE[self.style])]
        for k, s in enumerate(self.lines):
            parts.append(text(x + self.w / 2, y + 2.5 + PILL_LINE * (k + 1) - 3.5, s, PILL_SIZE,
                              _PILL_TEXT[self.style], anchor="middle"))
        return "".join(parts)


def _seg_at(route: List[Tuple[float, float]], t: float
            ) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """The point a fraction ``t`` of the way along a polyline, and the unit direction of
    the segment it lies on."""
    segs = [((route[k + 1][0] - route[k][0]) ** 2 + (route[k + 1][1] - route[k][1]) ** 2) ** 0.5
            for k in range(len(route) - 1)]
    left = sum(segs) * t
    for k, d in enumerate(segs):
        if left <= d and d > 0:
            f = left / d
            (x0, y0), (x1, y1) = route[k], route[k + 1]
            return (x0 + (x1 - x0) * f, y0 + (y1 - y0) * f), ((x1 - x0) / d, (y1 - y0) / d)
        left -= d
    return route[-1], (1.0, 0.0)


def _overlap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


_PILL_SPOTS = (0.5, 0.4, 0.6, 0.3, 0.7, 0.22, 0.78, 0.15, 0.85)
END_CLEAR = 14.0   # the last stretch of every line, and its arrowhead or dot, stays uncovered
MARKER_R = 8.0


def end_zones(route: List[Tuple[float, float]]) -> List[Tuple[float, float, float, float]]:
    """Rectangles a pill must not cover: both ends of the line, the last END_CLEAR px
    before its end, and the arrowhead or loose dot there."""
    if len(route) < 2:
        return []
    (x0, y0), (x1, y1) = route[0], route[-1]
    zones = [(x0 - 4, y0 - 4, 8, 8), (x1 - MARKER_R, y1 - MARKER_R, 2 * MARKER_R, 2 * MARKER_R)]
    k = len(route) - 2
    while k > 0 and route[k] == route[-1]:
        k -= 1
    dx, dy = x1 - route[k][0], y1 - route[k][1]
    d = (dx * dx + dy * dy) ** 0.5 or 1.0
    xa, ya = x1 - dx / d * min(END_CLEAR, d), y1 - dy / d * min(END_CLEAR, d)
    zones.append((min(xa, x1) - 3, min(ya, y1) - 3, abs(x1 - xa) + 6, abs(y1 - ya) + 6))
    return zones


def _candidates(route: List[Tuple[float, float]], probe: "_Pill"
                ) -> List[Tuple[float, float]]:
    """Pill centers to try: on the last segment (where the line enters its target) when it
    has room, then along the line from the middle out, then beside the line."""
    out: List[Tuple[float, float]] = []
    if len(route) < 2:
        return out
    (xa, ya), (xb, yb) = route[-2], route[-1]
    seg = ((xb - xa) ** 2 + (yb - ya) ** 2) ** 0.5
    along = probe.w if abs(xb - xa) >= abs(yb - ya) else probe.h
    if seg >= along + END_CLEAR + 2 * MARKER_R:
        f = (seg - END_CLEAR - MARKER_R - along / 2) / seg
        out.append((xa + (xb - xa) * f, ya + (yb - ya) * f))
        out.append((xa + (xb - xa) * 0.5, ya + (yb - ya) * 0.5))
    on = [_seg_at(route, t) for t in _PILL_SPOTS]
    out.extend(p for p, _ in on)
    for (px, py), (ux, uy) in on:
        if abs(ux) >= abs(uy):  # horizontal stretch: above, then below
            off = probe.h / 2 + MARKER_R + 4
            out += [(px, py - off), (px, py + off)]
        else:  # vertical stretch: right, then left
            off = probe.w / 2 + MARKER_R + 4
            out += [(px + off, py), (px - off, py)]
    return out


def place_pills(view: ViewGraph, L: Layout, styles: List[str]) -> List["_Pill"]:
    """One pill per labeled line, at the first candidate spot that covers no box, no
    other pill and no line end (arrowhead, dot or last stretch); else the spot covering
    least. A line into a missing box whose label only repeats the box's own words gets
    no pill."""
    by_id = {n.id: n for n in view.nodes}
    obstacles = [(b.x, b.y, b.w, b.h) for b in L.boxes.values()]
    for r in L.routes:
        obstacles.extend(end_zones(r))
    pills: List[_Pill] = []
    for i, e in enumerate(view.edges):
        s = _edge_text(e)
        if not s or i >= len(L.label_at):
            continue
        dst = by_id.get(e.dst)
        if (e.number is None and dst is not None and dst.kind == "missing"
                and e.label.strip() == dst.label.strip()):
            continue
        route = L.routes[i] if i < len(L.routes) else []
        best, best_cost = None, None
        # the label on one line where it fits; on a short line, wrapped narrower
        for max_w in (PILL_MAX_W, 84.0, 56.0):
            probe = _Pill(i, s, (0.0, 0.0), styles[i], max_w)
            for at in _candidates(route, probe) or [L.label_at[i]]:
                p = _Pill(i, s, at, styles[i], max_w)
                r = (p.x - 3, p.y - 3, p.w + 6, p.h + 6)
                cost = sum(_overlap(r, o) for o in obstacles)
                if best_cost is None or cost < best_cost:
                    best, best_cost = p, cost
                if cost == 0:
                    break
            if best_cost == 0:
                break
        pills.append(best)
        obstacles.append((best.x, best.y, best.w, best.h))
    return pills


def _edge_svg(i: int, route: List[Tuple[float, float]], style: str, status: str, kind: str,
              ox: float, oy: float) -> str:
    pts = [(x + ox, y + oy) for x, y in route]
    if len(pts) < 2:
        return ""
    attrs = line_attrs(status, kind)
    if style == "loose":
        return '<path id="edge-%d" d="%s" %s/>%s' % (i, path_d(pts), attrs,
                                                      loose_dot(pts[-1][0], pts[-1][1]))
    tip = pts[-1]
    k = len(pts) - 2
    while k > 0 and abs(pts[k][0] - tip[0]) + abs(pts[k][1] - tip[1]) < 1e-6:
        k -= 1
    prev = pts[k]
    dx, dy = tip[0] - prev[0], tip[1] - prev[1]
    d = (dx * dx + dy * dy) ** 0.5 or 1.0
    cut = min(ARROW_LEN - 3, d * 0.5)
    body = pts[:-1] + [(tip[0] - dx / d * cut, tip[1] - dy / d * cut)]
    return '<path id="edge-%d" d="%s" %s/>%s' % (i, path_d(body), attrs,
                                                  arrowhead(prev, tip, line_color(status, kind)))


def _node_svg(n: VNode, b: Box, color: str, ends_in_dot: bool, ox: float, oy: float) -> str:
    t = _NodeText(n)
    x, y, cx = b.x + ox, b.y + oy, b.cx + ox
    parts: List[str] = []
    if _has_icon(n):
        parts.append(ICONS[_icon_kind(n)](cx, y + TOP_PAD + ICON_H / 2, color))
        ty = y + TOP_PAD + ICON_H + ICON_GAP
        label_fill, sub_fill = "#0f172a", "#64748b"
        if n.kind in ("neighbor", "notanalyzed"):
            label_fill, sub_fill = "#64748b", "#94a3b8"
    else:
        partial = n.status == "partial"
        label_fill = "#b45309" if partial else LOOSE_COLOR
        sub_fill = label_fill
        ty = b.y + oy + (b.h - t.height) / 2
        if partial:
            parts.append('<rect x="%s" y="%s" width="%s" height="%s" rx="8" fill="#fffbeb" '
                         'stroke="%s" stroke-width="1.5" stroke-dasharray="3 4"/>'
                         % (num(x + 2), num(y + 2), num(b.w - 4), num(b.h - 4), PARTIAL_COLOR))
        elif not ends_in_dot:
            parts.append(ICONS["missing"](x + 8, y + b.h / 2, ""))
    for s in t.label:
        ty += LABEL_LINE
        parts.append(text(cx, ty - 3, s, LABEL_SIZE, label_fill, "middle", "700"))
    for s in t.sub:
        ty += SUB_LINE
        parts.append(text(cx, ty - 2.5, s, SUB_SIZE, sub_fill, "middle"))
    if t.detail:
        ty += 3
    for s, hi in t.detail:
        ty += DETAIL_LINE
        fill = "#0f172a" if hi else ("#475569" if _has_icon(n) else label_fill)
        parts.append(text(cx, ty - 2.5, s, DETAIL_SIZE, fill, "middle", "700" if hi else "",
                          mono=t.mono))
    return "<g>%s</g>" % "".join(parts)


def _lane_svg(view: ViewGraph, L: Layout, ox: float, oy: float) -> str:
    lane = [L.boxes[n.id] for n in view.nodes if n.row == "lane" and n.id in L.boxes]
    if not lane:
        return ""
    x0 = min(b.x for b in lane) - 12 + ox
    y0 = min(b.y for b in lane) - 8 + oy
    x1 = max(b.right for b in lane) + 12 + ox
    y1 = max(b.bottom for b in lane) + 8 + oy
    return ('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="#f8fafc" stroke="#e2e8f0" '
            'stroke-width="1.5"/>' % (num(x0), num(y0), num(x1 - x0), num(y1 - y0),
                                       num(min(42.0, (y1 - y0) / 2))))


def _svg(view: ViewGraph, L: Layout) -> str:
    colors = _group_colors(view)
    styles = [line_style(e.status, e.kind) for e in view.edges]
    pills = place_pills(view, L, styles)

    # grow the canvas so every pill fits (Ruling 6), and leave room for the title
    min_x = min([p.x for p in pills] + [0.0])
    min_y = min([p.y for p in pills] + [0.0])
    ox = max(0.0, 14 - min_x) if min_x < 14 else 0.0
    oy = TITLE_H + (max(0.0, 14 - min_y) if min_y < 14 else 0.0)
    content_w = max([L.width] + [p.x + p.w + 14 for p in pills]) + ox
    content_h = max([L.height] + [p.y + p.h + 14 for p in pills]) + oy

    present: Set[str] = set(styles)
    leg_y = content_h + 6
    leg, leg_h = legend(30, leg_y, present)
    title_w = text_width(view.title, 16) + 60
    width = max(content_w, legend_width(present) + 60, title_w, 360.0)
    note_w = max(width - 60, 560.0)
    width = max(width, note_w + 60)
    notes_y = leg_y + leg_h + (14 if leg_h else 0)
    n_h = notes_height(view.notes, note_w)
    height = notes_y + n_h + (16 if n_h else 4)

    body: List[str] = [text(24, 30, view.title, 16, "#0f172a", weight="700")]
    for g in view.groups:
        gb = L.groups.get(g.id)
        if gb is None:
            continue
        c = colors[g.id]
        body.append('<rect x="%s" y="%s" width="%s" height="%s" rx="12" fill="%s" stroke="%s" '
                    'stroke-width="1.5" stroke-dasharray="6 4"/>'
                    % (num(gb.x + ox), num(gb.y + oy), num(gb.w), num(gb.h), tint(c, 0.08), c))
        body.append(text(gb.x + ox + 14, gb.y + oy + 18, group_title(g.id, g.label), 12,
                         shade(c), weight="700"))
    body.append(_lane_svg(view, L, ox, oy))
    for i, e in enumerate(view.edges):
        if i < len(L.routes):
            body.append(_edge_svg(i, L.routes[i], styles[i], e.status, e.kind, ox, oy))
    dot_ends = {e.dst for e, s in zip(view.edges, styles) if s == "loose"}
    for n in view.nodes:
        b = L.boxes.get(n.id)
        if b is not None:
            body.append(_node_svg(n, b, _node_color(n, colors), n.id in dot_ends, ox, oy))
    body.extend(p.svg(ox, oy) for p in pills)
    body.append(leg)
    body.append(notes_block(view.notes, 30, notes_y, note_w))
    return svg_doc(width, height, "".join(body), title=view.title)


# ------------------------------------------------------------------ draw.io

_SHAPE = {
    "table": "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=8;",
    "dataset": "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=8;",
    "vsam": "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=8;",
    "gdg": "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=8;",
    "datastore": "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=8;",
    "person": "shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;",
    "external": "ellipse;shape=cloud;",
    "job": "shape=document;boundedLbl=1;",
    "cicsfile": "shape=card;size=14;",
    "endpoint": "shape=hexagon;perimeter=hexagonPerimeter2;size=0.12;",
    "queue": "shape=process;size=0.08;rounded=1;",
    "repo": "shape=folder;tabWidth=40;tabHeight=12;tabPosition=left;",
    "missing": "rounded=1;dashed=1;",
    "neighbor": "rounded=1;dashed=1;",
    "notanalyzed": "rounded=1;dashed=1;",
}

_EDGE_STYLE = {
    "confirmed": "strokeColor=#334155;strokeWidth=2;endArrow=block;endFill=1;",
    "partial": ("dashed=1;dashPattern=3 4;strokeColor=#d97706;strokeWidth=2;endArrow=block;"
                "endFill=1;fontColor=#b45309;"),
    "loose": "strokeColor=#dc2626;strokeWidth=2;endArrow=oval;endFill=1;endSize=10;"
             "fontColor=#dc2626;",
    "shared_code": ("dashed=1;dashPattern=7 4;strokeColor=#a16207;strokeWidth=1.6;"
                    "endArrow=block;endFill=1;fontColor=#a16207;"),
}


def _value(lines: List[str]) -> str:
    return "&#xa;".join(esc(s) for s in lines if s)


def _vertex_style(n: VNode, color: str) -> str:
    shape = _SHAPE.get(n.kind, "rounded=1;")
    if n.kind == "missing":
        partial = n.status == "partial"
        c = PARTIAL_COLOR if partial else LOOSE_COLOR
        return shape + "whiteSpace=wrap;html=0;fillColor=%s;strokeColor=%s;fontColor=%s;" % (
            "#fffbeb" if partial else "#fef2f2", c, c)
    if n.kind in ("neighbor", "notanalyzed"):
        return shape + "whiteSpace=wrap;html=0;fillColor=#f8fafc;strokeColor=#94a3b8;" \
                       "fontColor=#64748b;"
    c = color or "#64748b"
    return shape + "whiteSpace=wrap;html=0;fillColor=%s;strokeColor=%s;fontColor=#0f172a;" % (
        tint(c, 0.18), c)


def _geom(x: float, y: float, w: float, h: float) -> str:
    return '<mxGeometry x="%s" y="%s" width="%s" height="%s" as="geometry"/>' % (
        num(x), num(y), num(w), num(h))


def _drawio(view: ViewGraph, L: Layout) -> str:
    colors = _group_colors(view)
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    group_cell: Dict[str, Tuple[str, Box]] = {}
    for i, g in enumerate(view.groups):
        gb = L.groups.get(g.id)
        if gb is None:  # not drawn in the SVG either (no members, or a job/card level)
            continue
        c = colors[g.id]
        cid = "g%d" % i
        group_cell[g.id] = (cid, gb)
        cells.append('<mxCell id="%s" value="%s" style="rounded=1;arcSize=6;dashed=1;'
                     'dashPattern=6 4;container=1;collapsible=0;html=0;fillColor=%s;'
                     'strokeColor=%s;fontColor=%s;fontStyle=1;align=left;verticalAlign=top;'
                     'spacingLeft=10;spacingTop=2;" vertex="1" parent="1">%s</mxCell>'
                     % (cid, esc(group_title(g.id, g.label)), tint(c, 0.08), c, shade(c),
                        _geom(gb.x, gb.y, gb.w, gb.h)))
    node_cell: Dict[str, str] = {}
    for i, n in enumerate(view.nodes):
        b = L.boxes.get(n.id) or Box(0, 0, MIN_W, MIN_H)
        cid = "n%d" % i
        node_cell[n.id] = cid
        parent, px, py = "1", 0.0, 0.0
        if n.group in group_cell:
            parent, gb = group_cell[n.group]
            px, py = gb.x, gb.y
        lines = [n.label, n.sublabel] + list(n.detail_lines)
        cells.append('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="%s">%s</mxCell>'
                     % (cid, _value(lines), _vertex_style(n, _node_color(n, colors)), parent,
                        _geom(b.x - px, b.y - py, b.w, b.h)))
    for i, e in enumerate(view.edges):
        style = _EDGE_STYLE[line_style(e.status, e.kind)]
        route = L.routes[i] if i < len(L.routes) else []
        pts = ""
        if len(route) > 2:
            pts = '<Array as="points">%s</Array>' % "".join(
                '<mxPoint x="%s" y="%s"/>' % (num(x), num(y)) for x, y in route[1:-1])
        ends = ""
        if route:
            ends = ('<mxPoint x="%s" y="%s" as="sourcePoint"/><mxPoint x="%s" y="%s" '
                    'as="targetPoint"/>' % (num(route[0][0]), num(route[0][1]),
                                            num(route[-1][0]), num(route[-1][1])))
        cells.append('<mxCell id="e%d" value="%s" style="edgeStyle=none;rounded=0;html=0;'
                     'labelBackgroundColor=#ffffff;fontSize=10;%s" edge="1" parent="1" '
                     'source="%s" target="%s"><mxGeometry relative="1" as="geometry">%s%s'
                     '</mxGeometry></mxCell>'
                     % (i, esc(_edge_text(e)), style, node_cell[e.src], node_cell[e.dst], ends,
                        pts))
    return ('<mxfile host="archdiag" type="device"><diagram id="archdiag" name="%s">'
            '<mxGraphModel dx="0" dy="0" grid="1" gridSize="10" guides="1" tooltips="1" '
            'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="%s" '
            'pageHeight="%s" math="0" shadow="0"><root>%s</root></mxGraphModel></diagram>'
            '</mxfile>\n' % (esc(view.title), num(L.width), num(L.height), "".join(cells)))


# ------------------------------------------------------------------ entry point

def render(view: ViewGraph) -> Dict[str, str]:
    """The pictorial SVG and its draw.io file, from one layout of ``view``."""
    L = layout_for(view, node_size)
    return {"svg": _svg(view, L), "drawio": _drawio(view, L)}
