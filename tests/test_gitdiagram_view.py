"""The gitdiagram view (Task 4): one repo's resolved links as a picture of named groups of
files (spec 4.2 and 10). A line is never more certain than what it stands on, and no
classified file quietly disappears."""
from __future__ import annotations

import json

from conftest import fixture_resolved
from test_view_invariants import _violations

from archdiag.gitdiagram import (GitDiagram, GitGroup, default_gitdiagram, gitdiagram_path,
                                 load_gitdiagram, repo_files)
from archdiag.groups import default_groups
from archdiag.model import CONFIRMED, LOOSE, PARTIAL, Edge, Evidence, Inventory, Node, Repo, Resolved
from archdiag.views import MAX_NODES, build_view

BATCH = "claims-batch"
JOB = "step:claims-batch/jcl/CLMD100.jcl#"


def batch_gd(**kw):
    """A hand-written grouping of claims-batch. cobol/CLMB500, CLMB510 and asm/ are left out."""
    return GitDiagram(BATCH, "Nightly claims batch.", [
        GitGroup("Nightly jobs", "JCL", ["jcl/", "jcl.pds/"], "The nightly stream"),
        GitGroup("Procs", "JCL", ["proc/"]),
        GitGroup("Claim pricing", "COBOL", ["cobol/CLMB200.cbl", "cobol/CLMB210.cbl"],
                 "Prices each claim"),
        GitGroup("Payments", "COBOL", ["cobol/CLMB300.cbl", "cobol.pds/"]),
    ], kw.get("links", []), [], True, "ok")


def view_of(gd, r=None):
    r = r or fixture_resolved()
    return build_view(r, default_groups(r), "gitdiagram", gd.repo, gitdiagram=gd)


def node(v, nid):
    hits = [n for n in v.nodes if n.id == nid]
    assert hits, "%s not in view: %s" % (nid, sorted(n.id for n in v.nodes))
    return hits[0]


def lines(v, src=None, dst=None):
    return [e for e in v.edges if (src is None or e.src == src) and (dst is None or e.dst == dst)]


def accounted(v, r, repo):
    """Every file the view's boxes stand for, plus the repo's not-scanned and skipped files."""
    out = set()
    for n in v.nodes:
        if n.kind in ("group", "more"):
            out |= set(n.members)
    out |= {x["path"] for x in r.inventory.not_scanned if x.get("repo") == repo}
    out |= {x["path"] for x in r.inventory.skipped if x.get("repo") == repo}
    return out


# ------------------------------------------------------------------ synthetic estates

def _ev(repo, path, line=1):
    return Evidence(repo, path, line, "line %d" % line)


def synthetic(nodes, edges, files, repo="r1", refs=None):
    nd = {n.id: n for n in nodes}
    inv = Inventory("ws", [Repo(repo, repo)], dict(nd), list(refs or []), "", {},
                    files=[{"repo": repo, "path": p, "kind": k} for p, k in sorted(files)])
    return Resolved(inv, nd, list(edges))


def prog(name, path, repo="r1", **attrs):
    return Node("program:" + name, "program", name, repo, [_ev(repo, path)], dict(attrs))


# ------------------------------------------------------------------ tests

def test_groups_become_boxes_with_links():
    v = view_of(batch_gd())
    assert v.level == "gitdiagram" and v.scope == BATCH
    assert v.repo_path == "claims-batch" and v.overview == "Nightly claims batch."
    pricing = node(v, "grp:Claim pricing")
    assert (pricing.kind, pricing.label, pricing.sublabel) == ("group", "Claim pricing", "[COBOL]")
    assert pricing.detail_lines[:3] == ["CLMB200.cbl", "CLMB210.cbl", "Prices each claim"]
    assert pricing.link == "cobol"  # every file shares one folder
    assert node(v, "grp:Payments").link == "cobol.pds/CLMB400"  # no shared folder: first file
    jobs = node(v, "grp:Nightly jobs")
    # basenames that collide carry their parent folder
    assert jobs.detail_lines[:3] == ["CLMD300", "jcl/CLMD100.jcl", "test/CLMD100.jcl"]
    assert jobs.members == ["jcl.pds/CLMD300", "jcl/CLMD100.jcl", "jcl/test/CLMD100.jcl"]
    # files no group claims
    ung = node(v, "grp:?")
    assert ung.label == "Not yet grouped · 3 files" and ung.role == "ungrouped"
    assert set(ung.members) == {"asm/DATEUTIL.asm", "cobol/CLMB500.cbl", "cobol/CLMB510.cbl"}
    assert "3 files not yet grouped" in v.notes


