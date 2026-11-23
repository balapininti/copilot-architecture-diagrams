"""A config project (another repo holding services' settings) and service names: a REST
call is tied to the repo that serves it."""
from __future__ import annotations

from archdiag.config import Config
from archdiag.resolve import resolve
from archdiag.scan import scan_workspace

CLIENT = ("package x;\n"
          "import org.springframework.beans.factory.annotation.Value;\n"
          "import org.springframework.web.client.RestTemplate;\n"
          "public class BillingClient {\n"
          "  private RestTemplate rest;\n"
          "  @Value(\"${billing.url}\")\n"
          "  private String billingUrl;\n"
          "  public String invoice(String id) {\n"
          "    return rest.getForObject(billingUrl + \"/api/invoices/{id}\", String.class, id);\n"
          "  }\n"
          "}\n")
SERVER = ("package y;\n"
          "import org.springframework.web.bind.annotation.*;\n"
          "@RestController\n"
          "public class InvoiceController {\n"
          "  @GetMapping(\"/api/invoices/{id}\")\n"
          "  public String get(@PathVariable String id) { return id; }\n"
          "}\n")
ORDERS = ("orders-api", "src/main/java/x/BillingClient.java", CLIENT)
BILLING = ("billing-service", "src/main/java/y/InvoiceController.java", SERVER)


def _estate(root, files):
    for repo, rel, text in files:
        r = root / repo
        r.mkdir(exist_ok=True)
        (r / ".archdiag-repo").write_text("")
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def _http(root, files, config=None):
    _estate(root, files)
    cfg = config or Config()
    inv = scan_workspace(root, cfg)
    r = resolve(inv, cfg)
    found = [e for e in r.edges if e.src == "class:orders-api/BillingClient" and e.op == "http"]
    assert len(found) == 1, [(e.src, e.op, e.dst) for e in r.edges]
    return found[0], inv


def test_without_the_config_project_the_url_is_not_worked_out(tmp_path):
    e, inv = _http(tmp_path, [ORDERS, BILLING])
    assert e.dst != "endpoint:GET /api/invoices/{}"
    assert inv.config_projects == {}


def test_config_project_file_named_after_the_app_supplies_the_url(tmp_path):
    e, inv = _http(tmp_path, [ORDERS, BILLING, ("config-repo", "orders-api.yml",
                                               "billing:\n  url: http://billing-service:8080\n")])
    assert e.dst == "endpoint:GET /api/invoices/{}"
    # the host's first label is the repo that serves it: confirmed, not "matched on path only"
    assert e.status == "confirmed" and e.reason is None
    assert inv.config_projects == {"config-repo": ["orders-api"]}


def test_config_project_folder_named_after_the_app(tmp_path):
    e, _ = _http(tmp_path, [ORDERS, BILLING,
                            ("config-repo", "orders-api/application.properties",
                             "billing.url=http://billing-service.prod.svc.cluster.local\n")])
    assert e.dst == "endpoint:GET /api/invoices/{}" and e.status == "confirmed"


def test_config_project_matches_spring_application_name(tmp_path):
    e, inv = _http(tmp_path, [ORDERS, BILLING,
                              ("orders-api", "src/main/resources/bootstrap.yml",
                               "spring:\n  application:\n    name: order-svc\n"),
                              ("config-repo", "order-svc-prod.yml",
                               "billing:\n  url: https://billing.acme.example\n")])
    assert e.dst == "endpoint:GET /api/invoices/{}"
    assert e.status == "partial" and "billing.acme.example" in e.reason
    assert "order-svc" in inv.service_names["orders-api"]


def test_environment_profiles_with_different_hosts_still_link(tmp_path):
    files = [ORDERS, BILLING]
    for env in ("dev", "qa", "uat"):
        files.append(("config-repo", "orders-api-%s.yml" % env,
                      "billing:\n  url: https://billing.%s.acme.example/\n" % env))
    e, _ = _http(tmp_path, files)
    assert e.dst == "endpoint:GET /api/invoices/{}"


