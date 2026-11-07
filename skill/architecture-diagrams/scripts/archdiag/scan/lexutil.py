"""Shared helpers for the Java and Angular scanners: comment stripping, argument
splitting, property files and the small YAML / TypeScript-object readers."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from ..model import Evidence


def strip_code(text: str, ts: bool = False) -> Tuple[str, str]:
    """Return (clean, masked). Comments become blanks (newlines kept, so offsets and
    line numbers stay put). In ``masked`` the inside of every string literal is also
    replaced by ``_``, so structural regexes cannot match text inside strings."""
    n = len(text)
    clean: List[str] = []
    masked: List[str] = []
    i = 0

    def both(s: str, m: Optional[str] = None) -> None:
        clean.append(s)
        masked.append(s if m is None else m)

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            both(" " * (j - i))
            i = j
        elif ch == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            both("".join(c if c == "\n" else " " for c in text[i:j]))
            i = j
        elif not ts and text.startswith('"""', i):
            j = text.find('"""', i + 3)
            j = n if j < 0 else j + 3
            seg = text[i:j]
            clean.append(seg)
            masked.append('"""' + "".join(c if c == "\n" else "_" for c in seg[3:-3])
                          + ('"""' if j <= n and seg.endswith('"""') and len(seg) >= 6 else ""))
            i = j
        elif ch in "\"'`":
            if ch == "`" and not ts:
                both(ch)
                i += 1
                continue
            j = i + 1
            while j < n:
                c = text[j]
                if c == "\\":
                    j += 2
                    continue
                if c == ch:
                    break
                if c == "\n" and ch != "`":
                    break  # unterminated: stop at end of line
                j += 1
            end = min(j + 1, n) if j < n and text[j] == ch else min(j, n)
            seg = text[i:end]
            clean.append(seg)
            inner_end = len(seg) - 1 if seg.endswith(ch) and len(seg) > 1 else len(seg)
            masked.append(ch + "".join(c if c == "\n" else "_" for c in seg[1:inner_end])
                          + seg[inner_end:])
            i = end
        else:
            both(ch)
            i += 1
    return "".join(clean), "".join(masked)


class Lines:
    def __init__(self, text: str) -> None:
        self._text = text

    def line_of(self, off: int) -> int:
        return self._text.count("\n", 0, off) + 1


def make_ev(repo: str, rel: str, orig_lines: List[str], line: int) -> Evidence:
    txt = orig_lines[line - 1].strip() if 0 < line <= len(orig_lines) else ""
    return Evidence(repo, rel, line, txt[:200])


def args_at(clean: str, open_idx: int) -> Tuple[List[str], int]:
    """Split the arguments of the call whose ``(`` is at open_idx. Returns the argument
    strings (stripped) and the index of the closing paren (len(clean) if unbalanced)."""
    depth = 0
    args: List[str] = []
    cur: List[str] = []
    i = open_idx
    n = len(clean)
    while i < n:
        ch = clean[i]
        if ch in "\"'`":
            j = i + 1
            while j < n and clean[j] != ch:
                j += 2 if clean[j] == "\\" else 1
            cur.append(clean[i:j + 1])
            i = j + 1
            continue
        if ch in "([{":
            depth += 1
            if depth > 1:
                cur.append(ch)
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                tail = "".join(cur).strip()
                if tail or args:
                    args.append(tail)
                return args, i
            cur.append(ch)
        elif ch == "," and depth == 1:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    return args, n


def split_top(expr: str, sep: str) -> List[str]:
    """Split on a single-character separator outside strings and brackets."""
    out: List[str] = []
    cur: List[str] = []
    depth = 0
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch in "\"'`":
            j = i + 1
            while j < n and expr[j] != ch:
                j += 2 if expr[j] == "\\" else 1
            cur.append(expr[i:j + 1])
            i = j + 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur).strip())
    return out


_ESC = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "'": "'", "\\": "\\", "`": "`"}


def unescape(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESC.get(m.group(1), m.group(1)), s)


_PLACEHOLDER = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")


def expand_placeholders(s: str, props: Dict[str, str],
                        depth: int = 0) -> Tuple[Optional[str], Optional[str]]:
    """Resolve Spring ``${prop}`` / ``${prop:default}``. Returns (text, None) or
    (None, reason)."""
    if "#{" in s:
        return None, "SpEL expression %s cannot be worked out" % s
    reason: List[str] = []

    def sub(m: "re.Match[str]") -> str:
        key = m.group(1).strip()
        if key in props:
            val = props[key]
        elif m.group(2) is not None:
            val = m.group(2)
        else:
            reason.append("property %s not found" % key)
            return ""
        if "${" in val:
            if depth >= 5:
                reason.append("property %s refers to itself" % key)
                return ""
            got, why = expand_placeholders(val, props, depth + 1)
            if got is None:
                reason.append(why or "property %s not resolved" % key)
                return ""
            return got
        return val

    out = _PLACEHOLDER.sub(sub, s)
    if reason:
        return None, reason[0]
    return out, None


