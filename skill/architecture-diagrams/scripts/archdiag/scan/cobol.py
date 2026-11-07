from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from ..model import Evidence, Node, Ref
from . import ScanContext

# --------------------------------------------------------------------------
# Source preparation: sequence area, comments, continuation, literal masking
# --------------------------------------------------------------------------

AREA_B_WIDTH = 65  # columns 8-72

_VERBS = frozenset("""
ACCEPT ADD ALTER CALL CANCEL CLOSE COMPUTE CONTINUE DELETE DISPLAY DIVIDE
ELSE END END-CALL END-EVALUATE END-IF END-PERFORM END-READ EVALUATE EXEC EXIT
GO GOBACK IF INITIALIZE INSPECT MERGE MOVE MULTIPLY NEXT NOT ON OPEN PERFORM
READ RELEASE RETURN REWRITE SEARCH SET SORT START STOP STRING SUBTRACT
UNSTRING WHEN WRITE EXCEPTION RETURNING USING GIVING
""".split())


def _is_fixed(lines: List[str]) -> bool:
    """Fixed format unless the text clearly starts inside columns 1-6 (free format)."""
    from ..textio import six_char_area
    if six_char_area(lines):
        return True  # any six characters in columns 1-6 of a strongly COBOL-shaped file (B12)
    fixed = free = blank7 = 0
    for ln in lines:
        if not ln.strip():
            continue
        head = ln[:6]
        if len(ln) > 6 and ln[6] in "*/-" and not head.strip(" 0123456789"):
            fixed += 1
        elif head.strip().isdigit():
            fixed += 1
        elif (re.fullmatch(r"[A-Za-z0-9]*\d[A-Za-z0-9]*", head) and len(ln) > 6
              and ln[6] in " */-dD"):
            fixed += 1  # alphanumeric sequence area such as PRG001
        elif not head.strip():
            if not ln[6:7].strip():
                blank7 += 1
        elif ln[0] != "*":
            free += 1
    if fixed:
        return True
    return not free > blank7


def _cut(s: str, delim: Optional[str]) -> Tuple[str, Optional[str]]:
    """Drop a trailing '*>' comment; return (text, delimiter still open at end of line)."""
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if delim:
            if ch == delim:
                if i + 1 < n and s[i + 1] == delim:
                    i += 1
                else:
                    delim = None
        elif ch in "'\"":
            delim = ch
        elif ch == "*" and i + 1 < n and s[i + 1] == ">":
            return s[:i].rstrip(), delim
        i += 1
    return s.rstrip(), delim


_FORMAT_DIRECTIVE = re.compile(
    r"^\s*(?:>>\s*SOURCE\s+FORMAT(?:\s+IS)?\s+(FREE|FIXED)\b"
    r"|\$SET\s+SOURCEFORMAT\s*\(?\s*[\"'](FREE|FIXED)[\"'])", re.I)


class _Piece:
    __slots__ = ("line", "text", "glue", "delim")

    def __init__(self, line: int, text: str, glue: str, delim: Optional[str]) -> None:
        self.line = line
        self.text = text
        self.glue = glue
        self.delim = delim


class _Src:
    """The code of one source file as a single string with offset -> line mapping."""

    def __init__(self, text: str) -> None:
        raw_lines = text.split("\n")
        fixed = _is_fixed(raw_lines)
        pieces: List[_Piece] = []
        self.line_text: Dict[int, str] = {}
        for no, raw in enumerate(raw_lines, 1):
            raw = raw.rstrip("\r")
            fm = _FORMAT_DIRECTIVE.match(raw)
            if fm:
                fixed = (fm.group(1) or fm.group(2)).upper() == "FIXED"
                continue
            if fixed:
                ind = raw[6] if len(raw) > 6 else " "
                if ind in "*/":
                    continue
                body = raw[7:72]
            else:
                if raw[:1] in ("*", "/"):
                    continue
                body = raw
                ind = " "
            if not body.strip():
                continue
            self.line_text[no] = body.strip()
            if ind == "-" and pieces:
                prev = pieces[-1]
                if prev.delim:
                    prev.text = prev.text.ljust(AREA_B_WIDTH)
                    s = body.lstrip()
                    if s[:1] in ("'", '"'):
                        s = s[1:]
                    txt, dl = _cut(s, prev.delim)
                    pieces.append(_Piece(no, txt, "", dl))
                else:
                    txt, dl = _cut(body.strip(), None)
                    pieces.append(_Piece(no, txt, " ", dl))
                continue
            txt, dl = _cut(body, None)
            pieces.append(_Piece(no, txt, "\n", dl))
        out: List[str] = []
        self.starts: List[int] = []
        self.plines: List[int] = []
        pos = 0
        for i, p in enumerate(pieces):
            glue = p.glue if i else ""
            pos += len(glue)
            self.starts.append(pos)
            self.plines.append(p.line)
            out.append(glue)
            out.append(p.text)
            pos += len(p.text)
        self.blob = "".join(out)
        self.masked = _mask(self.blob)

    def line_of(self, off: int) -> int:
        if not self.plines:
            return 1
        lo, hi = 0, len(self.starts)
        while lo < hi:  # last piece starting at or before off
            mid = (lo + hi) // 2
            if self.starts[mid] <= off:
                lo = mid + 1
            else:
                hi = mid
        return self.plines[max(lo - 1, 0)]


def _mask(s: str) -> str:
    """Replace the inside of every string literal with '_' (quotes and newlines kept)."""
    out: List[str] = []
    delim: Optional[str] = None
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if delim:
            if ch == "\n":
                delim = None
                out.append(ch)
            elif ch == delim:
                if i + 1 < n and s[i + 1] == delim:
                    out.append("__")
                    i += 1
                else:
                    delim = None
                    out.append(ch)
            else:
                out.append("_")
        else:
            if ch in "'\"":
                delim = ch
            out.append(ch)
        i += 1
    return "".join(out)


# --------------------------------------------------------------------------
# COPY ... REPLACING
# --------------------------------------------------------------------------

def _rtokens(s: str) -> List[Tuple[str, int, int]]:
    """COBOL text words for REPLACING: literals, words, and the separators ( ) : and a
    period followed by a blank. Blanks, commas and semicolons only separate (IBM: the
    colon is a separator, so ==:TAG:== can replace part of a name)."""
    out: List[Tuple[str, int, int]] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch.isspace() or ch in ",;":
            i += 1
        elif ch in "'\"":
            j = i + 1
            while j < n and s[j] != "\n":
                if s[j] == ch:
                    if j + 1 < n and s[j + 1] == ch:
                        j += 2
                        continue
                    break
                j += 1
            j = min(j + 1, n)
            out.append((s[i:j], i, j))
            i = j
        elif ch in "():" or (ch == "." and (i + 1 == n or s[i + 1].isspace())):
            out.append((ch, i, i + 1))
            i += 1
        else:
            j = i
            while j < n and not (s[j].isspace() or s[j] in "'\"():,;"
                                 or (s[j] == "." and (j + 1 == n or s[j + 1].isspace()))):
                j += 1
            out.append((s[i:j], i, j))
            i = j
    return out


