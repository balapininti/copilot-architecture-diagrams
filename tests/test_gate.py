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


def actual_set() -> Set[Link]:
    if "actual" not in _CACHE:
        cfg = load_config(ESTATE / "architecture-diagrams")
        r = resolve(scan_workspace(ESTATE, cfg), cfg)
        _CACHE["actual"] = {(e.src, e.op, e.dst, e.status) for e in r.edges}
    return _CACHE["actual"]  # type: ignore[return-value]


def test_expected_list_is_well_formed():
    rows = _expected_rows()
    keys = [(r["src"], r["op"], r["dst"]) for r in rows]
    assert len(keys) == len(set(keys)), "duplicate entries in expected_links.json"
    assert all(r["status"] in ("confirmed", "partial", "loose") for r in rows)


def test_no_missed_links():
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
