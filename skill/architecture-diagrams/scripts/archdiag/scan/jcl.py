from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from ..model import Evidence, Node, Ref
from ..textio import drop_sequence_area
from . import ScanContext

UTILITIES = frozenset([
    "SORT", "ICETOOL", "SYNCSORT", "IEBGENER", "IEBCOPY", "IDCAMS", "IEFBR14",
    "IKJEFT01", "IKJEFT1B", "DMBATCH", "FTP", "ADRDSSU", "DFSRRC00",
])
TSO_DRIVERS = frozenset(["IKJEFT01", "IKJEFT1B"])
# EXEC keywords that are never proc symbol overrides
EXEC_KEYWORDS = frozenset([
    "PARM", "COND", "REGION", "TIME", "ACCT", "ADDRSPC", "DPRTY", "DYNAMNBR",
    "PERFORM", "RD", "MEMLIMIT", "CCSID", "TVSMSG", "TVSAMCOM", "RLSTMOUT",
])
LIBRARY_DDS = frozenset(["STEPLIB", "JOBLIB", "JOBCAT", "STEPCAT", "ISPLLIB"])
MAX_DEPTH = 8

_SYM = re.compile(r"&&|&([A-Za-z#$@][A-Za-z0-9#$@]*)\.?")
_RUN_PROGRAM = re.compile(r"\bRUN\s+PROG(?:RAM)?\s*\(\s*([^)\s]+)\s*\)", re.I)
_SNODE = re.compile(r"\bSNODE\s*=\s*\(?['\"]?([A-Za-z0-9_$#@&.\-]+)", re.I)
_GDG = re.compile(r"^(.*)\(([+-]?\d+)\)$")
_MEMBER = re.compile(r"^(.*)\(([A-Za-z#$@][A-Za-z0-9#$@]*)\)$")


# --------------------------------------------------------------------------
# Statement parsing
# --------------------------------------------------------------------------

class Stmt:
    __slots__ = ("line", "name", "op", "operands", "text", "data")

    def __init__(self, line: int, name: str, op: str, operands: str, text: str) -> None:
        self.line = line
        self.name = name
        self.op = op
        self.operands = operands
        self.text = text
        self.data: List[Tuple[int, str]] = []


def _split_operand(rest: str) -> Tuple[str, str]:
    """Split the operand field from the trailing comment (first blank outside quotes/parens)."""
    quote = False
    depth = 0
    for i, ch in enumerate(rest):
        if ch == "'":
            quote = not quote
        elif quote:
            continue
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch in " \t" and depth == 0:
            return rest[:i], rest[i + 1:].strip()
    return rest, ""


def parse_params(operands: str) -> List[Tuple[Optional[str], str]]:
    """Split on commas outside parentheses/quotes into (KEY|None, value) pairs."""
    parts: List[str] = []
    cur: List[str] = []
    depth = 0
    quote = False
    for ch in operands:
        if ch == "'":
            quote = not quote
        elif not quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif ch == "," and depth == 0:
                parts.append("".join(cur))
                cur = []
                continue
        cur.append(ch)
    parts.append("".join(cur))
    out: List[Tuple[Optional[str], str]] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        eq = p.find("=")
        par = p.find("(")
        if eq > 0 and (par < 0 or eq < par):
            out.append((p[:eq].strip().upper(), p[eq + 1:].strip()))
        else:
            out.append((None, p))
    return out


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        v = v[1:-1].replace("''", "'")
    return v


def _starts_data(stmt: Stmt) -> Tuple[bool, Optional[str]]:
    if stmt.op != "DD":
        return False, None
    params = parse_params(stmt.operands)
    pos = [v.upper() for k, v in params if k is None]
    if not pos or pos[0] not in ("*", "DATA"):
        return False, None
    dlm = None
    for k, v in params:
        if k == "DLM":
            dlm = _unquote(v)
    return True, dlm or None


def parse_statements(text: str) -> List[Stmt]:
    stmts: List[Stmt] = []
    cur: Optional[Stmt] = None
    cont = False
    data_stmt: Optional[Stmt] = None
    data_dlm: Optional[str] = None
    for idx, raw in enumerate(text.split("\n"), 1):
        ln = raw.rstrip().replace("\t", " ")
        if data_stmt is not None:
            if data_dlm:
                if ln.startswith(data_dlm):
                    data_stmt = None
                else:
                    data_stmt.data.append((idx, ln))
                continue
            if ln.startswith("/*"):
                data_stmt = None
                continue
            if not ln.startswith("//"):
                data_stmt.data.append((idx, ln))
                continue
            data_stmt = None  # a '//' line ends the in-stream data
        if ln.startswith("//*") or ln.startswith("/*") or not ln.startswith("//"):
            continue
        body = ln[2:]
        if cont and cur is not None:
            opnd, _ = _split_operand(body.strip())
            cur.operands += opnd
            cont = opnd.endswith(",")
            if not cont:
                starts, data_dlm = _starts_data(cur)
                if starts:
                    data_stmt = cur
            continue
        if not body.strip():
            cur = None
            continue
        if body[0] == " ":
            name, rest = "", body.strip()
        else:
            name, _, rest = body.partition(" ")
            rest = rest.strip()
        op, _, rest = rest.partition(" ")
        rest = rest.strip()
        op = op.upper()
        if op == "IF":
            opnd = rest
        else:
            opnd, _comment = _split_operand(rest)
        cur = Stmt(idx, name.upper(), op, opnd, ln.strip())
        stmts.append(cur)
        cont = op != "IF" and opnd.endswith(",")
        if not cont:
            starts, data_dlm = _starts_data(cur)
            if starts:
                data_stmt = cur
    return stmts


