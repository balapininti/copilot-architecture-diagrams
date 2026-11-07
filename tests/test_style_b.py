from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from conftest import OUT, assert_office_safe, fixture_view
from archdiag.layout import layout_for
from archdiag.render import style_b
from archdiag.views import VEdge, VGroup, VNode, ViewGraph

CASES = [("landscape", None), ("application", "claims-online"), ("flow_job", "CLMD100"),
         ("flow_tx", "claims/:id"), ("repomap", None)]


def _fence(md):
    return md.split("```mermaid", 1)[1].split("```", 1)[0]


def _texts(svg):
    return [(t.text or "") for t in ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}text")]


def test_svg_office_safe():
    for level, scope in CASES:
        assert_office_safe(style_b.render(fixture_view(level, scope))["svg"])


def test_mermaid_structure():
    v = fixture_view("landscape", None)
    md = style_b.render(v)["md"]
    assert md.startswith("# ")
    assert "```mermaid\nflowchart LR" in md
    assert md.count("subgraph") == len(v.groups)
    assert md.count("\n  end\n") == len(v.groups)
    assert "-.->" in md and "--x" in md
    assert "linkStyle" in md and "stroke:#dc2626" in md
    assert "classDef" in md
    assert "confirmed" in md.split("```", 2)[2]  # the legend follows the fence


def test_link_style_indexes_follow_link_order():
    v = fixture_view("landscape", None)
    fence = _fence(style_b.render(v)["md"])
    links = [ln for ln in fence.splitlines() if re.search(r"-->|-\.->|--x", ln)]
    assert len(links) == len(v.edges)
    full = {"confirmed": "stroke:#334155,stroke-width:2px",
            "partial": "stroke:#d97706,stroke-width:2px",
            "loose": "stroke:#dc2626,stroke-width:2px",
            "shared_code": "stroke:#a16207,stroke-width:2px,stroke-dasharray:7 4"}
    arrow = {"loose": "--x", "partial": "-.->", "confirmed": "-->", "shared_code": "-->"}
    seen = set()
    for i, (e, ln) in enumerate(zip(v.edges, links)):
        st = style_b.line_style(e.status, e.kind)
        seen.add(st)
        assert arrow[st] in ln
        assert "  linkStyle %d %s\n" % (i, full[st]) in fence + "\n"
    assert seen == {"confirmed", "partial", "loose", "shared_code"}
    assert fence.count("linkStyle") == len(v.edges)


def _tricky():
    return ViewGraph(
        title='Tricky "title"', level="landscape", scope=None,
        nodes=[VNode(id="program:A/B:C", label='say "hi"', sublabel="x <y> & z",
                     kind="program", group="g:1"),
               VNode(id="table:CLM#01", label="CLM#01", kind="table", group="g:1"),
               VNode(id="missing:x/y", label="&&SORTED", kind="missing", status="loose")],
        edges=[VEdge("program:A/B:C", "table:CLM#01", 'reads "it"'),
               VEdge("program:A/B:C", "missing:x/y", "calls", status="loose")],
        groups=[VGroup("g:1", 'grp "q"', "#3b82f6")], notes=[])


def test_mermaid_escapes_quotes_and_ids():
    out = style_b.render(_tricky())
    md = out["md"]
    fence = _fence(md)
    assert "say #quot;hi#quot;" in md
    assert 'say "hi"' not in md
    ids = re.findall(r"^\s*(n\d+)[\[\(]", md, re.M)
    assert ids == ["n0", "n1", "n2"]
    for ln in fence.splitlines():
        if "-->" in ln or "--x" in ln:
            assert ":" not in ln.split("|")[0] and "/" not in ln.split("|")[0]
    assert_office_safe(out["svg"])


def test_cylinders_for_tables():
    for level, scope in CASES:
        v = fixture_view(level, scope)
        svg = style_b.render(v)["svg"]
        n = sum(1 for x in v.nodes if x.kind in ("table", "dataset", "vsam", "gdg", "datastore"))
        assert len(re.findall("<ellipse", svg)) >= n
    v = fixture_view("flow_job", "CLMD100")
    assert "<ellipse" in style_b.render(v)["svg"]


def test_c4_boxes_and_three_lines():
    svg = style_b.render(fixture_view("landscape", None))["svg"]
    for c in ("#1168bd", "#999999", "#438dd5"):
        assert c in svg
    ts = _texts(svg)
    assert any(t.startswith("[Application: ") for t in ts)
    assert any(t.endswith(" [repo]") for t in ts)


def test_lines_keep_certainty_types():
    svg = style_b.render(fixture_view("landscape", None))["svg"]
    assert 'stroke-dasharray="3 4"' in svg and "#d97706" in svg
    assert 'stroke="#dc2626"' in svg and "<circle" in svg
    assert 'stroke-dasharray="7 4"' in svg


def _rects(root, pred):
    out = []
    for r in root.iter("{http://www.w3.org/2000/svg}rect"):
        if pred(r):
            out.append((float(r.get("x")), float(r.get("y")), float(r.get("width")),
                        float(r.get("height"))))
    return out


