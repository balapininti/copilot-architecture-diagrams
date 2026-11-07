from __future__ import annotations

import pytest

from archdiag.config import Config
from archdiag.scan import scan_workspace
from conftest import ESTATE


@pytest.fixture(scope="module")
def inv():
    return scan_workspace(ESTATE, Config())


def triples(inv, src):
    return {(r.op, r.target_kind, r.target_name) for r in inv.refs if r.src == src}


def mark(root, name):
    (root / name).mkdir(parents=True, exist_ok=True)
    (root / name / ".archdiag-repo").write_text("")
    return root / name


def java_inv(tmp_path, src, yml=None, name="Tmp"):
    repo = mark(tmp_path, "r")
    (repo / (name + ".java")).write_text(src, encoding="utf-8")
    if yml is not None:
        (repo / "application.yml").write_text(yml, encoding="utf-8")
    return scan_workspace(tmp_path, Config())


def test_endpoints(inv):
    for nid in ("endpoint:GET /api/claims/{}", "endpoint:POST /api/claims"):
        assert nid in inv.nodes
        assert inv.nodes[nid].attrs["handler"] == "class:claims-api/ClaimController"
        assert inv.nodes[nid].evidence[0].path.endswith("ClaimController.java")
    assert "class:claims-api/ClaimController" in inv.nodes


def test_java_queue_props_resolved(inv):
    t = triples(inv, "class:claims-api/MqClaimGateway")
    assert ("put", "queue", "CLM.REQ") in t and ("get", "queue", "CLM.RSP") in t
    assert ("put", "queue", "CLM.AUDIT") in triples(inv, "class:claims-api/AuditPublisher")


def test_java_http_join(inv):
    t = triples(inv, "class:claims-api/ClaimStatusClient")
    assert ("http", "endpoint", "GET https://zcee.internal:9443/zos/claims/{id}/status") in t
    assert ("http", "endpoint", "GET https://rates.example.com/v1/rates") in \
        triples(inv, "class:claims-api/RatesClient")


def test_java_sql(inv):
    assert ("select", "table", "CLMS.POLICY") in triples(inv, "class:claims-api/ClaimRepository")


def test_java_uses(inv):
    t = triples(inv, "class:claims-api/ClaimController")
    assert ("uses", "class", "claims-api/MqClaimGateway") in t
    assert ("uses", "class", "claims-api/ClaimStatusClient") in t
    assert not any(k == "class" and n and "RestTemplate" in n for _, k, n in t)


def test_angular_http(inv):
    t = triples(inv, "component:claims-portal/ClaimService")
    assert ("http", "endpoint", "GET /api/claims/${id}") in t
    assert ("http", "endpoint", "POST /api/claims") in t
    assert ("http", "endpoint", "DELETE /api/claims/${id}") in t


def test_angular_route_page(inv):
    assert "page:claims-portal/claims/:id" in inv.nodes
    assert ("uses", "component", "claims-portal/ClaimDetailsComponent") in \
        triples(inv, "page:claims-portal/claims/:id")


def test_angular_uses(inv):
    assert ("uses", "component", "claims-portal/ClaimService") in \
        triples(inv, "component:claims-portal/ClaimDetailsComponent")


def test_unresolved_property_reason(tmp_path):
    inv = java_inv(tmp_path, 'class Tmp { JmsTemplate jmsTemplate;\n'
                   ' void f() { jmsTemplate.convertAndSend("${mq.nope}", "x"); } }')
    (r,) = [r for r in inv.refs if r.op == "put"]
    assert r.target_name is None and r.reason == "property mq.nope not found"


def test_unresolvable_url_start_is_not_guessed(tmp_path):
    inv = java_inv(tmp_path, 'class Tmp { RestTemplate restTemplate;\n'
                   ' void f(String base) { restTemplate.getForObject(base + "/x", String.class); } }')
    (r,) = [r for r in inv.refs if r.op == "http"]
    assert r.target_name is None and r.reason


def test_commented_code_ignored_and_ctg(tmp_path):
    src = ('class Tmp {\n // jmsTemplate.convertAndSend("OLD.Q", 1);\n'
           ' /* jdbcTemplate.update("DELETE FROM A.B"); */\n'
           ' void f() { new ECIRequest(1, "S", null, null, "CLMPROG", null, null, 0, 0, 0);\n'
           '  jdbcTemplate.update("INSERT INTO A.T (X) SELECT X FROM B.U"); } }')
    inv = java_inv(tmp_path, src)
    t = triples(inv, "class:r/Tmp")
    assert ("ctg_call", "program", "CLMPROG") in t
    assert ("insert", "table", "A.T") in t and ("select", "table", "B.U") in t
    assert not any(n in ("OLD.Q", "A.B") for _, _, n in t)
    ev = [r for r in inv.refs if r.op == "ctg_call"][0].evidence
    assert ev.line == 4


def test_feign_url_from_property_and_reassigned_variable(tmp_path):
    src = ('@FeignClient(name="x", url="${zos.url}", path="/v2")\n'
           'interface Z { @GetMapping("/a/{id}") String a(); }\n'
           'class L { void m(String id) { String s = "A"; if (id == null) s = "B";\n'
           ' jmsTemplate.send(s, null); } }')
    inv = java_inv(tmp_path, src, name="A")
    (tmp_path / "r" / "application.properties").write_text("zos.url=http://zos:9080\n")
    inv = scan_workspace(tmp_path, Config())
    assert ("http", "endpoint", "GET http://zos:9080/v2/a/{id}") in triples(inv, "class:r/Z")
    (q,) = [r for r in inv.refs if r.op == "put"]
    assert q.target_name is None and "more than once" in q.reason
