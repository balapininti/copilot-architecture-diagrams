from __future__ import annotations

import json

import pytest

from conftest import ESTATE
from archdiag.config import load_config
from archdiag.groups import default_groups, load_groups
from archdiag.model import CONFIRMED, LOOSE, PARTIAL, Edge, Evidence, Inventory, Node, Repo, Resolved
from archdiag.resolve import resolve
from archdiag.scan import scan_workspace
from archdiag.views import MAX_NODES, ScopeError, build_view, cond_label

_C = {}


def fixture():
    if "r" not in _C:
        cfg = load_config(ESTATE / "architecture-diagrams")
        r = resolve(scan_workspace(ESTATE, cfg), cfg)
        _C["r"] = r
        _C["g"] = default_groups(r)
    return _C["r"], _C["g"]


def node(v, nid):
    hits = [n for n in v.nodes if n.id == nid]
    assert hits, "%s not in view: %s" % (nid, sorted(n.id for n in v.nodes))
    return hits[0]


def edges(v, src, dst):
    return [e for e in v.edges if e.src == src and e.dst == dst]


def well_formed(v):
    ids = [n.id for n in v.nodes]
    assert len(ids) == len(set(ids))
    for e in v.edges:
        assert e.src in ids and e.dst in ids, (e.src, e.dst)
    assert len(v.nodes) <= MAX_NODES


# ------------------------------------------------------------------ brief tests

def test_landscape_shape():
    r, g = fixture()
    v = build_view(r, g, "landscape", None)
    well_formed(v)
    ids = {n.id for n in v.nodes}
    assert {"app:%s" % a.name for a in g.apps} <= ids
    assert len([n for n in v.nodes if n.id.startswith("app:")]) == 6
    assert "dataset:CLM.MASTER.KSDS" in ids and "queue:CLM.REQ.LQ" in ids
    assert edges(v, "app:claims-api", "queue:CLM.REQ.LQ")
    assert node(v, "app:claims-db").kind == "datastore"
    # 9 classes and one partly known link inside: the final-fix traps PaymentArchiveRepository,
    # ClaimHistoryRepository and PartnerClient (its path-only REST match to our own endpoint
    # is partial, Ruling 36)
    assert node(v, "app:claims-api").detail_lines == ["2 endpoints · 9 classes",
                                                      "1 partly known link inside"]
    # tables of a datastore app are inside it, not separate boxes
    # (a table no DDL defines belongs to no app: shared by two apps, it is its own box, I5)
    assert [i for i in ids if i.startswith("table:")] == ["table:CLMS.CLMHIST"]
    sql = edges(v, "app:claims-online", "app:claims-db")
    assert [e.label for e in sql] == ["SQL · CLAIM"]
    assert sql[0].status == CONFIRMED and len(sql[0].underlying) == 2


def test_flow_job_rows():
    r, g = fixture()
    v = build_view(r, g, "flow_job", "CLMD100")
    well_formed(v)
    lane = [n.label for n in v.nodes if n.row == "lane"]
    assert lane == ["SORT", "CLMB200", "CLMB300", "IEBGENER", "DMBATCH"]
    assert "Also exists as: claims-batch/jcl/test/CLMD100.jcl" in v.notes


def test_flow_tx_from_page():
    r, g = fixture()
    v = build_view(r, g, "flow_tx", "claims/:id")
    well_formed(v)
    ids = {n.id for n in v.nodes}
    assert {"queue:CLM.REQ.LQ", "transaction:CLMI", "program:CLMO100", "table:CLMS.CLAIM"} <= ids


def test_repomap_has_evidence_files():
    r, g = fixture()
    v = build_view(r, g, "repomap", None)
    well_formed(v)
    card = node(v, "repo:claims-api")
    assert "MqClaimGateway.java" in " ".join(card.detail_lines)


