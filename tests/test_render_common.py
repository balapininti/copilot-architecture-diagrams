from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from conftest import assert_office_safe
from archdiag.render.common import (ICONS, REPO_COLORS, arrowhead, esc, legend, line_attrs,
                                    loose_dot, notes_block, svg_doc, text_width, wrap)

ICON_KINDS = ("person page component class endpoint program utility job step dataset gdg vsam "
              "table queue transaction map cicsfile external notanalyzed repo application "
              "datastore neighbor missing more").split()


def test_esc():
    assert esc('&&SORTED <x> "q"') == "&amp;&amp;SORTED &lt;x&gt; &quot;q&quot;"
    assert esc("O'Brien") == "O&apos;Brien"


def test_text_width():
    assert text_width("abcd", 10) == pytest.approx(24.0)
    assert text_width("abcd", 10, mono=True) == pytest.approx(22.0)


def test_wrap():
    assert wrap("", 100, 10) == [""]
    assert wrap("one two three", 1000, 10) == ["one two three"]
    lines = wrap("one two three four five", 60, 10)
    assert all(text_width(s, 10) <= 60 for s in lines) and " ".join(lines) == "one two three four five"
    long = wrap("PROD.CLAIMS.VERY.LONG.DATASET.NAME.HERE", 80, 10)
    assert "".join(long) == "PROD.CLAIMS.VERY.LONG.DATASET.NAME.HERE"
    assert all(text_width(s, 10) <= 80 for s in long)


def test_line_attrs():
    assert 'stroke-dasharray="3 4"' in line_attrs("partial", "runtime")
    assert "#d97706" in line_attrs("partial", "runtime")
    c = line_attrs("confirmed", "runtime")
    assert 'stroke="#334155"' in c and 'stroke-width="2"' in c and "dasharray" not in c
    assert line_attrs("confirmed", "sequence") == c
    s = line_attrs("confirmed", "shared_code")
    assert 'stroke="#a16207"' in s and 'stroke-dasharray="7 4"' in s
    lo = line_attrs("loose", "runtime")
    assert 'stroke="#dc2626"' in lo and "dasharray" not in lo
    # a partly known or loose COPY is drawn by its certainty, never as confirmed shared code
    assert line_attrs("loose", "shared_code") == lo
    assert line_attrs("partial", "shared_code") == line_attrs("partial", "runtime")


def test_loose_dot_and_arrowhead():
    d = ET.fromstring(loose_dot(10, 20))
    assert d.tag == "circle" and d.get("r") == "6" and d.get("fill") == "#dc2626"
    a = ET.fromstring(arrowhead((0, 0), (100, 0), "#334155"))
    assert a.tag == "polygon" and a.get("fill") == "#334155"
    pts = [tuple(map(float, p.split(","))) for p in a.get("points").split()]
    assert (100.0, 0.0) in pts and all(x <= 100 for x, _ in pts)


def test_legend_only_present():
    frag, h = legend(0, 0, {"confirmed", "loose"})
    assert h > 0 and "loose end" in frag and "confirmed" in frag
    assert "partly known" not in frag and "shared code" not in frag
    frag, h = legend(0, 0, set())
    assert frag == "" and h == 0


def test_svg_doc_and_notes():
    body = notes_block(["Also exists as: a&b <c>.jcl"], 10, 20)
    svg = svg_doc(300, 200, body, title="CLM#01 & co")
    root = assert_office_safe(svg)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.find("{http://www.w3.org/2000/svg}title").text == "CLM#01 & co"
    assert "a&amp;b &lt;c&gt;.jcl" in svg


def test_repo_colors():
    assert REPO_COLORS == ("#3b82f6", "#16a34a", "#9333ea", "#ca8a04", "#ea580c", "#0891b2",
                           "#db2777", "#4f46e5")


def test_every_icon_is_office_safe():
    for kind in ICON_KINDS:
        assert kind in ICONS, kind
        frag = ICONS[kind](100, 100, "#3b82f6") + ICONS[kind](100, 100, "")
        assert_office_safe(svg_doc(200, 200, frag))
