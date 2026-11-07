from __future__ import annotations

import json
import re

import pytest

from conftest import OUT, assert_office_safe, fixture_view
from archdiag.render import style_c
from archdiag.views import VEdge, VNode, ViewGraph
from archdiag.model import Evidence

CASES = [("repomap", None), ("repomap", "claims-batch")]


def _json(html):
    m = re.search(r'<script type="application/json" id="edge-data">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


def test_svg_office_safe():
    for level, scope in CASES:
        assert_office_safe(style_c.render(fixture_view(level, scope))["svg"])


def test_html_offline():
    for level, scope in CASES:
        html = style_c.render(fixture_view(level, scope))["html"]
        assert "<script" in html and "src=" not in html
        assert "https://" not in html.replace("http://www.w3.org", "")
        assert "href=" not in html


def test_html_has_every_evidence():
    v = fixture_view("repomap", None)
    html = style_c.render(v)["html"]
    data = _json(html)
    assert len(data) == len(v.edges)
    for e, d in zip(v.edges, data):
        assert len(d["evidence"]) == len(e.evidence)
        for x in e.evidence:
            assert "%s:%s" % (x.path, x.line) in html
            assert any(r["path"] == x.path and r["line"] == x.line and r["text"] == x.text
                       for r in d["evidence"])


def test_every_edge_group_is_clickable():
    v = fixture_view("repomap", None)
    html = style_c.render(v)["html"]
    for i in range(len(v.edges)):
        assert 'data-edge="%d"' % i in html
    assert "confirmed (both ends found in code)" in html


def test_evidence_strip():
    svg = style_c.render(fixture_view("repomap", None))["svg"]
    assert "MqClaimGateway.java:" in svg and "CLMO100.cbl:" in svg
    assert "↔" in svg


def test_line_types_and_cards():
    svg = style_c.render(fixture_view("repomap", None))["svg"]
    assert 'stroke="#cbd5e1"' in svg and 'fill-opacity="0.08"' in svg
    assert "⎇ claims-api" in svg
    for part in ('stroke="#334155"', 'stroke-dasharray="3 4"', 'stroke="#dc2626"',
                 'stroke-dasharray="7 4"'):
        assert part in svg


def test_hostile_evidence_cannot_break_out():
    n1 = VNode(id="repo:a", label="a", kind="repo", detail_lines=["x.cbl"], highlight=1)
    n2 = VNode(id="repo:b", label="b", kind="repo", detail_lines=["y.cbl"], highlight=1)
    ev = [Evidence(repo=None, path="z.aar!/</script><b>.xml", line=3,
                   text="</script><script>alert(1)</script> <!-- &")]
    v = ViewGraph("t", "repomap", None, [n1, n2],
                  [VEdge("repo:a", "repo:b", "x</script>", evidence=ev)], [])
    out = style_c.render(v)
    assert_office_safe(out["svg"])
    html = out["html"]
    assert html.count("</script>") == 2  # the data block and the code, nothing more
    assert _json(html)[0]["evidence"][0]["text"].startswith("</script>")
    assert "textContent" in html and "innerHTML" not in html


def test_empty_and_no_evidence():
    v = ViewGraph("t", "repomap", None, [], [], [])
    assert "<svg" in style_c.render(v)["svg"]


def test_visual_outputs():
    OUT.mkdir(exist_ok=True)
    for name, (level, scope) in (("all", CASES[0]), ("claims-batch", CASES[1])):
        out = style_c.render(fixture_view(level, scope))
        (OUT / ("style_c-%s.svg" % name)).write_text(out["svg"], encoding="utf-8")
        (OUT / ("style_c-%s.html" % name)).write_text(out["html"], encoding="utf-8")


# ------------------------------------------------------------------ Batch C (C9)

def test_strip_adds_the_folder_when_base_names_collide():
    n1 = VNode(id="repo:a", label="a", kind="repo", detail_lines=["x.cbl"], highlight=1)
    n2 = VNode(id="repo:b", label="b", kind="repo", detail_lines=["y.cbl"], highlight=1)
    ev = [Evidence(repo="a", path="src/online/CLMREC.cpy", line=3, text="COPY CLMREC"),
          Evidence(repo="b", path="src/batch/CLMREC.cpy", line=9, text="01 CLM-REC"),
          Evidence(repo="b", path="src/batch/OTHER.cbl", line=1, text="x")]
    v = ViewGraph("t", "repomap", None, [n1, n2],
                  [VEdge("repo:a", "repo:b", "COPY", kind="shared_code", evidence=ev)], [])
    strip = " ".join(style_c.evidence_strip(v, 400))
    assert "online/CLMREC.cpy:3" in strip and "batch/CLMREC.cpy:9" in strip
    assert "OTHER.cbl:1" in strip and "batch/OTHER.cbl" not in strip


def test_html_search_covers_evidence_paths_and_code():
    html = style_c.render(fixture_view("repomap", None))["html"]
    m = re.search(r"function matches\(d,s\)\{(.*?)\}\n", html, re.S)
    assert m and "evidence" in m.group(1) and ".path" in m.group(1) and ".text" in m.group(1)


def test_svg_built_once(monkeypatch):
    import archdiag.render.style_c as sc
    calls = {"layout": 0, "pills": 0}
    real_layout, real_pills = sc.layout_for, sc.place_pills

    def count_layout(*a, **k):
        calls["layout"] += 1
        return real_layout(*a, **k)

    def count_pills(*a, **k):
        calls["pills"] += 1
        return real_pills(*a, **k)

    monkeypatch.setattr(sc, "layout_for", count_layout)
    monkeypatch.setattr(sc, "place_pills", count_pills)
    out = sc.render(fixture_view("repomap", None))
    assert calls == {"layout": 1, "pills": 1}
    # the page shows the same picture, plus the wide click targets
    assert out["svg"].count('<path id="edge-') == out["html"].count('<path id="edge-')


CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _chrome():
    import os
    import shutil
    for c in (os.environ.get("ARCHDIAG_CHROME", ""), CHROME, shutil.which("google-chrome"),
              shutil.which("chromium"), shutil.which("chrome")):
        if c and os.path.exists(c):
            return c
    return None


def test_html_search_and_click_run_in_a_browser(tmp_path):
    """E9: the page's own script, run in headless Chrome (skipped when Chrome is not
    installed): typing an evidence file name leaves only the lines with evidence in it
    lit, and clicking a line shows its file:line table."""
    import json
    import subprocess
    chrome = _chrome()
    if chrome is None:
        pytest.skip("Chrome not installed")
    v = fixture_view("repomap", None)
    html = style_c.render(v)["html"]
    want = sorted(i for i, e in enumerate(v.edges)
                  if any("MqClaimGateway.java" in x.path for x in e.evidence))
    assert want and len(want) < len(v.edges)
    probe = """<script>
var q=document.getElementById('q');q.value='MqClaimGateway.java';
q.dispatchEvent(new Event('input'));
var lit=[];document.querySelectorAll('svg g[data-edge]').forEach(function(g){
if(!g.classList.contains('dim'))lit.push(Number(g.getAttribute('data-edge')));});
var shown=0;document.querySelectorAll('#panel button[data-pick]').forEach(function(b){
if(b.parentNode.style.display!=='none')shown++;});
document.querySelector('svg g[data-edge="%d"]').dispatchEvent(new MouseEvent('click',{bubbles:true}));
var cells=[];document.querySelectorAll('#panel td').forEach(function(td){cells.push(td.textContent);});
var out=document.createElement('pre');out.id='probe';
out.textContent=JSON.stringify({lit:lit,shown:shown,cells:cells});document.body.appendChild(out);
</script></body>""" % want[0]
    page = tmp_path / "map.html"
    page.write_text(html.replace("</body>", probe, 1), encoding="utf-8")
    dom = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--dump-dom",
                          page.as_uri()], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=120).stdout
    m = re.search(r'<pre id="probe">(.*?)</pre>', dom or "", re.S)
    if m is None:  # Chrome ran but gave back no page (sandbox, policy, no display)
        pytest.skip("Chrome returned no page")
    got = json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&")
                     .replace("&lt;", "<").replace("&gt;", ">"))
    assert sorted(set(got["lit"])) == want
    assert got["shown"] == len(want)
    assert any("MqClaimGateway.java" in c for c in got["cells"]), got["cells"]


def test_evidence_strip_total_leaves_out_job_structure_lines():
    """Ruling 10: the strip's "N of M links" agrees with the stdout Summary, so the grey
    Scheduler "starts" line is not a link in M (claims-batch: 17, not 18)."""
    from conftest import ESTATE, fixture_resolved
    from archdiag.gitdiagram import load_gitdiagram
    from archdiag.groups import default_groups
    from archdiag.views import build_view
    from archdiag.views.common import STRUCTURAL
    fixture_view("landscape")
    r = fixture_resolved()
    gd = load_gitdiagram(ESTATE / "architecture-diagrams", r, "claims-batch")
    v = build_view(r, default_groups(r), "gitdiagram", "claims-batch", gitdiagram=gd)
    links = sum(1 for e in v.edges if e.status != STRUCTURAL)
    assert links == len(v.edges) - 1
    svg = style_c.render(v)["svg"]
    m = re.search(r"Evidence \((\d+) of (\d+) links", svg)
    assert m and int(m.group(2)) == links, m and m.group(0)