def _synthetic(edge_specs, repos=("a", "b", "c", "d")):
    """Programs P<repo><i> in each repo; edges (src, dst, status) between them."""
    nodes = {}
    for spec in edge_specs:
        for nid in spec[:2]:
            name = nid.split(":", 1)[1]
            nodes[nid] = Node(nid, "program", name, name[1], [Evidence(name[1], "%s.cbl" % name, 1, "")])
    ev = Evidence("a", "x.cbl", 3, "CALL")
    es = [Edge(s, op, d, st, None if st == CONFIRMED else "why", [ev]) for s, d, st, op in edge_specs]
    inv = Inventory("ws", [Repo(x, x) for x in repos], dict(nodes), [], "fp", {})
    return Resolved(inv, nodes, es)


def test_status_combination():
    r = _synthetic([("program:Pa1", "program:Pb1", CONFIRMED, "call"),
                    ("program:Pa4", "program:Pb4", CONFIRMED, "call"),
                    ("program:Pa2", "program:Pb2", PARTIAL, "call"),
                    ("program:Pc1", "program:Pd1", PARTIAL, "call"),
                    ("program:Pc2", "program:Pd2", LOOSE, "call"),
                    ("program:Pc3", "program:Pa3", LOOSE, "link")])
    v = build_view(r, default_groups(r), "landscape", None)
    # a line is never more certain than a target it names (final review C3): each target
    # rides on the line of its own status, so Pb2 (partial) gets a dotted line beside the
    # solid one to Pb1 and Pb4
    ab = {e.status: e for e in edges(v, "app:a", "app:b")}
    cd = {e.status: e for e in edges(v, "app:c", "app:d")}
    ca, = edges(v, "app:c", "app:a")
    assert sorted(ab) == [CONFIRMED, PARTIAL] and sorted(cd) == [LOOSE, PARTIAL]
    assert ca.status == LOOSE
    assert ab[CONFIRMED].label == "CALL · Pb1, Pb4" and ab[PARTIAL].label == "CALL · Pb2"
    assert (cd[PARTIAL].label, cd[LOOSE].label) == ("CALL · Pd1", "CALL · Pd2")
    solid = ab[CONFIRMED]
    assert len(solid.underlying) == 2 and len(solid.evidence) == 1  # same evidence kept once


def test_scope_error_suggests():
    r, g = fixture()
    with pytest.raises(ScopeError) as e:
        build_view(r, g, "flow_job", "CLMD10")
    assert "CLMD100" in e.value.suggestions


def _big(n=200):
    nodes = {}
    for i in range(n):
        nid = "program:P%03d" % i
        nodes[nid] = Node(nid, "program", "P%03d" % i, "big", [Evidence("big", "P%03d.cbl" % i, 1, "")])
    nodes["program:OUT1"] = Node("program:OUT1", "program", "OUT1", "other", [Evidence("other", "o.cbl", 1, "")])
    es = [Edge("program:P%03d" % i, "call", "program:P%03d" % (i + 1), CONFIRMED, None, [])
          for i in range(0, 20)]
    es.append(Edge("program:P150", "call", "program:OUT1", CONFIRMED, None, []))
    es.append(Edge("program:P151", "call", "program:P152", PARTIAL, "via variable", []))
    inv = Inventory("ws", [Repo("big", "big"), Repo("other", "other")], dict(nodes), [], "fp", {})
    return Resolved(inv, nodes, es)


def test_cap():
    r = _big()
    v = build_view(r, default_groups(r), "application", "big")
    well_formed(v)
    assert any(n.id.startswith("more:") for n in v.nodes)
    assert any("Too big" in note for note in v.notes)
    more = [n for n in v.nodes if n.id.startswith("more:")]
    assert all(n.kind == "more" for n in more)
    assert more[0].id == "more:group:big:program" and more[0].label.startswith("… ")
    ids = {n.id for n in v.nodes}
    # kept: the node with a cross-app edge and both ends of the partial edge
    assert {"program:P150", "program:P151", "program:P152", "program:OUT1"} <= ids
    assert [e.status for e in edges(v, "program:P151", "program:P152")] == [PARTIAL]


