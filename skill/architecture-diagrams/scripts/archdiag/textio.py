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

# COBOL structure lines that look like code: the keyword starts the line's code area
# (fixed format: after columns 1-7; free format: near column 1)
# columns 1-6 must be blank, digits or a sequence-number shape (letters and digits with at
# least one digit, as cobol._is_fixed), never prose such as "Step 1" or "1. The"
# B12: the alphanumeric branch is exactly six characters
_SEQ6 = r"(?=[A-Za-z]{0,5}\d)[A-Za-z0-9]{6}"
_AREA = r"^(?:(?:[ 0-9]{6}|" + _SEQ6 + r") {1,8}| {0,7})"
# any six non-blank characters (PRGABC, AB-123): only for a file strongly COBOL-shaped
_AREA_ANY = r"^(?:(?:[ 0-9]{6}|\S{6}) {1,8}| {0,7})"


def _structure(area: str):
    return (re.compile(area + r"(?:IDENTIFICATION|ID)\s+DIVISION\s*\.", re.I),
            re.compile(area + r"PROGRAM-ID\s*\.?\s*['\"]?[A-Za-z0-9#$@][\w#$@-]*", re.I),
            re.compile(area + r"(?:DATA|PROCEDURE|ENVIRONMENT)\s+DIVISION\b", re.I),
            re.compile(area + r"0?1\s+[A-Za-z][\w-]*\s*(?:\.|\s(?:PIC|PICTURE|VALUE|"
                       r"REDEFINES|OCCURS|USAGE|COMP)\b)", re.I))


_ID_HEADER, _PROGID_LINE, _DIVISION_LINE, _LEVEL01_LINE = _structure(_AREA)
# columns 1-6 blank or digits only: no letters, so prose can't pass for a sequence area
_NUM_STRUCTURE = _structure(r"^(?:[ 0-9]{6} {1,8}| {0,7})")
_ANY_STRUCTURE = _structure(_AREA_ANY)
_SIX_AREA_LINE = re.compile(r"^(\S{6})[ *\-/]")
_SIX_AREA_CODE = re.compile(r"^\S{6} {1,4}(?:PROGRAM-ID\b|PROCEDURE\s+DIVISION\b)", re.I)
_VERB_COL12 = re.compile(r"^\S{6} {5,}(?:MOVE|CALL|PERFORM|DISPLAY|GOBACK|STOP|IF|EXEC|"
                         r"COMPUTE|ADD|SET|READ|WRITE|OPEN|CLOSE|EVALUATE|ACCEPT)\b", re.I)
SIX_AREA_SHARE = 0.8  # share of non-blank lines that must show the 6-character area


def lettered_area(lines: List[str]) -> bool:
    """True when columns 1-6 of a file read as a real sequence area that holds letters
    (PRG001, PRGABC, AB-123), not prose (fix round 1 of B12):

    * at least 80% of non-blank lines hold six non-blank characters then an indicator
      column (blank, ``*``, ``-``, ``/``);
    * the area is sequence-like: most of those values are one repeated value, or most
      hold a digit;
    * the code is COBOL-shaped: a verb in column 12 or later, or at least half of the
      non-comment area lines end with a period."""
    full = [ln.expandtabs(8).rstrip() for ln in lines if ln.strip()]
    if not full:
        return False
    hits = [(m.group(1), ln) for ln in full for m in [_SIX_AREA_LINE.match(ln)] if m]
    if len(hits) < SIX_AREA_SHARE * len(full):
        return False
    values = [v for v, _ in hits]
    top = max(values.count(v) for v in set(values))
    digits = sum(1 for v in values if any(c.isdigit() for c in v))
    if top < SIX_AREA_SHARE * len(values) and digits < SIX_AREA_SHARE * len(values):
        return False
    code = [ln for _, ln in hits if ln[6] not in "*/"]
    if any(_VERB_COL12.match(ln) for ln in code):
        return True
    return bool(code) and 2 * sum(1 for ln in code if ln.endswith(".")) >= len(code)


def six_char_area(lines: List[str]) -> bool:
    """True when a file is strongly COBOL-shaped with any six non-blank characters in
    columns 1-6 (B12): a lettered sequence area (see lettered_area), and PROGRAM-ID or
    PROCEDURE DIVISION starting in column 8 or later after such an area."""
    return lettered_area(lines) and any(
        _SIX_AREA_CODE.match(ln.expandtabs(8)) for ln in lines if ln.strip())


# code-shaped COBOL headers for the not-scanned reason: the header ends the line with a period
_HEADER_ONLY = re.compile(
    _AREA_ANY + r"(?:(?:IDENTIFICATION|ID|DATA|PROCEDURE|ENVIRONMENT)\s+DIVISION"
    r"(?:\s+USING\b[^.]*)?|PROGRAM-ID\s*\.?\s*['\"]?[A-Za-z0-9#$@][\w#$@-]*['\"]?)\s*\.\s*$",
    re.I)


