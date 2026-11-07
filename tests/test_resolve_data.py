from __future__ import annotations

from conftest import ESTATE
from archdiag.config import Config, load_config
from archdiag.model import Evidence, Inventory, Node, Ref
from archdiag.resolve import repo_links, resolve
from archdiag.scan import scan_workspace

_CACHE = {}


def resolved():
    if "r" not in _CACHE:
        cfg = load_config(ESTATE / "architecture-diagrams")
        _CACHE["r"] = resolve(scan_workspace(ESTATE, cfg), cfg)
    return _CACHE["r"]


def edges(src=None, op=None, dst=None, r=None):
    r = r or resolved()
    return [e for e in r.edges
            if (src is None or e.src == src) and (op is None or e.op == op)
            and (dst is None or e.dst == dst)]


def edge(src, op, dst, r=None):
    found = edges(src, op, dst, r)
    assert len(found) == 1, (src, op, dst, found)
    return found[0]


def edge_from(src, op, r=None):
    found = edges(src, op, None, r)
    assert len(found) == 1, (src, op, found)
    return found[0]


PROD = "step:claims-batch/jcl/CLMD100.jcl#"
TEST = "step:claims-batch/jcl/test/CLMD100.jcl#"


# fixture: datasets --------------------------------------------------------------------------

def test_disp_old_refined_by_open_mode():
    e = edge_from(PROD + "STEP020", "read")
    assert e.dst.endswith("#&&SORTED")
    assert e.dst == "dataset:claims-batch/jcl/CLMD100.jcl#&&SORTED"
    assert e.status == "confirmed"


def test_temp_datasets_do_not_link_across_jobs():
    assert edge_from(TEST + "STEP020", "read").dst == \
        "dataset:claims-batch/jcl/test/CLMD100.jcl#&&SORTED"
    assert not edges(op="loose", dst="missing:reader:&&SORTED")
    assert not [e for e in edges(op="loose") if "&&" in e.src]


def test_dataset_cross_repo_via_csd():
    e = edge("program:CLMO100", "read", "dataset:CLM.MASTER.KSDS")
    assert e.status == "confirmed"
    assert [x.path for x in e.evidence] == ["cobol/CLMO100.cbl", "csd/CLAIMS.csd"]


def test_env_copies_share_dataset_key():
    assert edge(PROD + "STEP020", "write", "dataset:CLAIMS.DAILY").status == "confirmed"
    assert edge(TEST + "STEP020", "write", "dataset:CLAIMS.DAILY").status == "confirmed"
    node = resolved().nodes["dataset:CLAIMS.DAILY"]
    assert node.attrs["names"] == ["PROD.CLAIMS.DAILY", "TEST.CLAIMS.DAILY"]
    assert node.attrs["env_dropped"] is True
    assert node.kind == "dataset" and node.repo is None


def test_without_env_config_keys_differ():
    r = resolve(scan_workspace(ESTATE, Config()), Config())
    assert "dataset:PROD.CLAIMS.DAILY" in r.nodes and "dataset:TEST.CLAIMS.DAILY" in r.nodes
    assert "dataset:CLAIMS.DAILY" not in r.nodes
    assert r.nodes["dataset:PROD.CLAIMS.DAILY"].attrs["env_dropped"] is False


def test_loose_written_never_read():
    e = edge("dataset:CLAIMS.AUDIT", "loose", "missing:reader:CLAIMS.AUDIT")
    assert e.status == "loose" and e.reason == "written but never read in these repos"
    assert e.evidence  # where it is written


def test_loose_read_never_written():
    e = edge("dataset:PAYMENT.FEED", "loose", "missing:writer:PAYMENT.FEED")
    assert e.status == "loose" and e.reason == "read but never written in these repos"


def test_transfer_partial():
    e = edge(PROD + "STEP050", "transfer", "external:NDM:FINANCE")
    assert e.status == "partial" and e.reason == "file transfer target is outside these repos"
    assert resolved().nodes["external:NDM:FINANCE"].kind == "external"


