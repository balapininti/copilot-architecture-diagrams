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


def _scan(tmp_path, files):
    from archdiag.config import Config
    from archdiag.scan import scan_workspace
    repo = tmp_path / "r"
    (repo / ".archdiag-repo").parent.mkdir(parents=True)
    (repo / ".archdiag-repo").write_text("", encoding="utf-8")
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return scan_workspace(tmp_path, Config())


def test_stem_resolved_copybooks_are_listed(tmp_path):
    cob = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PROGA.\n"
           "       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
           "           COPY CPYONE.\n           COPY CPYTWO.\n"
           "       PROCEDURE DIVISION.\n           GOBACK.\n")
    body = "       01  X-REC.\n           05  X-F PIC X(4).\n"
    inv = _scan(tmp_path, {"src/PROGA.cbl": cob, "cpy/CPYONE": body, "cpy/CPYTWO.txt": body})
    got = {f["path"]: f["kind"] for f in inv.files}
    assert got["cpy/CPYONE"] == "copybook"
    assert got["cpy/CPYTWO.txt"] == "copybook"


def test_sysin_only_member_is_not_listed(tmp_path):
    jcl = "//J1 JOB\n//S1 EXEC PGM=IDCAMS\n//SYSIN DD DSN=MY.LIB(CTL1),DISP=SHR\n"
    inv = _scan(tmp_path, {"jcl/J1.jcl": jcl, "ctl/CTL1": "REPRO IN(A) OUT(B)\n",
                           "ctl/OTHER.txt": "x\n"})
    paths = {f["path"] for f in inv.files}
    assert "jcl/J1.jcl" in paths
    assert "ctl/CTL1" not in paths


def test_archive_file_itself_is_listed_as_zosconnect(tmp_path):
    # members are left out ("!/"), but the .aar is the file in the repo: it must not vanish
    import zipfile
    from archdiag.config import Config
    from archdiag.scan import scan_workspace
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / ".archdiag-repo").write_text("", encoding="utf-8")
    with zipfile.ZipFile(str(repo / "svc.aar"), "w") as zf:
        zf.writestr("META-INF/x.properties", "a=b\n")
    inv = scan_workspace(tmp_path, Config())
    got = {f["path"]: f["kind"] for f in inv.files}
    assert got.get("svc.aar") == "zosconnect"
    assert not any("!/" in p for p in got)