def test_group_box_shortens_long_file_lists():
    files = [("src/F%02d.cbl" % i, "cobol") for i in range(7)]
    r = synthetic([], [], files)
    gd = GitDiagram("r1", "", [GitGroup("All", "COBOL", ["src/"], "Everything")], [], [], True)
    n = node(view_of(gd, r), "grp:All")
    assert n.detail_lines == ["F00.cbl", "F01.cbl", "F02.cbl", "F03.cbl", "… 3 more files",
                              "Everything"]
    assert n.link == "src"


def test_every_classified_file_is_accounted_for():
    r = fixture_resolved()
    for gd in (batch_gd(), default_gitdiagram(r, BATCH)):
        v = view_of(gd, r)
        assert accounted(v, r, BATCH) == {f["path"] for f in repo_files(r, BATCH)}
    for repo in r.inventory.repos:
        v = view_of(default_gitdiagram(r, repo.name), r)
        want = {f["path"] for f in repo_files(r, repo.name)}
        assert want <= accounted(v, r, repo.name), repo.name


def test_dataset_arrow_starts_at_program_group():
    v = view_of(batch_gd())
    # STEP020 runs CLMB200 (confirmed) and CLMB200 opens CLMOUT, the DD that writes CLAIMS.DAILY
    ln, = [e for e in lines(v, "grp:Claim pricing", "dataset:CLAIMS.DAILY") if e.label == "writes"]
    assert ln.status == CONFIRMED
    ops = {(u.src, u.op, u.dst) for u in ln.underlying}
    assert (JOB + "STEP020", "write", "dataset:CLAIMS.DAILY") in ops
    assert (JOB + "STEP020", "runs", "program:CLMB200") in ops  # stands on the runs edge too
    # the job's temporary datasets are no boxes: named on the job's line and in its info,
    # told apart by the job file (Ruling 6)
    assert not [n for n in v.nodes if "&&" in n.id]
    assert "temporary dataset &&SORTED (jcl/test/CLMD100.jcl)" in \
        node(v, "grp:Nightly jobs").info
    # the same DD is not drawn from the job's group
    assert not [e for e in lines(v, "grp:Nightly jobs", "dataset:CLAIMS.DAILY")
                if any(u.src == JOB + "STEP020" for u in e.underlying)]


def test_dataset_arrow_status_is_the_less_certain_of_the_two():
    p = prog("P", "cobol/P.cbl", files={"OUTDD": "output"})
    job = Node("job:r1/jcl/J.jcl", "job", "J", "r1", [_ev("r1", "jcl/J.jcl")])
    st = Node("step:r1/jcl/J.jcl#S1", "step", "S1", "r1", [_ev("r1", "jcl/J.jcl", 2)],
              {"job": job.id})
    ds = Node("dataset:A.B", "dataset", "A.B", None, [], {"names": ["A.B"]})
    other = prog("Q", "cobol/Q.cbl")
    ev_w = _ev("r1", "jcl/J.jcl", 3)
    from archdiag.model import Ref
    ref = Ref(st.id, "write", "dataset", "A.B", ev_w, None, [], {"ddname": "OUTDD"})
    edges = [Edge(st.id, "runs", p.id, CONFIRMED, None, [_ev("r1", "jcl/J.jcl", 2)]),
             Edge(st.id, "write", ds.id, PARTIAL, "symbol", [ev_w]),
             Edge(other.id, "read", ds.id, CONFIRMED, None, [_ev("r1", "cobol/Q.cbl")])]
    r = synthetic([p, job, st, ds, other], edges,
                  [("cobol/P.cbl", "cobol"), ("cobol/Q.cbl", "cobol"), ("jcl/J.jcl", "jcl")],
                  refs=[ref])
    gd = GitDiagram("r1", "", [GitGroup("Jobs", "JCL", ["jcl/"]), GitGroup("P", "", ["cobol/P.cbl"]),
                               GitGroup("Q", "", ["cobol/Q.cbl"])], [], [], True)
    v = view_of(gd, r)
    ln, = lines(v, "grp:P", "dataset:A.B")
    assert ln.status == PARTIAL


