from __future__ import annotations

import re
from typing import List, Optional, Tuple

_SCHEME_HOST = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:)?//[^/?#]*")


def _is_param(seg: str) -> bool:
    if len(seg) > 1 and seg[0] == ":":
        return True
    if seg.startswith("${") and seg.endswith("}"):
        return True
    return len(seg) > 1 and seg[0] == "{" and seg[-1] == "}"


def norm_path(path: str) -> str:
    """Normalize a REST path for matching.

    Every ``{x}``, ``:x`` and ``${x}`` segment becomes ``{}``, a trailing ``/`` is
    stripped, and a scheme/host/port prefix is dropped. The query string and fragment
    are dropped, repeated slashes collapse, and the result always starts with ``/``.
    """
    p = (path or "").strip()
    p = _SCHEME_HOST.sub("", p, count=1)
    for stop in ("?", "#"):
        i = p.find(stop)
        if i >= 0:
            p = p[:i]
    segs = [s for s in p.split("/") if s]
    return "/" + "/".join("{}" if _is_param(s) else s for s in segs)


# A relative generation: (+1), (0), (-1). An unsigned (n) is stripped too: a PDS member
# name can't start with a digit, so a number in parentheses is always a GDG generation
# (JCL reads an unsigned positive number as +n).
_GDG = re.compile(r"\(\s*[+-]?\d+\s*\)$")
# An absolute generation: the last qualifier GnnnnVnn of a GDG base.
_ABS_GDG = re.compile(r"\.G\d{4}V\d{2}$")
HTTP_VERBS = frozenset("GET POST PUT DELETE PATCH HEAD OPTIONS TRACE ANY".split())
_HOST = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:)?//([^/?#]*)")


def norm_dataset(name: str, env_quals: List[str]) -> Tuple[str, Optional[str]]:
    """Matching key for a dataset name, and the environment qualifier dropped (or None).

    The key is upper-case with a GDG relative generation (``(+1)``, ``(0)``, ``(-1)``) or
    an absolute generation (``.G0012V00``, see ``is_absolute_gdg``) removed, so every
    generation matches its base. If the first qualifier is one of ``env_quals`` (compared case-insensitively)
    and more qualifiers follow, it is removed and returned. ``PDS(MEMBER)`` keeps its member.
    """
    key = _GDG.sub("", (name or "").strip().upper()).strip()
    key = _ABS_GDG.sub("", key)
    quals = {q.strip().upper() for q in env_quals if q and q.strip()}
    first, dot, rest = key.partition(".")
    if dot and rest and first in quals:
        return rest, first
    return key, None


def is_absolute_gdg(name: str) -> bool:
    """True when the dataset name ends in an absolute GDG generation (``.G0012V00``)."""
    return bool(_ABS_GDG.search(_GDG.sub("", (name or "").strip().upper()).strip()))


def split_http(target: str) -> Tuple[str, str, Optional[str]]:
    """``"GET https://host:443/a/{id}"`` -> ``("GET", "/a/{}", "host")``.

    The method is upper-cased (``ANY`` when the target has none), the path goes through
    ``norm_path``, and the host is lower-cased without user info or port, or None when the
    target has no ``//host`` part.
    """
    t = (target or "").strip()
    method, sep, url = t.partition(" ")
    if not sep and method.upper() in HTTP_VERBS:
        return method.upper(), "/", None
    if not sep or "/" in method:
        method, url = "ANY", t
    url = url.strip()
    m = _HOST.match(url)
    host: Optional[str] = None
    if m:
        h = m.group(1).rsplit("@", 1)[-1]
        if h.startswith("["):  # IPv6 literal
            h = h[: h.find("]") + 1] if "]" in h else h
        else:
            h = h.split(":", 1)[0]
        host = h.lower() or None
    return method.upper(), norm_path(url), host
