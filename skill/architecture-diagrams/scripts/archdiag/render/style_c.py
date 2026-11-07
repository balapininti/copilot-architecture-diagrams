"""Style C: the repo link map, with an offline HTML page.

Looks like diagram 4 of ``docs/samples/mainframe-samples.html`` and option C of
``docs/samples/style-options.html``: one white card per repo with a colored header
(``⎇ repo`` and its languages), the files that tie repos together highlighted in the card,
lines labelled by what connects the repos, and a strip of the exact ``file:line`` evidence
at the bottom. Line types encode certainty exactly as in Styles A and B (see ``common``).

render(view) -> {"svg": ..., "html": ...}. The HTML holds the same SVG inline plus a side
panel: click a line to see every piece of evidence for it, or search to filter the lines.
Everything (CSS, JS, evidence data) is inline; the page names no URL.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Set, Tuple

from archdiag.layout import Box, Layout, layout_for
from archdiag.render.common import (LOOSE_COLOR, MONO, PARTIAL_COLOR, REPO_COLORS, esc,
                                    gd_details, group_colors, legend, legend_width, line_style, link_wrap,
                                    notes_block, notes_height, num, overview_block, svg_doc,
                                    text, text_width, tint, wrap)
from archdiag.render.pills import Pill, edge_svg, key_svg, marker_svg, place_pills
from archdiag.views import VEdge, VNode, ViewGraph
from archdiag.views.common import STRUCTURAL  # Ruling 10: not a link in any total

TITLE_H = 44.0
HEAD_H = 32.0
ROW_H = 22.0
ROW_GAP = 2.0
CARD_PAD = 8.0
MIN_CARD_W = 230.0
MAX_ROW_CHARS = 44
GD_ROW_CHARS = 38  # a gitdiagram card's text wraps here (monospace widths vary by font)
NAME_SIZE, LANG_SIZE, ROW_SIZE = 13.5, 10.5, 12.0
STRIP_SIZE, STRIP_LINE = 11.0, 18.0
STRIP_MAX = 6

STRIP_STYLE = 'fill="#f8fafc" stroke="#e2e8f0"'

_PILL = {  # style -> (fill, stroke, text)
    "confirmed": ("#0f172a", "#0f172a", "#ffffff"),
    "shared_code": ("#0f172a", "#0f172a", "#fcd34d"),
    "partial": ("#fffbeb", "#fcd34d", "#b45309"),
    "loose": ("#fef2f2", "#fca5a5", "#b91c1c"),
    "structural": ("#f8fafc", "#e2e8f0", "#64748b"),
}
CARD_KINDS = ("repo", "group", "actor")  # drawn as a card: gitdiagram groups and entry points
ACTOR_HEAD = "#1e293b"


# ------------------------------------------------------------------ card text

def _shorten(s: str, limit: int = MAX_ROW_CHARS) -> str:
    """``s`` cut from the left with a leading ``…`` when longer than ``limit`` (the end of
    a path is the part that tells files apart)."""
    return s if len(s) <= limit else "…" + s[-(limit - 1):]


def _rows(n: VNode) -> List[Tuple[str, bool, bool]]:
    """(text, is evidence file, muted) for each detail row of a card."""
    out = []
    if n.kind != "repo":  # gitdiagram text (files, names, a description): wrapped, not cut
        return [(s, False, m) for s, m in
                gd_details(n, GD_ROW_CHARS * 0.55 * ROW_SIZE, ROW_SIZE, True)]
    for i, d in enumerate(n.detail_lines):
        out.append((_shorten(d), i < n.highlight and not d.startswith("…"), False))
    return out


def _name(n: VNode) -> str:
    return "\u2387 " + n.label if n.kind == "repo" else n.label


def _missing_lines(n: VNode) -> Tuple[List[str], List[str]]:
    return wrap(n.label, 200, 12, False), wrap(n.sublabel, 200, 10, False) if n.sublabel else []


def node_size(n: VNode) -> Tuple[float, float]:
    if n.kind in CARD_KINDS:
        rows = _rows(n)
        w = max([MIN_CARD_W, text_width(_name(n), NAME_SIZE) + text_width(n.sublabel, LANG_SIZE)
                 + 44] + [text_width(r, ROW_SIZE, n.kind == "repo") + 28 for r, _, _ in rows])
        h = HEAD_H + CARD_PAD + len(rows) * (ROW_H + ROW_GAP) + CARD_PAD
        return w, max(h, HEAD_H + 40)
    name, sub = _missing_lines(n)
    w = max([text_width(s, 12) for s in name] + [text_width(s, 10) for s in sub] + [110.0]) + 28
    return w, 20 + 15 * len(name) + 13 * len(sub)


# ------------------------------------------------------------------ SVG

def _repo_colors(view: ViewGraph) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for n in view.nodes:
        if n.kind == "repo":
            out[n.id] = REPO_COLORS[len(out) % len(REPO_COLORS)]
        elif n.kind == "actor":
            out[n.id] = ACTOR_HEAD
    out.update(group_colors(view))
    return out


def _card_svg(n: VNode, b: Box, color: str, ox: float, oy: float) -> str:
    x, y, w, h = b.x + ox, b.y + oy, b.w, b.h
    if n.role == "ungrouped":  # gitdiagram "Not yet grouped": dashed grey, light header
        parts = ['<rect x="%s" y="%s" width="%s" height="%s" rx="10" fill="#f8fafc" '
                 'stroke="#94a3b8" stroke-width="1.4" stroke-dasharray="6 4"/>'
                 % (num(x), num(y), num(w), num(h)),
                 text(x + 13, y + 21, _name(n), NAME_SIZE, "#334155", weight="700")]
        ry = y + HEAD_H + CARD_PAD
        for row, _, _ in _rows(n):
            parts.append(text(x + 14, ry + 15, row, ROW_SIZE, "#64748b", mono=True))
            ry += ROW_H + ROW_GAP
        return "<g>%s</g>" % "".join(parts)
    parts = [
        # the shadow: a second rect offset 2px (no filter in Office-safe SVG)
        '<rect x="%s" y="%s" width="%s" height="%s" rx="10" fill="#0f172a" fill-opacity="0.08"/>'
        % (num(x + 2), num(y + 2), num(w), num(h)),
        '<rect x="%s" y="%s" width="%s" height="%s" rx="10" fill="#ffffff" stroke="#cbd5e1"/>'
        % (num(x), num(y), num(w), num(h)),
        '<path d="M%s,%s a10,10 0 0,1 10,-10 h%s a10,10 0 0,1 10,10 v%s h-%s z" fill="%s"/>'
        % (num(x), num(y + 10), num(w - 20), num(HEAD_H - 10), num(w), color),
        text(x + 13, y + 21, _name(n), NAME_SIZE, "#ffffff", weight="700"),
    ]
    if n.sublabel:
        parts.append(text(x + w - 10, y + 20, n.sublabel, LANG_SIZE, "#f1f5f9", anchor="end"))
    ry = y + HEAD_H + CARD_PAD
    for row, is_evidence, muted in _rows(n):
        if is_evidence:
            parts.append('<rect x="%s" y="%s" width="%s" height="%s" rx="4" fill="%s"/>'
                         % (num(x + 8), num(ry), num(w - 16), num(ROW_H), tint(color, 0.18)))
        parts.append(text(x + 14, ry + 15, row, ROW_SIZE,
                          "#0f172a" if is_evidence else ("#94a3b8" if muted else "#64748b"),
                          mono=True))
        ry += ROW_H + ROW_GAP
    return "<g>%s</g>" % "".join(parts)


def _stub_svg(n: VNode, b: Box, ox: float, oy: float, inside: bool = False) -> str:
    x, y, w, h = b.x + ox, b.y + oy, b.w, b.h
    name, sub = _missing_lines(n)
    cx = x + w / 2
    if n.kind == "missing":
        partial = n.status == "partial"
        c = PARTIAL_COLOR if partial else LOOSE_COLOR
        dash = ' stroke-dasharray="3 4"' if partial else ""
        rect = ('<rect x="%s" y="%s" width="%s" height="%s" rx="6" fill="%s" stroke="%s" '
                'stroke-width="1.6"%s/>' % (num(x), num(y), num(w), num(h),
                                            "#fffbeb" if partial else "#fef2f2", c, dash))
        fill = "#b45309" if partial else "#b91c1c"
    elif inside and n.kind not in ("outside", "external", "neighbor", "notanalyzed"):
        # a gitdiagram resource of this repo two groups share: solid, not the outside look
        rect = ('<rect x="%s" y="%s" width="%s" height="%s" rx="6" fill="#ffffff" '
                'stroke="#64748b" stroke-width="1.4"/>' % (num(x), num(y), num(w), num(h)))
        fill = "#1e293b"
    else:  # outside these repos
        rect = ('<rect x="%s" y="%s" width="%s" height="%s" rx="6" fill="#f1f5f9" '
                'stroke="#94a3b8" stroke-width="1.4" stroke-dasharray="4 3"/>'
                % (num(x), num(y), num(w), num(h)))
        fill = "#475569"
    parts = [rect]
    ty = y + 10
    for s in name:
        ty += 15
        parts.append(text(cx, ty - 3, s, 12, fill, "middle", "700"))
    for s in sub:
        ty += 13
        parts.append(text(cx, ty - 3, s, 10, fill, "middle"))
    return "<g>%s</g>" % "".join(parts)


_KEY_INK = {"confirmed": "#0f172a", "shared_code": "#a16207", "partial": "#b45309",
            "loose": "#b91c1c", "structural": "#64748b"}


def _pill_svg(p: Pill, ox: float, oy: float) -> str:
    fill, stroke, tcol = _PILL[p.style]
    x, y = p.x + ox, p.y + oy
    if p.marker:
        return marker_svg(p, x, y, _KEY_INK[p.style])
    parts = ['<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s" stroke="%s" '
             'stroke-width="1"/>' % (num(x), num(y), num(p.w), num(p.h),
                                     num(min(10.0, p.h / 2)), fill, stroke)]
    parts.append(p.mark(x, y, tcol, fill))
    for k, s in enumerate(p.lines):
        parts.append(text(p.text_cx(x), y + 2.5 + 13.5 * (k + 1) - 3.5, s, 10.5, tcol,
                          anchor="middle"))
    return "".join(parts)


def _base(path: str) -> str:
    """The file name of an evidence path; a member of an archive keeps its archive name
    (``claims.aar!/package.xml``)."""
    if "!/" in path:
        cut = path.rfind("/", 0, path.index("!/"))
        return path[cut + 1:]
    return path.rsplit("/", 1)[-1]


def _with_folder(path: str) -> str:
    """The base name with its parent folder (``batch/CLMREC.cpy``), for base names that
    would otherwise read the same."""
    base = _base(path)
    head = path[:len(path) - len(base)].rstrip("/")
    parent = head.rsplit("/", 1)[-1] if head else ""
    return "%s/%s" % (parent, base) if parent else base


def _loc(path: str, line: int, collide: Set[str] = frozenset()) -> str:
    base = _base(path)
    return "%s:%s" % (_with_folder(path) if base in collide else base, line)


def _side(items: list, collide: Set[str], limit: int = 2) -> str:
    locs: List[str] = []
    for e in items:
        if _loc(e.path, e.line, collide) not in locs:
            locs.append(_loc(e.path, e.line, collide))
    shown = locs[:limit]
    extra = len(locs) - limit
    return " \u00b7 ".join(shown) + (" \u00b7 + %d more" % extra if extra > 0 else "")


def evidence_strip(view: ViewGraph, max_chars: int) -> List[str]:
    """Up to STRIP_MAX lines ``<via>  <file>:<line> ↔ <file>:<line>``, the links tied
    together by the most files first, then a count of the links left out. A file name
    that two different paths in the strip share keeps its parent folder."""
    by_id = {n.id: n for n in view.nodes}
    ranked = [(i, e) for i, e in enumerate(view.edges) if e.evidence]
    ranked.sort(key=lambda ie: (-len(ie[1].evidence), ie[0]))
    shown = [e for _, e in ranked[:STRIP_MAX]]
    paths_of: Dict[str, Set[str]] = {}
    for e in shown:
        for x in e.evidence:
            paths_of.setdefault(_base(x.path), set()).add(x.path)
    collide = {b for b, ps in paths_of.items() if len(ps) > 1}
    lines = []
    for e in shown:
        src = by_id.get(e.src)
        src_repo = src.label if src is not None and src.kind == "repo" else None
        mine = [x for x in e.evidence if x.repo == src_repo] if src_repo else []
        other = [x for x in e.evidence if x not in mine]
        if not mine:
            mine, other = list(e.evidence), []
        s = "%s  %s" % (e.label or "link", _side(mine, collide))
        if other:
            s += "  \u2194  " + _side(other, collide)
        lines.append(s if len(s) <= max_chars else s[:max_chars - 1] + "\u2026")
    return lines


def _svg(view: ViewGraph, L: Layout, styles: List[str], pills: List[Pill],
         interactive: bool = False) -> str:
    colors = _repo_colors(view)
    routes = [list(r) for r in L.routes]
    pill_of = {p.i: p for p in pills}

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

    key, key_h = key_svg(pills, 30, content_h + 6, width - 60, _KEY_INK)
    strip = evidence_strip(view, int((width - 60) / (0.55 * STRIP_SIZE)))
    strip_y = content_h + 6 + (key_h + 10 if key_h else 0)
    strip_h = 16 + STRIP_LINE * len(strip) if strip else 0.0
    leg_y = strip_y + strip_h + (12 if strip else 0)
    leg, leg_h = legend(30, leg_y, present)
    notes_y = leg_y + leg_h + (14 if leg_h else 0)
    n_h = notes_height(view.notes + L.notes, note_w)
    height = notes_y + n_h + (16 if n_h else 4)

    body: List[str] = [text(24, 30, view.title, 16, "#0f172a", weight="700")]
    if overview:
        body.append('<g transform="translate(0,%s)">%s</g>' % (num(TITLE_H), overview))
    inside = view.level == "gitdiagram"
    for n in view.nodes:
        b = L.boxes.get(n.id)
        if b is None:
            continue
        body.append(link_wrap(view, n, _card_svg(n, b, colors[n.id], ox, oy)
                              if n.kind in CARD_KINDS else _stub_svg(n, b, ox, oy, inside)))
    labels: List[str] = []
    for i, e in enumerate(view.edges):
        if i >= len(routes):
            continue
        g = [edge_svg(i, routes[i], styles[i], e.status, e.kind, ox, oy)]
        if interactive and len(routes[i]) >= 2:  # a wide invisible line is easy to click
            pts = [(x + ox, y + oy) for x, y in routes[i]]
            g.append('<path d="M%s" fill="none" stroke="#ffffff" stroke-opacity="0" '
                     'stroke-width="14" pointer-events="stroke"/>'
                     % " L".join("%s,%s" % (num(x), num(y)) for x, y in pts))
        body.append('<g data-edge="%d" data-style="%s">%s</g>' % (i, styles[i], "".join(g)))
        if i in pill_of:  # labels go on top of every line, but click and dim with their line
            labels.append('<g data-edge="%d" data-style="%s">%s</g>'
                          % (i, styles[i], _pill_svg(pill_of[i], ox, oy)))
    body.extend(labels)
    body.append(key)
    if strip:
        body.append('<rect x="20" y="%s" width="%s" height="%s" rx="8" %s/>'
                    % (num(strip_y), num(width - 40), num(strip_h), STRIP_STYLE))
        body.append(text(34, strip_y + 14, "Evidence (%d of %d links; the HTML page lists all)"
                         % (len(strip), sum(1 for e in view.edges if e.status != STRUCTURAL)),
                         10.5, "#475569", weight="700"))
        for k, s in enumerate(strip):
            body.append(text(34, strip_y + 16 + STRIP_LINE * (k + 1) - 5, s, STRIP_SIZE,
                             "#475569", mono=True))
    body.append(leg)
    body.append(notes_block(view.notes + L.notes, 30, notes_y, note_w))
    return svg_doc(width, height, "".join(body), title=view.title)


# ------------------------------------------------------------------ HTML

def edge_data(view: ViewGraph) -> List[dict]:
    """Everything the page's side panel shows, one record per line (index = ``data-edge``)."""
    by_id = {n.id: n for n in view.nodes}

    def name(nid: str) -> str:
        n = by_id.get(nid)
        return n.label if n is not None else nid

    out = []
    for i, e in enumerate(view.edges):
        out.append({
            "i": i, "from": name(e.src), "to": name(e.dst), "label": e.label,
            "status": e.status, "kind": e.kind, "style": line_style(e.status, e.kind),
            "evidence": [{"repo": x.repo or "", "path": x.path, "line": x.line,
                          "loc": "%s:%s" % (x.path, x.line), "text": x.text}
                         for x in e.evidence],
        })
    return out


