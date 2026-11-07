# Why each expected link is in `expected_links.json`

Written by hand from the fixture sources under `tests/fixtures/claims-estate/`, before the
resolver was run over the estate. Rules: spec §7 (`docs/superpowers/specs/2026-11-06-architecture-diagram-skill-design.md`)
and the controller rulings (`.superpowers/sdd/2026-11-06-architecture-diagram-skill/scanner-facts.md`,
`progress.md`). Config: `environment_qualifiers = ["PROD", "TEST"]`.

Paths below are relative to the estate. "§7.4 solid rule" = "solid only when the name is
fully worked out from code in the repos and exactly one thing matches it".

## claims-batch: `jcl/CLMD100.jcl` (prod copy, `SET HLQ=PROD` at line 3)

| Edge | Status | Why |
|---|---|---|
| STEP010 runs utility:SORT | confirmed | line 4 `EXEC PGM=SORT`; utilities are created on demand, name literal |
| STEP010 read dataset:CLM.MASTER.KSDS | confirmed | line 5 `&HLQ..CLM.MASTER.KSDS`, DISP=SHR; `&HLQ` from SET counts as worked out (§7.4), PROD is a listed env qualifier so key drops it |
| STEP010 write dataset:claims-batch/jcl/CLMD100.jcl#&&SORTED | confirmed | line 6 `&&SORTED` DISP=NEW: temp dataset keyed by job (plan Task 8, `data.py` id form) |
| STEP020 runs program:CLMB200 | confirmed | line 10; one PROGRAM-ID CLMB200 (cobol/CLMB200.cbl:2) |
| STEP020 read …#&&SORTED | confirmed | line 11 `CLMIN DD … DISP=(OLD,DELETE)`: DISP=OLD is `update`, refined by the step program's open mode (spec §7.1 SELECT…ASSIGN tie-back, plan Task 8): CLMB200 has `SELECT CLMIN-FILE ASSIGN TO CLMIN` (CLMB200.cbl:6) and `OPEN INPUT CLMIN-FILE` (:21), so read; same job's temp node |
| STEP020 write dataset:CLAIMS.DAILY | confirmed | line 12 `&HLQ..CLAIMS.DAILY(+1)` NEW: GDG generation stripped, PROD dropped |
| STEP030 runs program:CLMB300 | confirmed | lines 13-16: IKJEFT01 with `RUN PROGRAM(CLMB300)` in SYSTSIN (§7.1); the driver IKJEFT01 itself is not a link |
| STEP030 read dataset:CLAIMS.DAILY | confirmed | line 19 `(0)` SHR. REPORT is SYSOUT (line 20): no edge |
| STEP040 runs utility:IEBGENER | confirmed | line 22 |
| STEP040 read dataset:CLAIMS.DAILY | confirmed | line 23 |
| STEP040 write dataset:CLAIMS.EXTRACT | confirmed | line 24 PROD.CLAIMS.EXTRACT NEW |
| STEP040 write dataset:CLAIMS.AUDIT | confirmed | line 25 DISP=MOD: write |
| STEP050 runs utility:DMBATCH | confirmed | line 26 |
| STEP050 read dataset:CLAIMS.EXTRACT | confirmed | line 28 `COPY FROM (DSN=PROD.CLAIMS.EXTRACT)`: the local side of a transfer is a real read (scanner-facts `via=transfer`) |
| STEP050 transfer external:NDM:FINANCE | partial | line 28 `TO (SNODE=FINANCE …)`: "file transfer target is outside these repos" (Ruling 24, plan Task 8) |

Line 31 is a `//*` comment holding `EXEC PGM=FAKEPGM DSN=FAKE.DS`: no edge. Lines 7-9 and 27-29
are in-stream `DD *` data: no dataset.

## claims-batch: `jcl/test/CLMD100.jcl` (test copy, `SET HLQ=TEST`)

