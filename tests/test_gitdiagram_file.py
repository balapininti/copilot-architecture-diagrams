from __future__ import annotations

import json

from conftest import fixture_resolved

from archdiag.gitdiagram import (GitDiagram, GitGroup, default_gitdiagram, file_of, gitdiagram_path,
                                 group_of, load_gitdiagram, repo_files)


def _write(tmp_path, data, raw=None):
    p = gitdiagram_path(tmp_path, "claims-batch")
    p.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")
    return p


def test_load_valid_file(tmp_path):
    r = fixture_resolved()
    _write(tmp_path, {
        "repo": "claims-batch", "overview": "Nightly batch.",
        "groups": [{"name": "Pricing", "tech": "COBOL", "files": ["cobol/CLMB200.cbl", "cobol/CLMB210.cbl"],
                    "description": "Prices claims"},
                   {"name": "Jobs", "tech": "JCL", "files": ["jcl/*.jcl", "proc/*.proc"]}],
        "suggested_links": [{"from": "Jobs", "to": "Pricing", "label": "runs", "note": "n"}]})
    gd = load_gitdiagram(tmp_path, r, "claims-batch")
    assert gd.from_file and gd.overview == "Nightly batch." and gd.repo == "claims-batch"
    assert [g.name for g in gd.groups] == ["Pricing", "Jobs"]
    assert gd.groups[0].description == "Prices claims"
    assert gd.suggested_links == [{"from": "Jobs", "to": "Pricing", "label": "runs", "note": "n"}]
    assert group_of(gd, "proc/CLMPRC.proc") == "Jobs"
    assert group_of(gd, "asm/DATEUTIL.asm") is None
    assert gd.problems == [] or all("asm" not in p for p in gd.problems)


def test_utf8_bom_tolerated(tmp_path):
    r = fixture_resolved()
    p = gitdiagram_path(tmp_path, "claims-batch")
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"groups": [{"name": "Café", "files": ["cobol/"]}]},
                                                ensure_ascii=False).encode("utf-8"))
    gd = load_gitdiagram(tmp_path, r, "claims-batch")
    assert gd.from_file and gd.groups[0].name == "Café"


def test_patterns_normalised(tmp_path):
    r = fixture_resolved()
    _write(tmp_path, {"groups": [{"name": "A", "files": ["cobol\\CLMB2*.CBL"]},
                                 {"name": "B", "files": ["./cobol/"]}]})
    gd = load_gitdiagram(tmp_path, r, "claims-batch")
    assert group_of(gd, "cobol/CLMB200.cbl") == "A"
    assert group_of(gd, "cobol/CLMB300.cbl") == "B"
    assert group_of(gd, "COBOL/clmb300.cbl") == "B"
    assert group_of(gd, "cobol.pds/CLMB400") is None  # folder prefix is a whole segment
    assert group_of(gd, "cobol") == "B"


def test_first_group_wins():
    gd = GitDiagram("x", "", [GitGroup("One", files=["cobol/*"]), GitGroup("Two", files=["cobol/CLMB200.cbl"])],
                    [], [], True)
    assert group_of(gd, "cobol/CLMB200.cbl") == "One"


def test_bad_json_and_wrong_types_are_problems_not_errors(tmp_path):
    r = fixture_resolved()
    _write(tmp_path, None, raw="{not json")
    gd = load_gitdiagram(tmp_path, r, "claims-batch")
    assert not gd.from_file and gd.problems and gd.groups
    _write(tmp_path, None, raw="[1]")
    assert load_gitdiagram(tmp_path, r, "claims-batch").problems
    _write(tmp_path, {"overview": 5, "groups": [
        {"name": "Ok", "files": None},
        {"name": 7, "files": ["cobol/"]},
        {"name": "Ok", "files": ["jcl/"]},
        {"name": "Typed", "tech": 3, "files": ["jcl/", 9, "nothing/here.txt"]},
        "junk"],
        "suggested_links": [{"from": "Ok", "to": "Nowhere"}, "x", {"from": "Ok", "to": "Typed"}]})
    gd = load_gitdiagram(tmp_path, r, "claims-batch")
    assert gd.from_file
    assert [g.name for g in gd.groups] == ["Ok", "Typed"]
    assert gd.groups[0].files == []
    text = "\n".join(gd.problems)
    for needle in ("duplicate", "Nowhere", "nothing/here.txt", "overview"):
        assert needle in text
    assert [(l["from"], l["to"]) for l in gd.suggested_links] == [("Ok", "Typed")]
    assert gd.suggested_links[0]["label"] == "" and gd.suggested_links[0]["note"] == ""