def test_utility_dataset_arrow_stays_with_job_group():
    v = view_of(batch_gd())
    # STEP040 runs IEBGENER: its SYSUT2 write of CLAIMS.EXTRACT is the job's own work
    ln, = [e for e in lines(v, "grp:Nightly jobs", "dataset:CLAIMS.EXTRACT") if e.label == "writes"]
    assert ln.status == CONFIRMED
    assert any(u.src == JOB + "STEP040" and u.op == "write" for u in ln.underlying)
    # a step whose program does not name the DD (CLMB300 has no SELECT for DAILYIN) also stays
    rd = [e for e in lines(v, "grp:Nightly jobs", "dataset:CLAIMS.DAILY") if e.label == "reads"]
    assert rd and any(u.src == JOB + "STEP030" for u in rd[0].underlying)
    assert not lines(v, "grp:Payments", "dataset:CLAIMS.DAILY")


def test_defined_table_arrow_goes_into_ddl_group():
    t = Node("table:S.T", "table", "S.T", "r1", [_ev("r1", "ddl/T.sql")], {"name": "T"})
    p = prog("P", "cobol/P.cbl")
    r = synthetic([t, p], [Edge(p.id, "select", t.id, CONFIRMED, None, [_ev("r1", "cobol/P.cbl", 5)])],
                  [("cobol/P.cbl", "cobol"), ("ddl/T.sql", "ddl")])
    gd = GitDiagram("r1", "", [GitGroup("Programs", "COBOL", ["cobol/"]),
                               GitGroup("Schema", "DDL", ["ddl/"])], [], [], True)
    v = view_of(gd, r)
    ln, = lines(v, "grp:Programs", "grp:Schema")
    assert (ln.label, ln.status) == ("SQL · T", CONFIRMED)
    assert "table:S.T" not in {n.id for n in v.nodes}


def test_undefined_shared_resource_box_only_when_two_groups():
    a, b = prog("A", "a/A.cbl"), prog("B", "b/B.cbl")
    d1 = Node("dataset:D1", "dataset", "D1", None, [], {"names": ["D1"]})
    d2 = Node("dataset:D2", "dataset", "D2", None, [], {"names": ["D2"]})
    edges = [Edge(a.id, "read", d1.id, CONFIRMED, None, [_ev("r1", "a/A.cbl", 3)]),
             Edge(b.id, "write", d1.id, CONFIRMED, None, [_ev("r1", "b/B.cbl", 3)]),
             Edge(a.id, "write", d2.id, PARTIAL, "symbol", [_ev("r1", "a/A.cbl", 4)])]
    r = synthetic([a, b, d1, d2], edges, [("a/A.cbl", "cobol"), ("b/B.cbl", "cobol")])
    gd = GitDiagram("r1", "", [GitGroup("A", "", ["a/"]), GitGroup("B", "", ["b/"])], [], [], True)
    v = view_of(gd, r)
    ids = {n.id for n in v.nodes}
    assert "dataset:D1" in ids and "dataset:D2" not in ids
    assert lines(v, "grp:A", "dataset:D1")[0].label == "reads"
    assert lines(v, "grp:B", "dataset:D1")[0].label == "writes"
    ga = node(v, "grp:A")
    assert any("D2" in x for x in ga.info)
    # its partial link is counted inside A (one muted box line) and kept for the links report
    assert ga.detail_lines[-1] == "+1 link (1 partly known)" and ga.muted == 1
    assert "1 link inside" in ga.info and "1 partly known link inside" in ga.info
    assert any(u.dst == "dataset:D2" for u in ga.underlying)