def test_extract_not_loose():
    assert not edges("dataset:CLAIMS.EXTRACT", "loose")
    assert edge(PROD + "STEP050", "read", "dataset:CLAIMS.EXTRACT").status == "confirmed"


def test_daily_not_loose():
    assert not edges("dataset:CLAIMS.DAILY", "loose")


def test_unresolved_symbol_partial():
    e = edge_from("step:claims-batch/jcl.pds/CLMD300#S2", "write")
    assert e.status == "partial" and "&UNDEF" in e.reason
    assert not edges(e.dst, "loose")


# fixture: tables ----------------------------------------------------------------------------

def test_table_rules():
    assert edge("program:CLMB200", "select", "table:CLMS.CLAIM").status == "confirmed"
    e = edge("program:CLMO100", "select", "missing:table:?POLICY")
    assert e.status == "partial" and e.reason == "ambiguous: CLMS.POLICY, ARCH.POLICY"
    assert resolved().nodes[e.dst].attrs["candidates"] == ["CLMS.POLICY", "ARCH.POLICY"]
    e = edges("program:CLMO100", "select", "table:CLMS.CLAIM")
    assert len(e) == 2 and all(x.status == "confirmed" for x in e)  # CLAIM and alias CLMS.CLM
    assert edge("class:claims-api/ClaimRepository", "select", "table:CLMS.POLICY").status == "confirmed"
    assert edge("program:CLMB300", "insert", "table:CLMS.PAYMENT").status == "confirmed"


def test_alias_evidence_includes_alias_definition():
    (e,) = [x for x in edges("program:CLMO100", "select", "table:CLMS.CLAIM")
            if x.evidence[0].line == 21]
    assert [x.path for x in e.evidence] == ["cobol/CLMO100.cbl", "ddl/CLAIM.sql", "ddl/CLAIM.sql"]


# fixture: queues ----------------------------------------------------------------------------

def test_queue_alias_and_trigger():
    assert edge("class:claims-api/MqClaimGateway", "put", "queue:CLM.REQ.LQ").status == "confirmed"
    assert edge("program:CLMO100", "get", "queue:CLM.REQ.LQ").status == "confirmed"
    assert edge("queue:CLM.REQ.LQ", "triggers", "transaction:CLMI").status == "confirmed"
    assert not edges("queue:CLM.REQ.LQ", "partial")


def test_queue_both_sides_confirmed():
    assert edge("program:CLMO100", "put", "queue:CLM.RSP").status == "confirmed"
    assert edge("class:claims-api/MqClaimGateway", "get", "queue:CLM.RSP").status == "confirmed"
    assert not edges("queue:CLM.RSP", "partial")


def test_queue_one_sided_partial():
    assert edge("class:claims-api/AuditPublisher", "put", "queue:CLM.AUDIT").status == "confirmed"
    e = edge("queue:CLM.AUDIT", "partial", "missing:queue-consumer:CLM.AUDIT")
    assert e.status == "partial" and e.reason == "how this queue reaches CICS isn't in these repos"


def test_bridge_trigger():
    e = edge_from("queue:CLM.BRIDGE.Q", "triggers")
    assert e.reason.startswith("CICS-MQ bridge")
    # CLMB is not defined in any CSD in the fixture: only one side found
    assert e.dst == "missing:transaction:CLMB" and e.status == "loose"


# fixture: REST ------------------------------------------------------------------------------

def test_rest():
    svc = "component:claims-portal/ClaimService"
    assert edge(svc, "http", "endpoint:GET /api/claims/{}").status == "confirmed"
    assert edge(svc, "http", "endpoint:POST /api/claims").status == "confirmed"
    assert edge(svc, "http", "missing:endpoint:DELETE /api/claims/{}").status == "loose"
    # Ruling 36: zcee.internal (claims-api's config) is not named in claims-online's config
    e = edge("class:claims-api/ClaimStatusClient", "http", "zosapi:GET /zos/claims/{}/status")
    assert e.status == "partial" and "host zcee.internal" in e.reason
    e = edge("class:claims-api/RatesClient", "http", "external:rates.example.com")
    assert e.status == "loose" and e.reason == "external or missing service"