def _json_for_script(data: object) -> str:
    """JSON safe inside ``<script type="application/json">``: no ``</`` or ``<!--`` can
    close or confuse the element."""
    s = json.dumps(data, ensure_ascii=False, indent=None)
    # a URL in code text is escaped too (JSON reads ``\/`` and ``\u003d`` back as the
    # original), so the page itself names no URL and no src=/href= attribute
    s = s.replace("://", ":\\/\\/").replace("src=", "src\\u003d").replace("href=", "href\\u003d")
    return (s.replace("</", "<\\/").replace("<!--", "<\\u0021--")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


_CSS = """
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;font-family:"Segoe UI",Arial,sans-serif;color:#0f172a;background:#f1f5f9}
.wrap{display:flex;gap:16px;align-items:flex-start;padding:16px}
.map{flex:1 1 auto;min-width:0;overflow:auto;background:#fff;border-radius:8px;border:1px solid #e2e8f0}
.map svg{display:block;max-width:none}
.map g[data-edge]{cursor:pointer}
.map g[data-edge].dim{opacity:.12}
.map g[data-edge].sel path[id^="edge-"]{stroke-width:4}
aside{flex:0 0 400px;max-width:40vw;position:sticky;top:16px;max-height:calc(100vh - 32px);
overflow:auto;background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:14px}
aside h2{font-size:15px;margin:0 0 8px}
aside input{width:100%;padding:7px 9px;border:1px solid #cbd5e1;border-radius:6px;font-size:13px}
.hint{color:#64748b;font-size:12px;margin:8px 0}
ul.links{list-style:none;margin:8px 0 0;padding:0}
ul.links li{margin:0}
ul.links button{width:100%;text-align:left;background:none;border:0;border-bottom:1px solid #f1f5f9;
padding:6px 4px;font:inherit;font-size:12.5px;cursor:pointer;color:#0f172a}
ul.links button:hover,ul.links button:focus{background:#f1f5f9}
ul.links .repos{color:#64748b}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:9px;margin-left:6px;
border:1px solid #cbd5e1;color:#334155}
.tag.partial{color:#b45309;border-color:#fcd34d;background:#fffbeb}
.tag.loose{color:#b91c1c;border-color:#fca5a5;background:#fef2f2}
.tag.shared_code{color:#a16207;border-color:#fde68a}
table{border-collapse:collapse;width:100%;font-size:12px;margin-top:8px}
th,td{text-align:left;vertical-align:top;border-bottom:1px solid #e2e8f0;padding:5px 6px}
th{color:#475569;font-weight:600}
td.mono,td code{font-family:Consolas,monospace;word-break:break-all}
.back{margin-top:8px;font-size:12px;background:none;border:0;color:#2563eb;cursor:pointer;padding:0}
@media (max-width:900px){.wrap{flex-direction:column}aside{flex:none;max-width:none;width:100%;position:static}}
"""

_JS = """
(function(){
var edges=JSON.parse(document.getElementById('edge-data').textContent);
var groups=document.querySelectorAll('svg g[data-edge]');
var panel=document.getElementById('panel'),q=document.getElementById('q');
var selected=-1;
function el(tag,cls,txt){var e=document.createElement(tag);if(cls)e.className=cls;
if(txt!==undefined)e.textContent=txt;return e;}
function matches(d,s){if(!s)return true;s=s.toLowerCase();
var t=d.label+' '+d.from+' '+d.to+' '+d.status+' '+d.kind;
d.evidence.forEach(function(x){t+=' '+x.repo+' '+x.path+':'+x.line+' '+x.text;});
return t.toLowerCase().indexOf(s)>=0;}
function tag(d){var t=el('span','tag '+d.style,d.style==='shared_code'?'shared code':d.status);return t;}
function showList(){
selected=-1;mark();
panel.textContent='';
panel.appendChild(el('p','hint','Click a line or its label on the map, or pick one here, to see the exact file:line evidence behind it.'));
var ul=el('ul','links');
edges.forEach(function(d){
var li=el('li'),b=el('button');b.type='button';b.setAttribute('data-pick',d.i);
b.appendChild(el('span','',d.label||'(link)'));b.appendChild(tag(d));
b.appendChild(el('div','repos',d.from+' \\u2192 '+d.to));
li.appendChild(b);ul.appendChild(li);});
panel.appendChild(ul);filter();}
function showEdge(i){
var d=edges[i];if(!d)return;
selected=i;mark();
panel.textContent='';
var back=el('button','back','\\u2190 all links');back.type='button';back.onclick=showList;
panel.appendChild(back);
var h=el('h2','',d.label||'(link)');h.appendChild(tag(d));panel.appendChild(h);
panel.appendChild(el('div','hint',d.from+' \\u2192 '+d.to));
if(!d.evidence.length){panel.appendChild(el('p','hint','No file:line evidence was recorded for this link.'));return;}
var t=el('table'),hr=el('tr');
['Repo','File','Line','Code'].forEach(function(c){hr.appendChild(el('th','',c));});
t.appendChild(hr);
d.evidence.forEach(function(x){var r=el('tr');
r.appendChild(el('td','',x.repo||''));r.appendChild(el('td','mono',x.path));
r.appendChild(el('td','',String(x.line)));r.appendChild(el('td','mono',x.text));
t.appendChild(r);});
panel.appendChild(t);}
function mark(){Array.prototype.forEach.call(groups,function(g){
var on=Number(g.getAttribute('data-edge'))===selected;
if(on)g.classList.add('sel');else g.classList.remove('sel');});}
function filter(){var s=q.value.trim();
Array.prototype.forEach.call(groups,function(g){var d=edges[Number(g.getAttribute('data-edge'))];
if(d&&matches(d,s))g.classList.remove('dim');else g.classList.add('dim');});
Array.prototype.forEach.call(panel.querySelectorAll('button[data-pick]'),function(b){
var d=edges[Number(b.getAttribute('data-pick'))];b.parentNode.style.display=matches(d,s)?'':'none';});}
document.querySelector('.map').addEventListener('click',function(ev){
var g=ev.target.closest?ev.target.closest('g[data-edge]'):null;
if(g)showEdge(Number(g.getAttribute('data-edge')));});
panel.addEventListener('click',function(ev){var b=ev.target.closest('button[data-pick]');
if(b)showEdge(Number(b.getAttribute('data-pick')));});
q.addEventListener('input',filter);
showList();
})();
"""


def _html(view: ViewGraph, svg: str) -> str:
    body = svg.split("?>", 1)[-1]
    return (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>%s</title><style>%s</style></head><body>'
        '<div class="wrap"><div class="map">%s</div>'
        '<aside><h2>Links between repos</h2>'
        '<input id="q" type="search" placeholder="Search links by name, repo, file or code" '
        'aria-label="Search links">'
        '<div id="panel"></div></aside></div>'
        '<script type="application/json" id="edge-data">%s</script>'
        '<script>%s</script></body></html>\n'
        % (esc(view.title), _CSS, body, _json_for_script(edge_data(view)), _JS))


# ------------------------------------------------------------------ entry point

def render(view: ViewGraph) -> Dict[str, str]:
    """The repo link map as an Office-safe SVG and as a self-contained HTML page."""
    L = layout_for(view, node_size)
    styles = [line_style(e.status, e.kind) for e in view.edges]
    pills = place_pills(view, L, styles, [list(r) for r in L.routes], lambda e: e.label,
                        lambda g, gb: None)
    return {"svg": _svg(view, L, styles, pills),
            "html": _html(view, _svg(view, L, styles, pills, interactive=True))}