# --------------------------------------------------------------------------
# Symbols
# --------------------------------------------------------------------------

class _Scope:
    def __init__(self, own: Dict[str, str], parent: Optional["_Scope"] = None) -> None:
        self.own = own
        self.parent = parent

    def get(self, key: str) -> Optional[str]:
        s: Optional[_Scope] = self
        while s is not None:
            if key in s.own:
                return s.own[key]
            s = s.parent
        return None

    def snapshot(self) -> "_Scope":
        """Flatten the chain into an independent copy (later SETs must not change it)."""
        chain = []
        s: Optional[_Scope] = self
        while s is not None:
            chain.append(s.own)
            s = s.parent
        flat: Dict[str, str] = {}
        for d in reversed(chain):
            flat.update(d)
        return _Scope(flat)


def _unres_names(text: str) -> List[str]:
    names: List[str] = []
    for m in _SYM.finditer(text):
        if m.group(1) and m.group(1).upper() not in names:
            names.append(m.group(1).upper())
    return names


def _resolve(text: str, scope: _Scope) -> Tuple[str, List[str]]:
    """Substitute &NAME. / &NAME.. symbols; leave unknown ones; return names still unresolved."""
    def rep(m: "re.Match[str]") -> str:
        if m.group(0) == "&&":
            return "&&"
        v = scope.get(m.group(1).upper())
        return m.group(0) if v is None else v

    out = _SYM.sub(rep, text)
    return out, _unres_names(out)


def _reason(names: List[str]) -> Optional[str]:
    if not names:
        return None
    if len(names) == 1:
        return "symbol &%s has no value in these repos" % names[0]
    return "symbols %s have no value in these repos" % ", ".join("&" + n for n in names)


# --------------------------------------------------------------------------
# Pass 1: proc / include member collection
# --------------------------------------------------------------------------

def _stem(relpath: str) -> str:
    base = relpath.replace("\\", "/").rsplit("/", 1)[-1]
    dot = base.rfind(".")
    return (base[:dot] if dot > 0 else base).upper()


def collect_procs(repo: str, relpath: str, text: str, ctx: ScanContext,
                  ftype: Optional[str] = None) -> None:
    """Register PROCs and INCLUDE members (JCL fragments without a JOB card) by name.
    Only JCL-like files count: a Java or TypeScript file that starts with a ``//`` comment
    is never a PROC."""
    if ftype not in ("jcl", "proc", None) or not text.lstrip().startswith("//"):
        return
    stmts = parse_statements(text)
    has_job = any(s.op == "JOB" for s in stmts)
    instream: set = set()  # in-stream PROCs of this job: calls to them use this file's copy
    for s in stmts:
        if s.op == "PROC" and has_job and s.name:
            instream.add(s.name)
        if s.op == "EXEC":
            called = None
            for k, v in parse_params(s.operands):
                if k is None and called is None:
                    called = v
                elif k == "PGM":
                    called = None
                    break
                elif k == "PROC":
                    called = v
            if called and "&" not in called:
                cname = _unquote(called).upper()
                if cname in instream:
                    continue
                ctx.proc_calls.add(cname)
                ctx.proc_callers.setdefault(cname, set()).add(repo)
    if not stmts or has_job:
        return
    names = [_stem(relpath)]
    if stmts[0].op == "PROC" and stmts[0].name and stmts[0].name not in names:
        names.append(stmts[0].name)
    for n in names:
        if n:
            ctx.proc_defs.setdefault(n, []).append((repo, relpath, text))


def _norm_text(text: str) -> str:
    return "\n".join(ln.rstrip() for ln in text.split("\n")).strip()


def select_proc(ctx: ScanContext, name: str, repo: str, what: str = "PROC"
                ) -> Optional[Tuple[Tuple[str, str, str], Optional[str]]]:
    """The definition of PROC / INCLUDE member ``name`` that JCL in ``repo`` uses, and why
    it is not certain (or None). The caller's own repo is searched first; when several
    definitions with different text remain, the first is used and the reason says
    ``ambiguous: PROC X defined in N places: <paths>``."""
    defs = ctx.proc_defs.get(name)
    if not defs:
        return None
    own = [d for d in defs if d[0] == repo]
    pool = sorted(own or defs, key=lambda d: (d[0], d[1]))
    texts = set(_norm_text(d[2]) for d in pool)
    reason = None
    if len(texts) > 1:
        reason = "ambiguous: %s %s defined in %d places: %s" % (
            what, name, len(pool), ", ".join("%s/%s" % (d[0], d[1]) for d in pool))
    return pool[0], reason


def _split_proc(stmts: List[Stmt]) -> Tuple[Dict[str, str], List[Stmt]]:
    """Return (symbol defaults, body statements) of a proc text."""
    defaults: Dict[str, str] = {}
    start = 0
    for i, s in enumerate(stmts):
        if s.op == "PROC":
            for k, v in parse_params(s.operands):
                if k and _unquote(v) != "":
                    defaults[k] = _unquote(v)  # a null/absent default means "not set"
            start = i + 1
            break
    body: List[Stmt] = []
    for s in stmts[start:]:
        if s.op == "PEND":
            break
        body.append(s)
    return defaults, body


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------