def _tkey(tok: str) -> str:
    return tok if tok[:1] in ("'", '"') else tok.upper()


def _operand_text(raw: str) -> str:
    """The text an operand stands for: pseudo-text without its == delimiters, else as is."""
    if raw.startswith("==") and raw.endswith("==") and len(raw) >= 4:
        return raw[2:-2].strip()
    return raw.strip()


def _replace_blob(blob: str, pairs: List[List[str]]
                  ) -> Tuple[str, List[Tuple[int, int, bool]], Optional[str]]:
    """Apply REPLACING ``pairs`` ([mode, operand, by-operand], mode "" / LEADING /
    TRAILING) to ``blob``. Returns (new text, chunks, error): chunks are (new offset,
    original offset, replaced) so a new offset maps back to its original line."""
    pats = []
    for mode, frm, to in pairs:
        ft = [_tkey(t) for t, _a, _b in _rtokens(_operand_text(frm))]
        if not ft:
            return blob, [], "empty operand %s" % frm
        if mode and (len(ft) != 1 or ft[0][:1] in ("'", '"')):
            return blob, [], "%s operand must be one word: %s" % (mode, frm)
        pats.append((mode, ft, _operand_text(to)))
    toks = _rtokens(blob)
    out: List[str] = []
    chunks: List[Tuple[int, int, bool]] = []
    size = 0
    pos = 0

    def emit(text: str, orig: int, replaced: bool) -> None:
        nonlocal size
        if text:
            chunks.append((size, orig, replaced))
            out.append(text)
            size += len(text)

    i = 0
    while i < len(toks):
        hit = False
        for mode, ft, tt in pats:
            if not mode:
                k = len(ft)
                if [_tkey(t[0]) for t in toks[i:i + k]] == ft:
                    a0, b0 = toks[i][1], toks[i + k - 1][2]
                    emit(blob[pos:a0], pos, False)
                    emit(tt, a0, True)
                    pos, i, hit = b0, i + k, True
                    break
                continue
            w, a0, b0 = toks[i]
            if w[:1] in ("'", '"') or len(w) < len(ft[0]):
                continue
            if mode == "LEADING" and w.upper().startswith(ft[0]):
                span = (a0, a0 + len(ft[0]))
            elif mode == "TRAILING" and w.upper().endswith(ft[0]):
                span = (b0 - len(ft[0]), b0)
            else:
                continue
            emit(blob[pos:span[0]], pos, False)
            emit(tt, span[0], True)
            emit(blob[span[1]:b0], span[1], False)
            pos, i, hit = b0, i + 1, True
            break
        if not hit:
            i += 1
    emit(blob[pos:], pos, False)
    return "".join(out), chunks, None


def apply_replacing(text: str, pairs: List[List[str]]) -> Tuple[str, Optional[str]]:
    """``text`` with COPY REPLACING ``pairs`` applied, and why they could not be (or None)."""
    new, _chunks, err = _replace_blob(text, pairs)
    return new, err


class _ReplacedSrc:
    """A _Src whose code had COPY REPLACING applied; offsets map back to original lines."""

    def __init__(self, orig: "_Src", pairs: List[List[str]]) -> None:
        self.orig = orig
        self.blob, self.chunks, self.error = _replace_blob(orig.blob, pairs)
        self.masked = _mask(self.blob)
        self.line_text = orig.line_text
        self._starts = [c[0] for c in self.chunks]

    def line_of(self, off: int) -> int:
        import bisect
        k = bisect.bisect_right(self._starts, off) - 1
        if k < 0:
            return self.orig.line_of(0)
        new0, orig0, replaced = self.chunks[k]
        return self.orig.line_of(orig0 if replaced else orig0 + (off - new0))


def _copy_clause(blob: str, start: int) -> Tuple[int, Optional[List[List[str]]], Optional[str]]:
    """The rest of a COPY statement after its name: (offset of its closing period,
    REPLACING pairs or None, why REPLACING could not be read or None)."""
    i, n = start, len(blob)
    end = n
    unended: Optional[str] = None  # the statement that starts where no period ended COPY
    while i < n:
        if blob[i] == "\n":
            w = re.match(r"\s*([A-Za-z][\w-]*)", blob[i + 1:i + 80])
            if w and (w.group(1).upper() in _VERBS or w.group(1).upper() == "COPY") \
                    and w.group(1).upper() not in ("BY", "IN"):
                end, unended = i, w.group(1).upper()
                break
        if blob.startswith("==", i):
            j = blob.find("==", i + 2)
            if j < 0:
                break
            i = j + 2
            continue
        ch = blob[i]
        if ch in "'\"":
            j = blob.find(ch, i + 1)
            i = n if j < 0 else j + 1
            continue
        if ch == "." and (i + 1 == n or blob[i + 1].isspace()):
            end = i
            break
        i += 1
    clause = blob[start:end]
    items: List[str] = []
    k, m = 0, len(clause)
    while k < m:
        if clause[k].isspace() or clause[k] in ",;":
            k += 1
            continue
        if clause.startswith("==", k):
            j = clause.find("==", k + 2)
            if j < 0:
                return end, None, "unclosed =="
            items.append(clause[k:j + 2])
            k = j + 2
        elif clause[k] in "'\"":
            q = clause[k]
            j = k + 1
            while j < m:
                if clause[j] == q:
                    if j + 1 < m and clause[j + 1] == q:
                        j += 2
                        continue
                    break
                j += 1
            items.append(clause[k:j + 1])
            k = j + 1
        elif clause[k] in "()":
            items.append(clause[k])
            k += 1
        else:
            j = k
            while j < m and not (clause[j].isspace() or clause[j] in ",;()"):
                j += 1
            items.append(clause[k:j])
            k = j
    up = [x.upper() for x in items]
    p = 0
    if p < len(up) and up[p] in ("OF", "IN"):
        p += 2
    if p < len(up) and up[p] == "SUPPRESS":
        p += 1
    if p >= len(up) or up[p] != "REPLACING":
        return end, None, None
    p += 1
    pairs: List[List[str]] = []
    while p < len(items):
        mode = ""
        if up[p] in ("LEADING", "TRAILING"):
            mode = up[p]
            p += 1
        if p >= len(items) or up[p] == "BY":
            return end, None, "an operand is missing before BY"
        frm = items[p]
        if p + 1 >= len(items) or up[p + 1] != "BY":
            return end, None, ("%s is not followed by BY (qualified or subscripted "
                               "operands are not read)" % frm)
        if p + 2 >= len(items) or up[p + 2] in ("BY", "LEADING", "TRAILING"):
            return end, None, "BY without an operand after %s" % frm
        pairs.append([mode, frm, items[p + 2]])
        p += 3
    if not pairs:
        return end, None, "REPLACING without operands"
    if unended:
        return end, None, "no period ends the COPY statement before %s" % unended
    return end, pairs, None


