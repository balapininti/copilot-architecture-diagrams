"""Angular (TypeScript): components and injectable services, router pages, and the HTTP
calls a class makes.

``component:<repo>/<Class>`` for ``@Component`` / ``@Injectable`` classes (and for any
other class that makes an HTTP call, so its Ref has a source node). ``page:<repo>/<path>``
for each route that names a component. A URL is built from literals, template strings,
``+``, constants in the same file and ``environment.*`` values (``ctx.ts_env``). A part
that is a plain run-time value (``${id}``) stays as ``${id}`` when it follows a ``/``;
a URL whose start cannot be worked out gives ``target_name=None`` and a reason.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from ..model import Evidence, Node, Ref
from . import ScanContext
from .lexutil import Lines, args_at, make_ev, split_top, strip_code, unescape

_DECORATED = re.compile(r"@(Component|Injectable)\b")
_CLASS = re.compile(r"(?<![\w.])class\s+([A-Za-z_$][\w$]*)")
_ENDS_HTTP = re.compile(r"^_?\w*(http|httpclient)$", re.I)


def _decorated_classes(masked: str) -> List[Tuple[str, str, int]]:
    """(decorator, class name, class keyword offset) for decorated classes."""
    out = []
    for m in _DECORATED.finditer(masked):
        j = m.end()
        if re.match(r"\s*\(", masked[j:j + 4]):
            _, close = args_at(masked, masked.find("(", j))
            j = close + 1
        c = re.compile(r"\s*(?:@\w+\s*\([^)]*\)\s*)*(?:export\s+)?(?:default\s+)?"
                       r"(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)").match(masked, j)
        if c:
            out.append((m.group(1), c.group(1), c.start(1)))
    return out


def collect_angular(repo: str, rel: str, text: str, ctx: ScanContext) -> None:
    _, masked = strip_code(text, ts=True)
    known = ctx.ts_classes.setdefault(repo, set())
    for _, name, _ in _decorated_classes(masked):
        known.add(name)


def _read_ts_expr(clean: str, i: int) -> str:
    n = len(clean)
    j = i
    depth = 0
    while j < n:
        ch = clean[j]
        if ch in "\"'`":
            j += 1
            while j < n and clean[j] != ch:
                j += 2 if clean[j] == "\\" else 1
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                break
        elif ch == ";" and depth == 0:
            break
        elif ch == "\n" and depth == 0:
            seg = clean[i:j].rstrip()
            nxt = clean[j:].lstrip()[:1]
            if seg and seg[-1] not in "+,(?:" and nxt not in ("+", ".", "?"):
                break
        j += 1
    return clean[i:j].strip()


class _Src:
    def __init__(self, repo: str, rel: str, text: str, ctx: ScanContext) -> None:
        self.repo, self.rel, self.ctx = repo, rel, ctx
        self.orig = text.split("\n")
        self.clean, self.masked = strip_code(text, ts=True)
        self.lines = Lines(self.clean)
        self.env = ctx.ts_env.get(repo, {})
        self.pairs: List[Tuple[int, int, int]] = []
        stack: List[int] = []
        for i, ch in enumerate(self.masked):
            if ch == "{":
                stack.append(i)
            elif ch == "}" and stack:
                self.pairs.append((stack.pop(), i, len(stack)))
        self.pairs.sort()
        close_of = {o: c for o, c, _ in self.pairs}
        self.classes: List[Tuple[int, int, int, str]] = []  # keyword, open, close, name
        for m in _CLASS.finditer(self.masked):
            o = self.masked.find("{", m.end())
            if o >= 0 and ";" not in self.masked[m.end():o]:
                self.classes.append((m.start(), o, close_of.get(o, len(self.masked)),
                                     m.group(1)))
        self.vars: Dict[str, List[Tuple[Optional[Tuple[int, int]], str]]] = {}
        for m in re.finditer(
                r"(?<![\w.$])(?:(?:private|public|protected|readonly|static|const|let|var)\s+)+"
                r"([A-Za-z_$][\w$]*)\s*(?::\s*string\s*)?=(?!=)\s*", self.masked):
            self.vars.setdefault(m.group(1), []).append(
                (self.scope(m.start()), _read_ts_expr(self.clean, m.end())))

    def class_at(self, off: int) -> Optional[Tuple[int, int, int, str]]:
        best = None
        for c in self.classes:
            if c[1] < off < c[2] and (best is None or c[1] > best[1]):
                best = c
        return best

    def scope(self, off: int) -> Optional[Tuple[int, int]]:
        cls = self.class_at(off)
        base = (next((d for o, _, d in self.pairs if o == cls[1]), 0) + 1) if cls else 0
        for o, c, d in self.pairs:
            if d == base and o < off < c:
                return (o, c)
        return None

    def ev(self, off: int) -> Evidence:
        return make_ev(self.repo, self.rel, self.orig, self.lines.line_of(off))

    def lookup(self, chain: str, off: int) -> Tuple[Optional[str], Optional[str]]:
        if chain.startswith("environment."):
            v = self.env.get(chain[len("environment."):])
            return ("'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'", None) \
                if v is not None else (None, "%s not found in environment files" % chain)
        name = chain[5:] if chain.startswith("this.") else chain.split(".")[-1] \
            if re.fullmatch(r"[A-Z]\w*\.[A-Z_]\w*", chain) else chain
        if not re.fullmatch(r"[A-Za-z_$][\w$]*", name):
            return None, "cannot work out '%s'" % chain
        entries = self.vars.get(name, [])
        scope = self.scope(off)
        local = [e for e in entries if e[0] is not None and e[0] == scope]
        pool = local or [e for e in entries if e[0] is None]
        exprs = {e[1] for e in pool}
        if len(exprs) == 1:
            return pool[0][1], None
        if len(exprs) > 1:
            return None, "variable %s is assigned more than once" % name
        return None, "cannot work out the value of %s" % chain

    def eval(self, expr: str, off: int, depth: int = 0) -> Tuple[Optional[str], Optional[str]]:
        expr = re.sub(r"\s+as\s+\w+\s*$", "", expr.strip())
        if depth > 8 or not expr:
            return None, "cannot work out '%s'" % expr
        out = ""
        for term in split_top(expr, "+"):
            t = term.strip()
            while t.startswith("(") and t.endswith(")") and len(split_top(t[1:-1], "+")) >= 1 \
                    and t[1:-1].count("(") == t[1:-1].count(")"):
                t = re.sub(r"\s+as\s+\w+\s*$", "", t[1:-1].strip())
            val: Optional[str]
            why: Optional[str] = None
            raw = t
            if len(split_top(t, "+")) > 1:
                val, why = self.eval(t, off, depth + 1)
            elif re.fullmatch(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"", t):
                val = unescape(t[1:-1])
            elif t.startswith("`") and t.endswith("`") and len(t) >= 2:
                val, why = self._template(out, t[1:-1], off, depth)
                if val is not None:
                    out += val
                    continue
            elif re.fullmatch(r"-?\d+", t):
                val = t
            elif re.fullmatch(r"(?:this\.)?[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*", t):
                e, why = self.lookup(t, off)
                val = None
                if e is not None:
                    val, why = self.eval(e, off, depth + 1)
            else:
                val, why = None, "cannot work out '%s'" % t
            if val is None:
                if out.endswith(("/", "=")) or "?" in out:
                    out += "${%s}" % raw
                    continue
                return None, why or "cannot work out '%s'" % raw
            out += val
        return out, None

    def _template(self, prefix: str, body: str, off: int,
                  depth: int) -> Tuple[Optional[str], Optional[str]]:
        out = ""
        i = 0
        while i < len(body):
            if body.startswith("${", i):
                j = i + 2
                d = 1
                while j < len(body) and d:
                    d += (body[j] == "{") - (body[j] == "}")
                    j += 1
                inner = body[i + 2:j - 1]
                val, why = self.eval(inner, off, depth + 1)
                if val is None:
                    full = prefix + out
                    if full.endswith(("/", "=")) or "?" in full:
                        out += "${%s}" % inner.strip()
                    else:
                        return None, why
                else:
                    out += val
                i = j
            else:
                out += body[i]
                i += 1
        return unescape(out), None


def _unquote(v: str) -> Optional[str]:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"`" and "${" not in v:
        return unescape(v[1:-1])
    return None


def _routes(s: _Src, open_idx: int, prefix: str, repo: str, nodes: List[Node],
            refs: List[Ref], cursor: List[int]) -> None:
    items, _ = args_at(s.clean, open_idx)
    for item in items:
        pos = s.clean.find(item, max(cursor[0], open_idx))
        if pos < 0:
            pos = open_idx
        cursor[0] = pos
        if not (item.startswith("{") and item.endswith("}")):
            continue
        props = {}
        for part in split_top(item[1:-1], ","):
            k, _, v = part.partition(":")
            props[k.strip().strip("'\"")] = v.strip()
        path = _unquote(props.get("path", "")) if "path" in props else None
        if path is None:
            continue
        full = "/".join(x for x in (prefix + "/" + path).split("/") if x)
        comp = None
        if re.fullmatch(r"[A-Za-z_$][\w$]*", props.get("component", "")):
            comp = props["component"]
        elif "loadComponent" in props:
            lm = re.search(r"\.then\s*\(\s*\(?\s*(\w+)\s*\)?\s*=>\s*\1\.(\w+)", props["loadComponent"])
            comp = lm.group(2) if lm else None
        if comp:
            pid = "page:%s/%s" % (repo, full)
            nodes.append(Node(pid, "page", full or "/", repo, [s.ev(pos)], {"path": full}))
            refs.append(Ref(pid, "uses", "component", "%s/%s" % (repo, comp), s.ev(pos)))
        ch = props.get("children", "")
        if ch.startswith("["):
            cpos = s.clean.find(ch, pos)
            _routes(s, cpos, full, repo, nodes, refs, cursor)


def scan_angular(repo: str, rel: str, text: str,
                 ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    s = _Src(repo, rel, text, ctx)
    nodes: List[Node] = []
    refs: List[Ref] = []
    known = ctx.ts_classes.get(repo, set())
    node_ids: Set[str] = set()

    def cid(name: str) -> str:
        return "component:%s/%s" % (repo, name)

    def ensure(name: str, off: int, decorator: Optional[str]) -> None:
        if cid(name) not in node_ids:
            node_ids.add(cid(name))
            nodes.append(Node(cid(name), "component", name, repo, [s.ev(off)],
                              {"decorator": decorator}))

    for dec, name, off in _decorated_classes(s.masked):
        ensure(name, off, dec)

    # constructor / inject() dependencies
    for _, o, c, name in s.classes:
        if name not in known:
            continue
        seen: Set[str] = set()
        deps: List[Tuple[str, int]] = []
        for m in re.finditer(r"\bconstructor\s*\(", s.masked[:c]):
            if m.start() < o:
                continue
            params, _ = args_at(s.clean, m.end() - 1)
            for p in params:
                p = re.sub(r"@\w+\s*\([^)]*\)\s*", "", p)
                tm = re.search(r":\s*([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*(?:\|[^=]*)?(?:=.*)?$",
                               p, re.S)
                if tm:
                    deps.append((tm.group(1), m.start()))
        for m in re.finditer(r"\binject\s*\(\s*([A-Za-z_$][\w$]*)", s.masked[o:c]):
            deps.append((m.group(1), o + m.start()))
        for t, off in deps:
            if t in known and t != name and t not in seen:
                seen.add(t)
                refs.append(Ref(cid(name), "uses", "component", "%s/%s" % (repo, t), s.ev(off)))

    # HTTP calls
    for m in re.finditer(
            r"(?<![\w$])((?:[\w$]+\s*\.\s*)*([\w$]+))\s*\.\s*(get|post|put|delete|patch|head|"
            r"options|request)\s*(?:<[^()]*?>)?\s*\(", s.masked):
        if not _ENDS_HTTP.match(m.group(2)):
            continue
        cls = s.class_at(m.start())
        if cls is None:
            continue
        args, _ = args_at(s.clean, m.end() - 1)
        meth = m.group(3).upper()
        if m.group(3) == "request":
            lit = _unquote(args[0]) if args else None
            if lit is None:
                ensure(cls[3], cls[0], None)
                refs.append(Ref(cid(cls[3]), "http", "endpoint", None, s.ev(m.start()),
                                "HTTP method of request(...) not worked out"))
                continue
            meth, args = lit.upper(), args[1:]
        if not args:
            continue
        ensure(cls[3], cls[0], None)
        url, why = s.eval(args[0], m.start())
        ev = s.ev(m.start())
        if url is None:
            refs.append(Ref(cid(cls[3]), "http", "endpoint", None, ev,
                            "URL not worked out: %s" % why))
        else:
            refs.append(Ref(cid(cls[3]), "http", "endpoint", "%s %s" % (meth, url), ev))

    # routes
    cursor = [0]
    seen_arrays: Set[int] = set()
    for m in re.finditer(r"\bRoutes\s*=\s*\[|\b(?:forRoot|forChild|provideRouter)\s*\(\s*\[",
                         s.masked):
        o = m.end() - 1
        if o not in seen_arrays:
            seen_arrays.add(o)
            cursor[0] = o
            _routes(s, o, "", repo, nodes, refs, cursor)
    return nodes, refs
