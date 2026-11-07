from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Set, Tuple

from ..config import Config
from ..model import Inventory, Node, Ref
from ..repos import discover_repos, iter_source_files
from ..store import fingerprint
from ..textio import classify, read_source


@dataclass
class ScanContext:
    procs: Dict[str, str] = field(default_factory=dict)
    proc_src: Dict[str, Tuple[str, str]] = field(default_factory=dict)  # NAME -> (repo, relpath)
    proc_calls: Set[str] = field(default_factory=set)  # PROC names some JCL EXECs (pass 1)
    props: Dict[str, Dict[str, str]] = field(default_factory=dict)   # per repo
    ts_env: Dict[str, Dict[str, str]] = field(default_factory=dict)  # per repo


# file type -> scanner(repo, relpath, text, ctx) -> (nodes, refs); registered by later tasks
SCANNERS: Dict[str, Callable[[str, str, str, ScanContext], Tuple[List[Node], List[Ref]]]] = {}

NOT_ANALYZED = ("asm", "pli", "easytrieve", "rexx")


def _register_builtin_scanners() -> None:
    from . import jcl
    SCANNERS["jcl"] = jcl.scan_jcl
    SCANNERS["proc"] = jcl.scan_proc


def _collect_pass(repo: str, rel: str, text: str, ctx: ScanContext) -> None:
    from . import jcl
    jcl.collect_procs(repo, rel, text, ctx)


def scan_workspace(workspace: Path, config: Config) -> Inventory:
    workspace = Path(workspace)
    repos = discover_repos(workspace)
    ctx = ScanContext()
    nodes: Dict[str, Node] = {}
    refs: List[Ref] = []
    not_analyzed: Dict[str, int] = {}
    # pass 1: read everything, classify, and collect procs / include members
    files: List[Tuple[str, str, str, str]] = []
    for repo in repos:
        root = workspace / repo.path
        for path in iter_source_files(root, config.exclude_dirs):
            rel = path.relative_to(root).as_posix()
            text = read_source(path)
            ftype = classify(rel, text)
            _collect_pass(repo.name, rel, text, ctx)
            if ftype is None:
                continue
            files.append((repo.name, rel, text, ftype))
    # pass 2: scan with the whole estate's procs known
    for repo_name, rel, text, ftype in files:
        if ftype in NOT_ANALYZED:
            not_analyzed[ftype] = not_analyzed.get(ftype, 0) + 1
        scanner = SCANNERS.get(ftype)
        if scanner is None:
            continue
        new_nodes, new_refs = scanner(repo_name, rel, text, ctx)
        for n in new_nodes:
            nodes.setdefault(n.id, n)
        refs.extend(new_refs)
    return Inventory(str(workspace), repos, nodes, refs,
                     fingerprint(workspace, repos, config), not_analyzed)


_register_builtin_scanners()
