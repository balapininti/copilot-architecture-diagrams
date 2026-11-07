"""SVG helpers shared by every style.

All output keeps to the Office-safe subset: plain shapes, ``<text>``, ``<g transform>``
and presentation attributes. Icons are drawn inline (the samples' ``<defs>``/``<use>``
symbols are copied into each call), and arrowheads are polygons, never markers.

Line types encode certainty and are the same on every diagram:

* confirmed   - solid ``#334155``, 2px, arrowhead
* partial     - dotted ``#d97706`` (``3 4``), arrowhead
* loose       - solid ``#dc2626`` ending in a filled dot r=6
* shared code - dashed ``#a16207`` (``7 4``), arrowhead (confirmed COPY lines only: a
  partly known or loose COPY is drawn by its certainty, never looking confirmed)
"""
from __future__ import annotations

import math
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

FONT = "Segoe UI, Arial, sans-serif"
MONO = "Consolas, monospace"

CONFIRMED_COLOR = "#334155"
PARTIAL_COLOR = "#d97706"
LOOSE_COLOR = "#dc2626"
SHARED_COLOR = "#a16207"
LOOSE_R = 6

REPO_COLORS = ("#3b82f6", "#16a34a", "#9333ea", "#ca8a04", "#ea580c", "#0891b2", "#db2777",
               "#4f46e5")

Point = Tuple[float, float]


# ------------------------------------------------------------------ text

