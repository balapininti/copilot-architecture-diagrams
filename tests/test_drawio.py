"""The draw.io file every style writes next to its SVG (``render/drawio.py``)."""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET

import pytest

from conftest import ESTATE, drawio_cells, fixture_resolved, fixture_view
from archdiag.cli import main
from archdiag.layout import Box, layout_for
from archdiag.render import drawio, style_a, style_b, style_c, style_d
from archdiag.render.common import line_style
from archdiag.views import VEdge, VGroup, VNode, ViewGraph

STYLES = (("a", style_a), ("b", style_b), ("c", style_c), ("d", style_d))
LEVELS = (("landscape", None), ("application", "claims-online"),
          ("application", "claims-batch"), ("flow_job", "CLMD100"), ("flow_tx", "claims/:id"),
          ("flow_tx", "CLMI"), ("repomap", None))
LAYER_NAMES = ["Diagram", "Loose ends and gaps", "Shared code", "Legend"]
LAYER_IDS = ["1", "layer-loose", "layer-shared", "layer-legend"]


def _gitdiagram_view():
    from test_gitdiagram_view import batch_gd, view_of
    gd = batch_gd()
    gd.overview = "Nightly claims batch: CLMD100 extracts & CLMB300 posts."
    return view_of(gd)


def _views():
    for level, scope in LEVELS:
        yield fixture_view(level, scope)
    yield _gitdiagram_view()


def _all():
    """(what, view, cells) for every level in every style."""
    for v in _views():
        for name, mod in STYLES:
            yield "%s / style %s" % (v.title, name), v, drawio_cells(mod.render(v)["drawio"])


def _edges(cells):
    return [c for c in cells if c["cell"].get("edge") == "1"]


def _vertices(cells):
    return [c for c in cells if c["cell"].get("vertex") == "1"]


def _special_view():
    nodes = [VNode("dataset:&&SORTED", "&&SORTED", "temp <dataset>", kind="dataset", group="g1"),
             VNode("program:CLM#01", "CLM#01", "it's \"quoted\" {x}", kind="program", group="g1"),
             VNode("missing:x", "no reader found", "&&SORTED", kind="missing", status="loose")]
    edges = [VEdge("program:CLM#01", "dataset:&&SORTED", "write <&> {y}", number=1),
             VEdge("dataset:&&SORTED", "missing:x", "no reader found", status="loose")]
    return ViewGraph("Job <&> \"x\"", "application", "g1", nodes, edges,
                     [VGroup("g1", "a&b <c>", "#3b82f6")], notes=["note with <&> 'q'"])


# ------------------------------------------------------------------ the CLI writes it

def _estate(tmp_path):
    w = tmp_path / "estate"
    shutil.copytree(str(ESTATE), str(w))
    return w


@pytest.mark.parametrize("level,scope,base", [
    ("landscape", None, "landscape"),
    ("application", "claims-online", "application-claims-online"),
    ("flow", "CLMD100", "flow-clmd100"),
    ("flow", "CLMI", "flow-clmi"),
    ("gitdiagram", "claims-batch", "gitdiagram-claims-batch"),
])
def test_every_style_and_level_writes_a_drawio_file(tmp_path, capsys, level, scope, base):
    w = _estate(tmp_path)
    args = ["draw", "--workspace", str(w), "--level", level, "--style", "all"]
    rc = main(args + (["--scope", scope] if scope else []))
    out = capsys.readouterr().out
    assert rc == 0, out
    wrote = out[out.index("Wrote:"):out.index("Summary:")]
    d = w / "architecture-diagrams"
    for s in "abcd":
        p = d / ("%s-%s.drawio" % (base, s))
        assert p.is_file() and (d / ("%s-%s.svg" % (base, s))).is_file(), p.name
        assert p.name in wrote
        raw = p.read_bytes()
        assert b"\r" not in raw and raw.endswith(b"</mxfile>\n")
        root = ET.fromstring(raw.decode("utf-8"))
        assert root.tag == "mxfile" and root.find("diagram/mxGraphModel/root") is not None
        # the CLI passes the resolver's nodes: a box says where the thing was found
        assert any(c["data"].get("evidence") for c in _vertices(drawio_cells(raw.decode("utf-8"))))
    # what each style already wrote stays
    for name in ("%s-b.md", "%s-c.html", "%s-d.excalidraw"):
        assert (d / (name % base)).is_file()


