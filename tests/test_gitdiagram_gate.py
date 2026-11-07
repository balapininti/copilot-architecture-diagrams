"""Release gate for the gitdiagram view (spec 8): the group arrows drawn for the claims
fixture's hand-written gitdiagram files match a list written by hand from the fixture sources
and the rules (``fixtures/expected_gitdiagram.json``, reasons in
``fixtures/expected_gitdiagram_notes.md``). A missed arrow, an unexpected solid arrow, a wrong
status or a file that quietly disappears fails the gate."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from conftest import ESTATE, fixture_resolved

from archdiag.gitdiagram import load_gitdiagram
from archdiag.groups import default_groups
from archdiag.model import CONFIRMED
from archdiag.views import build_view
from archdiag.views.common import _family, _missing_label, _short

EXPECTED = json.loads((Path(__file__).parent / "fixtures" / "expected_gitdiagram.json")
                      .read_text(encoding="utf-8"))
REPOS = sorted(EXPECTED)
_VIEWS = {}


def view(repo):
    if repo not in _VIEWS:
        r = fixture_resolved()
        gd = load_gitdiagram(ESTATE / "architecture-diagrams", r, repo)
        assert gd.from_file and gd.file_state == "ok", gd.problems
        _VIEWS[repo] = (gd, build_view(r, default_groups(r), "gitdiagram", repo, gitdiagram=gd))
    return _VIEWS[repo]


def family(e):
    """The label's kind of link: before " · " and " via "; a suggested line's whole label."""
    if any(u.op == "suggested" for u in e.underlying):
        return e.label
    return re.split(r" · | via ", e.label, maxsplit=1)[0]


def targets(repo, e):
    """Ids of the things line ``e`` names: the targets of its underlying edges of the line's
    own family (the ``runs`` edge a dataset line also stands on, an entry point's handler
    edge and a temporary dataset's edges are not named). A suggested line names none."""
    if any(u.op == "suggested" for u in e.underlying):
        return set()
    nodes = fixture_resolved().nodes
    return {u.dst for u in e.underlying if _family(u, nodes) == family(e)}


def shown_name(nid):
    n = fixture_resolved().nodes[nid]
    if n.kind == "missing":
        return _missing_label(n)[0] if n.name.startswith("?") else n.name
    return _short(n)


def actual(repo):
    return {(e.src, e.dst, family(e), e.status) for e in view(repo)[1].edges}


def expected(repo):
    return {(x["src"], x["dst"], x["label_family"], x["status"]) for x in EXPECTED[repo]["lines"]}


def _show(rows):
    return "\n".join("  %s -> %s [%s] %s" % t for t in sorted(rows))


def test_expected_list_is_not_empty_and_well_formed():
    for repo in REPOS:
        lines = EXPECTED[repo]["lines"]
        assert lines and EXPECTED[repo]["files"], repo
        ids = [x["id"] for x in lines]
        assert len(ids) == len(set(ids)), repo
        assert len(expected(repo)) == len(lines), "duplicate entries in %s" % repo
        for x in lines:
            assert x["status"] in ("confirmed", "partial", "loose", "structural"), x
        notes = (Path(__file__).parent / "fixtures" / "expected_gitdiagram_notes.md").read_text(
            encoding="utf-8")
        for i in ids:
            assert "| %s |" % i in notes, "no note for %s" % i


@pytest.mark.parametrize("repo", REPOS)
def test_gitdiagram_file_has_no_problems(repo):
    gd, v = view(repo)
    assert gd.problems == []
    assert v.overview == gd.overview and v.overview


@pytest.mark.parametrize("repo", REPOS)
def test_no_missed_group_arrows(repo):
    have = {t[:3] for t in actual(repo)}
    missed = {t for t in expected(repo) if t[:3] not in have}
    assert not missed, "missed:\n%s\ndrawn:\n%s" % (_show(missed), _show(actual(repo)))


@pytest.mark.parametrize("repo", REPOS)
def test_no_unexpected_solid_group_arrows(repo):
    bad = {t for t in actual(repo) if t[3] == CONFIRMED} - expected(repo)
    assert not bad, "unexpected solid:\n%s" % _show(bad)


@pytest.mark.parametrize("repo", REPOS)
def test_no_unexpected_group_arrows(repo):
    bad = actual(repo) - expected(repo)
    assert not bad, "unexpected:\n%s" % _show(bad)


@pytest.mark.parametrize("repo", REPOS)
def test_group_arrow_status_matches(repo):
    keys = {t[:3] for t in expected(repo)}
    got = {t for t in actual(repo) if t[:3] in keys}
    assert got == expected(repo), "expected:\n%s\ndrawn:\n%s" % (_show(expected(repo)), _show(got))


@pytest.mark.parametrize("repo", REPOS)
def test_no_line_drawn_twice(repo):
    seen = [(e.src, e.dst, family(e), e.status) for e in view(repo)[1].edges]
    twice = {t for t in seen if seen.count(t) > 1}
    assert not twice, "drawn twice:\n%s" % _show(twice)


@pytest.mark.parametrize("repo", REPOS)
def test_each_line_names_its_expected_targets(repo):
    """A line names exactly the hand-listed targets, so a view that swaps targets between
    the solid and the dotted line of one pair fails; and its label names only those."""
    edges = view(repo)[1].edges
    for x in EXPECTED[repo]["lines"]:
        key = (x["src"], x["dst"], x["label_family"], x["status"])
        hits = [e for e in edges if (e.src, e.dst, family(e), e.status) == key]
        assert len(hits) == 1, (x["id"], len(hits))
        e = hits[0]
        assert targets(repo, e) == set(x["targets"]), (x["id"], sorted(targets(repo, e)))
        m = re.match(r"[^·]+ · (.*?)( via .*)?$", e.label)
        if m and not x.get("suggested"):
            names = re.sub(r" \+\d+$", "", m.group(1)).split(", ")
            assert set(names) <= {shown_name(t) for t in x["targets"]}, (x["id"], e.label)


@pytest.mark.parametrize("repo", REPOS)
def test_expected_label_text(repo):
    """Entries naming label text (the temporary dataset folded into a job line, Ruling 6)."""
    edges = view(repo)[1].edges
    for x in EXPECTED[repo]["lines"]:
        if "label_has" in x:
            hits = [e for e in edges if (e.src, e.dst, family(e), e.status) ==
                    (x["src"], x["dst"], x["label_family"], x["status"])]
            assert any(x["label_has"] in e.label for e in hits), (x, [e.label for e in hits])


@pytest.mark.parametrize("repo", REPOS)
def test_suggested_links_are_dotted(repo):
    v = view(repo)[1]
    sug = [e for e in v.edges if any(u.op == "suggested" for u in e.underlying)]
    want = [x for x in EXPECTED[repo]["lines"] if x.get("suggested")]
    assert len(sug) == len(want)
    assert all(e.status == "partial" for e in sug)


@pytest.mark.parametrize("repo", REPOS)
def test_every_file_accounted_for(repo):
    """Every file on disk in the repo is in its expected box, or listed as not scanned or
    skipped; and every classified file of the inventory is in exactly one box."""
    r = fixture_resolved()
    v = view(repo)[1]
    box = {}
    for n in v.nodes:
        if n.kind in ("group", "more"):
            for p in n.members:
                assert p not in box, "%s in two boxes" % p
                box[p] = n.id
    root = ESTATE / repo
    on_disk = set()
    for d, _, fs in os.walk(str(root)):
        for f in fs:
            p = Path(d, f).relative_to(root).as_posix()
            if p != ".archdiag-repo":
                on_disk.add(p)
    listed = {x["path"] for x in r.inventory.not_scanned if x.get("repo") == repo} | \
        {x["path"] for x in r.inventory.skipped if x.get("repo") == repo}
    lost = on_disk - set(box) - listed
    assert not lost, "files that quietly disappear: %s" % sorted(lost)
    classified = {f["path"] for f in r.inventory.files if f.get("repo") == repo}
    assert classified <= set(box), sorted(classified - set(box))
    assert box == EXPECTED[repo]["files"]
