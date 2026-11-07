from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from ..config import Config
from ..model import Evidence, Inventory, Node, Ref
from ..repos import discover_repos, iter_source_files
from ..store import fingerprint
from ..textio import classify, needs_text, read_source


@dataclass
class ScanContext:
    procs: Dict[str, str] = field(default_factory=dict)
    proc_src: Dict[str, Tuple[str, str]] = field(default_factory=dict)  # NAME -> (repo, relpath)
    proc_calls: Set[str] = field(default_factory=set)  # PROC names some JCL EXECs (pass 1)
    props: Dict[str, Dict[str, str]] = field(default_factory=dict)   # per repo
    ts_env: Dict[str, Dict[str, str]] = field(default_factory=dict)  # per repo
    # Java / Angular (pass 1): class names defined per repo, and `static final String`
    # constants per repo (name -> source literal)
    # java_classes[repo][Simple] = qualified names (package.Outer.Simple); java_consts[repo]
    # holds "Class.NAME" -> literal and bare "NAME" (only while unique)
    java_classes: Dict[str, Dict[str, Set[str]]] = field(default_factory=dict)
    java_consts: Dict[str, Dict[str, str]] = field(default_factory=dict)
    # ts_classes[repo][Name] = file stems that declare a component / injectable of that name
    ts_classes: Dict[str, Dict[str, Set[str]]] = field(default_factory=dict)
    # config keys: where each base value came from, and keys whose base files disagree
    props_src: Dict[str, Dict[str, Tuple[str, str]]] = field(default_factory=dict)
    props_conflicts: Dict[str, Dict[str, str]] = field(default_factory=dict)
    ts_env_rank: Dict[str, Dict[str, int]] = field(default_factory=dict)
    ts_env_src: Dict[str, Dict[str, str]] = field(default_factory=dict)
    props_prof: Dict[str, Dict[str, Tuple[str, str]]] = field(default_factory=dict)
    java_jms: Dict[str, Dict[str, Tuple[Set[str], Optional[str]]]] = field(default_factory=dict)
    # MQ (pass 1): processes whose APPLICID is CKBR, and queues named in a CKBR start (Q=...)
    ckbr_processes: Set[str] = field(default_factory=set)
    ckbr_queues: Set[str] = field(default_factory=set)
    # z/OS Connect (pass 1): service name -> [(repo, program or None, evidence, provider)]
    zc_services: Dict[str, List[Tuple[str, Optional[str], Evidence, str]]] = field(
        default_factory=dict)
    # z/OS Connect OpenAPI 3: (repo, project prefix, asset name) -> (program or None, evidence, type)
    zc_assets: Dict[Tuple[str, str, str], Tuple[Optional[str], Evidence, str]] = field(
        default_factory=dict)
    # z/OS Connect OpenAPI 3: (repo, project prefix) -> first servers[].url of openapi.yaml/json
    zc_servers: Dict[Tuple[str, str], str] = field(default_factory=dict)


# file type -> scanner(repo, relpath, text, ctx) -> (nodes, refs); registered by later tasks
SCANNERS: Dict[str, Callable[[str, str, str, ScanContext], Tuple[List[Node], List[Ref]]]] = {}

# Binary archives (z/OS Connect .sar/.aar): extension -> reader(path) -> (members, problems),
# members = [(member, text)], problems = [(member or "" for the whole archive, reason)].
# Text scanners keep the (repo, relpath, text, ctx) signature: every text member of an
# archive is classified and scanned as its own file, with relpath "<archive>!/<member>".
ARCHIVE_READERS: Dict[str, Callable[[Path], Tuple[List[Tuple[str, str]],
                                                  List[Tuple[str, str]]]]] = {}
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
    from . import angular, java
    SCANNERS["java"] = java.scan_java
    SCANNERS["angular_ts"] = angular.scan_angular
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
    if ftype == "java":
        from . import java
        java.collect_java(repo, rel, text, ctx)
    elif ftype == "angular_ts":
        from . import angular
        angular.collect_angular(repo, rel, text, ctx)
        _load_ts_env(repo, rel, text, ctx)
    elif ftype in ("yaml", "properties"):
        _load_props(repo, rel, text, ftype, ctx)


_BASE_CONFIG = re.compile(r"^(application|bootstrap)\.(ya?ml|properties)$", re.I)


def _load_props(repo: str, rel: str, text: str, ftype: str, ctx: ScanContext) -> None:
    """application*/bootstrap* yml / properties into ctx.props[repo]. Files under a test
    directory are ignored. The base file wins over profile files (application-dev.yml) and
    later YAML documents; two base files that disagree on a key drop it and remember why."""
    from .lexutil import parse_properties, parse_yaml_docs
    parts = rel.lower().split("/")
    if "test" in parts[:-1] or "tests" in parts[:-1]:
        return
    name = rel.rsplit("/", 1)[-1]
    if not name.lower().startswith(("application", "bootstrap")):
        return
    docs = parse_yaml_docs(text) if ftype == "yaml" else [parse_properties(text)]
    props = ctx.props.setdefault(repo, {})
    src = ctx.props_src.setdefault(repo, {})
    conflicts = ctx.props_conflicts.setdefault(repo, {})
    base = bool(_BASE_CONFIG.match(name))
    for i, doc in enumerate(docs):
        for k, v in doc.items():
            if k in conflicts:
                if not (base and i == 0 and k not in src):
                    continue
                del conflicts[k]  # a profile-level disagreement; the base file decides
            if base and i == 0:
                if k in src and src[k][1] != v:
                    conflicts[k] = "property %s has different values in %s, %s" % (
                        k, src[k][0], rel)
                    props.pop(k, None)
                    continue
                src[k] = (rel, v)
                props[k] = v
            elif k in src:
                continue  # base value wins over profiles
            else:
                prof = ctx.props_prof.setdefault(repo, {})
                if k in prof and prof[k][1] != v:
                    conflicts[k] = "property %s has different values in %s, %s" % (
                        k, prof[k][0], rel)
                    props.pop(k, None)
                else:
                    prof[k] = (rel, v)
                    props[k] = v