def test_cap_keeps_confirmed_links_inside_a_folded_box_in_the_report():
    # final review I8: a confirmed line between two boxes folded into one "… N more" box
    # is not drawn, but its resolver edges stay listed (on the folded box's underlying)
    from archdiag.render.report import links_report
    r = _big()
    # a chain of confirmed calls through every program: folding must cut some of them
    r.edges[:] = [Edge("program:P%03d" % i, "call", "program:P%03d" % (i + 1), CONFIRMED, None,
                       []) for i in range(0, 199)]
    v = build_view(r, default_groups(r), "application", "big")
    more = [n for n in v.nodes if n.id.startswith("more:")]
    drawn = {id(u) for e in v.edges for u in e.underlying}
    listed = {id(u) for n in more for u in n.underlying}
    assert listed  # the fixture folds some P -> P calls into one box
    for e in r.edges:
        if e.src.startswith("program:P") and e.dst.startswith("program:P"):
            assert id(e) in drawn or id(e) in listed, (e.src, e.dst)
    report = links_report(v, r)
    for e in r.edges:
        if e.src.startswith("program:P") and e.dst.startswith("program:P"):
            assert "| program %s | call | program %s |" % (e.src[8:], e.dst[8:]) in report, e.src


# ------------------------------------------------------------------ further checks

def test_every_level_lays_out():
    from archdiag.layout import layout_for
    r, g = fixture()
    for level, scope in (("landscape", None), ("application", "claims-online"),
                         ("application", "claims-batch"), ("flow_job", "CLMD100"),
                         ("flow_tx", "CLMI"), ("flow_tx", "claims/:id"),
                         ("flow_tx", "GET /api/claims/{id}"), ("repomap", None),
                         ("repomap", "claims-api")):
        v = build_view(r, g, level, scope)
        well_formed(v)
        L = layout_for(v, lambda n: (140, 80))
        assert len(L.routes) == len(v.edges)


def test_landscape_keeps_every_loose_end():
    r, g = fixture()
    v = build_view(r, g, "landscape", None)
    ids = {n.id for n in v.nodes}
    drawn = {u.dst for e in v.edges for u in e.underlying}
    for nid in r.nodes:
        if nid.startswith("missing:"):
            assert nid in ids or nid in drawn, nid
    for n in v.nodes:
        if n.kind == "missing":
            assert n.status in (PARTIAL, LOOSE)
            assert all(e.status != CONFIRMED for e in v.edges if n.id in (e.src, e.dst))
    # the far side of an exchange keeps its own box
    for nid in ("missing:writer:CLM.MASTER.KSDS", "missing:reader:CLAIMS.AUDIT",
                "missing:endpoint:DELETE /api/claims/{}", "missing:queue-consumer:CLM.AUDIT"):
        assert node(v, nid).group is None
    assert edges(v, "dataset:CLM.MASTER.KSDS", "missing:writer:CLM.MASTER.KSDS")[0].status == LOOSE
    # NDM transfer stays dotted
    ndm, = edges(v, "app:claims-batch", "external:NDM:FINANCE")
    assert ndm.status == PARTIAL