Same 15 edges with source ids `step:claims-batch/jcl/test/CLMD100.jcl#…` and its own temp
`dataset:claims-batch/jcl/test/CLMD100.jcl#&&SORTED` (temps never link across jobs). TEST is a
listed qualifier, so `TEST.CLAIMS.DAILY` and `TEST.CLM.MASTER.KSDS` share the prod copy's keys:
a match only possible after dropping a listed env qualifier is confirmed (§7.4). The hard-coded
`PROD.CLAIMS.EXTRACT`/`PROD.CLAIMS.AUDIT` give the same keys too.

## claims-batch: `jcl.pds/CLMD300` + `proc/CLMPRC.proc`

| Edge | Status | Why |
|---|---|---|
| CLMD300#RUN runs program:CLMB400 | confirmed | CLMD300:2 `EXEC CLMPRC,ENV=PROD` expands CLMPRC.proc:2 `RUN EXEC PGM=CLMB400`; one PROGRAM-ID (cobol.pds/CLMB400:2, no extension, found by content §7.6) |
| CLMD300#RUN read dataset:PAYMENT.FEED | confirmed | CLMPRC.proc:3 `&ENV..PAYMENT.FEED` SHR; ENV=PROD is an EXEC override, which counts as worked out (§7.4); PROD dropped |
| CLMD300#S2 runs utility:IEFBR14 | confirmed | CLMD300:3 |
| CLMD300#S2 write dataset:&UNDEF..OUT.FILE | partial | CLMD300:4: `&UNDEF` has no value anywhere: "partly known" (§7.4). Not counted for loose ends |

The standalone scan of CLMPRC.proc gives nothing because CLMD300 calls it (Ruling 8).

## Dataset loose ends (counted reads/writes only; temps and unresolved names never count)

| Edge | Status | Why |
|---|---|---|
| dataset:CLAIMS.AUDIT loose missing:reader:CLAIMS.AUDIT | loose | written at CLMD100.jcl:25 (both copies), read nowhere: "a dataset with no reader" trap (§11); no other dataset differs only by a first qualifier (Ruling 22 does not apply) |
| dataset:PAYMENT.FEED loose missing:writer:PAYMENT.FEED | loose | read at CLMPRC.proc:3, written nowhere (plan Task 8 test) |
| dataset:CLM.MASTER.KSDS loose missing:writer:CLM.MASTER.KSDS | loose | read by SORTIN (CLMD100.jcl:5, both copies) and by CLMO100 via CICS FILE CLMMAST; no JCL, program or CICS write anywhere. Only one side found, so a loose end (§7.3). No dataset `MASTER.KSDS` or `X.CLM.MASTER.KSDS` exists, so no maybe_same |

CLAIMS.DAILY (written STEP020, read STEP030/040) and CLAIMS.EXTRACT (written STEP040, read by the
STEP050 transfer) have both sides: no loose end.

## claims-batch COBOL

| Edge | Status | Why |
|---|---|---|
| CLMB200 copy copybook:CLMREC | confirmed | CLMB200.cbl:15; one CLMREC (shared-copybooks/CLMREC.cpy) |
| CLMB200 select table:CLMS.CLAIM | confirmed | CLMB200.cbl:26 `FROM CLAIM` unqualified; exactly one table named CLAIM in the DDL (claims-db/ddl/CLAIM.sql:3) — §7.4 unqualified rule |
| CLMB200 call notanalyzed:DATEUTIL | confirmed | CLMB200.cbl:29 literal; DATEUTIL is assembler (asm/DATEUTIL.asm), registered not analyzed (§7.6, plan Task 7 test) |
| CLMB200 call program:CLMB210 | partial | CLMB200.cbl:31 `CALL WS-PGM`; WS-PGM VALUE 'CLMB210' (line 16) is the one candidate: a CALL through a variable is partly known (§7.3), drawn to the one defined candidate (plan Task 7) |
| CLMB300 copy copybook:PAYREC | confirmed | CLMB300.cbl:6 |
| CLMB300 insert table:CLMS.PAYMENT | confirmed | CLMB300.cbl:9 qualified, exact DDL match (PAYMENT.sql:1) |
| CLMB400 call program:CLMB210 | confirmed | cobol.pds/CLMB400:4 literal, one PROGRAM-ID CLMB210 |

