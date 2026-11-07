"""Resolve dataset, CICS file, table, queue, trigger, REST, transfer and ``uses`` Refs
(spec §7.2-7.5), and list the links between repos.

The rule: a link is solid only when the name is fully worked out from code in the repos and
exactly one thing matches it.

- **Datasets** link ``step -> dataset:<key>`` (``norm_dataset`` key, so environment copies
  share a node when their qualifier is listed). A name holding ``&`` or a Ref with a reason
  is partial. ``&&`` temporaries are keyed by job. DISP=OLD (``update``) becomes ``read`` or
  ``write`` from the step program's ``SELECT ... ASSIGN`` open mode. After all edges are
  built, a dataset only written gets a loose end to ``missing:reader:<key>`` and one only
  read a loose end to ``missing:writer:<key>``; PROC-default, temporary, library and
  unresolved-name uses never count for that.
- **CICS files** go through the CSD ``DSNAME`` to ``program -> dataset``.
- **Tables** match the DDL by schema and name, following aliases.
- **Queues** follow alias and remote definitions; MQ process definitions give ``triggers``
  edges to the CICS transaction; a queue used on one side only gets a partial gap edge.
- **REST** client calls match ``endpoint:`` and ``zosapi:`` nodes by method and path.

Every Edge's evidence is the Ref's evidence first, then the definitions'.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from ..config import Config
from ..model import CONFIRMED, LOOSE, PARTIAL, Edge, Evidence, Inventory, Node, Ref, Resolved
from .common import join, missing, src_label, unknown_name, where
from .names import norm_dataset, norm_path, split_http

TRANSFER_REASON = "file transfer target is outside these repos"
EXTERNAL_REASON = "external or missing service"
BRIDGE_REASON = "CICS-MQ bridge"
NO_READER = "written but never read in these repos"
NO_WRITER = "read but never written in these repos"
NO_CONSUMER = "how this queue reaches CICS isn't in these repos"
NO_PRODUCER = "nothing in these repos puts to this queue"
# the IBM-supplied CICS-MQ bridge monitor: never defined in a user CSD
BRIDGE_MONITOR = "CKBR"
# resources that, without a definition, belong to no repo and link every repo using them
SHARED_KINDS = ("dataset", "queue")


def _defs_reason(node: Node) -> Optional[str]:
    if len(node.evidence) > 1:
        return "ambiguous: defined in %d places: %s" % (
            len(node.evidence), ", ".join(where(e) for e in node.evidence))
    return None


def _status(*reasons: Optional[str]) -> Tuple[str, Optional[str]]:
    reason = join(*reasons)
    return (PARTIAL if reason else CONFIRMED), reason


def _unresolved_reason(name: str) -> str:
    return "symbol in %s has no value in these repos" % name


class _Data:
    def __init__(self, inv: Inventory, config: Config, nodes: Dict[str, Node],
                 edges: List[Edge]) -> None:
        self.inv = inv
        self.quals = {q.strip().upper() for q in config.environment_qualifiers if q.strip()}
        self.nodes = nodes
        self.edges = edges
        # dataset id -> evidence of the uses that count as reads / writes for loose ends
        self.ds_reads: Dict[str, List[Evidence]] = {}
        self.ds_writes: Dict[str, List[Evidence]] = {}
        # queue id -> evidence of puts / gets (an "open" counts as both)
        self.q_puts: Dict[str, List[Evidence]] = {}
        self.q_gets: Dict[str, List[Evidence]] = {}
        self.triggered: Set[str] = set()
        self.step_programs: Dict[str, List[str]] = {}
        self.file_dsn: Dict[str, List[Ref]] = {}
        self.tables_by_name: Dict[str, List[str]] = {}
        self.rest: List[Tuple[str, str, str]] = []  # (node id, METHOD, norm path)
        for ref in inv.refs:
            if ref.op == "runs" and ref.target_kind == "program" and ref.target_name:
                self.step_programs.setdefault(ref.src, []).append(ref.target_name.strip().upper())
            elif ref.op == "file_dataset":
                self.file_dsn.setdefault(ref.src, []).append(ref)
        for node in inv.nodes.values():
            if node.kind == "table":
                name = str(node.attrs.get("name") or node.name.rsplit(".", 1)[-1]).upper()
                self.tables_by_name.setdefault(name, []).append(node.id)
            elif node.kind in ("endpoint", "zosapi"):
                if node.attrs.get("unresolved") or node.id.startswith(node.kind + ":?"):
                    continue  # an endpoint whose path isn't worked out (Ruling 13)
                method, _, path = node.id.split(":", 1)[1].partition(" ")
                self.rest.append((node.id, method.upper(), norm_path(path)))

    # -- shared --------------------------------------------------------------------------
    def add(self, ref: Ref, op: str, dst: str, status: str, reason: Optional[str],
            defs: Optional[List[Evidence]] = None) -> None:
        self.edges.append(Edge(ref.src, op, dst, status, reason, [ref.evidence] + (defs or [])))

    def unknown(self, ref: Ref, kind: str, op: Optional[str] = None,
                written: Optional[str] = None) -> None:
        """PARTIAL to a per-site ``missing:<kind>:?<src>:<line>`` (name not worked out)."""
        reason = ref.reason or (_unresolved_reason(written) if written else "name not worked out")
        nid = missing(self.nodes, kind, unknown_name(ref.src, ref.evidence), reason,
                      ref.candidates)
        if written:
            self.nodes[nid].attrs.setdefault("written_name", written)
        self.add(ref, op or ref.op, nid, PARTIAL, reason)

    # -- datasets ------------------------------------------------------------------------
    def dataset_node(self, name: str, temp_scope: Optional[str]) -> str:
        if temp_scope is not None:
            key, dropped = "%s#%s" % (temp_scope, name), None
        else:
            key, dropped = norm_dataset(name, list(self.quals))
        nid = "dataset:" + key
        node = self.nodes.get(nid)
        if node is None:
            node = Node(nid, "dataset", key if temp_scope is None else name, None, [],
                        {"names": set(), "env_dropped": False})
            if temp_scope is not None:
                node.attrs["temp"] = True
            self.nodes[nid] = node
        node.attrs.setdefault("names", set()).add(name)
        if dropped:
            node.attrs["env_dropped"] = True
        if "&" in name and temp_scope is None:
            node.attrs["unresolved"] = True
        return nid

    def refine(self, ref: Ref) -> str:
        """DISP=OLD (``update``) becomes read/write from the program's open mode."""
        if ref.op != "update":
            return ref.op
        progs = set(self.step_programs.get(ref.src, []))
        dd = str(ref.attrs.get("ddname") or "").upper()
        if len(progs) != 1 or not dd:
            return ref.op
        node = self.nodes.get("program:" + progs.pop())
        files = node.attrs.get("files") if node is not None else None
        mode = str({str(k).upper(): v for k, v in (files or {}).items()}.get(dd) or "").lower()
        if mode == "input":
            return "read"
        if mode in ("output", "extend"):
            return "write"
        return ref.op

    def count(self, dst: str, op: str, ev: Evidence) -> None:
        if op in ("read", "update"):
            self.ds_reads.setdefault(dst, []).append(ev)
        if op in ("write", "update"):
            self.ds_writes.setdefault(dst, []).append(ev)

    def dataset(self, ref: Ref) -> None:
        name = (ref.target_name or "").strip().upper()
        if not name:
            self.unknown(ref, "dataset")
            return
        temp = ref.attrs.get("temp") is True or name.startswith("&&")
        scope = None
        if temp:
            step = self.nodes.get(ref.src)
            job = step.attrs.get("job") if step is not None else None
            scope = src_label(job) if job else src_label(ref.src).split("#", 1)[0]
        dst = self.dataset_node(name, scope)
        op = self.refine(ref)
        unresolved = not temp and "&" in name
        status, reason = _status(ref.reason or (_unresolved_reason(name) if unresolved else None))
        self.add(ref, op, dst, status, reason)
        if not (temp or unresolved or ref.attrs.get("proc_default") is True
                or ref.attrs.get("library") is True):
            self.count(dst, op, ref.evidence)

    def cics_file(self, ref: Ref) -> None:
        op = str(ref.attrs.get("io") or "update")
        name = (ref.target_name or "").strip().upper()
        if not name:
            self.unknown(ref, "cicsfile", op)
            return
        fid = "cicsfile:" + name
        node = self.nodes.get(fid)
        if node is None:
            self.add(ref, op, missing(self.nodes, "cicsfile", name), LOOSE, ref.reason)
            return
        keys: Dict[str, List[Ref]] = {}
        for r in self.file_dsn.get(fid, []):
            if (r.target_name or "").strip():
                key = norm_dataset(r.target_name.strip().upper(), list(self.quals))[0]
                keys.setdefault(key, []).append(r)
        if not keys:
            self.add(ref, op, fid, PARTIAL,
                     join(ref.reason, "CICS file %s has no DSNAME in these repos" % name),
                     list(node.evidence))
            return
        if len(keys) > 1:
            cands = sorted(keys)
            reason = join(ref.reason, "ambiguous: CICS file %s is defined with %s"
                          % (name, ", ".join(cands)))
            nid = missing(self.nodes, "dataset", unknown_name(ref.src, ref.evidence), reason, cands)
            self.add(ref, op, nid, PARTIAL, reason, [r.evidence for rs in keys.values() for r in rs])
            return
        (fds,) = keys.values()
        dsn = fds[0].target_name.strip().upper()
        dst = self.dataset_node(dsn, None)
        unresolved = "&" in dsn
        status, reason = _status(ref.reason, *[r.reason for r in fds])
        if unresolved and status == CONFIRMED:
            status, reason = PARTIAL, _unresolved_reason(dsn)
        self.add(ref, op, dst, status, reason, [r.evidence for r in fds])
        if not unresolved:
            self.count(dst, op, ref.evidence)

    def dataset_loose(self) -> None:
        for dst in list(self.ds_writes) + [d for d in self.ds_reads if d not in self.ds_writes]:
            key = dst.split(":", 1)[1]
            if dst not in self.ds_reads:
                side, kind, reason = self.ds_writes[dst], "reader", NO_READER
            elif dst not in self.ds_writes:
                side, kind, reason = self.ds_reads[dst], "writer", NO_WRITER
            else:
                continue
            self.edges.append(Edge(dst, "loose", missing(self.nodes, kind, key), LOOSE, reason,
                                   list(side)))

    # -- transfers -----------------------------------------------------------------------
    def transfer(self, ref: Ref) -> None:
        name = (ref.target_name or "").strip()
        if not name:
            self.unknown(ref, "external")
            return
        nid = "external:" + name
        if nid not in self.nodes:
            attrs = {k: v for k, v in ref.attrs.items() if k in ("remote_dsn", "direction", "via")}
            self.nodes[nid] = Node(nid, "external", name, None, [], attrs)
        self.add(ref, ref.op, nid, PARTIAL, join(TRANSFER_REASON, ref.reason))

    # -- tables --------------------------------------------------------------------------
    def follow_table(self, tid: str) -> Tuple[str, List[Evidence], Optional[str]]:
        """(final table id, definition evidence, ambiguity reason) following aliases."""
        seen: Set[str] = set()
        evid: List[Evidence] = []
        amb: Optional[str] = None
        cur = tid
        while True:
            seen.add(cur)
            node = self.nodes[cur]
            evid.extend(node.evidence)
            amb = amb or _defs_reason(node)
            target = node.attrs.get("alias_of")
            if not target:
                return cur, evid, amb
            nxt = "table:" + str(target).upper()
            if nxt not in self.nodes:
                nxt = "table:" + str(target)
            if nxt not in self.nodes or nxt in seen:
                return cur, evid, amb  # alias of something not in the DDL: the alias is the end
            cur = nxt

    def table_match(self, ref: Ref, cands: List[str], wanted: str,
                    extra: Optional[str]) -> None:
        """Link to the one candidate (after aliases), or ambiguous, or loose."""
        finals: Dict[str, Tuple[str, List[Evidence], Optional[str]]] = {}
        for c in cands:
            final = self.follow_table(c)
            finals.setdefault(final[0], final)
        if not finals:
            self.add(ref, ref.op, missing(self.nodes, "table", wanted), LOOSE, ref.reason)
            return
        if len(finals) > 1:
            names = [self.nodes[c].name for c in cands]
            reason = join(ref.reason, "ambiguous: " + ", ".join(names))
            nid = missing(self.nodes, "table", "?" + wanted, reason, names)
            self.add(ref, ref.op, nid, PARTIAL, reason)
            return
        dst, evid, amb = next(iter(finals.values()))
        status, reason = _status(ref.reason, extra, amb)
        self.add(ref, ref.op, dst, status, reason, evid)

    def table(self, ref: Ref) -> None:
        written = (ref.target_name or "").strip()
        name = written.upper()  # COBOL keeps SQL names as written
        if not name:
            self.unknown(ref, "table")
            return
        if "&" in name or ":" in name:
            self.unknown(ref, "table", written=written)
            return
        parts = [p.strip('"') for p in name.split(".")]
        full = ".".join(parts[-2:])  # LOCATION.SCHEMA.NAME: the location is dropped
        if len(parts) == 1:
            self.table_match(ref, self.tables_by_name.get(full, []), full, None)
            return
        if "table:" + full in self.nodes:
            self.table_match(ref, ["table:" + full], full, None)
            return
        schema, base = parts[-2], parts[-1]
        cands = self.tables_by_name.get(base, [])
        if schema in self.quals:
            self.table_match(ref, cands, full, None)  # dropping a listed qualifier: confirmed
        else:
            self.table_match(ref, cands, full,
                             "matched only after dropping schema %s, which is not a listed "
                             "environment qualifier" % schema)

    # -- queues --------------------------------------------------------------------------
    def follow_queue(self, name: str) -> Tuple[str, List[Evidence]]:
        """(queue id the use reaches, definition evidence) through alias / remote queues."""
        cur = "queue:" + name
        evid: List[Evidence] = []
        seen: Set[str] = set()
        while cur in self.nodes and cur not in seen:
            seen.add(cur)
            node = self.nodes[cur]
            evid.extend(node.evidence)
            target = node.attrs.get("target")
            if node.attrs.get("type") not in ("alias", "remote") or not target:
                break
            if node.attrs.get("type") == "alias" and \
                    str(node.attrs.get("targtype") or "QUEUE").upper() != "QUEUE":
                break  # an alias of a topic: no queue to follow
            nxt = "queue:" + str(target)
            if nxt not in self.nodes:
                break  # a remote queue whose target is on a queue manager not in these repos
            cur = nxt
        if cur not in self.nodes:
            self.nodes[cur] = Node(cur, "queue", cur.split(":", 1)[1], None, [],
                                   {"defined": False})
        return cur, evid

    def queue(self, ref: Ref) -> None:
        name = (ref.target_name or "").strip()
        if not name and len(ref.candidates) == 1:
            dst, evid = self.follow_queue(ref.candidates[0].strip())
            self.add(ref, ref.op, dst, PARTIAL, ref.reason or "name not worked out", evid)
            self.count_queue(dst, ref)
            return
        if not name:
            self.unknown(ref, "queue")
            return
        if "&" in name and "queue:" + name not in self.nodes:
            self.unknown(ref, "queue", written=name)
            return
        dst, evid = self.follow_queue(name)
        status, reason = _status(ref.reason)
        self.add(ref, ref.op, dst, status, reason, evid)
        self.count_queue(dst, ref)

    def count_queue(self, dst: str, ref: Ref) -> None:
        if ref.op in ("put", "open"):
            self.q_puts.setdefault(dst, []).append(ref.evidence)
        if ref.op in ("get", "open"):
            self.q_gets.setdefault(dst, []).append(ref.evidence)

    def triggers(self) -> None:
        for q in list(self.inv.nodes.values()):
            if q.kind != "queue":
                continue
            bridge = q.attrs.get("bridge") is True
            process = q.attrs.get("process")
            if not bridge and not (q.attrs.get("trigger") is True and process):
                continue
            self.triggered.add(q.id)
            base = BRIDGE_REASON if bridge else None
            evid = list(q.evidence)
            if not process:
                reason = join(base, "the queue names no PROCESS")
                nid = missing(self.nodes, "transaction", "?" + q.name, reason)
                self.edges.append(Edge(q.id, "triggers", nid, PARTIAL, reason, evid))
                continue
            proc = self.nodes.get("mqprocess:" + str(process))
            if proc is None:
                reason = join(base, "process %s is not defined in these repos" % process)
                self.edges.append(Edge(q.id, "triggers",
                                       missing(self.nodes, "mqprocess", str(process)),
                                       LOOSE, reason, evid))
                continue
            evid.extend(proc.evidence)
            applicid = str(proc.attrs.get("applicid") or "").strip().upper()
            if not applicid:
                reason = join(base, "process %s has no APPLICID" % process)
                nid = missing(self.nodes, "transaction", "?" + q.name, reason)
                self.edges.append(Edge(q.id, "triggers", nid, PARTIAL, reason, evid))
                continue
            tid = "transaction:" + applicid
            tx = self.nodes.get(tid)
            if tx is None and applicid == BRIDGE_MONITOR:
                # IBM's bridge monitor: the program comes from each message, not from code
                self.nodes[tid] = Node(tid, "transaction", applicid, None, [], {"system": True})
                self.edges.append(Edge(q.id, "triggers", tid, PARTIAL,
                                       join(BRIDGE_REASON, "the program is named in each "
                                            "message, not in these repos"), evid))
            elif tx is None:
                # a fully worked-out name that nothing defines: only one side found
                self.edges.append(Edge(q.id, "triggers", missing(self.nodes, "transaction",
                                                                 applicid), LOOSE, base, evid))
            else:
                amb = _defs_reason(tx)
                self.edges.append(Edge(q.id, "triggers", tid, PARTIAL if amb else CONFIRMED,
                                       join(base, amb), evid + list(tx.evidence)))

    def queue_gaps(self) -> None:
        for qid in list(self.q_puts) + [q for q in self.q_gets if q not in self.q_puts]:
            name = self.nodes[qid].name
            puts, gets = self.q_puts.get(qid), self.q_gets.get(qid)
            if puts and not gets and qid not in self.triggered:
                self.edges.append(Edge(qid, "partial", missing(self.nodes, "queue-consumer", name),
                                       PARTIAL, NO_CONSUMER, list(puts)))
            elif gets and not puts:
                self.edges.append(Edge(qid, "partial", missing(self.nodes, "queue-producer", name),
                                       PARTIAL, NO_PRODUCER, list(gets)))

    # -- REST ----------------------------------------------------------------------------
    def http(self, ref: Ref) -> None:
        if not (ref.target_name or "").strip():
            self.unknown(ref, "endpoint")
            return
        method, path, host = split_http(ref.target_name or "")
        cands = [nid for nid, m, p in self.rest
                 if p == path and (method == "ANY" or m == "ANY" or m == method)]
        if len(cands) == 1:
            node = self.nodes[cands[0]]
            status, reason = _status(ref.reason, _defs_reason(node))
            self.add(ref, ref.op, node.id, status, reason, list(node.evidence))
        elif cands:
            reason = join(ref.reason, "ambiguous: " + ", ".join(cands))
            nid = missing(self.nodes, "endpoint", "?%s %s" % (method, path), reason, cands)
            self.add(ref, ref.op, nid, PARTIAL, reason)
        elif host:
            nid = "external:" + host
            if nid not in self.nodes:
                self.nodes[nid] = Node(nid, "external", host, None, [], {})
            self.add(ref, ref.op, nid, LOOSE, join(EXTERNAL_REASON, ref.reason))
        else:
            self.add(ref, ref.op, missing(self.nodes, "endpoint", "%s %s" % (method, path)),
                     LOOSE, ref.reason)

    # -- uses ----------------------------------------------------------------------------
    def uses(self, ref: Ref) -> None:
        name = (ref.target_name or "").strip()
        if not name:
            self.unknown(ref, ref.target_kind)
            return
        node = self.nodes.get("%s:%s" % (ref.target_kind, name))
        if node is None:
            self.add(ref, ref.op, missing(self.nodes, ref.target_kind, name), LOOSE, ref.reason)
            return
        status, reason = _status(ref.reason)
        self.add(ref, ref.op, node.id, status, reason, list(node.evidence))

    # -- driver --------------------------------------------------------------------------
    def run(self) -> None:
        for ref in self.inv.refs:
            if ref.attrs.get("system") is True:
                continue  # IBM-supplied names (Ruling 9)
            kind, op = ref.target_kind, ref.op
            if kind == "dataset" and op != "file_dataset":
                self.dataset(ref)
            elif kind == "cicsfile" and op == "cics_file":
                self.cics_file(ref)
            elif kind == "external" and op == "transfer":
                self.transfer(ref)
            elif kind == "table":
                self.table(ref)
            elif kind == "queue":
                self.queue(ref)
            elif kind == "endpoint" and op == "http":
                self.http(ref)
            elif op == "uses" and kind in ("class", "component"):
                self.uses(ref)
        self.triggers()
        self.dataset_loose()
        self.queue_gaps()


