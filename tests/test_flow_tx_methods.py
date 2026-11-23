"""The online flow follows what a handler method really calls, numbers its steps in source
order and never numbers a loose end (scanner method tables + views/flow_tx.py)."""
from __future__ import annotations

import shutil

import pytest

from conftest import ESTATE
from archdiag.config import Config, load_config
from archdiag.groups import default_groups
from archdiag.render.report import links_report
from archdiag.resolve import resolve
from archdiag.scan import scan_workspace
from archdiag.views import build_view

_C = {}
CTRL = "class:claims-api/ClaimController"
GW = "class:claims-api/MqClaimGateway"
STATUS = "class:claims-api/ClaimStatusClient"
GET, POST = "endpoint:GET /api/claims/{}", "endpoint:POST /api/claims"


def fixture():
    if "r" not in _C:
        cfg = load_config(ESTATE / "architecture-diagrams")
        _C["r"] = resolve(scan_workspace(ESTATE, cfg), cfg)
        _C["g"] = default_groups(_C["r"])
    return _C["r"], _C["g"]


def flow(scope):
    r, g = fixture()
    return build_view(r, g, "flow_tx", scope)


def steps(v):
    """(number, src, dst, label) of the numbered lines, in number order."""
    return sorted((e.number, e.src, e.dst, e.label) for e in v.edges if e.number is not None)


def workspace(tmp_path, files, repo="r"):
    root = tmp_path / repo
    root.mkdir(parents=True)
    (root / ".archdiag-repo").write_text("")
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    r = resolve(scan_workspace(tmp_path, Config()), Config())
    return r, default_groups(r)


# ------------------------------------------------------------------ A: the scanner

def test_scan_records_what_each_method_calls():
    r, _ = fixture()
    table = r.nodes[CTRL].attrs["methods"]
    assert set(table) == {"get", "create"}  # the constructor is not a method of a request
    (call,) = table["get"]["calls"]
    assert (call["class"], call["method"], call["line"]) == (STATUS, "status", 18)
    assert call["text"] == "return statusClient.status(id);"
    (call,) = table["create"]["calls"]
    assert (call["class"], call["method"], call["line"]) == (GW, "submit", 23)
    assert r.nodes[GET].attrs["handler_methods"] == {CTRL: "get"}
    assert r.nodes[POST].attrs["handler_methods"] == {CTRL: "create"}
    by = {(x.src, x.op, x.target_name): x.attrs.get("method") for x in r.inventory.refs}
    assert by[(GW, "put", "CLM.REQ")] == "submit" and by[(GW, "get", "CLM.RSP")] == "reply"
    assert by[(STATUS, "http", "GET https://zcee.internal:9443/zos/claims/{id}/status")] == "status"
    # the class-level links other views draw are unchanged
    assert {(e.op, e.dst) for e in r.edges if e.src == CTRL} == {("uses", GW), ("uses", STATUS)}


def test_scan_angular_service_methods():
    r, _ = fixture()
    svc = "component:claims-portal/ClaimService"
    assert set(r.nodes[svc].attrs["methods"]) == {"get", "create", "remove"}
    by = {x.target_name: x.attrs.get("method") for x in r.inventory.refs if x.src == svc}
    assert by == {"GET /api/claims/${id}": "get", "POST /api/claims": "create",
                  "DELETE /api/claims/${id}": "remove"}
    # the component is handed the service and calls nothing on it
    assert "methods" not in r.nodes["component:claims-portal/ClaimDetailsComponent"].attrs


JAVA = {
    "C.java": '''
@RestController
public class C {
    private final S s;
    private final T t;
    private final U u;
    private final V v;
    public C(S s, T t, U u, V v) { this.s = s; this.t = t; this.u = u; this.v = v; }

    @GetMapping("/a")
    public String a() {
        helper();
        return s.one();
    }

    @GetMapping("/b")
    public String b() {
        register(u);
        return s.two();
    }

    private void helper() { t.go(); }
}
''',
    "S.java": '''
public class S {
    private JmsTemplate jms;
    public String one() { jms.convertAndSend("Q.ONE", "x"); return ""; }
    public String two() { jms.convertAndSend("Q.TWO", "x"); return ""; }
}
''',
    "T.java": 'public class T { private JmsTemplate jms;\n'
              ' public void go() { jms.convertAndSend("Q.T", "x"); } }\n',
    "U.java": 'public class U { private JmsTemplate jms;\n'
              ' public void x() { jms.convertAndSend("Q.U1", "x"); }\n'
              ' public void y() { jms.convertAndSend("Q.U2", "x"); } }\n',
    "V.java": 'public class V { private JmsTemplate jms;\n'
              ' public void z() { jms.convertAndSend("Q.V", "x"); } }\n',
}


