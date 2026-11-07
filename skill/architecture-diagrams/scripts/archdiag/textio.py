from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


def read_source(path: Path) -> str:
    """Read a source file as UTF-8, then Windows-1252, then Latin-1; LF line endings."""
    data = Path(path).read_bytes()
    text = None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = data.decode("latin-1")
    return text.replace("\r\n", "\n").replace("\r", "\n")


_EXT = {
    ".cbl": "cobol", ".cob": "cobol", ".cpy": "copybook", ".jcl": "jcl",
    ".proc": "proc", ".prc": "proc", ".csd": "csd", ".bms": "bms",
    ".sql": "ddl", ".ddl": "ddl", ".mqsc": "mqsc", ".java": "java",
    ".properties": "properties", ".yml": "yaml", ".yaml": "yaml",
    ".ts": "angular_ts", ".asm": "asm", ".mac": "asm", ".pli": "pli",
    ".pl1": "pli", ".ezt": "easytrieve", ".rexx": "rexx", ".rex": "rexx",
    ".clist": "rexx", ".sar": "zosconnect", ".aar": "zosconnect",
}

_JOB = re.compile(r"^//\S+\s+JOB\b", re.I)
_PROC = re.compile(r"^//\S*\s+PROC\b", re.I)
_PROGID = re.compile(r"\bPROGRAM-ID\b", re.I)
_CSECT = re.compile(r"^\S*\s+CSECT\b", re.I)
_DFHMSD = re.compile(r"\bDFHMSD\b", re.I)
_PLI = re.compile(r"\bPROCEDURE\s+OPTIONS\s*\(\s*MAIN\b", re.I)
_REXX = re.compile(r"^\s*/\*\s*REXX", re.I)


def classify(relpath: str, text: str) -> Optional[str]:
    """Return the file type for a repo-relative path and its text, or None."""
    rel = relpath.replace("\\", "/")
    parts = rel.lower().split("/")
    ext = ""
    dot = parts[-1].rfind(".")
    if dot > 0:
        ext = parts[-1][dot:]
    if ext in _EXT:
        return _EXT[ext]
    if "zosconnect" in parts[:-1]:
        return "zosconnect"
    seen = 0
    for line in text.split("\n"):
        if not line.strip():
            continue
        seen += 1
        if seen > 20:
            break
        if _JOB.match(line):
            return "jcl"
        if _PROC.match(line):
            return "proc"
        if _PROGID.search(line):
            return "cobol"
        if _DFHMSD.search(line):
            return "bms"
        if _CSECT.match(line):
            return "asm"
        if _PLI.search(line):
            return "pli"
        if _REXX.match(line):
            return "rexx"
    return None