def test_outside_stubs_collapse_per_repo():
    v = view_of(batch_gd())
    outs = sorted(n.id for n in v.nodes if n.id.startswith("out:"))
    assert outs == ["out:claims-db", "out:external", "out:missing", "out:shared-copybooks"]
    db = node(v, "out:claims-db")
    assert db.kind == "outside" and db.label == "claims-db (2 tables)"
    srcs = {e.src for e in lines(v, dst="out:claims-db")}
    assert srcs == {"grp:Claim pricing", "grp:Payments", "grp:?"}  # CLMB500 is not grouped
    loose = node(v, "out:missing")
    assert loose.label == "3 loose ends" and loose.status == LOOSE
    for e in lines(v, dst="out:missing"):
        assert e.status == LOOSE
    ext = lines(v, dst="out:external")
    assert ext and all(e.status == PARTIAL for e in ext)  # the transfer is partly known


def test_outside_stub_line_takes_the_least_certain_edge():
    p = prog("P", "cobol/P.cbl")
    t1 = Node("table:S.T1", "table", "S.T1", "db", [_ev("db", "ddl/T1.sql")], {"name": "T1"})
    t2 = Node("table:S.T2", "table", "S.T2", "db", [_ev("db", "ddl/T2.sql")], {"name": "T2"})
    edges = [Edge(p.id, "select", t1.id, CONFIRMED, None, [_ev("r1", "cobol/P.cbl", 3)]),
             Edge(p.id, "select", t2.id, PARTIAL, "schema", [_ev("r1", "cobol/P.cbl", 4)])]
    r = synthetic([p, t1, t2], edges, [("cobol/P.cbl", "cobol")])
    r.inventory.repos.append(Repo("db", "db"))
    gd = GitDiagram("r1", "", [GitGroup("P", "", ["cobol/"])], [], [], True)
    v = view_of(gd, r)
    ln, = lines(v, "grp:P", "out:db")
    assert ln.status == PARTIAL and ln.label == "SQL · T1, T2"
    assert node(v, "out:db").label == "db (2 tables)"


def _jobs_estate(submitted):
    jobs = [Node("job:r1/jcl/%s.jcl" % j, "job", j, "r1", [_ev("r1", "jcl/%s.jcl" % j)])
            for j in ("A", "B", "C")]
    st = Node("step:r1/jcl/A.jcl#S1", "step", "S1", "r1", [_ev("r1", "jcl/A.jcl", 2)],
              {"job": jobs[0].id})
    edges = []
    if submitted:
        edges.append(Edge(st.id, "submits", jobs[1].id, CONFIRMED, None, [_ev("r1", "jcl/A.jcl", 3)]))
    files = [("jcl/%s.jcl" % j, "jcl") for j in ("A", "B", "C")]
    r = synthetic(jobs + [st], edges, files)
    gd = GitDiagram("r1", "", [GitGroup("A jobs", "JCL", ["jcl/A.jcl"]),
                               GitGroup("B jobs", "JCL", ["jcl/B.jcl"]),
                               GitGroup("C jobs", "JCL", ["jcl/C.jcl"])], [], [], True)
    return view_of(gd, r)


def test_scheduler_lines_are_structural_and_only_for_unsubmitted_jobs():
    v = _jobs_estate(submitted=True)
    sch = node(v, "act:scheduler")
    assert sch.kind == "actor" and sch.label == "Scheduler"
    starts = lines(v, "act:scheduler")
    assert sorted(e.dst for e in starts) == ["grp:A jobs", "grp:C jobs"]
    for e in starts:
        assert (e.kind, e.label, e.status, e.underlying) == ("sequence", "starts", "structural", [])
    assert lines(v, "grp:A jobs", "grp:B jobs")[0].status == CONFIRMED
    # in the fixture nothing submits a job: one "starts" line per group holding jobs
    f = view_of(batch_gd())
    assert sorted(e.dst for e in lines(f, "act:scheduler")) == ["grp:Nightly jobs"]
    assert {e.status for e in lines(f, "act:scheduler")} == {"structural"}