class _DD:
    """A DD statement with its symbols already resolved (a snapshot at the point it was read)."""
    __slots__ = ("ddname", "params", "data", "repo", "path", "line", "text", "amb")

    def __init__(self, ddname: str, params: List[Tuple[Optional[str], str, List[str]]],
                 data: List[Tuple[int, str, str, List[str]]], repo: str, path: str,
                 line: int, text: str) -> None:
        self.ddname = ddname
        self.params = params   # (KEY|None, resolved value, unresolved symbol names)
        self.data = data       # (line, evidence text, resolved text, unresolved names)
        self.repo = repo
        self.path = path
        self.line = line
        self.text = text
        self.amb: Optional[str] = None  # read inside an ambiguous PROC / INCLUDE expansion


def _make_dd(ddname: str, stmt: Stmt, scope: _Scope, repo: str, path: str) -> _DD:
    params = []
    for k, v in parse_params(stmt.operands):
        rv, names = _resolve(v, scope)
        params.append((k, rv, names))
    data = []
    for line, text in stmt.data:
        rv, names = _resolve(text, scope)
        data.append((line, text.strip(), rv, names))
    return _DD(ddname, params, data, repo, path, stmt.line, stmt.text)


def _merge_override(orig: _DD, new: _DD) -> _DD:
    """Dotted-DD override: the override's keywords win, everything else is kept from the proc."""
    over_kw = set(k for k, _v, _n in new.params if k)
    params = [p for p in orig.params if p[0] is None or p[0] not in over_kw]
    if any(k is None for k, _v, _n in new.params):
        params = [p for p in params if p[0] is not None]
    params = [p for p in new.params if p[0] is None] + params + [p for p in new.params if p[0]]
    data = new.data if new.data else orig.data
    out = _DD(orig.ddname, params, data, new.repo, new.path, new.line, new.text)
    out.amb = new.amb
    return out


class _Step:
    def __init__(self, sid: str, name: str, order: int, stmt: Optional[Stmt], repo: str, path: str,
                 scope: _Scope, proc: Optional[str], cond: Optional[str]) -> None:
        self.id = sid
        self.name = name
        self.order = order
        self.stmt = stmt
        self.repo = repo
        self.path = path
        self.scope = scope
        self.proc = proc
        self.cond = cond
        self.pgm: Optional[str] = None
        self.pgm_reason: Optional[str] = None
        self.parm: Optional[str] = None
        self.parm_names: List[str] = []
        self.missing_proc: Optional[str] = None
        self.dds: List[_DD] = []
        self.amb: Optional[str] = None  # the step comes from an ambiguous PROC / INCLUDE
        # IDCAMS INFILE / OUTFILE: ddname -> every use in command order (read / write)
        self.dd_modes: Dict[str, List[str]] = {}


