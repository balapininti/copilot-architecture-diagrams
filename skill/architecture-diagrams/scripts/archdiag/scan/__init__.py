from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from ..config import Config
from ..model import Inventory, Node, Ref
from ..repos import discover_repos, iter_source_files
from ..store import fingerprint
from ..textio import classify, read_source


@dataclass
class ScanContext:
    procs: Dict[str, str] = field(default_factory=dict)
    props: Dict[str, Dict[str, str]] = field(default_factory=dict)   # per repo
    ts_env: Dict[str, Dict[str, str]] = field(default_factory=dict)  # per repo


# file type -> scanner(repo, relpath, text, ctx) -> (nodes, refs); registered by later tasks
SCANNERS: Dict[str, Callable[[str, str, str, ScanContext], Tuple[List[Node], List[Ref]]]] = {}

NOT_ANALYZED = ("asm", "pli", "easytrieve", "rexx")


def scan_workspace(workspace: Path, config: Config) -> Inventory:
    workspace = Path(workspace)
    repos = discover_repos(workspace)
    ctx = ScanContext()
    nodes: Dict[str, Node] = {}
    refs: List[Ref] = []
    not_analyzed: Dict[str, int] = {}
    for repo in repos:
        root = workspace / repo.path
        for path in iter_source_files(root, config.exclude_dirs):
            rel = path.relative_to(root).as_posix()
            text = read_source(path)
            ftype = classify(rel, text)
            if ftype is None:
                continue
            if ftype in NOT_ANALYZED:
                not_analyzed[ftype] = not_analyzed.get(ftype, 0) + 1
            scanner = SCANNERS.get(ftype)
            if scanner is None:
                continue
            new_nodes, new_refs = scanner(repo.name, rel, text, ctx)
            for n in new_nodes:
                nodes.setdefault(n.id, n)
            refs.extend(new_refs)
    return Inventory(str(workspace), repos, nodes, refs,
                     fingerprint(workspace, repos, config), not_analyzed)