def test_uses():
    assert edge("class:claims-api/ClaimController", "uses",
                "class:claims-api/MqClaimGateway").status == "confirmed"
    assert edge("page:claims-portal/claims/:id", "uses",
                "component:claims-portal/ClaimDetailsComponent").status == "confirmed"


def test_repo_links():
    links = repo_links(resolved())
    keyed = {(a, b, via): es for a, b, via, es in links}
    assert ("claims-api", "claims-online", "queue CLM.REQ.LQ") in keyed
    assert ("claims-batch", "claims-db", "table CLMS.CLAIM") in keyed
    assert ("claims-db", "claims-online", "table CLMS.CLAIM") in keyed
    assert ("claims-batch", "shared-copybooks", "copybook CLMREC") in keyed
    # a dataset with no definition links every repo that touches it
    assert ("claims-batch", "claims-online", "dataset CLM.MASTER.KSDS") in keyed
    assert ("claims-portal", "claims-api", "endpoint GET /api/claims/{}") not in keyed
    assert ("claims-api", "claims-portal", "endpoint GET /api/claims/{}") in keyed
    for a, b, via, es in links:
        assert a < b and es
    assert len(keyed) == len(links)  # one entry per (pair, resource)


# synthetic cases ----------------------------------------------------------------------------

def _ev(line, path="x", repo="r"):
    return Evidence(repo, path, line, "line %d" % line)


def _inv(nodes, refs):
    return Inventory("ws", [], {n.id: n for n in nodes}, refs, "fp", {})


def _step(job, name, pgm, repo="r"):
    sid = "step:%s/%s#%s" % (repo, job, name)
    return Node(sid, "step", name, repo, [_ev(1, job, repo)],
                {"pgm": pgm, "job": "job:%s/%s" % (repo, job)})


def _ds(step, op, name, line, **attrs):
    return Ref(step, op, "dataset", name, _ev(line, "a.jcl"), attrs.pop("reason", None), [],
               dict(attrs, ddname=attrs.get("ddname", "DD1")))


def _run(nodes, refs, quals=None):
    return resolve(_inv(nodes, refs), Config(environment_qualifiers=quals or []))


def _prog(name, files=None, repo="r"):
    return Node("program:" + name, "program", name, repo, [_ev(1, name + ".cbl", repo)],
                {"files": files or {}})


def test_update_refined_to_write_and_unknown_stays_update():
    s1, s2 = _step("a.jcl", "S1", "P1"), _step("a.jcl", "S2", "IDCAMS")
    refs = [Ref(s1.id, "runs", "program", "P1", _ev(1, "a.jcl")),
            _ds(s1.id, "update", "A.OUT", 2, ddname="OUTF"),
            _ds(s2.id, "update", "A.OTHER", 4)]
    r = _run([s1, s2, _prog("P1", {"OUTF": "extend"})], refs)
    assert edge(s1.id, "write", "dataset:A.OUT", r).status == "confirmed"
    assert edge(s2.id, "update", "dataset:A.OTHER", r).status == "confirmed"
    # update counts as both a read and a write: no loose end
    assert not edges("dataset:A.OTHER", "loose", r=r)
    assert edge("dataset:A.OUT", "loose", "missing:reader:A.OUT", r).status == "loose"


def test_update_refined_to_read():
    s1 = _step("a.jcl", "S1", "P1")
    refs = [Ref(s1.id, "runs", "program", "P1", _ev(1, "a.jcl")),
            _ds(s1.id, "update", "A.IN", 2, ddname="INF")]
    r = _run([s1, _prog("P1", {"INF": "input"})], refs)
    assert edge(s1.id, "read", "dataset:A.IN", r).status == "confirmed"