class _Scanner:
    def __init__(self, repo: str, relpath: str, ctx: ScanContext, proc_file: bool) -> None:
        self.repo = repo
        self.relpath = relpath
        self.ctx = ctx
        self.proc_file = proc_file
        self.job_id = ("proc:" if proc_file else "job:") + repo + "/" + relpath
        self.steps: List[_Step] = []
        self.used_ids: set = set()
        self.local_procs: Dict[str, Tuple[Dict[str, str], List[Stmt]]] = {}
        self.conds: List[str] = []
        self.cur_step: Optional[_Step] = None
        self.last_call: Dict[str, _Step] = {}
        self.dd_target: Optional[_Step] = None
        self.dd_last: str = ""
        self.active_procs: List[str] = []
        self.header_done = False
        # reasons of the ambiguous PROC / INCLUDE expansions being walked (None = certain)
        self.amb: List[Optional[str]] = []
        # JCLLIB ORDER libraries (dataset names): which repo holds them is not known
        self.jcllib: List[str] = []

    def jcllib_reason(self, what: str, name: str, repo: str, path: str) -> Optional[str]:
        """A PROC / INCLUDE member found only in another repo while the job names its own
        libraries (JCLLIB ORDER): the libraries are not mapped to repos, so not certain."""
        if not self.jcllib or repo == self.repo:
            return None
        return "JCLLIB ORDER not mapped to repos; %s %s taken from %s/%s" % (
            what, name, repo, path)

    def amb_reason(self) -> Optional[str]:
        parts = [a for a in self.amb if a]
        return "; ".join(parts) if parts else None

    # -- helpers
    def _ev(self, repo: str, path: str, line: int, text: str) -> Evidence:
        return Evidence(repo, path, line, text)

    def _step_id(self, name: str, callstep: Optional[str]) -> str:
        base = "step:%s/%s#" % (self.repo, self.relpath)
        sid = base + name
        if sid in self.used_ids and callstep:
            sid = base + callstep + "." + name
        n = 2
        orig = sid
        while sid in self.used_ids:
            sid = "%s_%d" % (orig, n)
            n += 1
        self.used_ids.add(sid)
        return sid

    # -- statement walk
    def run(self, stmts: List[Stmt], src: Tuple[str, str], scope: _Scope,
            proc: Optional[str], callstep: Optional[str], depth: int) -> None:
        mark = len(self.conds)
        i = 0
        while i < len(stmts):
            s = stmts[i]
            i += 1
            op = s.op
            if op == "SET":
                for k, v in parse_params(s.operands):
                    if k:
                        scope.own[k] = _resolve(_unquote(v), scope)[0]
            elif op == "PROC":
                if self.proc_file and not self.header_done and depth == 0:
                    self.header_done = True
                    defaults, _body = _split_proc([s])
                    for k, v in defaults.items():
                        scope.own.setdefault(k, v)
                else:
                    defaults, _ = _split_proc([s])
                    body: List[Stmt] = []
                    while i < len(stmts) and stmts[i].op != "PEND":
                        body.append(stmts[i])
                        i += 1
                    i += 1
                    if s.name:
                        self.local_procs[s.name] = (defaults, body)
            elif op == "IF":
                m = re.match(r"^(.*?)\bTHEN\b", s.operands, re.I)
                cond = " ".join((m.group(1) if m else s.operands).split())
                if cond.startswith("(") and cond.endswith(")") and _balanced(cond[1:-1]):
                    cond = cond[1:-1].strip()
                self.conds.append(cond)
            elif op == "ELSE":
                if self.conds:
                    self.conds[-1] = "NOT (%s)" % self.conds[-1]
            elif op == "ENDIF":
                if self.conds:
                    self.conds.pop()
            elif op == "JCLLIB":
                for k, v in parse_params(s.operands):
                    if k == "ORDER":
                        v = v.strip()
                        if v.startswith("(") and v.endswith(")"):
                            v = v[1:-1]
                        for _k, lib in parse_params(v):
                            lib = _resolve(_unquote(lib), scope)[0].upper()
                            if lib and lib not in self.jcllib:
                                self.jcllib.append(lib)
            elif op == "INCLUDE":
                self.include(s, src, scope, proc, callstep, depth)
            elif op == "EXEC":
                self.exec_stmt(s, src, scope, proc, callstep, depth)
            elif op == "DD":
                self.dd_stmt(s, src, scope)
        del self.conds[mark:]

    def include(self, s: Stmt, src: Tuple[str, str], scope: _Scope, proc: Optional[str],
                callstep: Optional[str], depth: int) -> None:
        member = None
        for k, v in parse_params(s.operands):
            if k == "MEMBER":
                member = _resolve(_unquote(v), scope)[0].upper()
        if not member or depth >= MAX_DEPTH or member in self.active_procs:
            return
        sel = select_proc(self.ctx, member, self.repo, "INCLUDE member")
        if sel is None:
            return
        (irepo, irel, text), amb = sel
        jl = self.jcllib_reason("INCLUDE member", member, irepo, irel)
        amb = "; ".join(x for x in (amb, jl) if x) or None
        isrc = (irepo, irel)
        _defaults, body = _split_proc(parse_statements(text)) if _has_proc(text) else ({}, parse_statements(text))
        self.active_procs.append(member)
        self.amb.append(amb)
        self.run(body, isrc, scope, proc, callstep, depth + 1)
        self.amb.pop()
        self.active_procs.pop()

    def exec_stmt(self, s: Stmt, src: Tuple[str, str], scope: _Scope, proc: Optional[str],
                  callstep: Optional[str], depth: int) -> None:
        pgm = None
        procname = None
        condv = None
        parm = None
        overrides: Dict[str, str] = {}
        for k, v in parse_params(s.operands):
            if k is None:
                if procname is None and pgm is None:
                    procname = v
            elif k == "PGM":
                pgm = v
            elif k == "PROC":
                procname = v
            elif k == "COND":
                condv = "COND=" + "".join(v.split())
            elif k == "PARM":
                parm = _unquote(v)
            elif "." in k or k in EXEC_KEYWORDS:
                continue
            else:
                overrides[k] = _resolve(_unquote(v), scope)[0]
        self.dd_target = None
        self.dd_last = ""
        order = len(self.steps) + 1
        stepname = s.name or "STEP%d" % order
        conds = list(self.conds) + ([condv] if condv else [])
        cond = " AND ".join(conds) if conds else None
        if pgm is not None:
            step = _Step(self._step_id(stepname, callstep), stepname, order, s, src[0], src[1],
                         scope, proc, cond)
            name, unres = _resolve(_unquote(pgm), scope)
            step.pgm = name.upper()
            step.pgm_reason = _reason(unres)
            step.amb = self.amb_reason()
            if parm is not None:
                step.parm, step.parm_names = _resolve(parm, scope)
            self.steps.append(step)
            self.cur_step = step
            self.last_call = {}
            return
        if procname is None:
            return
        pname, _ = _resolve(procname, scope)
        pname = pname.upper()
        found = None
        psrc = src
        amb = None
        sel = select_proc(self.ctx, pname, self.repo)
        if pname in self.local_procs:
            found = self.local_procs[pname]
        elif sel is not None and pname not in self.active_procs and depth < MAX_DEPTH:
            (prepo, prel, ptext), amb = sel
            jl = self.jcllib_reason("PROC", pname, prepo, prel)
            amb = "; ".join(x for x in (amb, jl) if x) or None
            found = _split_proc(parse_statements(ptext))
            psrc = (prepo, prel)
        if found is None:
            step = _Step(self._step_id(stepname, callstep), stepname, order, s, src[0], src[1],
                         scope, pname, cond)
            step.pgm = ""
            step.missing_proc = pname
            step.amb = self.amb_reason()
            self.steps.append(step)
            self.cur_step = step
            self.last_call = {}
            return
        defaults, body = found
        own = dict(defaults)
        own.update(overrides)
        before = len(self.steps)
        self.active_procs.append(pname)
        self.amb.append(amb)
        self.run(body, psrc, _Scope(own, scope), pname, stepname, depth + 1)
        self.amb.pop()
        self.active_procs.pop()
        created = self.steps[before:]
        if condv:  # an EXEC-level COND applies to every step of the call
            for st in created:
                st.cond = " AND ".join(c for c in (st.cond, condv) if c)
        self.last_call = {st.name.upper(): st for st in created}
        self.dd_target = None

    def dd_stmt(self, s: Stmt, src: Tuple[str, str], scope: _Scope) -> None:
        name = s.name
        if "." in name:
            parts = name.split(".")
            ddname = parts[-1]
            target = self.last_call.get(parts[-2]) or self.cur_step
            if target is None:
                return
            new = _make_dd(ddname, s, scope, src[0], src[1])
            new.amb = self.amb_reason()
            for i, d in enumerate(target.dds):
                if d.ddname == ddname:
                    target.dds[i] = _merge_override(d, new)  # only the first DD; keep concatenations
                    break
            else:
                target.dds.append(new)
            self.dd_target, self.dd_last = target, ddname
            return
        elif name:
            target, ddname = self.cur_step, name
            if target is None:
                return  # JOBLIB/JOBCAT etc. before the first step
        else:
            target, ddname = self.dd_target, self.dd_last
            if target is None:
                return
        self.dd_target, self.dd_last = target, ddname
        dd = _make_dd(ddname, s, scope, src[0], src[1])
        dd.amb = self.amb_reason()
        target.dds.append(dd)

    # -- emission
    def emit(self) -> Tuple[List[Node], List[Ref]]:
        nodes: List[Node] = []
        refs: List[Ref] = []
        dd_index: Dict[Tuple[str, str], Tuple[str, bool, Optional[str]]] = {}
        for st in self.steps:
            self.emit_step(st, nodes, refs, dd_index)
        return nodes, refs

    def emit_step(self, st: _Step, nodes: List[Node], refs: List[Ref], dd_index) -> None:
        stmt = st.stmt
        assert stmt is not None
        ev = Evidence(st.repo, st.path, stmt.line, stmt.text)
        sysout: List[str] = []
        attrs = {"order": st.order, "cond": st.cond, "pgm": st.pgm or "", "proc": st.proc,
                 "sysout": sysout, "job": self.job_id}
        if self.jcllib:
            attrs["jcllib"] = list(self.jcllib)
        nodes.append(Node(st.id, "step", st.name, self.repo, [ev], attrs))

        cur_amb: List[Optional[str]] = [st.amb]

        def add(op: str, kind: str, name: Optional[str], e: Evidence, reason: Optional[str] = None,
                a: Optional[dict] = None) -> None:
            parts = [x for x in [reason] + cur_amb if x]
            seen: List[str] = []
            for x in parts:
                if x not in seen:
                    seen.append(x)
            refs.append(Ref(st.id, op, kind, name, e, "; ".join(seen) if seen else None, [],
                            a or {}))

        if st.missing_proc:
            add("runs", "program", None, ev, "PROC %s is not in these repos" % st.missing_proc)
        elif st.pgm:
            self.emit_program(st, ev, add)
        for dd in st.dds:
            cur_amb[1:] = [dd.amb]
            self.emit_dd(st, dd, sysout, add, dd_index)

    def emit_program(self, st: _Step, ev: Evidence, add) -> None:
        pgm = st.pgm or ""
        if pgm in TSO_DRIVERS:
            found = False
            for dd in st.dds:
                if dd.ddname != "SYSTSIN":
                    continue
                for line, evtext, rv, _names in dd.data:
                    for m in _RUN_PROGRAM.finditer(rv):
                        name = m.group(1).upper()
                        kind = "utility" if name in UTILITIES else "program"
                        add("runs", kind, name, Evidence(dd.repo, dd.path, line, evtext),
                            _reason(_unres_names(name)))
                        found = True
            if not found:
                add("runs", "utility", pgm, ev, st.pgm_reason)
            return
        add("runs", "utility" if pgm in UTILITIES else "program", pgm, ev, st.pgm_reason)
        if pgm == "IDCAMS":
            self.emit_idcams(st, add)
        elif pgm == "DMBATCH":
            self.emit_ndm(st, ev, add)
        elif pgm == "FTP":
            self.emit_ftp(st, ev, add)

    @staticmethod
    def _join_data(dd) -> Tuple[str, List[Tuple[int, int, str]]]:
        """Join in-stream lines (dropping trailing - / + continuation marks), keeping line
        offsets. ``dd`` is a _DD or its data lines."""
        text = ""
        offs: List[Tuple[int, int, str]] = []
        for line, evtext, rv, _n in (dd.data if isinstance(dd, _DD) else dd):
            offs.append((len(text), line, evtext))
            piece = rv.rstrip()
            if piece.endswith("-") or piece.endswith("+"):
                piece = piece[:-1]
            text += piece + " "
        return text, offs

    @staticmethod
    def _line_at(offs: List[Tuple[int, int, str]], pos: int) -> Tuple[int, str]:
        best = offs[0]
        for o in offs:
            if o[0] <= pos:
                best = o
        return best[1], best[2]

    def _dataset_ref(self, add, dd: _DD, op: str, raw: str, ev: Evidence, extra: dict) -> None:
        name, gdg, member = _split_dsn(raw.upper())
        a = {"ddname": dd.ddname, "disp": None, "gdg": gdg}
        if member:
            a["member"] = member
        if name.startswith("&&"):
            a["temp"] = True
        a.update(extra)
        add(op, "dataset", name, ev, _reason(_unres_names(name)), a)

    def control_member(self, member: str
                       ) -> Tuple[Optional[Tuple[str, str, List[Tuple[int, str, str, List[str]]]]],
                                  Optional[str]]:
        """The file holding PDS member ``member`` (control statements): one in the job's own
        repo, else the only one in the estate. Returns ((repo, path, data lines), None), or
        (None, why) when several different copies leave it open, or (None, None)."""
        from ..textio import read_source
        pool = self.ctx.members.get(member.upper(), [])
        own = [m for m in pool if m[0] == self.repo]
        pool = sorted(own or pool, key=lambda m: (m[0], m[1]))
        if not pool:
            return None, None
        texts = []
        for repo, rel, path in pool:
            try:
                texts.append(read_source(path))
            except (OSError, ValueError):
                texts.append(None)
        if len(set(_norm_text(t) if t is not None else None for t in texts)) > 1:
            return None, "member %s found in %d places: %s" % (
                member, len(pool), ", ".join("%s/%s" % (m[0], m[1]) for m in pool))
        if texts[0] is None:
            return None, None
        repo, rel, _path = pool[0]
        self.ctx.used_files.add((repo, rel))
        data = []
        for no, raw in enumerate(texts[0].split("\n"), 1):
            ln = drop_sequence_area(raw.rstrip())
            if ln.strip():
                data.append((no, ln.strip(), ln, _unres_names(ln)))
        return (repo, rel, data), None

    def emit_idcams(self, st: _Step, add) -> None:
        """IDCAMS control statements in SYSIN: REPRO / PRINT INDATASET (read) and
        OUTDATASET (write), DEFINE ... NAME (write: it creates the dataset), DELETE
        (delete), and INFILE / OUTFILE ddnames, which set how the step's DDs are used.
        SYSIN may name a dataset instead (DSN=LIB(MEMBER)): a file named MEMBER in the
        job's repo (or only one in the estate) is read as the statements; otherwise a
        partial note says where they are."""
        for dd in st.dds:
            if dd.ddname != "SYSIN":
                continue
            if dd.data:
                self.idcams_statements(st, dd, dd.data, dd.repo, dd.path, add)
                continue
            dsn = next((v for k, v, _n in dd.params if k in ("DSN", "DSNAME")), None)
            if not dsn:
                continue
            full = _unquote(dsn).upper()
            if full.startswith("*.") or full == "NULLFILE":
                continue
            _name, _gdg, member = _split_dsn(full)
            found, why = self.control_member(member) if member else (None, None)
            if found is None:
                reason = "IDCAMS control statements in %s not in these repos" % full
                if why:
                    reason = "IDCAMS control statements in %s: %s" % (full, why)
                add("update", "dataset", None, Evidence(dd.repo, dd.path, dd.line, dd.text),
                    reason, {"ddname": dd.ddname, "via": "idcams", "sysin": full})
                continue
            mrepo, mrel, data = found
            self.idcams_statements(st, dd, data, mrepo, mrel, add)

    def idcams_statements(self, st: _Step, dd: _DD,
                          data: List[Tuple[int, str, str, List[str]]], repo: str, path: str,
                          add) -> None:
        text, offs = self._join_data(data)
        text = _IDC_COMMENT.sub(lambda m: " " * len(m.group(0)), text)
        cmds = list(_IDC_CMD.finditer(text))
        for k, m in enumerate(cmds):
            cmd = m.group(1).upper()
            end = cmds[k + 1].start() if k + 1 < len(cmds) else len(text)
            seg_at, seg = m.end(), text[m.end():end]

            def ref(op: str, raw: str, pos: int) -> None:
                line, evtext = self._line_at(offs, seg_at + pos)
                self._dataset_ref(add, dd, op, raw.strip("'"),
                                  Evidence(repo, path, line, evtext), {"via": "idcams"})
            if cmd in ("REPRO", "PRINT"):
                for o in _IDC_OPT.finditer(seg):
                    kw, val = o.group(1).upper(), o.group(2).strip()
                    if kw in ("INDATASET", "IDS"):
                        ref("read", val, o.start())
                    elif kw in ("OUTDATASET", "ODS"):
                        ref("write", val, o.start())
                    elif kw in ("INFILE", "IFILE", "OUTFILE", "OFILE") and val.split():
                        mode = "read" if kw in ("INFILE", "IFILE") else "write"
                        modes = st.dd_modes.setdefault(val.split()[0].upper(), [])
                        if mode not in modes:
                            modes.append(mode)
            elif cmd == "DEFINE":
                n = _IDC_NAME.search(seg)
                if n:
                    ref("write", n.group(1), n.start())
            elif cmd == "DELETE":
                d = _IDC_DELETE.match(seg)
                if d:
                    names = d.group(1) or d.group(2)
                    for nm in re.finditer(r"'?([A-Za-z0-9#$@&][A-Za-z0-9#$@&.()+-]*)'?",
                                          names):
                        ref("delete", nm.group(1), d.start())

    def emit_ndm(self, st: _Step, ev: Evidence, add) -> None:
        got = False
        for dd in st.dds:
            if not dd.data:
                continue
            text, offs = self._join_data(dd)
            spans = []
            for m in _COPY.finditer(text):
                spans.append(m.span())
                for gi, role in ((1, "read"), (2, "write")):
                    clause = m.group(gi)
                    line, evtext = self._line_at(offs, m.start(gi))
                    cev = Evidence(dd.repo, dd.path, line, evtext)
                    sn = _SNODE.search(clause)
                    dsn = _DSN.search(clause)
                    if sn:
                        name = sn.group(1)
                        a = {"via": "transfer", "direction": "send" if gi == 2 else "receive"}
                        if dsn:
                            a["remote_dsn"] = _trim_paren(dsn.group(1))
                        sline, stext = self._line_at(offs, m.start(gi) + sn.start())
                        add("transfer", "external", "NDM:" + (name if _unres_names(name) else name.upper()),
                            Evidence(dd.repo, dd.path, sline, stext), _reason(_unres_names(name)), a)
                        got = True
                    elif dsn:
                        self._dataset_ref(add, dd, role, _trim_paren(dsn.group(1)), cev, {"via": "transfer"})
            for m in _SNODE.finditer(text):
                if any(a0 <= m.start() < b0 for a0, b0 in spans):
                    continue
                name = m.group(1)
                line, evtext = self._line_at(offs, m.start())
                add("transfer", "external", "NDM:" + (name if _unres_names(name) else name.upper()),
                    Evidence(dd.repo, dd.path, line, evtext), _reason(_unres_names(name)),
                    {"via": "transfer"})
                got = True
        if not got:
            add("transfer", "external", None, ev,
                "Connect:Direct SNODE= was not found in the in-stream input of this step")

    def emit_ftp(self, st: _Step, ev: Evidence, add) -> None:
        host, hev, reason = None, ev, None
        if st.parm and st.parm.split():
            host = st.parm.split()[0]
            reason = _reason(st.parm_names)
        ftp_dds = [dd for dd in st.dds if dd.ddname in ("INPUT", "SYSIN")]
        host_line = None
        if not host:
            for dd in ftp_dds:
                for line, evtext, rv, _n in dd.data:
                    toks = rv.split()
                    if not toks:
                        continue
                    host = toks[1] if toks[0].lower() == "open" and len(toks) > 1 else toks[0]
                    reason = _reason(_unres_names(host))
                    hev = Evidence(dd.repo, dd.path, line, evtext)
                    host_line = line
                    break
                if host:
                    break
        if host:
            add("transfer", "external", "FTP:" + host, hev, reason, {"via": "transfer"})
        else:
            add("transfer", "external", None, ev, "FTP host was not found in this step")
        for dd in ftp_dds:
            for line, evtext, rv, _n in dd.data:
                toks = rv.split()
                if not toks or line == host_line:
                    continue
                cmd = toks[0].lower()
                dev = Evidence(dd.repo, dd.path, line, evtext)
                if cmd in ("put", "mput", "send", "append") and len(toks) > 1 and _is_local_ds(toks[1]):
                    self._dataset_ref(add, dd, "read", toks[1].strip("'"), dev, {"via": "transfer"})
                elif cmd in ("get", "mget", "recv") and len(toks) > 2 and _is_local_ds(toks[2]):
                    self._dataset_ref(add, dd, "write", toks[2].strip("'"), dev, {"via": "transfer"})

    def emit_dd(self, st: _Step, dd: _DD, sysout: List[str], add, dd_index) -> None:
        pos = [v.upper() for k, v, _n in dd.params if k is None]
        kw: Dict[str, str] = {}
        kwn: Dict[str, List[str]] = {}
        for k, v, n in dd.params:
            if k and k not in kw:
                kw[k] = v
                kwn[k] = n
        if "SYSOUT" in kw:
            sysout.append("%s (SYSOUT=%s)" % (dd.ddname, kw["SYSOUT"]))
            return
        if "DUMMY" in pos or (pos and pos[0] in ("*", "DATA", "DYNAM")):
            return
        dkey = "DSN" if "DSN" in kw else ("DSNAME" if "DSNAME" in kw else None)
        if dkey is None:
            return
        ev = Evidence(dd.repo, dd.path, dd.line, dd.text)
        disp_raw = kw.get("DISP")
        disp_names = kwn.get("DISP", [])
        status = _disp_status(disp_raw) if disp_raw is not None else None
        dsn = _unquote(kw[dkey])
        referback = dsn.startswith("*.")
        reason = None
        temp = False
        gdg: Optional[str] = None
        member = None
        names: List[str] = []
        if referback:
            tail = dsn[2:].upper().split(".")
            hit = dd_index.get((tail[-2], tail[-1])) if len(tail) >= 2 else None
            if hit is None:
                name = None
                reason = "backward reference %s does not match an earlier DD in this job" % dsn
            else:
                name, temp, gdg = hit
        else:
            name = dsn.upper()
            if name == "NULLFILE":
                return
            names = _unres_names(name)
            name, gdg, member = _split_dsn(name)
            temp = name.startswith("&&")
        for n in disp_names:
            if n not in names:
                names.append(n)
        if names:
            reason = _reason(names)
        if status == "SHR":
            op = "read"
        elif status in ("NEW", "MOD"):
            op = "write"
        elif status == "OLD":
            op = "update"
        elif disp_names:
            op = "update"  # DISP could not be worked out: assume the widest access
        else:
            op = "read" if referback else "write"
        if temp and op == "update" and not disp_names:
            op = "read"
        ops = [op]
        if dd.ddname in st.dd_modes:
            ops = st.dd_modes[dd.ddname]  # IDCAMS INFILE / OUTFILE: every way it is used
        a = {"ddname": dd.ddname, "disp": disp_raw, "gdg": gdg}
        if temp:
            a["temp"] = True
        if member:
            a["member"] = member
        if dd.ddname in LIBRARY_DDS:
            a["library"] = True
        if name:
            dd_index[(st.name.upper(), dd.ddname)] = (name, temp, gdg)
        for op in ops:
            add(op, "dataset", name, ev, reason, dict(a))


