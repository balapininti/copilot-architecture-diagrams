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
           'class L { JmsTemplate jmsTemplate; void m(String id) { String s = "A"; if (id == null) s = "B";\n'
           ' jmsTemplate.send(s, null); } }')
    inv = java_inv(tmp_path, src, name="A")
    (tmp_path / "r" / "application.properties").write_text("zos.url=http://zos:9080\n")
    inv = scan_workspace(tmp_path, Config())
    assert ("http", "endpoint", "GET http://zos:9080/v2/a/{id}") in triples(inv, "class:r/Z")
    (q,) = [r for r in inv.refs if r.op == "put"]
    assert q.target_name is None and "more than once" in q.reason


# ---------------------------------------------------------------- fix round 1


def ws(tmp_path, files, repo="r"):
    root = mark(tmp_path, repo)
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return scan_workspace(tmp_path, Config())


def refs_of(inv, src, op=None):
    return [r for r in inv.refs if r.src == src and (op is None or r.op == op)]


def test_unresolved_controller_path_is_not_a_wrong_endpoint(tmp_path):
    inv = ws(tmp_path, {"C.java": (
        '@RestController @RequestMapping("/api")\nclass C {\n'
        '  @GetMapping(Paths.CLAIMS) String get() { return ""; }\n'
        '  @PostMapping("/ok") void ok() {}\n}\n'
        '@RestController @RequestMapping(Other.BASE)\nclass D {\n'
        '  @GetMapping("/x") String x() { return ""; }\n}\n')})
    ids = set(inv.nodes)
    assert "endpoint:GET /api" not in ids and "endpoint:GET /x" not in ids
    assert "endpoint:POST /api/ok" in ids
    n = inv.nodes["endpoint:?r/C#get"]
    assert n.kind == "endpoint" and "unresolved" in n.attrs
    assert "prefix" in inv.nodes["endpoint:?r/D#x"].attrs["unresolved"]


def test_feign_unresolved_path_gives_loose_ref(tmp_path):
    inv = ws(tmp_path, {"F.java": (
        '@FeignClient(name="z", path=Cfg.PATH)\ninterface F {\n'
        '  @GetMapping("/a") String a();\n}\n')})
    (r,) = refs_of(inv, "class:r/F", "http")
    assert r.target_name is None and r.reason


def test_angular_reassigned_variable_is_unresolved(tmp_path):
    inv = ws(tmp_path, {"s.service.ts": (
        "@Injectable()\nexport class S {\n  private base = '/a';\n"
        "  constructor(private http: HttpClient) { this.base = '/b'; }\n"
        "  get() { return this.http.get(this.base + '/x'); }\n}\n")})
    (r,) = refs_of(inv, "component:r/S", "http")
    assert r.target_name is None and "assigned more than once" in r.reason
    assert r.candidates == ["/a", "/b"]


def test_config_in_test_dirs_ignored_and_conflicts_dropped(tmp_path):
    inv = ws(tmp_path, {
        "a/application.yml": "mq:\n  q: A.Q\n  ok: SAME\n",
        "b/application.yml": "mq:\n  q: B.Q\n  ok: SAME\n",
        "src/test/resources/application.yml": "mq:\n  t: T.Q\n",
        "T.java": 'class T { JmsTemplate j; @Value("${mq.q}") String q; @Value("${mq.t}") String t;\n'
                  ' @Value("${mq.ok}") String ok;\n'
                  ' void f() { j.convertAndSend(q, 1);\n j.convertAndSend(t, 1);\n j.convertAndSend(ok, 1);} }'})
    by = sorted(refs_of(inv, "class:r/T", "put"), key=lambda r: r.evidence.line)
    reasons = [r.reason for r in by]
    assert any(x and "different values in a/application.yml, b/application.yml" in x
               for x in reasons)
    assert any(x == "property mq.t not found" for x in reasons)
    assert "SAME" in [r.target_name for r in by]


def test_only_application_properties_are_config(tmp_path):
    inv = ws(tmp_path, {
        "other.properties": "mq.x=NOPE\n",
        "T.java": 'class T { JmsTemplate j; @Value("${mq.x}") String q;\n'
                  ' void f() { j.convertAndSend(q, 1); } }'})
    (r,) = refs_of(inv, "class:r/T", "put")
    assert r.reason == "property mq.x not found"


def test_access_queue_open_mode(tmp_path):
    inv = ws(tmp_path, {"T.java": (
        'class T { void f(MQQueueManager qm) {\n qm.accessQueue("A.Q", 1);\n'
        ' qm.accessQueue("B.Q", MQC.MQOO_OUTPUT); } }')})
    a, b = sorted(refs_of(inv, "class:r/T"), key=lambda r: r.evidence.line)
    assert (a.op, a.target_name, a.reason) == ("open", "A.Q", "queue open mode not worked out")
    assert (b.op, b.target_name, b.reason) == ("put", "B.Q", None)
    assert not any(r.attrs for r in inv.refs)