def test_landscape_folds_each_apps_loose_ends():
    r, g = fixture()
    v = build_view(r, g, "landscape", None)
    # 20: the final-fix traps make CLAIMS.DAILY (CLMEXT, duplicate PROC), CLM.AUDIT
    # (CLMO140, MQ handles) and the DDL-less table CLMS.CLMHIST (CLMB510) shared between apps
    assert len(v.nodes) == 20
    box = node(v, "missing:app:claims-online")
    assert (box.kind, box.label, box.status) == ("missing", "7 loose ends", LOOSE)
    assert box.detail_lines == ["ERRMSG · which program? · CLMO120 … +4"]
    e, = edges(v, "app:claims-online", "missing:app:claims-online")
    want = {"missing:copybook:ERRMSG", "missing:program:?CLMO100:26", "missing:program:CLMO120",
            "missing:table:?POLICY", "missing:transaction:CLMB", "missing:transaction:CLMX",
            "missing:queue:?CLMO140:27"}
    assert {u.dst for u in e.underlying} == want and len(e.underlying) == 8
    assert e.status == LOOSE  # the least certain: a red end never looks merely dotted
    assert not want & {n.id for n in v.nodes}
    # partly known links inside one application are counted on its box
    assert "1 partly known link inside" in node(v, "app:claims-online").detail_lines
    # 2 + the uncalled claims-batch copy of CLMEXT (scanned with its defaults: partial)
    assert "4 partly known links inside" in node(v, "app:claims-batch").detail_lines


def test_landscape_shared_code():
    r, g = fixture()
    v = build_view(r, g, "landscape", None)
    cb, = edges(v, "app:shared-copybooks", "app:claims-batch")
    # ×5: CLMB200, CLMB300 and the I3 trap CLMB500 (CLMREC, ADDRREC.cbl, CLMPROC)
    assert cb.kind == "shared_code" and cb.label == "COPY ×5"
    co, = edges(v, "app:shared-copybooks", "app:claims-online")
    assert co.label == "COPY ×1"


def test_suggested_links_are_partial(tmp_path):
    r, _ = fixture()
    p = tmp_path / "groups.json"
    p.write_text(json.dumps({"apps": [], "suggested_links": [
        {"from": "claims-batch", "to": "claims-api", "note": "nightly feed"}]}))
    g = load_groups(p, r)
    v = build_view(r, g, "landscape", None)
    e, = edges(v, "app:claims-batch", "app:claims-api")
    assert e.status == PARTIAL and "suggested" in e.label
    # never into the resolved links
    assert not any(x.op == "suggested" for x in r.edges)


def test_flow_job_details():
    r, g = fixture()
    v = build_view(r, g, "flow_job", "CLMD100")
    lane = [n for n in v.nodes if n.row == "lane"]
    assert [n.sublabel.split()[0] for n in lane] == ["STEP010", "STEP020", "STEP030", "STEP040", "STEP050"]
    assert lane[0].kind == "utility" and lane[1].kind == "program"
    rows = {n.id: n.row for n in v.nodes}
    assert rows["dataset:CLM.MASTER.KSDS"] == "above"
    assert rows["dataset:CLAIMS.DAILY"] == "below"  # written, then read by later steps
    assert rows["table:CLMS.CLAIM"] == "above"
    assert rows["missing:reader:CLAIMS.AUDIT"] == "below"
    s1, s2 = lane[0].id, lane[1].id
    step_edge, = edges(v, s1, s2)
    assert step_edge.label.startswith("if RC = 0") and "&&SORTED" in step_edge.label
    assert edges(v, lane[2].id, lane[3].id)[0].label == "if RC ≤ 4"
    # the SELECT of CLMB200 is drawn on its step
    assert edges(v, "table:CLMS.CLAIM", s2)
    # the step box stands for its runs edge
    assert lane[1].underlying and lane[1].underlying[0].op == "runs"
    # partly known call to a subprogram stays dotted
    call, = edges(v, s2, "program:CLMB210")
    assert call.status == PARTIAL
    ndm, = edges(v, lane[4].id, "external:NDM:FINANCE")
    assert ndm.status == PARTIAL
    assert edges(v, "dataset:CLAIMS.AUDIT", "missing:reader:CLAIMS.AUDIT")[0].status == LOOSE
    # the drawn copy is the first by path; the test copy appears only in the note
    assert all("/test/" not in n.id for n in v.nodes)


