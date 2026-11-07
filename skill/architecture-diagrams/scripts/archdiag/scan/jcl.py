from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from ..model import Evidence, Node, Ref
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


def _resolve(text: str, scope: _Scope) -> Tuple[str, List[str]]:
    """Substitute &NAME. / &NAME.. symbols; leave unknown ones; return names still unresolved."""
    def rep(m: "re.Match[str]") -> str:
        if m.group(0) == "&&":
            return "&&"
        v = scope.get(m.group(1).upper())
        return m.group(0) if v is None else v

    out = _SYM.sub(rep, text)
    names: List[str] = []
    for m in _SYM.finditer(out):
        if m.group(1) and m.group(1).upper() not in names:
            names.append(m.group(1).upper())
    return out, names


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


def collect_procs(repo: str, relpath: str, text: str, ctx: ScanContext) -> None:
    """Register PROCs and INCLUDE members (JCL fragments without a JOB card) by name."""
    if not text.lstrip().startswith("//"):
        return
    stmts = parse_statements(text)
    if not stmts or any(s.op == "JOB" for s in stmts):
        return
    names = [_stem(relpath)]
    if stmts[0].op == "PROC" and stmts[0].name:
        names.append(stmts[0].name)
    for n in names:
        if n and n not in ctx.procs:
            ctx.procs[n] = text
            ctx.proc_src[n] = (repo, relpath)