def test_proc_default_and_library_never_loose():
    s1 = _step("p.proc", "S1", "P1")
    why = "PROC default values; no caller in these repos"
    refs = [_ds(s1.id, "write", "X.ONLY.WRITTEN", 2, reason=why, proc_default=True),
            _ds(s1.id, "read", "LOAD.LIB", 3, ddname="STEPLIB", library=True)]
    r = _run([s1], refs)
    assert edge(s1.id, "write", "dataset:X.ONLY.WRITTEN", r).status == "partial"
    assert edge(s1.id, "read", "dataset:LOAD.LIB", r).status == "confirmed"
    assert not edges(op="loose", r=r)


def test_non_env_qualifier_is_partly_known_not_two_loose_ends():
    s1, s2 = _step("a.jcl", "S1", "P"), _step("b.jcl", "S1", "P")
    for quals, other in ((["PROD"], "dataset:X.Y"), ([], "dataset:PROD.X.Y")):
        refs = [_ds(s1.id, "write", "QA.X.Y", 2), _ds(s2.id, "read", "PROD.X.Y", 3)]
        r = _run([s1, s2], refs, quals)
        # a different key: the step edges don't merge
        assert edge(s1.id, "write", "dataset:QA.X.Y", r).status == "confirmed"
        assert edge(s2.id, "read", other, r).status == "confirmed"
        (e,) = edges(op="maybe_same", r=r)
        assert {e.src, e.dst} == {"dataset:QA.X.Y", other} and e.status == "partial"
        assert e.reason == "names differ only by first qualifier: QA vs PROD"
        assert not edges(op="loose", r=r)


def test_several_first_qualifier_candidates():
    s1, s2, s3 = (_step(j, "S1", "P") for j in ("a.jcl", "b.jcl", "c.jcl"))
    refs = [_ds(s1.id, "write", "QA.X.Y", 2), _ds(s2.id, "read", "DEV.X.Y", 3),
            _ds(s3.id, "read", "UAT.X.Y", 4)]
    r = _run([s1, s2, s3], refs)
    e = edge("dataset:QA.X.Y", "maybe_same", "missing:dataset:?QA.X.Y", r)
    assert e.status == "partial"
    assert r.nodes[e.dst].attrs["candidates"] == ["DEV.X.Y", "UAT.X.Y"]
    assert not edges("dataset:QA.X.Y", "loose", r=r)


def test_last_qualifier_difference_is_not_paired():
    s1, s2 = _step("a.jcl", "S1", "P"), _step("b.jcl", "S1", "P")
    r = _run([s1, s2], [_ds(s1.id, "write", "A.X.Y", 2), _ds(s2.id, "read", "A.X.Z", 3)])
    assert not edges(op="maybe_same", r=r) and len(edges(op="loose", r=r)) == 2


def test_library_writes_never_loose():
    s1 = _step("a.jcl", "LKED", "IEWL")
    r = _run([s1], [_ds(s1.id, "write", "PROD.LOADLIB", 2, ddname="SYSLMOD"),
                    _ds(s1.id, "write", "PROD.OTHER.LIB", 3, ddname="STEPLIB", library=True)])
    assert len(edges(s1.id, "write", r=r)) == 2
    assert not edges(op="loose", r=r)


def test_save_load_round_trip(tmp_path):
    from archdiag.store import load_resolved, save_json
    r = resolved()
    save_json(tmp_path / "links.json", r)
    back = load_resolved(tmp_path / "links.json")
    assert back.edges == r.edges and back.nodes == r.nodes


def test_transfer_write_counts_as_writer():
    s1, s2 = _step("a.jcl", "S1", "DMBATCH"), _step("b.jcl", "S1", "P")
    refs = [_ds(s1.id, "write", "IN.FEED", 2, via="transfer"), _ds(s2.id, "read", "IN.FEED", 3)]
    r = _run([s1, s2], refs)
    assert not edges(op="loose", r=r)


