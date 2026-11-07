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


_AMBIGUOUS = "\0ambiguous"


def collect_java(repo: str, rel: str, text: str, ctx: ScanContext) -> None:
    """Pass 1: class names (with package) defined in the repo and ``static final String``
    constants, keyed ``Class.NAME`` and, while unique in the repo, bare ``NAME``."""
    s = _Src(repo, rel, text, ctx, collecting=True)
    classes = ctx.java_classes.setdefault(repo, {})
    for c in s.classes:
        classes.setdefault(c[3], set()).add(s.qual[c[0]])
    jms = ctx.java_jms.setdefault(repo, {})
    for c in s.classes:
        ext = re.match(r"[^{]*?\bextends\s+([A-Za-z_]\w*)", s.masked[c[0]:c[1]])
        jms[c[3]] = (_jms_receivers(s.masked[c[1]:c[2]]), ext.group(1) if ext else None)
    consts = ctx.java_consts.setdefault(repo, {})
    for m in _CONST.finditer(s.clean):
        cls = s.class_at(m.start())
        if cls is None:
            continue
        consts["%s.%s" % (cls[3], m.group(1))] = m.group(2)
        have = consts.get(m.group(1))
        consts[m.group(1)] = m.group(2) if have is None or have == m.group(2) else _AMBIGUOUS