def test_default_style_writes_one_drawio_file(tmp_path, capsys):
    w = _estate(tmp_path)
    assert main(["draw", "--workspace", str(w), "--level", "landscape"]) == 0
    out = capsys.readouterr().out
    names = sorted(p.name for p in (w / "architecture-diagrams").glob("*.drawio"))
    assert len(names) == 1 and names[0] in out


def test_same_bytes_on_a_second_run(tmp_path, capsys):
    w = _estate(tmp_path)
    args = ["draw", "--workspace", str(w), "--level", "flow", "--scope", "claims/:id",
            "--style", "all"]
    assert main(args) == 0
    d = w / "architecture-diagrams"
    first = {p.name: p.read_bytes() for p in d.glob("*.drawio")}
    assert len(first) == 4
    assert main(args) == 0
    capsys.readouterr()
    assert {p.name: p.read_bytes() for p in d.glob("*.drawio")} == first
    for v in _views():
        for _name, mod in STYLES:
            assert mod.render(v)["drawio"] == mod.render(v)["drawio"]


# ------------------------------------------------------------------ a file draw.io opens

def test_xml_parses_with_the_mxfile_skeleton_and_a_page():
    for v in _views():
        for name, mod in STYLES:
            text = mod.render(v)["drawio"]
            root = ET.fromstring(text)
            assert root.tag == "mxfile", name
            diagram = root.find("diagram")
            assert diagram.get("name") == v.title
            model = diagram.find("mxGraphModel")
            assert model.get("grid") == "1" and model.get("gridSize") == "10"
            assert model.get("page") == "1"
            # A3 landscape, or the diagram's size when larger
            assert int(model.get("pageWidth")) >= 1654 and int(model.get("pageHeight")) >= 1169
            cells = drawio_cells(text)
            assert cells[0]["id"] == "0" and cells[0]["cell"].get("parent") is None
            assert cells[1]["id"] == "1" and cells[1]["cell"].get("parent") == "0"
            assert "\r" not in text and text.endswith("</mxfile>\n")


def test_ids_are_unique_and_every_reference_resolves():
    for what, v, cells in _all():
        ids = [c["id"] for c in cells]
        assert all(ids) and len(set(ids)) == len(ids), what
        seen = set()
        for c in cells:
            for k in ("parent", "source", "target"):
                ref = c["cell"].get(k)
                assert ref is None or ref in set(ids), (what, c["id"], k, ref)
            if c["cell"].get("parent") is not None:  # a parent is written before its children
                assert c["cell"].get("parent") in seen, (what, c["id"])
            seen.add(c["id"])
        assert len(_edges(cells)) == len(v.edges), what
        L_groups = [c for c in cells if c["data"].get("kind") == "group" and "swimlane" in c["style"]]
        assert len([c for c in _vertices(cells) if c["wrapped"]]) == len(v.nodes) + len(L_groups)


def test_page_holds_every_cell():
    for v in _views():
        for name, mod in STYLES:
            text = mod.render(v)["drawio"]
            model = ET.fromstring(text).find("diagram/mxGraphModel")
            cells = drawio_cells(text)
            by_id = {c["id"]: c for c in cells}
            for c in _vertices(cells):
                g = c["cell"].find("mxGeometry")
                x, y = float(g.get("x")), float(g.get("y"))
                p = by_id.get(c["cell"].get("parent"))
                while p is not None:  # a child's geometry is relative to its container
                    pg = p["cell"].find("mxGeometry")
                    if pg is not None:
                        x, y = x + float(pg.get("x")), y + float(pg.get("y"))
                    p = by_id.get(p["cell"].get("parent"))
                what = (v.title, name, c["id"])
                assert x >= 0 and y >= 0, what
                assert x + float(g.get("width")) <= float(model.get("pageWidth")), what
                assert y + float(g.get("height")) <= float(model.get("pageHeight")), what


def test_geometry_is_on_the_10px_grid():
    for what, _v, cells in _all():
        for c in _vertices(cells):
            g = c["cell"].find("mxGeometry")
            for k in ("x", "y", "width", "height"):
                assert int(g.get(k)) % 10 == 0, (what, c["id"], k, g.get(k))
            assert int(g.get("width")) > 0 and int(g.get("height")) > 0


# ------------------------------------------------------------------ lines

