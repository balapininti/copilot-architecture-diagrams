# Why each expected line is in `expected_gitdiagram.json`

Written by hand from the fixture sources under `tests/fixtures/claims-estate/`, the
hand-checked resolver edges (`expected_links.json`, `expected_links_notes.md`) and the rules,
before the gitdiagram view was run over the fixture. Groupings: the two hand-written files
`claims-estate/architecture-diagrams/gitdiagram-claims-batch.json` and
`gitdiagram-claims-api.json`.

Rules cited:

- **§4.2** spec `docs/superpowers/specs/2026-11-07-gitdiagram-view-design.md` 4.2 (boxes, lines
  between groups, shared resources, outside stubs, entry points, suggested arrows, "Not yet
  grouped"). **§10.n** the same spec, section 10, item n.
- **C3** the landscape combining rule: a line is never more certain than the least certain
  target its label names; between boxes of this repo one line per (family, best status per
  target), so a partly known target rides on its own dotted line.
- **Stub rule** Task 4 brief: a line to or from an `out:` stub takes the least certain edge
  under it (one line per family), so loose and partial stay visible.
- **R2, R5, R6** global.md Rulings 2 (structural Scheduler lines), 5 (a group's call to an
  entry point is drawn to the handler's group, no more certain than either edge), 6 (temp
  `&&` datasets are not boxes; folded into the job line as "via &&X").

Box ids: `grp:<name>`, `grp:?` ("Not yet grouped"), `act:scheduler`, `act:<kind>`,
`out:<repo>`, `out:missing`, `out:external`, a shared resource's own node id.
`label_family` is the label before " · " (and before " via "); a suggested line's family is
its whole label.

## claims-batch: files to boxes

First matching group wins (§4.1). `jcl/**` matches `jcl/test/CLMD100.jcl` too (`*` crosses
`/`). `cobol/CLMB500.cbl` and `cobol/CLMB510.cbl` are in no group: "Not yet grouped" (§4.2).
`asm/DATEUTIL.asm` is registered, not analysed: placed in "Not analyzed" (§3 non-goals, §10.5).

## claims-batch: lines

| Id | Line | Status | Source and rule |
|---|---|---|---|
| B1 | Scheduler → Nightly jobs "starts" | structural | jobs CLMD100 (jcl/CLMD100.jcl:1, jcl/test/CLMD100.jcl:1) and CLMD300 (jcl.pds/CLMD300:1); nothing in the repo submits them. One line per job group. §10.3, R2 |
| B2 | Nightly jobs → Claim pricing "runs · CLMB200 via &&SORTED" | confirmed | CLMD100.jcl:10 `EXEC PGM=CLMB200` (one PROGRAM-ID, CLMB200.cbl:2), both copies. Temp: STEP010 SORT writes `&&SORTED` (CLMD100.jcl:6, SORT is the job's own work, §10.1) and STEP020 reads it on DD CLMIN (:11), which CLMB200 opens (`SELECT CLMIN-FILE ASSIGN TO CLMIN`, CLMB200.cbl:6), so the read starts from Claim pricing (§10.1). Writer and reader in different groups: folded into the job line as "via &&SORTED", same status (R6). All edges confirmed |
| B3 | Nightly jobs → Claim pricing "runs · CLMB210" | partial | proc/CLMEXT.proc:3 `EXEC PGM=CLMB210`; scanned with defaults because CLMO900 uses claims-online's own CLMEXT (expected_links C1): partial. C3: its own dotted line beside B2 |
| B4 | Nightly jobs → Payments "runs · CLMB300, CLMB400" | confirmed | CLMD100.jcl:16 `RUN PROGRAM(CLMB300)` under IKJEFT01 (CLMB300.cbl:2); CLMD300:2 `EXEC CLMPRC` → CLMPRC.proc:2 `EXEC PGM=CLMB400` (cobol.pds/CLMB400:2). Both confirmed. §4.2 |
| B5 | Claim pricing → CLAIMS.DAILY "writes" | confirmed | CLMD100.jcl:12 `CLMOUT DD …CLAIMS.DAILY(+1)` NEW, read by CLMB200 through `SELECT CLMOUT-FILE ASSIGN TO UT-S-CLMOUT` (CLMB200.cbl:7; `UT-S-` is the old device prefix, the DD name is CLMOUT), so the write starts from the program's group (§10.1): confirmed write + confirmed runs. CLAIMS.DAILY has no defining file and two boxes of this repo touch it (B5, B6): its own shared box (§4.2, §10.2) |
| B6 | Nightly jobs → CLAIMS.DAILY "reads" | confirmed | CLMD100.jcl:19 DAILYIN (STEP030; CLMB300 has no FILE-CONTROL, so the DD can't be matched to it: job's group, §10.1) and :23 SYSUT1 (IEBGENER, a utility: job's group, §10.1). claims-online's CLMO900 also reads it (CLMEXT.proc:4 there): named on the shared box, not drawn (§4.2 "without the other repos' insides") |
| B7 | Nightly jobs → out:missing "no writer found · CLM.MASTER.KSDS, PAYMENT.FEED" | loose | CLMD100.jcl:5 SORTIN reads CLM.MASTER.KSDS; CLMPRC.proc:3 FEED reads PAYMENT.FEED (DD not in CLMB400: job's group); nothing writes either (expected_links loose ends). Each dataset is touched by one group only, so it is a detail line on Nightly jobs and its loose end leaves from there. Stub rule, §4.2 "loose ends stay visible" |
| B8 | Nightly jobs → out:missing "no reader found · CLAIMS.AUDIT" | loose | CLMD100.jcl:25 AUDIT DD (IEBGENER step: job's group); read nowhere. Different family from B7, so its own line. Stub rule |
| B9 | Nightly jobs → out:external "file transfer · FINANCE" | partial | CLMD100.jcl:28 `TO (SNODE=FINANCE …)`, STEP050 DMBATCH (utility: job's group); partial by Ruling 24 of the base spec. Stub rule |
| B10 | Claim pricing → out:shared-copybooks "COPY · CLMREC" | confirmed | CLMB200.cbl:15; CLMREC is defined in shared-copybooks/CLMREC.cpy, another repo: one stub per outside repo (§4.2) |
| B11 | Claim pricing → out:claims-db "SQL · CLAIM" | confirmed | CLMB200.cbl:24-26 `FROM CLAIM`, one table CLAIM (claims-db/ddl/CLAIM.sql:3) |
| B12 | Claim pricing → Not analyzed "CALL · DATEUTIL" | confirmed | CLMB200.cbl:29 `CALL 'DATEUTIL'`; DATEUTIL is defined by asm/DATEUTIL.asm:1 (`DATEUTIL CSECT`), a grouped file, so the target is part of "Not analyzed" (§10.2). The evidence is the COBOL CALL, so the line is drawn although the assembler brings no arrows of its own (§3 non-goals) |
| B13 | Payments → out:shared-copybooks "COPY · PAYREC" | confirmed | CLMB300.cbl:6; shared-copybooks/PAYREC.cpy |
| B14 | Payments → out:claims-db "SQL · PAYMENT" | confirmed | CLMB300.cbl:9 `INSERT INTO CLMS.PAYMENT`, exact DDL match |
| B15 | Payments → Claim pricing "CALL · CLMB210" | confirmed | cobol.pds/CLMB400:4 `CALL 'CLMB210'` literal (CLMB210.cbl:2) |
| B16 | Not yet grouped → out:shared-copybooks "COPY · ADDRREC, CLMPROC +1" | confirmed | CLMB500.cbl:8,9,12 (CLMREC, ADDRREC, CLMPROC, all in shared-copybooks). Ungrouped files still bring their evidence (§4.2 "Not yet grouped") |
| B17 | Not yet grouped → Claim pricing "CALL · CLMB210" | confirmed | shared-copybooks/copylib/CLMPROC:2 `CALL 'CLMB210'`, COPYed at CLMB500.cbl:12 (expected_links I3) |
| B18 | Not yet grouped → out:claims-db "SQL · CLAIM" | confirmed | CLMPROC:3 `FROM CLMS.CLAIM` via CLMB500.cbl:12 |

Not drawn, on purpose:

- Links inside one box: STEP0x0 → SORT/IEBGENER/DMBATCH/IEFBR14 (utilities are the job's own
  work, §10.1); every read/write of CLAIMS.EXTRACT (CLMD100.jcl:24,28; CLMEXT.proc:4, partial
  and from Nightly jobs since the step's `runs` is not confirmed), `&UNDEF..OUT.FILE`
  (CLMD300:4, partial); CLMB200 `CALL WS-PGM` → CLMB210 (CLMB200.cbl:31, partial, both in
  Claim pricing). They are counted on the box ("+N links (M partly known)").
- CLMB510 `INSERT INTO CLMS.CLMHIST` (CLMB510.cbl:9, partial): the table has no DDL and only one
  box of this repo touches it, so it is a detail line on "Not yet grouped", not a box (§10.2:
  "only when two groups touch them"). claims-api's use is named on that line, not drawn.
- CLMD100.jcl:31 (`//*` comment) and CLMB200.cbl:30 (column-7 comment): no edges at all.
- CLMPRC.proc standalone: CLMD300 calls it, so it gives no step of its own (base Ruling 8).

## claims-api: files to boxes

Patterns in `gitdiagram-claims-api.json`; `*Repository.java` matches the three repositories.
`src/main/resources/application.yml` is a config file the scanner reads (§10.5) and is left out
of every group on purpose: "Not yet grouped" (§4.2). It defines no node, so it brings no lines.

## claims-api: lines

| Id | Line | Status | Source and rule |
|---|---|---|---|
| A1 | REST endpoints → REST controllers "runs · ClaimController" | confirmed | ClaimController.java:16 `@GetMapping("/claims/{id}")` and :21 `@PostMapping("/claims")` under :6 `@RequestMapping("/api")`; handler class :7 (base Ruling 25). One actor box per kind (§10.3) |
| A2 | out:claims-portal → REST endpoints "REST · GET /api/claims/{}, POST /api/claims" | confirmed | claims-portal claim.service.ts:10,14 call our two endpoints (expected_links). Another repo reaching an entry point of this one: its stub on the outside, the line into the actor that holds the endpoint (§4.2 entry points, stub per outside repo). R5 does not apply: the caller is not a group of this repo |
| A3 | Outbound clients → REST controllers "REST · GET /api/claims/{}" | partial | PartnerClient.java:13 absolute URL matching our GET path on the path only (base Ruling 36: partial). A group's call to an entry point of this repo is drawn to the handler's group, no more certain than the call or the endpoint → handler edge (R5): least(partial, confirmed) = partial |
| A4 | REST controllers → MQ gateway "uses · MqClaimGateway" | confirmed | ClaimController.java:11 constructor parameter |
| A5 | REST controllers → z/OS Connect client "uses · ClaimStatusClient" | confirmed | ClaimController.java:11 constructor parameter |
| A6 | MQ gateway → out:claims-online "MQ PUT · CLM.REQ.LQ" | confirmed | MqClaimGateway.java:22 `${mq.request}` = CLM.REQ (application.yml:3), QALIAS → CLM.REQ.LQ, defined in claims-online/mq/claims.mqsc:2: another repo (§4.2, §10.2) |
| A7 | MQ gateway → out:claims-online "MQ GET · CLM.RSP" | confirmed | MqClaimGateway.java:26, `${mq.reply}` = CLM.RSP (application.yml:4), claims.mqsc:7. Different family from A6 |
| A8 | MQ gateway → out:missing "no consumer found · …CLM.AUDIT" | partial | AuditPublisher.java:15 puts to CLM.AUDIT, which no MQSC defines: a resource with no defining file, touched by one group only, so a detail line on MQ gateway (§10.2). Its gap edge (put only, no get or trigger: partial, base Ruling 21) leaves from there to the loose-ends stub. Stub rule; a loose end never looks solid. claims-online CLMO140's put is named on the detail line, not drawn |
| A9 | Data access → out:claims-db "SQL · PAYMENT, POLICY" | partial | ClaimRepository.java:15 `CLMS.POLICY` (confirmed) and PaymentArchiveRepository.java:17 `OLDS.PAYMENT` (partial: OLDS is not an environment qualifier). Both tables are in claims-db: one line to the one stub, at the least certain edge under it (stub rule, C3: never more certain than PAYMENT). See "Needs a ruling" in the task 9 report |
| A10 | z/OS Connect client → out:claims-online "REST · GET /zos/claims/{}/status" | partial | ClaimStatusClient.java:19 with zosUrl from application.yml:6; the zosapi is in claims-online (apis/claimstatus/package.xml); host not tied to claims-online: partial (base Ruling 36) |
| A11 | Outbound clients → out:external "REST · rates.example.com" | loose | RatesClient.java:11 absolute URL nothing serves (expected_links): loose. Stub rule |
| A12 | REST controllers → Data access "looks up claims in" | partial (suggested) | the one suggested link in gitdiagram-claims-api.json; suggested arrows are always dotted and name existing groups (§4.2, §2) |

Not drawn, on purpose:

- ClaimHistoryRepository `FROM CLMS.CLMHIST` (ClaimHistoryRepository.java:16, partial): no DDL,
  one box of this repo touches it: a detail line on Data access (§10.2). The batch use is named.
- claims-portal → `missing:endpoint:DELETE /api/claims/{}`: neither end is in claims-api.
- JmsTemplate / RestTemplate / JdbcTemplate: not repo classes, no `uses` (expected_links).
- No jobs in claims-api: no Scheduler.

## Changes made after running the gate

- First run: all 30 entries matched exactly (claims-batch 18, claims-api 12; 19 confirmed,
  7 partial (one of them the suggested link), 3 loose, 1 structural), with no unexpected
  line. No entry was changed and no view fix was needed.
- `tests/test_gitdiagram_cli.py` copies the estate; its tests start with no gitdiagram file,
  so its helper now removes the two fixture files from the copy.