def esc(s: str) -> str:
    """Escape for XML text and attribute values (``& < > " '``)."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def num(v: float) -> str:
    """A coordinate, at most one decimal, without a trailing ``.0``."""
    s = "%.1f" % v
    if s.endswith(".0"):
        s = s[:-2]
    return "0" if s == "-0" else s


def text_width(s: str, size: float, mono: bool = False) -> float:
    """Estimated width of ``s`` drawn at font ``size``."""
    return (0.55 if mono else 0.6) * size * len(s)


def _split_long(word: str, max_chars: int) -> List[str]:
    """Break one word longer than ``max_chars``, preferring after ``. / _ - ,``."""
    out: List[str] = []
    while len(word) > max_chars:
        cut = max(word.rfind(c, 0, max_chars) for c in "./_-,")
        cut = cut + 1 if cut >= max_chars // 3 else max_chars
        out.append(word[:cut])
        word = word[cut:]
    out.append(word)
    return out


def wrap(s: str, max_px: float, size: float, mono: bool = False) -> List[str]:
    """Words of ``s`` in lines no wider than ``max_px`` at ``size`` (long words broken)."""
    max_chars = max(1, int(max_px / ((0.55 if mono else 0.6) * size)))
    words: List[str] = []
    for w in str(s).split():
        words.extend(_split_long(w, max_chars))
    if not words:
        return [""]
    lines: List[str] = []
    cur = ""
    for w in words:
        cand = w if not cur else cur + " " + w
        if len(cand) <= max_chars:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def text(x: float, y: float, s: str, size: float = 12, fill: str = "#0f172a",
         anchor: str = "start", weight: str = "", mono: bool = False) -> str:
    attrs = ['x="%s"' % num(x), 'y="%s"' % num(y), 'font-size="%s"' % num(size),
             'fill="%s"' % fill]
    if anchor != "start":
        attrs.append('text-anchor="%s"' % anchor)
    if weight:
        attrs.append('font-weight="%s"' % weight)
    if mono:
        attrs.append('font-family="%s"' % MONO)
    return "<text %s>%s</text>" % (" ".join(attrs), esc(s))


def tint(color: str, amount: float) -> str:
    """``color`` mixed with white: ``amount`` 0 is white, 1 the color itself."""
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except (ValueError, IndexError):
        return "#f1f5f9"
    mix = lambda v: int(round(255 - (255 - v) * amount))  # noqa: E731
    return "#%02x%02x%02x" % (mix(r), mix(g), mix(b))


def step_text(n: Optional[int]) -> str:
    """A step number in a text-only copy (draw.io, Mermaid, Excalidraw): ``(1)`` ... ``(21)``,
    every number the same way; empty for no number. The SVGs draw ``step_mark`` instead."""
    return "" if n is None else "(%d)" % n


STEP_R = 7.5      # a step number's circle
STEP_SIZE = 9.0   # and its text


def step_mark(n: int, cx: float, cy: float, ink: str, fill: str = "#ffffff",
              gid: Optional[str] = None) -> str:
    """A step number as drawn on a line label: a small circle outlined in the label's ink,
    the number inside it (``<g id="step-N">``, or ``gid``). Drawn, not a Unicode circled
    digit, so 21 looks like 1 and every font shows it."""
    return ('<g id="%s"><circle cx="%s" cy="%s" r="%s" fill="%s" stroke="%s" '
            'stroke-width="1.3"/>%s</g>'
            % (gid if gid is not None else "step-%d" % n, num(cx), num(cy), num(STEP_R), fill, ink,
               text(cx, cy + STEP_SIZE * 0.36, str(n), STEP_SIZE if n < 100 else 7.5, ink,
                    anchor="middle", weight="700")))


# ------------------------------------------------------------------ lines

def line_style(status: str, kind: str) -> str:
    """``confirmed``, ``partial``, ``loose`` or ``shared_code``: the line type to draw."""
    if status == "partial":
        return "partial"
    if status == "loose":
        return "loose"
    if kind == "shared_code":
        return "shared_code"
    return "confirmed"


_LINE_ATTRS = {
    "confirmed": 'stroke="%s" stroke-width="2" fill="none"' % CONFIRMED_COLOR,
    "partial": 'stroke="%s" stroke-width="2" stroke-dasharray="3 4" fill="none"' % PARTIAL_COLOR,
    "loose": 'stroke="%s" stroke-width="2" fill="none"' % LOOSE_COLOR,
    "shared_code": ('stroke="%s" stroke-width="1.6" stroke-dasharray="7 4" fill="none"'
                    % SHARED_COLOR),
}
LINE_COLORS = {"confirmed": CONFIRMED_COLOR, "partial": PARTIAL_COLOR, "loose": LOOSE_COLOR,
               "shared_code": SHARED_COLOR}


def line_attrs(status: str, kind: str) -> str:
    """The stroke attributes for a line of this status and kind."""
    return _LINE_ATTRS[line_style(status, kind)]


def line_color(status: str, kind: str) -> str:
    return LINE_COLORS[line_style(status, kind)]


def arrowhead(p_from: Point, p_to: Point, color: str, length: float = 10.0,
              half: float = 4.5) -> str:
    """A filled triangle with its tip at ``p_to``, pointing away from ``p_from``."""
    dx, dy = p_to[0] - p_from[0], p_to[1] - p_from[1]
    d = math.hypot(dx, dy) or 1.0
    ux, uy = dx / d, dy / d
    bx, by = p_to[0] - ux * length, p_to[1] - uy * length
    pts = [p_to, (bx - uy * half, by + ux * half), (bx + uy * half, by - ux * half)]
    return '<polygon points="%s" fill="%s"/>' % (
        " ".join("%s,%s" % ("%.1f" % x, "%.1f" % y) for x, y in pts), color)


def loose_dot(x: float, y: float) -> str:
    """The filled red dot a loose end finishes in."""
    return '<circle cx="%s" cy="%s" r="%d" fill="%s"/>' % (num(x), num(y), LOOSE_R, LOOSE_COLOR)


def path_d(pts: Sequence[Point]) -> str:
    return "M" + " L".join("%s,%s" % (num(x), num(y)) for x, y in pts)


# ------------------------------------------------------------------ legend, notes, document

_LEGEND = (
    ("confirmed", "confirmed (both ends found in code)"),
    ("partial", "partly known / suggested"),
    ("loose", "loose end (only one side found)"),
    ("shared_code", "shared code (copybook, package)"),
)
LEGEND_SIZE = 11.0


def legend_width(statuses_present: Iterable[str]) -> float:
    present = set(statuses_present)
    return sum(54 + text_width(t, LEGEND_SIZE) + 24 for k, t in _LEGEND if k in present)


def legend(x: float, y: float, statuses_present: Set[str]) -> Tuple[str, float]:
    """One row naming each line type present (and only those), and the row's height."""
    parts: List[str] = []
    cx = x
    cy = y + 9
    for key, label in _LEGEND:
        if key not in statuses_present:
            continue
        if key == "loose":
            parts.append('<path d="M%s,%s L%s,%s" %s/>' % (num(cx), num(cy), num(cx + 36),
                                                           num(cy), _LINE_ATTRS[key]))
            parts.append(loose_dot(cx + 40, cy))
        else:
            parts.append('<path d="M%s,%s L%s,%s" %s/>' % (num(cx), num(cy), num(cx + 44),
                                                           num(cy), _LINE_ATTRS[key]))
        parts.append(text(cx + 54, cy + 4, label, LEGEND_SIZE, "#334155"))
        cx += 54 + text_width(label, LEGEND_SIZE) + 24
    if not parts:
        return "", 0.0
    return "<g>%s</g>" % "".join(parts), 18.0