def test_profiles_that_differ_in_more_than_the_host_are_a_conflict(tmp_path):
    e, _ = _http(tmp_path, [ORDERS, BILLING,
                            ("config-repo", "orders-api-dev.yml", "billing:\n  url: http://a/v1\n"),
                            ("config-repo", "orders-api-qa.yml", "billing:\n  url: http://a/v2\n")])
    assert e.dst != "endpoint:GET /api/invoices/{}"
    assert "different values" in (e.reason or "")


def test_default_file_beats_profiles_and_prod_beats_other_profiles(tmp_path):
    e, _ = _http(tmp_path, [ORDERS, BILLING,
                            ("config-repo", "orders-api-dev.yml", "billing:\n  url: http://x/old\n"),
                            ("config-repo", "orders-api-prod.yml",
                             "billing:\n  url: http://billing-service\n")])
    assert e.dst == "endpoint:GET /api/invoices/{}" and e.status == "confirmed"


def test_the_services_own_file_wins_over_the_config_project(tmp_path):
    e, _ = _http(tmp_path, [ORDERS, BILLING,
                            ("orders-api", "src/main/resources/application.yml",
                             "billing:\n  url: http://billing-service\n"),
                            ("config-repo", "orders-api.yml", "billing:\n  url: http://x/other\n")])
    assert e.dst == "endpoint:GET /api/invoices/{}"


def test_user_confirmed_service_host_ties_the_host(tmp_path):
    files = [ORDERS, BILLING, ("config-repo", "orders-api.yml",
                               "billing:\n  url: https://billing.acme.example\n")]
    e, _ = _http(tmp_path, files)
    assert e.status == "partial"
    e, _ = _http(tmp_path, files, Config(service_hosts={"billing.acme.example": "billing-service"}))
    assert e.status == "confirmed" and e.reason is None


def test_service_host_naming_an_unknown_repo_is_ignored(tmp_path):
    e, _ = _http(tmp_path, [ORDERS, BILLING, ("config-repo", "orders-api.yml",
                                             "billing:\n  url: https://billing.acme.example\n")],
                 Config(service_hosts={"billing.acme.example": "nope"}))
    assert e.status == "partial"


def test_host_picks_between_two_repos_serving_the_same_path(tmp_path):
    e, _ = _http(tmp_path, [ORDERS, BILLING,
                            ("billing-legacy", "src/main/java/y/InvoiceController.java", SERVER),
                            ("config-repo", "orders-api.yml",
                             "billing:\n  url: http://billing-service\n")])
    assert e.dst == "endpoint:GET /api/invoices/{}" and e.status == "confirmed"


def test_known_service_without_that_endpoint_is_a_loose_end_naming_the_repo(tmp_path):
    e, _ = _http(tmp_path, [ORDERS, ("billing-service", "src/main/java/y/Other.java",
                                     SERVER.replace("/api/invoices", "/api/other")),
                            ("config-repo", "orders-api.yml",
                             "billing:\n  url: http://billing-service\n")])
    assert e.status == "loose" and e.dst == "missing:endpoint:GET /api/invoices/{}"
    assert "host billing-service is billing-service, which has no endpoint" in e.reason


def test_a_name_two_repos_claim_names_neither(tmp_path):
    _estate(tmp_path, [ORDERS, BILLING,
                       ("other", "src/main/resources/application.yml",
                        "spring:\n  application:\n    name: billing-service\n")])
    inv = scan_workspace(tmp_path, Config())
    assert "billing-service" not in inv.service_names.get("billing-service", [])
    assert "billing-service" not in inv.service_names.get("other", [])


def test_inventory_round_trips_the_new_fields(tmp_path):
    from archdiag.store import load_inventory, save_json
    _estate(tmp_path, [ORDERS, BILLING, ("config-repo", "orders-api.yml",
                                         "billing:\n  url: http://billing-service\n")])
    inv = scan_workspace(tmp_path, Config())
    save_json(tmp_path / "inv.json", inv)
    back = load_inventory(tmp_path / "inv.json")
    assert back.service_names == inv.service_names
    assert back.config_projects == inv.config_projects
