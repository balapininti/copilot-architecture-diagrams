"""The links report for the gitdiagram level (Task 7, spec 4.2): overview, every group's full
file list as relative links, entry points, job structure kept apart from links, the not-yet-
grouped list and the problems in the gitdiagram file."""
from __future__ import annotations

import re

from conftest import fixture_resolved
from test_gitdiagram_view import BATCH, batch_gd, view_of

from archdiag.gitdiagram import GitDiagram, GitGroup
from archdiag.render.common import href
from archdiag.render.report import links_report


def report(gd=None):
    v = view_of(gd or batch_gd())
    return links_report(v, fixture_resolved()), v


def test_report_has_gitdiagram_sections_in_order():
    text, _ = report()
    heads = re.findall(r"^## (.+)$", text, re.M)
    order = ["Overview", "Groups", "Entry points", "Links on this diagram", "Loose ends",
             "Partly known", "Possibly missing repos", "Not analyzed", "Skipped files",
             "Not scanned", "Notes", "Not yet grouped", "Problems in the gitdiagram file"]
    pos = [heads.index(h) for h in order]
    assert pos == sorted(pos), heads
    assert "Nightly claims batch." in text.split("## Groups")[0]
    assert "Clickable boxes" in text


def test_every_group_file_listed():
    text, v = report()
    groups = [n for n in v.nodes if n.kind == "group" and n.members]
    assert groups
    for n in groups:
        for p in n.members:
            assert "](%s)" % href(v.repo_path, p) in text, p
    assert "Prices each claim" in text


def test_scheduler_lines_not_listed_as_links():
    text, v = report()
    assert any(e.status == "structural" for e in v.edges)
    assert "## Job structure" in text
    job = text.split("## Job structure")[1].split("\n## ")[0]
    assert "Scheduler" in job and "starts" in job
    links = text.split("## Links on this diagram")[1].split("\n## ")[0]
    assert "starts" not in links
    assert "job-structure lines" not in text
    head = text.splitlines()[2]
    assert "confirmed" in head


def test_problems_listed():
    gd = GitDiagram(BATCH, "x", [GitGroup("Ghost", "JCL", ["nowhere/"])], [],
                    ["group 'Ghost': pattern 'nowhere/' matches no file in %s" % BATCH],
                    True, "ok")
    text, _ = report(gd)
    sec = text.split("## Problems in the gitdiagram file")[1]
    assert "nowhere/" in sec
    assert "nowhere/" not in text.split("## Notes")[1].split("## Not yet grouped")[0]
    clean, _ = report()
    assert clean.split("## Problems in the gitdiagram file")[1].strip() == "None."


def test_ungrouped_and_hidden_info_listed():
    text, v = report()
    ung = text.split("## Not yet grouped")[1].split("\n## ")[0]
    n = [x for x in v.nodes if x.id == "grp:?"][0]
    for p in n.members:
        assert p in ung
    for x in v.nodes:
        for line in x.info:
            assert line in text, line