def _hit(a, b):
    return (min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]) > 0.5
            and min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]) > 0.5)


def test_pills_inside_canvas_and_boxes_do_not_overlap():
    for level, scope in CASES:
        v = fixture_view(level, scope)
        root = ET.fromstring(style_b.render(v)["svg"])
        w, h = float(root.get("width")), float(root.get("height"))
        for x, y, pw, ph in _rects(root, lambda r: r.get("id", "").startswith("pill-")):
            assert 0 <= x and x + pw <= w and 0 <= y and y + ph <= h
        # node boxes: filled rects with rx=6 (cylinders and persons are other shapes)
        boxes = _rects(root, lambda r: r.get("rx") == "6")
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                assert not _hit(a, b), (level, a, b)


def test_pill_covers_no_box():
    for level, scope in CASES:
        root = ET.fromstring(style_b.render(fixture_view(level, scope))["svg"])
        boxes = _rects(root, lambda r: r.get("rx") == "6")
        for p in _rects(root, lambda r: r.get("id", "").startswith("pill-")):
            for b in boxes:
                assert not _hit(p, b), (level, p, b)


REAL_KINDS = [
    # (id, kind drawn, real_kind, sublabel, expected second line)
    ("copybook:CLMREC", "program", "copybook", "copybook · shared-copybooks", "[Copybook: COBOL]"),
    ("zosapi:GET /z", "endpoint", "zosapi", "z/OS Connect API · claims-online",
     "[API: z/OS Connect]"),
    ("endpoint:GET /a", "endpoint", "", "REST endpoint · claims-api", "[Endpoint: REST]"),
    ("transaction:CLMI", "transaction", "", "CICS transaction · claims-online",
     "[CICS transaction]"),
    ("map:CLMM01", "map", "", "3270 map · claims-online", "[BMS map]"),
    ("utility:SORT", "utility", "", "STEP010", "[Utility]"),
    ("program:P", "program", "", "COBOL program · claims-online", "[Program: COBOL]"),
    ("mqprocess:Q", "queue", "mqprocess", "MQ process · claims-online", "[MQ process]"),
    ("queue:Q", "queue", "", "IBM MQ queue", "[Queue: IBM MQ]"),
    ("table:T", "table", "", "DB2 table", "[Table: DB2]"),
    ("notanalyzed:D", "notanalyzed", "", "asm · not analyzed · claims-batch",
     "[Not analyzed: asm]"),
    ("program:N", "neighbor", "program", "COBOL program · claims-batch",
     "[COBOL program · neighbor]"),
    ("copybook:N", "neighbor", "copybook", "copybook · shared-copybooks",
     "[COBOL copybook · neighbor]"),
]


def test_every_real_kind_is_labelled_by_what_it_is():
    for nid, kind, real, sub, want in REAL_KINDS:
        v = ViewGraph(title="K", level="landscape", scope=None,
                      nodes=[VNode(id=nid, label="X", sublabel=sub, kind=kind, real_kind=real)],
                      edges=[], groups=[], notes=[])
        out = style_b.render(v)
        assert want in _texts(out["svg"]), (nid, _texts(out["svg"]))
        assert "<br/>%s" % style_b.mm(want) in out["md"], (nid, out["md"])


def test_fixture_views_keep_real_kind():
    texts = " ".join(_texts(style_b.render(fixture_view("application", "claims-online"))["svg"]))
    assert "[API: z/OS Connect]" in texts and "[MQ process]" in texts
    assert "[COBOL copybook · neighbor]" in texts
    assert "[Neighbor]" not in texts


def test_writes_samples():
    OUT.mkdir(exist_ok=True)
    for level, scope in CASES:
        out = style_b.render(fixture_view(level, scope))
        name = "style_b-%s%s" % (level.split("_")[0], "-" + re.sub(r"\W", "_", scope) if scope else "")
        (OUT / (name + ".svg")).write_text(out["svg"], encoding="utf-8")
        (OUT / (name + ".md")).write_text(out["md"], encoding="utf-8")


def test_person_and_external_colors():
    v = ViewGraph(title="P", level="landscape", scope=None,
                  nodes=[VNode(id="person:u", label="User", sublabel="Uses it", kind="person"),
                         VNode(id="external:x", label="X", sublabel="outside", kind="external"),
                         VNode(id="program:a", label="A", kind="program")],
                  edges=[VEdge("person:u", "program:a", "uses")], groups=[], notes=[])
    svg = style_b.render(v)["svg"]
    assert "#08427b" in svg and "#999999" in svg and "#1168bd" in svg
    assert_office_safe(svg)


def test_azure_devops_copy_uses_the_wiki_fence():
    # GitHub reads ```mermaid; Azure DevOps wikis read ::: mermaid. One file each, the same
    # diagram, so neither shows the other's block as raw text.
    out = style_b.render(fixture_view("landscape"))
    assert "::: mermaid" not in out["md"]
    az = out["azure.md"]
    assert "```" not in az
    body = az.split("::: mermaid\n", 1)[1].split("\n:::", 1)[0]
    assert body.strip() == _fence(out["md"]).strip()