def test_no_edge_has_waypoints():
    for what, _v, cells in _all():
        for c in _edges(cells):
            cell = c["cell"]
            assert cell.get("source") and cell.get("target"), (what, c["id"])
            assert not list(cell.iter("mxPoint")) and not list(cell.iter("Array")), (what, c["id"])
            g = cell.find("mxGeometry")
            assert g.get("relative") == "1" and len(g) == 0
            st = c["style"]
            assert st["edgeStyle"] == "orthogonalEdgeStyle" and st["rounded"] == "1"
            assert st["jettySize"] == "auto" and st["html"] == "1"


def test_edges_keep_the_side_the_layout_used():
    v = fixture_view("flow_tx", "CLMI")
    L = layout_for(v, style_a.node_size)
    edges = _edges(drawio_cells(style_a.render(v)["drawio"]))
    ported = 0
    for e, r, c in zip(v.edges, L.routes, edges):
        st = c["style"]
        out_, in_ = drawio.side_of(L.boxes[e.src], r[0]), drawio.side_of(L.boxes[e.dst], r[-1])
        if out_:
            assert (st["exitX"], st["exitY"]) == out_
            ported += 1
        else:
            assert "exitX" not in st
        if in_:
            assert (st["entryX"], st["entryY"]) == in_
        else:
            assert "entryX" not in st
    assert ported >= len(edges) // 2
    b = Box(100.0, 100.0, 200.0, 100.0)
    assert drawio.side_of(b, (300.0, 150.0)) == ("1", "0.5")
    assert drawio.side_of(b, (100.0, 125.0)) == ("0", "0.25")
    assert drawio.side_of(b, (150.0, 100.0)) == ("0.25", "0")
    assert drawio.side_of(b, (250.0, 200.0)) == ("0.75", "1")
    assert drawio.side_of(b, (200.0, 150.0)) is None  # inside: the side is not known
    assert drawio.side_of(b, (400.0, 150.0)) is None


def test_edges_keep_the_certainty_styling():
    for what, v, cells in _all():
        for e, c in zip(v.edges, _edges(cells)):
            st, style = c["style"], line_style(e.status, e.kind)
            want = {"confirmed": ("#334155", None), "partial": ("#d97706", "3 4"),
                    "loose": ("#dc2626", None), "shared_code": ("#a16207", "7 4"),
                    "structural": ("#94a3b8", None)}[style]
            assert st["strokeColor"] == want[0], (what, c["id"])
            assert (st.get("dashPattern") if st.get("dashed") == "1" else None) == want[1]
            assert st["endArrow"] == ("oval" if style == "loose" else "block")
            assert c["data"]["status"] == e.status and c["data"]["kind"] == e.kind


def test_an_edge_inside_one_group_belongs_to_it():
    v = fixture_view("flow_tx", "CLMI")
    cells = drawio_cells(style_a.render(v)["drawio"])
    by_id = {c["id"]: c for c in cells}
    inside = 0
    for c in _edges(cells):
        ps = by_id[c["cell"].get("source")]["cell"].get("parent")
        pt = by_id[c["cell"].get("target")]["cell"].get("parent")
        parent = c["cell"].get("parent")
        if ps == pt and ps.startswith("g"):  # both ends are members of one group
            assert parent == ps, c["id"]
            inside += 1
        else:
            assert parent in LAYER_IDS, c["id"]
    assert inside >= 3


def test_step_numbers_stay_in_the_label():
    v = fixture_view("flow_tx", "claims/:id")
    for _name, mod in STYLES:
        edges = _edges(drawio_cells(mod.render(v)["drawio"]))
        for e, c in zip(v.edges, edges):
            assert e.number is not None
            assert c["label"].startswith("(%d)" % e.number), c["label"]
            assert c["data"]["step"] == str(e.number)
        assert any(c["label"] == "(1) uses" for c in edges)


# ------------------------------------------------------------------ boxes and groups