class _Src:
    """One cleaned Java file with its structure and variable table."""

    def __init__(self, repo: str, rel: str, text: str, ctx: ScanContext,
                 collecting: bool = False) -> None:
        self.repo, self.rel, self.ctx = repo, rel, ctx
        self.orig = text.split("\n")
        self.clean, self.masked = strip_code(text)
        self.lines = Lines(self.clean)
        self.props = ctx.props.get(repo, {})
        self.conflicts = ctx.props_conflicts.get(repo, {})
        self.pairs: List[Tuple[int, int, int]] = []  # (open, close, depth)
        stack: List[int] = []
        for i, ch in enumerate(self.masked):
            if ch == "{":
                stack.append(i)
            elif ch == "}" and stack:
                self.pairs.append((stack.pop(), i, len(stack)))
        self.pairs.sort()
        pk = re.search(r"^\s*package\s+([\w.]+)\s*;", self.clean, re.M)
        self.pkg = pk.group(1) if pk else ""
        self.imports = set()  # type: Set[str]
        self.wild = []  # type: List[str]
        for im in re.finditer(r"^\s*import\s+(?!static\b)([\w.]+?)(\.\*)?\s*;", self.clean, re.M):
            if im.group(2):
                self.wild.append(im.group(1))
            else:
                self.imports.add(im.group(1))
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
        self.qual: Dict[int, str] = {}
        for c in self.classes:
            chain = [x for x in self.classes if x[1] < c[1] < x[2]]
            chain.sort(key=lambda x: x[1])
            names = [x[3] for x in chain] + [c[3]]
            self.qual[c[0]] = (self.pkg + "." if self.pkg else "") + ".".join(names)
        self._params: Dict[Tuple[int, int], Set[str]] = {}
        self.vars: Dict[str, List[Tuple[Optional[Tuple[int, int]], str]]] = {}
        if not collecting:
            self._find_vars()

    # class identity ------------------------------------------------------------------
    def id_for(self, simple: str, qual: str) -> str:
        quals = self.ctx.java_classes.get(self.repo, {}).get(simple, set())
        return "class:%s/%s" % (self.repo, simple if len(quals | {qual}) == 1 else qual)

    def cid(self, c: Tuple[int, int, int, str, int]) -> str:
        return self.id_for(c[3], self.qual[c[0]])

    def resolve_type(self, t: str, off: Optional[int] = None
                     ) -> Optional[Tuple[Optional[str], List[str]]]:
        """(class id, []) for a type defined in this repo; (None, candidate ids) when two
        same-named classes cannot be told apart; None when it is not a repo class. A
        member class of an enclosing class (innermost first) wins, as in Java (B5)."""
        quals = self.ctx.java_classes.get(self.repo, {}).get(t)
        if not quals:
            return None
        if len(quals) == 1:
            return self.id_for(t, next(iter(quals))), []
        if off is not None:
            for c in sorted((c for c in self.classes if c[1] < off < c[2]),
                            key=lambda c: -c[1]):
                q = self.qual[c[0]]
                for cand in (q + "." + t, q if c[3] == t else None):
                    if cand in quals:
                        return self.id_for(t, cand), []
        for q in sorted(quals):
            if q in self.imports:
                return self.id_for(t, q), []
        same = (self.pkg + "." if self.pkg else "") + t
        if same in quals:
            return self.id_for(t, same), []
        for w in self.wild:
            if w + "." + t in quals:
                return self.id_for(t, w + "." + t), []
        return None, [self.id_for(t, q) for q in sorted(quals)]

    def params_of(self, scope: Optional[Tuple[int, int]]) -> Set[str]:
        """Names of the parameters of the method whose body is scope (an @Value parameter
        is a configuration value, not a passed-in one, so it is left out)."""
        if scope is None:
            return set()
        if scope in self._params:
            return self._params[scope]
        names: Set[str] = set()
        j = self.masked.rfind(")", 0, scope[0])
        if j >= 0 and re.fullmatch(r"\s*(?:throws[\w\s,.]*)?", self.masked[j + 1:scope[0]]):
            depth = 0
            k = j
            while k >= 0:
                ch = self.masked[k]
                depth += (ch == ")") - (ch == "(")
                if depth == 0:
                    break
                k -= 1
            for piece in split_generic(split_top(self.clean[k + 1:j], ",")):
                if piece.lstrip().startswith("@Value"):
                    continue
                pm = re.search(r"(\w+)\s*$", piece)
                if pm:
                    names.add(pm.group(1))
        self._params[scope] = names
        return names

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
        return self.cid(c) if c else None

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

    def lookup(self, chain: str, off: int) -> Tuple[Optional[str], Optional[str]]:
        """Source expression for a name: ``NAME``, ``this.NAME`` or ``Class.NAME``."""
        consts = self.ctx.java_consts.get(self.repo, {})
        parts = chain[5:].split(".") if chain.startswith("this.") else chain.split(".")
        if chain.startswith("this.") and len(parts) > 1 or (
                len(parts) > 1 and (not parts[-2][:1].isupper()
                                    or any(x[:1].isupper() for x in parts[:-2]))):
            return None, "value read from another object: %s" % chain
        if len(parts) > 1:
            got = consts.get("%s.%s" % (parts[-2], parts[-1]))  # Other.NAME looks only there
            return (got, None) if got is not None else \
                (None, "cannot work out the value of %s" % chain)
        name = parts[-1]
        scope = self.method_scope(off)
        if not chain.startswith("this.") and name in self.params_of(scope):
            return None, "value passed in as parameter %s" % name
        entries = self.vars.get(name)
        if entries:
            local = [e for e in entries if e[0] is not None and e[0] == scope]
            pool = local or [e for e in entries if e[0] is None]
            exprs = {e[1] for e in pool}
            if len(exprs) == 1:
                return pool[0][1], None
            if len(exprs) > 1:
                return None, "variable %s is assigned more than once" % name
        for c in sorted((c for c in self.classes if c[1] < off < c[2]), key=lambda c: -c[1]):
            got = consts.get("%s.%s" % (c[3], name))
            if got is not None:
                return got, None
        got = consts.get(name)
        if got is not None and got != _AMBIGUOUS:
            return got, None
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
                val, why = expand_placeholders(unescape(t[1:-1]), self.props, 0, self.conflicts)
            elif re.fullmatch(r"-?\d+", t):
                val = t
            else:
                if re.fullmatch(r"(?:\w+\.)*\w+", t):
                    e, why = self.lookup(t, off)
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


def _paths(a: str, s: _Src, off: int) -> Tuple[Optional[List[str]], Optional[str]]:
    """Paths in one annotation value; all of them must resolve or none is returned."""
    a = a.strip()
    parts = [p for p in split_top(a[1:-1], ",") if p] if a.startswith("{") and a.endswith("}") \
        else [a]
    out = []
    for p in parts:
        v, why = s.eval(p, off)
        if v is None:
            return None, "path %s not worked out: %s" % (p, why)
        out.append(v)
    return out, None