def test_dataset_name_not_worked_out():
    s1 = _step("a.jcl", "S1", "P")
    r = _run([s1], [_ds(s1.id, "read", None, 4, reason="backward reference *.S0.DD")])
    e = edge_from(s1.id, "read", r)
    assert e.status == "partial" and e.dst == "missing:dataset:?r/a.jcl#S1:4"


def test_cics_file_without_definition_is_loose():
    r = _run([_prog("P")], [Ref("program:P", "cics_file", "cicsfile", "NOFILE", _ev(3),
                                attrs={"io": "write"})])
    e = edge_from("program:P", "write", r)
    assert e.dst == "missing:cicsfile:NOFILE" and e.status == "loose"


def _table(full, repo="db", **attrs):
    schema, _, name = full.rpartition(".")
    a = {"schema": schema or None, "name": name, "type": "table"}
    a.update(attrs)
    return Node("table:" + full, "table", full, repo, [_ev(1, "ddl.sql", repo)], a)


def _sel(name, line=5, reason=None):
    return Ref("program:P", "select", "table", name, _ev(line), reason)


def test_env_schema_falls_back_to_unique_name():
    r = _run([_prog("P"), _table("CLMS.CLAIM")], [_sel("prod.claim")], ["PROD"])
    assert edge("program:P", "select", "table:CLMS.CLAIM", r).status == "confirmed"


def test_env_schema_with_several_names_is_ambiguous():
    r = _run([_prog("P"), _table("A.T"), _table("B.T")], [_sel("PROD.T")], ["PROD"])
    e = edge_from("program:P", "select", r)
    assert e.status == "partial" and e.dst == "missing:table:?PROD.T"
    assert e.reason == "ambiguous: A.T, B.T"


def test_qualified_without_exact_match():
    # a non-environment schema: dropping it is a guess, so only partly known
    r = _run([_prog("P"), _table("CLMS.CLAIM")], [_sel("OTHER.CLAIM")], ["PROD"])
    e = edge_from("program:P", "select", r)
    assert e.dst == "table:CLMS.CLAIM" and e.status == "partial"
    assert "OTHER" in e.reason
    r = _run([_prog("P")], [_sel("OTHER.NONE")])
    e = edge_from("program:P", "select", r)
    assert e.dst == "missing:table:OTHER.NONE" and e.status == "loose"


def test_unqualified_none_is_loose_and_duplicate_ddl_is_ambiguous():
    r = _run([_prog("P")], [_sel("NOPE")])
    assert edge("program:P", "select", "missing:table:NOPE", r).status == "loose"
    dup = _table("S.T")
    dup.evidence.append(_ev(9, "other.sql", "db2"))
    r = _run([_prog("P"), dup], [_sel("S.T")])
    e = edge_from("program:P", "select", r)
    assert e.dst == "table:S.T" and e.status == "partial" and e.reason.startswith("ambiguous")


def test_table_reason_and_unknown_name():
    r = _run([_prog("P"), _table("S.T")],
             [_sel("S.T", 5, "guessed"), _sel(None, 6, "dynamic SQL")])
    assert edge("program:P", "select", "table:S.T", r).status == "partial"
    e = edge("program:P", "select", "missing:table:?P:6", r)
    assert e.status == "partial" and e.reason == "dynamic SQL"


def test_three_part_table_name_is_partial():
    r = _run([_prog("P"), _table("S.T")], [_sel("LOC1.S.T")])
    e = edge("program:P", "select", "table:S.T", r)
    assert e.status == "partial" and e.reason == "table on DB2 location LOC1"


