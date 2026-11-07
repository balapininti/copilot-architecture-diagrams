from __future__ import annotations

from pathlib import Path

import pytest

from conftest import ESTATE
from archdiag.config import Config, load_config
from archdiag.model import Evidence, Inventory, Node, Ref
from archdiag.resolve import resolve
from archdiag.resolve.names import is_absolute_gdg, norm_dataset, norm_path, split_http
from archdiag.scan import scan_workspace

_CACHE = {}


def resolved():
    if "r" not in _CACHE:
        cfg = load_config(ESTATE / "architecture-diagrams")
        _CACHE["r"] = resolve(scan_workspace(ESTATE, cfg), cfg)
    return _CACHE["r"]


def edges(src=None, op=None, dst=None):
    return [e for e in resolved().edges
            if (src is None or e.src == src) and (op is None or e.op == op)
            and (dst is None or e.dst == dst)]


def edge(src, op, dst):
    found = edges(src, op, dst)
    assert len(found) == 1, (src, op, dst, found)
    return found[0]


def edge_from(src, op):
    found = edges(src, op)
    assert len(found) == 1, (src, op, found)
    return found[0]


# names --------------------------------------------------------------------------------------

def test_norm_dataset():
    assert norm_dataset("PROD.CLAIMS.DAILY(+1)", ["PROD", "TEST"]) == ("CLAIMS.DAILY", "PROD")
    assert norm_dataset("&&SORTED", []) == ("&&SORTED", None)
    assert norm_dataset("prod.claims.daily(0)", ["PROD"]) == ("CLAIMS.DAILY", "PROD")
    assert norm_dataset("PROD.CLAIMS.DAILY(-1)", []) == ("PROD.CLAIMS.DAILY", None)
    assert norm_dataset("QA.CLAIMS.DAILY", ["PROD", "TEST"]) == ("QA.CLAIMS.DAILY", None)
    assert norm_dataset("PROD.CLAIMS.G0001V00", ["prod"]) == ("CLAIMS", "PROD")
    # absolute generations match their base, and are flagged
    assert norm_dataset("PROD.CLAIMS.DAILY.G0012V00", ["PROD"]) == ("CLAIMS.DAILY", "PROD")
    assert norm_dataset("PROD.CLAIMS.DAILY.G0012V00", ["PROD"])[0] == \
        norm_dataset("PROD.CLAIMS.DAILY(+1)", ["PROD"])[0]
    assert is_absolute_gdg("PROD.CLAIMS.DAILY.G0012V00")
    assert not is_absolute_gdg("PROD.CLAIMS.DAILY(+1)")
    assert not is_absolute_gdg("PROD.CLAIMS.G12V00")
    # an unsigned number in parentheses is a generation, a member name is kept
    assert norm_dataset("PROD.CLAIMS.DAILY(1)", []) == ("PROD.CLAIMS.DAILY", None)
    assert norm_dataset("PROD.LOAD(CLMB200)", []) == ("PROD.LOAD(CLMB200)", None)
    # a lone qualifier is never dropped to nothing
    assert norm_dataset("PROD", ["PROD"]) == ("PROD", None)


def test_norm_path():
    assert norm_path("https://h:9443/zos/claims/${id}/status/") == "/zos/claims/{}/status"
    assert norm_path("/api/claims/:id") == "/api/claims/{}"


def test_split_http():
    assert split_http("GET https://zcee.internal:9443/zos/claims/{id}/status") == (
        "GET", "/zos/claims/{}/status", "zcee.internal")
    assert split_http("delete /api/claims/${id}") == ("DELETE", "/api/claims/{}", None)
    assert split_http("POST //Rates.Example.com/v1") == ("POST", "/v1", "rates.example.com")
    assert split_http("get") == ("GET", "/", None)


# programs -----------------------------------------------------------------------------------

def test_runs_confirmed():
    e = edge("step:claims-batch/jcl/CLMD100.jcl#STEP020", "runs", "program:CLMB200")
    assert e.status == "confirmed" and e.reason is None
    # evidence: the "from" side first, then the definition
    assert e.evidence[0].path == "jcl/CLMD100.jcl" and e.evidence[0].line == 10
    assert e.evidence[1].path == "cobol/CLMB200.cbl"


