"""The gitdiagram view drawn in the four SVG styles (Task 5): the context layout with entry
points on the left and outside stubs on the right, boxes that open their file or folder,
the overview above the picture, and the Scheduler's grey "starts" lines with their own
legend entry (spec 4.2, 4.3 and 10.3)."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from conftest import assert_office_safe, fixture_resolved, svg_edge_encodings
from test_gitdiagram_view import batch_gd, view_of

from archdiag.gitdiagram import GitDiagram, GitGroup
from archdiag.layout import layout_for
from archdiag.render import style_a, style_b, style_c, style_d
from archdiag.render.common import (CONFIRMED_COLOR, LINE_COLORS, LOOSE_COLOR, PARTIAL_COLOR,
                                    SHARED_COLOR, STARTS_LEGEND, group_colors, href,
                                    line_style, overview_block)
from archdiag.views.common import STRUCTURAL

STYLES = (style_a, style_b, style_c, style_d)
SVG = "{http://www.w3.org/2000/svg}"
GREY = "#94a3b8"
LEGEND = "starts — the job exists; who schedules it isn't in these repos"


def api_gd():
    p = "src/main/java/com/acme/claims/"
    return GitDiagram("claims-api", "Spring Boot claims API.", [
        GitGroup("Controllers", "Java", [p + "ClaimController.java"], "REST entry"),
        GitGroup("Repositories", "Java", [p + "*Repository.java"]),
        GitGroup("Mainframe clients", "Java", [p + "*Client.java", p + "MqClaimGateway.java",
                                               p + "AuditPublisher.java"]),
        GitGroup("Config", "YAML", ["src/main/resources/"]),
    ], [], [], True, "ok")


def _texts(svg):
    root = ET.fromstring(svg)
    return [el.text or "" for el in root.iter(SVG + "text")]


def _hrefs(svg):
    root = ET.fromstring(svg)
    return [el.get("href") for el in root.iter(SVG + "a")]


def test_boxes_are_links_in_every_style():
    v = view_of(batch_gd())
    groups = [n for n in v.nodes if n.kind == "group" and n.link]
    assert len(groups) >= 3
    for mod in STYLES:
        svg = mod.render(v)["svg"]
        assert_office_safe(svg)
        found = _hrefs(svg)
        for n in groups:
            want = href(v.repo_path, n.link)
            assert want in found, (mod.__name__, n.id, want, found)
        # an <a> wraps a box, never sits empty
        root = ET.fromstring(svg)
        assert all(len(list(a)) for a in root.iter(SVG + "a")), mod.__name__


def test_href_encodes_spaces_and_hash():
    assert href("client repos/claims#1", "jcl/CLMD100.jcl") == \
        "../client%20repos/claims%231/jcl/CLMD100.jcl"
    assert href("claims-batch", "cobol") == "../claims-batch/cobol"
    assert href("a b", "x y/z#q.cbl") == "../a%20b/x%20y/z%23q.cbl"
    # Windows separators and a leading ./ do not leak into the URL
    assert href(".\\client repos\\claims", "jcl\\A.jcl") == "../client%20repos/claims/jcl/A.jcl"


def test_overview_drawn_in_every_style():
    text = ("Nightly claims batch: CLMD100 extracts the claims, prices them with CLMB200 and "
            "CLMB210 & posts payments through CLMB300; the procs hold the shared steps.")
    gd = batch_gd()
    gd.overview = text
    v = view_of(gd)
    for mod in STYLES:
        svg = mod.render(v)["svg"]
        assert_office_safe(svg)
        joined = " ".join(" ".join(_texts(svg)).split())
        assert text in joined, mod.__name__
    frag, h = overview_block(text, 400.0)
    assert h > 0 and frag.count("<text") >= 2  # wrapped over several lines
    assert overview_block("", 400.0) == ("", 0.0)


def test_overview_moves_the_picture_down_and_grows_the_canvas():
    gd = batch_gd()
    gd.overview = ""
    plain = view_of(gd)
    gd2 = batch_gd()
    gd2.overview = "A paragraph. " * 40
    with_ov = view_of(gd2)
    for mod in STYLES:
        h0 = float(ET.fromstring(mod.render(plain)["svg"]).get("height"))
        h1 = float(ET.fromstring(mod.render(with_ov)["svg"]).get("height"))
        assert h1 > h0 + 30, mod.__name__


def test_structural_line_style_and_legend():
    assert line_style(STRUCTURAL, "sequence") == "structural"
    assert LINE_COLORS["structural"] == GREY
    assert STARTS_LEGEND == LEGEND
    assert GREY not in (CONFIRMED_COLOR, PARTIAL_COLOR, LOOSE_COLOR, SHARED_COLOR)
    v = view_of(batch_gd())
    starts = [i for i, e in enumerate(v.edges) if e.status == STRUCTURAL]
    assert starts
    for mod in STYLES:
        svg = mod.render(v)["svg"]
        enc = svg_edge_encodings(svg)
        for i in starts:
            assert enc[i] == (GREY, ""), (mod.__name__, enc[i])
        assert LEGEND in _texts(svg), mod.__name__
    # no structural line: no "starts" legend entry
    v2 = view_of(api_gd())
    assert not [e for e in v2.edges if e.status == STRUCTURAL]
    for mod in STYLES:
        assert LEGEND not in _texts(mod.render(v2)["svg"]), mod.__name__


def test_gitdiagram_layout_columns():
    for v in (view_of(batch_gd()), view_of(api_gd())):
        for mod in STYLES:
            L = layout_for(v, mod.node_size)
            centre = [L.boxes[n.id] for n in v.nodes
                      if not n.id.startswith(("act:", "out:"))]
            acts = [L.boxes[n.id] for n in v.nodes if n.id.startswith("act:")]
            outs = [L.boxes[n.id] for n in v.nodes if n.id.startswith("out:")]
            assert centre and acts and outs, (v.scope, mod.__name__)
            left = min(b.x for b in centre)
            right = max(b.right for b in centre)
            assert all(b.right < left for b in acts), (v.scope, mod.__name__)
            assert all(b.x > right for b in outs), (v.scope, mod.__name__)
            xs = sorted({round(b.x) for b in centre})
            assert len(xs) <= 5 or len({round(b.cx) for b in centre}) <= 5, xs


def test_group_colours_are_distinct_stable_and_not_line_colours():
    v = view_of(batch_gd())
    c = group_colors(v)
    named = [n.id for n in v.nodes if n.kind == "group" and n.id != "grp:?"]
    assert len({c[g] for g in named}) == len(named)
    lines = {CONFIRMED_COLOR, PARTIAL_COLOR, LOOSE_COLOR, SHARED_COLOR, GREY}
    assert not lines & set(c.values())
    # by sorted group name: dropping a group does not recolour the ones before it
    gd = batch_gd()
    gd.groups = [g for g in gd.groups if g.name != "Procs"]
    c2 = group_colors(view_of(gd))
    assert c2["grp:Claim pricing"] == c["grp:Claim pricing"]
    assert c2["grp:Nightly jobs"] == c["grp:Nightly jobs"]


def test_group_boxes_show_their_tech_and_actors_their_icon():
    v = view_of(batch_gd())
    svg = style_a.render(v)["svg"]
    texts = _texts(svg)
    assert "CBL" in texts and "JCL" in texts  # COBOL and JCL group icons
    b = style_b.render(v)["svg"]
    # every group's files are on its box
    assert "CLMB200.cbl" in _texts(b) and "CLMEXT.proc" in _texts(b)


def test_special_characters_in_overview_and_group_names_parse():
    name = 'Pay & "Post" [v2] | <A>'
    base = batch_gd()
    gd = GitDiagram(base.repo, name, [GitGroup(name, "JCL", ["jcl/", "jcl.pds/"])]
                    + base.groups[1:], [], [], True, "ok")
    v = view_of(gd)
    assert any(n.label == name for n in v.nodes)
    for mod in STYLES:
        svg = mod.render(v)["svg"]
        assert_office_safe(svg)
        assert 'Pay & "Post" [v2] | <A>' in " ".join(_texts(svg)), mod.__name__


def test_deterministic():
    for gd in (batch_gd(), api_gd()):
        r = fixture_resolved()
        for mod in STYLES:
            a = mod.render(view_of(gd, r))
            b = mod.render(view_of(gd, r))
            assert a == b, mod.__name__
