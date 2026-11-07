from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skill" / "architecture-diagrams" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

ESTATE = Path(__file__).parent / "fixtures" / "claims-estate"
OUT = Path(__file__).parent / "out"

_FIXTURE = {}


def fixture_view(level, scope=None):
    """The view ``level`` / ``scope`` of the claims estate (scan, resolve, default groups and
    build_view, with the estate's own config), each step cached for the whole session."""
    from archdiag.config import load_config
    from archdiag.groups import default_groups
    from archdiag.resolve import resolve
    from archdiag.scan import scan_workspace
    from archdiag.views import build_view

    if "r" not in _FIXTURE:
        cfg = load_config(ESTATE / "architecture-diagrams")
        _FIXTURE["r"] = resolve(scan_workspace(ESTATE, cfg), cfg)
        _FIXTURE["g"] = default_groups(_FIXTURE["r"])
    key = (level, scope)
    if key not in _FIXTURE:
        _FIXTURE[key] = build_view(_FIXTURE["r"], _FIXTURE["g"], level, scope)
    return _FIXTURE[key]


OFFICE_UNSAFE_TAGS = {"filter", "style", "use", "marker", "foreignObject", "image", "script"}


def assert_office_safe(svg):
    """The SVG parses, uses none of the tags Word and PowerPoint drop, and names no URL
    other than the SVG namespace."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(svg)
    tags = {el.tag.split("}")[-1] for el in root.iter()}
    bad = tags & OFFICE_UNSAFE_TAGS
    assert not bad, "Office-unsafe tags: %s" % sorted(bad)
    rest = svg.replace("http://www.w3.org", "")
    assert "http://" not in rest and "https://" not in rest, "SVG names a URL"
    assert "url(" not in svg, "SVG references a paint server or filter by url()"
    for el in root.iter():
        assert "style" not in el.attrib, "style attribute on <%s>" % el.tag
    return root


# ------------------------------------------------------------------ line encoding

def expected_line(status, kind):
    """(color, dash) the legend promises for a line of this status and kind: dash is the
    SVG dasharray ("" for solid)."""
    import re
    from archdiag.render.common import LINE_COLORS, _LINE_ATTRS, line_style

    key = line_style(status, kind)
    m = re.search(r'stroke-dasharray="([^"]+)"', _LINE_ATTRS[key])
    return LINE_COLORS[key], (m.group(1) if m else "")


def svg_edge_encodings(svg):
    """{edge index: (stroke, dasharray)} of the ``id="edge-N"`` paths of an SVG."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(svg)
    out = {}
    for el in root.iter("{http://www.w3.org/2000/svg}path"):
        i = el.get("id", "")
        if i.startswith("edge-"):
            out[int(i[5:])] = (el.get("stroke"), el.get("stroke-dasharray") or "")
    return out


def drawio_edge_encodings(xml):
    """{edge index: (strokeColor, dashPattern)} of the diagram's own edges (``e<N>``)."""
    import xml.etree.ElementTree as ET

    out = {}
    for c in ET.fromstring(xml).iter("mxCell"):
        cid = c.get("id", "")
        if c.get("edge") == "1" and cid.startswith("e") and cid[1:].isdigit():
            st = dict(kv.split("=", 1) for kv in c.get("style").split(";") if "=" in kv)
            dash = st.get("dashPattern", "") if st.get("dashed") == "1" else ""
            out[int(cid[1:])] = (st["strokeColor"], dash)
    return out


EXCALIDRAW_DASH = {"solid": "", "dotted": "3 4", "dashed": "7 4"}


def excalidraw_edge_encodings(js):
    """{edge index: (strokeColor, dash)} of the ``arrow-N`` elements."""
    import json

    out = {}
    for e in json.loads(js)["elements"]:
        if e["type"] == "arrow":
            out[int(e["id"][6:])] = (e["strokeColor"], EXCALIDRAW_DASH[e["strokeStyle"]])
    return out
