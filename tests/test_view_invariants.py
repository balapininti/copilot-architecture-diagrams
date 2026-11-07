"""Cross-view invariant (final review C3): a drawn line is never more certain than what it
names. For every line on every view of the fixture estate (and of a copy of it with one more
partial SQL link), each target the line stands for has at least one underlying edge as
certain as the line; a line between two repos through a shared resource is no more certain
than the less certain side."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from conftest import ESTATE
from archdiag.config import load_config
from archdiag.gitdiagram import gitdiagram_path, load_gitdiagram
from archdiag.groups import default_groups
from archdiag.model import CONFIRMED, LOOSE, PARTIAL, Edge, Evidence, Inventory, Node, Repo, Resolved
from archdiag.resolve import repo_link_status, repo_links, resolve
from archdiag.scan import scan_workspace
from archdiag.views import ScopeError, build_view

_RANK = {CONFIRMED: 0, PARTIAL: 1, LOOSE: 2}


def _resolved(ws: Path):
    cfg = load_config(ws / "architecture-diagrams")
    r = resolve(scan_workspace(ws, cfg), cfg)
    return r, default_groups(r)


def _all_views(r, g, ws: Path = ESTATE):
    """Every view of the estate at ``ws``, with the gitdiagram views of the repos that have
    a grouping file there (claims-batch and claims-api in the fixture)."""
    out = [build_view(r, g, "landscape", None), build_view(r, g, "repomap", None)]
    for repo in r.inventory.repos:
        if gitdiagram_path(ws / "architecture-diagrams", repo.name).is_file():
            out.append(build_view(r, g, "gitdiagram", repo.name, gitdiagram=load_gitdiagram(
                ws / "architecture-diagrams", r, repo.name)))
    for repo in r.inventory.repos:
        out.append(build_view(r, g, "repomap", repo.name))
    for a in g.apps:
        out.append(build_view(r, g, "application", a.name))
    for n in sorted(r.nodes.values(), key=lambda n: n.id):
        try:
            if n.kind == "job":
                out.append(build_view(r, g, "flow_job", n.id))
            elif n.kind in ("transaction", "page", "endpoint"):
                out.append(build_view(r, g, "flow_tx", n.name))
        except ScopeError:
            continue
    return out


def _violations(views) -> List[Tuple[str, str, str, str, str]]:
    bad = []
    for v in views:
        for e in v.edges:
            if not e.underlying:
                continue
            best: Dict[str, int] = {}
            for u in e.underlying:
                best[u.dst] = min(best.get(u.dst, 2), _RANK[u.status])
            for target, rank in best.items():
                if rank > _RANK[e.status]:
                    bad.append((v.level, v.scope or "", "%s -> %s" % (e.src, e.dst), e.label,
                                target))
    return bad


@pytest.fixture(scope="module")
def estate_with_partial_sql(tmp_path_factory):
    """The fixture estate plus one partial SQL link (OLDS.PAYMENT: matched only after dropping
    a schema that is not an environment qualifier) next to a confirmed one, as in the review."""
    ws = tmp_path_factory.mktemp("fx") / "estate"
    shutil.copytree(str(ESTATE), str(ws))
    p = ws / "claims-api/src/main/java/com/acme/claims/ClaimRepository.java"
    lines = p.read_text(encoding="utf-8").split("\n")
    at = next(i for i, ln in enumerate(lines) if "CLMS.POLICY" in ln)
    lines.insert(at + 1, '        jdbcTemplate.queryForList("SELECT * FROM OLDS.PAYMENT");')
    p.write_text("\n".join(lines), encoding="utf-8")
    return _resolved(ws) + (ws,)


def test_no_line_is_more_certain_than_its_targets_fixture():
    r, g = _resolved(ESTATE)
    views = _all_views(r, g)
    assert {v.scope for v in views if v.level == "gitdiagram"} == {"claims-batch", "claims-api"}
    assert not _violations(views)
    # the C3 trap: PaymentArchiveRepository's OLDS.PAYMENT (partial) beside the solid POLICY
    sql = [e for e in views[0].edges if e.src == "app:claims-api" and e.dst == "app:claims-db"]
    assert {e.status: e.label for e in sql} == {CONFIRMED: "SQL · POLICY",
                                                 PARTIAL: "SQL · PAYMENT"}


def test_no_line_is_more_certain_than_its_targets_with_partial_sql(estate_with_partial_sql):
    r, g, ws = estate_with_partial_sql
    views = _all_views(r, g, ws)
    assert not _violations(views)
    land = views[0]
    sql = [e for e in land.edges if e.src == "app:claims-api" and e.dst == "app:claims-db"]
    by_status = {e.status: e.label for e in sql}
    assert by_status == {CONFIRMED: "SQL · POLICY", PARTIAL: "SQL · PAYMENT"}


def _ev(repo, line):
    return Evidence(repo, "x", line, "line %d" % line)


def test_repo_link_through_shared_dataset_is_the_less_certain_side():
    nodes = {
        "step:a/J#S1": Node("step:a/J#S1", "step", "S1", "a", [_ev("a", 1)]),
        "step:a/J#S2": Node("step:a/J#S2", "step", "S2", "a", [_ev("a", 2)]),
        "step:b/K#S1": Node("step:b/K#S1", "step", "S1", "b", [_ev("b", 1)]),
        "dataset:X.Y": Node("dataset:X.Y", "dataset", "X.Y", None, []),
    }
    edges = [Edge("step:a/J#S1", "write", "dataset:X.Y", CONFIRMED, None, [_ev("a", 1)]),
             Edge("step:a/J#S2", "write", "dataset:X.Y", PARTIAL, "x", [_ev("a", 2)]),
             Edge("step:b/K#S1", "read", "dataset:X.Y", PARTIAL, "symbol", [_ev("b", 1)])]
    inv = Inventory("ws", [Repo("a", "a"), Repo("b", "b")], dict(nodes), [], "", {})
    r = Resolved(inv, nodes, edges)
    (a, b, via, es), = repo_links(r)
    assert (a, b, via) == ("a", "b", "dataset X.Y")
    assert repo_link_status(r, a, b, es) == PARTIAL
    v = build_view(r, default_groups(r), "repomap", None)
    line, = [e for e in v.edges if e.src.startswith("repo:") and e.dst.startswith("repo:")]
    assert line.status == PARTIAL
    edges[2] = Edge("step:b/K#S1", "read", "dataset:X.Y", CONFIRMED, None, [_ev("b", 1)])
    r = Resolved(inv, nodes, edges)
    (a, b, via, es), = repo_links(r)
    assert repo_link_status(r, a, b, es) == CONFIRMED