def test_structural_is_ignored_when_statuses_combine():
    from archdiag.views.common import _least_certain, combine_status
    assert combine_status(["structural", "partial"]) == PARTIAL
    assert combine_status(["structural", "loose"]) == LOOSE
    assert _least_certain(["structural", CONFIRMED]) == CONFIRMED
    assert _least_certain(["structural", PARTIAL]) == PARTIAL
    assert combine_status(["structural"]) == "structural"
    assert _least_certain(["structural"]) == "structural"


def test_entry_actor_folding():
    p = prog("P", "cobol/P.cbl")
    txs = [Node("transaction:T%03d" % i, "transaction", "T%03d" % i, "r1",
                [_ev("r1", "csd/T.csd", i + 1)]) for i in range(50)]
    edges = [Edge(t.id, "runs", p.id, CONFIRMED, None, [t.evidence[0]]) for t in txs]
    r = synthetic([p] + txs, edges, [("cobol/P.cbl", "cobol"), ("csd/T.csd", "csd")])
    gd = GitDiagram("r1", "", [GitGroup("Programs", "COBOL", ["cobol/"]),
                               GitGroup("CSD", "CICS", ["csd/"])], [], [], True)
    v = view_of(gd, r)
    acts = [n for n in v.nodes if n.id.startswith("act:")]
    assert [a.id for a in acts] == ["act:transaction"]
    a = acts[0]
    assert a.kind == "actor" and a.label == "CICS transactions (50)"
    names = [x for x in a.detail_lines if not x.startswith("…")]
    assert names == ["T000", "T001", "T002", "T003", "T004", "T005"]
    assert a.members == ["T%03d" % i for i in range(50)]
    assert a.link == "csd/T.csd"
    ln, = lines(v, "act:transaction", "grp:Programs")
    assert (ln.label, ln.status, len(ln.underlying)) == ("runs · P", CONFIRMED, 50)
    assert not [n for n in v.nodes if n.id.startswith("transaction:")]


def test_fixture_entry_actors_for_online_repo():
    r = fixture_resolved()
    v = view_of(default_gitdiagram(r, "claims-online"), r)
    tx = node(v, "act:transaction")
    assert tx.label == "CICS transactions (2)"
    assert node(v, "act:zosapi").label == "z/OS Connect APIs (1)"
    # CLMU runs CLMO120, which is in no repo: a loose end, never solid
    assert any(e.src == "act:transaction" and e.status == LOOSE for e in lines(v, dst="out:missing"))


def test_suggested_links_are_dotted():
    links = [{"from": "Nightly jobs", "to": "Claim pricing", "label": "hands work to",
              "note": "inferred from README"},
             {"from": "Scheduler", "to": "Payments", "label": "starts at 2am", "note": ""},
             {"from": "Nowhere", "to": "Payments", "label": "x", "note": ""}]
    v = view_of(batch_gd(links=links))
    s1, = [e for e in lines(v, "grp:Nightly jobs", "grp:Claim pricing") if e.label == "hands work to"]
    assert s1.status == PARTIAL and s1.kind == "runtime"
    u, = s1.underlying
    assert (u.op, u.status, u.reason) == ("suggested", PARTIAL, "suggested by Copilot: inferred from README")
    s2, = lines(v, "act:scheduler", "grp:Payments")
    assert s2.status == PARTIAL and s2.label == "starts at 2am"
    assert s2.underlying[0].reason == "suggested by Copilot"
    assert any("Nowhere" in n for n in v.notes)
    for e in v.edges:
        if any(x.op == "suggested" for x in e.underlying):
            assert e.status == PARTIAL


