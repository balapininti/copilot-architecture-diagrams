"""Style D: the whiteboard sketch, with an Excalidraw copy.

Looks like diagram 3 of ``docs/samples/mainframe-samples.html`` and option D of
``docs/samples/style-options.html``: a hand-drawn look for walkthroughs and slides. The
samples get their wobble from an SVG filter; Word and PowerPoint drop filters, so here the
wobble is real: every rectangle, ellipse and line is a ``<path>`` whose points are jittered
by +-2px (``random.Random(seed)``), each rectangle edge split into segments of about 30px.

Line types still encode certainty exactly as in Styles A to C (see ``common``): solid
confirmed, dotted orange partly known, red ending in a dot for a loose end, dashed for
shared code. The dash pattern is applied to the jittered path, so a dotted line stays
visibly dotted. Notes and the reasons behind partly known links are yellow sticky notes.

render(view, seed=7) -> {"svg": ..., "excalidraw": ...}. Same view and seed give
byte-identical output.
"""
from __future__ import annotations

import json
import math
import random
from typing import Dict, List, Optional, Sequence, Set, Tuple

from archdiag.layout import Box, Layout, layout_for
from archdiag.render.common import (FONT, LEGEND_SIZE, LINE_COLORS, LOOSE_COLOR,
                                    PARTIAL_COLOR, SHARED_COLOR, _LEGEND,
                                    esc, legend, legend_width, line_style,
                                    loose_dot, note_lines, num, path_d, step_text, svg_doc, text,
                                    text_width, wrap)
from archdiag.render.pills import KEY_LINE, KEY_R, Pill, key_entries, key_svg, marker_svg, place_pills
from archdiag.views import VNode, ViewGraph

D_FONT = "Segoe Print, Comic Sans MS, cursive"
BG = "#fffdf7"
INK = "#1e1e1e"
STROKE_W = 2.2
JITTER = 2.0
SEG = 30.0
PASTELS = ("#a5d8ff", "#b2f2bb", "#d0bfff", "#ffd8a8", "#ffec99", "#fcc2d7")
PASTEL_INK = ("#1971c2", "#2f9e44", "#6741d9", "#d9480f", "#b08400", "#c2255c")
STICKY = "#ffec99"
STICKY_EDGE = "#e8b600"
STICKY_INK = "#5c4400"
TILTS = (-3.0, 2.0, -1.5, 3.0, -2.5, 1.0)  # sticky note rotations, all within +-3 degrees

TITLE_H = 48.0
MAX_TEXT_W = 170.0
LABEL_SIZE, SUB_SIZE, DETAIL_SIZE = 14.0, 11.0, 10.0
LABEL_LINE, SUB_LINE, DETAIL_LINE = 18.0, 14.0, 13.0
PILL_FONT = 11.0
NOTE_SIZE, NOTE_LINE_H = 11.0, 15.0
NOTE_W = 210.0

CYLINDERS = ("table", "dataset", "vsam", "gdg", "datastore")
PIPES = ("queue", "mqprocess")
GREY_KINDS = ("neighbor", "notanalyzed")

_PILL_INK = {"confirmed": "#343a40", "partial": "#b45309", "loose": "#c92a2a",
             "shared_code": "#a16207"}


# ------------------------------------------------------------------ jitter

