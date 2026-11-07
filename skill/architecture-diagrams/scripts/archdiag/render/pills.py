"""Edge-label pills and line drawing, shared by the styles that draw routed lines.

A label sits on an opaque pill placed where it covers no box, no other pill and no line end;
the canvas grows to hold every pill (Ruling 6). Both Style A and Style B call these.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from archdiag.layout import Layout
from archdiag.render.common import (STEP_R, arrowhead, line_attrs, line_color, loose_dot, num,
                                    path_d, step_mark, text, text_width, wrap)
from archdiag.views import ViewGraph

PILL_SIZE, PILL_LINE = 10.5, 13.5
PILL_MAX_W = 230.0
ARROW_LEN = 10.0

_PILL_STROKE = {"confirmed": "#cbd5e1", "partial": "#fcd34d", "loose": "#fca5a5",
                "shared_code": "#fde68a"}
_PILL_TEXT = {"confirmed": "#334155", "partial": "#b45309", "loose": "#b91c1c",
              "shared_code": "#a16207"}


class Pill:
    """A line's label: its text (``\\n`` starts a new line) and, for a numbered step, the
    number drawn as a circle at the left (``step_mark``)."""

    def __init__(self, i: int, s: str, at: Tuple[float, float], style: str,
                 max_w: float = PILL_MAX_W, number: Optional[int] = None) -> None:
        self.i = i
        self.number = number
        self.lines = [w for part in s.split("\n") for w in wrap(part, max_w, PILL_SIZE)] \
            if s else []
        self.num_w = 2 * STEP_R + (4 if self.lines else 0) if number is not None else 0.0
        text_w = max([text_width(x, PILL_SIZE) for x in self.lines] or [0.0])
        self.w = text_w + self.num_w + (14 if self.lines else 6)
        self.h = 5 + PILL_LINE * max(1, len(self.lines))
        self.x = at[0] - self.w / 2
        self.y = at[1] - self.h / 2
        self.style = style
        self.marker = False       # True: drawn as a numbered marker, the text in the key
        self.key: Optional[int] = None

    def as_marker(self, at: Tuple[float, float]) -> "Pill":
        """This label as a small marker centered on ``at`` (its line), keyed later."""
        self.marker = True
        self.w = self.h = 2 * KEY_R + 2
        self.x, self.y = at[0] - self.w / 2, at[1] - self.h / 2
        return self

    def text_cx(self, x: float) -> float:
        """The middle of the text, for a pill whose left edge is at ``x``."""
        return x + self.num_w + (self.w - self.num_w) / 2

    def mark(self, x: float, y: float, ink: str, fill: str = "#ffffff") -> str:
        """The step number's circle, for a pill drawn at ``x``, ``y`` (empty for none)."""
        if self.number is None:
            return ""
        return step_mark(self.number, x + 3 + STEP_R, y + 2.5 + PILL_LINE / 2, ink, fill)

    def svg(self, ox: float, oy: float) -> str:
        x, y = self.x + ox, self.y + oy
        if self.marker:
            return marker_svg(self, x, y, _PILL_TEXT[self.style])
        parts = ['<rect id="pill-%d" x="%s" y="%s" width="%s" height="%s" rx="%s" '
                 'fill="#ffffff" stroke="%s" stroke-width="1"/>'
                 % (self.i, num(x), num(y), num(self.w), num(self.h),
                    num(min(9.0, self.h / 2)), _PILL_STROKE[self.style])]
        parts.append(self.mark(x, y, _PILL_TEXT[self.style]))
        for k, s in enumerate(self.lines):
            parts.append(text(self.text_cx(x), y + 2.5 + PILL_LINE * (k + 1) - 3.5, s,
                              PILL_SIZE, _PILL_TEXT[self.style], anchor="middle"))
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


LINE_PAD = 1.5      # a pill keeps this far off any other line
KEY_R = 8.0         # a marker's radius (circle for a step, rounded square otherwise)
KEY_SIZE, KEY_LINE = 11.0, 20.0
MARK_STEP = 1.0     # markers are tried every this many px along their line
PILL_CLEAR = 8.0    # a pill keeps this far off other lines where its line allows
MARK_CLEAR = 5.0    # a marker keeps this far off other lines where its line allows


def _mark_spots(route: List[Tuple[float, float]]) -> List[float]:
    """Fractions along the line to try a marker at: every MARK_STEP px, middle first,
    keeping off both ends."""
    length = sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
                 for a, b in zip(route, route[1:]))
    if length <= 0:
        return [0.5]
    n = max(1, int(length / MARK_STEP))
    ts = [k / float(n) for k in range(n + 1)]
    ts = [t for t in ts if 0.08 <= t <= 0.92] or [0.5]
    return sorted(ts, key=lambda t: (abs(t - 0.5), t))


def _seg_in_rect(a: Tuple[float, float], b: Tuple[float, float], rect: Rect) -> bool:
    """Does segment a-b pass through the inside of rect (any direction)?"""
    x, y, w, h = rect
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - x), (dx, x + w - a[0]), (-dy, a[1] - y), (dy, y + h - a[1])):
        if abs(p) < 1e-12:
            if q <= 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 >= t1:
                return False
    return t0 < t1


