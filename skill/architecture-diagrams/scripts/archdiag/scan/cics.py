"""CICS resource definitions (DFHCSDUP input / CSD extracts) and BMS mapsets.

CSD: ``DEFINE TRANSACTION(X) ... PROGRAM(P)`` gives ``transaction:X`` and a ``runs`` Ref to
the program; ``DEFINE FILE(F) ... DSNAME(D)`` gives ``cicsfile:F`` with ``attrs["dsname"]``
and a ``file_dataset`` Ref to the dataset. A DFHCSDUP command runs until the next line that
starts with a command verb (``DEFINE``, ``ADD``, ``LIST`` ...); a verb followed directly by
``(`` is an attribute (``ADD(NO)`` on a FILE), not a command. ``*`` in column 1 is a comment.

BMS: the label of each ``DFHMSD`` macro (other than ``TYPE=FINAL``) is the mapset name,
giving ``map:<MAPSET>`` with the ``DFHMDI`` map names in ``attrs["maps"]``.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from ..model import Evidence, Node, Ref
from . import ScanContext

_VERBS = frozenset(
    "ADD ALTER APPEND COPY DEFINE DEF DELETE EXTRACT INITIALIZE LIST MIGRATE PROCESS "
    "REMOVE SCAN SERVICE UPGRADE USERDEFINE VERIFY".split())
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def _statements(lines: List[str]) -> List[List[Tuple[int, str]]]:
    """Group the lines of a DFHCSDUP input into commands of (line number, text)."""
    stmts: List[List[Tuple[int, str]]] = []
    for no, raw in enumerate(lines, 1):
        if raw[:1] == "*" or not raw.strip():
            continue
        body = raw.rstrip()
        m = _WORD.match(body.lstrip())
        rest = body.lstrip()[m.end():] if m else ""
        if m and m.group(0).upper() in _VERBS and not rest.lstrip().startswith("("):
            stmts.append([])
        if stmts:
            stmts[-1].append((no, body))
    return stmts


def _keywords(stmt: List[Tuple[int, str]]) -> List[Tuple[str, str, int]]:
    """KEYWORD(value) pairs of one command, with the line each starts on.

    Values can hold balanced parentheses (DESCRIPTION(Claim (online))) and quotes.
    """
    out: List[Tuple[str, str, int]] = []
    text = ""
    starts: List[Tuple[int, int]] = []  # (offset, line)
    for no, body in stmt:
        starts.append((len(text), no))
        text += body + " "

    def line_at(off: int) -> int:
        ln = starts[0][1]
        for o, no in starts:
            if o <= off:
                ln = no
        return ln

    i, n = 0, len(text)
    while i < n:
        m = _WORD.match(text, i)
        if not m:
            i += 1
            continue
        j = m.end()
        if j < n and text[j] == "(":
            depth, k, quote = 0, j, None
            while k < n:
                ch = text[k]
                if quote:
                    if ch == quote:
                        quote = None
                elif ch == "'":
                    quote = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            out.append((m.group(0).upper(), text[j + 1:k].strip(), line_at(m.start())))
            i = k + 1
        else:
            out.append((m.group(0).upper(), "", line_at(m.start())))
            i = j
    return out


def _name(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == "'":
        v = v[1:-1]
    return v.strip().upper()


def _kw(kws: List[Tuple[str, str, int]], *names: str) -> Optional[Tuple[str, int]]:
    for k, v, ln in kws[1:]:  # kws[0] is the command verb
        if k in names and v:
            return _name(v), ln
    return None


def scan_csd(repo: str, relpath: str, text: str,
             ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    lines = text.split("\n")
    nodes: List[Node] = []
    refs: List[Ref] = []

    def ev(line: int) -> Evidence:
        return Evidence(repo, relpath, line, lines[line - 1].strip())

    for stmt in _statements(lines):
        kws = _keywords(stmt)
        if len(kws) < 2 or kws[0][0] not in ("DEFINE", "DEF"):
            continue
        kind, value, line = kws[1]
        value = _name(value)
        if not value:
            continue
        if kind in ("TRANSACTION", "TRANSACTIO", "TRANSACTI", "TRANSACT", "TRANSAC",
                    "TRANSA", "TRANS"):
            tid = "transaction:" + value
            group = _kw(kws, "GROUP")
            nodes.append(Node(tid, "transaction", value, repo, [ev(line)],
                              {"group": group[0] if group else None}))
            prog = _kw(kws, "PROGRAM", "PROGRA", "PROGR", "PROG")
            if prog:
                refs.append(Ref(tid, "runs", "program", prog[0], ev(prog[1])))
        elif kind == "FILE":
            fid = "cicsfile:" + value
            dsn = _kw(kws, "DSNAME", "DSNAM", "DSNA", "DSN")
            nodes.append(Node(fid, "cicsfile", value, repo, [ev(line)],
                              {"dsname": dsn[0] if dsn else None}))
            if dsn:
                refs.append(Ref(fid, "file_dataset", "dataset", dsn[0], ev(dsn[1])))
    return nodes, refs


_BMS = re.compile(r"^([A-Za-z@#$][A-Za-z0-9@#$]{0,7})?\s+(DFHMSD|DFHMDI)\b(.*)$")


def scan_bms(repo: str, relpath: str, text: str,
             ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    nodes: List[Node] = []
    current: Optional[Node] = None
    for no, raw in enumerate(text.split("\n"), 1):
        if raw[:1] == "*" or raw[:2] == ".*":
            continue
        m = _BMS.match(raw[:71])
        if not m:
            continue
        label, macro, ops = m.group(1), m.group(2).upper(), m.group(3)
        if macro == "DFHMSD":
            if re.search(r"\bTYPE\s*=\s*FINAL\b", ops, re.I) or not label:
                current = None
                continue
            name = label.upper()
            current = Node("map:" + name, "map", name, repo,
                           [Evidence(repo, relpath, no, raw.strip())], {"maps": []})
            nodes.append(current)
        elif current is not None and label:
            current.attrs["maps"].append(label.upper())
    return nodes, []