def test_loader_keeps_suggested_links_to_entry_actors(tmp_path):
    r = fixture_resolved()
    gitdiagram_path(tmp_path, BATCH).write_text(json.dumps({
        "groups": [{"name": "Jobs", "files": ["jcl/"]}],
        "suggested_links": [{"from": "Scheduler", "to": "Jobs"},
                            {"from": "cics transactions", "to": "Jobs"},
                            {"from": "Jobs", "to": "Nowhere"},
                            {"from": "program:CLMB200", "to": "Jobs"}]}), encoding="utf-8")
    gd = load_gitdiagram(tmp_path, r, BATCH)
    assert [(x["from"], x["to"]) for x in gd.suggested_links] == [("Scheduler", "Jobs"),
                                                                   ("cics transactions", "Jobs")]
    # a node id is not a box: one problem, from the loader, in the view's own words
    bad = [p for p in gd.problems if "program:CLMB200" in p]
    assert len(bad) == 1 and "names no group or entry point" in bad[0]
    v = view_of(gd, r)
    assert lines(v, "act:scheduler", "grp:Jobs")
    # claims-batch has no CICS transactions: the end names no box, so the notes say so
    assert any("cics transactions" in n for n in v.notes)


def test_no_line_more_certain_than_its_named_targets():
    r = fixture_resolved()
    views = [view_of(batch_gd(), r)]
    for repo in r.inventory.repos:
        views.append(view_of(default_gitdiagram(r, repo.name), r))
    assert not _violations(views)
    for v in views:
        for e in v.edges:
            if e.status == "structural":
                assert e.kind == "sequence" and e.src == "act:scheduler" and not e.underlying
                continue
            # a solid line always has a confirmed resolver edge under it
            if e.status == CONFIRMED:
                assert any(u.status == CONFIRMED for u in e.underlying), (v.scope, e)


def test_partial_call_between_groups_is_dotted():
    v = view_of(batch_gd())
    # CLMB400 (Payments) CALLs CLMB210 confirmed; CLMB200 -> CLMB210 is inside Claim pricing
    ln, = lines(v, "grp:Payments", "grp:Claim pricing")
    assert (ln.label, ln.status) == ("CALL · CLMB210", CONFIRMED)
    pricing = node(v, "grp:Claim pricing")
    assert "1 partly known link inside" in pricing.info
    # the partly known runs of the CLMEXT proc
    pr, = [e for e in lines(v, "grp:Procs", "grp:Claim pricing") if e.label.startswith("runs")]
    assert pr.status == PARTIAL


def test_all_stale_patterns_leave_everything_not_yet_grouped_with_problems(tmp_path):
    r = fixture_resolved()
    gitdiagram_path(tmp_path, BATCH).write_text(json.dumps({
        "overview": "Old layout",
        "groups": [{"name": "Old jobs", "files": ["JCL_OLD/*.jcl"]},
                   {"name": "Old code", "files": ["src/cobol/", "legacy\\CLMB200.cbl"]}]}),
        encoding="utf-8")
    gd = load_gitdiagram(tmp_path, r, BATCH)
    v = view_of(gd, r)
    assert not [n for n in v.nodes if n.kind == "group" and n.id != "grp:?"]
    ung = node(v, "grp:?")
    assert set(ung.members) == {f["path"] for f in repo_files(r, BATCH)}
    text = "\n".join(v.notes)
    for pat in ("JCL_OLD/*.jcl", "src/cobol/", "legacy\\\\CLMB200.cbl"):
        assert pat in text, pat
    assert "12 files not yet grouped" in v.notes
    assert any("no group" in n.lower() and "matches" in n for n in v.notes)


def test_folder_fallback_note():
    r = fixture_resolved()
    v = view_of(default_gitdiagram(r, BATCH), r)
    assert "Grouped by folder. Ask Copilot to name groups for this repo." in v.notes
    assert node(v, "grp:cobol").label == "cobol"


def test_default_grouping_when_none_given_and_scope_checked():
    import pytest
    from archdiag.views import ScopeError
    r = fixture_resolved()
    v = build_view(r, default_groups(r), "gitdiagram", "claims-batch")
    assert any(n.id == "grp:jcl" for n in v.nodes)
    with pytest.raises(ScopeError) as ei:
        build_view(r, default_groups(r), "gitdiagram", "claims-btch")
    assert "claims-batch" in ei.value.suggestions