def _load_ts_env(repo: str, rel: str, text: str, ctx: ScanContext) -> None:
    """environment*.ts into ctx.ts_env[repo]. environment.prod.ts beats environment.ts,
    which beats other variants; a non-literal value is stored as lexutil.NONLIT."""
    from .lexutil import parse_ts_object, strip_code
    name = rel.rsplit("/", 1)[-1].lower()
    if not re.match(r"environment(\.[\w-]+)?\.ts$", name):
        return
    clean, masked = strip_code(text, ts=True)
    m = re.search(r"\benvironment\b[^=\n]*=\s*\{", masked)
    if not m:
        return
    rank = 2 if name in ("environment.prod.ts", "environment.production.ts") else \
        1 if name == "environment.ts" else 0
    env = ctx.ts_env.setdefault(repo, {})
    ranks = ctx.ts_env_rank.setdefault(repo, {})
    srcs = ctx.ts_env_src.setdefault(repo, {})
    for k, v in parse_ts_object(clean, m.end() - 1).items():
        if k not in env or rank > ranks.get(k, -1):
            env[k] = v
            ranks[k] = rank
            srcs[k] = rel
        elif rank == ranks[k] and env[k] != v and not env[k].startswith("\0conflict:"):
            env[k] = "\0conflict:environment.%s has different values in %s, %s" % (
                k, srcs[k], rel)


def scan_workspace(workspace: Path, config: Config) -> Inventory:
    workspace = Path(workspace)
    repos = discover_repos(workspace)
    ctx = ScanContext()
    nodes: Dict[str, Node] = {}
    refs: List[Ref] = []
    not_analyzed: Dict[str, int] = {}
    skipped: List[Dict[str, str]] = []
    # pass 1: read everything, classify, and collect procs / include members
    files: List[Tuple[str, str, str, str]] = []
    for repo in repos:
        root = workspace / repo.path
        too_big: List[Tuple[Path, str]] = []
        for path in iter_source_files(root, config.exclude_dirs, too_big):
            rel = path.relative_to(root).as_posix()
            reader = ARCHIVE_READERS.get(path.suffix.lower())
            if reader is not None:
                got, problems = reader(path)
                for member, reason in problems:
                    skipped.append({"repo": repo.name, "reason": reason,
                                    "path": rel + (ARCHIVE_SEP + member if member else "")})
                members = [(rel + ARCHIVE_SEP + m, t, classify(m, t)) for m, t in got]
            else:
                if not needs_text(rel):
                    continue
                try:
                    text = read_source(path)
                except (OSError, ValueError) as e:
                    skipped.append({"repo": repo.name, "path": rel,
                                    "reason": "cannot read file: %s" % e})
                    continue
                members = [(rel, text, classify(rel, text))]
            for mrel, text, ftype in members:
                try:
                    _collect_pass(repo.name, mrel, text, ftype, ctx)
                except Exception as e:  # one odd file must not stop the scan
                    skipped.append({"repo": repo.name, "path": mrel,
                                    "reason": "could not be analyzed (%s: %s)"
                                    % (type(e).__name__, e)})
                    continue
                if ftype is not None:
                    files.append((repo.name, mrel, text, ftype))
        for path, reason in too_big:
            skipped.append({"repo": repo.name, "path": path.relative_to(root).as_posix(),
                            "reason": reason})
    # pass 2: scan with the whole estate's procs known
    for repo_name, rel, text, ftype in files:
        if ftype in NOT_ANALYZED:
            not_analyzed[ftype] = not_analyzed.get(ftype, 0) + 1
        scanner = SCANNERS.get(ftype)
        if scanner is None:
            continue
        try:
            new_nodes, new_refs = scanner(repo_name, rel, text, ctx)
        except Exception as e:  # one odd file must not stop the scan
            skipped.append({"repo": repo_name, "path": rel,
                            "reason": "could not be analyzed (%s: %s)" % (type(e).__name__, e)})
            continue
        for n in new_nodes:
            have = nodes.get(n.id)
            if have is None:
                nodes[n.id] = n
                continue
            for ev in n.evidence:  # same id defined again: keep every definition site
                if ev not in have.evidence:
                    have.evidence.append(ev)
        refs.extend(new_refs)
    from . import zosconnect
    refs = zosconnect.merge_built_copies(nodes, refs)
    return Inventory(str(workspace), repos, nodes, refs,
                     fingerprint(workspace, repos, config), not_analyzed, skipped)


_register_builtin_scanners()