def test_parameter_shadows_field_and_constants_are_qualified(tmp_path):
    inv = ws(tmp_path, {
        "A.java": 'class A { static final String Q = "A.Q"; }',
        "B.java": 'class B { static final String Q = "B.Q"; }',
        "T.java": ('class T { JmsTemplate j; String name = "FIELD.Q";\n'
                   ' void f(String name) { j.convertAndSend(name, 1); }\n'
                   ' void g() { j.convertAndSend(A.Q, 1); j.convertAndSend(B.Q, 1);\n'
                   ' j.convertAndSend(Q, 1); } }')})
    rs = sorted(refs_of(inv, "class:r/T", "put"), key=lambda r: r.evidence.line)
    assert rs[0].target_name is None and rs[0].reason == "value passed in as parameter name"
    assert [r.target_name for r in rs[1:3]] == ["A.Q", "B.Q"]
    assert rs[3].target_name is None  # bare Q is ambiguous in the repo


def test_angular_http_client_any_name(tmp_path):
    inv = ws(tmp_path, {"s.ts": (
        "@Injectable()\nexport class S {\n  constructor(private api: HttpClient) {}\n"
        "  a() { return this.api.get('/x'); }\n  b() { this.cache.get('/y'); }\n}\n")})
    assert triples(inv, "component:r/S") == {("http", "endpoint", "GET /x")}


def test_same_named_classes_get_qualified_ids(tmp_path):
    inv = ws(tmp_path, {
        "a/Dup.java": "package com.a;\nclass Dup {}\n",
        "b/Dup.java": "package com.b;\nclass Dup {}\n",
        "U.java": "package com.b;\nclass U { U(Dup d) {} }\n",
        "V.java": "package com.v;\nimport com.a.Dup;\nclass V { V(Dup d) {} }\n",
        "W.java": "package com.w;\nclass W { W(Dup d) {} }\n",
        "X.java": "class X { X(U u) {} }\n"})
    assert "class:r/com.a.Dup" in inv.nodes and "class:r/com.b.Dup" in inv.nodes
    assert "class:r/Dup" not in inv.nodes
    assert ("uses", "class", "r/com.b.Dup") in triples(inv, "class:r/U")
    assert ("uses", "class", "r/com.a.Dup") in triples(inv, "class:r/V")
    (w,) = refs_of(inv, "class:r/W")
    assert w.target_name is None and len(w.candidates) == 2
    assert ("uses", "class", "r/U") in triples(inv, "class:r/X")


def test_nested_class_members_belong_to_nested_class(tmp_path):
    inv = ws(tmp_path, {"O.java": (
        "class Helper {}\nclass O {\n  static class In {\n    @Autowired Helper h;\n"
        '    void f() { jdbcTemplate.update("DELETE FROM A.B"); }\n  }\n}\n')})
    assert ("uses", "class", "r/Helper") in triples(inv, "class:r/In")
    assert ("delete", "table", "A.B") in triples(inv, "class:r/In")
    assert not triples(inv, "class:r/O")


def test_same_named_angular_components(tmp_path):
    inv = ws(tmp_path, {
        "a/x.component.ts": "@Component({})\nexport class X {}\n",
        "b/x.component.ts": "@Component({})\nexport class X {}\n",
        "b/y.component.ts": ("import { X } from './x.component';\n"
                             "@Component({})\nexport class Y { constructor(private x: X) {} }\n")})
    assert "component:r/a/x.component/X" in inv.nodes and "component:r/b/x.component/X" in inv.nodes
    assert ("uses", "component", "r/b/x.component/X") in triples(inv, "component:r/Y")


def test_ts_env_reader(tmp_path):
    inv = ws(tmp_path, {
        "src/environments/environment.ts": (
            "export const environment = { apiBase: '/dev', onlyBase: '/ob', "
            "...extra, calc: base + '/x', tpl: `${a}/b`, ok: '/ok' };\n"),
        "src/environments/environment.prod.ts": (
            "export const environment = { apiBase: '/prod' };\n"),
        "s.ts": ("@Injectable()\nexport class S {\n  constructor(private http: HttpClient) {}\n"
                 "  a() { this.http.get(environment.apiBase + '/a'); }\n"
                 "  b() { this.http.get(environment.onlyBase + '/b'); }\n"
                 "  c() { this.http.get(environment.calc + '/c'); }\n"
                 "  d() { this.http.get(environment.ok + '/d'); }\n}\n")})
    rs = sorted(refs_of(inv, "component:r/S", "http"), key=lambda r: r.evidence.line)
    assert rs[0].target_name == "GET /prod/a" and rs[1].target_name == "GET /ob/b"
    assert rs[2].target_name is None and rs[2].reason.endswith("environment.calc is not a literal")
    assert rs[3].target_name == "GET /ok/d"  # keys after a spread / expression still read


def test_nested_placeholder_and_defaults(tmp_path):
    inv = ws(tmp_path, {
        "application.yml": "b: BQ\n",
        "T.java": ('class T { JmsTemplate j; void f() {\n'
                   ' j.convertAndSend("${a:${b}}", 1);\n'
                   ' j.convertAndSend("${a:DEF.Q}", 1);\n'
                   ' j.convertAndSend("${a:${zz}}", 1); } }')})
    rs = sorted(refs_of(inv, "class:r/T", "put"), key=lambda r: r.evidence.line)
    assert [r.target_name for r in rs] == ["BQ", "DEF.Q", None]
    assert rs[2].reason == "property zz not found"


