"""z/OS Connect API definitions: which REST path and method runs which CICS program.

Research (2026-11-06), formats confirmed from IBM documentation and IBM-published samples.
Only the files and keys below are read; nothing else is assumed about an archive's layout.

z/OS Connect EE / OpenAPI 2 -- service side (which CICS program a service runs):
  * Build-toolkit properties file (``zconbt -p=x.properties -f=x.sar``): keys ``name``,
    ``provider`` (must be ``cics`` for the CICS provider) and ``program`` ("The CICS program
    to invoke"), e.g. ``program=CICSPGM3``.
    https://www.ibm.com/docs/en/zos-connect/zosconnect/3.0?topic=reference-creating-cics-service-c-top-down
    https://www.ibm.com/docs/en/zos-connect/3.0.0?topic=reference-command
  * API toolkit service project: ``service.properties`` ("The service.properties file opens
    in the service project editor"). IBM's CICS Banking Sample (Copyright IBM Corp. 2023)
    shows its keys: ``name=CSaccenq``, ``provider=cics``, ``servicetype=cicsCommarea``,
    ``executableName=INQACC`` (the program).
    https://github.com/IBM/example-health-apis/blob/master/ExposeCICSApplicationDataThroughzOSConnect.md
    https://github.com/cicsdev/cics-banking-sample-application-cbsa/tree/July2024Refresh/src/zosconnect_artefacts/services
  * Service archive contents (``.sar``, also unpacked under an API project's ``services/<name>/``):
    ``manifest.yml`` with ``name: "CSaccenq"``, ``provider: "CICS-1.0"`` and a
    ``providerProperties`` list holding ``propertyName: "program"`` / ``value: "INQACC"``.
    https://github.com/cicsdev/cics-banking-sample-application-cbsa/tree/July2024Refresh/src/zosconnect_artefacts/apis
z/OS Connect EE / OpenAPI 2 -- API side (which path and method call which service):
  * API project / API archive (``.aar``) ``package.xml``: ``<zosConnectApi>`` /
    ``<apiSpec basePath="/inqaccz">`` / ``<path relativePath="/enquiry/{accno}">`` /
    ``<method type="GET" zosConnectServiceRef="CSaccenq" .../>``. IBM docs: "double-click the
    package.xml file in your project folder"; per-method ``request.map``/``response.map`` live
    in the project's ``/api`` folder (``api/<path>/<METHOD>/mapping.xml`` repeats the same
    facts; only package.xml is read so each method is counted once).
    https://ibm.com/docs/en/zos-connect/zosconnect/3.0?topic=apis-editing-existing-api
    The REST path is ``basePath + relativePath``.
z/OS Connect OpenAPI 3 (Designer / API provider Gradle project, built as a WAR, not an .aar):
  * Layout ``src/main/api/openapi.yaml``, ``src/main/operations/``, ``src/main/zosAssets/``;
    each z/OS Asset has a ``zosAsset.yaml`` holding the ``program`` value and ``connectionRef``.
    https://www.ibm.com/docs/en/SS4SVW_3.0.0/developing/oa3/provider_using_gradle_plugin.html
  * IBM's sample project (github.com/zosconnect/sample-cics-api, ``finish/``) shows the files:
    ``operations/<URL-encoded path>/<method>/operation.yaml`` with ``zasset: "catalogProgram"``
    (e.g. ``operations/%2Fitems%2F%7Bid%7D/get/``), and
    ``zosAssets/catalogProgram/zosAsset.yaml`` with ``type: "cicsCommarea-1.0"`` and
    ``providerProperties: program: "DFH0XCMN"``.
    https://github.com/zosconnect/sample-cics-api
  * Not confirmed: whether ``servers[].url`` in openapi.yaml (or the WAR context root)
    prefixes the served path, so nothing is added: the path is the operation's own path.

Archives (``.sar``/``.aar``) are zip files and are read with ``zipfile`` (members, and
``.sar`` files nested inside an ``.aar``); unpacked project folders are read the same way.
IBM's DevOps guide notes archives are usually build outputs, not kept in source control:
https://www.ibm.com/docs/en/zos-connect/3.0.0?topic=devops

Output: ``zosapi:<METHOD> <norm path>`` nodes and a ``runs`` Ref to ``program``. If the service
or z/OS Asset isn't in these repos, or maps to more than one program, the Ref has
``target_name=None`` with a reason (and candidates), so the link is partly known, never wrong.
A service in the API's own repo wins over one elsewhere. Non-CICS services (IMS, Db2, MQ...)
give the API node with ``attrs["provider"]`` and no ``runs`` Ref.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

from ..model import Evidence, Node, Ref
from ..resolve.names import norm_path
from . import ARCHIVE_SEP, ScanContext

ARCHIVE_EXTS = (".sar", ".aar")
MAX_MEMBER_BYTES = 5 * 1024 * 1024
MAX_MEMBERS = 5000
_TEXT_MEMBERS = re.compile(r"(?:^|/)(?:package\.xml|manifest\.yml|[^/]*\.properties|"
                           r"zosAsset\.yaml|operation\.yaml)$", re.I)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


_ZIP_ERRORS = (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, RuntimeError, ValueError,
               NotImplementedError, EOFError)


def _members(zf: zipfile.ZipFile, prefix: str, depth: int, out: List[Tuple[str, str]],
             problems: List[Tuple[str, str]]) -> None:
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        problems.append((prefix[:-len(ARCHIVE_SEP)] if prefix else "",
                         "archive has %d members; only the first %d were read"
                         % (len(infos), MAX_MEMBERS)))
    for info in infos[:MAX_MEMBERS]:
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/").lstrip("/")
        nested = name.lower().endswith(".sar") and depth == 0
        if not nested and not _TEXT_MEMBERS.search(name):
            continue
        if info.file_size > MAX_MEMBER_BYTES:
            problems.append((prefix + name, "archive member larger than %d MB (%d bytes)"
                             % (MAX_MEMBER_BYTES // (1024 * 1024), info.file_size)))
            continue
        try:
            if nested:
                with zipfile.ZipFile(io.BytesIO(zf.read(info))) as inner:
                    _members(inner, prefix + name + ARCHIVE_SEP, depth + 1, out, problems)
            else:
                text = _decode(zf.read(info)).replace("\r\n", "\n").replace("\r", "\n")
                out.append((prefix + name, text))
        except _ZIP_ERRORS as e:
            problems.append((prefix + name, "unreadable archive member: %s" % e))


def read_archive(path: Path) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """Text members of a .sar/.aar that hold z/OS Connect facts, and the problems met:
    ([(member, text)], [(member or "" for the whole archive, reason)])."""
    out: List[Tuple[str, str]] = []
    problems: List[Tuple[str, str]] = []
    try:
        with zipfile.ZipFile(str(path)) as zf:
            _members(zf, "", 0, out, problems)
    except _ZIP_ERRORS as e:
        return [], [("", "unreadable archive: %s" % e)]
    return out, problems


# ------------------------------------------------------------------ small parsers


def _line_of(text: str, off: int) -> int:
    return text.count("\n", 0, off) + 1


def _ev(repo: str, rel: str, text: str, line: int) -> Evidence:
    lines = text.split("\n")
    return Evidence(repo, rel, line, lines[line - 1].strip() if line <= len(lines) else "")


def _props(text: str) -> Dict[str, Tuple[str, int]]:
    out: Dict[str, Tuple[str, int]] = {}
    for no, raw in enumerate(text.split("\n"), 1):
        s = raw.strip()
        if not s or s[0] in "#!":
            continue
        m = re.match(r"([^=:\s]+)\s*[=:]\s*(.*)$", s)
        if m:
            out[m.group(1)] = (m.group(2).strip(), no)
    return out


def _yaml_scalar(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return re.sub(r"\s+#.*$", "", v)


def _yaml_key(text: str, key: str, indent: Optional[str] = None) -> Optional[Tuple[str, int]]:
    pat = r"^%s%s:\s*(.*)$" % (indent if indent is not None else r"\s*", re.escape(key))
    m = re.search(pat, text, re.M)
    if not m:
        return None
    return _yaml_scalar(m.group(1)), _line_of(text, m.start(1))


def _manifest_program(text: str) -> Optional[Tuple[str, int]]:
    """providerProperties entry ``propertyName: "program"`` -> its ``value``."""
    lines = text.split("\n")
    for i, raw in enumerate(lines):
        m = re.match(r"^\s*-?\s*propertyName:\s*(.*)$", raw)
        if not m or _yaml_scalar(m.group(1)) != "program":
            continue
        for j in range(i + 1, min(i + 4, len(lines))):
            if re.match(r"^\s*-", lines[j]):
                break
            v = re.match(r"^\s*value:\s*(.*)$", lines[j])
            if v:
                return _yaml_scalar(v.group(1)), j + 1
    return None


def _project_prefix(rel: str, marker: str) -> Optional[str]:
    i = rel.rfind("/" + marker + "/")
    if i >= 0:
        return rel[:i + 1]
    return "" if rel.startswith(marker + "/") else None


_OAS3_DOCS = ("openapi.yaml", "openapi.yml", "openapi.json", "swagger.json")


def _servers_urls(text: str) -> List[str]:
    """Every ``servers[].url`` of an OpenAPI document (YAML or JSON), in order."""
    m = re.search(r'"servers"\s*:\s*\[(.*?)\]', text, re.S)
    if m:
        return [u.strip() for u in re.findall(r'"url"\s*:\s*"([^"]*)"', m.group(1))
                if u.strip()]
    out: List[str] = []
    lines = text.split("\n")
    for i, raw in enumerate(lines):
        if re.match(r"^servers\s*:", raw):
            for nxt in lines[i + 1:]:
                if nxt.strip() and not nxt[:1].isspace() and not nxt.startswith("-"):
                    break  # next top-level key
                u = re.match(r"^\s*-?\s*url\s*:\s*(.+)$", nxt)
                if u:
                    v = _yaml_scalar(u.group(1))
                    if v:
                        out.append(v)
            break
    return out


def _servers_url(text: str) -> Optional[str]:
    """First ``servers[].url`` of an OpenAPI document (YAML or JSON)."""
    urls = _servers_urls(text)
    return urls[0] if urls else None


# ------------------------------------------------------------------ pass 1


def _add_service(ctx: ScanContext, name: str, repo: str, program: Optional[str],
                 ev: Evidence, provider: str) -> None:
    ctx.zc_services.setdefault(name, []).append((repo, program, ev, provider))


def collect_zosconnect(repo: str, rel: str, text: str, ftype: Optional[str],
                       ctx: ScanContext) -> None:
    """Pass 1: services (name -> program) and OpenAPI 3 z/OS Assets, estate-wide."""
    base = rel.rsplit("/", 1)[-1]
    low = base.lower()
    if low in _OAS3_DOCS:
        prefix = _project_prefix(rel, "api")
        urls = _servers_urls(text)
        if urls and prefix is not None:
            ctx.zc_servers[(repo, prefix)] = urls[0]
        parts = rel.lower().split("/")
        if urls and "test" not in parts[:-1] and "tests" not in parts[:-1]:
            # the repo's own API definition: where it is served (Ruling 38)
            ctx.api_servers.setdefault(repo, []).extend(urls)
        return
    if ftype != "zosconnect":
        return
    if low == "manifest.yml":
        name = _yaml_key(text, "name", "")
        provider = (_yaml_key(text, "provider", "") or ("", 0))[0]
        if not name:
            return
        prog = _manifest_program(text) if provider.lower().startswith("cics") else None
        line = prog[1] if prog else name[1]
        _add_service(ctx, name[0], repo, prog[0].upper() if prog else None,
                     _ev(repo, rel, text, line), provider)
    elif low.endswith(".properties"):
        p = _props(text)
        name = p.get("name")
        prog = p.get("program") or p.get("executableName")
        if not name or not prog or not prog[0]:
            return
        _add_service(ctx, name[0], repo, prog[0].upper(), _ev(repo, rel, text, prog[1]),
                     p.get("provider", ("cics", 0))[0])
    elif low == "zosasset.yaml":
        prefix = _project_prefix(rel, "zosAssets")
        if prefix is None:
            return
        asset = rel[len(prefix) + len("zosAssets/"):].split("/", 1)[0]
        atype = (_yaml_key(text, "type", "") or ("", 0))[0]
        prog = _yaml_key(text, "program")
        if prog and not prog[0]:
            prog = None
        line = prog[1] if prog else 1
        ctx.zc_assets[(repo, prefix, asset)] = (
            prog[0].upper() if prog else None, _ev(repo, rel, text, line), atype)


# ------------------------------------------------------------------ pass 2

_TAG = re.compile(r"<\s*(?:\w+:)?(apiSpec|path|method)\b([^>]*)>", re.S)
_ATTR = re.compile(r"([\w:.-]+)\s*=\s*(\"[^\"]*\"|'[^']*')")


def _attrs(s: str) -> Dict[str, str]:
    return {k: v[1:-1] for k, v in _ATTR.findall(s)}


def _runs_ref(src: str, ev: Evidence, label: str,
              found: List[Tuple[str, Optional[str], Evidence, str]],
              repo: str, attrs: Dict[str, str]) -> Optional[Ref]:
    """Ref from an API operation to the program behind a service or asset (or why unknown).

    The nearest definitions win: the API's own archive (for an API inside an .aar), then
    unpacked files in the same repo, then anything in the same repo, then the estate.
    """
    container = ev.path.split(ARCHIVE_SEP, 1)[0] + ARCHIVE_SEP if ARCHIVE_SEP in ev.path else None
    local = [f for f in found if f[0] == repo]
    tiers = [
        [f for f in local if container and f[2].path.startswith(container)],
        [f for f in local if ARCHIVE_SEP not in f[2].path],
        local,
        found,
    ]
    use = next((t for t in tiers if t), [])
    if not use:
        return Ref(src, "runs", "program", None, ev,
                   "z/OS Connect %s is not in these repos" % label, [], dict(attrs))
    progs = sorted({f[1] for f in use if f[1]})
    if not progs:
        providers = sorted({f[3] for f in use if f[3]})
        if providers and not any(p.lower().startswith("cics") for p in providers):
            return None  # IMS, Db2, MQ, REST... provider: no CICS program to run
        return Ref(src, "runs", "program", None, ev,
                   "z/OS Connect %s names no CICS program" % label, [], dict(attrs))
    at = [f[2] for f in use if f[1]]
    attrs = dict(attrs, service_at="%s:%d" % (at[0].path, at[0].line))
    every = sorted({f[1] for f in found if f[1]})
    if len(progs) == 1 and len(every) == 1:
        return Ref(src, "runs", "program", progs[0], ev, None, [], attrs)
    if len(progs) == 1:
        # the nearest definition must not hide a conflict: another copy (a stale build
        # archive, another repo) names a different program
        where = sorted({"%s/%s" % (f[0], f[2].path) for f in found if f[1]})
        return Ref(src, "runs", "program", None, ev,
                   "z/OS Connect %s maps to different programs in different places: %s (%s)"
                   % (label, ", ".join(every), ", ".join(where)), every, attrs)
    return Ref(src, "runs", "program", None, ev,
               "z/OS Connect %s maps to more than one program: %s" % (label, ", ".join(every)),
               every, attrs)


def _scan_package(repo: str, rel: str, text: str,
                  ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    nodes: List[Node] = []
    refs: List[Ref] = []
    base_path, rel_path = "", ""
    for m in _TAG.finditer(text):
        tag, a = m.group(1), _attrs(m.group(2))
        if tag == "apiSpec":
            base_path = a.get("basePath", "")
        elif tag == "path":
            rel_path = a.get("relativePath", "")
        else:
            method = a.get("type", "").upper()
            service = a.get("zosConnectServiceRef", "")
            if not method:
                continue
            path = norm_path(base_path.rstrip("/") + "/" + rel_path.lstrip("/"))
            nid = "zosapi:%s %s" % (method, path)
            ev = _ev(repo, rel, text, _line_of(text, m.start()))
            providers = sorted({f[3] for f in ctx.zc_services.get(service, []) if f[3]})
            nodes.append(Node(nid, "zosapi", "%s %s" % (method, path), repo, [ev],
                              {"method": method, "path": path, "service": service or None,
                               "provider": providers[0] if len(providers) == 1 else None}))
            if not service:
                refs.append(Ref(nid, "runs", "program", None, ev,
                                "z/OS Connect API method names no service", [], {}))
                continue
            r = _runs_ref(nid, ev, "service %s" % service, ctx.zc_services.get(service, []),
                          repo, {"service": service})
            if r is not None:
                refs.append(r)
    return nodes, refs


def _scan_operation(repo: str, rel: str, text: str,
                    ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    prefix = _project_prefix(rel, "operations")
    if prefix is None:
        return [], []
    parts = rel[len(prefix) + len("operations/"):].split("/")
    if len(parts) != 3:
        return [], []
    path = norm_path(unquote(parts[0]))
    method = parts[1].upper()
    nid = "zosapi:%s %s" % (method, path)
    asset = _yaml_key(text, "zasset")
    line = asset[1] if asset else 1
    ev = _ev(repo, rel, text, line)
    attrs: Dict[str, object] = {"method": method, "path": path,
                                "zasset": asset[0] if asset else None}
    found = ctx.zc_assets.get((repo, prefix, asset[0])) if asset and asset[0] else None
    if found:
        attrs["provider"] = found[2] or None
    base_url = ctx.zc_servers.get((repo, prefix))
    if base_url:
        attrs["base_url"] = base_url  # servers[].url: kept, not part of the id (unconfirmed)
    nodes = [Node(nid, "zosapi", "%s %s" % (method, path), repo, [ev], attrs)]
    if not asset or not asset[0]:
        return nodes, [Ref(nid, "runs", "program", None, ev,
                           "z/OS Connect operation names no z/OS Asset", [], {})]
    cand = [(repo, found[0], found[1], found[2])] if found else []
    r = _runs_ref(nid, ev, "z/OS Asset %s" % asset[0], cand, repo, {"zasset": asset[0]})
    return nodes, [r] if r else []


def merge_built_copies(nodes: Dict[str, Node], refs: List[Ref]) -> List[Ref]:
    """One definition per API operation when a repo holds both the project and its build.

    Within one repo, a ``zosapi`` operation defined in an unpacked project and again in an
    archive (``!/`` path) with the same program keeps the unpacked file as its evidence and
    ``runs`` Ref; the archive copies go to ``attrs["also_built_as"]``. Different programs
    are a real ambiguity and are all kept.
    """
    def key(r: Ref) -> Tuple[str, Optional[str], Tuple[str, ...], Optional[str]]:
        return (r.evidence.repo, r.target_name, tuple(r.candidates), r.reason)

    by_src: Dict[str, List[Ref]] = {}
    for r in refs:
        if r.src.startswith("zosapi:"):
            by_src.setdefault(r.src, []).append(r)
    drop = set()
    for nid, node in nodes.items():
        if node.kind != "zosapi" or len(node.evidence) < 2:
            continue
        mine = by_src.get(nid, [])
        built: List[str] = []
        dropped_paths = set()
        for r in mine:
            if ARCHIVE_SEP not in r.evidence.path:
                continue
            if any(key(o) == key(r) and ARCHIVE_SEP not in o.evidence.path for o in mine):
                drop.add(id(r))
                dropped_paths.add((r.evidence.repo, r.evidence.path))
        with_ref = {(r.evidence.repo, r.evidence.path) for r in mine}
        unpacked_no_ref = {e.repo for e in node.evidence
                           if ARCHIVE_SEP not in e.path and (e.repo, e.path) not in with_ref}
        keep = []
        for e in node.evidence:
            k = (e.repo, e.path)
            if ARCHIVE_SEP in e.path and (k in dropped_paths or (
                    k not in with_ref and e.repo in unpacked_no_ref)):
                if e.path not in built:
                    built.append(e.path)
                continue
            keep.append(e)
        if built:
            node.evidence = keep
            node.attrs["also_built_as"] = built
    return [r for r in refs if id(r) not in drop]


def scan_zosconnect(repo: str, relpath: str, text: str,
                    ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    low = relpath.rsplit("/", 1)[-1].lower()
    if low == "package.xml":
        return _scan_package(repo, relpath, text, ctx)
    if low == "operation.yaml":
        return _scan_operation(repo, relpath, text, ctx)
    return [], []  # services and assets were collected in pass 1