NOTE_SIZE = 10.5
NOTE_LINE = 15.0


def note_lines(notes: Sequence[str], max_w: float) -> List[str]:
    lines: List[str] = []
    for n in notes:
        for i, s in enumerate(wrap(n, max_w - 14, NOTE_SIZE)):
            lines.append(("• " if i == 0 else "  ") + s)
    return lines


def notes_height(notes: Sequence[str], max_w: float = 900.0) -> float:
    if not notes:
        return 0.0
    return 18 + NOTE_LINE * len(note_lines(notes, max_w))


def notes_block(notes: Sequence[str], x: float, y: float, max_w: float = 900.0) -> str:
    """A ``Notes`` heading and one bullet per note, wrapped to ``max_w``; top at ``y``."""
    if not notes:
        return ""
    parts = [text(x, y + 12, "Notes", 11, "#475569", weight="700")]
    for i, line in enumerate(note_lines(notes, max_w)):
        parts.append(text(x, y + 18 + NOTE_LINE * (i + 1) - 3, line, NOTE_SIZE, "#475569"))
    return "<g>%s</g>" % "".join(parts)


def svg_doc(w: float, h: float, body: str, bg: str = "#ffffff",
            title: str = "Architecture diagram") -> str:
    """A complete SVG document: namespace, size, ``<title>``, background, body."""
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%s" height="%s" viewBox="0 0 %s %s" '
            'font-family="%s"><title>%s</title><rect x="0" y="0" width="%s" height="%s" '
            'fill="%s"/>%s</svg>\n' % (num(w), num(h), num(w), num(h), FONT, esc(title),
                                       num(w), num(h), bg, body))


# ------------------------------------------------------------------ icons
#
# Each icon is centered on (x, y) and fits in about 72 x 56. ``color`` is the group color;
# an empty string means the kind's own color from the samples.

ICON_W = 72.0
ICON_H = 56.0

_DEFAULT = {
    "person": "#64748b", "page": "#3b82f6", "component": "#dd0031", "class": "#16a34a",
    "endpoint": "#16a34a", "program": "#2563eb", "utility": "#64748b", "job": "#334155",
    "step": "#334155", "dataset": "#0284c7", "gdg": "#7c3aed", "vsam": "#0284c7",
    "table": "#1d4ed8", "queue": "#f97316", "transaction": "#16a34a", "map": "#2b8a3e",
    "cicsfile": "#0284c7", "external": "#64748b", "notanalyzed": "#94a3b8", "repo": "#334155",
    "application": "#3b82f6", "datastore": "#ea580c", "neighbor": "#94a3b8",
    "missing": LOOSE_COLOR, "more": "#64748b", "sysout": "#475569",
}