# ---------------------------------------------------------------- property files


def parse_properties(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or line[0] in "#!":
            continue
        m = re.match(r"([^=:\s]+)\s*[=:\s]\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        inner = v[1:-1]
        return unescape(inner) if v[0] == '"' else inner.replace("''", "'")
    # strip trailing comment
    m = re.search(r"\s#", v)
    return (v[:m.start()] if m else v).strip()


def _strip_yaml_comment(line: str) -> str:
    q: Optional[str] = None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'" and (i == 0 or line[i - 1] in " \t:[{,"):
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def _flow_map(v: str, prefix: str, out: Dict[str, str]) -> None:
    body = v.strip()[1:-1]
    for part in split_top(body, ","):
        if ":" not in part:
            continue
        k, _, val = part.partition(":")
        k = _unquote(k.strip())
        val = val.strip()
        if val.startswith("{") and val.endswith("}"):
            _flow_map(val, prefix + k + ".", out)
        elif val and not val.startswith("["):
            out[prefix + k] = _unquote(val)


def parse_yaml_docs(text: str) -> List[Dict[str, str]]:
    """Small YAML subset: nested maps flattened with dots, scalars, quotes, comments,
    flow maps. Lists and block scalars are skipped. One dict per ``---`` document."""
    docs: List[Dict[str, str]] = [{}]
    stack: List[Tuple[int, str]] = []  # (indent, dotted prefix)
    skip_indent: Optional[int] = None
    for raw in text.split("\n"):
        if raw.strip() == "---":
            docs.append({})
            stack = []
            skip_indent = None
            continue
        line = _strip_yaml_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if skip_indent is not None:
            if indent > skip_indent:
                continue
            skip_indent = None
        body = line.strip()
        if body.startswith("- ") or body == "-":
            skip_indent = indent
            continue
        m = re.match(r"""("[^"]*"|'[^']*'|[^\s:'"][^:]*?)\s*:(?:\s+(.*))?$""", body)
        if not m:
            continue
        key = _unquote(m.group(1))
        val = (m.group(2) or "").strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        prefix = stack[-1][1] if stack else ""
        full = prefix + key
        cur = docs[-1]
        if val == "":
            stack.append((indent, full + "."))
        elif val[0] in "|>":
            skip_indent = indent
        elif val.startswith("{") and val.endswith("}"):
            _flow_map(val, full + ".", cur)
        elif val.startswith("["):
            continue
        else:
            cur[full] = _unquote(val)
    return docs


# ---------------------------------------------------------------- TypeScript object


def parse_ts_object(text: str, open_idx: int, prefix: str = "") -> Dict[str, str]:
    """Flatten a TypeScript object literal starting at the ``{`` at open_idx."""
    out: Dict[str, str] = {}
    i = open_idx + 1
    n = len(text)
    while i < n:
        m = re.compile(r"""\s*,?\s*(?:(\w+)|'([^']*)'|"([^"]*)")\s*:\s*""").match(text, i)
        if not m:
            break
        key = m.group(1) or m.group(2) or m.group(3)
        i = m.end()
        if i >= n:
            break
        ch = text[i]
        if ch in "'\"`":
            j = i + 1
            while j < n and text[j] != ch:
                j += 2 if text[j] == "\\" else 1
            body = text[i + 1:j]
            if ch != "`" or "${" not in body:
                out[prefix + key] = unescape(body)
            i = j + 1
        elif ch == "{":
            out.update(parse_ts_object(text, i, prefix + key + "."))
            _, close = args_at(text, i)
            i = close + 1
        else:
            j = i
            depth = 0
            while j < n:
                c = text[j]
                if c in "([{":
                    depth += 1
                elif c in ")]}":
                    if depth == 0:
                        break
                    depth -= 1
                elif c == "," and depth == 0:
                    break
                j += 1
            val = text[i:j].strip()
            if re.fullmatch(r"-?\d+(?:\.\d+)?|true|false", val):
                out[prefix + key] = val
            i = j
        # next property or the closing brace
        k = re.compile(r"\s*").match(text, i).end()
        if k < n and text[k] == "}":
            break
    return out
