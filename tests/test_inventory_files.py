from __future__ import annotations

import json
from dataclasses import asdict

from conftest import fixture_resolved


def _files():
    return fixture_resolved().inventory.files


def test_files_lists_every_classified_file():
    got = {(f["repo"], f["path"]): f["kind"] for f in _files()}
    assert got[("claims-batch", "jcl/CLMD100.jcl")] == "jcl"
    assert got[("shared-copybooks", "CLMREC.cpy")] == "copybook"
    assert ("claims-api", "src/main/resources/application.yml") in got
    assert not [f for f in _files() if "!/" in f["path"]]
    keys = [(f["repo"], f["path"]) for f in _files()]
    assert keys == sorted(keys)


def test_files_round_trip(tmp_path):
    from archdiag.store import _inventory, save_json
    inv = fixture_resolved().inventory
    save_json(tmp_path / "i.json", inv)
    back = _inventory(json.loads((tmp_path / "i.json").read_text(encoding="utf-8")))
    assert back.files == inv.files and inv.files


def test_schema_5_rescans_schema_4_cache():
    from archdiag.store import SCHEMA_VERSION, cache_is_current
    import archdiag
    inv = fixture_resolved().inventory
    assert SCHEMA_VERSION == 5
    inv4 = _copy_with(inv, 4)
    assert not cache_is_current(inv4)


def _copy_with(inv, schema):
    import dataclasses
    return dataclasses.replace(inv, schema_version=schema)


def test_version_is_0_1_4():
    import archdiag
    from pathlib import Path
    assert archdiag.__version__ == "0.1.4"
    toml = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.1.4"' in toml