def test_scan_own_method_calls_and_uses_that_are_not_calls(tmp_path):
    r, _ = workspace(tmp_path, JAVA)
    table = r.nodes["class:r/C"].attrs["methods"]
    assert [(s["method"], s["line"]) for s in table["a"]["self"]] == [("helper", 12)]
    assert [(c["class"], c["method"]) for c in table["b"]["calls"]] == \
        [("class:r/U", None), ("class:r/S", "two")]  # u is passed on: which method is not known
    assert [(c["class"], c["method"]) for c in table["helper"]["calls"]] == [("class:r/T", "go")]


# ------------------------------------------------------------------ B: what is followed

def test_get_flow_has_no_mq_steps():
    v = flow("GET /api/claims/{}")
    ids = {n.id for n in v.nodes}
    assert not [i for i in ids if i.startswith(("queue:", "transaction:"))] and GW not in ids
    assert [s[1:] for s in steps(v)] == [
        (GET, STATUS, "calls status()"),
        (STATUS, "zosapi:GET /zos/claims/{}/status", "REST GET"),
        ("zosapi:GET /zos/claims/{}/status", "program:CLMO130", "runs CLMO130")]
    assert not v.notes


def test_post_flow_has_the_mq_steps_and_not_the_status_call():
    v = flow("POST /api/claims")
    ids = {n.id for n in v.nodes}
    assert {GW, "queue:CLM.REQ.LQ", "transaction:CLMI", "program:CLMO100", "queue:CLM.RSP"} <= ids
    assert STATUS not in ids and "program:CLMO130" not in ids
    assert [s[1:] for s in steps(v)][:4] == [
        (POST, GW, "calls submit()"),
        (GW, "queue:CLM.REQ.LQ", "MQ PUT CLM.REQ.LQ"),
        ("queue:CLM.REQ.LQ", "transaction:CLMI", "triggers CLMI"),
        ("transaction:CLMI", "program:CLMO100", "runs CLMO100")]


def test_reply_reader_is_met_only_after_the_program_puts_the_reply():
    """MqClaimGateway.reply() is called by nobody: its MQ GET is on the picture as the
    reader of what CLMO100 puts on CLM.RSP, never as a step of the gateway's submit()."""
    num = {(s[1], s[2], s[3]): s[0] for s in steps(flow("POST /api/claims"))}
    assert num[(GW, "queue:CLM.RSP", "MQ GET CLM.RSP")] == \
        num[("program:CLMO100", "queue:CLM.RSP", "MQ PUT CLM.RSP")] + 1


def test_endpoint_follows_only_its_handler_method(tmp_path):
    r, g = workspace(tmp_path, JAVA)
    v = build_view(r, g, "flow_tx", "GET /a")
    assert [s[1:] for s in steps(v)] == [  # helper() is followed where a() calls it
        ("endpoint:GET /a", "class:r/T", "calls go()"),
        ("class:r/T", "queue:Q.T", "MQ PUT Q.T"),
        ("endpoint:GET /a", "class:r/S", "calls one()"),
        ("class:r/S", "queue:Q.ONE", "MQ PUT Q.ONE")]
    ids = {n.id for n in v.nodes}
    assert not ids & {"queue:Q.TWO", "class:r/U", "queue:Q.U1"}
    # V is handed to C and no call to it was found: the class-level link stays, unnumbered
    (e,) = [e for e in v.edges if e.dst == "class:r/V"]
    assert e.label == "uses V" and e.number is None
    assert any(n.startswith("No call from C to V was found") for n in v.notes)


def test_collaborator_used_without_a_plain_call_is_followed_whole(tmp_path):
    r, g = workspace(tmp_path, JAVA)
    v = build_view(r, g, "flow_tx", "GET /b")
    labels = {(e.src, e.dst): (e.label, e.number) for e in v.edges}
    assert labels[("endpoint:GET /b", "class:r/U")] == ("uses U", 1)
    # both of U's methods are drawn: not numbered, the scan cannot tell which one runs
    assert labels[("class:r/U", "queue:Q.U1")] == ("MQ PUT Q.U1", None)
    assert labels[("class:r/U", "queue:Q.U2")] == ("MQ PUT Q.U2", None)
    assert labels[("endpoint:GET /b", "class:r/S")][0] == "calls two()"
    assert ("class:r/S", "queue:Q.ONE") not in labels
    assert any(n.startswith("U makes 2 different calls") for n in v.notes)


def test_page_keeps_every_call_and_says_so():
    v = flow("claims/:id")
    ids = {n.id for n in v.nodes}
    assert {GET, POST, "missing:endpoint:DELETE /api/claims/{}"} <= ids
    assert all(e.number is None for e in v.edges)
    assert ('ClaimService makes 3 different calls and the scan cannot tell which of them this '
            'page makes: all are drawn, and nothing from ClaimService on is numbered. Each '
            'endpoint can be drawn as its own flow, for example --scope "GET /api/claims/{}"') \
        in v.notes


