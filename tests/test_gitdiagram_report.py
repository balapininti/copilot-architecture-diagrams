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


def test_redirected_handler_lines_are_complete():
    # a caller group's use of the repo's own endpoint is drawn to the handler groups
    # (Ruling 5); both the caller edge and each handler edge must be listed with a row
    from test_gitdiagram_view import _handler_estate
    from archdiag.render.report import _edges, _links
    v, edges = _handler_estate("partial", "confirmed")
    assert any(e.src == "grp:C" and e.dst == "grp:A" for e in v.edges)
    r = _handler_estate.resolved
    rows = _links(_edges(v), r)
    text = links_report(v, r)
    for e in edges:
        assert any(any(e is x for x in g) for g in rows), (e.src, e.op, e.dst)
    table = text.split("## Links on this diagram")[1].split("\n## ")[0]
    assert sum(1 for ln in table.splitlines() if ln.startswith("| ")) - 1 == len(rows)
    assert "GET /x" in table


# ------------------------------------------------------------------ final review fixes

def _sec(text, name):
    return text.split("## %s\n" % name)[1].split("\n## ")[0]


def test_folded_groups_are_listed_with_all_their_files():
    """Under the 40-box cap, groups folded into '… N more groups' are still listed under
    Groups with every file linked, so the 'lists every one' note is true."""
    from test_gitdiagram_view import _ev, prog, synthetic
    from archdiag.model import CONFIRMED, Edge
    from archdiag.views import MAX_NODES
    files = [("g%02d/P%02d.cbl" % (i, i), "cobol") for i in range(50)]
    a, b = prog("P00", "g00/P00.cbl"), prog("P01", "g01/P01.cbl")
    r = synthetic([a, b], [Edge(a.id, "call", b.id, CONFIRMED, None, [_ev("r1", "g00/P00.cbl", 5)])],
                  files)
    groups = [GitGroup("Group %02d" % i, "COBOL", ["g%02d/" % i]) for i in range(50)]
    v = view_of(GitDiagram("r1", "", groups, [], [], True, "ok"), r)
    assert len(v.nodes) <= MAX_NODES
    assert any(n.kind == "more" for n in v.nodes)
    assert any("lists every one" in n for n in v.notes)
    text = links_report(v, r)
    sec = _sec(text, "Groups")
    for i in range(50):
        assert "### Group %02d" % i in sec, i
        assert "](%s)" % href(v.repo_path, "g%02d/P%02d.cbl" % (i, i)) in sec, i
    more = [n for n in v.nodes if n.kind == "more"][0]
    assert "Group 02" in more.sublabel  # a zero-link group, folded
    folded = sec.split("### Group 02")[1].split("\n### ")[0]
    assert "folded into '%s'" % md(more.label) in folded


def test_folded_outside_and_shared_boxes_are_listed():
    from test_gitdiagram_view import _ev, prog, synthetic
    from archdiag.model import CONFIRMED, Edge, Node, Repo
    from archdiag.views import MAX_NODES
    a, b = prog("A", "a/A.cbl"), prog("B", "b/B.cbl")
    nodes, edges = [a, b], []
    for i in range(25):
        far = prog("X%02d" % i, "x/X%02d.cbl" % i, repo="o%02d" % i)
        nodes.append(far)
        edges.append(Edge(a.id, "call", far.id, CONFIRMED, None, [_ev("r1", "a/A.cbl", i + 1)]))
        d = Node("dataset:D%02d" % i, "dataset", "D%02d" % i, None, [], {"names": ["D%02d" % i]})
        nodes.append(d)
        edges.append(Edge(a.id, "write", d.id, CONFIRMED, None, [_ev("r1", "a/A.cbl", 50 + i)]))
        edges.append(Edge(b.id, "read", d.id, CONFIRMED, None, [_ev("r1", "b/B.cbl", 50 + i)]))
    r = synthetic(nodes, edges, [("a/A.cbl", "cobol"), ("b/B.cbl", "cobol")])
    r.inventory.repos += [Repo("o%02d" % i, "o%02d" % i) for i in range(25)]
    gd = GitDiagram("r1", "", [GitGroup("A", "", ["a/"]), GitGroup("B", "", ["b/"])], [], [],
                    True, "ok")
    v = view_of(gd, r)
    assert len(v.nodes) <= MAX_NODES
    mores = [n for n in v.nodes if n.kind == "more"]
    assert mores
    sec = _sec(links_report(v, r), "Shared resources and outside this repo")
    for i in range(25):
        assert "o%02d (" % i in sec, i
        assert "D%02d" % i in sec, i
    assert all("folded into '%s'" % md(m.label) in sec for m in mores)
