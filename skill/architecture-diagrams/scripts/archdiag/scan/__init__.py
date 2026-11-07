from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from ..config import Config
from ..model import Evidence, Inventory, Node, Ref
from ..repos import discover_repos, iter_source_files
from .. import __version__
from ..store import SCHEMA_VERSION, fingerprint
from ..textio import classify, needs_text, read_source


@dataclass
class ScanContext:
    # every PROC / INCLUDE member definition: NAME -> [(repo, relpath, text)] (several when
    # the same name is defined in more than one place; see jcl.select_proc)
    proc_defs: Dict[str, List[Tuple[str, str, str]]] = field(default_factory=dict)
    proc_calls: Set[str] = field(default_factory=set)  # PROC names some JCL EXECs (pass 1)
    proc_callers: Dict[str, Set[str]] = field(default_factory=dict)  # NAME -> caller repos
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
    # OpenAPI documents under src/main/resources: (repo, every servers[].url, paths keys);
    # their servers count as the repo's address only if the repo serves them (Ruling 39)
    api_specs: List[Tuple[str, List[str], List[str]]] = field(default_factory=list)
    # COBOL copybooks (pass 2): NAME -> the Refs their own text makes (CALL, SQL, CICS, MQ,
    # nested COPY), with src "copybook:NAME"; attributed to every program that COPYs them
    copybook_refs: Dict[str, List[Ref]] = field(default_factory=dict)


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
    jcl.collect_procs(repo, rel, text, ctx, ftype)
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


_URL_HOST = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://(?:[^@/\s'\"]*@)?(\[[^\]]*\]|[^/:?#\s'\"]+)")


# Spring keys that name the service itself (Ruling 38), after relaxed binding (lower case,
# no '-' or '_'): a URL host in any of them, or a bare host in an address/hostname key, is
# the repo's own address. Every other key (partner.url, *.base-url, *.endpoint, ...) is a
# service the repo CALLS, so its host is never counted; when unsure, don't count it.
_OWN_KEY_PREFIXES = ("server.", "spring.application.")
_OWN_ADDRESS_KEYS = frozenset(["server.address", "management.server.address",
                               "eureka.instance.hostname"])
_BARE_HOST = re.compile(
    r"^(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)(?::\d+)?$")


def _own_key(key: str) -> Optional[str]:
    """The relaxed-binding form of a Spring key that names the service itself, else None."""
    k = re.sub(r"[-_]", "", str(key).lower())
    if k in _OWN_ADDRESS_KEYS or k.startswith(_OWN_KEY_PREFIXES):
        return k
    return None


def _value_hosts(value: str, bare: bool) -> List[str]:
    v = str(value).strip()
    hosts = [m.group(1).lower() for m in _URL_HOST.finditer(v)]
    if not hosts and bare:
        m = _BARE_HOST.match(v)
        if m:
            hosts.append(m.group(1).lower())
    return hosts


def _config_hosts(ctx: ScanContext, nodes: Dict[str, Node]) -> Dict[str, List[str]]:
    """Per repo, the hosts its config names as its OWN address (Rulings 36 and 38): hosts
    in Spring keys that name the service (server.*, spring.application.*,
    management.server.address, eureka.instance.hostname), servers[].url of its z/OS Connect
    API projects, and servers[].url of a spec under src/main/resources whose paths hold one
    of its own endpoints (Ruling 39). Client base URLs, client specs and Angular environment
    values are outbound: never counted."""
    found: Dict[str, Set[str]] = {}
    for repo in set(ctx.props) | set(ctx.props_src) | set(ctx.props_prof):
        entries = list(ctx.props.get(repo, {}).items())
        for table in (ctx.props_src, ctx.props_prof):
            entries.extend((k, v) for k, (_rel, v) in table.get(repo, {}).items())
        for k, v in entries:
            own = _own_key(k)
            if own is not None:
                found.setdefault(repo, set()).update(_value_hosts(v, own in _OWN_ADDRESS_KEYS))
    for (repo, _prefix), url in ctx.zc_servers.items():
        found.setdefault(repo, set()).update(_value_hosts(url, False))
    from ..resolve.names import norm_path
    served: Dict[str, Set[str]] = {}
    for n in nodes.values():
        if n.kind == "endpoint" and n.repo and " " in n.name and not n.name.startswith("?"):
            served.setdefault(n.repo, set()).add(n.name.split(" ", 1)[1])
    for repo, urls, paths in ctx.api_specs:
        own = served.get(repo, set())
        for url in urls:
            base = norm_path(url)  # the server URL's path: specs' paths are relative to it
            base = "" if base == "/" else base
            if any(norm_path(p) in own or norm_path(base + p) in own for p in paths):
                found.setdefault(repo, set()).update(_value_hosts(url, False))
    return {repo: sorted(hs) for repo, hs in found.items() if hs}