No edges: `EXEC SQL INCLUDE SQLCA` (CLMB200.cbl:18, IBM, Ruling 9); `*    CALL 'NOTREAL'`
(CLMB200.cbl:30, column-7 comment); `SELECT … ASSIGN TO` (lines 6-7) only feed DISP=OLD
refinement; CLMB210 has no outgoing statements.

## claims-online

| Edge | Status | Why |
|---|---|---|
| CLMO100 copy copybook:CLMREC | confirmed | CLMO100.cbl:5. `COPY DFHAID` (line 6) is IBM: no edge |
| CLMO100 select table:CLMS.CLAIM | confirmed | CLMO100.cbl:16 `FROM CLAIM C` (one table CLAIM) and CLMO100.cbl:21 `FROM CLMS.CLM`, an alias of CLMS.CLAIM (CLAIM.sql:10) followed to its target — both give this same edge |
| CLMO100 select missing:table:?POLICY | partial | CLMO100.cbl:17 `JOIN POLICY` unqualified; CLMS.POLICY and ARCH.POLICY both exist (POLICY.sql:1,6): ambiguous (§7.4) |
| CLMO100 link program:CLMO110 | partial | CLMO100.cbl:23; CLMO110 defined twice (cobol/ and endevor/qa/): duplicate names are ambiguous (§7.4) |
| CLMO100 xctl missing:program:?CLMO100:26 | partial | CLMO100.cbl:26 `XCTL PROGRAM(WS-NEXT-PGM)`, no VALUE (line 7): computed at run time (§7.3), per-site id |
| CLMO100 read dataset:CLM.MASTER.KSDS | confirmed | CLMO100.cbl:28 `READ FILE('CLMMAST')` → CLAIMS.csd:6 `DSNAME(PROD.CLM.MASTER.KSDS)`; one FILE definition, PROD dropped (plan Task 8 test) |
| CLMO100 send_map map:CLMM01 | confirmed | CLMO100.cbl:31 MAPSET('CLMM01'); maps/CLMM01.bms:1 defines it |
| CLMO100 get queue:CLM.REQ.LQ | confirmed | CLMO100.cbl:33-36 literal moved into MQOD, opened as HOBJ-REQ, MQGET on HOBJ-REQ; defined at claims.mqsc:2 |
| CLMO100 put queue:CLM.RSP | confirmed | CLMO100.cbl:8 `WS-RSPQ VALUE 'CLM.RSP'`, moved at line 38, MQPUT on HOBJ-RSP at 41. The VALUE is in the code and WS-RSPQ is never changed, so the name is worked out (§7.1 "resolved from a VALUE clause", Ruling 10); claims.mqsc:7 |
| CLMO100 return_transid transaction:CLMU | confirmed | CLMO100.cbl:43; CLAIMS.csd:5 defines CLMU |
| CLMO110 copy missing:copybook:ERRMSG | loose | cobol/CLMO110.cbl:5 and endevor/qa/CLMO110.cbl:5; no ERRMSG copybook anywhere (plan Task 7 test) |
| CLMO130 start missing:transaction:CLMX | loose | CLMO130.cbl:4; no CSD defines CLMX |
| transaction:CLMI runs program:CLMO100 | confirmed | CLAIMS.csd:3-4 (PROGRAM on a continuation line) |
| transaction:CLMU runs missing:program:CLMO120 | loose | CLAIMS.csd:5; CLMO120 is the repo left out on purpose (§11, plan Task 7 test) |
| zosapi:GET /zos/claims/{}/status runs program:CLMO130 | confirmed | apis/claimstatus/package.xml:3-5 basePath + `/{id}/status` GET → service ClaimStatus; services/ClaimStatus/service.properties:5 `executableName=CLMO130` |
| queue:CLM.REQ.LQ triggers transaction:CLMI | confirmed | claims.mqsc:2-4 TRIGGER PROCESS(CLM.PROC); :6 APPLICID(CLMI); CSD defines CLMI (§7.5) |
| queue:CLM.BRIDGE.Q triggers missing:transaction:CLMB | loose | claims.mqsc:8 DESCR('CICS BRIDGE') PROCESS(CLM.BPROC); :9 APPLICID(CLMB); no CSD defines CLMB → loose (Ruling 20) |

