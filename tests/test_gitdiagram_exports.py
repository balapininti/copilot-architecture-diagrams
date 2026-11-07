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
    links = [u.get("link") for u in root.iter("UserObject")]
    for u in root.iter("UserObject"):  # the wrapper holds the label and id; one vertex inside
        cell = u.find("mxCell")
        assert cell is not None and cell.get("vertex") == "1" and u.get("id") and u.get("label")
    assert len(_linked(v)) >= 3
    for n in _linked(v):
        assert href(v.repo_path, n.link) in links
    assert OVERVIEW in " ".join(c.get("value") or "" for c in root.iter("mxCell"))
    cells = {c.get("id"): c for c in root.iter("mxCell")}
    ov = cells["overview"].find("mxGeometry")
    assert float(ov.get("y")) >= 0
    for c in root.iter("mxCell"):  # edges still point at ids that exist (wrapper ids included)
        for k in ("source", "target"):
            if c.get(k):
                assert c.get(k) in cells or c.get(k) in {u.get("id") for u in root.iter("UserObject")}


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


def test_mermaid_markdown_overview_and_notes_are_markdown_safe():
    base = batch_gd()
    gd = GitDiagram(base.repo, "Uses a_b *x*\n\n  <script> [y]", base.groups,
                    [{"from": "Nowhere box", "to": "Procs", "label": "", "note": ""}], [], True,
                    "ok")
    v = view_of(gd)
    v.problems.append("group 'a_b <c>': pattern x matches no file")
    v.notes.append(v.problems[-1])
    for key in ("md", "azure.md"):
        text = style_b.render(v)[key]
        assert "Uses a\\_b \\*x\\* &lt;script> \\[y\\]" in text, text
        assert "<script>" not in text
        assert "- group 'a\\_b &lt;c>': pattern x matches no file" in text


def test_report_md_escapes_angle_brackets_and_collapses_names():
    from archdiag.render.report import links_report, md
    from conftest import fixture_resolved
    assert md("a <b> c") == "a &lt;b> c"
    assert md("one\n  two\tthree") == "one two three"
    assert md("para one\n\npara two", lines=True) == "para one\n\npara two"
    base = batch_gd()
    gd = GitDiagram(base.repo, "Line one\nline two", [GitGroup("Pay\n<A>", "JCL\n1", ["jcl/"],
                                                               "first\nsecond")]
                    + base.groups[1:], [], [], True, "ok")
    text = links_report(view_of(gd), fixture_resolved())
    assert "### Pay &lt;A> \\[JCL 1\\]" in text
    assert "first second" in text
    assert "Line one\nline two" in text