# --------------------------------------------------------------------------
# Patterns (applied to the masked text; values are read from the original)
# --------------------------------------------------------------------------

_I = re.I
_NB = r"(?<![\w-])"
_LIT = r"(['\"])_*\1"

_PROGRAM_ID = re.compile(_NB + r"PROGRAM-ID\b", _I)
# on the masked text a quoted name is quotes around '_'s: its value is read from the blob
_END_PROGRAM = re.compile(_NB + r"END\s+PROGRAM\s+((['\"])_*\2|[A-Za-z0-9#$@][\w#$@-]*)\s*\.?",
                          _I)
_PROGRAM_NAME = re.compile(r"\s*\.?\s*['\"]?([A-Za-z0-9#$@][\w#$@-]*)")
_EXEC = re.compile(_NB + r"EXEC\s+(SQL|CICS)\b", _I)
_END_EXEC = re.compile(_NB + r"END-EXEC\b", _I)
_COPY = re.compile(_NB + r"COPY\s+((['\"])_*\2|[A-Za-z0-9][\w#$@-]*)", _I)
_CALL = re.compile(_NB + r"CALL\s+((['\"])_*\2|[A-Za-z][\w-]*)", _I)
_SELECT_FILE = re.compile(
    _NB + r"SELECT\s+(?:OPTIONAL\s+)?([A-Za-z][\w-]*)\s+ASSIGN\s+(?:TO\s+)?"
    r"((['\"])_*\3|[A-Za-z0-9][\w#$@-]*)", _I)
_OPEN = re.compile(_NB + r"OPEN\s+(?=INPUT|OUTPUT|I-O|EXTEND)", _I)
_VALUE_ITEM = re.compile(
    _NB + r"(\d{1,2})\s+([A-Za-z][\w-]*)\s+((?:[^.]|\.(?=\S))*?)"
    r"(?<![\w-])VALUES?\s+(?:IS\s+|ARE\s+)?((['\"])_*\5)", _I)
_MOVE = re.compile(
    _NB + r"MOVE\s+(?:CORR(?:ESPONDING)?\s+)?((['\"])_*\2|[A-Za-z][\w-]*)\s+TO\s+", _I)
_IDENT = re.compile(r"\s*([A-Za-z][\w-]*)")
_QUAL = re.compile(r"\s+(?:OF|IN)\s+[A-Za-z][\w-]*", _I)
_SUBSCR = re.compile(r"\s*\([^)]*\)")
_SORT = re.compile(_NB + r"(?:SORT|MERGE)\s+[A-Za-z][\w-]*", _I)
_PARA = re.compile(
    r"(?m)^[ ]*(?:[A-Za-z0-9][\w-]*[ ]+SECTION(?:[ ]+\d+)?|([A-Za-z0-9][\w-]*))[ ]*\.[ ]*$")
_IF = re.compile(_NB + r"IF\b", _I)
_INLINE_LOOP = re.compile(
    _NB + r"PERFORM\s+(?:WITH\s+TEST\s+(?:BEFORE|AFTER)\s+)?(?:UNTIL|VARYING)\b"
    r"|" + _NB + r"PERFORM\s+(?:\d+|[A-Za-z][\w-]*)\s+TIMES\b", _I)
_END_IF = re.compile(_NB + r"END-IF\b", _I)
_EVAL = re.compile(_NB + r"EVALUATE\b", _I)
_END_EVAL = re.compile(_NB + r"END-EVALUATE\b", _I)
_FIGURATIVE = frozenset("""SPACE SPACES ZERO ZEROS ZEROES LOW-VALUE LOW-VALUES HIGH-VALUE
HIGH-VALUES QUOTE QUOTES NULL NULLS""".split())
_STRING_INTO = re.compile(_NB + r"STRING\b[^.]{0,600}?\bINTO\s+([A-Za-z][\w-]*)", _I)
_UNSTRING_INTO = re.compile(_NB + r"UNSTRING\b[^.]{0,600}?\bINTO\s+([^.]{0,300})", _I)
_READ_INTO = re.compile(_NB + r"READ\s+[A-Za-z][\w-]*[^.]{0,300}?\bINTO\s+([A-Za-z][\w-]*)", _I)
_ACCEPT = re.compile(_NB + r"ACCEPT\s+([A-Za-z][\w-]*)", _I)
_DATA_DIV = re.compile(_NB + r"DATA\s+DIVISION\b", _I)
_PROC_DIV = re.compile(_NB + r"PROCEDURE\s+DIVISION\b", _I)
_LINKAGE = re.compile(_NB + r"LINKAGE\s+SECTION\b", _I)
_LEVEL_ITEM = re.compile(_NB + r"\d{1,2}\s+([A-Za-z][\w-]*)")
_ARG_TOK = re.compile(r"(['\"])_*\1|[A-Za-z][\w-]*|\d+|\.")

MQ_PUTGET = {"MQPUT": "put", "MQPUT1": "put", "MQGET": "get"}
MQ_API = frozenset("""
MQCONN MQCONNX MQDISC MQOPEN MQCLOSE MQINQ MQSET MQCMIT MQBACK MQBEGIN MQSUB
MQSUBRQ MQCRTMH MQDLTMH MQSETMP MQINQMP MQDLTMP MQMHBUF MQBUFMH MQCB MQCTL
MQSTAT
""".split())
_MODES = {"INPUT": "input", "OUTPUT": "output", "I-O": "i-o", "EXTEND": "extend"}

_SQL_TOKEN = re.compile(
    r"'_*'"
    r"|:[\w#$@-]+(?:\.[\w-]+)*"
    r"|\d[\w.]*"
    r"|(?:[A-Za-z_#$@][\w#$@]*|\"_*\")(?:\.(?:[A-Za-z_#$@][\w#$@]*|\"_*\")){0,2}"
    r"|\S")