def test_groups_are_containers_with_children():
    seen = 0
    for what, v, cells in _all():
        by_id = {c["id"]: c for c in cells}
        groups = [c for c in cells if "swimlane" in c["style"] and c["id"] != "legend"]
        for g in groups:
            assert g["style"]["startSize"] == "24" and g["cell"].get("parent") == "1"
            kids = [c for c in _vertices(cells) if c["cell"].get("parent") == g["id"]]
            assert kids, (what, g["id"])
            gg = g["cell"].find("mxGeometry")
            for k in kids:  # relative geometry, inside the group, below its title
                kg = k["cell"].find("mxGeometry")
                assert 0 <= int(kg.get("x")) and 24 <= int(kg.get("y")), (what, k["id"])
                assert int(kg.get("x")) + int(kg.get("width")) <= int(gg.get("width")), (what, k["id"])
                assert int(kg.get("y")) + int(kg.get("height")) <= int(gg.get("height")), (what, k["id"])
            seen += 1
        # every box of a drawn group that is on the Diagram layer is its child
        L_groups = {c["label"] for c in groups}
        for n, c in zip(v.nodes, [c for c in _vertices(cells) if c["id"].startswith("n")]):
            parent = by_id[c["cell"].get("parent")]
            if parent["id"].startswith("g"):
                assert n.group is not None and parent["label"] in L_groups
    assert seen >= 20


def test_only_laid_out_groups_are_drawn():
    v = ViewGraph("job", "flow_job", "J",
                  [VNode("job:J", "J", kind="job", group="g1"),
                   VNode("step:J#S1", "S1", kind="program", row="lane", group="g1")],
                  [VEdge("job:J", "step:J#S1", kind="sequence")],
                  [VGroup("g1", "app", "#3b82f6")])
    cells = drawio_cells(style_a.render(v)["drawio"])
    assert not [c for c in cells if c["data"].get("kind") == "group"]
    assert [c["cell"].get("parent") for c in cells if c["id"] in ("n0", "n1")] == ["1", "1"]


def test_shapes_follow_the_kind_of_thing():
    def shape(kind, real="", nid="x", **kw):
        return drawio.shape_of(VNode(nid, "X", kind=kind, real_kind=real, **kw))

    for kind in ("table", "datastore", "vsam", "cicsfile"):
        assert shape(kind).startswith("shape=cylinder3;") and "direction" not in shape(kind)
    assert shape("queue") == shape("queue", "mqprocess") != shape("table")
    assert "shape=cylinder3;direction=south" in shape("queue")  # a cylinder on its side
    assert shape("person").startswith("shape=umlActor;") and shape("actor") == shape("person")
    assert not shape("actor", nid="act:scheduler").startswith("shape=umlActor")
    for kind in ("job", "dataset", "gdg"):
        assert shape(kind).startswith("shape=document;")
    assert shape("job", "proc").startswith("shape=document;")
    assert shape("external") == shape("outside") == "ellipse;shape=cloud;"
    assert shape("endpoint").startswith("shape=hexagon;")
    assert shape("endpoint", "zosapi").startswith("shape=hexagon;")
    for kind in ("program", "class", "transaction", "application", "missing", "notanalyzed"):
        assert shape(kind).startswith("rounded=1;")
    # a neighbor keeps the shape of what it really is
    assert shape("neighbor", "table").startswith("shape=cylinder3;")
    # on the fixture: every style, the same shape for the same thing
    v = fixture_view("flow_tx", "CLMI")
    for _name, mod in STYLES:
        by = {c["label"].split("</b>")[0][3:]: c for c in _vertices(drawio_cells(mod.render(v)["drawio"]))}
        assert by["CLMS.CLAIM"]["style"]["shape"] == "cylinder3"
        assert by["CLM.RSP"]["style"].get("direction") == "south"
        assert "rounded" in by["CLMO100"]["style"]
        assert by["CLMS.CLAIM"]["style"]["html"] == "1"


def test_labels_are_html_with_a_bold_name_and_a_smaller_technology_line():
    v = fixture_view("flow_tx", "CLMI")
    cells = drawio_cells(style_a.render(v)["drawio"])
    c = next(c for c in cells if c["label"].startswith("<b>CLMO100</b>"))
    assert c["label"] == ('<b>CLMO100</b><br><font color="#64748b" style="font-size: 10px">'
                          'COBOL program · claims-online</font>')
    assert c["data"]["technology"] == "COBOL program · claims-online"
    assert c["data"]["kind"] == "program"
    b = drawio_cells(style_b.render(v)["drawio"])
    assert any(x["label"].startswith("<b>CLMO100</b><br>") and "[Program: COBOL]" in x["label"]
               for x in b)