def test_flow_job_gdg_vsam_sysout():
    r, g = fixture()
    v = build_view(r, g, "flow_job", "CLMD100")
    by = {n.id: n for n in v.nodes}
    assert by["dataset:CLAIMS.DAILY"].kind == "gdg"
    assert by["dataset:CLM.MASTER.KSDS"].kind == "vsam"
    s2, s3 = "step:claims-batch/jcl/CLMD100.jcl#STEP020", "step:claims-batch/jcl/CLMD100.jcl#STEP030"
    assert [e.label for e in edges(v, s2, "dataset:CLAIMS.DAILY")] == ["write (+1)"]
    assert [e.label for e in edges(v, "dataset:CLAIMS.DAILY", s3)] == ["read (0)"]
    so = [n for n in v.nodes if n.id.startswith("sysout:")]
    assert [(n.label, n.sublabel, n.row) for n in so] == [("REPORT", "SYSOUT=A", "below")]
    assert edges(v, s3, so[0].id)


def test_flow_job_by_id():
    r, g = fixture()
    v = build_view(r, g, "flow_job", "job:claims-batch/jcl/test/CLMD100.jcl")
    assert all("/test/" in n.id for n in v.nodes if n.row == "lane")
    assert "Also exists as: claims-batch/jcl/CLMD100.jcl" in v.notes


def test_cond_label():
    assert cond_label("COND=(0,NE)") == "if RC = 0"
    assert cond_label("RC <= 4") == "if RC ≤ 4"
    assert cond_label("COND=(4,LT)") == "if RC ≤ 4"
    assert cond_label("COND=((4,LT),(8,GT,STEP1))") == "if RC ≤ 4 and STEP1 RC ≥ 8"
    assert cond_label("COND=EVEN") == "even after an abend"
    assert cond_label(None) == ""


def test_flow_tx_numbers_and_maps():
    r, g = fixture()
    v = build_view(r, g, "flow_tx", "CLMI")
    ids = {n.id for n in v.nodes}
    assert {"program:CLMO100", "program:CLMO110", "map:CLMM01", "missing:program:?CLMO100:26",
            "missing:table:?POLICY"} <= ids
    nums = [e.number for e in v.edges]
    assert sorted(nums) == list(range(1, len(nums) + 1))
    first = min(v.edges, key=lambda e: e.number)
    assert (first.src, first.dst) == ("transaction:CLMI", "program:CLMO100")
    link, = edges(v, "program:CLMO100", "program:CLMO110")
    assert link.status == PARTIAL
    sel, = edges(v, "program:CLMO100", "table:CLMS.CLAIM")
    assert sel.label == "SELECT" and len(sel.underlying) == 2


def test_flow_tx_page_reaches_java_and_mq():
    r, g = fixture()
    v = build_view(r, g, "flow_tx", "claims/:id")
    ids = {n.id for n in v.nodes}
    # page → component → service → endpoint → controller → gateway
    assert {"component:claims-portal/ClaimService", "endpoint:GET /api/claims/{}",
            "class:claims-api/ClaimController", "class:claims-api/MqClaimGateway",
            "queue:CLM.RSP", "missing:endpoint:DELETE /api/claims/{}"} <= ids
    assert any(e.src == "class:claims-api/MqClaimGateway" and e.dst == "queue:CLM.RSP" for e in v.edges)


def test_flow_tx_scope_error():
    r, g = fixture()
    with pytest.raises(ScopeError) as e:
        build_view(r, g, "flow_tx", "CLMJ")
    assert "CLMI" in e.value.suggestions


def test_application_view():
    r, g = fixture()
    v = build_view(r, g, "application", "claims-online")
    well_formed(v)
    by = {n.id: n for n in v.nodes}
    assert by["program:CLMO100"].group == "group:claims-online"
    assert by["table:CLMS.CLAIM"].kind == "neighbor"
    assert by["queue:CLM.REQ.LQ"].group == "group:claims-online"  # defined in this repo
    assert by["class:claims-api/MqClaimGateway"].kind == "neighbor"
    assert [x.id for x in v.groups] == ["group:claims-online"]
    with pytest.raises(ScopeError) as e:
        build_view(r, g, "application", "claims-onlin")
    assert "claims-online" in e.value.suggestions


