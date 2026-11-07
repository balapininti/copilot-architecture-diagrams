"""Code the skill doesn't analyze (spec 7.6): Assembler, PL/I, Easytrieve, REXX/CLIST.

``register_other`` only registers program names, so a ``CALL`` or ``EXEC PGM=`` to one of
them reaches a grey "not analyzed" box instead of a loose end. Each file gives
``notanalyzed:<NAME>`` with ``attrs["language"]`` for its member name (the file stem,
upper-cased), plus its obvious entry points: Assembler ``CSECT``/``RSECT``/``START`` labels and
``ENTRY`` operands, and a PL/I ``label: PROC OPTIONS(MAIN)``. More names means fewer missed
links; each is a real way the load module can be called. Assembler macro files (``.mac``)
are not programs and register nothing. ``scan_workspace`` counts every file of these
languages into ``Inventory.languages_not_analyzed``.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from ..model import Evidence, Node, Ref
from ..textio import classify
from . import ScanContext

_ASM_SECT = re.compile(r"^([A-Za-z@#$][A-Za-z0-9@#$_]{0,62})\s+(?:CSECT|RSECT|START)\b", re.I)
_ASM_ENTRY = re.compile(r"^(?:[A-Za-z@#$]\S*)?\s+ENTRY\s+(\S+)", re.I)
_PLI_MAIN = re.compile(r"^\s*([A-Za-z@#$][A-Za-z0-9@#$_]*)\s*:\s*PROC(?:EDURE)?\s+OPTIONS\s*\(\s*MAIN\b",
                       re.I)
_NAME = re.compile(r"^[A-Za-z@#$][A-Za-z0-9@#$_-]*$")


def register_other(repo: str, relpath: str, text: str,
                   ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    language = classify(relpath, text)
    base = relpath.replace("\\", "/").rsplit("/", 1)[-1]
    if base.lower().endswith(".mac"):
        return [], []
    lines = text.split("\n")
    found: List[Tuple[str, int]] = []
    for no, raw in enumerate(lines, 1):
        if language == "asm":
            if raw[:1] == "*" or raw[:2] == ".*":
                continue
            m = _ASM_SECT.match(raw[:71])
            if m:
                found.append((m.group(1).upper(), no))
            m = _ASM_ENTRY.match(raw[:71])
            if m:
                for name in m.group(1).split(","):
                    if _NAME.match(name):
                        found.append((name.upper(), no))
        elif language == "pli":
            m = _PLI_MAIN.match(raw)
            if m:
                found.append((m.group(1).upper(), no))
    stem = base.split(".", 1)[0].upper() if "." in base[1:] else base.upper()
    if _NAME.match(stem):
        found.append((stem, 1))
    nodes: List[Node] = []
    seen = set()
    for name, no in found:
        if name in seen:
            continue
        seen.add(name)
        text_at = lines[no - 1].strip() if no <= len(lines) else ""
        nodes.append(Node("notanalyzed:" + name, "notanalyzed", name, repo,
                          [Evidence(repo, relpath, no, text_at)], {"language": language}))
    return nodes, []