def test_default_destination_and_untyped_receiver(tmp_path):
    inv = ws(tmp_path, {"T.java": (
        "import org.springframework.jms.core.JmsTemplate;\n"
        "class T { JmsTemplate j; Other other; void f() {\n"
        " j.convertAndSend(payload);\n other.convertAndSend(\"X.Q\", 1); } }")})
    (r,) = refs_of(inv, "class:r/T")
    assert r.target_name is None and "default destination" in r.reason


def test_sql_table_not_a_plain_name(tmp_path):
    inv = ws(tmp_path, {"T.java": (
        'class T { void f() { jdbcTemplate.update("DELETE FROM {schema}.T WHERE A=1"); } }')})
    (r,) = refs_of(inv, "class:r/T")
    assert (r.op, r.target_name) == ("delete", None) and "{schema}.T" in r.reason


def test_yaml_reader():
    from archdiag.scan.lexutil import parse_yaml_docs
    docs = parse_yaml_docs(
        "# top\nmq:\n  request: CLM.REQ  # note\n  reply: \"CLM.RSP\"\n"
        "  flow: {a: 1, b: 'x y'}\nlist:\n  - one\n  - two: 2\nafter: ok\n"
        "block: |\n  text: hidden\nurl: https://h:9443/p\n---\nsecond: 1\n")
    assert docs[0] == {"mq.request": "CLM.REQ", "mq.reply": "CLM.RSP", "mq.flow.a": "1",
                       "mq.flow.b": "x y", "after": "ok", "url": "https://h:9443/p"}
    assert docs[1] == {"second": "1"}


def test_placeholder_defaults():
    from archdiag.scan.lexutil import expand_placeholders
    assert expand_placeholders("${a:dflt}/x", {}) == ("dflt/x", None)
    assert expand_placeholders("${a}", {"a": "${b}", "b": "B"}) == ("B", None)
    assert expand_placeholders("${a}", {}) == (None, "property a not found")


# ---------------------------------------------------------------- fix round 2


def test_this_other_object_field_is_not_resolved(tmp_path):
    inv = ws(tmp_path, {"T.java": (
        'class T { JmsTemplate j; Cfg cfg; String url = "FIELD.Q";\n'
        ' void f() { j.convertAndSend(this.cfg.url, 1);\n j.convertAndSend(cfg.url, 1);\n'
        ' j.convertAndSend(this.url, 1); } }')})
    rs = sorted(refs_of(inv, "class:r/T", "put"), key=lambda r: r.evidence.line)
    assert rs[0].target_name is None and "another object" in rs[0].reason
    assert rs[1].target_name is None and "another object" in rs[1].reason
    assert rs[2].target_name == "FIELD.Q"


def test_same_rank_profile_and_env_disagreement_dropped(tmp_path):
    inv = ws(tmp_path, {
        "application-dev.yml": "q: DEV.Q\nsame: S\nonly: O\n",
        "application-prod.yml": "q: PROD.Q\nsame: S\n",
        "T.java": ('class T { JmsTemplate j; @Value("${q}") String q; @Value("${same}") String s;\n'
                   '@Value("${only}") String o;\n'
                   ' void f() { j.convertAndSend(q, 1);\n j.convertAndSend(s, 1);\n'
                   ' j.convertAndSend(o, 1); } }'),
        "src/environments/environment.dev.ts": "export const environment = { a: '/d', b: '/b' };",
        "src/environments/environment.staging.ts": "export const environment = { a: '/s', b: '/b' };",
        "s.ts": ("@Injectable()\nexport class S {\n  constructor(private http: HttpClient) {}\n"
                 "  x() { this.http.get(environment.a + '/x');\n this.http.get(environment.b + '/y'); }\n}\n")})
    rs = sorted(refs_of(inv, "class:r/T", "put"), key=lambda r: r.evidence.line)
    assert rs[0].target_name is None and "different values in" in rs[0].reason
    assert [r.target_name for r in rs[1:]] == ["S", "O"]
    hs = sorted(refs_of(inv, "component:r/S", "http"), key=lambda r: r.evidence.line)
    assert hs[0].target_name is None and "different values in" in hs[0].reason
    assert hs[1].target_name == "GET /b/y"


def test_jms_types_and_inherited_template(tmp_path):
    inv = ws(tmp_path, {
        "Base.java": "class Base { protected JmsOperations ops; }",
        "Kid.java": 'class Kid extends Base { void f() { ops.convertAndSend("K.Q", 1); } }',
        "C.java": 'class C { MessageConsumer mc; QueueSender qs; Stranger s;\n'
                  ' void f() { mc.receive("C.IN"); qs.send("C.OUT", 1); s.send("NO.Q", 1); } }'})
    assert ("put", "queue", "K.Q") in triples(inv, "class:r/Kid")
    t = triples(inv, "class:r/C")
    assert ("get", "queue", "C.IN") in t and ("put", "queue", "C.OUT") in t
    assert not any(n == "NO.Q" for _, _, n in t)