class Rough:
    """Hand-drawn geometry: every point moves a little, in a fixed order, from one seeded
    generator, so the same drawing calls give the same wobble."""

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)

    def jit(self, amp: float = JITTER) -> float:
        return self.rng.uniform(-amp, amp)

    def shake(self, p: Tuple[float, float], amp: float = JITTER) -> Tuple[float, float]:
        return (p[0] + self.jit(amp), p[1] + self.jit(amp))

    def stroke(self, pts: Sequence[Tuple[float, float]], closed: bool = False,
               amp: float = JITTER, step: float = SEG) -> List[Tuple[float, float]]:
        """``pts`` jittered, each stretch between them split into pieces of about ``step`` px
        with the new points jittered too. A closed outline returns without repeating the
        first point."""
        v = [self.shake(p, amp) for p in pts]
        n = len(v)
        out: List[Tuple[float, float]] = []
        last = n if closed else n - 1
        for k in range(last):
            (x0, y0), (x1, y1) = v[k], v[(k + 1) % n]
            out.append((x0, y0))
            parts = int(math.hypot(x1 - x0, y1 - y0) // step)
            for q in range(1, parts + 1):
                f = q / (parts + 1.0)
                out.append(self.shake((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f), amp * 0.75))
        if not closed:
            out.append(v[-1])
        return out

    def rect(self, x: float, y: float, w: float, h: float, r: float = 0.0
             ) -> List[Tuple[float, float]]:
        """A (rounded) rectangle outline as jittered points."""
        r = min(r, w / 2, h / 2)
        if r <= 0:
            return self.stroke([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)
        c = math.sqrt(0.5) * r
        corners = [((x + w - r, y + r), (1, -1)), ((x + w - r, y + h - r), (1, 1)),
                   ((x + r, y + h - r), (-1, 1)), ((x + r, y + r), (-1, -1))]
        pts: List[Tuple[float, float]] = []
        for (cx, cy), (sx, sy) in corners:  # each corner: edge end, mid-arc, next edge start
            enter = (cx, cy + sy * r) if sx * sy < 0 else (cx + sx * r, cy)
            leave = (cx + sx * r, cy) if sx * sy < 0 else (cx, cy + sy * r)
            pts += [enter, (cx + sx * c, cy + sy * c), leave]
        return self.stroke(pts, True)

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, n: int = 18
                ) -> List[Tuple[float, float]]:
        start = self.rng.uniform(0, math.tau)
        pts = [(cx + rx * math.cos(start + math.tau * k / n),
                cy + ry * math.sin(start + math.tau * k / n)) for k in range(n)]
        return self.stroke(pts, True, amp=1.2, step=1e9)

    def half_ellipse_down(self, cx: float, cy: float, rx: float, ry: float, n: int = 8
                          ) -> List[Tuple[float, float]]:
        """The lower half, left to right."""
        pts = [(cx - rx * math.cos(math.pi * k / n), cy + ry * math.sin(math.pi * k / n))
               for k in range(n + 1)]
        return self.stroke(pts, False, amp=1.0, step=1e9)


def _d(pts: Sequence[Tuple[float, float]], closed: bool = False) -> str:
    return path_d(pts) + (" Z" if closed else "")


def _shift(pts: Sequence[Tuple[float, float]], ox: float, oy: float) -> List[Tuple[float, float]]:
    return [(x + ox, y + oy) for x, y in pts]


def _shape(d: str, fill: str = "none", opacity: float = 1.0, stroke: str = INK,
           width: float = STROKE_W, dash: str = "") -> str:
    a = ['d="%s"' % d, 'fill="%s"' % fill]
    if fill != "none" and opacity < 1.0:
        a.append('fill-opacity="%s"' % opacity)
    if stroke == "none":
        a.append('stroke="none"')
    else:
        a.append('stroke="%s" stroke-width="%s" stroke-linejoin="round"' % (stroke, num(width)))
    if dash:
        a.append('stroke-dasharray="%s"' % dash)
    return "<path %s/>" % " ".join(a)


# ------------------------------------------------------------------ node text and size

def _real(n: VNode) -> str:
    return n.real_kind or n.kind


class _NodeText:
    def __init__(self, n: VNode) -> None:
        self.label = wrap(n.label, MAX_TEXT_W, LABEL_SIZE)
        self.sub = wrap(n.sublabel, MAX_TEXT_W, SUB_SIZE) if n.sublabel else []
        self.detail: List[str] = []
        for d in n.detail_lines:
            self.detail.extend(wrap(d, MAX_TEXT_W, DETAIL_SIZE))
        widths = [text_width(s, LABEL_SIZE) for s in self.label]
        widths += [text_width(s, SUB_SIZE) for s in self.sub]
        widths += [text_width(s, DETAIL_SIZE) for s in self.detail]
        self.width = max(widths) if widths else 0.0
        self.height = (LABEL_LINE * len(self.label) + SUB_LINE * len(self.sub)
                       + (3 + DETAIL_LINE * len(self.detail) if self.detail else 0))

    def plain(self) -> str:
        return "\n".join(self.label + self.sub + self.detail)


def node_size(n: VNode) -> Tuple[float, float]:
    t = _NodeText(n)
    w = max(124.0, t.width * 1.05 + 28)
    if n.kind == "person":
        return max(100.0, t.width + 20), 62 + t.height + 6
    if n.kind in CYLINDERS:
        return w, max(78.0, t.height + 44)
    if n.kind in PIPES:
        return w + 24, max(58.0, t.height + 26)
    if n.kind == "missing":
        return w, max(46.0, t.height + 22)
    return w, max(66.0, t.height + 26)


def _group_index(view: ViewGraph) -> Dict[str, int]:
    return {g.id: i for i, g in enumerate(view.groups)}


def _tilt(i: int) -> float:
    return TILTS[i % len(TILTS)]


# ------------------------------------------------------------------ SVG pieces

def _text_block(t: _NodeText, cx: float, top: float, ink: str, sub_ink: str) -> str:
    parts: List[str] = []
    y = top
    for s in t.label:
        y += LABEL_LINE
        parts.append(text(cx, y - 4, s, LABEL_SIZE, ink, "middle"))
    for s in t.sub:
        y += SUB_LINE
        parts.append(text(cx, y - 3, s, SUB_SIZE, sub_ink, "middle"))
    if t.detail:
        y += 3
    for s in t.detail:
        y += DETAIL_LINE
        parts.append(text(cx, y - 3, s, DETAIL_SIZE, "#495057", "middle"))
    return "".join(parts)


def _node_svg(R: Rough, n: VNode, b: Box, idx: Optional[int], grouped: bool, i: int,
              ox: float, oy: float) -> str:
    t = _NodeText(n)
    x, y, w, h = b.x + ox, b.y + oy, b.w, b.h
    cx = x + w / 2
    pastel = PASTELS[(idx if idx is not None else i) % len(PASTELS)]
    ink_sub = PASTEL_INK[(idx if idx is not None else i) % len(PASTEL_INK)]
    fill, op = ("#ffffff", 0.9) if grouped else (pastel, 0.5)
    parts: List[str] = []
    top = y + (h - t.height) / 2
    k = n.kind

    if k == "person":
        hx, hy = cx, y + 12
        parts.append(_shape(_d(R.ellipse(hx, hy, 10, 10), True)))
        body = [[(hx, hy + 10), (hx, y + 40)], [(hx, y + 22), (hx - 17, y + 34)],
                [(hx, y + 22), (hx + 17, y + 34)], [(hx, y + 40), (hx - 14, y + 58)],
                [(hx, y + 40), (hx + 14, y + 58)]]
        parts.append(_shape(" ".join(_d(R.stroke(s, False, amp=1.2)) for s in body)))
        parts.append(_text_block(t, cx, y + 60, INK, ink_sub))
        return "<g>%s</g>" % "".join(parts)

    if k in CYLINDERS:
        ry = 11.0
        rx = w / 2 - 2
        left, right = x + 2, x + w - 2
        side = R.stroke([(left, y + ry), (left, y + h - ry)], False, amp=1.2)
        base = R.half_ellipse_down(cx, y + h - ry, rx, ry)
        up = R.stroke([(right, y + h - ry), (right, y + ry)], False, amp=1.2)
        parts.append(_shape(_d(side + base + up, True), fill, op))
        parts.append(_shape(_d(R.ellipse(cx, y + ry, rx, ry, 22), True), fill, min(1.0, op + 0.15)))
        parts.append(_text_block(t, cx, y + ry * 2 + (h - ry * 3 - t.height) / 2 - 1, INK, ink_sub))
        return "<g>%s</g>" % "".join(parts)

    if k in PIPES:
        ex = 11.0
        l, r_ = x + ex, x + w - ex
        parts.append(_shape(_d(R.stroke([(l, y), (r_, y), (r_, y + h), (l, y + h)], True)),
                            fill, op))
        parts.append(_shape(_d(R.ellipse(l, y + h / 2, ex, h / 2), True), fill, op))
        parts.append(_shape(_d(R.ellipse(r_, y + h / 2, ex, h / 2), True), "#fff3bf", 0.9))
        parts.append(_text_block(t, cx, top, INK, ink_sub))
        return "<g>%s</g>" % "".join(parts)

    if k == "missing":
        partial = n.status == "partial"
        ink = "#b45309" if partial else "#c92a2a"
        g = '<g transform="rotate(%s %s %s)">' % (num(_tilt(i)), num(cx), num(y + h / 2))
        parts.append(g)
        parts.append(_shape(_d(R.rect(x, y, w, h, 0), True), STICKY, 1.0, STICKY_EDGE, 1.4))
        parts.append(_text_block(t, cx, top, ink, ink))
        parts.append("</g>")
        return "".join(parts)

    if k == "map":
        parts.append(_shape(_d(R.rect(x, y, w, h, 6), True), "#2b8a3e", 0.85))
        parts.append(_text_block(t, cx, top, "#ebfbee", "#ebfbee").replace('fill="#495057"',
                                                                         'fill="#ebfbee"'))
        return "<g>%s</g>" % "".join(parts)

    if k in GREY_KINDS or k == "external":
        parts.append(_shape(_d(R.rect(x, y, w, h, 8), True), "#f1f3f5", 0.9, "#868e96"))
        parts.append(_text_block(t, cx, top, "#495057", "#868e96"))
        return "<g>%s</g>" % "".join(parts)

    parts.append(_shape(_d(R.rect(x, y, w, h, 8), True), fill, op))
    parts.append(_text_block(t, cx, top, INK, ink_sub))
    return "<g>%s</g>" % "".join(parts)


def _chevron(R: Rough, prev: Tuple[float, float], tip: Tuple[float, float]
             ) -> Tuple[List[Tuple[float, float]], Tuple[float, float]]:
    """The two strokes of a hand-drawn arrowhead at ``tip``, and where the line should stop."""
    dx, dy = tip[0] - prev[0], tip[1] - prev[1]
    d = math.hypot(dx, dy) or 1.0
    ux, uy = dx / d, dy / d
    L, half = 11.0, 5.5
    bx, by = tip[0] - ux * L, tip[1] - uy * L
    a = (bx - uy * half + R.jit(0.8), by + ux * half + R.jit(0.8))
    c = (bx + uy * half + R.jit(0.8), by - ux * half + R.jit(0.8))
    stop = (tip[0] - ux * 5, tip[1] - uy * 5)
    return [a, tip, c], stop


def _edge_attrs(style: str) -> Tuple[str, float, str]:
    """(stroke color, width, dasharray) of a line type: the same colors and patterns as the
    legend and every other style. Box outlines are ink; lines are never ink."""
    color = LINE_COLORS[style]
    dash = {"confirmed": "", "partial": "3 4", "loose": "", "shared_code": "7 4"}[style]
    return color, {"confirmed": STROKE_W, "shared_code": 2.0}.get(style, 2.4), dash


def _edge_svg(R: Rough, i: int, route: Sequence[Tuple[float, float]], style: str,
              ox: float, oy: float) -> str:
    if len(route) < 2:
        return ""
    pts = [(x + ox, y + oy) for x, y in route]
    color, width, dash = _edge_attrs(style)
    k = len(pts) - 2
    tip = pts[-1]
    while k > 0 and abs(pts[k][0] - tip[0]) + abs(pts[k][1] - tip[1]) < 1e-6:
        k -= 1
    if style == "loose":
        body = R.stroke(pts, False, amp=1.5)
        return ('<path id="edge-%d" d="%s" fill="none" stroke="%s" stroke-width="%s" '
                'stroke-linecap="round" stroke-linejoin="round"/>%s'
                % (i, _d(body), color, num(width), loose_dot(tip[0], tip[1])))
    head, stop = _chevron(R, pts[k], tip)
    body = R.stroke(pts[:-1] + [stop], False, amp=1.5)
    out = ('<path id="edge-%d" d="%s" fill="none" stroke="%s" stroke-width="%s" '
           'stroke-linejoin="round"%s/>'
           % (i, _d(body), color, num(width), ' stroke-dasharray="%s"' % dash if dash else ""))
    out += ('<path d="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linecap="round" '
            'stroke-linejoin="round"/>' % (_d(head), color, num(width)))
    return out


def _pill_svg(p: Pill, ox: float, oy: float) -> str:
    x, y = p.x + ox, p.y + oy
    if p.marker:
        return marker_svg(p, x, y, _PILL_INK[p.style], BG)
    parts = ['<rect id="pill-%d" x="%s" y="%s" width="%s" height="%s" rx="5" fill="%s" '
             'fill-opacity="0.92"/>' % (p.i, num(x), num(y), num(p.w), num(p.h), BG)]
    parts.append(p.mark(x, y, _PILL_INK[p.style], BG))
    for k, s in enumerate(p.lines):
        parts.append(text(p.text_cx(x), y + 2.5 + 13.5 * (k + 1) - 3, s, PILL_FONT,
                          _PILL_INK[p.style], "middle"))
    return "".join(parts)


def _edge_text(e) -> str:
    """The pill text (the pill draws the step number itself)."""
    return e.label


def _title_zone(g, gb):
    return (gb[0] + 10, gb[1] + 2, text_width(g.label, 13) + 16, 24)


# ------------------------------------------------------------------ sticky notes

class _Sticky:
    def __init__(self, s: str, i: int) -> None:
        self.lines = wrap(s, NOTE_W - 22, NOTE_SIZE)
        self.w = min(NOTE_W, max(text_width(x, NOTE_SIZE) for x in self.lines) + 22)
        self.h = 14 + NOTE_LINE_H * len(self.lines)
        self.tilt = _tilt(i + 2)
        self.x = self.y = 0.0


def _place_stickies(notes: Sequence[str], x0: float, y0: float, max_w: float
                    ) -> Tuple[List[_Sticky], float]:
    out = [_Sticky(s, i) for i, s in enumerate(notes)]
    x, y, row_h = x0, y0, 0.0
    for s in out:
        if x > x0 and x + s.w > x0 + max_w:
            x, y, row_h = x0, y + row_h + 14, 0.0
        s.x, s.y = x, y
        x += s.w + 16
        row_h = max(row_h, s.h)
    return out, (y + row_h - y0) if out else 0.0


def _sticky_svg(R: Rough, s: _Sticky) -> str:
    cx, cy = s.x + s.w / 2, s.y + s.h / 2
    parts = ['<g transform="rotate(%s %s %s)">' % (num(s.tilt), num(cx), num(cy)),
             _shape(_d(R.rect(s.x, s.y, s.w, s.h, 0), True), STICKY, 1.0, STICKY_EDGE, 1.4)]
    for k, line in enumerate(s.lines):
        parts.append(text(s.x + 10, s.y + 8 + NOTE_LINE_H * (k + 1) - 3, line, NOTE_SIZE,
                          STICKY_INK))
    parts.append("</g>")
    return "".join(parts)


# ------------------------------------------------------------------ the scene

class _Scene:
    """Everything both outputs need, computed once from a view and its layout."""

    def __init__(self, view: ViewGraph) -> None:
        self.view = view
        self.L: Layout = layout_for(view, node_size)
        self.styles = [line_style(e.status, e.kind) for e in view.edges]
        self.routes = [list(r) for r in self.L.routes]
        self.pills = place_pills(view, self.L, self.styles, self.routes, _edge_text, _title_zone)
        pills = self.pills
        min_x = min([p.x for p in pills] + [0.0])
        min_y = min([p.y for p in pills] + [0.0])
        self.ox = max(0.0, 14 - min_x) if min_x < 14 else 0.0
        self.oy = TITLE_H + (max(0.0, 14 - min_y) if min_y < 14 else 0.0)
        content_w = max([self.L.width] + [p.x + p.w + 14 for p in pills]) + self.ox
        content_h = max([self.L.height] + [p.y + p.h + 14 for p in pills]) + self.oy
        self.present: Set[str] = set(self.styles)
        title_w = text_width(view.title, 18) + 60
        self.width = max(content_w, legend_width(self.present) + 60, title_w, 360.0)
        self.key_y = content_h + 6
        self.key, key_h = key_svg(pills, 30, self.key_y, self.width - 60, _PILL_INK)
        self.leg_y = content_h + 6 + (key_h + 10 if key_h else 0)
        self.leg, leg_h = legend(30, self.leg_y, self.present)
        notes_y = self.leg_y + leg_h + (14 if leg_h else 0)
        self.notes = view.notes + self.L.notes
        self.stickies, notes_h = _place_stickies(self.notes, 30, notes_y + 4,
                                                  max(self.width - 60, 560.0))
        self.width = max([self.width] + [s.x + s.w + 30 for s in self.stickies])
        self.height = notes_y + (notes_h + 28 if self.notes else 4)
        self.gidx = _group_index(view)

    def lane(self) -> Optional[Tuple[float, float, float, float]]:
        lane = [self.L.boxes[n.id] for n in self.view.nodes
                if n.row == "lane" and n.id in self.L.boxes]
        if not lane:
            return None
        x0 = min(b.x for b in lane) - 12 + self.ox
        y0 = min(b.y for b in lane) - 8 + self.oy
        return x0, y0, max(b.right for b in lane) + 12 + self.ox - x0, \
            max(b.bottom for b in lane) + 8 + self.oy - y0


def _svg(S: _Scene, seed: int) -> str:
    R = Rough(seed)
    view, L, ox, oy = S.view, S.L, S.ox, S.oy
    body: List[str] = [text(24, 32, view.title, 18, INK, weight="")]
    for g in view.groups:
        gb = L.groups.get(g.id)
        if gb is None:
            continue
        k = S.gidx[g.id]
        body.append(_shape(_d(R.rect(gb.x + ox, gb.y + oy, gb.w, gb.h, 10), True),
                           PASTELS[k % len(PASTELS)], 0.5))
        body.append(text(gb.x + ox + 14, gb.y + oy + 19, g.label, 13, PASTEL_INK[k % 6]))
    lane = S.lane()
    if lane:
        body.append(_shape(_d(R.rect(*lane, 16), True), "#f1f3f5", 0.6, "#adb5bd", 1.6))
    for i, e in enumerate(view.edges):
        if i < len(S.routes):
            body.append(_edge_svg(R, i, S.routes[i], S.styles[i], ox, oy))
    for i, n in enumerate(view.nodes):
        b = L.boxes.get(n.id)
        if b is None:
            continue
        grouped = n.group in L.groups and n.group is not None
        idx = S.gidx.get(n.group or "")
        body.append(_node_svg(R, n, b, idx, grouped, i, ox, oy))
    body.extend(_pill_svg(p, ox, oy) for p in S.pills)
    body.append(S.key)
    body.append(S.leg)
    body.extend(_sticky_svg(R, s) for s in S.stickies)
    doc = svg_doc(S.width, S.height, "".join(body), BG, view.title)
    return doc.replace('font-family="%s"' % FONT, 'font-family="%s"' % D_FONT, 1)


# ------------------------------------------------------------------ Excalidraw

class _Ex:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed * 7919 + 1)
        self.els: List[dict] = []
        self.by_id: Dict[str, dict] = {}

    def base(self, eid: str, typ: str, x: float, y: float, w: float, h: float, **kw) -> dict:
        e = {"id": eid, "type": typ, "x": round(x, 1), "y": round(y, 1), "width": round(w, 1),
             "height": round(h, 1), "angle": 0, "strokeColor": INK, "backgroundColor": "transparent",
             "fillStyle": "solid", "strokeWidth": 2, "strokeStyle": "solid", "roughness": 1,
             "opacity": 100, "groupIds": [], "frameId": None, "roundness": None,
             "seed": self.rng.randint(1, 2 ** 31 - 1), "version": 1,
             "versionNonce": self.rng.randint(1, 2 ** 31 - 1), "isDeleted": False,
             "boundElements": [], "updated": 1, "link": None, "locked": False}
        e.update(kw)
        self.els.append(e)
        self.by_id[eid] = e
        return e

    def box(self, eid: str, typ: str, x: float, y: float, w: float, h: float, bg: str,
            stroke: str = INK, angle_deg: float = 0.0, rounded: bool = True,
            style: str = "solid") -> dict:
        return self.base(eid, typ, x, y, w, h, backgroundColor=bg, strokeColor=stroke,
                         strokeStyle=style, angle=round(math.radians(angle_deg), 4),
                         roundness={"type": 3} if rounded and typ == "rectangle" else None)

    def label(self, eid: str, x: float, y: float, s: str, size: float, color: str = INK,
              container: Optional[str] = None, align: str = "left", w: Optional[float] = None,
              h: Optional[float] = None, angle_deg: float = 0.0) -> dict:
        lines = s.split("\n")
        tw = w if w is not None else max(text_width(t, size) for t in lines)
        th = h if h is not None else size * 1.25 * len(lines)
        e = self.base(eid, "text", x, y, tw, th, strokeColor=color, text=s, originalText=s,
                      fontSize=size, fontFamily=1, textAlign=align,
                      verticalAlign="middle" if container else "top", containerId=container,
                      lineHeight=1.25, baseline=round(size), autoResize=container is None,
                      angle=round(math.radians(angle_deg), 4))
        if container:
            self.by_id[container]["boundElements"].append({"id": eid, "type": "text"})
        return e