No edges: CLAIMS.csd:2 is a `*` comment (`FAKE`/`NOTREAL`); the MQ API calls (`CALL 'MQOPEN'`
etc.) are system refs (Ruling 9); the QALIAS CLM.REQ (claims.mqsc:5) and FILE definitions
are only used to resolve other links; CLM.RSP, CLM.REQ.LQ have puts and gets, so no gap edge;
CLM.BRIDGE.Q has no put/get in the code, so no gap edge.

## claims-api (Java)

| Edge | Status | Why |
|---|---|---|
| AuditPublisher put queue:CLM.AUDIT | confirmed | AuditPublisher.java:15 literal; the use is certain even though no MQSC defines it |
| queue:CLM.AUDIT partial missing:queue-consumer:CLM.AUDIT | partial | put only, no get, no trigger/bridge: "how this queue reaches CICS isn't in these repos" (§7.5, Ruling 21) |
| MqClaimGateway put queue:CLM.REQ.LQ | confirmed | MqClaimGateway.java:22 `requestQueue` = `${mq.request}` = CLM.REQ (application.yml:3); QALIAS CLM.REQ → CLM.REQ.LQ followed (§7.2) |
| MqClaimGateway get queue:CLM.RSP | confirmed | MqClaimGateway.java:26 `receive(replyQueue)`, `${mq.reply}` = CLM.RSP (application.yml:4) |
| ClaimRepository select table:CLMS.POLICY | confirmed | ClaimRepository.java:15 qualified, exact DDL match (POLICY.sql:1) |
| ClaimStatusClient http zosapi:GET /zos/claims/{}/status | confirmed | ClaimStatusClient.java:19 `getForObject(zosUrl + "/zos/claims/{id}/status")`, zosUrl = application.yml:6; path matches the one zosapi (§7.2 REST) |
| RatesClient http external:rates.example.com | loose | RatesClient.java:11 absolute URL, nothing serves `/v1/rates`: "external or missing service" (plan Task 8) |
| ClaimController uses class:claims-api/MqClaimGateway | confirmed | ClaimController.java:11 constructor parameter |
| ClaimController uses class:claims-api/ClaimStatusClient | confirmed | ClaimController.java:11 constructor parameter |
| endpoint:GET /api/claims/{} runs class:claims-api/ClaimController | confirmed | ClaimController.java:16 `@GetMapping("/claims/{id}")` under class `@RequestMapping("/api")` (:6); handler class defined once (:7). Ruling 25 |
| endpoint:POST /api/claims runs class:claims-api/ClaimController | confirmed | ClaimController.java:21 `@PostMapping("/claims")`; same handler. Ruling 25 |

The two endpoint `runs` edges were added in fix round 1 (Ruling 25). They are a resolver
change, not a misread fixture: the plan's model kept the handler only as
`attrs["handler"]` on the endpoint node, with no edge, so an Angular → Java → MQ/CICS flow
stopped at the endpoint. The resolver now emits `endpoint -runs-> handler class`
(confirmed; partial for an unresolved `endpoint:?` node). JmsTemplate/RestTemplate/JdbcTemplate
are not repo classes: no `uses`.

## claims-portal (Angular)

| Edge | Status | Why |
|---|---|---|
| page:claims-portal/claims/:id uses component:claims-portal/ClaimDetailsComponent | confirmed | app-routing.module.ts:6 |
| ClaimDetailsComponent uses component:claims-portal/ClaimService | confirmed | claim-details.component.ts:6 constructor injection |
| ClaimService http endpoint:GET /api/claims/{} | confirmed | claim.service.ts:10 `${environment.apiBase}/claims/${id}`, apiBase '/api' (environment.ts:3); `${id}` normalizes to `{}` (§7.2) |
| ClaimService http endpoint:POST /api/claims | confirmed | claim.service.ts:14 |
| ClaimService http missing:endpoint:DELETE /api/claims/{} | loose | claim.service.ts:18; no DELETE handler, no host: only one side (plan Task 8 test) |

