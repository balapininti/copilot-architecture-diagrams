from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .config import Config
from .model import Edge, Evidence, Inventory, Node, Ref, Repo, Resolved
from .repos import iter_source_files, with_long_path


# the shape of inventory.json / links.json; bump when a scanner or resolver change means
# an old cache would give different links
SCHEMA_VERSION = 5


def cache_is_current(inv: Inventory) -> bool:
    """Was this inventory written by this archdiag version and cache schema?"""
    return inv.archdiag_version == __version__ and inv.schema_version == SCHEMA_VERSION


def fingerprint(workspace: Path, repos: Iterable[Repo], config: Config = None) -> str:
    workspace = Path(workspace)
    exclude = config.exclude_dirs if config else ()
    entries = ["archdiag %s schema %d" % (__version__, SCHEMA_VERSION)]
    for repo in repos:
        root = workspace / repo.path
        for p in iter_source_files(root, exclude):
            try:
                st = with_long_path(os.stat, str(p))
            except OSError:
                continue
            rel = p.relative_to(workspace).as_posix()
            entries.append("%s|%d|%d" % (rel, st.st_size, st.st_mtime_ns))
    h = hashlib.sha1()
    for e in sorted(entries):
        h.update(e.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def save_json(path: Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        obj = dataclasses.asdict(obj)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        os.replace(str(tmp), str(path))
    except OSError:
        try:
            os.remove(str(tmp))
        except OSError:
            pass
        raise


def _evidence(d: dict) -> Evidence:
    return Evidence(d["repo"], d["path"], d["line"], d["text"])


def _node(d: dict) -> Node:
    return Node(d["id"], d["kind"], d["name"], d.get("repo"),
                [_evidence(e) for e in d.get("evidence", [])], dict(d.get("attrs", {})))


def _ref(d: dict) -> Ref:
    return Ref(d["src"], d["op"], d["target_kind"], d.get("target_name"), _evidence(d["evidence"]),
               d.get("reason"), list(d.get("candidates", [])), dict(d.get("attrs", {})))


def _edge(d: dict) -> Edge:
    return Edge(d["src"], d["op"], d["dst"], d["status"], d.get("reason"),
                [_evidence(e) for e in d.get("evidence", [])])


def _inventory(d: dict) -> Inventory:
    return Inventory(
        d["workspace"],
        [Repo(r["name"], r["path"]) for r in d.get("repos", [])],
        {k: _node(v) for k, v in d.get("nodes", {}).items()},
        [_ref(r) for r in d.get("refs", [])],
        d.get("fingerprint", ""),
        dict(d.get("languages_not_analyzed", {})),
        [dict(x) for x in d.get("skipped", [])],
        {k: list(v) for k, v in d.get("config_hosts", {}).items()},
        [dict(x) for x in d.get("not_scanned", [])],
        str(d.get("archdiag_version", "")),
        int(d.get("schema_version", 0) or 0),
        [dict(x) for x in d.get("files", [])],
    )


def load_inventory(path: Path) -> Inventory:
    return _inventory(json.loads(Path(path).read_text(encoding="utf-8")))


def load_resolved(path: Path) -> Resolved:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return Resolved(
        _inventory(d["inventory"]),
        {k: _node(v) for k, v in d.get("nodes", {}).items()},
        [_edge(e) for e in d.get("edges", [])],
    )