def _split_proc(stmts: List[Stmt]) -> Tuple[Dict[str, str], List[Stmt]]:
    """Return (symbol defaults, body statements) of a proc text."""
    defaults: Dict[str, str] = {}
    start = 0
    for i, s in enumerate(stmts):
        if s.op == "PROC":
            for k, v in parse_params(s.operands):
                if k:
                    defaults[k] = _unquote(v)
                else:
                    defaults.setdefault(v.upper(), "")
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
    __slots__ = ("ddname", "stmt", "scope", "repo", "path")

    def __init__(self, ddname: str, stmt: Stmt, scope: _Scope, repo: str, path: str) -> None:
        self.ddname = ddname
        self.stmt = stmt
        self.scope = scope
        self.repo = repo
        self.path = path


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
        self.missing_proc: Optional[str] = None
        self.dds: List[_DD] = []


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
        text = self.ctx.procs.get(member)
        if text is None:
            return
        isrc = self.ctx.proc_src.get(member, src)
        _defaults, body = _split_proc(parse_statements(text)) if _has_proc(text) else ({}, parse_statements(text))
        self.active_procs.append(member)
        self.run(body, isrc, scope, proc, callstep, depth + 1)
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
            step.parm = parm
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
        if pname in self.local_procs:
            found = self.local_procs[pname]
        elif pname in self.ctx.procs and pname not in self.active_procs and depth < MAX_DEPTH:
            found = _split_proc(parse_statements(self.ctx.procs[pname]))
            psrc = self.ctx.proc_src.get(pname, src)
        if found is None:
            step = _Step(self._step_id(stepname, callstep), stepname, order, s, src[0], src[1],
                         scope, pname, cond)
            step.pgm = ""
            step.missing_proc = pname
            step.parm = parm
            self.steps.append(step)
            self.cur_step = step
            self.last_call = {}
            return
        defaults, body = found
        own = dict(defaults)
        own.update(overrides)
        before = len(self.steps)
        self.active_procs.append(pname)
        self.run(body, psrc, _Scope(own, scope), pname, stepname, depth + 1)
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
            target.dds = [d for d in target.dds if d.ddname != ddname]
        elif name:
            target, ddname = self.cur_step, name
            if target is None:
                return  # JOBLIB/JOBCAT etc. before the first step
        else:
            target, ddname = self.dd_target, self.dd_last
            if target is None:
                return
        self.dd_target, self.dd_last = target, ddname
        target.dds.append(_DD(ddname, s, scope, src[0], src[1]))

    # -- emission
    def emit(self) -> Tuple[List[Node], List[Ref]]:
        nodes: List[Node] = []
        refs: List[Ref] = []
        dd_index: Dict[Tuple[str, str], Tuple[str, bool, str]] = {}
        for st in self.steps:
            self.emit_step(st, nodes, refs, dd_index)
        return nodes, refs

    def emit_step(self, st: _Step, nodes: List[Node], refs: List[Ref],
                  dd_index: Dict[Tuple[str, str], Tuple[str, bool, str]]) -> None:
        stmt = st.stmt
        assert stmt is not None
        ev = Evidence(st.repo, st.path, stmt.line, stmt.text)
        sysout: List[str] = []
        attrs = {"order": st.order, "cond": st.cond, "pgm": st.pgm or "", "proc": st.proc,
                 "sysout": sysout, "job": self.job_id}
        nodes.append(Node(st.id, "step", st.name, self.repo, [ev], attrs))

        def add(op: str, kind: str, name: Optional[str], e: Evidence, reason: Optional[str] = None,
                a: Optional[dict] = None) -> None:
            refs.append(Ref(st.id, op, kind, name, e, reason, [], a or {}))

        if st.missing_proc:
            add("runs", "program", None, ev, "PROC %s is not in these repos" % st.missing_proc)
        elif st.pgm:
            self.emit_program(st, ev, add)
        for dd in st.dds:
            self.emit_dd(st, dd, sysout, add, dd_index)

    def emit_program(self, st: _Step, ev: Evidence, add) -> None:
        pgm = st.pgm or ""
        if pgm in TSO_DRIVERS:
            found = False
            for dd in st.dds:
                if dd.ddname != "SYSTSIN":
                    continue
                for line, text in dd.stmt.data:
                    for m in _RUN_PROGRAM.finditer(text):
                        name, unres = _resolve(m.group(1).upper(), dd.scope)
                        kind = "utility" if name.upper() in UTILITIES else "program"
                        add("runs", kind, name.upper(), Evidence(dd.repo, dd.path, line, text.strip()),
                            _reason(unres))
                        found = True
            if not found:
                add("runs", "utility", pgm, ev, st.pgm_reason)
            return
        add("runs", "utility" if pgm in UTILITIES else "program", pgm, ev, st.pgm_reason)
        if pgm == "DMBATCH":
            self.emit_ndm(st, ev, add)
        elif pgm == "FTP":
            self.emit_ftp(st, ev, add)

    def emit_ndm(self, st: _Step, ev: Evidence, add) -> None:
        got = False
        for dd in st.dds:
            for line, text in dd.stmt.data:
                for m in _SNODE.finditer(text):
                    name, unres = _resolve(m.group(1), dd.scope)
                    add("transfer", "external", "NDM:" + (name if unres else name.upper()),
                        Evidence(dd.repo, dd.path, line, text.strip()), _reason(unres))
                    got = True
        if not got:
            add("transfer", "external", None, ev,
                "Connect:Direct SNODE= was not found in the in-stream input of this step")

    def emit_ftp(self, st: _Step, ev: Evidence, add) -> None:
        host, hev, reason = None, ev, None
        if st.parm:
            host = st.parm.split()[0] if st.parm.split() else None
            if host:
                host, unres = _resolve(host, st.scope)
                reason = _reason(unres)
        if not host:
            for dd in st.dds:
                if dd.ddname not in ("INPUT", "SYSIN"):
                    continue
                for line, text in dd.stmt.data:
                    toks = text.split()
                    if not toks:
                        continue
                    if toks[0].lower() == "open" and len(toks) > 1:
                        host = toks[1]
                    else:
                        host = toks[0]
                    host, unres = _resolve(host, dd.scope)
                    reason = _reason(unres)
                    hev = Evidence(dd.repo, dd.path, line, text.strip())
                    break
                if host:
                    break
        if host:
            add("transfer", "external", "FTP:" + host, hev, reason)
        else:
            add("transfer", "external", None, ev, "FTP host was not found in this step")

    def emit_dd(self, st: _Step, dd: _DD, sysout: List[str], add, dd_index) -> None:
        s = dd.stmt
        params = parse_params(s.operands)
        pos = [v.upper() for k, v in params if k is None]
        kw = {}
        for k, v in params:
            if k:
                kw.setdefault(k, v)
        if "SYSOUT" in kw:
            sysout.append("%s (SYSOUT=%s)" % (dd.ddname, kw["SYSOUT"]))
            return
        if "DUMMY" in pos or (pos and pos[0] in ("*", "DATA", "DYNAM")):
            return
        dsn = kw.get("DSN", kw.get("DSNAME"))
        if dsn is None:
            return
        ev = Evidence(dd.repo, dd.path, s.line, s.text)
        disp_raw = kw.get("DISP")
        status = _disp_status(disp_raw) if disp_raw is not None else None
        dsn = _unquote(dsn)
        referback = dsn.startswith("*.")
        reason = None
        temp = False
        gdg = None
        member = None
        if referback:
            tail = dsn[2:].upper().split(".")
            hit = dd_index.get((tail[-2], tail[-1])) if len(tail) >= 2 else None
            if hit is None:
                name = None
                reason = "backward reference %s does not match an earlier DD in this job" % dsn
            else:
                name, temp, gdg = hit
        else:
            name, unres = _resolve(dsn, dd.scope)
            reason = _reason(unres)
            if name.upper() == "NULLFILE":
                return
            m = _GDG.match(name)
            if m:
                name, gdg = m.group(1), m.group(2)
                if gdg[0].isdigit():
                    gdg = str(int(gdg))
            else:
                m = _MEMBER.match(name)
                if m:
                    name, member = m.group(1), m.group(2)
            temp = name.startswith("&&")
        if status == "SHR":
            op = "read"
        elif status in ("NEW", "MOD"):
            op = "write"
        elif status == "OLD":
            op = "update"
        else:
            op = "read" if referback else "write"
        if temp and op == "update":
            op = "read"
        a = {"ddname": dd.ddname, "disp": disp_raw, "gdg": gdg}
        if temp:
            a["temp"] = True
        if member:
            a["member"] = member
        if dd.ddname in LIBRARY_DDS:
            a["library"] = True
        if name:
            dd_index[(st.name.upper(), dd.ddname)] = (name, temp, gdg)
        add(op, "dataset", name, ev, reason, a)


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
    sc = _Scanner(repo, relpath, ctx, proc_file)
    src = (repo, relpath)
    sc.run(stmts, src, _Scope({}), None, None, 0)
    first = stmts[0] if stmts else None
    job_stmt = next((s for s in stmts if s.op == "JOB"), None)
    head = job_stmt or first
    if head is None:
        return [], []
    name = (job_stmt.name if job_stmt and job_stmt.name else _stem(relpath))
    if proc_file and first is not None and first.op == "PROC" and first.name:
        name = first.name
    node = Node(sc.job_id, "proc" if proc_file else "job", name, repo,
                [Evidence(repo, relpath, head.line, head.text)], {})
    nodes, refs = sc.emit()
    return [node] + nodes, refs


def scan_jcl(repo: str, relpath: str, text: str, ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    return _scan(repo, relpath, text, ctx, False)


def scan_proc(repo: str, relpath: str, text: str, ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    """A PROC file on its own: steps use the PROC's default symbol values."""
    return _scan(repo, relpath, text, ctx, True)
