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
        callers = {n.id for n in v.nodes if n.id.startswith("out:")
                   and all(e.src == n.id for e in v.edges if n.id in (e.src, e.dst))}
        for mod in STYLES:
            L = layout_for(v, mod.node_size)
            centre = [L.boxes[n.id] for n in v.nodes
                      if not n.id.startswith(("act:", "out:")) and n.id != "grp:?"]
            acts = [L.boxes[n.id] for n in v.nodes if n.id.startswith("act:")]
            outs = [L.boxes[n.id] for n in v.nodes
                    if n.id.startswith("out:") and n.id not in callers]
            assert centre and acts and outs, (v.scope, mod.__name__)
            left = min(b.x for b in centre)
            right = max(b.right for b in centre)
            assert all(b.right < left for b in acts), (v.scope, mod.__name__)
            assert all(b.x > right for b in outs), (v.scope, mod.__name__)
            # an outside caller (every line leaves it) stands left, under the entry points
            for c in callers:
                cb = L.boxes[c]
                assert cb.right < left and all(cb.y > a.y for a in acts), (v.scope, c)
            # "Not yet grouped" is last: a row under the centre
            if "grp:?" in L.boxes:
                assert L.boxes["grp:?"].y > max(b.bottom for b in centre), mod.__name__
            xs = sorted({round(b.x) for b in centre})
            assert len(xs) <= 5 or len({round(b.cx) for b in centre}) <= 5, xs
    assert "out:claims-portal" in {n.id for n in view_of(api_gd()).nodes}


def _box_texts(svg, link, name=None):
    """The texts inside the <a> of the box that links to ``link`` (and shows ``name``)."""
    root = ET.fromstring(svg)
    for a in root.iter(SVG + "a"):
        texts = [el.text or "" for el in a.iter(SVG + "text")]
        if a.get("href") == link and (name is None or name in texts):
            return texts
    raise AssertionError("no box links to %s" % link)


def test_group_box_line_caps_in_every_style():
    """A group box: name, [tech], up to 4 files then "… N more", a description in at most 2
    lines, one muted "+N links inside" line; never the resource or other-repo details."""
    long_desc = "This group does a great many things for the nightly claims run, " * 6
    base = batch_gd()
    gd = GitDiagram(base.repo, "", [GitGroup("Everything", "COBOL", ["cobol/", "cobol.pds/"],
                                             long_desc)] + base.groups[:2], [], [], True, "ok")
    v = view_of(gd)
    g = [n for n in v.nodes if n.id == "grp:Everything"][0]
    assert len(g.detail_lines) <= 4 + 1 + 1 + 1
    assert not any(x.startswith(("datasets:", "tables:", "also used")) for x in g.detail_lines)
    for mod in STYLES:
        texts = _box_texts(mod.render(v)["svg"], href(v.repo_path, g.link))
        files = [t for t in texts if t.endswith((".cbl",)) or t in ("CLMB400",)]
        assert len(files) <= 4, (mod.__name__, texts)
        assert any(t.startswith("… ") and "more" in t for t in texts), (mod.__name__, texts)
        desc = [t for t in texts if "great many" in t or "nightly claims" in t or "things" in t]
        assert 1 <= len(desc) <= 2 and desc[-1].endswith("…"), (mod.__name__, texts)
        # name + tech + 5 file lines + 2 description + 1 links line (+ icon text in A)
        assert len(texts) <= 11 + (mod is style_a), (mod.__name__, len(texts), texts)
    jobs = [n for n in v.nodes if n.id == "grp:Nightly jobs"][0]
    assert jobs.detail_lines[-1].startswith("+") and "links inside" in jobs.detail_lines[-1]
    assert jobs.muted == 1
    assert any(x.startswith("datasets:") for x in jobs.info)  # kept for the links report


def test_not_yet_grouped_is_compact():
    v = view_of(batch_gd())
    u = [n for n in v.nodes if n.id == "grp:?"][0]
    assert u.label == "Not yet grouped · 3 files" and u.role == "ungrouped"
    assert len(u.detail_lines) <= 4
    assert v.nodes.index(u) > max(v.nodes.index(n) for n in v.nodes
                                  if not n.id.startswith(("out:", "grp:?")))
    for mod in STYLES:
        svg = mod.render(v)["svg"]
        texts = _box_texts(svg, href(v.repo_path, u.link))
        assert len(texts) <= 1 + 4 + 2, (mod.__name__, texts)  # (+ icon text in A)
        root = ET.fromstring(svg)
        a = [a for a in root.iter(SVG + "a") if a.get("href") == href(v.repo_path, u.link)][0]
        assert any(el.get("stroke-dasharray") for el in a.iter()), mod.__name__