def test_ambiguous_link():
    e = edge("program:CLMO100", "link", "program:CLMO110")
    assert e.status == "partial" and e.reason.startswith("ambiguous")
    assert e.reason == ("ambiguous: defined in 2 places: claims-online/cobol/CLMO110.cbl, "
                        "claims-online/endevor/qa/CLMO110.cbl")
    assert len(e.evidence) == 3


def test_variable_call_single_candidate():
    e = edge("program:CLMB200", "call", "program:CLMB210")
    assert e.status == "partial" and "WS-PGM" in e.reason


def test_xctl_unknown():
    e = edge_from("program:CLMO100", "xctl")
    assert e.status == "partial" and e.dst.startswith("missing:program:?")
    assert e.dst == "missing:program:?CLMO100:26"
    assert e.reason == "XCTL to WS-NEXT-PGM, name set at run time"
    node = resolved().nodes[e.dst]
    assert node.kind == "missing" and node.attrs["candidates"] == []


def test_not_analyzed_is_confirmed():
    assert edge("program:CLMB200", "call", "notanalyzed:DATEUTIL").status == "confirmed"


def test_missing_program_loose():
    e = edge("transaction:CLMU", "runs", "missing:program:CLMO120")
    assert e.status == "loose"
    assert resolved().nodes["missing:program:CLMO120"].kind == "missing"


def test_transaction_and_zosapi_runs():
    assert edge("transaction:CLMI", "runs", "program:CLMO100").status == "confirmed"
    assert edge("zosapi:GET /zos/claims/{}/status", "runs",
                "program:CLMO130").status == "confirmed"


def test_system_calls_dropped():
    assert not [e for e in edges("program:CLMO100") if "MQ" in e.dst and e.op == "call"]
    assert not [e for e in resolved().edges if e.dst.endswith("SQLCA")]


def test_system_ref_gives_no_edge():
    inv = _inv([_prog("A", 1)],
               [Ref("program:A", "call", "program", "MQPUT", _ev(4), attrs={"system": True}),
                Ref("program:A", "copy", "copybook", "MYCOPY", _ev(5), attrs={"system": True})])
    r = resolve(inv, Config())
    assert r.edges == [] and not [n for n in r.nodes if n.startswith("missing:")]


def test_copybooks():
    assert edge("program:CLMB200", "copy", "copybook:CLMREC").status == "confirmed"
    assert not [e for e in resolved().edges if "DFHAID" in e.dst]
    found = edges("program:CLMO110", "copy", "missing:copybook:ERRMSG")
    assert found and all(e.status == "loose" for e in found)


# CICS ---------------------------------------------------------------------------------------

def test_transactions_and_maps():
    assert edge("program:CLMO100", "return_transid", "transaction:CLMU").status == "confirmed"
    assert edge("program:CLMO130", "start", "missing:transaction:CLMX").status == "loose"
    assert edge("program:CLMO100", "send_map", "map:CLMM01").status == "confirmed"


def test_utilities_created_on_demand():
    e = edge("step:claims-batch/jcl/CLMD100.jcl#STEP010", "runs", "utility:SORT")
    assert e.status == "confirmed"
    assert resolved().nodes["utility:SORT"].kind == "utility"


def test_task8_kinds_not_handled_here():
    from archdiag.resolve.programs import resolve_programs
    inv = resolved().inventory
    nodes, out = dict(inv.nodes), []
    resolve_programs(inv, nodes, out)
    assert not [e for e in out if e.op in ("http", "uses", "transfer", "put", "read", "select")]


def test_config_fixture_loaded():
    assert load_config(ESTATE / "architecture-diagrams").environment_qualifiers == ["PROD", "TEST"]


# synthetic cases ----------------------------------------------------------------------------

def _ev(line, path="x.cbl", repo="r"):
    return Evidence(repo, path, line, "line %d" % line)


def _inv(nodes, refs):
    return Inventory("ws", [], {n.id: n for n in nodes}, refs, "fp", {})


def _prog(name, *lines, repo="r"):
    return Node("program:" + name, "program", name, repo, [_ev(l, name + ".cbl", repo) for l in lines])


def test_reason_caps_at_partial():
    inv = _inv([_prog("A", 1), _prog("B", 1)],
               [Ref("program:A", "call", "program", "B", _ev(5), "guessed from a PROC default")])
    (e,) = resolve(inv, Config()).edges
    assert e.dst == "program:B" and e.status == "partial"
    assert e.reason == "guessed from a PROC default"