def _g(x: float, y: float, inner: str) -> str:
    return '<g transform="translate(%s,%s)">%s</g>' % (num(x), num(y), inner)


def _c(kind: str, color: str) -> str:
    return color or _DEFAULT[kind]


def _person(x: float, y: float, color: str) -> str:
    c = _c("person", color)
    return _g(x, y, '<circle cx="0" cy="-14" r="11" fill="%s"/>'
                    '<path d="M-21,26 Q-21,0 0,0 Q21,0 21,26 z" fill="%s"/>' % (c, c))


def _page(x: float, y: float, color: str) -> str:
    c = _c("page", color)
    return _g(x, y,
              '<rect x="-32" y="-24" width="64" height="48" rx="5" fill="#ffffff" stroke="%s" '
              'stroke-width="2"/><rect x="-32" y="-24" width="64" height="11" rx="5" fill="%s"/>'
              '<circle cx="-25" cy="-18.5" r="2" fill="#ffffff"/>'
              '<circle cx="-19" cy="-18.5" r="2" fill="#ffffff"/>'
              '<circle cx="-13" cy="-18.5" r="2" fill="#ffffff"/>'
              '<rect x="-24" y="-6" width="32" height="5" rx="2" fill="%s"/>'
              '<rect x="-24" y="3" width="48" height="5" rx="2" fill="%s"/>'
              '<rect x="-24" y="12" width="22" height="8" rx="2" fill="%s"/>'
              % (c, c, tint(c, 0.35), tint(c, 0.35), c))


def _component(x: float, y: float, color: str) -> str:
    c = _c("component", color)
    return _g(x, y,
              '<rect x="-28" y="-22" width="56" height="44" rx="6" fill="#ffffff" stroke="%s" '
              'stroke-width="2"/><rect x="-28" y="-22" width="56" height="9" rx="4" fill="%s"/>'
              '<path d="M-9,-4 L-17,4 L-9,12 M9,-4 L17,4 L9,12 M4,-6 L-4,14" fill="none" '
              'stroke="%s" stroke-width="2.4" stroke-linecap="round"/>' % (c, tint(c, 0.4), c))


def _doc_header(c: str, label: str) -> str:
    return ('<rect x="-20" y="-24" width="40" height="48" rx="3" fill="#ffffff" stroke="%s" '
            'stroke-width="2"/><rect x="-20" y="-24" width="40" height="11" rx="3" fill="%s"/>'
            '<text x="0" y="-15.5" text-anchor="middle" font-size="8" fill="#ffffff" '
            'font-weight="700">%s</text>'
            '<path d="M-13,-4 h20 M-13,3 h14 M-9,10 h18 M-13,17 h10" stroke="%s" '
            'stroke-width="3"/>' % (c, c, label, tint(c, 0.45)))


def _program(x: float, y: float, color: str) -> str:
    return _g(x, y, _doc_header(_c("program", color), "CBL"))


def _class(x: float, y: float, color: str) -> str:
    return _g(x, y, _doc_header(_c("class", color), "JAVA"))


def _endpoint(x: float, y: float, color: str) -> str:
    c = _c("endpoint", color)
    return _g(x, y,
              '<path d="M-30,0 L-17,-20 L17,-20 L30,0 L17,20 L-17,20 z" fill="%s" stroke="%s" '
              'stroke-width="2"/><text x="0" y="4" text-anchor="middle" font-size="11" '
              'font-weight="700" fill="%s">API</text>' % (tint(c, 0.15), c, c))


def _utility(x: float, y: float, color: str) -> str:
    c = _c("utility", color)
    return _g(x, y,
              '<circle cx="0" cy="0" r="15" fill="none" stroke="%s" stroke-width="9" '
              'stroke-dasharray="5.5 4.5"/><circle cx="0" cy="0" r="11" fill="#e2e8f0" '
              'stroke="%s" stroke-width="2"/><circle cx="0" cy="0" r="4" fill="%s"/>'
              % (c, c, c))


