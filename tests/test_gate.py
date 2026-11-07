"""The release gate (spec §11): over the claims fixture estate, every expected link is found
and no unexpected solid link appears.

``fixtures/expected_links.json`` is written by hand from the fixture sources; the reason for
each entry is in ``fixtures/expected_links_notes.md``. When this gate fails, fix the scanner
or resolver, not the list, unless the entry contradicts the spec (then say why in the notes).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Set, Tuple

from conftest import ESTATE
from archdiag.config import load_config
from archdiag.resolve import resolve
from archdiag.scan import scan_workspace

EXPECTED_FILE = Path(__file__).parent / "fixtures" / "expected_links.json"
Link = Tuple[str, str, str, str]

_CACHE: Dict[str, object] = {}


def _expected_rows():
    return json.loads(EXPECTED_FILE.read_text(encoding="utf-8"))


def expected_set() -> Set[Link]:
    return {(r["src"], r["op"], r["dst"], r["status"]) for r in _expected_rows()}


def resolved():
    if "r" not in _CACHE:
        cfg = load_config(ESTATE / "architecture-diagrams")
        _CACHE["r"] = resolve(scan_workspace(ESTATE, cfg), cfg)
    return _CACHE["r"]


def actual_set() -> Set[Link]:
    return {(e.src, e.op, e.dst, e.status) for e in resolved().edges}  # type: ignore[attr-defined]


def test_expected_list_is_well_formed():
    rows = _expected_rows()
    assert expected_set(), "expected_links.json is empty"
    keys = [(r["src"], r["op"], r["dst"]) for r in rows]
    assert len(keys) == len(set(keys)), "duplicate entries in expected_links.json"
    assert all(r["status"] in ("confirmed", "partial", "loose") for r in rows)


def test_no_missed_links():
    assert expected_set()
    missing = expected_set() - actual_set()
    assert not missing, "missed links: %s" % sorted(missing)


def test_no_unexpected_confirmed_links():
    extra = {e for e in actual_set() if e[3] == "confirmed"} - expected_set()
    assert not extra, "unexpected solid links: %s" % sorted(extra)


def test_status_matches():
    want = {(s, o, d): st for s, o, d, st in expected_set()}
    got: Dict[Tuple[str, str, str], Set[str]] = {}
    for s, o, d, st in actual_set():
        got.setdefault((s, o, d), set()).add(st)
    wrong = {k: (want[k], sorted(v)) for k, v in got.items() if k in want and v != {want[k]}}
    assert not wrong, "status differs (expected, actual): %s" % wrong


def test_no_unexpected_links():
    # the list holds every edge, so a new dotted or red edge is a change to look at too
    extra = actual_set() - expected_set()
    assert not extra, "edges not in the expected list: %s" % sorted(extra)


def _files(evidence) -> Set[Tuple[str, str]]:
    return {(v.repo, v.path) for v in evidence}


def test_every_edge_has_evidence():
    bare = [(e.src, e.op, e.dst) for e in resolved().edges if not e.evidence]
    assert not bare, "edges without evidence: %s" % bare


def _norm(text: str) -> str:
    return " ".join(text.split())


def _line_is_real(v) -> bool:
    """Does line ``v.line`` of the fixture file hold the text the evidence quotes?"""
    f = ESTATE / v.repo / v.path
    if v.line < 1 or not f.is_file():
        return False
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    return v.line <= len(lines) and _norm(v.text)[:20] in _norm(lines[v.line - 1])


MIN_CHECKED = 30  # the estate has 38 confirmed edges between two nodes defined in the code


def test_confirmed_edges_carry_evidence_for_both_ends():
    # spec §7.3: every link stores both ends' file and line. Checked where both ends are
    # nodes defined in the code (resolver-made dataset, utility and missing nodes have none).
    # Destination: the edge cites the line the node is defined on. Source: the edge cites a
    # line (not just a file) of the source's own file, and that line really holds the quote.
    r = resolved()
    short, checked = [], 0
    for e in r.edges:  # type: ignore[attr-defined]
        if e.status != "confirmed":
            continue
        s, d = r.nodes.get(e.src), r.nodes.get(e.dst)
        if s is None or d is None or not s.evidence or not d.evidence:
            continue
        checked += 1
        got = set((v.repo, v.path, v.line) for v in e.evidence)
        dst_ok = any((v.repo, v.path, v.line) in got for v in d.evidence)
        src_files = _files(s.evidence)
        src_ok = any((v.repo, v.path) in src_files and _line_is_real(v) for v in e.evidence)
        if not (src_ok and dst_ok):
            short.append((e.src, e.op, e.dst, src_ok, dst_ok))
    assert not short, "confirmed edges missing an end's evidence (src_ok, dst_ok): %s" % short
    assert checked >= MIN_CHECKED, "only %d edges checked: the test went vacuous" % checked