def _mapping(s: _Src, m: "re.Match[str]") -> Tuple[Optional[List[str]], List[str], Optional[str]]:
    """(paths, methods, reason) of one @XxxMapping annotation; no path means ``""``.
    paths is None, with a reason, when a path cannot be worked out."""
    kind = m.group(1)
    paths: Optional[List[str]] = [""]
    why: Optional[str] = None
    methods = [_METHOD_ANN[kind]] if kind in _METHOD_ANN else []
    if _OPEN.match(s.masked, m.end()):
        args, _ = args_at(s.clean, s.masked.find("(", m.end()))
        for k, a in enumerate(args):
            nm = _NAMED.match(a)
            if nm and nm.group(1) in ("value", "path"):
                paths, why = _paths(nm.group(2), s, m.start())
            elif nm and nm.group(1) == "method":
                methods = re.findall(r"(?:Request|Http)Method\.(\w+)", nm.group(2))
            elif not nm and k == 0:
                paths, why = _paths(a, s, m.start())
    return paths, methods or ["ANY"], why


def _method_name(s: _Src, m: "re.Match[str]") -> str:
    pos = m.end()
    if _OPEN.match(s.masked, pos):
        _, close = args_at(s.clean, s.masked.find("(", pos))
        pos = close + 1
    for mm in re.finditer(r"(?<![@\w.])(\w+)\s*\(", s.masked[pos:pos + 600]):
        return mm.group(1)
    return "method"


def _join(*parts: str) -> str:
    return "/" + "/".join(x for p in parts for x in p.split("/") if x)


# Spring settings that put every controller path under a prefix, outermost first
_SERVLET_KEYS = (("server.servlet.context-path", "server.servlet.contextPath",
                  "server.context-path", "server.contextPath"),
                 ("spring.mvc.servlet.path", "spring.mvc.servletPath"))


def _servlet_base(ctx: ScanContext, repo: str) -> Tuple[str, Optional[str]]:
    """The context path + DispatcherServlet path from the repo's config, and why it is not
    worked out (or None)."""
    props = ctx.props.get(repo, {})
    conflicts = ctx.props_conflicts.get(repo, {})
    parts: List[str] = []
    for keys in _SERVLET_KEYS:
        for k in keys:
            if k in conflicts:
                return "", "context path not worked out: %s" % conflicts[k]
            v = props.get(k)
            if v is None:
                continue
            v = str(v).strip().strip("'\"")
            if "${" in v or "\0" in v:
                return "", "context path not worked out: %s = %s" % (k, v.replace("\0", ""))
            parts.append(v)
            break
    return _join(*parts) if parts else "", None


class _Out:
    def __init__(self, s: _Src) -> None:
        self.s = s
        self.refs: List[Ref] = []
        self.seen: Set[Tuple[str, str, str, Optional[str], int]] = set()

    def add(self, off: int, op: str, kind: str, name: Optional[str],
            reason: Optional[str] = None, attrs: Optional[Dict[str, object]] = None,
            keep_reason: bool = False, candidates: Optional[List[str]] = None) -> None:
        src = self.s.class_id(off)
        if src is None:
            return
        ev = self.s.ev(off)
        key = (src, op, kind, name, ev.line)
        if key in self.seen:
            return
        self.seen.add(key)
        why = (reason or "unknown") if not name else (reason if keep_reason else None)
        self.refs.append(Ref(src, op, kind, name, ev, why, list(candidates or []),
                             attrs=attrs or {}))


# ---------------------------------------------------------------------- SQL

_KW_END = (r"(?=\b(?:WHERE|GROUP|ORDER|HAVING|UNION|LIMIT|FETCH|FOR|ON|USING|SET|"
           r"INNER|LEFT|RIGHT|FULL|CROSS|NATURAL|JOIN|WITH|VALUES|SELECT|OFFSET|"
           r"INTERSECT|EXCEPT)\b|[;)]|$)")
_TABLE = re.compile(r'^(?:"[^"]+"|`[^`]+`|[A-Za-z_#$@][\w#$@]*)'
                    r'(?:\.(?:"[^"]+"|`[^`]+`|[\w#$@]+))*$')


_FROM_STOP = re.compile(r"(?:WHERE|GROUP|ORDER|HAVING|UNION|LIMIT|FETCH|FOR|SET|WITH|VALUES|"
                        r"SELECT|OFFSET|INTERSECT|EXCEPT|RETURNING|WINDOW)\b", re.I)