_SQL_NOT_TABLE = frozenset(
    "SELECT TABLE LATERAL UNNEST ONLY FINAL NEW OLD XMLTABLE JSON_TABLE VALUES".split())
_ALIAS_STOP = frozenset("""
WHERE GROUP ORDER HAVING UNION EXCEPT INTERSECT JOIN INNER LEFT RIGHT FULL CROSS
NATURAL ON USING FETCH WITH FOR SET OPTIMIZE QUERY READ ISOLATION SKIP LIMIT
OFFSET CONCURRENT INTO VALUES WHEN THEN ELSE END SELECT AND OR
""".split())
_FUNC_FROM = frozenset("EXTRACT TRIM SUBSTRING POSITION OVERLAY".split())
_DUMMY_TABLES = frozenset(["SYSIBM.SYSDUMMY1", "SYSDUMMY1"])

_CICS_READ = frozenset("READ STARTBR READNEXT READPREV RESETBR ENDBR".split())
_CICS_WRITE = frozenset("WRITE REWRITE DELETE".split())


IBM_COPYBOOKS = frozenset("""DFHAID DFHBMSCA DFHEIBLK DFHCOMMAREA SQLCA SQLDA CMQV CMQODV
CMQMDV CMQPMOV CMQGMOV""".split())
_SYSTEM_CALLS = frozenset("DSNTIAR DSNTIAC DSNHLI CBLTDLI AIBTDLI".split())


def _is_system(op: str, name: str) -> bool:
    """IBM-supplied copybooks and run-time routines: kept, but flagged for the resolver."""
    n = name.upper()
    if op == "copy":
        return n in IBM_COPYBOOKS
    if op == "call":
        return (n in _SYSTEM_CALLS or n in MQ_API or n in MQ_PUTGET
                or n.startswith(("CEE", "ILBO", "IGZ")))
    return False


def _unq(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] in "'\"" and text[-1] == text[0]:
        q = text[0]
        return text[1:-1].replace(q + q, q)
    return text


# --------------------------------------------------------------------------
# Scanner
# --------------------------------------------------------------------------

