from __future__ import annotations

import re

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