_COPY = re.compile(r"\bCOPY\b\s+FROM\s*\((.*?)\)\s*TO\s*\((.*?)\)", re.I | re.S)
_IDC_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_IDC_CMD = re.compile(r"(?<![\w.&#$@-])(REPRO|PRINT|DEFINE|DELETE|ALTER|LISTCAT|VERIFY|EXPORT|"
                      r"IMPORT|BLDINDEX|EXAMINE|DIAGNOSE|IF|SET)(?![\w.#$@-])", re.I)
_IDC_OPT = re.compile(r"(?<![\w-])(INDATASET|IDS|OUTDATASET|ODS|INFILE|IFILE|OUTFILE|OFILE)"
                      r"\s*\(\s*([^)]*?)\s*\)", re.I)
_IDC_NAME = re.compile(r"(?<![\w-])NAME\s*\(\s*'?([A-Za-z0-9#$@&][A-Za-z0-9#$@&.+-]*)'?\s*\)",
                       re.I)
_IDC_DELETE = re.compile(r"\s*(?:\(([^)]*)\)|('?[A-Za-z0-9#$@&][A-Za-z0-9#$@&.()+-]*'?))")
_DSN = re.compile(r"\bDSN(?:AME)?\s*=\s*([^\s,]+)", re.I)
_DSN_NAME = re.compile(r"^[A-Z#$@&][A-Z0-9#$@&]{0,7}(?:\.[A-Z#$@&][A-Z0-9#$@&]{0,7})+(?:\([A-Z0-9#$@+\-]*\))?$")
_FILE_EXTS = frozenset(["TXT", "CSV", "DAT", "XML", "JSON", "ZIP", "PDF", "LOG", "TSV", "GZ"])