class _Lines:
    """Every line's segments, bucketed on a coarse grid, to ask which lines a rectangle
    lies over."""
    CELL = 80.0

    def __init__(self, routes: List[List[Tuple[float, float]]]) -> None:
        self.cells: dict = {}
        for k, r in enumerate(routes):
            for a, b in zip(r, r[1:]):
                for c in self._cells((min(a[0], b[0]), min(a[1], b[1]),
                                      abs(a[0] - b[0]), abs(a[1] - b[1]))):
                    self.cells.setdefault(c, []).append((k, a, b))

    def _cells(self, rect: Rect):
        x, y, w, h = rect
        for i in range(int(x // self.CELL), int((x + w) // self.CELL) + 1):
            for j in range(int(y // self.CELL), int((y + h) // self.CELL) + 1):
                yield (i, j)

    def others(self, rect: Rect, own: int) -> int:
        """How many segments of other lines pass through ``rect``."""
        seen = set()
        n = 0
        for c in self._cells(rect):
            for item in self.cells.get(c, ()):
                if item[0] != own and id(item) not in seen:
                    seen.add(id(item))
                    if _seg_in_rect(item[1], item[2], rect):
                        n += 1
        return n


def _line_rect(p: "Pill") -> Rect:
    return (p.x - LINE_PAD, p.y - LINE_PAD, p.w + 2 * LINE_PAD, p.h + 2 * LINE_PAD)


def prefer_marker(pill: Tuple[float, float], marker: Tuple[float, float]) -> bool:
    """Does a marker replace the best pill? Costs are (box/end overlap, other-line hits).
    A pill over another line is never kept; otherwise line hits are compared first, so a
    marker touching a line never beats a line-free pill, and on equal (zero) hits the
    one covering less wins (E4)."""
    if pill[1] > 0:
        return True
    return (marker[1], marker[0]) < (pill[1], pill[0])


def place_pills(view: ViewGraph, L: Layout, styles: List[str],
                routes: List[List[Tuple[float, float]]],
                edge_text: Callable[[object], str],
                title_zone: Callable[[object, Rect], Optional[Rect]]) -> List["Pill"]:
    """One pill per labeled line, at the first candidate spot that covers no box, no
    other pill, no line end (arrowhead, dot or last stretch) and no other line, so it
    reads as its own line's label. When no spot on, beside or near the line is free, the
    line gets a small numbered marker on a free stretch instead (a pill set further out
    could be read as another line's label) (``Pill.marker``; its
    step number when it has one, else the next free number, ``Pill.key``) and the label
    goes in the key under the picture (``key_svg``). A line into a missing box whose
    label only repeats the box's own words gets no pill. ``edge_text(edge)`` is the pill
    text (``\\n`` starts a new line), without the step number: the pill draws
    ``edge.number`` itself; ``title_zone(group, group_box)`` is the rectangle the style
    draws the group's title in."""
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
    lines = _Lines(routes)
    pills: List[Pill] = []

    def score(p: Pill) -> Tuple[float, float]:
        r = (p.x - 3, p.y - 3, p.w + 6, p.h + 6)
        return (sum(_overlap(r, o) for o in obstacles), float(lines.others(_line_rect(p), p.i)))

    for i, e in enumerate(view.edges):
        s = edge_text(e)
        if (not s and e.number is None) or i >= len(L.label_at):
            continue
        dst = by_id.get(e.dst)
        if (e.number is None and dst is not None and dst.kind == "missing"
                and e.label.strip() == dst.label.strip()):
            continue
        route = routes[i] if i < len(routes) else []
        best: Optional[Pill] = None
        best_cost: Optional[Tuple[float, float]] = None
        # the label on one line where it fits; on a short line, wrapped narrower. Never
        # further out: a pill away from its line could be read as another line's.
        tries = []
        for max_w in (PILL_MAX_W, 84.0, 56.0):
            probe = Pill(i, s, (0.0, 0.0), styles[i], max_w, e.number)
            tries += [(max_w, at) for at in (_candidates(route, probe, i, routes)
                                             or [L.label_at[i]])]
        best_near = 0.0
        for max_w, at in tries:
            p = Pill(i, s, at, styles[i], max_w, e.number)
            hits = float(lines.others(_line_rect(p), i))
            if best_cost is not None and hits > best_cost[1]:
                continue
            cost = score(p)
            # (E6) then a spot PILL_CLEAR px off every other line: a pill at a crossing
            # could be read as either line's
            near = float(lines.others((p.x - PILL_CLEAR, p.y - PILL_CLEAR,
                                       p.w + 2 * PILL_CLEAR, p.h + 2 * PILL_CLEAR), i))
            if best_cost is None or (cost[1], cost[0], near) < \
                    (best_cost[1], best_cost[0], best_near):
                best, best_cost, best_near = p, cost, near
            if cost == (0.0, 0.0) and near == 0.0:
                break
        if best_cost != (0.0, 0.0) and len(route) >= 2:
            # nowhere free: a marker on a free stretch of the line, the label in the key
            mark_best, mark_cost = None, None
            m = Pill(i, s, (0.0, 0.0), styles[i], PILL_MAX_W, e.number)
            for t in _mark_spots(route):
                m = Pill(i, s, (0.0, 0.0), styles[i], PILL_MAX_W, e.number) \
                    if m is mark_best else m
                m.as_marker(seg_at(route, t)[0])
                hits = float(lines.others(_line_rect(m), i))
                if mark_cost is not None and hits > mark_cost[1]:
                    continue
                # (E1) a spot with MARK_CLEAR px of room to the next line beats one that
                # only just misses it
                near = float(lines.others((m.x - MARK_CLEAR, m.y - MARK_CLEAR,
                                           m.w + 2 * MARK_CLEAR, m.h + 2 * MARK_CLEAR), i))
                r = (m.x - 3, m.y - 3, m.w + 6, m.h + 6)
                cost = (sum(_overlap(r, o) for o in obstacles), hits, near)
                if mark_cost is None or (cost[1], cost[2], cost[0]) < \
                        (mark_cost[1], mark_cost[2], mark_cost[0]):
                    mark_best, mark_cost = m, cost
                if cost == (0.0, 0.0, 0.0):
                    break
            # a pill over another line is never kept: the marker is, crowded or not
            if mark_best is not None and prefer_marker(best_cost, mark_cost[:2]):
                best = mark_best
        pills.append(best)
        obstacles.append((best.x, best.y, best.w, best.h))
    # number the markers: a step keeps its number, others take the next free ones
    nxt = max([e.number for e in view.edges if e.number is not None] or [0])
    for p in pills:
        if p.marker:
            if p.number is not None:
                p.key = p.number
            else:
                nxt += 1
                p.key = nxt
    return pills


def marker_svg(p: "Pill", x: float, y: float, ink: str, fill: str = "#ffffff") -> str:
    """A marker drawn at ``x``, ``y`` (its box's top left): the step circle for a step
    (``<g id="step-N">``), else a small rounded square with the key number
    (``<g id="mark-N">``)."""
    cx, cy = x + p.w / 2, y + p.h / 2
    if p.number is not None:
        return step_mark(p.number, cx, cy, ink, fill)
    return _square(p.key, cx, cy, ink, fill, "mark-%d" % p.key)


def _square(n: int, cx: float, cy: float, ink: str, fill: str, gid: str) -> str:
    return ('<g id="%s"><rect x="%s" y="%s" width="%s" height="%s" rx="3" fill="%s" '
            'stroke="%s" stroke-width="1.3"/>%s</g>'
            % (gid, num(cx - KEY_R), num(cy - KEY_R), num(2 * KEY_R), num(2 * KEY_R), fill,
               ink, text(cx, cy + 3.3, str(n), 9.0 if n < 100 else 7.5, ink,
                         anchor="middle", weight="700")))


def _key_glyph(p: "Pill", cx: float, cy: float, ink: str, fill: str = "#ffffff") -> str:
    """A marker's glyph in the key list (``<g id="key-N">``)."""
    if p.number is not None:
        return step_mark(p.number, cx, cy, ink, fill, "key-%d" % p.key)
    return _square(p.key, cx, cy, ink, fill, "key-%d" % p.key)


def _key_entries(pills: List["Pill"], max_w: float
                 ) -> List[Tuple["Pill", str, float, int]]:
    """(pill, text, x offset, row) for each marker, in key order, wrapped to ``max_w``."""
    out = []
    x, row = 0.0, 0
    for p in sorted((p for p in pills if p.marker), key=lambda q: q.key):
        s = " ".join(p.lines)
        w = 2 * KEY_R + 8 + text_width(s, KEY_SIZE) + 24
        if x > 0 and x + w > max_w:
            x, row = 0.0, row + 1
        out.append((p, s, x, row))
        x += w
    return out


def key_height(pills: List["Pill"], max_w: float) -> float:
    """Height of the key under the picture (0 when no line has a marker)."""
    entries = _key_entries(pills, max_w)
    if not entries:
        return 0.0
    return 18 + KEY_LINE * (entries[-1][3] + 1)


def key_svg(pills: List["Pill"], x: float, y: float, max_w: float,
            inks: Optional[dict] = None) -> Tuple[str, float]:
    """The key: a ``Line labels`` heading, then each marker and its line's label; top at
    ``y``. Returns (svg, height); empty when no line has a marker."""
    entries = _key_entries(pills, max_w)
    if not entries:
        return "", 0.0
    inks = inks or _PILL_TEXT
    parts = [text(x, y + 12, "Line labels (marked on the lines)", 11, "#475569",
                  weight="700")]
    for p, s, dx, row in entries:
        cy = y + 18 + KEY_LINE * row + KEY_LINE / 2
        parts.append(_key_glyph(p, x + dx + KEY_R, cy, inks[p.style]))
        parts.append(text(x + dx + 2 * KEY_R + 8, cy + 4, s, KEY_SIZE, inks[p.style]))
    return "<g>%s</g>" % "".join(parts), key_height(pills, max_w)


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
