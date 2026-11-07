"""Hand-built view graphs and geometry checks for the layout tests.

claims_landscape() and claims_job() copy diagrams 1 and 2 of
docs/samples/mainframe-samples.html.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from archdiag.views import VEdge, VGroup, VNode, ViewGraph

Point = Tuple[float, float]


def claims_landscape() -> ViewGraph:
    groups = [
        VGroup("repo:claims-portal", "claims-portal", "#3b82f6"),
        VGroup("repo:claims-api", "claims-api", "#16a34a"),
        VGroup("repo:claims-online", "claims-online", "#9333ea"),
        VGroup("repo:claims-batch", "claims-batch", "#ca8a04"),
        VGroup("repo:claims-db", "claims-db", "#ea580c"),
        VGroup("repo:shared-copybooks", "shared-copybooks", "#0891b2"),
    ]
    nodes = [
        VNode("person:adjuster", "Claims adjuster", "Person", kind="person"),
        VNode("app:portal", "Claims Portal", "Angular", kind="application",
              group="repo:claims-portal"),
        VNode("app:api", "Claims API", "Java · Spring Boot", kind="application",
              group="repo:claims-api"),
        VNode("queue:CLM.REQ", "CLM.REQ / CLM.RSP", "IBM MQ queues", kind="queue"),
        VNode("app:online", "Claims Online", "CICS · COBOL", kind="application",
              group="repo:claims-online"),
        VNode("app:batch", "Claims Nightly Batch", "JCL · COBOL", kind="application",
              group="repo:claims-batch"),
        VNode("app:db", "Claims DB2", "DB2 for z/OS", kind="datastore",
              group="repo:claims-db"),
        VNode("dataset:PROD.CLAIMS.EXTRACT", "PROD.CLAIMS.EXTRACT", "Sequential dataset",
              kind="dataset"),
        VNode("external:FINANCE", "Finance", "External system", kind="external"),
        VNode("missing:reader:PROD.CLAIMS.EXTRACT", "no reader found", kind="missing",
              status="loose"),
        VNode("app:shared-copybooks", "shared-copybooks", "CLMREC, PAYREC",
              kind="application", group="repo:shared-copybooks"),
    ]
    edges = [
        VEdge("person:adjuster", "app:portal", "uses"),
        VEdge("app:portal", "app:api", "REST"),
        VEdge("app:api", "queue:CLM.REQ", "MQ PUT"),
        VEdge("queue:CLM.REQ", "app:online", "triggers"),
        VEdge("app:online", "app:db", "SQL · CLAIM, POLICY"),
        VEdge("app:batch", "app:db", "reads CLAIM, updates PAYMENT"),
        VEdge("app:batch", "dataset:PROD.CLAIMS.EXTRACT", "writes"),
        VEdge("dataset:PROD.CLAIMS.EXTRACT", "external:FINANCE", "suggested: NDM",
              status="partial"),
        VEdge("dataset:PROD.CLAIMS.EXTRACT", "missing:reader:PROD.CLAIMS.EXTRACT",
              "no reader found", status="loose"),
        VEdge("app:shared-copybooks", "app:batch", "COPY ×21", kind="shared_code"),
        VEdge("app:shared-copybooks", "app:online", "COPY ×14", kind="shared_code"),
    ]
    return ViewGraph("Claims landscape", "landscape", None, nodes, edges, groups)


def claims_job() -> ViewGraph:
    nodes = [
        VNode("external:scheduler", "scheduler", "not in repos", kind="external"),
        VNode("job:CLMD100", "CLMD100", "nightly claims", kind="job"),
        VNode("step:CLMD100.STEP010", "SORT", "STEP010", kind="utility", row="lane"),
        VNode("step:CLMD100.STEP020", "CLMB200", "STEP020", kind="program", row="lane"),
        VNode("step:CLMD100.STEP030", "CLMB300", "STEP030", kind="program", row="lane"),
        VNode("step:CLMD100.STEP040", "IEBGENER", "STEP040", kind="utility", row="lane"),
        VNode("dataset:CLM.MASTER.KSDS", "CLM.MASTER.KSDS", "VSAM · read", kind="vsam",
              row="above"),
        VNode("table:CLAIM", "CLAIM", "DB2 table · SELECT", kind="table", row="above"),
        VNode("table:PAYMENT", "PAYMENT", "DB2 table · INSERT", kind="table", row="above"),
        VNode("dataset:PROD.CLAIMS.DAILY", "PROD.CLAIMS.DAILY(+1)", "new generation · written",
              kind="gdg", row="below"),
        VNode("dataset:SYSOUT:CLMR30", "Report CLMR30", "SYSOUT=A", kind="dataset", row="below"),
        VNode("dataset:PROD.CLAIMS.EXTRACT", "PROD.CLAIMS.EXTRACT", "sequential · written",
              kind="dataset", row="below"),
        VNode("missing:reader:PROD.CLAIMS.EXTRACT", "no reader found", kind="missing",
              row="below", status="loose"),
    ]
    edges = [
        VEdge("external:scheduler", "job:CLMD100", "runs", status="partial"),
        VEdge("job:CLMD100", "step:CLMD100.STEP010"),
        VEdge("step:CLMD100.STEP010", "step:CLMD100.STEP020", "&&SORTED"),
        VEdge("step:CLMD100.STEP020", "step:CLMD100.STEP030", "if RC = 0"),
        VEdge("step:CLMD100.STEP030", "step:CLMD100.STEP040", "if RC ≤ 4"),
        VEdge("dataset:CLM.MASTER.KSDS", "step:CLMD100.STEP010", "read"),
        VEdge("table:CLAIM", "step:CLMD100.STEP020", "SELECT"),
        VEdge("step:CLMD100.STEP030", "table:PAYMENT", "INSERT"),
        VEdge("step:CLMD100.STEP020", "dataset:PROD.CLAIMS.DAILY", "write (+1)"),
        VEdge("dataset:PROD.CLAIMS.DAILY", "step:CLMD100.STEP030", "read as (0)"),
        VEdge("step:CLMD100.STEP030", "dataset:SYSOUT:CLMR30", "write"),
        VEdge("step:CLMD100.STEP040", "dataset:PROD.CLAIMS.EXTRACT", "write"),
        VEdge("dataset:PROD.CLAIMS.EXTRACT", "missing:reader:PROD.CLAIMS.EXTRACT",
              "no reader found", status="loose"),
    ]
    return ViewGraph("Job CLMD100", "flow_job", "CLMD100", nodes, edges, [])


def graph_with_cycle() -> ViewGraph:
    nodes = [VNode(n, n) for n in ("A", "B", "C", "D")]
    edges = [VEdge("A", "B"), VEdge("B", "C"), VEdge("C", "A"), VEdge("C", "D"),
             VEdge("D", "D"), VEdge("D", "B")]
    return ViewGraph("cycle", "application", None, nodes, edges, [])


def repomap_of(n: int) -> ViewGraph:
    nodes = [VNode("repo:r%d" % i, "r%d" % i, kind="repo",
                   detail_lines=["file%d.cbl" % i]) for i in range(n)]
    edges = [VEdge("repo:r0", "repo:r%d" % i, "COPY") for i in range(1, n)]
    edges.append(VEdge("repo:r1", "repo:r2", "MQ"))
    edges.append(VEdge("repo:r2", "repo:r1", "DB2"))
    return ViewGraph("repo map", "repomap", None, nodes, edges, [])


def crossing_bait() -> ViewGraph:
    # Listed so that keeping input order would cross almost every edge.
    names = ["a", "b", "c", "x", "y", "z", "p", "q", "r"]
    nodes = [VNode(n, n) for n in names]
    edges = [VEdge("a", "z"), VEdge("b", "y"), VEdge("c", "x"),
             VEdge("x", "r"), VEdge("y", "q"), VEdge("z", "p")]
    return ViewGraph("bait", "application", None, nodes, edges, [])


# ---------------------------------------------------------------- geometry

def no_box_overlaps(boxes: Dict[str, object], margin: float) -> bool:
    items = list(boxes.values())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if (a.x < b.x + b.w + margin and b.x < a.x + a.w + margin
                    and a.y < b.y + b.h + margin and b.y < a.y + a.h + margin):
                return False
    return True


def on_border(p: Point, box, tol: float = 0.5) -> bool:
    x, y = p
    inside_x = box.x - tol <= x <= box.x + box.w + tol
    inside_y = box.y - tol <= y <= box.y + box.h + tol
    on_v = inside_y and (abs(x - box.x) <= tol or abs(x - box.x - box.w) <= tol)
    on_h = inside_x and (abs(y - box.y) <= tol or abs(y - box.y - box.h) <= tol)
    return on_v or on_h


def contains(outer, inner) -> bool:
    return (outer.x <= inner.x and outer.y <= inner.y
            and inner.x + inner.w <= outer.x + outer.w
            and inner.y + inner.h <= outer.y + outer.h)


def _segments(route: List[Point]):
    return [(route[i], route[i + 1]) for i in range(len(route) - 1)]


def _proper_cross(s1, s2) -> bool:
    (p1, p2), (p3, p4) = s1, s2

    def orient(a, b, c):
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)

    d1, d2 = orient(p3, p4, p1), orient(p3, p4, p2)
    d3, d4 = orient(p1, p2, p3), orient(p1, p2, p4)
    return d1 * d2 < 0 and d3 * d4 < 0


def count_crossings(view: ViewGraph, layout) -> int:
    total = 0
    for i in range(len(view.edges)):
        for j in range(i + 1, len(view.edges)):
            if any(_proper_cross(a, b) for a in _segments(layout.routes[i])
                   for b in _segments(layout.routes[j])):
                total += 1
    return total


def debug_svg(view: ViewGraph, layout) -> str:
    """Rects and polylines only, so a human can eyeball the geometry."""
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%.0f" height="%.0f" '
           'viewBox="0 0 %.0f %.0f">' % (layout.width, layout.height,
                                         layout.width, layout.height),
           '<rect x="0" y="0" width="%.0f" height="%.0f" fill="#ffffff"/>'
           % (layout.width, layout.height)]
    for gid, g in layout.groups.items():
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6" fill="#f1f5f9" '
                   'stroke="#94a3b8" stroke-dasharray="6 4"/>' % (g.x, g.y, g.w, g.h))
    for nid, b in layout.boxes.items():
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6" fill="#dbeafe" '
                   'stroke="#1d4ed8"/>' % (b.x, b.y, b.w, b.h))
    colors = {"confirmed": "#334155", "partial": "#d97706", "loose": "#dc2626"}
    for e, r in zip(view.edges, layout.routes):
        color = "#a16207" if e.kind == "shared_code" else colors.get(e.status, "#334155")
        pts = " ".join("%.1f,%.1f" % p for p in r)
        out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2"/>'
                   % (pts, color))
    for (x, y) in layout.label_at:
        out.append('<rect x="%.1f" y="%.1f" width="6" height="6" fill="#ef4444"/>'
                   % (x - 3, y - 3))
    out.append("</svg>")
    return "\n".join(out)


def app_with_neighbors() -> ViewGraph:
    """An application view: one group across several layers, neighbors outside it."""
    g = "app:claims-online"
    nodes = [
        VNode("queue:CLM.REQ.LQ", "CLM.REQ.LQ", kind="neighbor"),
        VNode("transaction:CLMI", "CLMI", kind="transaction", group=g),
        VNode("program:CLMO100", "CLMO100", group=g),
        VNode("program:CLMO200", "CLMO200", group=g),
        VNode("program:CLMO300", "CLMO300", group=g),
        VNode("map:CLMM01", "CLMM01", kind="map", group=g),
        VNode("table:CLAIM", "CLAIM", kind="neighbor"),
        VNode("table:POLICY", "POLICY", kind="neighbor"),
        VNode("program:CLMB200", "CLMB200", kind="neighbor"),
        VNode("queue:CLM.RSP.LQ", "CLM.RSP.LQ", kind="neighbor"),
    ]
    edges = [
        VEdge("queue:CLM.REQ.LQ", "transaction:CLMI", "triggers"),
        VEdge("transaction:CLMI", "program:CLMO100", "runs"),
        VEdge("program:CLMO100", "program:CLMO200", "LINK"),
        VEdge("program:CLMO200", "program:CLMO300", "XCTL"),
        VEdge("program:CLMO100", "map:CLMM01", "SEND MAP"),
        VEdge("program:CLMO200", "table:CLAIM", "SELECT"),
        VEdge("program:CLMO300", "table:POLICY", "SELECT"),
        VEdge("program:CLMB200", "table:CLAIM", "UPDATE"),
        VEdge("program:CLMO100", "queue:CLM.RSP.LQ", "PUT"),
        VEdge("program:CLMO300", "program:CLMO100", "RETURN", status="partial"),
    ]
    return ViewGraph("Claims Online", "application", "claims-online", nodes, edges,
                     [VGroup(g, "claims-online", "#9333ea")])


def random_view(seed: int) -> ViewGraph:
    import random
    R = random.Random(seed)
    level = R.choice(["landscape", "application", "flow_tx", "flow_job", "repomap"])
    n = R.randint(1, 40)
    groups = [VGroup("g%d" % i, "g%d" % i, "#000000") for i in range(R.randint(0, 5))]
    nodes = [VNode("n%d" % i, "n%d" % i,
                   group=(R.choice(groups).id if groups and R.random() < 0.6 else None),
                   row=R.choice(["lane", "above", "below", None])) for i in range(n)]
    edges = [VEdge("n%d" % R.randrange(n), "n%d" % R.randrange(n))
             for _ in range(R.randint(0, 2 * n))]
    if level in ("flow_job", "repomap"):  # these views carry no groups
        groups = []
        for nd in nodes:
            nd.group = None
    return ViewGraph("random %d" % seed, level, None, nodes, edges, groups)


def foreign_box_in_group(view: ViewGraph, layout) -> bool:
    for gid, g in layout.groups.items():
        for n in view.nodes:
            b = layout.boxes[n.id]
            if n.group != gid and b.x < g.x + g.w and g.x < b.x + b.w \
                    and b.y < g.y + g.h and g.y < b.y + b.h:
                return True
    return False
