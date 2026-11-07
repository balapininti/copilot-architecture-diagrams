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
from ..textio import drop_sequence_area
from . import ScanContext

_OBJ = {"QLOCAL": "local", "QL": "local", "QALIAS": "alias", "QA": "alias",
        "QREMOTE": "remote", "QR": "remote", "PROCESS": "process", "PRO": "process"}
_CKBR_APPLICID = "CKBR"
DEFAULT_BRIDGE_QUEUE = "SYSTEM.CICS.BRIDGE.QUEUE"  # CKBR's queue when its start has no Q=
_CKBR_START = re.compile(r"\bSTART\b.*?\bTRANS(?:ID)?\s*\(\s*['\"]?CKBR['\"]?\s*\)", re.I | re.S)
_CKBR_Q = re.compile(r"\bQ\s*=\s*([A-Za-z0-9._/%#$@]+)", re.I)
_CKBR_FROM = re.compile(r"\bFROM\s*\(\s*(['\"])?", re.I)


def _commands(text: str) -> List[Tuple[int, str]]:
    """Join continued MQSC lines into commands: (first line number, command text)."""
    out: List[Tuple[int, str]] = []
    buf, first, cont = "", 0, None
    for no, raw in enumerate(text.split("\n"), 1):
        # z/OS MQSC input (CSQINP1/2, CSQUTIL): "Only columns 1 through 72 can contain
        # meaningful information; columns 73 through 80 are ignored."
        # https://publibfp.boulder.ibm.com/epubs/html/csqzaj06/csqzaj060f.htm
        line = drop_sequence_area(raw).rstrip()
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
        # '-' continues from column 1 of the next line, '+' from its first non-blank;
        # neither inserts a blank, so a name may be split mid-token
        buf += seg
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
    for stmt in _ckbr_statements(text, ftype):
        if not _CKBR_START.search(stmt):
            continue
        q = _CKBR_Q.search(stmt)
        if q:
            ctx.ckbr_queues.add(q.group(1).upper())
            continue
        f = _CKBR_FROM.search(stmt)
        if f is None or f.group(1):  # no FROM, or a literal FROM without Q=
            ctx.ckbr_queues.add(DEFAULT_BRIDGE_QUEUE)
        # FROM(variable): the parameters are set at run time, so nothing is known


def _ckbr_statements(text: str, ftype: Optional[str]) -> List[str]:
    """The statements that mention CKBR: an EXEC CICS ... END-EXEC block, else the line."""
    lines = text.split("\n")
    cobol = ftype in ("cobol", "copybook")
    out: List[str] = []
    for i, raw in enumerate(lines):
        if "CKBR" not in raw.upper():
            continue
        if cobol and len(raw) > 6 and raw[6] in "*/":
            continue
        start = end = i
        for j in range(i, max(-1, i - 30), -1):
            up = lines[j].upper()
            if j < i and "END-EXEC" in up:
                break
            if re.search(r"\bEXEC\s+CICS\b", up):
                start = j
                break
        if start != i or "EXEC" in raw.upper():
            for j in range(i, min(len(lines), i + 30)):
                if "END-EXEC" in lines[j].upper():
                    end = j
                    break
        stmt = " ".join(lines[start:end + 1])
        out.append(stmt)
    return out


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
        if kind == "alias":
            attrs["targtype"] = (_value(kws, "TARGTYPE") or "QUEUE").upper()
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