def _job(x: float, y: float, color: str) -> str:
    c = _c("job", color)
    return _g(x, y,
              '<path d="M-24,-27 h34 l14,14 v40 h-48 z" fill="#f8fafc" stroke="%s" '
              'stroke-width="2"/><path d="M10,-27 v14 h14" fill="none" stroke="%s" '
              'stroke-width="2"/><text x="0" y="6" text-anchor="middle" font-size="12" '
              'font-weight="700" fill="%s">JCL</text>' % (c, c, c))


def _step(x: float, y: float, color: str) -> str:
    c = _c("step", color)
    return _g(x, y,
              '<rect x="-28" y="-16" width="56" height="32" rx="8" fill="%s" stroke="%s" '
              'stroke-width="2"/><path d="M-8,-8 L4,0 L-8,8" fill="none" stroke="%s" '
              'stroke-width="3" stroke-linecap="round"/>' % (tint(c, 0.12), c, c))


def _disk(c: str, extra: str = "") -> str:
    return ('<path d="M-26,-14 L-26,14 A26,8 0 0,0 26,14 L26,-14" fill="%s" stroke="%s" '
            'stroke-width="2"/><ellipse cx="0" cy="-14" rx="26" ry="8" fill="%s" stroke="%s" '
            'stroke-width="2"/><path d="M-26,0 A26,8 0 0,0 26,0" fill="none" stroke="%s" '
            'stroke-width="1.5"/>%s' % (tint(c, 0.12), c, tint(c, 0.3), c, c, extra))


def _dataset(x: float, y: float, color: str) -> str:
    return _g(x, y, _disk(_c("dataset", color)))


def _vsam(x: float, y: float, color: str) -> str:
    c = _c("vsam", color)
    return _g(x, y, _disk(c, '<text x="0" y="13" text-anchor="middle" font-size="9" '
                             'font-weight="700" fill="%s">VSAM</text>' % c))


def _gdg(x: float, y: float, color: str) -> str:
    c = _c("gdg", color)
    lt, md = tint(c, 0.12), tint(c, 0.25)
    return _g(x, y,
              '<rect x="-30" y="-19" width="44" height="30" rx="3" fill="%s" stroke="%s" '
              'stroke-width="1.5"/><rect x="-26" y="-15" width="44" height="30" rx="3" '
              'fill="%s" stroke="%s" stroke-width="1.5"/><rect x="-22" y="-11" width="44" '
              'height="30" rx="3" fill="%s" stroke="%s" stroke-width="2"/><text x="0" y="8" '
              'text-anchor="middle" font-size="9" font-weight="700" fill="%s">GDG</text>'
              % (lt, c, lt, c, md, c, c))


def _table(x: float, y: float, color: str) -> str:
    c = _c("table", color)
    return _g(x, y,
              '<path d="M-26,-16 L-26,16 A26,8 0 0,0 26,16 L26,-16" fill="%s" stroke="%s" '
              'stroke-width="2"/><ellipse cx="0" cy="-16" rx="26" ry="8" fill="%s" stroke="%s" '
              'stroke-width="2"/><text x="0" y="10" text-anchor="middle" font-size="10" '
              'font-weight="700" fill="%s">DB2</text>' % (tint(c, 0.16), c, tint(c, 0.45), c, c))


def _queue(x: float, y: float, color: str) -> str:
    c = _c("queue", color)
    return _g(x, y,
              '<rect x="-36" y="-15" width="72" height="30" rx="15" fill="%s" stroke="%s" '
              'stroke-width="2"/><rect x="-25" y="-8" width="11" height="16" rx="2" fill="%s"/>'
              '<rect x="-11" y="-8" width="11" height="16" rx="2" fill="%s"/>'
              '<rect x="3" y="-8" width="11" height="16" rx="2" fill="%s"/>'
              '<path d="M18,0 L24,0" stroke="%s" stroke-width="2"/>%s'
              % (tint(c, 0.1), c, tint(c, 0.5), tint(c, 0.5), tint(c, 0.5), c,
                 arrowhead((18, 0), (31, 0), c, 8, 4)))


