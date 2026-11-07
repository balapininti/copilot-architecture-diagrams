from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from .repos import with_long_path


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def read_source(path: Path) -> str:
    """Read a source file as UTF-8, then Windows-1252, then Latin-1; LF line endings."""
    data = with_long_path(_read_bytes, str(path))  # type: ignore[assignment]
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

# Extensions of files no scanner or collector looks at (data, docs, web assets): their text is
# never read, which saves decoding most of a large Angular or Java repo. Files that z/OS
# Connect needs (package.xml, openapi.json and anything under a zosconnect folder) are exempt.
# .json and .xml are NOT listed: collect_mq looks for CKBR starts in any file, so they are read.
_NO_TEXT_EXTS = frozenset([
    ".md", ".html", ".htm", ".css", ".scss", ".sass", ".less", ".svg", ".csv",
    ".log", ".map", ".xsd", ".woff", ".woff2", ".ttf", ".eot", ".otf", ".webp",
    ".bmp", ".tif", ".tiff", ".mp3", ".mp4", ".gz", ".tgz", ".7z", ".rar", ".tar", ".bin",
    ".pyc", ".o", ".obj", ".a", ".lib", ".db", ".sqlite", ".xlsx", ".xls", ".docx", ".doc",
    ".pptx", ".ppt",
])
_ZC_NAMES = frozenset(["package.xml", "openapi.json", "swagger.json"])


def needs_text(relpath: str) -> bool:
    """False when classify() could not give this path a type from its name alone and no
    scanner reads its text, so the file need not be read. Extensionless files, unknown
    extensions and every extension in ``_EXT`` are read (they may be classified by content)."""
    parts = relpath.replace("\\", "/").lower().split("/")
    name = parts[-1]
    dot = name.rfind(".")
    ext = name[dot:] if dot > 0 else ""
    if ext not in _NO_TEXT_EXTS:
        return True
    return name in _ZC_NAMES or "zosconnect" in parts[:-1]


_JOB = re.compile(r"^//(?!\*)\S+\s+JOB\b", re.I)
_PROC = re.compile(r"^//(?!\*)\S*\s+PROC\b", re.I)
_PROGID = re.compile(r"\bPROGRAM-ID\b", re.I)
_CSECT = re.compile(r"^\S*\s+CSECT\b", re.I)
_DFHMSD = re.compile(r"\bDFHMSD\b", re.I)
_PLI = re.compile(r"\bPROCEDURE\s+OPTIONS\s*\(\s*MAIN\b", re.I)
_REXX = re.compile(r"^\s*/\*\s*REXX", re.I)
_IDDIV = re.compile(r"(?<![\w-])(?:IDENTIFICATION|ID)\s+DIVISION\b", re.I)
SNIFF_LINES = 200  # code lines (comments and blanks not counted) read to decide a type


def _is_comment(line: str) -> bool:
    """A comment line of COBOL (column 7 ``*`` or ``/``), JCL (``//*``), SQL (``--``),
    assembler (column 1 ``*``) or a ``/*`` line."""
    if len(line) > 6 and line[6] in "*/" and not line[:6].strip(" 0123456789") \
            or len(line) > 6 and line[6] in "*/" and line[:6].isalnum():
        return True
    st = line.lstrip()
    return line.startswith(("//*", "*")) or st.startswith(("--", "/*", "*>"))


_ZC_API = re.compile(r"<\s*(?:\w+:)?zosConnectApi\b")
_ZC_MANIFEST = re.compile(r"^provider:", re.M)
_ZC_PROPS_PROVIDER = re.compile(r"^\s*provider\s*[=:]\s*cics\s*$", re.I | re.M)
_ZC_PROPS_PROGRAM = re.compile(r"^\s*(?:program|executableName)\s*[=:]", re.M)


def _is_zosconnect(parts: List[str], ext: str, text: str) -> bool:
    """z/OS Connect project files, recognized by name and content (see scan/zosconnect.py)."""
    name = parts[-1]
    if name == "package.xml":
        return bool(_ZC_API.search(text))
    if name == "manifest.yml":
        return bool(_ZC_MANIFEST.search(text)) and "providerProperties" in text
    if name == "zosasset.yaml":
        return True
    if name == "operation.yaml":
        return len(parts) >= 4 and parts[-4] == "operations"
    if ext == ".properties":
        return bool(_ZC_PROPS_PROVIDER.search(text) and _ZC_PROPS_PROGRAM.search(text))
    return False


def classify(relpath: str, text: str) -> Optional[str]:
    """Return the file type for a repo-relative path and its text, or None."""
    rel = relpath.replace("\\", "/")
    parts = rel.lower().split("/")
    ext = ""
    dot = parts[-1].rfind(".")
    if dot > 0:
        ext = parts[-1][dot:]
    if _is_zosconnect(parts, ext, text):
        return "zosconnect"
    if ext in _EXT:
        return _EXT[ext]
    if "zosconnect" in parts[:-1]:
        return "zosconnect"
    seen = 0
    for line in text.split("\n"):
        if not line.strip():
            continue
        if _REXX.match(line):
            return "rexx"
        if _is_comment(line):
            continue  # a long comment header must not hide the code below it
        seen += 1
        if seen > SNIFF_LINES:
            break
        if _IDDIV.search(line):
            return "cobol"
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
    if ext in COPY_EXTS and any(d in COPY_DIRS for d in parts[:-1]):
        return "copybook"
    return None


# copybook libraries exported from PDSes: folder names, and the extensions (or none) a
# member file in them may carry
COPY_DIRS = frozenset(["copy", "copys", "copybook", "copybooks", "copylib", "copylibs", "cpy",
                       "cpylib", "cpylibs"])
COPY_EXTS = frozenset(["", ".copy", ".inc", ".txt", ".mem", ".cpybk"])


_SEQ = re.compile(r"\s*[A-Za-z0-9]+\s*")


def drop_sequence_area(line: str) -> str:
    """Cut columns 73-80 when they hold a sequence number (80-byte z/OS records).

    Only cut when the line fits an 80-byte record, column 72 is blank or a continuation
    mark (+ - *), and columns 73-80 hold one alphanumeric word, so a long free-form line
    from a distributed platform keeps its text.
    """
    if 72 < len(line) <= 80 and line[71] in " +-*" and _SEQ.fullmatch(line[72:]):
        return line[:72]
    return line
