"""The links report for the gitdiagram level (Task 7, spec 4.2): overview, every group's full
file list as relative links, entry points, job structure kept apart from links, the not-yet-
grouped list and the problems in the gitdiagram file."""
from __future__ import annotations

import re

from conftest import fixture_resolved
from test_gitdiagram_view import BATCH, batch_gd, view_of

from archdiag.gitdiagram import GitDiagram, GitGroup
from archdiag.render.common import href
from archdiag.render.report import links_report, md


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


def _in_repo(r, repo):
    return [e for e in r.edges if any(x.repo == repo for x in e.evidence)]


def _assert_complete(v, r, text, repo):
    from archdiag.render.report import _edges, _links
    listed = _edges(v)
    missing = [e for e in _in_repo(r, repo) if not any(e is x for x in listed)]
    assert not missing, ["%s %s %s" % (e.src, e.op, e.dst) for e in missing]
    rows = _links(listed, r)
    table = text.split("## Links on this diagram")[1].split("\n## ")[0]
    assert sum(1 for ln in table.splitlines() if ln.startswith("| ")) - 1 == len(rows)
    for e in _in_repo(r, repo):
        assert any(any(e is x for x in g) for g in rows)


def test_every_resolver_edge_in_repo_has_a_row():
    text, v = report()
    _assert_complete(v, fixture_resolved(), text, BATCH)


def test_complete_with_redirected_handlers_and_temp_datasets():
    # all four default-ish groups plus an entry-point-heavy repo and the temp dataset jobs
    for repo in ("claims-online", "claims-api"):
        r = fixture_resolved()
        gd = GitDiagram(repo, "o", [GitGroup("Code", "x", ["*.cbl", "*.java", "proc/"])],
                        [], [], True, "ok")
        v = view_of(gd, r)
        _assert_complete(v, r, links_report(v, r), repo)
    r = fixture_resolved()
    gd = GitDiagram(BATCH, "o", [GitGroup("A", "JCL", ["jcl/CLMD100.jcl"]),
                                 GitGroup("B", "COBOL", ["cobol/CLMB200.cbl"])], [], [], True, "ok")
    v = view_of(gd, r)
    assert any(n.kind == "dataset" and n.attrs.get("temp") for n in r.nodes.values())
    _assert_complete(v, r, links_report(v, r), BATCH)


def test_names_with_markdown_characters_are_escaped():
    gd = GitDiagram(BATCH, "Uses a_b and *bold* [x]", [
        GitGroup("My_group *1*", "JCL", ["jcl/"], "# not a heading_x")], [], [], True, "ok")
    text, _ = report(gd)
    assert "My\\_group \\*1\\*" in text
    assert "Uses a\\_b and \\*bold\\* \\[x\\]" in text
    assert "\\# not a heading\\_x" in text


def test_extra_sections_positions_and_info_in_section():
    text, v = report()
    heads = re.findall(r"^## (.+)$", text, re.M)
    i = heads.index
    assert i("Entry points") < i("Job structure") < i("Shared resources and outside this repo") \
        < i("Links on this diagram")
    assert i("Notes") < i("Clickable boxes") < i("Not yet grouped")

    def sec(name):
        return text.split("## %s\n" % name)[1].split("\n## ")[0]
    groups, shared = sec("Groups"), sec("Shared resources and outside this repo")
    for n in v.nodes:
        where = groups if n.kind == "group" and n.role != "ungrouped" else \
            sec("Not yet grouped") if n.role == "ungrouped" else \
            shared if (n.role == "shared" or n.id.startswith("out:")) else None
        if where is None:
            continue
        sub = where.split("### %s" % md(n.label))[1].split("\n### ")[0] \
            if where is groups else where
        for line in n.info:
            assert md(line) in sub, (n.id, line)