def _from_parts(s: str, i: int) -> List[str]:
    """The comma-separated parts of a FROM clause starting at ``i``, split at top level, up
    to the clause's end (a closing paren, ``;`` or a keyword that ends it)."""
    parts: List[str] = []
    depth = 0
    start = i
    n = len(s)
    while i < n:
        ch = s[i]
        if ch in "'\"`":
            j = s.find(ch, i + 1)
            i = n if j < 0 else j + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                break
        elif ch == ";" and depth == 0:
            break
        elif ch == "," and depth == 0:
            parts.append(s[start:i])
            start = i + 1
        elif depth == 0 and (i == 0 or not (s[i - 1].isalnum() or s[i - 1] in "_.$#@")) \
                and _FROM_STOP.match(s, i):
            break
        i += 1
    parts.append(s[start:i])
    return parts


def sql_tables(sql: str) -> List[Tuple[str, Optional[str], str]]:
    """(op, TABLE, token) triples in one SQL statement. TABLE is None when the token is
    not a plain table name. Sub-selects and CTE names are skipped."""
    s = re.sub(r"\s+", " ", sql.strip())
    s = re.sub(r"\bFOR UPDATE\b(?: OF [\w., ]+)?", " ", s, flags=re.I)
    s = re.sub(r"\bON DUPLICATE KEY UPDATE\b", " ", s, flags=re.I)
    s = re.sub(r"\b(?:EXTRACT|TRIM|SUBSTRING|OVERLAY)\s*\([^()]*\)", " X ", s, flags=re.I)
    ctes = {m.group(1).upper() for m in re.finditer(
        r"(?:\bWITH(?:\s+RECURSIVE)?|,)\s*(\w+)\s*(?:\([^)]*\)\s*)?AS\s*\(", s, re.I)}
    found: List[Tuple[str, Optional[str], str]] = []

    def take(op: str, tok: str) -> None:
        if not tok or tok[0] == "(":
            return
        name = tok.replace('"', "").replace("`", "").upper()
        if not _TABLE.match(tok):
            found.append((op, None, tok))
        elif name not in ctes and (op, name, tok) not in found:
            found.append((op, name, tok))

    for m in re.finditer(r"\bINSERT\s+(?:INTO\s+)?([^\s(]+)", s, re.I):
        take("insert", m.group(1))
    for m in re.finditer(r"\bMERGE\s+INTO\s+([^\s(]+)", s, re.I):
        take("update", m.group(1))
    for m in re.finditer(r"(?<![\w.])UPDATE\s+([^\s(;]+)", s, re.I):
        take("update", m.group(1))
    for m in re.finditer(r"\bDELETE\s+FROM\s+([^\s(;]+)", s, re.I):
        take("delete", m.group(1))
    for m in re.finditer(r"\bFROM\s+", s, re.I):
        if re.search(r"\bDELETE\s*$", s[:m.start()], re.I):
            continue
        # every top-level comma part of the FROM clause, also one after a JOIN ... ON (B4)
        for part in _from_parts(s, m.end()):
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
    for op, table, tok in sql_tables(sql):
        out.add(off, op, "table", table, "table name %s is not a plain name" % tok)


# ---------------------------------------------------------------------- queues

_JMS = re.compile(r"\b(\w+)\s*\.\s*(convertAndSend|send|receive|receiveAndConvert|"
                  r"receiveSelected|receiveSelectedAndConvert)\s*\(")
_HTTP_CALLS = {
    "getForObject": "GET", "getForEntity": "GET", "postForObject": "POST",
    "postForEntity": "POST", "postForLocation": "POST", "patchForObject": "PATCH",
    "headForHeaders": "HEAD", "optionsForAllow": "OPTIONS", "put": "PUT", "delete": "DELETE",
}


_JMS_TYPES = re.compile(r"\b(?:JmsTemplate|JmsOperations|JmsMessagingTemplate|JMSContext|"
                        r"JMSProducer|MessageProducer|MessageConsumer|QueueReceiver|QueueSender|"
                        r"MQQueue)\s*(?:<[^>]*>)?\s+(\w+)")


def _jms_receivers(masked: str) -> Set[str]:
    """Names of fields, parameters and variables typed as a JMS sender / receiver."""
    return {m.group(1) for m in _JMS_TYPES.finditer(masked)}


