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