# extensions of source the scanners read (by extension only: a cheap check)
_MAINFRAME_EXTS = frozenset([".cbl", ".cob", ".cobol", ".cpy", ".copy", ".jcl", ".proc", ".prc",
                             ".cntl", ".jcllib", ".csd", ".bms", ".ddl", ".mqsc", ".asm",
                             ".mac", ".pli", ".pl1", ".ezt", ".rexx", ".rex", ".clist"])
_SOURCE_EXTS = _MAINFRAME_EXTS | frozenset([".sql", ".java", ".ts"])
_MAINFRAME_TEXT = re.compile(
    r"^//\S|^.{6}[*/ ] *(?:\d\d +[A-Z][\w-]* +PIC\b|EXEC +(?:SQL|CICS)\b|"
    r"(?:IDENTIFICATION|PROCEDURE|DATA|ENVIRONMENT) +DIVISION\b|COPY +\w)", re.I | re.M)


def _ext(rel: str) -> str:
    base = rel.rsplit("/", 1)[-1]
    dot = base.rfind(".")
    return base[dot:].lower() if dot > 0 else ""


def _looks_mainframe(rel: str, text: str) -> bool:
    """An untyped file with a mainframe source extension, or mainframe-looking lines."""
    return _ext(rel) in _MAINFRAME_EXTS or bool(_MAINFRAME_TEXT.search(text[:20000]))


def _source_under(folder: Path, exts: frozenset = _MAINFRAME_EXTS, limit: int = 1000
                  ) -> List[Path]:
    """Files under ``folder`` whose extension is source (by name only, never read)."""
    import os
    out: List[Path] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(str(folder)):
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in (".git", "node_modules"))
        for name in sorted(filenames):
            seen += 1
            if _ext(name) in exts:
                out.append(Path(dirpath) / name)
        if seen > limit * 20:
            break
    return out


def _non_repo_folders(workspace: Path, repos, config: Config) -> List[Dict[str, str]]:
    """Folders beside the repos that are not repos (no .git, no .archdiag-repo) yet hold
    source, such as an unpacked zip export: never scanned, so say so."""
    from ..repos import SKIP_DIRS
    if any(r.path == "." for r in repos):
        return []
    names = {r.path for r in repos}
    skip = set(d.lower() for d in SKIP_DIRS) | set(str(d).lower() for d in config.exclude_dirs)
    out: List[Dict[str, str]] = []
    try:
        children = sorted(workspace.iterdir(), key=lambda p: p.name)
    except OSError:
        return out
    for child in children:
        if not child.is_dir() or child.name in names or child.name.startswith(".") \
                or child.name.lower() in skip:
            continue
        found = _source_under(child, _SOURCE_EXTS)
        if found:
            out.append({"repo": "", "path": child.name,
                        "reason": "folder is not a repo (no .git), so it was not scanned, but "
                                  "it holds %d source file(s), e.g. %s" % (len(found), ", ".join(
                                      p.relative_to(workspace).as_posix() for p in found[:3]))})
    return out


def _merge_nodes(nodes: Dict[str, Node], new_nodes: List[Node]) -> None:
    for n in new_nodes:
        have = nodes.get(n.id)
        if have is None:
            nodes[n.id] = n
            continue
        for ev in n.evidence:  # same id defined again: keep every definition site
            if ev not in have.evidence:
                have.evidence.append(ev)


def _note_unclassified(unclassified: Dict[str, List[Tuple[str, str, Path]]], repo: str,
                       rel: str, path: Path) -> None:
    """Remember a file of no type that could be a copybook member (COPY X finds it by stem)."""
    from ..textio import COPY_EXTS
    base = rel.rsplit("/", 1)[-1]
    dot = base.rfind(".")
    ext = base[dot:].lower() if dot > 0 else ""
    if ext in COPY_EXTS:
        unclassified.setdefault((base[:dot] if dot > 0 else base).upper(), []).append(
            (repo, rel, path))


def _copy_names(refs: List[Ref]) -> Set[str]:
    return {r.target_name.strip().upper() for r in refs
            if r.op == "copy" and r.target_kind == "copybook" and r.target_name}