def test_application_batch_collapses_steps():
    r, g = fixture()
    v = build_view(r, g, "application", "claims-batch")
    ids = {n.id for n in v.nodes}
    assert not any(i.startswith("step:") for i in ids)
    assert not any("&&" in i for i in ids)
    assert edges(v, "job:claims-batch/jcl/CLMD100.jcl", "program:CLMB200")


def test_repomap_links_and_stubs():
    r, g = fixture()
    v = build_view(r, g, "repomap", None)
    assert len([n for n in v.nodes if n.kind == "repo"]) == 6
    from archdiag.resolve import repo_links
    assert len([e for e in v.edges if e.src.startswith("repo:") and e.dst.startswith("repo:")]) \
        == len(repo_links(r))
    labels = {e.label for e in v.edges}
    assert "queue CLM.REQ.LQ" in labels
    card = node(v, "repo:claims-batch")
    assert card.highlight >= 1 and card.detail_lines[card.highlight:]  # evidence files first
    assert "jcl/CLMD100.jcl" in card.detail_lines[:card.highlight]
    assert "missing:reader:CLAIMS.AUDIT" in {n.id for n in v.nodes}
    rates = [e for e in v.edges if e.dst == "external:rates.example.com"]
    assert rates and rates[0].status == LOOSE
    v2 = build_view(r, g, "repomap", "claims-portal")
    assert {n.id for n in v2.nodes if n.kind == "repo"} == {"repo:claims-portal", "repo:claims-api"}


def test_bad_level():
    r, g = fixture()
    with pytest.raises(ScopeError) as e:
        build_view(r, g, "landscap", None)
    assert "landscape" in e.value.suggestions


def test_large_landscape_capped():
    nodes, es = {}, []
    repos = ["r%02d" % i for i in range(60)]
    for i, repo in enumerate(repos):
        nid = "program:P%02d" % i
        nodes[nid] = Node(nid, "program", "P%02d" % i, repo, [])
    for i in range(59):
        es.append(Edge("program:P%02d" % i, "call", "program:P%02d" % (i + 1), CONFIRMED, None, []))
    for i in range(10):
        m = "missing:program:X%d" % i
        nodes[m] = Node(m, "missing", "X%d" % i, None, [], {"target_kind": "program"})
        es.append(Edge("program:P%02d" % i, "call", m, LOOSE, None, []))
    inv = Inventory("ws", [Repo(x, x) for x in repos], dict(nodes), [], "fp", {})
    r = Resolved(inv, nodes, es)
    v = build_view(r, default_groups(r), "landscape", None)
    well_formed(v)
    # folding never turns a loose link solid
    loose = [e for e in r.edges if e.status == LOOSE]
    drawn = [u for e in v.edges if e.status == LOOSE for u in e.underlying]
    assert len(drawn) == len(loose)
    assert all(u.status != LOOSE for e in v.edges if e.status != LOOSE for u in e.underlying)
    assert not any(n.id.startswith("more:None:") for n in v.nodes)
    for n in v.nodes:
        if n.id.startswith("more:") and n.kind == "missing":
            assert "loose ends" in n.label