def _inherited_jms(table: Dict[str, Tuple[Set[str], Optional[str]]], cls: str) -> Set[str]:
    """JMS field names a class gets from superclasses declared in the same repo."""
    out: Set[str] = set()
    cur = table.get(cls, (set(), None))[1]
    for _ in range(10):
        if cur is None or cur not in table:
            break
        out |= table[cur][0]
        cur = table[cur][1]
    return out


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


_ECI_ARITIES = (7, 9, 10)
# the call type: a number or an ECI_* constant (ECI_SYNC, ECIRequest.ECI_SYNC, ...)
_ECI_CALL_TYPE = re.compile(r"\d+|(?:[A-Za-z_]\w*\.)*ECI_\w+")


def scan_java(repo: str, rel: str, text: str, ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    s = _Src(repo, rel, text, ctx)
    nodes: List[Node] = []
    out = _Out(s)
    for c in s.classes:
        nodes.append(Node(s.cid(c), "class", c[3], repo, [s.ev(c[0])],
                          {"package": s.pkg or None}))

    # endpoints (controllers) and REST calls declared by Feign interfaces --------------
    for c in s.classes:
        decl, o, close, name, hdr = c
        header = s.masked[hdr:decl]
        is_ctrl = bool(re.search(r"@(RestController|Controller)\b", header))
        feign = re.search(r"@FeignClient\b", header)
        if not (is_ctrl or feign):
            continue
        cid = s.cid(c)
        prefixes: Optional[List[str]] = [""]
        prefix_why: Optional[str] = None
        for m in _MAPPING.finditer(s.masked, hdr, decl):
            if m.group(1) == "Request":
                prefixes, _, prefix_why = _mapping(s, m)
        if is_ctrl:
            sbase, sbase_why = _servlet_base(ctx, repo)
            if sbase_why is not None:
                prefixes, prefix_why = None, sbase_why
            elif sbase and prefixes is not None:
                prefixes = [_join(sbase, p) for p in prefixes]
        base_url: Optional[str] = None
        base_why: Optional[str] = None
        fpath = ""
        if feign and _OPEN.match(s.masked, hdr + feign.end()):
            fargs, _ = args_at(s.clean, s.masked.find("(", hdr + feign.end()))
            for a in fargs:
                nm = _NAMED.match(a)
                if nm and nm.group(1) in ("url", "path"):
                    v, why = s.eval(nm.group(2), hdr + feign.start())
                    if v is None:
                        base_why = "Feign %s not worked out: %s" % (nm.group(1), why)
                    elif nm.group(1) == "path":
                        fpath = v
                    else:
                        base_url = v
        for m in _MAPPING.finditer(s.masked, o + 1, close):
            cls = s.class_at(m.start())
            if cls is None or cls[0] != decl:
                continue
            paths, methods, why = _mapping(s, m)
            if not is_ctrl:
                if base_why is not None or paths is None:
                    out.add(m.start(), "http", "endpoint", None, base_why or why)
                    continue
                for meth in methods:
                    for pth in paths:
                        full = _join(fpath, pth)
                        url = (base_url.rstrip("/") + full) if base_url else full
                        out.add(m.start(), "http", "endpoint", "%s %s" % (meth, url))
                continue
            if paths is None or prefixes is None:
                reason = why if paths is None else "class path prefix not worked out: %s" % prefix_why
                mname = _method_name(s, m)
                uid = "endpoint:?%s#%s" % (cid[len("class:"):], mname)
                nodes.append(Node(uid, "endpoint", "?%s#%s" % (name, mname), repo,
                                  [s.ev(m.start())],
                                  {"handler": cid, "unresolved": reason}))
                continue
            for meth in methods:
                for pre in prefixes:
                    for pth in paths:
                        full = _join(pre, pth)
                        label = "%s %s" % (meth, norm_path(full))
                        nodes.append(Node("endpoint:" + label, "endpoint", label, repo,
                                          [s.ev(m.start())], {"handler": cid, "path": full}))

    # uses: constructor parameters and injected fields of classes in this repo --------
    for c in s.classes:
        decl, o, close, name, hdr = c
        types: List[Tuple[str, int]] = []
        for m in re.finditer(r"(?<![\w.])%s\s*\(" % re.escape(name), s.masked[:close]):
            if m.start() < o or re.search(r"new\s+$", s.masked[max(0, m.start() - 6):m.start()]):
                continue
            cls = s.class_at(m.start())
            if cls is None or cls[0] != decl:
                continue
            params, pclose = args_at(s.clean, m.end() - 1)
            if not re.match(r"\s*(?:throws\s+[\w.,\s]+)?\{", s.masked[pclose + 1:pclose + 120]):
                continue
            for p in split_generic(params):
                t = param_type(p)
                if t:
                    types.append((t, m.start()))
        lombok = re.search(r"@(RequiredArgsConstructor|AllArgsConstructor)\b",
                           s.masked[hdr:decl])
        for m in re.finditer(r"((?:@\w+(?:\([^)]*\))?\s+)*)(?:(?:private|protected|public|final)\s+)*"
                             r"([A-Z]\w*)\s+\w+\s*(=[^;]*)?;", s.masked[o + 1:close]):
            cls = s.class_at(o + 1 + m.start())
            if cls is None or cls[0] != decl:
                continue
            member = re.search(r"@(Autowired|Inject|Resource)\b", m.group(1))
            lfinal = (lombok and re.search(r"\bfinal\b", m.group(0))
                      and not m.group(3) and "static" not in m.group(0))
            if member or lfinal:
                types.append((m.group(2), o + 1 + m.start()))
        done: Set[str] = set()
        for t, off in types:
            got = s.resolve_type(t, off)
            if got is None:
                continue
            tid, cands = got
            if tid == s.cid(c) or (tid or t) in done:
                continue
            done.add(tid or t)
            if tid is None:
                src = s.cid(c)
                out.refs.append(Ref(src, "uses", "class", None, s.ev(off),
                                    "class %s matches more than one class in the repo" % t,
                                    cands))
            else:
                out.add(off, "uses", "class", tid[len("class:"):])

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
        elif url.startswith("/") and len(base_urls) != 1:
            # a path with no single base URL in the file: the host is not known (B4)
            out.add(m.start(), "http", "endpoint", "%s %s" % (meth, url),
                    "base URL not worked out (%s)" % (
                        "baseUrl set %d times in this file" % len(base_urls) if base_urls
                        else "no baseUrl in this file"), keep_reason=True)
        else:
            out.add(m.start(), "http", "endpoint", "%s %s" % (meth, url))

    # queues -----------------------------------------------------------------------------------
    jms_file = _jms_receivers(s.masked)
    for m in _JMS.finditer(s.masked):
        cls = s.class_at(m.start())
        if m.group(1) not in jms_file and not (
                cls and m.group(1) in _inherited_jms(ctx.java_jms.get(repo, {}), cls[3])):
            continue
        op = "put" if m.group(2) in ("convertAndSend", "send") else "get"
        args, _ = args_at(s.clean, m.end() - 1)
        if not args or (m.group(2) in ("send", "convertAndSend") and len(args) == 1):
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
        if ops:
            for op in ops:
                out.add(m.start(), op, "queue", q, why)
        else:
            out.add(m.start(), "open", "queue", q, why or "queue open mode not worked out",
                    keep_reason=True)

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
        # the CTG constructors that take a program: (callType, server, userid, password,
        # program, transid, commarea|channel [, length, extend mode, LUW token]) - 7, 9 or
        # 10 arguments, the call type a number or constant; any other shape is not trusted
        if len(args) not in _ECI_ARITIES or not _ECI_CALL_TYPE.fullmatch(args[0].strip()):
            lits = sorted(set(v.strip().upper() for v in (
                s.eval(a, m.start())[0] for a in args
                if re.fullmatch(r'\s*"(?:[^"\\]|\\.)*"\s*', a)) if v and v.strip()))
            out.add(m.start(), "ctg_call", "program", None,
                    "ECIRequest constructor with %d argument(s) is not a known shape; "
                    "program not worked out" % len(args), candidates=lits)
            continue
        prog, why = s.eval(args[4], m.start())
        if prog is not None and prog.strip():
            out.add(m.start(), "ctg_call", "program", prog.strip().upper())
        else:
            out.add(m.start(), "ctg_call", "program", None,
                    "program name not worked out: %s" % (why or "empty"))
    return nodes, out.refs