def _excalidraw(S: _Scene, seed: int) -> str:
    X = _Ex(seed)
    view, L, ox, oy = S.view, S.L, S.ox, S.oy
    X.label("title", 24, 12, view.title, 20)
    for g in view.groups:
        gb = L.groups.get(g.id)
        if gb is None:
            continue
        k = S.gidx[g.id]
        X.box("grp-%d" % k, "rectangle", gb.x + ox, gb.y + oy, gb.w, gb.h,
              PASTELS[k % len(PASTELS)])
        X.label("grp-%d-title" % k, gb.x + ox + 12, gb.y + oy + 4, g.label, 14,
                PASTEL_INK[k % 6])
    lane = S.lane()
    if lane:
        X.box("lane", "rectangle", *lane, "#f1f3f5", "#adb5bd")
    node_el: Dict[str, str] = {}
    for i, n in enumerate(view.nodes):
        b = L.boxes.get(n.id)
        if b is None:
            continue
        t = _NodeText(n)
        eid = "node-%d" % i
        node_el[n.id] = eid
        x, y = b.x + ox, b.y + oy
        grouped = n.group in L.groups and n.group is not None
        idx = S.gidx.get(n.group or "", i)
        pastel = PASTELS[idx % len(PASTELS)]
        if n.kind == "person":  # invisible box to bind lines to, a stick figure on it
            X.box(eid, "rectangle", x, y, b.w, b.h, "transparent", "transparent", rounded=False)
            cx = x + b.w / 2
            X.box(eid + "-head", "ellipse", cx - 10, y + 2, 20, 20, "transparent")
            X.base(eid + "-body", "line", cx, y + 22, 0, 0, points=[[0, 0], [0, 18], [-17, 12],
                   [0, 18], [17, 12], [0, 18], [-14, 36], [0, 18], [14, 36]],
                   startArrowhead=None, endArrowhead=None, lastCommittedPoint=None)
            X.by_id[eid + "-body"].update(width=34, height=36)
            X.label(eid + "-text", x, y + 60, t.plain(), 14, align="center", w=b.w)
            continue
        if n.kind == "missing":
            partial = n.status == "partial"
            X.box(eid, "rectangle", x, y, b.w, b.h, STICKY, STICKY_EDGE, _tilt(i), False)
            X.label(eid + "-text", x + 6, y + 6, t.plain(), 13, "#b45309" if partial else "#c92a2a",
                    container=eid, align="center", w=b.w - 12, h=b.h - 12, angle_deg=_tilt(i))
            continue
        if n.kind == "map":
            bg, stroke, ink = "#2b8a3e", INK, "#ebfbee"
        elif n.kind in GREY_KINDS or n.kind == "external":
            bg, stroke, ink = "#f1f3f5", "#868e96", "#495057"
        else:
            bg, stroke, ink = ("#ffffff" if grouped else pastel), INK, INK
        if n.kind in PIPES:
            bg = "#fff3bf"
        X.box(eid, "rectangle", x, y, b.w, b.h, bg, stroke)
        if n.kind in CYLINDERS:
            X.box(eid + "-cap", "ellipse", x, y, b.w, 22, "transparent", stroke)  # outline only: never hides the label
        X.label(eid + "-text", x + 6, y + 6, t.plain(), 14, ink, container=eid, align="center",
                w=b.w - 12, h=b.h - 12)
    for i, e in enumerate(view.edges):
        route = S.routes[i] if i < len(S.routes) else []
        if len(route) < 2 or e.src not in node_el or e.dst not in node_el:
            continue
        pts = [(x + ox, y + oy) for x, y in route]
        style = S.styles[i]
        color = _edge_attrs(style)[0]
        stroke_style = {"partial": "dotted", "shared_code": "dashed"}.get(style, "solid")
        x0, y0 = pts[0]
        rel = [[round(px - x0, 1), round(py - y0, 1)] for px, py in pts]
        xs, ys = [p[0] for p in rel], [p[1] for p in rel]
        aid = "arrow-%d" % i
        a = X.base(aid, "arrow", x0, y0, max(xs) - min(xs), max(ys) - min(ys),
                   strokeColor=color, strokeStyle=stroke_style, points=rel,
                   startArrowhead=None, endArrowhead="circle" if style == "loose" else "arrow",
                   lastCommittedPoint=None,
                   startBinding={"elementId": node_el[e.src], "focus": 0, "gap": 4},
                   endBinding={"elementId": node_el[e.dst], "focus": 0, "gap": 4})
        a["strokeWidth"] = 2
        for nid in (node_el[e.src], node_el[e.dst]):
            X.by_id[nid]["boundElements"].append({"id": aid, "type": "arrow"})
    entries = key_entries(S.pills, S.width - 60)
    if entries:  # the key, as in the SVG
        X.label("key-heading", 30, S.key_y + 1, "Line labels (marked on the lines)", 12,
                "#475569")
    for p, lines, dx, row in entries:
        X.label("key-%d" % p.key, 30 + dx, S.key_y + 18 + KEY_LINE * row + 3,
                "%s %s" % (marker_text(p), "\n".join(lines)), 12, _PILL_INK[p.style])
    for p in S.pills:
        if p.marker:  # just the number on the line; the label is in the key
            X.label("label-%d" % p.i, p.x + ox - 4, p.y + oy + 1, marker_text(p), 11,
                    _PILL_INK[p.style], align="center", w=p.w + 8)
            continue
        lines = list(p.lines)
        if p.number is not None:  # text only here: the number written as in draw.io
            lines = [(step_text(p.number) + " " + (lines[0] if lines else "")).strip()] \
                + lines[1:]
        X.label("label-%d" % p.i, p.x + ox + 7, p.y + oy + 2.5, "\n".join(lines), 12,
                _PILL_INK[p.style], align="center", w=max(p.w - 14, 30.0))
    cx = 30.0  # the legend: one short line per type present, as in the SVG
    cy = S.leg_y + 9
    for key, lab in _LEGEND:
        if key not in S.present:
            continue
        length = 36.0 if key == "loose" else 44.0
        color = LINE_COLORS[key]
        style = {"partial": "dotted", "shared_code": "dashed"}.get(key, "solid")
        ln = X.base("legend-%s" % key, "line", cx, cy, length, 0, strokeColor=color,
                    strokeStyle=style, points=[[0, 0], [length, 0]], startArrowhead=None,
                    endArrowhead=None, lastCommittedPoint=None)
        ln["strokeWidth"] = 2
        if key == "loose":
            X.box("legend-loose-dot", "ellipse", cx + 34, cy - 6, 12, 12, color, color)
        X.label("legend-%s-text" % key, cx + 54, cy - 7, lab, 12, "#334155")
        cx += 54 + text_width(lab, LEGEND_SIZE) + 24
    for k, s in enumerate(S.stickies):
        sid = "note-%d" % k
        X.box(sid, "rectangle", s.x, s.y, s.w, s.h, STICKY, STICKY_EDGE, s.tilt, False)
        X.label(sid + "-text", s.x + 6, s.y + 6, "\n".join(s.lines), 12, STICKY_INK,
                container=sid, align="left", w=s.w - 12, h=s.h - 12, angle_deg=s.tilt)
    doc = {"type": "excalidraw", "version": 2, "source": "archdiag", "elements": X.els,
           "appState": {"viewBackgroundColor": BG}}
    return json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


# ------------------------------------------------------------------ entry point

def marker_text(p: Pill) -> str:
    """A marker written as text: ``(n)`` for a numbered step (the SVG's circle), ``[n]``
    for any other line (the SVG's square)."""
    return "(%d)" % p.key if p.number is not None else "[%d]" % p.key


def render(view: ViewGraph, seed: int = 7) -> Dict[str, str]:
    """The whiteboard SVG and its Excalidraw file, from one layout of ``view``."""
    S = _Scene(view)
    return {"svg": _svg(S, seed), "excalidraw": _excalidraw(S, seed)}