def test_application_keeps_look_alikes_and_utilities():
    ds = {"dataset:A.X": None, "dataset:B.X": None}
    nodes = {nid: Node(nid, "dataset", nid[8:], None, [], {"names": [nid[8:]]}) for nid in ds}
    for nid, repo in (("step:a/j#S1", "a"), ("step:b/j#S1", "b")):
        nodes[nid] = Node(nid, "step", "S1", repo, [], {"order": 1})
    nodes["utility:SORT"] = Node("utility:SORT", "utility", "SORT", None, [])
    es = [Edge("step:a/j#S1", "write", "dataset:A.X", CONFIRMED, None, []),
          Edge("step:b/j#S1", "read", "dataset:B.X", CONFIRMED, None, []),
          Edge("step:a/j#S1", "runs", "utility:SORT", CONFIRMED, None, []),
          Edge("step:b/j#S1", "runs", "utility:SORT", CONFIRMED, None, []),
          Edge("dataset:A.X", "maybe_same", "dataset:B.X", PARTIAL, "differ only by A/B", [])]
    inv = Inventory("ws", [Repo("a", "a"), Repo("b", "b")], dict(nodes), [], "fp", {})
    r = Resolved(inv, nodes, es)
    v = build_view(r, default_groups(r), "application", "a")
    by = {n.id: n for n in v.nodes}
    assert by["dataset:A.X"].group == "group:a"
    assert by["utility:SORT"].group == "group:a" and by["utility:SORT"].kind == "utility"
    assert by["dataset:B.X"].kind == "neighbor"
    same, = edges(v, "dataset:A.X", "dataset:B.X")
    assert same.status == PARTIAL


def test_cap_is_fast_on_large_views():
    import time
    t = time.time()
    v = build_view(_big(3000), default_groups(_big(3000)), "application", "big")
    assert len(v.nodes) <= MAX_NODES and time.time() - t < 5


# ------------------------------------------------------------------ fix round 1

def _with_suggestion(tmp_path, frm, to, note="nightly feed"):
    r, _ = fixture()
    p = tmp_path / "groups.json"
    p.write_text(json.dumps({"apps": [], "suggested_links": [{"from": frm, "to": to, "note": note}]}))
    return r, load_groups(p, r)


def test_undrawable_suggestions_are_noted(tmp_path):
    r, g = _with_suggestion(tmp_path, "claims-batch", "claims-api")
    msg = "Copilot suggests a link claims-batch → claims-api (nightly feed); shown on the landscape"
    assert msg in build_view(r, g, "application", "claims-batch").notes
    assert msg in build_view(r, g, "flow_job", "CLMD100").notes
    r2, g2 = _with_suggestion(tmp_path, "claims-portal", "shared-copybooks")
    assert not build_view(r2, g2, "flow_job", "CLMD100").notes[1:]  # not about this job
    r, g = _with_suggestion(tmp_path, "program:CLMO100", "program:CLMB200", "")
    v = build_view(r, g, "flow_tx", "CLMI")
    assert "Copilot suggests a link program:CLMO100 → program:CLMB200; shown on the landscape" \
        in v.notes
    r, g = _with_suggestion(tmp_path, "program:CLMO100", "program:CLMO110")
    v = build_view(r, g, "flow_tx", "CLMI")
    e, = [e for e in v.edges if e.underlying and e.underlying[0].op == "suggested"]
    assert e.status == PARTIAL and e.number == len(v.edges)
    assert any("inside one application" in n for n in build_view(r, g, "landscape", None).notes)


def test_flow_tx_walkthrough_order():
    r, g = fixture()
    v = build_view(r, g, "flow_tx", "claims/:id")
    num = {(e.src, e.dst): e.number for e in v.edges}
    t = num[("queue:CLM.REQ.LQ", "transaction:CLMI")]
    assert num[("transaction:CLMI", "program:CLMO100")] == t + 1
    assert num[("program:CLMO100", "queue:CLM.REQ.LQ")] == t + 2
    # the handler hop follows the REST call that reached it
    assert num[("endpoint:GET /api/claims/{}", "class:claims-api/ClaimController")] == \
        num[("component:claims-portal/ClaimService", "endpoint:GET /api/claims/{}")] + 1
    assert sorted(num.values()) == list(range(1, len(v.edges) + 1))
    # a link back to a box met earlier comes after the box it starts from
    assert num[("program:CLMO100", "queue:CLM.RSP")] > num[("transaction:CLMI", "program:CLMO100")]


