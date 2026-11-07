"""What one diagram shows: nodes, edges and groups, ready to lay out and draw.

build_view() cuts the resolved link graph into one of five views (spec section 5):

* ``landscape``   - one box per application, the data stores and queues shared by two or
  more of them, outside systems and the far sides of exchanges; each application's own
  loose ends folded into one ``N loose ends`` box. Lines combined per pair and kind of link.
* ``application`` - one application's members, with what it talks to outside as grey stubs.
* ``flow_job``    - one batch job: its steps in a lane, data read above, data written below.
* ``flow_tx``     - one online path from a transaction, page or endpoint, numbered in order.
* ``repomap``     - one card per repo, one line per link between two repos.

A line is never drawn more certain than the resolver decided. A combined line is
confirmed only if a confirmed edge is under it, otherwise partial if a partial one is,
otherwise loose; folding (``… N more``, ``N loose ends``) keeps lines of different status
apart or takes the least certain. Every loose end and partly known link reaching the view
is drawn, or named in ``notes``. Copilot's suggested links are added here only, as partial;
one a view cannot draw is named in ``notes``.

Fields for the renderers and the links report (Tasks 12-16):

* ``VEdge.underlying``  - the resolver Edges drawn as the line (several when combined).
* ``VEdge.kind``        - ``runtime``, ``shared_code`` (COPY) or ``sequence``: a job's
  step-to-step and SYSOUT lines, drawn like runtime lines but backed by the job's
  structure, not a resolver Edge (``underlying`` holds only folded ``&&temp`` edges).
* ``VNode.underlying``  - the resolver Edges a box stands for (a job step's ``runs`` edge).
* ``VNode.highlight``   - repomap: the first N ``detail_lines`` are files holding link evidence.
"""
from __future__ import annotations

import difflib
from typing import Optional

from archdiag.model import Resolved
from archdiag.views.common import (GROUP_COLORS, LEVELS, MAX_NODES, TX_DEPTH, ScopeError, VEdge,
                                   VGroup, ViewGraph, VNode, _Ctx, combine_status)
from archdiag.views.application import application
from archdiag.views.cap import cap
from archdiag.views.flow_job import cond_label, flow_job
from archdiag.views.flow_tx import flow_tx
from archdiag.views.landscape import landscape
from archdiag.views.repomap import repomap

__all__ = ["build_view", "ScopeError", "MAX_NODES", "TX_DEPTH", "LEVELS", "GROUP_COLORS",
           "VNode", "VEdge", "VGroup", "ViewGraph", "combine_status", "cond_label"]


def build_view(r: Resolved, g, level: str, scope: Optional[str]) -> ViewGraph:
    """The view ``level`` of the resolved graph for ``scope`` (an application, a job name or
    id, a transaction, page route or endpoint, or a repo, by level; none for the landscape).
    Raises ScopeError for an unknown level or a scope that names nothing."""
    if level not in LEVELS:
        hits = difflib.get_close_matches(str(level), list(LEVELS), n=3, cutoff=0.5)
        raise ScopeError("unknown level %r; choose from %s" % (level, ", ".join(LEVELS)),
                         hits or list(LEVELS))
    ctx = _Ctx(r, g)
    if level == "landscape":
        v = landscape(ctx)
        if scope:
            v.notes.append("The landscape shows the whole estate; scope %r was not used." % scope)
    elif level == "application":
        v = application(ctx, scope)
    elif level == "flow_job":
        v = flow_job(ctx, scope)
    elif level == "flow_tx":
        v = flow_tx(ctx, scope)
    else:
        v = repomap(ctx, scope)
    cap(ctx, v)
    return v