def test_alias_chain_followed():
    r = _run([_prog("P"), _table("S.A", type="alias", alias_of="S.B"),
              _table("S.B", type="alias", alias_of="S.T"), _table("S.T")], [_sel("S.A")])
    assert edge("program:P", "select", "table:S.T", r).status == "confirmed"


def _queue(name, repo="mq", **attrs):
    a = {"type": "local", "target": None, "process": None, "initq": None, "trigger": False,
         "bridge": False}
    a.update(attrs)
    return Node("queue:" + name, "queue", name, repo, [_ev(1, "q.mqsc", repo)], a)


def _q(src, op, name, line=3, reason=None):
    return Ref(src, op, "queue", name, _ev(line), reason)


def test_get_only_queue():
    r = _run([_prog("P")], [_q("program:P", "get", "IN.Q")])
    assert edge("program:P", "get", "queue:IN.Q", r).status == "confirmed"
    e = edge("queue:IN.Q", "partial", "missing:queue-producer:IN.Q", r)
    assert e.reason == "nothing in these repos puts to this queue"


def test_open_is_partial_and_satisfies_neither_side():
    why = "queue open mode not worked out"
    r = _run([_prog("P")], [_q("class:r/C", "open", "X.Q", 3, why)])
    assert edge("class:r/C", "open", "queue:X.Q", r).status == "partial"
    assert not edges("queue:X.Q", "partial", r=r)
    r = _run([_prog("P")], [_q("program:P", "put", "X.Q"), _q("class:r/C", "open", "X.Q", 4, why)])
    assert edge("queue:X.Q", "partial", "missing:queue-consumer:X.Q", r).status == "partial"


def test_guessed_queue_use_does_not_satisfy_the_other_side():
    refs = [_q("program:P", "put", "A.Q"),
            Ref("program:P", "get", "queue", None, _ev(8), "MOVE from WS-Q", ["A.Q"])]
    r = _run([_prog("P")], refs)
    assert edge("program:P", "get", "queue:A.Q", r).status == "partial"
    assert edge("queue:A.Q", "partial", "missing:queue-consumer:A.Q", r).status == "partial"


def _alias_case(put_first):
    nodes = [_prog("P"), _queue("A.ALIAS", type="alias", target="T.LOCAL", targtype="QUEUE")]
    refs = [_q("class:r/C", "put", "A.ALIAS", 3), _q("program:P", "get", "T.LOCAL", 4)]
    return _run(nodes, refs if put_first else refs[::-1])


def test_alias_to_undefined_queue_put_before_get():
    r = _alias_case(True)
    assert edge("class:r/C", "put", "queue:T.LOCAL", r).status == "confirmed"
    assert edge("program:P", "get", "queue:T.LOCAL", r).status == "confirmed"
    assert not edges(op="partial", r=r)


def test_alias_follow_does_not_depend_on_ref_order():
    key = lambda r: sorted((e.src, e.op, e.dst, e.status, e.reason) for e in r.edges)
    assert key(_alias_case(True)) == key(_alias_case(False))


def test_remote_queue_target_must_be_defined():
    nodes = [_prog("P"), _queue("R.Q", type="remote", target="FAR.Q")]
    r = _run(nodes, [_q("program:P", "put", "R.Q"), _q("program:P", "get", "FAR.Q", 4)])
    assert edge_from("program:P", "put", r).dst == "queue:R.Q"


def test_queue_names_upper_cased():
    r = _run([_prog("P"), _queue("CLM.X")], [_q("class:r/C", "put", "clm.x"),
                                             _q("program:P", "get", "CLM.X", 4)])
    assert edge("class:r/C", "put", "queue:CLM.X", r).status == "confirmed"
    assert not edges(op="partial", r=r)
    # a quoted mixed-case MQSC definition keeps its case and is matched exactly
    r = _run([_prog("P"), _queue("Mixed.Q")], [_q("class:r/C", "put", "Mixed.Q")])
    assert edge_from("class:r/C", "put", r).dst == "queue:Mixed.Q"


