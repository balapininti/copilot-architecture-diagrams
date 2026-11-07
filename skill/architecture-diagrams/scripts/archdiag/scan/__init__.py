from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from ..config import Config
from ..model import Evidence, Inventory, Node, Ref
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
    # MQ (pass 1): processes whose APPLICID is CKBR, and queues named in a CKBR start (Q=...)
    ckbr_processes: Set[str] = field(default_factory=set)
    ckbr_queues: Set[str] = field(default_factory=set)
    # z/OS Connect (pass 1): service name -> [(repo, program or None, evidence, provider)]
    zc_services: Dict[str, List[Tuple[str, Optional[str], Evidence, str]]] = field(
        default_factory=dict)
    # z/OS Connect OpenAPI 3: (repo, project prefix, asset name) -> (program or None, evidence, type)
    zc_assets: Dict[Tuple[str, str, str], Tuple[Optional[str], Evidence, str]] = field(
        default_factory=dict)


# file type -> scanner(repo, relpath, text, ctx) -> (nodes, refs); registered by later tasks
SCANNERS: Dict[str, Callable[[str, str, str, ScanContext], Tuple[List[Node], List[Ref]]]] = {}

# Binary archives (z/OS Connect .sar/.aar): extension -> reader(path) -> [(member, text)].
# Text scanners keep the (repo, relpath, text, ctx) signature: every text member of an
# archive is classified and scanned as its own file, with relpath "<archive>!/<member>".
ARCHIVE_READERS: Dict[str, Callable[[Path], List[Tuple[str, str]]]] = {}
ARCHIVE_SEP = "!/"

NOT_ANALYZED = ("asm", "pli", "easytrieve", "rexx")


def _register_builtin_scanners() -> None:
    from . import jcl
    SCANNERS["jcl"] = jcl.scan_jcl
    SCANNERS["proc"] = jcl.scan_proc
    from . import cobol
    SCANNERS["cobol"] = cobol.scan_cobol
    SCANNERS["copybook"] = cobol.scan_copybook
    from . import cics, ddl, mq, other, zosconnect
    SCANNERS["csd"] = cics.scan_csd
    SCANNERS["bms"] = cics.scan_bms
    SCANNERS["ddl"] = ddl.scan_ddl
    SCANNERS["mqsc"] = mq.scan_mqsc
    SCANNERS["zosconnect"] = zosconnect.scan_zosconnect
    for lang in NOT_ANALYZED:
        SCANNERS[lang] = other.register_other
    for ext in zosconnect.ARCHIVE_EXTS:
        ARCHIVE_READERS[ext] = zosconnect.read_archive


def _collect_pass(repo: str, rel: str, text: str, ftype: Optional[str],
                  ctx: ScanContext) -> None:
    from . import jcl, mq, zosconnect
    jcl.collect_procs(repo, rel, text, ctx)
    mq.collect_mq(repo, rel, text, ftype, ctx)
    zosconnect.collect_zosconnect(repo, rel, text, ftype, ctx)


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
            reader = ARCHIVE_READERS.get(path.suffix.lower())
            if reader is not None:
                members = [(rel + ARCHIVE_SEP + m, t, classify(m, t)) for m, t in reader(path)]
            else:
                text = read_source(path)
                members = [(rel, text, classify(rel, text))]
            for mrel, text, ftype in members:
                _collect_pass(repo.name, mrel, text, ftype, ctx)
                if ftype is not None:
                    files.append((repo.name, mrel, text, ftype))
    # pass 2: scan with the whole estate's procs known
    for repo_name, rel, text, ftype in files:
        if ftype in NOT_ANALYZED:
            not_analyzed[ftype] = not_analyzed.get(ftype, 0) + 1
        scanner = SCANNERS.get(ftype)
        if scanner is None:
            continue
        new_nodes, new_refs = scanner(repo_name, rel, text, ctx)
        for n in new_nodes:
            have = nodes.get(n.id)
            if have is None:
                nodes[n.id] = n
                continue
            for ev in n.evidence:  # same id defined again: keep every definition site
                if ev not in have.evidence:
                    have.evidence.append(ev)
        refs.extend(new_refs)
    return Inventory(str(workspace), repos, nodes, refs,
                     fingerprint(workspace, repos, config), not_analyzed)


_register_builtin_scanners()