def test_colours_follow_each_styles_svg():
    v = fixture_view("application", "claims-online")
    for name, mod in STYLES:
        by = {c["label"].split("</b>")[0][3:]: c["style"]
              for c in _vertices(drawio_cells(mod.render(v)["drawio"]))}
        # a "nothing found" box: red, or dotted orange when partly known, as in every SVG
        assert by["which program?"]["fillColor"] == "#fffbeb", name
        assert by["which program?"]["strokeColor"] == "#d97706" and by["which program?"]["dashed"] == "1"
        assert by["CLMO120"]["fillColor"] == "#fef2f2" and by["CLMO120"]["strokeColor"] == "#dc2626"
    fill = {name: {c["label"].split("</b>")[0][3:]: c["style"]
                   for c in _vertices(drawio_cells(mod.render(v)["drawio"]))}["CLMO100"]
            for name, mod in STYLES}
    assert fill["b"]["fillColor"] == style_b.BOX and fill["b"]["fontColor"] == "#ffffff"
    assert fill["a"]["fontColor"] == "#0f172a" and fill["a"]["fillColor"] != fill["b"]["fillColor"]
    assert fill["d"]["sketch"] == "1" and "sketch" not in fill["a"]


# ------------------------------------------------------------------ evidence

def test_a_confirmed_edge_carries_its_evidence():
    v = fixture_view("flow_tx", "CLMI")
    for _name, mod in STYLES:
        edges = _edges(drawio_cells(mod.render(v)["drawio"]))
        for e, c in zip(v.edges, edges):
            assert c["wrapped"]
            assert set(c["data"]) >= {"status", "kind", "evidence", "reason"}
            assert c["data"]["evidence"], c["id"]
            first = e.evidence[0]
            assert "%s/%s:%d" % (first.repo, first.path, first.line) in c["data"]["evidence"]
        c = next(c for e, c in zip(v.edges, edges) if e.status == "confirmed")
        assert c["data"]["status"] == "confirmed" and c["data"]["kind"] == "runtime"
        assert c["data"]["evidence"].startswith("claims-online/csd/CLAIMS.csd:4")
        assert c["data"]["reason"] == ""
        partial = next(c for e, c in zip(v.edges, edges) if e.status == "partial")
        assert partial["data"]["reason"]


def test_a_box_says_where_it_was_found_when_the_nodes_are_given():
    v = fixture_view("flow_tx", "CLMI")
    nodes = fixture_resolved().nodes
    for _name, mod in STYLES:
        cells = drawio_cells(mod.render(v, nodes=nodes)["drawio"])
        c = next(c for c in cells if c["label"].startswith("<b>CLMO100</b>"))
        assert c["data"]["evidence"] == "claims-online/cobol/CLMO100.cbl:2"
        missing = next(c for c in cells if c["label"].startswith("<b>CLMO120</b>"))
        assert missing["data"]["status"] == "loose" and missing["data"]["kind"] == "missing"


def test_evidence_lists_each_place_once_and_is_capped():
    from archdiag.model import Evidence
    ev = [Evidence("r", "a.cbl", k, "x") for k in (1, 1, 2)] + [Evidence("r", "b%d.cbl" % k, 3, "x")
                                                               for k in range(20)]
    s = drawio.evidence_text(ev)
    assert s.startswith("r/a.cbl:1; r/a.cbl:2; r/b0.cbl:3")
    assert s.endswith("; +12 more") and s.count(";") == 10


# ------------------------------------------------------------------ layers and the legend

def test_layers_are_children_of_the_root():
    for what, v, cells in _all():
        layers = [c for c in cells if c["cell"].get("parent") == "0"]
        assert [c["label"] for c in layers] == LAYER_NAMES, what
        assert [c["id"] for c in layers] == LAYER_IDS
        by_id = {c["id"]: c for c in cells}

        def layer(c):
            while c["cell"].get("parent") != "0":
                c = by_id[c["cell"].get("parent")]
            return c["label"]

        nodes = [c for c in _vertices(cells) if c["id"].startswith("n")]
        for n, c in zip(v.nodes, nodes):
            if n.kind == "missing":
                assert layer(c) == "Loose ends and gaps", (what, n.id)
            elif (n.real_kind or n.kind) == "copybook":
                assert layer(c) == "Shared code", (what, n.id)
            else:
                assert layer(c) == "Diagram", (what, n.id)
        order = {name: k for k, name in enumerate(["Diagram", "Shared code", "Loose ends and gaps"])}
        for e, c in zip(v.edges, _edges(cells)):
            style = line_style(e.status, e.kind)
            ends = [layer(by_id[c["cell"].get(k)]) for k in ("source", "target")]
            if style == "loose":
                assert layer(c) == "Loose ends and gaps", (what, c["id"])
            # hiding a layer never leaves a line with a hidden end
            assert order[layer(c)] >= max(order[x] for x in ends), (what, c["id"])
            if style == "shared_code" and layer(c) != "Loose ends and gaps":
                assert layer(c) == "Shared code", (what, c["id"])
            if style == "confirmed" and ends == ["Diagram", "Diagram"]:
                assert layer(c) == "Diagram", (what, c["id"])
        for c in cells:
            if c["id"].startswith("lg-") or c["id"] in ("legend", "notes"):
                assert layer(c) == "Legend", (what, c["id"])


