"""IBM MQ definitions (MQSC): local, alias and remote queues, and processes.

``DEFINE QLOCAL|QALIAS|QREMOTE(name)`` gives ``queue:<name>`` with ``attrs`` ``type``
(``local``/``alias``/``remote``), ``target`` (alias ``TARGET``/``TARGQ``, remote ``RNAME``),
``process``, ``initq``, ``trigger`` and ``bridge``; remote queues also keep ``rqmname`` and
``xmitq``. ``DEFINE PROCESS(name)`` gives ``mqprocess:<name>`` with ``attrs["applicid"]``.

MQSC rules: a line starting with ``*`` is a comment; a trailing ``+`` continues the command
and drops the next line's leading blanks, a trailing ``-`` continues it keeping them.
Unquoted names fold to upper case, quoted names keep their case (MQ semantics). Keywords
accept the MQSC short forms (DEF, QL, QA, QR, PRO, TARGQ).

``bridge`` (the CICS-MQ bridge) is true when any of these hold:
  * ``DESCR`` mentions ``CICS BRIDGE`` (how the fixture marks it);
  * the queue's ``PROCESS`` has ``APPLICID(CKBR)`` (the bridge monitor is triggered);
  * the queue, or its ``INITQ``, is named as ``Q=<queue>`` in a ``CKBR`` start anywhere in
    the scanned repos (for example ``EXEC CICS START TRANSID('CKBR') FROM('Q=...')``).
The last two are collected estate-wide in pass 1 (``collect_mq``).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from ..model import Evidence, Node, Ref
from . import ScanContext

_OBJ = {"QLOCAL": "local", "QL": "local", "QALIAS": "alias", "QA": "alias",
        "QREMOTE": "remote", "QR": "remote", "PROCESS": "process", "PRO": "process"}
_CKBR = re.compile(r"\bCKBR\b(.{0,400}?)\bQ\s*=\s*([A-Za-z0-9._/%#$@]+)", re.I | re.S)
_CKBR_APPLICID = "CKBR"


def _commands(text: str) -> List[Tuple[int, str]]:
    """Join continued MQSC lines into commands: (first line number, command text)."""
    out: List[Tuple[int, str]] = []
    buf, first, cont = "", 0, None
    for no, raw in enumerate(text.split("\n"), 1):
        line = raw.rstrip()
        if cont is None:
            if not line.strip() or line.lstrip()[:1] == "*":
                continue
            first = no
        elif cont == "+":
            line = line.lstrip()
        if line.endswith("+") or line.endswith("-"):
            cont = line[-1]
            seg = line[:-1]
        else:
            cont = None
            seg = line
        buf += seg + " "
        if cont is None:
            out.append((first, buf))
            buf = ""
    if buf.strip():
        out.append((first, buf))
    return out


_TOKEN = re.compile(r"([A-Za-z][A-Za-z0-9]*)\s*(\()?")


def _keywords(cmd: str) -> List[Tuple[str, Optional[str], int]]:
    """KEYWORD or KEYWORD(value) items with their offsets; quoted values keep their case."""
    out: List[Tuple[str, Optional[str], int]] = []
    i, n = 0, len(cmd)
    while i < n:
        m = _TOKEN.match(cmd, i)
        if not m:
            i += 1
            continue
        key = m.group(1).upper()
        if not m.group(2):
            out.append((key, None, m.start()))
            i = m.end()
            continue
        j = m.end()
        val = []
        quoted = False
        while j < n:
            ch = cmd[j]
            if ch == "'":
                if quoted and j + 1 < n and cmd[j + 1] == "'":
                    val.append("'")
                    j += 2
                    continue
                quoted = not quoted
                j += 1
                continue
            if ch == ")" and not quoted:
                break
            val.append(ch if quoted else ch.upper())
            j += 1
        out.append((key, "".join(val).strip(), m.start()))
        i = j + 1
    return out


def _value(kws: List[Tuple[str, Optional[str], int]], *keys: str) -> Optional[str]:
    for k, v, _ in kws:
        if k in keys and v:
            return v
    return None


def collect_mq(repo: str, rel: str, text: str, ftype: Optional[str],
               ctx: ScanContext) -> None:
    """Pass 1: CKBR processes (from MQSC) and queues named in CKBR starts (any file)."""
    if "CKBR" not in text.upper():
        return
    if ftype == "mqsc":
        for _, cmd in _commands(text):
            kws = _keywords(cmd)
            if len(kws) >= 2 and kws[0][0] in ("DEFINE", "DEF") and kws[1][0] in ("PROCESS", "PRO"):
                if (_value(kws, "APPLICID") or "").upper() == _CKBR_APPLICID and kws[1][1]:
                    ctx.ckbr_processes.add(kws[1][1])
        return
    for m in _CKBR.finditer(text):
        ctx.ckbr_queues.add(m.group(2).upper())


def scan_mqsc(repo: str, relpath: str, text: str,
              ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    src_lines = text.split("\n")
    nodes: List[Node] = []
    for first, cmd in _commands(text):
        kws = _keywords(cmd)
        if len(kws) < 2 or kws[0][0] not in ("DEFINE", "DEF"):
            continue
        obj, name, _ = kws[1]
        kind = _OBJ.get(obj)
        if kind is None or not name:
            continue
        ev = Evidence(repo, relpath, first, src_lines[first - 1].strip())
        if kind == "process":
            nodes.append(Node("mqprocess:" + name, "mqprocess", name, repo, [ev],
                              {"applicid": _value(kws, "APPLICID")}))
            continue
        process = _value(kws, "PROCESS")
        initq = _value(kws, "INITQ")
        descr = _value(kws, "DESCR") or ""
        keys = {k for k, v, _ in kws if v is None}
        attrs: Dict[str, object] = {
            "type": kind,
            "target": _value(kws, "TARGET", "TARGQ") if kind == "alias" else (
                _value(kws, "RNAME") if kind == "remote" else None),
            "process": process,
            "initq": initq,
            "trigger": "TRIGGER" in keys and "NOTRIGGER" not in keys,
        }
        if kind == "remote":
            attrs["rqmname"] = _value(kws, "RQMNAME")
            attrs["xmitq"] = _value(kws, "XMITQ")
        attrs["bridge"] = bool(
            "CICS BRIDGE" in descr.upper()
            or (process is not None and process in ctx.ckbr_processes)
            or name.upper() in ctx.ckbr_queues
            or (initq is not None and initq.upper() in ctx.ckbr_queues))
        nodes.append(Node("queue:" + name, "queue", name, repo, [ev], attrs))
    return nodes, []