class _Scan:
    def __init__(self, repo: str, relpath: str, text: str, src=None) -> None:
        self.repo = repo
        self.rel = relpath
        self.src = src if src is not None else _Src(text)
        self.refs: List[Ref] = []
        self.nodes: List[Node] = []
        s = self.src
        # EXEC blocks, and the COBOL text with them blanked out
        self.execs: List[Tuple[str, int, int]] = []
        cm = list(s.masked)
        pos = 0
        while True:
            m = _EXEC.search(s.masked, pos)
            if not m:
                break
            e = _END_EXEC.search(s.masked, m.end())
            nxt = _EXEC.search(s.masked, m.end())
            if e and (not nxt or e.start() < nxt.start()):
                end, after = e.start(), e.end()
            elif nxt:
                end, after = nxt.start(), nxt.start()
            else:
                end, after = len(s.masked), len(s.masked)
            self.execs.append((m.group(1).upper(), m.end(), end))
            for i in range(m.start(), after):
                if cm[i] != "\n":
                    cm[i] = " "
            pos = max(after, m.end())
        self.cm = "".join(cm)
        self.segs: Optional[List[Tuple[int, int]]] = None  # pieces of the program scanned

    # -- helpers --------------------------------------------------------
    def ev(self, off: int) -> Evidence:
        line = self.src.line_of(off)
        return Evidence(self.repo, self.rel, line, self.src.line_text.get(line, ""))

    def lit(self, s: int, e: int) -> str:
        """Value of the literal whose quotes are at s and e-1 (e exclusive)."""
        return _unq(self.src.blob[s:e])

    def add(self, pid: str, op: str, kind: str, name: Optional[str], off: int,
            reason: Optional[str] = None, candidates: Optional[List[str]] = None,
            attrs: Optional[dict] = None) -> None:
        at = dict(attrs or {})
        if name and _is_system(op, name):
            at["system"] = True
        self.refs.append(Ref(pid, op, kind, name, self.ev(off), reason,
                             list(candidates or []), at))

    # -- program discovery ----------------------------------------------
    def programs(self, stem: str) -> List[Tuple[str, List[Tuple[int, int]], int]]:
        """(PROGRAM-ID, text segments, offset of PROGRAM-ID) per program. With END PROGRAM
        markers, programs nest (a stack): the outer program's code after END PROGRAM of a
        nested one is the outer program's again. Without them each program runs to the
        next PROGRAM-ID."""
        s = self.src
        n = len(s.masked)
        found: List[Tuple[str, int]] = []
        for m in _PROGRAM_ID.finditer(s.masked):
            nm = _PROGRAM_NAME.match(s.blob, m.end())
            if nm:
                found.append((nm.group(1).upper(), m.start()))
        if not found:
            return [(stem.upper(), [(0, n)], 0)]
        ends = [((self.lit(m.start(1), m.end(1)) if m.group(2) else m.group(1)).strip().upper(),
                 m.start(), m.end()) for m in _END_PROGRAM.finditer(self.cm)]
        if not ends:
            out = []
            for i, (pid, start) in enumerate(found):
                end = found[i + 1][1] if i + 1 < len(found) else n
                out.append((pid, [(start if i else 0, end)], start))
            return out
        events = sorted([(at, 0, pid, at) for pid, at in found]
                        + [(a0, 1, pid, b0) for pid, a0, b0 in ends])
        segs: Dict[int, List[Tuple[int, int]]] = {}
        order: List[Tuple[str, int]] = []
        stack: List[Tuple[int, int]] = []  # (program index, start of its open segment)
        for at, kind, pid, end in events:
            if kind == 0:
                if stack:
                    k, st = stack[-1]
                    segs[k].append((st, at))
                idx = len(order)
                order.append((pid, at))
                segs[idx] = []
                stack.append((idx, 0 if idx == 0 else at))
            else:
                names = [order[k][0] for k, _st in stack]
                if pid not in names:
                    continue  # END PROGRAM of a name not open: ignore it
                while stack:
                    k, st = stack.pop()
                    segs[k].append((st, end))
                    if order[k][0] == pid:
                        break
                if stack:
                    k, _st = stack[-1]
                    stack[-1] = (k, end)
        last = n
        while stack:
            k, st = stack.pop()
            segs[k].append((st, last))
        return [(pid, sorted(x for x in segs[i] if x[1] > x[0]) or [(at, at)], at)
                for i, (pid, at) in enumerate(order)]

    def scan_segments(self, pid: str, segs: List[Tuple[int, int]]) -> Dict[str, str]:
        """scan_program over a program made of several pieces of the file: the text of
        every other program is blanked out while it runs."""
        if len(segs) == 1:
            return self.scan_program(pid, segs[0][0], segs[0][1])
        keep = list(self.cm)
        full = self.cm
        out = [" "] * len(full)
        for a, b in segs:
            out[a:b] = keep[a:b]
        for i, ch in enumerate(full):
            if ch == "\n":
                out[i] = "\n"
        self.cm = "".join(out)
        self.segs = segs
        try:
            return self.scan_program(pid, segs[0][0], segs[-1][1])
        finally:
            self.cm = full
            self.segs = None

    # -- one program ----------------------------------------------------
    def scan_program(self, pid: str, a: int, b: int) -> Dict[str, str]:
        s = self.src
        cm = self.cm
        values: Dict[str, List[str]] = {}
        pm = _PROC_DIV.search(cm, a, b)
        pstart = pm.start() if pm else b
        dm = _DATA_DIV.search(cm, a, pstart)
        dstart = dm.start() if dm else a
        other_writes = self.runtime_writes(a, b, dstart, pstart)
        for m in _VALUE_ITEM.finditer(cm, dstart, pstart):
            if m.group(1) == "88":
                continue
            v = self.lit(m.start(4), m.end(4)).strip()
            lst = values.setdefault(m.group(2).upper(), [])
            if v and v not in lst:
                lst.append(v)

        # COPY (with REPLACING kept for the copybook's attributed statements)
        blanks: List[Tuple[int, int]] = []
        for m in _COPY.finditer(cm, a, b):
            name = self.lit(m.start(1), m.end(1)) if m.group(2) else m.group(1)
            name = name.strip().upper()
            end, pairs, err = _copy_clause(s.blob, m.end(1))
            at: dict = {}
            if pairs:
                at["replacing"] = pairs
            if err:
                at["replacing_error"] = "COPY %s REPLACING could not be read (%s)" % (name, err)
            if pairs or err:
                blanks.append((m.end(1), min(end, b)))
            self.add(pid, "copy", "copybook", name, m.start(1), attrs=at)
        if blanks:  # the REPLACING operands are not this program's own statements
            chars = list(cm)
            for x, y in blanks:
                for k in range(x, y):
                    if chars[k] != "\n":
                        chars[k] = " "
            cm = self.cm = "".join(chars)

        # CALL (MQ calls are collected separately)
        mq_calls: List[Tuple[int, str, int]] = []   # (offset, API name, end of match)
        for m in _CALL.finditer(cm, a, b):
            if m.group(2):
                name = self.lit(m.start(1), m.end(1)).strip().upper()
                self.add(pid, "call", "program", name, m.start(1))
                if name in MQ_PUTGET or name in MQ_API:
                    mq_calls.append((m.start(), name, m.end()))
            else:
                var = m.group(1)
                self.variable(pid, "call", "program", var, m.start(1),
                              "CALL through variable " + var, values)

        # MOVEs (literal and identifier sources) for MQ queue resolution
        moves = self.collect_moves(a, b)
        self.mq(pid, mq_calls, moves, values, other_writes, a, b)

        # file modes
        files = self.file_modes(a, b)

        # EXEC blocks
        for kind, bs, be in self.execs:
            if bs < a or bs >= b:
                continue
            if self.segs and not any(x <= bs < y for x, y in self.segs):
                continue
            if any(x <= bs < y for x, y in blanks):
                continue  # an EXEC inside a COPY REPLACING operand is not this program's
            if kind == "SQL":
                self.sql(pid, bs, be, values)
            else:
                self.cics(pid, bs, be, values)
        return files

    def runtime_writes(self, a: int, b: int, dstart: int, pstart: int) -> Set[str]:
        """Data items that run-time code can overwrite with something unknown."""
        cm = self.cm
        out: Set[str] = set()
        lm = _LINKAGE.search(cm, dstart, pstart)
        if lm:
            for m in _LEVEL_ITEM.finditer(cm, lm.end(), pstart):
                out.add(m.group(1).upper())
        for rx in (_STRING_INTO, _READ_INTO, _ACCEPT):
            for m in rx.finditer(cm, pstart, b):
                out.add(m.group(1).upper())
        for m in _UNSTRING_INTO.finditer(cm, pstart, b):
            for t in re.finditer(r"[A-Za-z][\w-]*", re.sub(r"\([^)]*\)", " ", m.group(1))):
                w = t.group(0).upper()
                if w in _VERBS or w in ("DELIMITER", "COUNT", "IN", "TALLYING", "POINTER", "WITH"):
                    if w in _VERBS:
                        break
                    continue
                out.add(w)
        return out

    def variable(self, pid: str, op: str, kind: str, var: str, off: int, reason: str,
                 values: Dict[str, List[str]]) -> None:
        self.add(pid, op, kind, None, off, reason, values.get(var.upper(), []))

    # -- files ----------------------------------------------------------
    def file_modes(self, a: int, b: int) -> Dict[str, str]:
        s = self.src
        dd_of: Dict[str, str] = {}
        for m in _SELECT_FILE.finditer(self.cm, a, b):
            op = self.lit(m.start(2), m.end(2)) if m.group(3) else m.group(2)
            dd_of[m.group(1).upper()] = _ddname(op.strip())
        seen: Dict[str, set] = {}
        for m in _OPEN.finditer(self.cm, a, b):
            pos = m.end()
            mode = None
            while True:
                t = re.compile(r"[\s,]*([A-Za-z][\w-]*)").match(self.cm, pos, b)
                if not t:
                    break
                w = t.group(1).upper()
                if w in _MODES:
                    mode = _MODES[w]
                elif w in ("WITH", "NO", "REWIND", "LOCK") or w in _VERBS:
                    if w in _VERBS or w == "LOCK":
                        break
                elif mode and w in dd_of:
                    seen.setdefault(w, set()).add(mode)
                else:
                    break
                pos = t.end()
                if self.cm[pos:pos + 1] == ".":
                    break
        for m in _SORT.finditer(self.cm, a, b):
            end = self.cm.find(".", m.end(), b)
            seg = self.cm[m.end(): end if end >= 0 else b]
            for kw, mode in (("USING", "input"), ("GIVING", "output")):
                u = re.search(r"(?<![\w-])" + kw + r"\s+((?:[A-Za-z][\w-]*\s*)+)", seg, _I)
                if not u:
                    continue
                for w in re.findall(r"[A-Za-z][\w-]*", u.group(1)):
                    if w.upper() not in dd_of:
                        break
                    seen.setdefault(w.upper(), set()).add(mode)
        out: Dict[str, str] = {}
        for fname, modes in seen.items():
            if len(modes) == 1:
                mode = next(iter(modes))
            elif modes == {"output", "extend"}:
                mode = "extend"
            else:
                mode = "i-o"
            out[dd_of[fname]] = mode
        return out

    # -- MOVE / MQ ------------------------------------------------------
    def collect_moves(self, a: int, b: int) -> Dict[str, List[Tuple[int, str, str]]]:
        """target name -> [(offset, 'lit'|'var', source)] in program order."""
        out: Dict[str, List[Tuple[int, str, str]]] = {}
        cm = self.cm
        for m in _MOVE.finditer(cm, a, b):
            if m.group(2):
                kind, srcv = "lit", self.lit(m.start(1), m.end(1)).strip()
            else:
                kind, srcv = "var", m.group(1).upper()
            pos = m.end()
            while True:
                t = _IDENT.match(cm, pos, b)
                if not t or t.group(1).upper() in _VERBS:
                    break
                out.setdefault(t.group(1).upper(), []).append((m.start(), kind, srcv))
                pos = t.end()
                q = _QUAL.match(cm, pos, b)
                if q:
                    pos = q.end()
                sb = _SUBSCR.match(cm, pos, b)
                if sb:
                    pos = sb.end()
                c = re.compile(r"\s*,").match(cm, pos, b)
                if c:
                    pos = c.end()
        return out

    def mq(self, pid: str, calls: List[Tuple[int, str, int]],
           moves: Dict[str, List[Tuple[int, str, str]]],
           values: Dict[str, List[str]], other_writes: Set[str], a: int, b: int) -> None:
        if not any(n in MQ_PUTGET for _, n, _ in calls):
            return
        cm = self.cm
        OBJ = "*OBJECTNAME*"
        mv = {k: list(v) for k, v in moves.items()}
        mv[OBJ] = sorted(x for tgt, lst in moves.items() if tgt.endswith("OBJECTNAME")
                         for x in lst)
        vals = dict(values)
        vals[OBJ] = []
        for k, v in values.items():
            if k.endswith("OBJECTNAME"):
                vals[OBJ].extend(x for x in v if x not in vals[OBJ])
        obj_written = sorted(w for w in other_writes if w.endswith("OBJECTNAME"))
        pheads = [(m.start(), m.group(0).strip().split()[0].rstrip(".").upper())
                  for m in _PARA.finditer(cm, a, b)
                  if (m.group(1) or "").upper() not in _VERBS]
        pstarts = [p for p, _n in pheads]

        def para(off: int) -> int:
            n = 0
            for p in pstarts:
                if p <= off:
                    n += 1
            return n

        def looped(off: int) -> bool:
            """The paragraph holding ``off`` has a loop that can run it again: an inline
            PERFORM UNTIL / VARYING / n TIMES, or a GO TO the paragraph itself."""
            k = para(off)
            start = pstarts[k - 1] if k > 0 else a
            end = pstarts[k] if k < len(pstarts) else b
            seg = cm[start:end]
            if _INLINE_LOOP.search(seg):
                return True
            name = pheads[k - 1][1] if k > 0 else None
            return bool(name and re.search(_NB + r"GO\s+(?:TO\s+)?" + re.escape(name)
                                           + r"(?![\w-])", seg, _I))

        def conditional(off: int) -> bool:
            start = cm.rfind(".", a, off) + 1
            seg = cm[max(start, a):off]
            if len(_IF.findall(seg)) > len(_END_IF.findall(seg)):
                return True
            return len(_EVAL.findall(seg)) > len(_END_EVAL.findall(seg))

        def reaching(offs: List[int], at: int) -> Tuple[List[int], bool]:
            """Writes that can reach 'at'; second value tells whether an earlier
            (initial) value is certainly overwritten."""
            prior = [o for o in offs if o < at]
            # a write anywhere outside this paragraph/section may run (PERFORM, GO TO)
            if not prior or any(para(o) != para(at) for o in offs):
                return list(offs), False
            # a write after 'at' in the same paragraph reaches it when the paragraph loops
            if any(o > at for o in offs) and looped(at):
                return list(offs), False
            out: List[int] = []
            for o in reversed(prior):
                out.append(o)
                if not conditional(o):
                    return out, True
            return out, False

        def var_names(var: str, at: int, depth: int) -> Tuple[List[str], Optional[str]]:
            names: List[str] = []
            runtime: Optional[str] = None
            if var == OBJ:
                if obj_written:
                    runtime = obj_written[0]
            elif var in other_writes:
                runtime = var
            entries = {m[0]: m for m in mv.get(var, [])}
            reach, complete = reaching(sorted(entries), at)
            for o in reach:
                _, kind, srcv = entries[o]
                if kind == "lit":
                    cand, rt = [srcv], None
                elif srcv in _FIGURATIVE:
                    continue
                elif depth < 4:
                    cand, rt = var_names(srcv, o, depth + 1)
                    if not cand and not rt:
                        rt = var if var != OBJ else srcv
                else:
                    cand, rt = [], (var if var != OBJ else srcv)
                for n in cand:
                    if n not in names:
                        names.append(n)
                runtime = runtime or rt
            if not complete or runtime:
                for n in vals.get(var, []):
                    if n not in names:
                        names.append(n)
            return names, runtime

        def args_of(end: int) -> List[Optional[str]]:
            m = re.compile(r"\s+USING\s+", _I).match(self.cm, end)
            if not m:
                return []
            stop = self.cm.find(".", m.end())
            seg = self.cm[m.end(): stop if stop >= 0 else len(self.cm)]
            seg = re.sub(r"\([^)]*\)", " ", seg)
            args: List[Optional[str]] = []
            qualifier = False
            special: Optional[str] = None  # "ADDRESS" / "LENGTH" waiting for OF X
            toks = [t.group(0) for t in _ARG_TOK.finditer(seg)]
            for k, w in enumerate(toks):
                up = w.upper()
                if special:
                    if up == "OF" and not special.endswith(" OF"):
                        special += " OF"
                        continue
                    # ADDRESS OF X / LENGTH OF X is one argument; never X's handle
                    args.append("%s %s" % (special, up) if w[0].isalpha() else None)
                    special = None
                    continue
                if qualifier:  # the group after OF / IN qualifies the argument before it
                    qualifier = False
                    continue
                if up in ("ADDRESS", "LENGTH") and k + 1 < len(toks) \
                        and toks[k + 1].upper() == "OF":
                    special = up
                    continue
                if up in ("OF", "IN"):
                    qualifier = True
                    continue
                if up in ("BY", "REFERENCE", "CONTENT", "VALUE"):
                    continue
                if up in _VERBS:
                    break
                args.append(up if w[0].isalpha() else None)
            return args

        opens: List[Tuple[int, Optional[str]]] = []   # (offset, handle variable)
        for off, name, end in calls:
            if name == "MQOPEN":
                ar = args_of(end)
                opens.append((off, ar[3] if len(ar) > 3 else None))

        open_names: Dict[int, List[str]] = {}
        for o, _h in opens:
            open_names[o] = var_names(OBJ, o, 0)[0]
        distinct_opens = set(tuple(v) for v in open_names.values())
        for off, name, end in calls:
            op = MQ_PUTGET.get(name)
            if not op:
                continue
            at_list = [off]
            untied: Optional[str] = None
            if name != "MQPUT1":
                ar = args_of(end)
                hobj = ar[1] if len(ar) > 1 else None
                mine = [o for o, h in opens if h and h == hobj]
                if mine:
                    at_list, _ = reaching(mine, off)
                elif len(opens) > 1 and len(distinct_opens) > 1:
                    # the handle can't be tied to one MQOPEN and the opens name different
                    # queues: every queue the program opens is a candidate, never the last
                    # MOVE before the call
                    at_list = [o for o, _h in opens]
                    untied = hobj or "?"
            names: List[str] = []
            runtime: Optional[str] = None
            for at in at_list:
                n, rt = var_names(OBJ, at, 0)
                for x in n:
                    if x not in names:
                        names.append(x)
                runtime = runtime or rt
            if untied is not None and not runtime:
                self.add(pid, op, "queue", None, off,
                         "MQ handle %s can't be tied to one MQOPEN; the program opens: %s"
                         % (untied, ", ".join(names)), names)
            elif runtime:
                self.add(pid, op, "queue", None, off,
                         "queue name set at run time (%s)" % runtime, names)
            elif len(names) == 1:
                self.add(pid, op, "queue", names[0], off)
            elif names:
                self.add(pid, op, "queue", None, off,
                         "queue name depends on run-time path: " + ", ".join(names), names)
            else:
                self.add(pid, op, "queue", None, off, "queue name not found in program")

    # -- SQL ------------------------------------------------------------
    def sql(self, pid: str, bs: int, be: int, values: Dict[str, List[str]]) -> None:
        s = self.src
        body = re.sub(r"--[^\n]*", lambda m: " " * len(m.group()), s.masked[bs:be])
        toks = [(m.group(0), m.start() + bs) for m in _SQL_TOKEN.finditer(body)]
        if not toks:
            return
        up = [t.upper() for t, _ in toks]
        kind = up[0]

        def name_at(i: int) -> Optional[str]:
            if i >= len(toks):
                return None
            t = toks[i][0]
            if t.upper() in _SQL_NOT_TABLE or not re.match(r'^("|[A-Za-z_#$@])', t):
                return None
            return s.blob[toks[i][1]: toks[i][1] + len(t)]

        if kind == "INCLUDE":
            n = name_at(1)
            if n:
                self.add(pid, "copy", "copybook", n.upper(), toks[1][1])
            return
        if kind in ("PREPARE", "EXECUTE") and (kind == "PREPARE" or up[1:2] == ["IMMEDIATE"]):
            if kind == "EXECUTE" and up[1:2] != ["IMMEDIATE"]:
                return
            host = next((t for t, _ in toks[1:] if t.startswith(":")), None)
            self.add(pid, "select", "table", None, toks[0][1],
                     "dynamic SQL" + (" in " + host[1:] if host else "")
                     + ", table and operation set at run time")
            return
        if kind == "DECLARE" and "CURSOR" not in up[:6]:
            return
        if kind == "CALL" and len(toks) > 1:
            # a DB2 stored procedure: a call to the program behind it (spec §7.6 registers
            # stored procedures by name); the SQL name may differ from its EXTERNAL NAME
            t = toks[1][0]
            if t.startswith(":"):
                self.add(pid, "call", "program", None, toks[1][1],
                         "stored procedure name set at run time (%s)" % t[1:])
                return
            n = name_at(1)
            if n:
                sql_name = n.replace('"', "")
                self.add(pid, "call", "program", sql_name.split(".")[-1].upper(), toks[1][1],
                         "DB2 stored procedure %s: its program (EXTERNAL NAME) may have "
                         "another name" % sql_name, attrs={"sql_call": sql_name})
            return
        if kind in ("LOCK", "FETCH", "OPEN", "CLOSE", "COMMIT", "ROLLBACK", "WHENEVER",
                    "CONNECT", "CALL", "GRANT", "REVOKE", "SAVEPOINT", "RELEASE"):
            return

        ctes = set()
        if kind == "WITH":
            depth = 0
            for i, t in enumerate(up):
                if t == "(":
                    depth += 1
                elif t == ")":
                    depth -= 1
                elif depth == 0 and i and re.match(r"[A-Z_#$@]", t):
                    j = i + 1
                    if j < len(up) and up[j] == "(":
                        d = 0
                        while j < len(up):
                            d += up[j] == "("
                            d -= up[j] == ")"
                            j += 1
                            if d == 0:
                                break
                    if j + 1 < len(up) and up[j] == "AS" and up[j + 1] == "(":
                        ctes.add(t)

        def record(op: str, i: int) -> bool:
            n = name_at(i)
            if not n or n.upper() in ctes or n.upper() in _DUMMY_TABLES:
                return False
            self.add(pid, op, "table", n, toks[i][1])
            return True

        def table_list(op: str, i: int, many: bool) -> None:
            j = i
            while j < len(toks):
                if up[j] == "(" or not record(op, j):
                    return
                j += 1
                if j < len(toks) and up[j] == "AS":
                    j += 2
                elif j < len(toks) and re.match(r"[A-Z_#$@\"]", up[j]) and up[j] not in _ALIAS_STOP:
                    j += 1
                if many and j < len(toks) and up[j] == ",":
                    j += 1
                    continue
                return

        if kind == "INSERT" and up[1:2] == ["INTO"]:
            record("insert", 2)
        elif kind == "UPDATE":
            record("update", 1)
        elif kind == "MERGE" and up[1:2] == ["INTO"]:
            record("update", 2)
        stack: List[bool] = []
        for i, t in enumerate(up):
            if t == "(":
                stack.append(i > 0 and up[i - 1] in _FUNC_FROM)
            elif t == ")":
                if stack:
                    stack.pop()
            elif t == "FROM" and not any(stack) and up[i - 1:i] != ["DISTINCT"]:
                if kind == "DELETE" and i == 1:
                    record("delete", i + 1)
                else:
                    table_list("select", i + 1, True)
            elif t == "JOIN":
                table_list("select", i + 1, False)
            elif t == "USING" and kind == "MERGE":
                table_list("select", i + 1, False)

    # -- CICS -----------------------------------------------------------
    def cics_options(self, bs: int, be: int) -> Tuple[str, List[Tuple[str, int, int]]]:
        m = self.src.masked
        pos = bs
        words: List[Tuple[str, int, int]] = []
        cmd = ""
        word = re.compile(r"\s*([A-Za-z][\w-]*)")
        while pos < be:
            w = word.match(m, pos, be)
            if not w:
                nxt = re.compile(r"\s*\S").match(m, pos, be)
                if not nxt:
                    break
                pos = nxt.end()
                continue
            name = w.group(1).upper()
            pos = w.end()
            p = re.compile(r"\s*\(").match(m, pos, be)
            if p:
                depth = 1
                j = p.end()
                while j < be and depth:
                    depth += m[j] == "("
                    depth -= m[j] == ")"
                    j += 1
                words.append((name, p.end(), j - 1))
                pos = j
            else:
                if not cmd:
                    cmd = name
                else:
                    words.append((name, -1, -1))
        return cmd, words

    def cics(self, pid: str, bs: int, be: int, values: Dict[str, List[str]]) -> None:
        cmd, opts = self.cics_options(bs, be)
        d = {n: (s, e) for n, s, e in opts if s >= 0}
        s = self.src

        def arg(name: str) -> Optional[Tuple[str, bool, int]]:
            if name not in d:
                return None
            a, e = d[name]
            raw = s.blob[a:e]
            lead = len(raw) - len(raw.lstrip())
            t = raw.strip()
            is_lit = bool(s.masked[a + lead: a + lead + 1] in ("'", '"'))
            return (_unq(t).strip() if is_lit else t), is_lit, a + lead

        def emit(op: str, kind: str, optname: str, label: str, attrs: Optional[dict] = None,
                 alt: Optional[str] = None) -> None:
            r = arg(optname)
            if r is None and alt:
                r = arg(alt)
            if r is None:
                return
            val, is_lit, off = r
            if is_lit:
                self.add(pid, op, kind, val, off, attrs=attrs)
                return
            if re.match(r"^[A-Za-z][\w-]*$", val):
                reason = (f"{cmd} to {val}, name set at run time" if optname == "PROGRAM"
                          else f"{label} {val}, name set at run time")
                self.add(pid, op, kind, None, off, reason, values.get(val.upper(), []), attrs)
            else:
                self.add(pid, op, kind, None, off,
                         f"{label} {val}, name set at run time", [], attrs)

        if cmd == "LINK":
            emit("link", "program", "PROGRAM", "LINK PROGRAM")
        elif cmd == "HANDLE" and any(n == "ABEND" for n, _s, _e in opts):
            # the abend handler program is LINKed to when the task abends
            cmd = "HANDLE ABEND"
            emit("link", "program", "PROGRAM", "HANDLE ABEND PROGRAM")
        elif cmd == "XCTL":
            emit("xctl", "program", "PROGRAM", "XCTL PROGRAM")
        elif cmd == "START":
            emit("start", "transaction", "TRANSID", "START TRANSID")
        elif cmd == "RETURN":
            emit("return_transid", "transaction", "TRANSID", "RETURN TRANSID")
        elif cmd == "SEND" and "MAP" in d:
            emit("send_map", "map", "MAPSET", "SEND MAPSET", alt="MAP")
        elif cmd in _CICS_READ or cmd in _CICS_WRITE:
            emit("cics_file", "cicsfile", "FILE", cmd + " FILE",
                 {"io": "read" if cmd in _CICS_READ else "write"}, alt="DATASET")