def _copybooks_by_stem(refs: List[Ref], nodes: Dict[str, Node],
                       unclassified: Dict[str, List[Tuple[str, str, Path]]], ctx: ScanContext,
                       skipped: List[Dict[str, str]]) -> None:
    """COPY X with no copybook X found: a file of no type whose stem is X is the member
    (PDS exports often have no extension, or .txt / .inc)."""
    from . import cobol
    done: Set[str] = set()
    while True:
        wanted = set(_copy_names(refs))
        for lst in ctx.copybook_refs.values():
            wanted |= _copy_names(lst)
        wanted = {w for w in wanted - done if "copybook:" + w not in nodes and w in unclassified}
        if not wanted:
            return
        for name in sorted(wanted):
            done.add(name)
            for repo, rel, path in unclassified[name]:
                try:
                    text = read_source(path)
                    new_nodes, _ = cobol.scan_copybook(repo, rel, text, ctx)
                except Exception as e:  # one odd file must not stop the scan
                    skipped.append({"repo": repo, "path": rel,
                                    "reason": "could not be analyzed (%s: %s)"
                                    % (type(e).__name__, e)})
                    continue
                _merge_nodes(nodes, new_nodes)


def _copybook_refs(refs: List[Ref], nodes: Dict[str, Node], ctx: ScanContext) -> List[Ref]:
    """The CALL / SQL / CICS / MQ / COPY statements inside copybooks, as Refs of each
    program that COPYs them (directly or through other copybooks). Evidence is the
    copybook line; attrs["copy_evidence"] is the program's COPY statement. A copybook
    defined in several places makes them partial."""
    from .lexutil import evidence_dict
    out: List[Ref] = []
    seen: Set[Tuple[str, str]] = set()

    def walk(src: str, name: str, copy_ev: Evidence, depth: int, chain: Tuple[str, ...]) -> None:
        node = nodes.get("copybook:" + name)
        inner = ctx.copybook_refs.get(name)
        if node is None or not inner or depth > 8 or name in chain or (src, name) in seen:
            return
        seen.add((src, name))
        amb = None
        if len(node.evidence) > 1:
            amb = "via copybook %s, defined in %d places: %s" % (
                name, len(node.evidence),
                ", ".join("%s/%s" % (e.repo, e.path) for e in node.evidence))
        for r in inner:
            reason = "; ".join(x for x in (r.reason, amb) if x) or None
            attrs = dict(r.attrs)
            attrs["via_copybook"] = name
            attrs["copy_evidence"] = evidence_dict(copy_ev)
            out.append(Ref(src, r.op, r.target_kind, r.target_name, r.evidence, reason,
                           list(r.candidates), attrs))
            if r.op == "copy" and r.target_name:
                walk(src, r.target_name.strip().upper(), copy_ev, depth + 1, chain + (name,))

    for r in list(refs):
        if r.op == "copy" and r.target_kind == "copybook" and r.target_name \
                and not r.src.startswith("copybook:"):
            walk(r.src, r.target_name.strip().upper(), r.evidence, 0, ())
    return out


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
    unclassified: Dict[str, List[Tuple[str, str, Path]]] = {}  # STEM -> files of no type
    not_scanned: List[Dict[str, str]] = _non_repo_folders(workspace, repos, config)
    odd: List[Tuple[str, str]] = []  # untyped files that look like mainframe source
    for repo in repos:
        root = workspace / repo.path
        too_big: List[Tuple[Path, str]] = []
        pruned: List[Path] = []
        for path in iter_source_files(root, config.exclude_dirs, too_big, pruned):
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
                elif mrel == rel:
                    _note_unclassified(unclassified, repo.name, rel, path)
                    if _looks_mainframe(rel, text):
                        odd.append((repo.name, rel))
        for path, reason in too_big:
            skipped.append({"repo": repo.name, "path": path.relative_to(root).as_posix(),
                            "reason": reason})
        for d in pruned:
            found = _source_under(d)
            if found:
                not_scanned.append({
                    "repo": repo.name, "path": d.relative_to(root).as_posix(),
                    "reason": "folder skipped by default (build output) but holds %d source "
                              "file(s), e.g. %s" % (len(found), ", ".join(
                                  p.relative_to(root).as_posix() for p in found[:3]))})
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
        _merge_nodes(nodes, new_nodes)
        refs.extend(new_refs)
    _copybooks_by_stem(refs, nodes, unclassified, ctx, skipped)
    refs.extend(_copybook_refs(refs, nodes, ctx))
    used = {(ev.repo, ev.path) for n in nodes.values() for ev in n.evidence}
    for repo_name, rel in odd:
        if (repo_name, rel) not in used:
            not_scanned.append({"repo": repo_name, "path": rel,
                                "reason": "looks like mainframe source but its type could not "
                                          "be recognised, so it was not analyzed"})
    from . import zosconnect
    refs = zosconnect.merge_built_copies(nodes, refs)
    return Inventory(str(workspace), repos, nodes, refs,
                     fingerprint(workspace, repos, config), not_analyzed, skipped,
                     _config_hosts(ctx, nodes), not_scanned, __version__, SCHEMA_VERSION)


_register_builtin_scanners()