def test_cap_never_folds_not_yet_grouped_or_entry_points():
    files = [("f%02d/P%04d.cbl" % (i % 60, i), "cobol") for i in range(600)]
    p = prog("P", "f00/P0000.cbl")
    tx = Node("transaction:T1", "transaction", "T1", "r1", [_ev("r1", "f01/P0001.cbl")])
    r = synthetic([p, tx], [Edge(tx.id, "runs", p.id, CONFIRMED, None, [tx.evidence[0]])], files)
    gd = default_gitdiagram(r, "r1")
    gd = GitDiagram("r1", "", gd.groups[:-1], [], [], True)  # f59/ is left out
    v = view_of(gd, r)
    assert len(v.nodes) <= MAX_NODES
    ids = {n.id for n in v.nodes}
    assert "grp:?" in ids and "act:transaction" in ids
    assert len(node(v, "grp:?").members) == 10
    assert accounted(v, r, "r1") == {f for f, _ in files}


def test_other_repo_use_of_a_resource_is_marked_and_kept():
    a = prog("A", "a/A.cbl")
    b = prog("B", "b/B.cbl", repo="r2")
    c = prog("C", "c/C.cbl", repo="r3")
    d = Node("dataset:D", "dataset", "D", None, [], {"names": ["D"]})
    e_a = Edge(a.id, "read", d.id, CONFIRMED, None, [_ev("r1", "a/A.cbl", 3)])
    e_b = Edge(b.id, "write", d.id, PARTIAL, "symbol", [_ev("r2", "b/B.cbl", 3)])
    e_c = Edge(c.id, "write", d.id, CONFIRMED, None, [_ev("r3", "c/C.cbl", 3)])
    r = synthetic([a, b, c, d], [e_a, e_b, e_c], [("a/A.cbl", "cobol")])
    r.inventory.repos += [Repo("r2", "r2"), Repo("r3", "r3")]
    gd = GitDiagram("r1", "", [GitGroup("A", "", ["a/"])], [], [], True)
    ga = node(view_of(gd, r), "grp:A")
    assert "also used by other repos: D (r2, partly known; r3)" in ga.info
    assert any(u is e_b for u in ga.underlying) and any(u is e_c for u in ga.underlying)
    # a shared box says the same in its info (its box shows name and kind) and keeps the
    # edges too
    a2 = prog("A2", "a2/A2.cbl")
    r = synthetic([a, a2, b, d], [e_a, Edge(a2.id, "read", d.id, CONFIRMED, None,
                                            [_ev("r1", "a2/A2.cbl", 3)]), e_b],
                  [("a/A.cbl", "cobol"), ("a2/A2.cbl", "cobol")])
    r.inventory.repos.append(Repo("r2", "r2"))
    gd = GitDiagram("r1", "", [GitGroup("A", "", ["a/"]), GitGroup("A2", "", ["a2/"])], [], [], True)
    box = node(view_of(gd, r), "dataset:D")
    assert box.sublabel == "dataset" and "also used by r2, partly known" in box.info
    assert any(u is e_b for u in box.underlying)


def test_huge_repo_capped_at_40():
    files = [("f%02d/P%04d.cbl" % (i % 60, i), "cobol") for i in range(3000)]
    r = synthetic([], [], files)
    gd = default_gitdiagram(r, "r1")
    assert len(gd.groups) == 60
    v = view_of(gd, r)
    assert len(v.nodes) <= MAX_NODES
    assert accounted(v, r, "r1") == {p for p, _ in files}
    assert any("fewer groups" in n for n in v.notes)


def test_deterministic():
    a, b = view_of(batch_gd()), view_of(batch_gd())
    assert [(n.id, n.label, n.detail_lines) for n in a.nodes] == \
        [(n.id, n.label, n.detail_lines) for n in b.nodes]
    assert [(e.src, e.dst, e.label, e.status) for e in a.edges] == \
        [(e.src, e.dst, e.label, e.status) for e in b.edges]


# ------------------------------------------------------------------ fix round 2 (Ruling 5, 6)