## Transfer status

STEP050's NDM transfer is partial by Ruling 24 ("NDM/FTP transfer to an outside node stays
PARTIAL"), which settles the partial-vs-loose question raised in the first gate run.

## Changes made after running the gate

- First run: matched all 75 entries exactly (58 confirmed, 8 partial, 9 loose).
- Fix round 1: +2 entries, the endpoint → handler `runs` edges (Ruling 25, resolver change
  above). Now 77 entries (60 confirmed, 8 partial, 9 loose).

## Final fix wave traps

Added by the final fix wave (final-findings.md). Each trap is a new file; no existing fixture
file was changed.

### C1: duplicate PROC names (`claims-batch/proc/CLMEXT.proc`, `claims-online/proc/CLMEXT.proc`, `claims-online/jcl/CLMO900.jcl`)

| Edge | Status | Why |
|---|---|---|
| CLMO900#EXT runs program:CLMO130 | confirmed | CLMO900.jcl:3 `EXEC CLMEXT`; CLMEXT is defined in claims-batch and in claims-online with different steps. The job's own repo is searched first, so claims-online/proc/CLMEXT.proc:3 `EXEC PGM=CLMO130`; one PROGRAM-ID CLMO130. The old first-wins lookup expanded the claims-batch copy (CLMB210) and drew it solid |
| CLMO900#EXT read dataset:CLAIMS.DAILY | confirmed | claims-online/proc/CLMEXT.proc:4 `PROD.CLAIMS.DAILY(0)` SHR; PROD dropped, GDG stripped |
| claims-batch/proc/CLMEXT.proc#EXT runs program:CLMB210 | partial | no caller uses the claims-batch copy (CLMO900 uses its own repo's), so it is scanned with its defaults: "PROC default values; callers of CLMEXT use another copy of it" (Ruling 8) |
| claims-batch/proc/CLMEXT.proc#EXT read dataset:CLAIMS.EXTRACT | partial | same; a default-scan ref never counts as a reader |

A job in a repo with no copy of a PROC that two repos define differently gets every ref
partial, "ambiguous: PROC X defined in N places: ..." (unit tests in test_scan_jcl.py).

### C2: MQ handles qualified with OF (`claims-online/cobol/CLMO140.cbl`)

| Edge | Status | Why |
|---|---|---|
| CLMO140 put queue:CLM.AUDIT | confirmed | CLMO140.cbl:25 `MQPUT USING HCONN OF CTL, HAUD OF CTL`: the handle is the second argument once each `OF <group>` is skipped; HAUD is opened at :20 after `MOVE 'CLM.AUDIT'` (:19). The old parser counted `CTL` as an argument and fell back to the last MOVE before the call (`CLM.RSP`, :22), a confirmed wrong queue |
| CLMO140 put missing:queue:?CLMO140:27 | partial | CLMO140.cbl:27 `MQPUT` on WS-HANDLE, which no MQOPEN in the program sets; the program opens two different queues, so the ref is partial with both candidates (CLM.AUDIT, CLM.RSP) |

CLM.AUDIT still has no consumer: the existing `queue:CLM.AUDIT partial missing:queue-consumer:CLM.AUDIT` edge is unchanged.

### C3: a partial target beside a solid one on a combined line (`claims-api/.../PaymentArchiveRepository.java`)

| Edge | Status | Why |
|---|---|---|
| PaymentArchiveRepository select table:CLMS.PAYMENT | partial | PaymentArchiveRepository.java:17 `FROM OLDS.PAYMENT`; OLDS is not a listed environment qualifier, so the match to CLMS.PAYMENT (PAYMENT.sql:1) is only possible after dropping it: partly known (§7.4) |