def test_page_shows_only_the_calls_its_component_makes(tmp_path):
    ws = tmp_path / "estate"
    shutil.copytree(str(ESTATE), str(ws))
    p = ws / "claims-portal/src/app/claims/claim-details.component.ts"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "constructor(private claims: ClaimService) {}",
        "constructor(private claims: ClaimService) {}\n"
        "  ngOnInit() {\n    this.claims.get('1').subscribe();\n  }"), encoding="utf-8")
    cfg = load_config(ws / "architecture-diagrams")
    r = resolve(scan_workspace(ws, cfg), cfg)
    v = build_view(r, default_groups(r), "flow_tx", "claims/:id")
    ids = {n.id for n in v.nodes}
    assert GET in ids and POST not in ids and "missing:endpoint:DELETE /api/claims/{}" not in ids
    assert not [i for i in ids if i.startswith("queue:")]
    assert [s[3] for s in steps(v)] == ["calls get()", "REST GET", "calls status()", "REST GET",
                                        "runs CLMO130"]
    assert not v.notes


# ------------------------------------------------------------------ C: order and numbers

def test_clmo100_steps_are_numbered_in_source_line_order():
    v = flow("CLMI")
    mine = [e for e in v.edges if e.src == "program:CLMO100"]
    line = {id(e): min(ev.line for ev in e.evidence if ev.path.endswith("CLMO100.cbl"))
            for e in mine}
    numbered = sorted((e for e in mine if e.number is not None), key=lambda e: e.number)
    assert [e.label for e in numbered] == [
        "SELECT CLMS.CLAIM", "LINK CLMO110", "read", "SEND MAP CLMM01", "MQ GET CLM.REQ.LQ",
        "MQ PUT CLM.RSP", "RETURN TRANSID CLMU"]
    assert [line[id(e)] for e in numbered] == sorted(line[id(e)] for e in numbered)
    # the lines are listed in source order too, the unnumbered ones in their place
    assert [line[id(e)] for e in mine] == sorted(line[id(e)] for e in mine)


def test_loose_ends_and_gaps_carry_no_number():
    r, _ = fixture()
    for scope in ("CLMI", "POST /api/claims", "GET /api/claims/{}", "claims/:id"):
        v = flow(scope)
        kinds = {n.id: n.kind for n in v.nodes}
        for e in v.edges:
            if kinds[e.dst] == "missing" or kinds[e.src] == "missing":
                assert e.number is None, (scope, e.label)
        nums = [s[0] for s in steps(v)]
        assert nums == list(range(1, len(nums) + 1)), scope
    v = flow("CLMI")
    unnumbered = {e.label for e in v.edges if e.number is None}
    assert {"no writer found", "runs CLMO120", "XCTL", "SELECT"} <= unnumbered
    # the queue CLMI is triggered from is context here, not a step after the program reads it
    assert "triggers CLMI" in unnumbered


# ------------------------------------------------------------------ D: labels and folding

def test_endpoint_box_carries_its_handler_and_the_hop_is_not_a_step():
    r, _ = fixture()
    v = flow("GET /api/claims/{}")
    box = [n for n in v.nodes if n.id == GET][0]
    assert box.sublabel == "ClaimController.get() · claims-api"
    assert CTRL not in {n.id for n in v.nodes}
    assert not [e for e in v.edges if e.label in ("runs", "uses", "REST")]
    # nothing is lost: the report lists the handler link and the call with its own line
    rep = links_report(v, r)
    assert "| endpoint GET /api/claims/{} | runs | class ClaimController | confirmed |" in rep
    row = [ln for ln in rep.splitlines() if "| calls |" in ln][0]
    assert "class ClaimController | calls | class ClaimStatusClient" in row
    assert "ClaimController.java:18 (here)" in row


def test_labels_are_verb_plus_object():
    labels = {e.label for e in flow("POST /api/claims").edges}
    assert {"MQ PUT CLM.REQ.LQ", "SELECT CLMS.CLAIM", "LINK CLMO110", "SEND MAP CLMM01",
            "RETURN TRANSID CLMU", "triggers CLMI", "runs CLMO100", "calls submit()"} <= labels
    assert not labels & {"MQ PUT", "MQ GET", "LINK", "runs", "uses", "triggers"}
    # a name not worked out leaves the verb alone; a long name stays on its box
    assert {"XCTL", "read"} <= labels
    page = {e.label for e in flow("claims/:id").edges}
    assert {"uses ClaimService", "REST GET", "REST POST", "REST DELETE"} <= page
    assert "REST" not in page


@pytest.mark.parametrize("scope", ["CLMI", "POST /api/claims", "GET /api/claims/{}",
                                   "claims/:id"])
def test_every_line_stands_on_scan_evidence(scope):
    v = flow(scope)
    for e in v.edges:
        assert e.underlying and e.evidence, e.label
