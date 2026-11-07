from __future__ import annotations

import json

from conftest import ESTATE
from archdiag.config import Config, load_config
from archdiag.groups import default_groups, load_groups, app_of, suggested_edges
from archdiag.resolve import resolve
from archdiag.scan import scan_workspace
from archdiag.summary import build_summary, list_items

_C = {}


def res(qualifiers=True):
    if qualifiers not in _C:
        cfg = load_config(ESTATE / "architecture-diagrams") if qualifiers else Config()
        _C[qualifiers] = (resolve(scan_workspace(ESTATE, cfg), cfg), cfg)
    return _C[qualifiers]


def write(tmp_path, data):
    p = tmp_path / "groups.json"
    p.write_text(json.dumps(data))
    return p


def test_default_groups_one_per_repo():
    g = default_groups(res()[0])
    assert len(g.apps) == 6
    assert {a.name: a.kind for a in g.apps}["claims-db"] == "datastore"


def test_selector_precedence(tmp_path):
    r = res()[0]
    g = load_groups(write(tmp_path, {"apps": [{"name": "Claims Online",
                     "members": ["program:CLMO1*", "transaction:CLMI"]}]}), r)
    assert app_of(g, r, "program:CLMO100") == "Claims Online"
    assert app_of(g, r, "transaction:CLMI") == "Claims Online"
    assert app_of(g, r, "program:CLMB200") == "claims-batch"
    assert app_of(g, r, "dataset:PROD.CLAIMS.DAILY") is None
    assert not g.problems


def test_unknown_selector_and_link_end_reported(tmp_path):
    r = res()[0]
    g = load_groups(write(tmp_path, {"apps": [{"name": "X", "members": ["program:NOPE*", "bad"]}],
                     "suggested_links": [{"from": "dataset:CLAIMS.EXTRACT", "to": "nowhere", "note": "n"}]}), r)
    assert len(g.problems) == 3 and not g.suggested_links


def test_missing_file_is_default(tmp_path):
    assert len(load_groups(tmp_path / "none.json", res()[0]).apps) == 6


def test_suggested_link_is_partial(tmp_path):
    r = res()[0]
    g = load_groups(write(tmp_path, {"suggested_links": [
        {"from": "dataset:CLAIMS.EXTRACT", "to": "external:NDM:FINANCE", "note": "x"},
        {"from": "claims-batch", "to": "claims-db", "note": "y"}]}), r)
    e = suggested_edges(g, r)
    assert e[0].status == "partial" and e[0].reason == "suggested by Copilot: x" and e[0].op == "suggested"
    assert e[1].src == "app:claims-batch"


def test_summary_env_candidates():
    r, _ = res(False)
    s = build_summary(r, default_groups(r), Config())
    assert "TEST" in s and "PROD" in s
    r2, cfg2 = res(True)
    cand = build_summary(r2, default_groups(r2), cfg2).split("## Links")[0].split("candidates")[1]
    assert "PROD" not in cand and "TEST" not in cand


def test_summary_size():
    r, cfg = res()
    assert len(build_summary(r, default_groups(r), cfg).splitlines()) <= 120


def test_list_jobs():
    r = res()[0]
    jobs = list_items(r, default_groups(r), "jobs")
    assert "CLMD100 (claims-batch/jcl/CLMD100.jcl)" in jobs
    assert "CLMD100 (claims-batch/jcl/test/CLMD100.jcl)" in jobs
    for w in ("transactions", "pages", "endpoints", "applications", "repos", "programs"):
        assert list_items(r, default_groups(r), w)