def _trim_paren(v: str) -> str:
    v = v.strip("'")
    while v.endswith(")") and v.count(")") > v.count("("):
        v = v[:-1]
    return v


def _is_local_ds(tok: str) -> bool:
    """FTP put/get argument that is a local z/OS dataset: quoted, or upper-case qualified name."""
    quoted = len(tok) > 2 and tok[0] == "'" and tok[-1] == "'"
    t = tok.strip("'")
    if not _DSN_NAME.match(t.upper()):
        return False
    if quoted:
        return True
    return t == t.upper() and t.rsplit(".", 1)[-1] not in _FILE_EXTS


def _split_dsn(name: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Split a resolved upper-case DSN into (dataset, gdg relative generation, pds member)."""
    m = _GDG.match(name)
    if m:
        n = int(m.group(2))
        return m.group(1), "0" if n == 0 else "%+d" % n, None
    m = _MEMBER.match(name)
    if m:
        return m.group(1), None, m.group(2)
    return name, None, None


def _balanced(s: str) -> bool:
    depth = 0
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _has_proc(text: str) -> bool:
    return any(s.op == "PROC" for s in parse_statements(text))


def _disp_status(raw: str) -> str:
    first = raw.strip().split(",")[0].strip("() ").upper()
    return first or "NEW"


def _scan(repo: str, relpath: str, text: str, ctx: ScanContext, proc_file: bool
          ) -> Tuple[List[Node], List[Ref]]:
    stmts = parse_statements(text)
    card = next((s for s in stmts if s.op == ("PROC" if proc_file else "JOB")), None)
    if card is None:
        return [], []  # a fragment / include member: only scanned where it is INCLUDEd or called
    sc = _Scanner(repo, relpath, ctx, proc_file)
    sc.run(stmts, (repo, relpath), _Scope({}), None, None, 0)
    name = card.name or _stem(relpath)
    node = Node(sc.job_id, "proc" if proc_file else "job", name, repo,
                [Evidence(repo, relpath, card.line, card.text)],
                {"jcllib": list(sc.jcllib)} if sc.jcllib else {})
    called = False
    other_copy = ""
    if proc_file:
        for pn in set([name.upper(), _stem(relpath)]):
            for caller in sorted(ctx.proc_callers.get(pn, ())):
                sel = select_proc(ctx, pn, caller)
                if sel is not None and sel[0][:2] == (repo, relpath):
                    called = True
                else:
                    other_copy = other_copy or ("may use" if sel and sel[1] else "use")
    if called:
        return [node], []  # callers' expansions already cover every step of this PROC
    nodes, refs = sc.emit()
    if proc_file:
        why = ("PROC default values; callers of %s %s another copy of it"
               % (name.upper(), other_copy) if other_copy
               else "PROC default values; no caller in these repos")
        for r in refs:
            r.attrs["proc_default"] = True
            r.reason = why if not r.reason else r.reason + "; " + why
    return [node] + nodes, refs


def scan_jcl(repo: str, relpath: str, text: str, ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    return _scan(repo, relpath, text, ctx, False)


def scan_proc(repo: str, relpath: str, text: str, ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    """A PROC file nobody calls: steps use the PROC's default symbol values, flagged as defaults."""
    return _scan(repo, relpath, text, ctx, True)
