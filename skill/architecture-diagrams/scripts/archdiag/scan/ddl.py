"""DB2 DDL: tables, views, aliases and synonyms with their schema.

``CREATE TABLE`` / ``CREATE VIEW`` give ``table:<SCHEMA>.<NAME>`` (``attrs["type"]`` is
``table`` or ``view``). ``CREATE ALIAS|SYNONYM A FOR B`` gives a ``table:`` node for A with
``attrs["alias_of"] = B`` and ``type`` ``alias``. ``--`` and ``/* */`` comments and string
literals are blanked before matching, so text inside them produces no facts. An unqualified
name takes the schema from an earlier ``SET SCHEMA`` / ``SET CURRENT SQLID`` in the same file,
and otherwise has ``schema=None`` (node ``table:<NAME>``). Names are upper-cased unless they
are delimited identifiers (``"x"``), which keep their case.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from ..model import Evidence, Node, Ref
from . import ScanContext


def mask_sql(text: str) -> str:
    """Blank comments and string literals (keeping newlines and offsets)."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "-" and text.startswith("--", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
        elif ch == "/" and text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif ch == "'":
            j = i + 1
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
        else:
            i += 1
            continue
        for k in range(i, j):
            if out[k] != "\n":
                out[k] = " "
        i = j
    return "".join(out)


_PART = r'(?:"[^"\n]+"|[A-Za-z@#$_][A-Za-z0-9@#$_]*)'
_QNAME = r"(%s(?:\s*\.\s*%s){0,2})" % (_PART, _PART)
_CREATE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:PUBLIC|GLOBAL\s+TEMPORARY|LARGE)\s+)?"
    r"(TABLE|VIEW|ALIAS|SYNONYM)\s+" + _QNAME + r"(?:\s+FOR\s+(?:TABLE\s+)?" + _QNAME + ")?",
    re.I)
_SET_SCHEMA = re.compile(
    r"\bSET\s+(?:CURRENT\s+)?(?:SCHEMA|SQLID)\s*=?\s*(?:'([^']+)'|(" + _PART + "))", re.I)


def _parts(qname: str) -> List[str]:
    out = []
    for p in re.split(r"\s*\.\s*", qname.strip()):
        out.append(p[1:-1] if p.startswith('"') else p.upper())
    return out


def scan_ddl(repo: str, relpath: str, text: str,
             ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    masked = mask_sql(text)
    lines = text.split("\n")
    nodes: List[Node] = []
    # SET SCHEMA / SQLID: matched on the original text (the value is often a string
    # literal, which masking blanks), kept only where the SET itself is live code
    sets: List[Tuple[int, str]] = []
    for m in _SET_SCHEMA.finditer(text):
        if masked[m.start()] == " ":
            continue
        val = m.group(1).strip().upper() if m.group(1) else _parts(m.group(2))[0]
        sets.append((m.start(), val))

    def schema_at(off: int) -> Optional[str]:
        cur = None
        for o, s in sets:
            if o < off and s:
                cur = s
        return cur

    for m in _CREATE.finditer(masked):
        kind = m.group(1).upper()
        parts = _parts(m.group(2))
        if kind in ("ALIAS", "SYNONYM") and not m.group(3):
            continue
        name = parts[-1]
        schema = parts[-2] if len(parts) >= 2 else schema_at(m.start())
        line = masked.count("\n", 0, m.start()) + 1
        full = schema + "." + name if schema else name
        attrs = {"schema": schema, "name": name,
                 "type": {"TABLE": "table", "VIEW": "view"}.get(kind, "alias")}
        if kind in ("ALIAS", "SYNONYM"):
            attrs["alias_of"] = ".".join(_parts(m.group(3)))
        nodes.append(Node("table:" + full, "table", full, repo,
                          [Evidence(repo, relpath, line, lines[line - 1].strip())], attrs))
    return nodes, []