def test_shared_code_and_loose_ends_are_on_their_layers_in_the_fixture():
    v = fixture_view("application", "claims-batch")
    cells = drawio_cells(style_a.render(v)["drawio"])
    shared = [c for c in cells if c["cell"].get("parent") == "layer-shared"]
    loose = [c for c in cells if c["cell"].get("parent") == "layer-loose"]
    assert len([c for c in shared if c["cell"].get("vertex")]) == 4   # the four copybooks
    assert len([c for c in shared if c["cell"].get("edge")]) == 5     # and the COPY lines
    assert len([c for c in loose if c["cell"].get("vertex")]) == 3
    assert all(c["data"].get("kind") == "missing" for c in loose if c["cell"].get("vertex"))


def test_the_legend_is_one_container_on_the_legend_layer():
    for what, v, cells in _all():
        legend = [c for c in cells if c["cell"].get("parent") == "layer-legend"]
        assert [c["id"] for c in legend] == ["legend"], what
        present = {line_style(e.status, e.kind) for e in v.edges}
        texts = {c["id"][8:] for c in cells if c["id"].startswith("lg-text-")}
        assert texts == present, what
        for c in cells:
            if c["id"].startswith("lg-") or c["id"] == "notes":
                assert c["cell"].get("parent") == "legend"
    v = fixture_view("flow_job", "CLMD100")
    notes = next(c for c in drawio_cells(style_a.render(v)["drawio"]) if c["id"] == "notes")
    assert "Also exists as: claims-batch/jcl/test/CLMD100.jcl" in notes["label"]


# ------------------------------------------------------------------ escaping

def test_special_characters_are_escaped():
    v = _special_view()
    for name, mod in STYLES:
        text = mod.render(v)["drawio"]
        root = ET.fromstring(text)  # parses: nothing raw got through
        assert root.find("diagram").get("name") == 'Job <&> "x"'
        cells = drawio_cells(text)
        by_id = {c["id"]: c for c in cells}
        # html labels: the text is escaped for html, and that again for the attribute
        assert by_id["title"]["label"] == 'Job &lt;&amp;&gt; "x"'
        assert by_id["g0"]["label"] == "a&amp;b &lt;c&gt;"
        assert "<b>&amp;&amp;SORTED</b>" in by_id["n0"]["label"], name
        assert "temp &lt;dataset&gt;" in by_id["n0"]["label"] or name == "b"
        assert "{x}" in by_id["n1"]["label"] or name == "b"
        assert by_id["e0"]["label"] == "(1) write &lt;&amp;&gt; {y}"
        assert "note with &lt;&amp;&gt; 'q'" in by_id["notes"]["label"]
        assert 'label="&lt;b&gt;&amp;amp;&amp;amp;SORTED&lt;/b&gt;' in text
        raw = text.replace("&amp;", "").replace("&lt;", "").replace("&gt;", "") \
                  .replace("&quot;", "").replace("&apos;", "").replace("&#10;", "")
        assert "&" not in raw, name


def test_control_characters_never_reach_the_file():
    v = ViewGraph("T\x00\x0b", "application", "x",
                  [VNode("a", "A\x01B", "line one\nline two", kind="program"),
                   VNode("b", "B", kind="program")],
                  [VEdge("a", "b", "call\x1f")], [])
    for _name, mod in STYLES:
        text = mod.render(v)["drawio"]
        cells = {c["id"]: c for c in drawio_cells(text)}
        assert cells["n0"]["label"].startswith("<b>AB</b>")
        assert cells["e0"]["label"] == "call"