def _transaction(x: float, y: float, color: str) -> str:
    c = _c("transaction", color)
    return _g(x, y,
              '<rect x="-28" y="-22" width="56" height="44" rx="6" fill="#ffffff" stroke="%s" '
              'stroke-width="2"/><rect x="-28" y="-22" width="56" height="12" rx="5" fill="%s"/>'
              '<text x="0" y="-13" text-anchor="middle" font-size="8" font-weight="700" '
              'fill="#ffffff">CICS</text><path d="M4,-7 L-8,7 L-1,7 L-4,19 L9,3 L2,3 L6,-7 z" '
              'fill="%s"/>' % (c, c, c))


def _map(x: float, y: float, color: str) -> str:
    c = _c("map", color)
    return _g(x, y,
              '<rect x="-30" y="-25" width="60" height="40" rx="4" fill="#166534" stroke="%s" '
              'stroke-width="2"/><path d="M-22,-15 h26 M-22,-7 h36 M-22,1 h18 M-22,8 h30" '
              'stroke="#86efac" stroke-width="2.4"/><rect x="-8" y="15" width="16" height="6" '
              'fill="#475569"/><rect x="-18" y="21" width="36" height="4" rx="2" '
              'fill="#475569"/>' % c)


def _cicsfile(x: float, y: float, color: str) -> str:
    c = _c("cicsfile", color)
    return _g(x, y,
              '<path d="M-22,-25 h30 l14,14 v36 h-44 z" fill="%s" stroke="%s" stroke-width="2"/>'
              '<path d="M8,-25 v14 h14" fill="none" stroke="%s" stroke-width="2"/>'
              '<text x="0" y="10" text-anchor="middle" font-size="9" font-weight="700" '
              'fill="%s">FILE</text>' % (tint(c, 0.12), c, c, c))


def _external(x: float, y: float, color: str) -> str:
    c = _c("external", color)
    return ('<g transform="translate(%s,%s) scale(0.72) translate(-47,-30)"><path d="M18,52 '
            'a18,18 0 0,1 2,-36 a24,24 0 0,1 44,-6 a18,18 0 0,1 30,22 a14,14 0 0,1 -6,20 z" '
            'fill="#f1f5f9" stroke="%s" stroke-width="2.6"/></g>' % (num(x), num(y), c))


def _notanalyzed(x: float, y: float, color: str) -> str:
    c = _DEFAULT["notanalyzed"]
    return _g(x, y,
              '<path d="M-22,-25 h30 l14,14 v36 h-44 z" fill="#f1f5f9" stroke="%s" '
              'stroke-width="2" stroke-dasharray="4 3"/><text x="0" y="12" text-anchor="middle" '
              'font-size="22" font-weight="700" fill="%s">?</text>' % (c, c))


def _repo(x: float, y: float, color: str) -> str:
    c = _c("repo", color)
    return _g(x, y,
              '<path d="M-30,-20 h20 l6,6 h34 v34 h-60 z" fill="%s" stroke="%s" '
              'stroke-width="2"/><path d="M-8,-4 v16 M-8,4 C-8,0 8,2 8,-4" fill="none" '
              'stroke="%s" stroke-width="2"/><circle cx="-8" cy="-4" r="3" fill="%s"/>'
              '<circle cx="-8" cy="12" r="3" fill="%s"/><circle cx="8" cy="-4" r="3" fill="%s"/>'
              % (tint(c, 0.15), c, c, c, c, c))


