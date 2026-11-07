"""Java: classes, Spring endpoints, and the links a class makes (calls to other classes,
REST calls, queues, SQL tables, CICS Transaction Gateway programs).

Facts come from regexes over comment-stripped source. A URL, queue or table name that
cannot be worked out from the code gives a Ref with ``target_name=None`` and a reason,
never a guess. A variable resolves only through its one assignment in the same method,
or its field / ``@Value`` / ``static final`` definition.

Class references use ``target_name = "<repo>/<Simple>"`` so the id is ``class:<repo>/<Simple>``.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from ..model import Evidence, Node, Ref
from ..resolve.names import norm_path
from . import ScanContext
from .lexutil import (Lines, args_at, expand_placeholders, make_ev, split_top,
                      strip_code, unescape)

_CLASS_DECL = re.compile(r"(?<![\w.@])(class|interface|enum|record)\s+([A-Za-z_]\w*)")
_METHOD_ANN = {"Get": "GET", "Post": "POST", "Put": "PUT", "Delete": "DELETE",
               "Patch": "PATCH"}
_MAPPING = re.compile(r"@(Get|Post|Put|Delete|Patch|Request)Mapping\b")
_CONST = re.compile(
    r"\bstatic\s+final\s+String\s+([A-Za-z_]\w*)\s*=\s*(\"(?:[^\"\\\n]|\\.)*\")\s*;")
_NAMED = re.compile(r"(\w+)\s*=(?!=)\s*(.*)$", re.S)
_OPEN = re.compile(r"\s*\(")


def _read_expr(clean: str, i: int) -> str:
    """Text from i up to the next top-level ';' (string aware)."""
    n = len(clean)
    j = i
    depth = 0
    while j < n:
        ch = clean[j]
        if ch == '"':
            j += 1
            while j < n and clean[j] != '"':
                j += 2 if clean[j] == "\\" else 1
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                break
        elif ch == ";" and depth == 0:
            break
        j += 1
    return clean[i:j].strip()


def collect_java(repo: str, rel: str, text: str, ctx: ScanContext) -> None:
    """Pass 1: class names defined in the repo and ``static final String`` constants."""
    clean, masked = strip_code(text)
    classes = ctx.java_classes.setdefault(repo, set())
    for m in _CLASS_DECL.finditer(masked):
        classes.add(m.group(2))
    consts = ctx.java_consts.setdefault(repo, {})
    for m in _CONST.finditer(clean):
        consts.setdefault(m.group(1), m.group(2))


class _Src:
    """One cleaned Java file with its structure and variable table."""

    def __init__(self, repo: str, rel: str, text: str, ctx: ScanContext) -> None:
        self.repo, self.rel, self.ctx = repo, rel, ctx
        self.orig = text.split("\n")
        self.clean, self.masked = strip_code(text)
        self.lines = Lines(self.clean)
        self.props = ctx.props.get(repo, {})
        self.pairs: List[Tuple[int, int, int]] = []  # (open, close, depth)
        stack: List[int] = []
        for i, ch in enumerate(self.masked):
            if ch == "{":
                stack.append(i)
            elif ch == "}" and stack:
                self.pairs.append((stack.pop(), i, len(stack)))
        self.pairs.sort()
        # (declaration start, open brace, close brace, name, header start)
        self.classes: List[Tuple[int, int, int, str, int]] = []
        close_of = {o: c for o, c, _ in self.pairs}
        for m in _CLASS_DECL.finditer(self.masked):
            o = self.masked.find("{", m.end())
            if o < 0 or ";" in self.masked[m.end():o]:
                continue
            hdr = max(self.masked.rfind(c, 0, m.start()) for c in ";{}") + 1
            self.classes.append((m.start(), o, close_of.get(o, len(self.masked)),
                                 m.group(2), hdr))
        self.vars: Dict[str, List[Tuple[Optional[Tuple[int, int]], str]]] = {}
        self._find_vars()

    def class_at(self, off: int) -> Optional[Tuple[int, int, int, str, int]]:
        best = None
        for c in self.classes:
            if c[1] < off < c[2] and (best is None or c[1] > best[1]):
                best = c
        return best

    def method_scope(self, off: int) -> Optional[Tuple[int, int]]:
        """The body one brace level inside the enclosing class that contains off."""
        cls = self.class_at(off)
        if cls is None:
            return None
        depth = next((d for o, _, d in self.pairs if o == cls[1]), 0)
        for o, c, d in self.pairs:
            if d == depth + 1 and o < off < c:
                return (o, c)
        return None

    def class_id(self, off: int) -> Optional[str]:
        c = self.class_at(off)
        return "class:%s/%s" % (self.repo, c[3]) if c else None

    def ev(self, off: int) -> Evidence:
        return make_ev(self.repo, self.rel, self.orig, self.lines.line_of(off))

    # variables -------------------------------------------------------------------
    def _find_vars(self) -> None:
        c = self.clean
        for m in re.finditer(r'@Value\s*\(\s*("(?:[^"\\\n]|\\.)*")\s*\)\s*'
                             r'(?:(?:private|public|protected|final|static|volatile)\s+)*'
                             r'String\s+(\w+)', c):
            if self.masked[m.start()] == "@":  # a real annotation, not text in a string
                self.vars.setdefault(m.group(2), []).append((None, m.group(1)))
        for m in re.finditer(r'(?<![\w.])String\s+(\w+)\s*=(?!=)', self.masked):
            self.vars.setdefault(m.group(1), []).append(
                (self.method_scope(m.start()), _read_expr(c, m.end())))
        for m in re.finditer(r'(?<![\w.])(?<!String )(\w+)\s*(\+=|=(?!=))', self.masked):
            if m.group(1) in self.vars:  # a later assignment makes the value ambiguous
                self.vars[m.group(1)].append(
                    (self.method_scope(m.start()), "\0reassigned" + str(m.start())))
        for m in re.finditer(r'(?<![\w.])(\w+)\s*=(?!=)\s*new\s+\w*Queue\s*\(', self.masked):
            a, _ = args_at(c, m.end() - 1)
            if a:
                self.vars.setdefault(m.group(1), []).append(
                    (self.method_scope(m.start()), a[-1]))

    def lookup(self, name: str, off: int) -> Tuple[Optional[str], Optional[str]]:
        entries = self.vars.get(name)
        if entries:
            scope = self.method_scope(off)
            local = [e for e in entries if e[0] is not None and e[0] == scope]
            pool = local or [e for e in entries if e[0] is None]
            exprs = {e[1] for e in pool}
            if len(exprs) == 1:
                return pool[0][1], None
            if len(exprs) > 1:
                return None, "variable %s is assigned more than once" % name
        const = self.ctx.java_consts.get(self.repo, {}).get(name)
        if const is not None:
            return const, None
        return None, "cannot work out the value of %s" % name

    # expressions ---------------------------------------------------------------------
    def eval(self, expr: str, off: int, url: bool = False,
             depth: int = 0) -> Tuple[Optional[str], Optional[str]]:
        """Value of a string expression (literals, ``+``, variables, constants, ``${prop}``).
        In ``url`` mode an unknown term right after a ``/`` or ``=`` becomes ``{}``."""
        expr = expr.strip()
        if depth > 8 or not expr:
            return None, "cannot work out '%s'" % expr
        out = ""
        for term in split_top(expr, "+"):
            t = term.strip()
            while t.startswith("(") and t.endswith(")") and _balanced(t[1:-1]):
                t = t[1:-1].strip()
            val: Optional[str] = None
            why: Optional[str] = None
            if len(split_top(t, "+")) > 1:
                val, why = self.eval(t, off, url, depth + 1)
            elif re.fullmatch(r'"(?:[^"\\\n]|\\.)*"', t):
                val, why = expand_placeholders(unescape(t[1:-1]), self.props)
            elif re.fullmatch(r"-?\d+", t):
                val = t
            else:
                m = re.fullmatch(r"(?:this\.)?(\w+)|(?:\w+\.)+([A-Z_]\w*)", t)
                if m:
                    e, why = self.lookup(m.group(1) or m.group(2), off)
                    if e is not None:
                        val, why = self.eval(e, off, url, depth + 1)
                else:
                    why = "cannot work out '%s'" % t
            if val is None:
                if why and why.startswith("property "):
                    return None, why
                if url and out.endswith(("/", "=")):
                    out += "{}"
                    continue
                return None, why or "cannot work out '%s'" % t
            out += val
        return out, None


def _balanced(s: str) -> bool:
    d = 0
    for ch in s:
        if ch == "(":
            d += 1
        elif ch == ")":
            d -= 1
            if d < 0:
                return False
    return d == 0


def _paths(a: str, s: _Src, off: int) -> List[str]:
    a = a.strip()
    parts = [p for p in split_top(a[1:-1], ",") if p] if a.startswith("{") and a.endswith("}") \
        else [a]
    out = []
    for p in parts:
        v, _ = s.eval(p, off)
        if v is not None:
            out.append(v)
    return out


def _mapping(s: _Src, m: "re.Match[str]") -> Tuple[List[str], List[str]]:
    """(paths, methods) of one @XxxMapping annotation; no path means ``""``."""
    kind = m.group(1)
    paths: List[str] = [""]
    methods = [_METHOD_ANN[kind]] if kind in _METHOD_ANN else []
    if _OPEN.match(s.masked, m.end()):
        args, _ = args_at(s.clean, s.masked.find("(", m.end()))
        for k, a in enumerate(args):
            nm = _NAMED.match(a)
            if nm and nm.group(1) in ("value", "path"):
                paths = _paths(nm.group(2), s, m.start()) or paths
            elif nm and nm.group(1) == "method":
                methods = [x for x in re.findall(r"(?:Request|Http)Method\.(\w+)", nm.group(2))]
            elif not nm and k == 0:
                paths = _paths(a, s, m.start()) or paths
    return paths, methods or ["ANY"]


def _join(*parts: str) -> str:
    return "/" + "/".join(x for p in parts for x in p.split("/") if x)


class _Out:
    def __init__(self, s: _Src) -> None:
        self.s = s
        self.refs: List[Ref] = []
        self.seen: Set[Tuple[str, str, str, Optional[str], int]] = set()

    def add(self, off: int, op: str, kind: str, name: Optional[str],
            reason: Optional[str] = None, attrs: Optional[Dict[str, object]] = None) -> None:
        src = self.s.class_id(off)
        if src is None:
            return
        ev = self.s.ev(off)
        key = (src, op, kind, name, ev.line)
        if key in self.seen:
            return
        self.seen.add(key)
        self.refs.append(Ref(src, op, kind, name, ev, None if name else (reason or "unknown"),
                             attrs=attrs or {}))


# ---------------------------------------------------------------------- SQL

_KW_END = (r"(?=\b(?:WHERE|GROUP|ORDER|HAVING|UNION|LIMIT|FETCH|FOR|ON|USING|SET|"
           r"INNER|LEFT|RIGHT|FULL|CROSS|NATURAL|JOIN|WITH|VALUES|SELECT|OFFSET|"
           r"INTERSECT|EXCEPT)\b|[;)]|$)")
_TABLE = re.compile(r'^(?:"[^"]+"|`[^`]+`|[A-Za-z_#$@][\w#$@]*)'
                    r'(?:\.(?:"[^"]+"|`[^`]+`|[\w#$@]+))*$')


def sql_tables(sql: str) -> List[Tuple[str, str]]:
    """(op, TABLE) pairs in one SQL statement. Sub-selects and CTE names are skipped."""
    s = re.sub(r"\s+", " ", sql.strip())
    s = re.sub(r"\bFOR UPDATE\b(?: OF [\w., ]+)?", " ", s, flags=re.I)
    s = re.sub(r"\bON DUPLICATE KEY UPDATE\b", " ", s, flags=re.I)
    s = re.sub(r"\b(?:EXTRACT|TRIM|SUBSTRING|OVERLAY)\s*\([^()]*\)", " X ", s, flags=re.I)
    ctes = {m.group(1).upper() for m in re.finditer(
        r"(?:\bWITH(?:\s+RECURSIVE)?|,)\s*(\w+)\s*(?:\([^)]*\)\s*)?AS\s*\(", s, re.I)}
    found: List[Tuple[str, str]] = []

    def take(op: str, tok: str) -> None:
        name = tok.replace('"', "").replace("`", "").upper()
        if _TABLE.match(tok) and name not in ctes and (op, name) not in found:
            found.append((op, name))

    for m in re.finditer(r"\bINSERT\s+(?:INTO\s+)?([^\s(]+)", s, re.I):
        take("insert", m.group(1))
    for m in re.finditer(r"\bMERGE\s+INTO\s+([^\s(]+)", s, re.I):
        take("update", m.group(1))
    for m in re.finditer(r"(?<![\w.])UPDATE\s+([^\s(;]+)", s, re.I):
        take("update", m.group(1))
    for m in re.finditer(r"\bDELETE\s+FROM\s+([^\s(;]+)", s, re.I):
        take("delete", m.group(1))
    for m in re.finditer(r"\bFROM\s+(.*?)" + _KW_END, s, re.I):
        if re.search(r"\bDELETE\s*$", s[:m.start()], re.I):
            continue
        for part in m.group(1).split(","):
            tok = part.strip().split(" ")[0]
            if tok:
                take("select", tok)
    for m in re.finditer(r"\bJOIN\s+([^\s(]+)", s, re.I):
        take("select", m.group(1))
    return found


_JDBC = re.compile(
    r"\b(\w+)\s*\.\s*(queryForObject|queryForList|queryForMap|queryForRowSet|queryForStream|"
    r"query|batchUpdate|update|execute|prepareStatement|prepareCall|createNativeQuery|"
    r"createSQLQuery)\s*\(")
_STATEMENT = re.compile(r"\s*\(?\s*(SELECT|INSERT|UPDATE|DELETE|MERGE|WITH|CALL|TRUNCATE|VALUES)\b",
                        re.I)


def _sql_ref(s: _Src, out: _Out, off: int, expr: str, default_op: str) -> None:
    sql, why = s.eval(expr, off)
    if sql is None:
        out.add(off, default_op, "table", None,
                "SQL text is not a literal or constant (%s)" % (why or "unknown"))
        return
    if not _STATEMENT.match(sql):
        return
    for op, table in sql_tables(sql):
        out.add(off, op, "table", table)


# ---------------------------------------------------------------------- queues

_JMS = re.compile(r"\b(\w+)\s*\.\s*(convertAndSend|send|receive|receiveAndConvert|"
                  r"receiveSelected|receiveSelectedAndConvert)\s*\(")
_HTTP_CALLS = {
    "getForObject": "GET", "getForEntity": "GET", "postForObject": "POST",
    "postForEntity": "POST", "postForLocation": "POST", "patchForObject": "PATCH",
    "headForHeaders": "HEAD", "optionsForAllow": "OPTIONS", "put": "PUT", "delete": "DELETE",
}


def _is_jms_receiver(name: str, text: str) -> bool:
    if re.search(r"jms|mq", name, re.I):
        return True
    return bool(re.search(r"import\s+(?:org\.springframework\.jms|javax\.jms|jakarta\.jms)",
                          text)) and not re.search(r"import\s+[\w.]*amqp", text)


def split_generic(params: List[str]) -> List[str]:
    """Re-join parameters broken at the comma inside ``Map<String, Foo>``."""
    out: List[str] = []
    cur = ""
    for p in params:
        cur = (cur + ", " + p) if cur else p
        if cur.count("<") <= cur.count(">"):
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def param_type(p: str) -> Optional[str]:
    p = re.sub(r"@\w+(?:\([^)]*\))?\s*", "", p).strip()
    p = re.sub(r"\bfinal\s+", "", p)
    m = re.match(r"([A-Za-z_][\w.]*)\s+\w+$", p)
    return m.group(1).split(".")[-1] if m else None


def scan_java(repo: str, rel: str, text: str, ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    s = _Src(repo, rel, text, ctx)
    nodes: List[Node] = []
    out = _Out(s)
    known = ctx.java_classes.get(repo, set())
    pkg = re.search(r"^\s*package\s+([\w.]+)\s*;", s.clean, re.M)
    for decl, o, c, name, hdr in s.classes:
        nodes.append(Node("class:%s/%s" % (repo, name), "class", name, repo, [s.ev(decl)],
                          {"package": pkg.group(1) if pkg else None}))

    # endpoints (controllers) and REST calls declared by Feign interfaces --------------
    for decl, o, c, name, hdr in s.classes:
        header = s.masked[hdr:decl]
        is_ctrl = bool(re.search(r"@(RestController|Controller)\b", header))
        feign = re.search(r"@FeignClient\b", header)
        if not (is_ctrl or feign):
            continue
        prefixes = [""]
        for m in _MAPPING.finditer(s.masked, hdr, decl):
            if m.group(1) == "Request":
                prefixes = _mapping(s, m)[0]
        base_url: Optional[str] = None
        base_why: Optional[str] = None
        fpath = ""
        if feign and _OPEN.match(s.masked, hdr + feign.end()):
            fargs, _ = args_at(s.clean, s.masked.find("(", hdr + feign.end()))
            for a in fargs:
                nm = _NAMED.match(a)
                if nm and nm.group(1) in ("url", "path"):
                    v, why = s.eval(nm.group(2), hdr + feign.start())
                    if nm.group(1) == "path":
                        fpath = v or ""
                    elif v is not None:
                        base_url = v
                    else:
                        base_why = why
        for m in _MAPPING.finditer(s.masked, o + 1, c):
            cls = s.class_at(m.start())
            if cls is None or cls[3] != name:
                continue
            paths, methods = _mapping(s, m)
            for meth in methods:
                for pre in (prefixes if is_ctrl else [fpath]):
                    for pth in paths:
                        full = _join(pre, pth)
                        if is_ctrl:
                            label = "%s %s" % (meth, norm_path(full))
                            nodes.append(Node("endpoint:" + label, "endpoint", label, repo,
                                              [s.ev(m.start())],
                                              {"handler": "class:%s/%s" % (repo, name),
                                               "path": full}))
                        elif base_why is not None:
                            out.add(m.start(), "http", "endpoint", None,
                                    "Feign client url not worked out: %s" % base_why)
                        else:
                            url = (base_url.rstrip("/") + full) if base_url else full
                            out.add(m.start(), "http", "endpoint", "%s %s" % (meth, url))

    # uses: constructor parameters and injected fields of classes in this repo --------
    for decl, o, c, name, hdr in s.classes:
        types: List[Tuple[str, int]] = []
        for m in re.finditer(r"(?<![\w.])%s\s*\(" % re.escape(name), s.masked[:c], ):
            if m.start() < o or re.search(r"new\s+$", s.masked[max(0, m.start() - 6):m.start()]):
                continue
            params, close = args_at(s.clean, m.end() - 1)
            if not re.match(r"\s*(?:throws\s+[\w.,\s]+)?\{", s.masked[close + 1:close + 120]):
                continue
            for p in split_generic(params):
                t = param_type(p)
                if t:
                    types.append((t, m.start()))
        lombok = re.search(r"@(RequiredArgsConstructor|AllArgsConstructor)\b",
                           s.masked[hdr:decl])
        for m in re.finditer(r"((?:@\w+(?:\([^)]*\))?\s+)*)(?:(?:private|protected|public|final)\s+)*"
                             r"([A-Z]\w*)\s+\w+\s*(=[^;]*)?;", s.masked[o + 1:c]):
            member = re.search(r"@(Autowired|Inject|Resource)\b", m.group(1))
            lfinal = (lombok and re.search(r"\bfinal\b", m.group(0))
                      and not m.group(3) and "static" not in m.group(0))
            if member or lfinal:
                types.append((m.group(2), o + 1 + m.start()))
        done: Set[str] = set()
        for t, off in types:
            if t in known and t != name and t not in done:
                done.add(t)
                out.add(off, "uses", "class", "%s/%s" % (repo, t))

    # REST calls ----------------------------------------------------------------------------
    for m in re.finditer(r"\.\s*(getForObject|getForEntity|postForObject|postForEntity|"
                         r"postForLocation|patchForObject|headForHeaders|optionsForAllow|"
                         r"exchange|execute|put|delete)\s*\(", s.masked):
        name = m.group(1)
        recv = re.search(r"(\w+)\s*$", s.masked[max(0, m.start() - 40):m.start()])
        args, _ = args_at(s.clean, m.end() - 1)
        if not args:
            continue
        if name in ("put", "delete", "execute") and not (
                recv and re.search(r"rest", recv.group(1), re.I)):
            continue  # Map.put, Set.delete, ... are not REST calls
        meth = _HTTP_CALLS.get(name)
        if name in ("exchange", "execute"):
            hm = re.search(r"HttpMethod\.(\w+)", ",".join(args[:2]))
            meth = hm.group(1).upper() if hm else None
            if name == "exchange" and not hm and "RequestEntity" not in args[0]:
                continue  # some other exchange(...)
        url, why = s.eval(args[0], m.start(), url=True)
        if url is None:
            out.add(m.start(), "http", "endpoint", None, "URL not worked out: %s" % why)
        elif meth is None:
            out.add(m.start(), "http", "endpoint", None, "HTTP method not worked out")
        else:
            out.add(m.start(), "http", "endpoint", "%s %s" % (meth, url))

    base_urls = list(re.finditer(r"\.\s*baseUrl\s*\(", s.masked))
    for m in re.finditer(r"\.\s*(get|post|put|delete|patch|head|options)\s*\(\s*\)\s*\.\s*"
                         r"uri\s*\(|\.\s*method\s*\(\s*HttpMethod\.(\w+)\s*\)\s*\.\s*uri\s*\(",
                         s.masked):
        meth = (m.group(1) or m.group(2)).upper()
        args, _ = args_at(s.clean, m.end() - 1)
        if not args:
            continue
        url, why = s.eval(args[0], m.start(), url=True)
        if url is not None and url.startswith("/") and len(base_urls) == 1:
            bargs, _ = args_at(s.clean, base_urls[0].end() - 1)
            b, bwhy = s.eval(bargs[0], base_urls[0].start()) if bargs else (None, "no value")
            if b is None:
                out.add(m.start(), "http", "endpoint", None,
                        "base URL not worked out: %s" % bwhy)
                continue
            url = b.rstrip("/") + url
        if url is None:
            out.add(m.start(), "http", "endpoint", None, "URL not worked out: %s" % why)
        else:
            out.add(m.start(), "http", "endpoint", "%s %s" % (meth, url))

    # queues -----------------------------------------------------------------------------------
    for m in _JMS.finditer(s.masked):
        if not _is_jms_receiver(m.group(1), s.clean):
            continue
        op = "put" if m.group(2) in ("convertAndSend", "send") else "get"
        args, _ = args_at(s.clean, m.end() - 1)
        if not args or (m.group(2) == "send" and len(args) == 1):
            out.add(m.start(), op, "queue", None, "default destination, queue name not in code")
            continue
        q, why = s.eval(args[0], m.start())
        out.add(m.start(), op, "queue", q, why)
    for m in re.finditer(r"@JmsListener\b", s.masked):
        if not _OPEN.match(s.masked, m.end()):
            continue
        args, _ = args_at(s.clean, s.masked.find("(", m.end()))
        for a in args:
            nm = _NAMED.match(a)
            if nm and nm.group(1) == "destination":
                q, why = s.eval(nm.group(2), m.start())
                out.add(m.start(), "get", "queue", q, why)
    for m in re.finditer(r"\baccessQueue\s*\(", s.masked):
        args, _ = args_at(s.clean, m.end() - 1)
        if not args:
            continue
        q, why = s.eval(args[0], m.start())
        opts = " ".join(args[1:])
        ops = [o for o, pat in (("put", "OUTPUT"), ("get", "INPUT")) if pat in opts]
        for op in ops or ["put", "get"]:
            out.add(m.start(), op, "queue", q, why, None if ops else {"op_unclear": True})

    # SQL ----------------------------------------------------------------------------------------
    for m in _JDBC.finditer(s.masked):
        name, recv = m.group(2), m.group(1)
        if name in ("query", "update", "execute", "batchUpdate") and not re.search(
                r"jdbc|sql|db|dao", recv, re.I):
            continue
        args, _ = args_at(s.clean, m.end() - 1)
        if args:
            _sql_ref(s, out, m.start(), args[0], "select" if name.startswith("query") else "update")
    for m in re.finditer(r"@Query\b", s.masked):
        if not _OPEN.match(s.masked, m.end()):
            continue
        args, _ = args_at(s.clean, s.masked.find("(", m.end()))
        if not any(re.fullmatch(r"nativeQuery\s*=\s*true", a) for a in args):
            continue
        for k, a in enumerate(args):
            nm = _NAMED.match(a)
            if (nm and nm.group(1) == "value") or (not nm and k == 0):
                _sql_ref(s, out, m.start(), nm.group(2) if nm else a, "select")

    # CICS Transaction Gateway --------------------------------------------------------------------
    for m in re.finditer(r"(?<![\w.])ECIRequest\s*\(", s.masked):
        args, _ = args_at(s.clean, m.end() - 1)
        if len(args) < 5:
            out.add(m.start(), "ctg_call", "program", None,
                    "ECIRequest program argument not found")
            continue
        prog, why = s.eval(args[4], m.start())
        if prog is not None and prog.strip():
            out.add(m.start(), "ctg_call", "program", prog.strip().upper())
        else:
            out.add(m.start(), "ctg_call", "program", None,
                    "program name not worked out: %s" % (why or "empty"))
    return nodes, out.refs