def test_mqsc_scanner_upper_cases_unquoted_names():
    from archdiag.scan import ScanContext
    from archdiag.scan.mq import scan_mqsc
    nodes, _ = scan_mqsc("r", "q.mqsc", "DEFINE QLOCAL(clm.low)\nDEFINE QLOCAL('Keep.Case')\n",
                         ScanContext())
    assert [n.id for n in nodes] == ["queue:CLM.LOW", "queue:Keep.Case"]


def test_repo_links_sorted():
    links = repo_links(resolved())
    assert [l[:3] for l in links] == sorted(l[:3] for l in links)


def test_put_plus_trigger_has_no_consumer_gap_and_missing_process():
    nodes = [_prog("P"), _queue("T.Q", trigger=True, process="NOPROC")]
    r = _run(nodes, [_q("program:P", "put", "T.Q")])
    e = edge_from("queue:T.Q", "triggers", r)
    assert e.status == "loose" and e.dst == "missing:mqprocess:NOPROC"


def test_defined_one_sided_queue_without_trigger_still_partial():
    r = _run([_prog("P"), _queue("D.Q")], [_q("program:P", "put", "D.Q")])
    assert edge("queue:D.Q", "partial", "missing:queue-consumer:D.Q", r).status == "partial"


def test_remote_queue_followed_when_target_defined():
    nodes = [_prog("P"), _queue("R.Q", type="remote", target="L.Q"), _queue("L.Q")]
    r = _run(nodes, [_q("program:P", "put", "R.Q"), _q("program:P", "get", "L.Q", 4)])
    assert edge("program:P", "put", "queue:L.Q", r).status == "confirmed"


def test_queue_name_not_worked_out():
    r = _run([_prog("P")], [Ref("program:P", "put", "queue", None, _ev(8), "MOVE from WS-Q",
                                ["A.Q", "B.Q"])])
    e = edge_from("program:P", "put", r)
    assert e.dst == "missing:queue:?P:8" and e.status == "partial"
    assert r.nodes[e.dst].attrs["candidates"] == ["A.Q", "B.Q"]


def _ep(method, path, repo="api", **attrs):
    nid = "endpoint:%s %s" % (method, path)
    return Node(nid, "endpoint", "%s %s" % (method, path), repo, [_ev(1, "C.java", repo)], attrs)


def _http(target, line=4, reason=None, src="component:web/S"):
    return Ref(src, "http", "endpoint", target, _ev(line, "s.ts", "web"), reason)


def test_any_method_endpoint_matches():
    r = _run([_ep("ANY", "/a/{}")], [_http("PUT /a/${id}")])
    assert edge("component:web/S", "http", "endpoint:ANY /a/{}", r).status == "confirmed"


def test_unresolved_endpoint_never_matched():
    ep = Node("endpoint:?api/C#get", "endpoint", "?api/C#get", "api", [_ev(1)],
              {"unresolved": True, "path": "/a"})
    r = _run([ep], [_http("GET /a")])
    assert edge_from("component:web/S", "http", r).dst == "missing:endpoint:GET /a"


def test_path_only_ambiguous_across_repos():
    zos = Node("zosapi:GET /a/{}", "zosapi", "GET /a/{}", "zos", [_ev(1, "pkg.xml", "zos")],
               {"method": "GET", "path": "/a/{}"})
    r = _run([_ep("GET", "/a/{}"), zos], [_http("GET /a/{x}")])
    e = edge_from("component:web/S", "http", r)
    assert e.status == "partial" and e.dst == "missing:endpoint:?GET /a/{}"
    assert e.reason == "ambiguous: endpoint:GET /a/{}, zosapi:GET /a/{}"
    assert r.nodes[e.dst].attrs["candidates"] == ["endpoint:GET /a/{}", "zosapi:GET /a/{}"]