def _handler_estate(ha_status, hb_status=None):
    c = prog("C", "c/C.java")
    ha = prog("HA", "a/HA.java")
    ep = Node("endpoint:GET /x", "endpoint", "GET /x", "r1", [_ev("r1", "a/Api.java")])
    edges = [Edge(c.id, "http", ep.id, CONFIRMED, None, [_ev("r1", "c/C.java", 5)]),
             Edge(ep.id, "runs", ha.id, ha_status, None if ha_status == CONFIRMED else "x",
                  [_ev("r1", "a/Api.java", 2)])]
    nodes = [c, ha, ep]
    groups = [GitGroup("A", "", ["a/"]), GitGroup("C", "", ["c/"])]
    files = [("c/C.java", "java"), ("a/HA.java", "java"), ("a/Api.java", "java")]
    if hb_status is not None:
        hb = prog("HB", "b/HB.java")
        nodes.append(hb)
        edges.append(Edge(ep.id, "runs", hb.id, hb_status, None if hb_status == CONFIRMED
                          else "x", [_ev("r1", "a/Api.java", 3)]))
        groups.append(GitGroup("B", "", ["b/"]))
        files.append(("b/HB.java", "java"))
    r = synthetic(nodes, edges, files)
    _handler_estate.resolved = r  # for the report's completeness test
    return view_of(GitDiagram("r1", "", groups, [], [], True), r), edges


def test_entry_point_redirect_one_line_per_handler_group_least_certain():
    v, edges = _handler_estate(PARTIAL, CONFIRMED)
    assert not lines(v, "grp:C", "act:endpoint")
    la, = lines(v, "grp:C", "grp:A")
    lb, = lines(v, "grp:C", "grp:B")
    assert la.status == PARTIAL and lb.status == CONFIRMED
    assert any(u is edges[1] for u in la.underlying)  # the handler edge it stands on
    assert any(u is edges[2] for u in lb.underlying)
    assert not any(u is edges[1] for u in lb.underlying)


def test_entry_point_redirect_single_partial_or_loose_handler():
    v, _ = _handler_estate(PARTIAL)
    ln, = lines(v, "grp:C", "grp:A")
    assert ln.status == PARTIAL
    v, _ = _handler_estate(LOOSE)
    ln, = lines(v, "grp:C", "grp:A")
    assert ln.status == LOOSE


def _temp_estate(extra_edges):
    a, b = prog("A", "a/A.cbl"), prog("B", "b/B.cbl")
    t = Node("dataset:r1/j.jcl#&&T", "dataset", "&&T", None, [],
             {"temp": True, "names": ["&&T"]})
    edges = [Edge(a.id, "write", t.id, CONFIRMED, None, [_ev("r1", "a/A.cbl", 2)])] + \
        [Edge(*x) for x in extra_edges(a, b, t)]
    r = synthetic([a, b, t], edges, [("a/A.cbl", "cobol"), ("b/B.cbl", "cobol")])
    gd = GitDiagram("r1", "", [GitGroup("A", "", ["a/"]), GitGroup("B", "", ["b/"])], [], [], True)
    return view_of(gd, r), edges


def test_temp_dataset_as_edge_source_is_a_read():
    v, _ = _temp_estate(lambda a, b, t: [(t.id, "feeds", b.id, CONFIRMED, None,
                                         [_ev("r1", "b/B.cbl", 4)])])
    ln, = lines(v, "grp:A", "grp:B")
    assert ln.label == "via &&T" and ln.status == CONFIRMED


def test_temp_dataset_same_group_pair_kept_inside_when_a_cross_pair_exists():
    v, edges = _temp_estate(lambda a, b, t: [
        (b.id, "read", t.id, CONFIRMED, None, [_ev("r1", "b/B.cbl", 4)]),
        (a.id, "read", t.id, PARTIAL, "x", [_ev("r1", "a/A.cbl", 9)])])
    assert lines(v, "grp:A", "grp:B")[0].label == "via &&T"
    ga = node(v, "grp:A")
    assert "1 partly known link inside" in ga.info or "2 links inside" in ga.info
    assert any(u is edges[2] for u in ga.underlying)  # A's own read of &&T, kept