The resolver edge was already right; the trap guards the views. The landscape used to merge it
with ClaimRepository's confirmed POLICY edge into one solid "SQL · PAYMENT, POLICY" line. Now
each target rides on a line of its own most certain status: solid "SQL · POLICY" and dotted
"SQL · PAYMENT" (tests/test_view_invariants.py checks every line of every fixture view).

### I1 / Ruling 36: absolute-URL REST matches need their host tied to the target repo (`claims-api/.../PartnerClient.java`)

| Edge | Status | Why |
|---|---|---|
| PartnerClient http endpoint:GET /api/claims/{} | partial | PartnerClient.java:13 `https://partner.example.com/api/claims/{id}`: the path equals our `GET /api/claims/{}` (ClaimController.java:16), but partner.example.com is named in no config of claims-api (the endpoint's repo): "matched on path only; host partner.example.com isn't tied to a scanned repo". Before Ruling 36 this was drawn solid |

Changed by Ruling 36 (revises Ruling 17): **ClaimStatusClient http zosapi:GET /zos/claims/{}/status
is now partial** (was confirmed). Its base URL `https://zcee.internal:9443` comes from
claims-api's own application.yml:6; claims-online (the z/OS Connect API's repo) names no
such host in its config, so the match is on the path only. Relative URLs (ClaimService's
`/api` base) and `localhost` keep the old behaviour.

### I3: copybooks named `.cbl`, with no extension, and holding procedure code (`claims-batch/cobol/CLMB500.cbl`, `shared-copybooks/copylib/ADDRREC.cbl`, `shared-copybooks/copylib/CLMPROC`)

| Edge | Status | Why |
|---|---|---|
| CLMB500 copy copybook:CLMREC | confirmed | CLMB500.cbl:8; one CLMREC (shared-copybooks/CLMREC.cpy) |
| CLMB500 copy copybook:ADDRREC | confirmed | CLMB500.cbl:9; copylib/ADDRREC.cbl has no PROGRAM-ID and no PROCEDURE DIVISION, so it is a copybook, not a program (the old scanner made a phantom program:ADDRREC and this COPY loose) |
| CLMB500 copy copybook:CLMPROC | confirmed | CLMB500.cbl:12; copylib/CLMPROC has no extension and sits in a copybook folder (`copylib`) |
| CLMB500 call program:CLMB210 | confirmed | CLMPROC:2 `CALL 'CLMB210'`: the statement is in the copybook, so it belongs to every program that COPYs it (evidence: the copybook line and CLMB500.cbl:12); one PROGRAM-ID CLMB210 |
| CLMB500 select table:CLMS.CLAIM | confirmed | CLMPROC:3 `FROM CLMS.CLAIM`, qualified, exact DDL match (CLAIM.sql:1) |

### I5 / Ruling 37: a table no DDL defines, used from two repos (`claims-batch/cobol/CLMB510.cbl`, `claims-api/.../ClaimHistoryRepository.java`)

| Edge | Status | Why |
|---|---|---|
| CLMB510 insert table:CLMS.CLMHIST | partial | CLMB510.cbl:9 `INSERT INTO CLMS.CLMHIST`; no DDL in these repos defines it, but claims-api uses it too, so it is a shared `table:CLMS.CLMHIST` with no definition: "no DDL for this table in these repos" (Ruling 37). The old resolver drew two red loose ends and no link between the repos |
| ClaimHistoryRepository select table:CLMS.CLMHIST | partial | ClaimHistoryRepository.java:16 `FROM CLMS.CLMHIST`; same shared table, same reason |

A table with no DDL used from one repo only stays a loose end to `missing:table:<NAME>`
(unit test in test_resolve_data.py).

### Counts after the final fix wave

92 entries (67 confirmed, 16 partial, 9 loose): the 77 above, one changed by Ruling 36
(ClaimStatusClient → zosapi, confirmed → partial), and 15 new for the C1, C2, C3, I1, I3
and I5 traps.