def _application(x: float, y: float, color: str) -> str:
    c = _c("application", color)
    rows = []
    for ry in (-25, -7, 11):
        rows.append('<rect x="-30" y="%d" width="60" height="15" rx="3" fill="#ffffff" '
                    'stroke="%s" stroke-width="2"/><circle cx="20" cy="%s" r="3" fill="%s"/>'
                    '<rect x="-23" y="%s" width="26" height="4" rx="2" fill="%s"/>'
                    % (ry, c, num(ry + 7.5), c, num(ry + 5.5), tint(c, 0.35)))
    return _g(x, y, "".join(rows))


def _datastore(x: float, y: float, color: str) -> str:
    c = _c("datastore", color)
    return _g(x, y,
              '<path d="M-30,-18 L-30,18 A30,8 0 0,0 30,18 L30,-18" fill="%s" stroke="%s" '
              'stroke-width="2"/><ellipse cx="0" cy="-18" rx="30" ry="8" fill="%s" stroke="%s" '
              'stroke-width="2"/><path d="M-30,-5 A30,8 0 0,0 30,-5 M-30,7 A30,8 0 0,0 30,7" '
              'fill="none" stroke="%s" stroke-width="1.2"/>'
              % (tint(c, 0.15), c, tint(c, 0.3), c, c))


def _neighbor(x: float, y: float, color: str) -> str:
    c = _DEFAULT["neighbor"]
    return _g(x, y,
              '<rect x="-28" y="-16" width="56" height="32" rx="6" fill="#f8fafc" stroke="%s" '
              'stroke-width="1.6" stroke-dasharray="4 3"/><circle cx="-10" cy="0" r="3" '
              'fill="%s"/><circle cx="0" cy="0" r="3" fill="%s"/><circle cx="10" cy="0" r="3" '
              'fill="%s"/>' % (c, c, c, c))


def _missing(x: float, y: float, color: str) -> str:
    return '<circle cx="%s" cy="%s" r="%d" fill="%s"/>' % (num(x), num(y), LOOSE_R,
                                                           _c("missing", color))


def _more(x: float, y: float, color: str) -> str:
    c = _c("more", color)
    return _g(x, y,
              '<rect x="-24" y="-18" width="44" height="30" rx="3" fill="#ffffff" stroke="%s" '
              'stroke-width="1.5"/><rect x="-20" y="-14" width="44" height="30" rx="3" '
              'fill="#ffffff" stroke="%s" stroke-width="1.5"/><rect x="-16" y="-10" width="44" '
              'height="30" rx="3" fill="#ffffff" stroke="%s" stroke-width="2"/>'
              '<text x="6" y="9" text-anchor="middle" font-size="14" font-weight="700" '
              'fill="%s">…</text>' % (c, c, c, c))


def _sysout(x: float, y: float, color: str) -> str:
    c = _c("sysout", color)
    return _g(x, y,
              '<rect x="-24" y="-20" width="48" height="22" rx="4" fill="#e2e8f0" stroke="%s" '
              'stroke-width="2"/><rect x="-16" y="-4" width="32" height="26" fill="#ffffff" '
              'stroke="%s" stroke-width="1.5"/><path d="M-10,4 h20 M-10,10 h14 M-10,16 h18" '
              'stroke="#94a3b8" stroke-width="1.5"/>' % (c, c))


ICONS: Dict[str, Callable[[float, float, str], str]] = {
    "person": _person, "page": _page, "component": _component, "class": _class,
    "endpoint": _endpoint, "program": _program, "utility": _utility, "job": _job,
    "step": _step, "dataset": _dataset, "gdg": _gdg, "vsam": _vsam, "table": _table,
    "queue": _queue, "transaction": _transaction, "map": _map, "cicsfile": _cicsfile,
    "external": _external, "notanalyzed": _notanalyzed, "repo": _repo,
    "application": _application, "datastore": _datastore, "neighbor": _neighbor,
    "missing": _missing, "more": _more, "sysout": _sysout,
}

# kinds whose color means something (grey = outside or not analyzed, red = loose), so a
# group color never replaces it
FIXED_COLOR_KINDS = ("person", "external", "notanalyzed", "neighbor", "missing", "more")