def test_flow_tx_depth_cut_noted():
    nodes = {"transaction:T1": Node("transaction:T1", "transaction", "T1", "a", [])}
    es = []
    prev = "transaction:T1"
    for i in range(12):
        nid = "program:P%02d" % i
        nodes[nid] = Node(nid, "program", "P%02d" % i, "a", [])
        es.append(Edge(prev, "runs" if i == 0 else "call", nid, CONFIRMED, None, []))
        prev = nid
    inv = Inventory("ws", [Repo("a", "a")], dict(nodes), [], "fp", {})
    r = Resolved(inv, nodes, es)
    v = build_view(r, default_groups(r), "flow_tx", "T1")
    assert "Stopped after 8 hops; 3 more links not drawn" in v.notes
    assert len(v.edges) == 9


def test_job_structure_lines_are_sequence():
    r, g = fixture()
    v = build_view(r, g, "flow_job", "CLMD100")
    lane = [n.id for n in v.nodes if n.row == "lane"]
    assert {e.kind for e in v.edges if e.dst in lane and (e.src in lane or e.src.startswith("job:"))} \
        == {"sequence"}
    assert {e.kind for e in v.edges if e.dst.startswith("sysout:")} == {"sequence"}
    assert all(e.kind != "sequence" for e in v.edges if e.underlying and
               e.dst not in lane)


def test_called_program_data_drawn_on_its_own_box():
    nodes = {
        "job:a/j": Node("job:a/j", "job", "J", "a", []),
        "step:a/j#S1": Node("step:a/j#S1", "step", "S1", "a", [], {"order": 1, "job": "job:a/j"}),
        "program:P1": Node("program:P1", "program", "P1", "a", []),
        "program:P2": Node("program:P2", "program", "P2", "a", []),
        "table:S.T": Node("table:S.T", "table", "S.T", "a", [], {"name": "T"}),
        "table:S.U": Node("table:S.U", "table", "S.U", "a", [], {"name": "U"}),
    }
    es = [Edge("step:a/j#S1", "runs", "program:P1", CONFIRMED, None, []),
          Edge("program:P1", "call", "program:P2", CONFIRMED, None, []),
          Edge("program:P1", "select", "table:S.U", CONFIRMED, None, []),
          Edge("program:P2", "select", "table:S.T", CONFIRMED, None, [])]
    inv = Inventory("ws", [Repo("a", "a")], dict(nodes), [], "fp", {})
    r = Resolved(inv, nodes, es)
    v = build_view(r, default_groups(r), "flow_job", "J")
    assert edges(v, "table:S.T", "program:P2") and not edges(v, "table:S.T", "step:a/j#S1")
    assert edges(v, "table:S.U", "step:a/j#S1")
    for e in v.edges:
        for u in e.underlying:
            if u.op == "select":
                assert u.src == e.dst or (u.src == "program:P1" and e.dst == "step:a/j#S1")


def test_repomap_caps_evidence_files():
    nodes = {"program:Q": Node("program:Q", "program", "Q", "b", [Evidence("b", "q.cbl", 1, "")])}
    es = []
    for i in range(12):
        nid = "program:P%02d" % i
        ev = Evidence("a", "f%02d.cbl" % i, 1, "")
        nodes[nid] = Node(nid, "program", "P%02d" % i, "a", [ev])
        es.append(Edge(nid, "call", "program:Q", CONFIRMED, None, [ev]))
    inv = Inventory("ws", [Repo("a", "a"), Repo("b", "b")], dict(nodes), [], "fp", {})
    r = Resolved(inv, nodes, es)
    card = node(build_view(r, default_groups(r), "repomap", None), "repo:a")
    assert card.highlight == 8
    assert card.detail_lines[8] == "… 4 more evidence files"
