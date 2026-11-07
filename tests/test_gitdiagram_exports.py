"""Links and the overview in the editable exports (Task 6): draw.io, Mermaid, HTML, Excalidraw."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

from test_gitdiagram_render import _hrefs
from test_gitdiagram_view import batch_gd, view_of

from archdiag.gitdiagram import GitDiagram, GitGroup
from archdiag.render import style_a, style_b, style_c, style_d
from archdiag.render.common import href

OVERVIEW = "Nightly claims batch: CLMD100 extracts and CLMB300 posts."


def _view():
    gd = batch_gd()
    gd.overview = OVERVIEW
    return view_of(gd)


def _linked(v):
    return [n for n in v.nodes if n.link]


def test_drawio_cells_have_links():
    v = _view()
    xml = style_a.render(v)["drawio"]
    root = ET.fromstring(xml)
    links = [c.get("link") for c in root.iter("mxCell") if c.get("vertex") and c.get("link")]
    assert len(_linked(v)) >= 3
    for n in _linked(v):
        assert href(v.repo_path, n.link) in links
    assert OVERVIEW in " ".join(c.get("value") or "" for c in root.iter("mxCell"))


def test_mermaid_click_lines():
    v = _view()
    out = style_b.render(v)
    for key in ("md", "azure.md"):
        md = out[key]
        for i, n in enumerate(v.nodes):
            line = 'click n%d "%s"' % (i, href(v.repo_path, n.link)) if n.link else None
            if line:
                assert line in md, (key, line)
        assert md.index(OVERVIEW) < md.index("flowchart")
        assert len(re.findall(r"^\s*linkStyle \d+", md, re.M)) == len(v.edges)


def test_excalidraw_links():
    v = _view()
    doc = json.loads(style_d.render(v)["excalidraw"])
    links = [e.get("link") for e in doc["elements"] if e.get("link")]
    for n in _linked(v):
        assert href(v.repo_path, n.link) in links
    assert any(OVERVIEW in (e.get("text") or "").replace("\n", " ") for e in doc["elements"])


def test_html_box_links():
    v = _view()
    html = style_c.render(v)["html"]
    for n in _linked(v):
        assert 'href="%s"' % href(v.repo_path, n.link) in html
    assert OVERVIEW in " ".join(html.split())
    assert html.index(OVERVIEW) < html.index("<aside>")


def test_special_characters_escaped_everywhere():
    name = 'Pay & "Post" [v2] | <A>'
    base = batch_gd()
    gd = GitDiagram(base.repo, name, [GitGroup(name, "JCL", ["jcl/", "jcl.pds/"])]
                    + base.groups[1:], [], [], True, "ok")
    gd.overview = 'Pays & "posts" [v2] | <A>'
    v = view_of(gd)
    ET.fromstring(style_a.render(v)["drawio"])
    for mod in (style_a, style_b, style_c, style_d):
        ET.fromstring(mod.render(v)["svg"])
    json.loads(style_d.render(v)["excalidraw"])
    html = style_c.render(v)["html"]
    assert "<A>" not in html.split("<script")[0]
    b = style_b.render(v)
    for key in ("md", "azure.md"):
        md = b[key]
        assert "#quot;" in md
        for ln in md.splitlines():
            if re.match(r'\s*(n\d+\[|subgraph|n\d+ [-.>x]+\|)', ln):
                m = re.sub(r"</?b>|<br/>", "", ln)
                inner = m.split('"', 1)[1].rsplit('"', 1)[0] if '"' in m else ""
                assert not re.search(r"[\[\]|<]", inner), ln