def test_unresolved_symbol_name_is_partial_not_loose():
    inv = _inv([], [Ref("step:r/a.jcl#S1", "runs", "program", "&PGM", _ev(3),
                        "symbol &PGM has no value in these repos")])
    r = resolve(inv, Config())
    (e,) = r.edges
    assert e.dst == "missing:program:?r/a.jcl#S1:3" and e.status == "partial"
    assert e.reason == "symbol &PGM has no value in these repos"
    assert r.nodes[e.dst].attrs["written_name"] == "&PGM"


def test_unresolved_symbol_names_do_not_share_a_target():
    why = "symbol &PGM has no value in these repos"
    refs = [Ref("step:r/a.jcl#S1", "runs", "program", "&PGM", _ev(3), why),
            Ref("step:r/b.jcl#S1", "runs", "program", "&PGM", _ev(3), why)]
    r = resolve(_inv([], refs), Config())
    assert len({e.dst for e in r.edges}) == 2
    assert "missing:program:&PGM" not in r.nodes


def test_literal_name_with_reason_matching_nothing_is_loose():
    inv = _inv([], [Ref("step:r/p.proc#S1", "runs", "program", "NOSUCH", _ev(3),
                        "scanned with the PROC defaults", attrs={"proc_default": True})])
    (e,) = resolve(inv, Config()).edges
    assert e.dst == "missing:program:NOSUCH" and e.status == "loose"
    assert e.reason == "scanned with the PROC defaults"


def test_lowercase_target_matches():
    inv = _inv([_prog("A", 1), _prog("B", 1)],
               [Ref("class:r/X", "ctg_call", "program", "b", _ev(5))])
    (e,) = resolve(inv, Config()).edges
    assert e.dst == "program:B" and e.status == "confirmed"


def test_program_and_notanalyzed_same_name_is_ambiguous():
    na = Node("notanalyzed:B", "notanalyzed", "B", "r", [_ev(1, "asm/B.asm")])
    inv = _inv([_prog("A", 1), _prog("B", 1), na],
               [Ref("program:A", "call", "program", "B", _ev(5))])
    (e,) = resolve(inv, Config()).edges
    assert e.status == "partial" and e.reason.startswith("ambiguous: defined in 2 places")


def test_variable_with_several_candidates():
    inv = _inv([_prog("A", 1), _prog("B", 1), _prog("C", 1)],
               [Ref("program:A", "call", "program", None, _ev(7), "CALL through variable WS-X",
                    ["B", "C"])])
    r = resolve(inv, Config())
    (e,) = r.edges
    assert e.dst == "missing:program:?A:7" and e.status == "partial"
    assert r.nodes[e.dst].attrs["candidates"] == ["B", "C"]


def test_variable_with_undefined_single_candidate():
    inv = _inv([_prog("A", 1)],
               [Ref("program:A", "call", "program", None, _ev(7), "CALL through variable WS-X",
                    ["ZZZ"])])
    (e,) = resolve(inv, Config()).edges
    assert e.dst == "missing:program:?A:7" and e.status == "partial"


def test_step_unknown_name_ids_do_not_collide():
    refs = [Ref("step:r/a.jcl#RUN", "runs", "program", None, _ev(2), "PROC P is not in these repos"),
            Ref("step:r/b.jcl#RUN", "runs", "program", None, _ev(2), "PROC P is not in these repos")]
    r = resolve(_inv([], refs), Config())
    assert len({e.dst for e in r.edges}) == 2


def test_duplicate_copybook_is_ambiguous():
    cb = Node("copybook:X", "copybook", "X", "r", [_ev(1, "a/X.cpy"), _ev(1, "b/X.cpy", "s")])
    inv = _inv([_prog("A", 1), cb], [Ref("program:A", "copy", "copybook", "X", _ev(3))])
    (e,) = resolve(inv, Config()).edges
    assert e.status == "partial" and e.reason == "ambiguous: defined in 2 places: r/a/X.cpy, s/b/X.cpy"


def test_ibm_copybook_without_system_flag_gives_no_edge():
    inv = _inv([_prog("A", 1)], [Ref("program:A", "copy", "copybook", "dfheiblk", _ev(3))])
    assert resolve(inv, Config()).edges == []