def resolve_data(inv: Inventory, config: Config, nodes: Dict[str, Node],
                 edges: List[Edge]) -> None:
    """Append data-link edges (and the dataset / queue / missing / external nodes they need)."""
    _Data(inv, config, nodes, edges).run()


def _label(node: Node) -> str:
    return "%s %s" % (node.kind, node.name)


def repo_links(resolved: Resolved) -> List[Tuple[str, str, str, List[Edge]]]:
    """``(repo_a, repo_b, via_label, edges)`` for every link between two repos, with
    ``repo_a < repo_b`` and one entry per pair and resource.

    A direct edge whose two ends belong to different repos links them, labeled with its
    target (``"table CLMS.CLAIM"``): a definition's repo owns the resource. A dataset or queue
    with no definition belongs to no repo, so it links every pair of repos that use it.
    """
    nodes = resolved.nodes
    out: Dict[Tuple[str, str, str], List[Edge]] = {}

    def put(a: str, b: str, label: str, es: List[Edge]) -> None:
        lst = out.setdefault((min(a, b), max(a, b), label), [])
        for e in es:
            if not any(x is e for x in lst):
                lst.append(e)

    touch: Dict[str, Dict[str, List[Edge]]] = {}
    for e in resolved.edges:
        s, d = nodes.get(e.src), nodes.get(e.dst)
        if s is None or d is None or "missing" in (s.kind, d.kind):
            continue
        if s.repo and d.repo and s.repo != d.repo:
            put(s.repo, d.repo, _label(d), [e])
        for res, other in ((d, s), (s, d)):
            if res.kind in SHARED_KINDS and res.repo is None and other.repo:
                touch.setdefault(res.id, {}).setdefault(other.repo, []).append(e)
    for rid, by_repo in touch.items():
        repos = sorted(by_repo)
        for i, a in enumerate(repos):
            for b in repos[i + 1:]:
                put(a, b, _label(nodes[rid]), by_repo[a] + by_repo[b])
    return [(a, b, label, es) for (a, b, label), es in out.items()]