def test_shared_boxes_show_name_and_short_kind_and_are_neutral():
    v = view_of(batch_gd())
    shared = [n for n in v.nodes if n.role == "shared"]
    assert shared and all(not n.detail_lines for n in shared)
    daily = [n for n in shared if n.id == "dataset:CLAIMS.DAILY"][0]
    assert daily.sublabel == "GDG" and any("claims-online" in x for x in daily.info)
    assert daily.link == "jcl/CLMD100.jcl"  # the first file that uses it
    colours = set(group_colors(v).values())
    for mod in (style_b, style_d):
        texts = _box_texts(mod.render(v)["svg"], href(v.repo_path, daily.link),
                           "PROD.CLAIMS.DAILY")
        assert len(texts) <= 3, texts  # name and short kind (B: "[GDG]")
    b = style_b.render(v)["svg"]
    root = ET.fromstring(b)
    for a in root.iter(SVG + "a"):
        if a.get("href") == href(v.repo_path, daily.link) and \
                "PROD.CLAIMS.DAILY" in [t.text for t in a.iter(SVG + "text")]:
            fills = {el.get("fill") for el in a.iter() if el.tag in (SVG + "path", SVG + "rect")}
            assert not fills & colours and "#1168bd" not in fills, fills


def test_temporary_datasets_fold_into_the_job_line():
    v = view_of(batch_gd())
    assert not [n for n in v.nodes if "&&" in n.id]
    ln, = [e for e in v.edges if (e.src, e.dst) == ("grp:Nightly jobs", "grp:Claim pricing")
           and "via &&SORTED" in e.label]
    assert ln.status == "confirmed"
    assert any("&&SORTED" in u.dst for u in ln.underlying)
    jobs = [n for n in v.nodes if n.id == "grp:Nightly jobs"][0]
    assert any("&&SORTED" in x for x in jobs.info)


def test_group_line_to_an_entry_point_goes_to_its_handler_group():
    v = view_of(api_gd())
    assert not [e for e in v.edges if e.src.startswith("grp:") and e.dst.startswith("act:")]
    ln, = [e for e in v.edges if (e.src, e.dst) == ("grp:Mainframe clients", "grp:Controllers")
           and e.label.startswith("REST")]
    assert ln.status == "partial"
    # an outside caller still points at the entry point
    assert [e for e in v.edges if (e.src, e.dst) == ("out:claims-portal", "act:endpoint")]


def test_scheduler_and_shared_boxes_link():
    v = view_of(batch_gd())
    sch = [n for n in v.nodes if n.id == "act:scheduler"][0]
    assert sch.link in ("jcl/CLMD100.jcl", "jcl")
    svg = style_b.render(v)["svg"]
    assert 'href="%s"' % href(v.repo_path, sch.link) in svg


def test_links_carry_xlink_too():
    v = view_of(batch_gd())
    for mod in STYLES:
        svg = mod.render(v)["svg"]
        assert 'xmlns:xlink="http://www.w3.org/1999/xlink"' in svg
        root = assert_office_safe(svg)
        for a in root.iter(SVG + "a"):
            assert a.get("{http://www.w3.org/1999/xlink}href") == a.get("href")
    # no links: no xlink namespace (other levels unchanged)
    from conftest import fixture_view
    assert "xmlns:xlink" not in style_b.render(fixture_view("landscape"))["svg"]


def test_href_cuts_archive_member():
    assert href("claims-api", "lib/x.aar!/package.xml") == "../claims-api/lib/x.aar"


def test_tech_icon_matches_whole_words():
    from archdiag.render.common import group_icon
    from archdiag.views import VNode
    assert group_icon(VNode("grp:x", "x", "[JavaScript]", "group")) == "repo"
    assert group_icon(VNode("grp:x", "x", "[Java]", "group")) == "class"
    assert group_icon(VNode("grp:x", "x", "[Spring Boot Java]", "group")) == "class"
    assert group_icon(VNode("grp:x", "x", "[z/OS Connect]", "group")) == "endpoint"
    assert group_icon(VNode("grp:x", "x", "[COBOL copybooks]", "group")) == "program"


def test_first_five_group_colours_are_far_apart():
    from archdiag.render.common import GROUP_PALETTE
    import colorsys

    def hue(c):
        r, g, b = (int(c[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
        return colorsys.rgb_to_hsv(r, g, b)[0] * 360

    hs = [hue(c) for c in GROUP_PALETTE[:5]]
    for i in range(5):
        for j in range(i + 1, 5):
            d = abs(hs[i] - hs[j])
            assert min(d, 360 - d) >= 25, (GROUP_PALETTE[i], GROUP_PALETTE[j])


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