def _ddname(operand: str) -> str:
    """ddname from an ASSIGN operand such as UT-S-CLMIN, S-CLMIN or 'CLMIN'."""
    op = operand.upper()
    m = re.match(r"^(?:[A-Z]{2}-)?[A-Z]-([A-Z0-9#$@]+)$", op)
    return m.group(1) if m else op


def _stem(relpath: str) -> str:
    base = relpath.replace("\\", "/").rsplit("/", 1)[-1]
    dot = base.rfind(".")
    return base[:dot] if dot > 0 else base


def scan_cobol(repo: str, relpath: str, text: str,
               ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    sc = _Scan(repo, relpath, text)
    if not _PROGRAM_ID.search(sc.src.masked) and not _PROC_DIV.search(sc.src.masked):
        # COBOL text with no PROGRAM-ID and no PROCEDURE DIVISION is a copybook member,
        # whatever its extension (copylib/CLMREC.cbl)
        return scan_copybook(repo, relpath, text, ctx)
    nodes: List[Node] = []
    for pid, segs, at in sc.programs(_stem(relpath)):
        files = sc.scan_segments("program:" + pid, segs)
        nodes.append(Node("program:" + pid, "program", pid, repo,
                          [sc.ev(at)], {"files": files}))
    return nodes, sc.refs


def copybook_refs_replaced(name: str, repo: str, relpath: str, text: str,
                           pairs: List[List[str]]) -> Tuple[List[Ref], Optional[str]]:
    """The statements of copybook ``name`` (one copy of it) after a COPY ... REPLACING
    applied ``pairs``, and why the pairs could not be applied (then the refs are the
    copybook's own, unreplaced)."""
    plain = _Scan(repo, relpath, text)
    src = _ReplacedSrc(plain.src, pairs)
    sc = plain if src.error else _Scan(repo, relpath, text, src)
    sc.scan_program("copybook:" + name, 0, len(sc.cm))
    return sc.refs, src.error


def scan_copybook(repo: str, relpath: str, text: str,
                  ctx: ScanContext) -> Tuple[List[Node], List[Ref]]:
    name = _stem(relpath).upper()
    first, first_text = 1, ""
    for no, ln in enumerate(text.split("\n"), 1):
        if ln.strip():
            first, first_text = no, ln.strip()
            break
    # the copybook's own statements, attributed later to every program that COPYs it
    sc = _Scan(repo, relpath, text)
    sc.scan_program("copybook:" + name, 0, len(sc.cm))
    if sc.refs:
        ctx.copybook_refs.setdefault(name, []).extend(sc.refs)
    ctx.copybook_texts.setdefault(name, []).append((repo, relpath, text))
    return [Node("copybook:" + name, "copybook", name, repo,
                 [Evidence(repo, relpath, first, first_text)])], []