def test_host_not_tied_to_target_repo_is_partial_and_reason_caps():
    # Ruling 36 (revises Ruling 17): an absolute URL matched on its path alone is partial
    r = _run([_ep("GET", "/a")], [_http("GET https://h.example/a", 4),
                                  _http("GET /a", 5, "base URL guessed"),
                                  _http("GET http://localhost:8080/a", 6)])
    got = [(e.evidence[0].line, e.status, e.reason) for e in edges(op="http", r=r)]
    assert got == [(4, "partial", "matched on path only; host h.example isn't tied to a "
                                  "scanned repo"),
                   (5, "partial", "base URL guessed"),
                   (6, "confirmed", None)]


def test_host_named_in_the_target_repos_config_is_confirmed():
    inv = _inv([_ep("GET", "/a")], [_http("GET https://h.example:8443/a", 4),
                                    _http("GET https://other.example/a", 5)])
    inv.config_hosts = {"api": ["h.example"], "web": ["other.example"]}
    r = resolve(inv, Config())
    got = [(e.evidence[0].line, e.status) for e in edges(op="http", r=r)]
    # other.example is only in the CALLER's config: not tied to the target repo
    assert got == [(4, "confirmed"), (5, "partial")]


def test_scan_collects_config_hosts_per_repo(tmp_path):
    for repo, rel, text in (
            ("svc", "src/main/resources/application.yml",
             "server:\n  public-url: https://Claims.Internal:9443/claims\n"),
            ("svc", "zosconnect/openapi.yaml", "servers:\n  - url: http://zcee.internal/x\n"),
            ("web", "src/environments/environment.ts",
             "export const environment = { apiBase: 'https://web.example/api' };\n")):
        root = tmp_path / repo
        root.mkdir(exist_ok=True)
        (root / ".archdiag-repo").write_text("")
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    inv = scan_workspace(tmp_path, Config())
    assert "claims.internal" in inv.config_hosts["svc"]
    assert inv.config_hosts["web"] == ["web.example"]


def test_http_target_not_worked_out():
    r = _run([], [_http(None, 7, "URL built at run time")])
    e = edge_from("component:web/S", "http", r)
    assert e.status == "partial" and e.dst == "missing:endpoint:?web/S:7"


def test_uses_missing_target_is_loose():
    r = _run([], [Ref("class:r/A", "uses", "class", "r/B", _ev(2))])
    assert edge_from("class:r/A", "uses", r).dst == "missing:class:r/B"
    assert edge_from("class:r/A", "uses", r).status == "loose"


def test_system_refs_dropped():
    r = _run([_prog("P")], [Ref("program:P", "put", "queue", "Q", _ev(1), attrs={"system": True})])
    assert r.edges == []


def _handler_class(repo="api", name="C"):
    return Node("class:%s/%s" % (repo, name), "class", name, repo, [_ev(3, "C.java", repo)], {})


def test_endpoint_runs_handler_class():
    ep = _ep("GET", "/a/{}", handler="class:api/C")
    r = _run([ep, _handler_class()], [])
    e = edge("endpoint:GET /a/{}", "runs", "class:api/C", r)
    assert e.status == "confirmed" and e.reason is None
    # the mapping annotation first, then the class definition
    assert [(v.path, v.line) for v in e.evidence] == [(ep.evidence[0].path, ep.evidence[0].line),
                                                       ("C.java", 3)]


def test_unresolved_endpoint_runs_handler_partial():
    ep = Node("endpoint:?api/C#get", "endpoint", "?C#get", "api", [_ev(9, "C.java", "api")],
              {"handler": "class:api/C", "unresolved": "path from ${base.path} not worked out"})
    r = _run([ep, _handler_class()], [])
    e = edge("endpoint:?api/C#get", "runs", "class:api/C", r)
    assert e.status == "partial" and e.reason == "path from ${base.path} not worked out"


def test_endpoint_without_handler_has_no_runs_edge():
    r = _run([_ep("GET", "/a")], [])
    assert edges(op="runs", r=r) == []
