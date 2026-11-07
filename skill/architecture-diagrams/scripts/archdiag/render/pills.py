"""Edge-label pills and line drawing, shared by the styles that draw routed lines.

A label sits on an opaque pill placed where it covers no box, no other pill and no line end;
the canvas grows to hold every pill (Ruling 6). Both Style A and Style B call these.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from archdiag.layout import Layout
from archdiag.render.common import (arrowhead, line_attrs, line_color, loose_dot, num, path_d,
                                    text, text_width, wrap)
from archdiag.views import ViewGraph

PILL_SIZE, PILL_LINE = 10.5, 13.5
PILL_MAX_W = 230.0
ARROW_LEN = 10.0

_PILL_STROKE = {"confirmed": "#cbd5e1", "partial": "#fcd34d", "loose": "#fca5a5",
                "shared_code": "#fde68a"}
_PILL_TEXT = {"confirmed": "#334155", "partial": "#b45309", "loose": "#b91c1c",
              "shared_code": "#a16207"}


class Pill:
    def __init__(self, i: int, s: str, at: Tuple[float, float], style: str,
                 max_w: float = PILL_MAX_W) -> None:
        self.i = i
        self.lines = [w for part in s.split("\n") for w in wrap(part, max_w, PILL_SIZE)]
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


def seg_at(route: List[Tuple[float, float]], t: float
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
PARALLEL_NEAR = 40.0  # no pill beside a line where another line runs this close
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


def _crowded(at: Tuple[float, float], horizontal: bool, own: int,
             routes: List[List[Tuple[float, float]]]) -> bool:
    """Is another line running alongside within PARALLEL_NEAR px of this spot?"""
    px, py = at
    for k, r in enumerate(routes):
        if k == own:
            continue
        for (x0, y0), (x1, y1) in zip(r, r[1:]):
            if horizontal and abs(y0 - y1) < 1e-6 and min(x0, x1) <= px <= max(x0, x1) \
                    and abs(y0 - py) < PARALLEL_NEAR:
                return True
            if not horizontal and abs(x0 - x1) < 1e-6 and min(y0, y1) <= py <= max(y0, y1) \
                    and abs(x0 - px) < PARALLEL_NEAR:
                return True
    return False


def _candidates(route: List[Tuple[float, float]], probe: "Pill", own: int = -1,
                routes: Optional[List[List[Tuple[float, float]]]] = None
                ) -> List[Tuple[float, float]]:
    """Pill centers to try: on the last segment (where the line enters its target) when it
    has room, then along the line from the middle out, then beside the line where no
    other line runs alongside (a pill there could read as the other line's)."""
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
    on = [seg_at(route, t) for t in _PILL_SPOTS]
    out.extend(p for p, _ in on)
    for (px, py), (ux, uy) in on:
        if routes is not None and _crowded((px, py), abs(ux) >= abs(uy), own, routes):
            continue
        if abs(ux) >= abs(uy):  # horizontal stretch: above, then below
            off = probe.h / 2 + MARKER_R + 4
            out += [(px, py - off), (px, py + off)]
        else:  # vertical stretch: right, then left
            off = probe.w / 2 + MARKER_R + 4
            out += [(px + off, py), (px - off, py)]
    return out


Rect = Tuple[float, float, float, float]


def place_pills(view: ViewGraph, L: Layout, styles: List[str],
                routes: List[List[Tuple[float, float]]],
                edge_text: Callable[[object], str],
                title_zone: Callable[[object, Rect], Optional[Rect]]) -> List["Pill"]:
    """One pill per labeled line, at the first candidate spot that covers no box, no
    other pill and no line end (arrowhead, dot or last stretch); else the spot covering
    least. A line into a missing box whose label only repeats the box's own words gets
    no pill. ``edge_text(edge)`` is the pill text (``\\n`` starts a new line);
    ``title_zone(group, group_box)`` is the rectangle the style draws the group's title in."""
    by_id = {n.id: n for n in view.nodes}
    obstacles = [(b.x, b.y, b.w, b.h) for b in L.boxes.values()]
    for r in routes:
        obstacles.extend(end_zones(r))
    for g in view.groups:  # group titles
        gb = L.groups.get(g.id)
        if gb is not None:
            z = title_zone(g, (gb.x, gb.y, gb.w, gb.h))
            if z is not None:
                obstacles.append(z)
    pills: List[Pill] = []
    for i, e in enumerate(view.edges):
        s = edge_text(e)
        if not s or i >= len(L.label_at):
            continue
        dst = by_id.get(e.dst)
        if (e.number is None and dst is not None and dst.kind == "missing"
                and e.label.strip() == dst.label.strip()):
            continue
        route = routes[i] if i < len(routes) else []
        best, best_cost = None, None
        # the label on one line where it fits; on a short line, wrapped narrower
        for max_w in (PILL_MAX_W, 84.0, 56.0):
            probe = Pill(i, s, (0.0, 0.0), styles[i], max_w)
            for at in _candidates(route, probe, i, routes) or [L.label_at[i]]:
                p = Pill(i, s, at, styles[i], max_w)
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


def edge_svg(i: int, route: List[Tuple[float, float]], style: str, status: str, kind: str,
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