def test_missing_file_falls_back_to_folders(tmp_path):
    r = fixture_resolved()
    gd = load_gitdiagram(tmp_path, r, "claims-batch")
    assert not gd.from_file and gd.overview == ""
    assert [g.name for g in gd.groups] == ["asm", "cobol", "cobol.pds", "jcl", "jcl.pds", "proc"]
    assert "Grouped by folder. Ask Copilot to name groups for this repo." in gd.problems
    cob = [g for g in gd.groups if g.name == "cobol"][0]
    assert cob.tech == "cobol"
    for f in repo_files(r, "claims-batch"):
        assert group_of(gd, f["path"]) == f["path"].split("/")[0]


def test_root_files_group_named_after_repo():
    gd = default_gitdiagram(_FakeR([("r", "README.cbl", "cobol"), ("r", "a/x.cbl", "cobol")]), "r")
    assert [g.name for g in gd.groups] == ["r", "a"] or [g.name for g in gd.groups] == ["a", "r"]
    assert group_of(gd, "README.cbl") == "r" and group_of(gd, "a/x.cbl") == "a"


class _Inv:
    def __init__(self, files):
        self.files = [{"repo": a, "path": b, "kind": c} for a, b, c in files]


class _FakeR:
    def __init__(self, files):
        self.inventory = _Inv(files)
        self.nodes = {}


def test_file_of_step_is_job_file():
    r = fixture_resolved()
    step = [n for n in r.nodes.values() if n.kind == "step"][0]
    assert file_of(step, r) == (step.repo, step.evidence[0].path)
    job = r.nodes[step.attrs["job"]]
    assert file_of(step, r) == file_of(job, r) == ("claims-batch", "jcl/CLMD100.jcl")
    prog = [n for n in r.nodes.values() if n.kind == "program" and n.evidence][0]
    assert file_of(prog, r) == (prog.evidence[0].repo, prog.evidence[0].path)


def test_file_of_dataset_is_none():
    r = fixture_resolved()
    for kind in ("dataset", "missing", "external", "utility"):
        ns = [n for n in r.nodes.values() if n.kind == kind]
        assert ns, kind
        assert all(file_of(n, r) is None for n in ns)


def test_deeply_nested_and_huge_files_are_problems(tmp_path):
    r = fixture_resolved()
    _write(tmp_path, None, raw="[" * 200000 + "]" * 200000)
    gd = load_gitdiagram(tmp_path, r, "claims-batch")
    assert gd.file_state == "unusable" and not gd.from_file and gd.problems and gd.groups
    _write(tmp_path, None, raw=" " * (5 * 1024 * 1024 + 1))
    gd = load_gitdiagram(tmp_path, r, "claims-batch")
    assert gd.file_state == "unusable" and "limit" in gd.problems[0]


def test_file_state(tmp_path):
    r = fixture_resolved()
    assert load_gitdiagram(tmp_path, r, "claims-batch").file_state == "missing"
    _write(tmp_path, {"groups": []})
    gd = load_gitdiagram(tmp_path, r, "claims-batch")
    assert gd.file_state == "ok" and gd.from_file


def test_file_of_archive_members():
    from archdiag.model import Evidence, Node
    r = fixture_resolved()
    z = Node("zosapi:x", "zosapi", "X", "claims-online",
             [Evidence("claims-online", "apis/x.aar!/x.json", 1, "t")], {})
    assert file_of(z, r) == ("claims-online", "apis/x.aar")
    both = Node("c:y", "class", "Y", "claims-api",
                [Evidence("claims-api", "lib/a.jar!/Y.class", 1, "t"), Evidence("claims-api", "src/Y.java", 2, "t")], {})
    assert file_of(both, r) == ("claims-api", "src/Y.java")
    assert file_of(Node("c:z", "class", "Z", None, [], {}), r) is None