def _looks_like_cobol(at: int, code: List[str], structure=None) -> bool:
    """A line naming the IDENTIFICATION DIVISION or PROGRAM-ID is COBOL only when it
    looks like code and the sniffed code also holds another part of a program
    (PROGRAM-ID, a DATA / PROCEDURE / ENVIRONMENT DIVISION header or an 01-level item),
    so prose that mentions them is not a program. ``at`` is the line's index in ``code``."""
    id_header, progid, division, level01 = structure or (
        _ID_HEADER, _PROGID_LINE, _DIVISION_LINE, _LEVEL01_LINE)
    line = code[at]
    if id_header.match(line):
        others = (progid, division, level01)
    elif progid.match(line):
        others = (id_header, division, level01)
    else:
        return False
    return any(rx.match(c) for k, c in enumerate(code) if k != at for rx in others)


def unscanned_reason(text: str) -> str:
    """Why a mainframe-looking file of no type was not analyzed: code-shaped COBOL
    structure lines, prose that only mentions COBOL divisions, or other mainframe text."""
    lines = [ln.expandtabs(8) for ln in text[:20000].split("\n")]
    if any(_HEADER_ONLY.match(ln.rstrip()) for ln in lines):
        return ("looks like COBOL but its type was not recognised (no other part of a "
                "program, or an unusual sequence area), so it was not analyzed")
    if _IDDIV.search(text[:20000]) or re.search(
            r"\b(?:DATA|PROCEDURE|ENVIRONMENT)\s+DIVISION\b|\bPROGRAM-ID\b", text[:20000], re.I):
        return "prose mentioning COBOL divisions, not code, so it was not analyzed"
    return "looks like mainframe source but its type could not be recognised, so it was not " \
           "analyzed"


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
    code: List[str] = []
    rexx = False  # a /* REXX line ends the sniff: it is REXX unless an earlier line decides
    for line in text.split("\n"):
        if not line.strip():
            continue
        if _REXX.match(line):
            rexx = True
            break
        if _is_comment(line):
            continue  # a long comment header must not hide the code below it
        code.append(line.expandtabs(8))  # a tab-indented member reads like column 9
        if len(code) >= SNIFF_LINES:
            break
    head = text.split("\n")[:SNIFF_LINES * 2]
    # letters in columns 1-6 count only for a file whose whole area reads as one (B12)
    lettered = lettered_area(head)
    base = None if lettered else _NUM_STRUCTURE
    wide = _ANY_STRUCTURE if lettered and six_char_area(head) else None
    for at, line in enumerate(code):
        if _IDDIV.search(line) or _PROGID.search(line):
            if _looks_like_cobol(at, code, base) or (wide and _looks_like_cobol(at, code, wide)):
                return "cobol"
            continue
        if _JOB.match(line):
            return "jcl"
        if _PROC.match(line):
            return "proc"
        if _DFHMSD.search(line):
            return "bms"
        if _CSECT.match(line):
            return "asm"
        if _PLI.search(line):
            return "pli"
    if rexx:
        return "rexx"
    if ext in COPY_EXTS and any(d in COPY_DIRS for d in parts[:-1]) and (
            ext in ("", ".copy", ".cpybk") or _COBOL_TEXT.search(text)):
        return "copybook"  # a .txt / .inc there must also read like COBOL
    return None


# copybook libraries exported from PDSes: folder names, and the extensions (or none) a
# member file in them may carry
COPY_DIRS = frozenset(["copy", "copys", "copybook", "copybooks", "copylib", "copylibs", "cpy",
                       "cpylib", "cpylibs"])
COPY_EXTS = frozenset(["", ".copy", ".inc", ".txt", ".mem", ".cpybk"])
# COBOL-looking text: a data item with a level number, or a procedure statement
_COBOL_TEXT = re.compile(
    r"(?im)^.{0,12}\b(?:0?[1-9]|[1-4]\d|66|77|88)\s+[A-Za-z][\w-]*(?:\s|\.)"
    r"|\b(?:EXEC\s+(?:SQL|CICS)|PERFORM|MOVE\s+\S+\s+TO|CALL\s+['\"])")


_SEQ_NUMBER = re.compile(r"\s*[A-Za-z0-9]*\d[A-Za-z0-9]*\s*")
SEQ_SHARE = 0.8  # share of long lines that must hold a sequence number


def has_sequence_area(lines: List[str]) -> bool:
    """True when the file is 80-byte records numbered in columns 73-80: of its non-blank
    lines at least 73 characters long, at least 80% are at most 80 long and hold one
    alphanumeric word with a digit in columns 73-80."""
    long = [ln for ln in lines if len(ln.rstrip()) >= 73]
    if not long:
        return False
    numbered = sum(1 for ln in long
                   if len(ln.rstrip()) <= 80 and _SEQ_NUMBER.fullmatch(ln.rstrip()[72:]))
    return numbered >= SEQ_SHARE * len(long)


def drop_sequence_areas(lines: List[str]) -> List[str]:
    """Cut columns 73-80 from every line when the file has a sequence area (see
    has_sequence_area), so a token running through column 72 loses the number glued to
    it; otherwise every line is kept whole, so a word after column 72 of a free-form file
    is never dropped. z/OS MQSC and DFHCSDUP input ignore columns 73-80."""
    if not has_sequence_area(lines):
        return list(lines)
    return [ln[:72] for ln in lines]
