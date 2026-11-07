# Architecture Diagram Skill for GitHub Copilot: Design

Date: 2026-11-06
Status: draft, awaiting approval (builder check done)

## 1. What this is and why

We are building a **skill for GitHub Copilot** and delivering it to clients. A client installs it on their own Windows machine, points Copilot at one repo or many linked repos, and gets **pictorial architecture diagrams** of what is in that code and how the repos connect.

Most client code is **mainframe** (COBOL, JCL, CICS, DB2, VSAM, MQ) alongside **Java** services and **Angular** front ends. A typical client has **hundreds of programs** across **5 to 50 or more repos**, and those repos depend on each other in ways nobody has written down.

The people looking at the diagrams are:

- **Architects and developers planning modernization.** They need the big picture: what talks to what, where the boundaries are, and what is tangled together.
- **New developers joining the team.** They need a map they can follow from a screen or a batch job down to the program and the table.

### What success looks like

A client architect opens a diagram, trusts it, and can check any line on it against the code. A new developer can follow one batch job or one online transaction end to end without asking anyone.

### Anti-goal (the failure that matters most)

**A missing link between repos, or a wrong connection.** A diagram that looks good but leaves out a dependency, or draws one that isn't real, is worse than no diagram, because people will plan modernization around it. Correctness wins over looks every time.

## 2. Decisions the user made

- **Platform:** GitHub Copilot in **VS Code** (agent mode) and the **Copilot CLI**. One skill serves both.
- **Client machine:** Windows with **VS Code and Python**. The **internet may be blocked**.
- **Code it must understand:** COBOL, JCL and CICS (mostly), plus Java and Angular.
- **Input:** one repo, or many linked repos.
- **Outputs:** SVG only, no PNG. **Python 3.9+** is fine. **No real client code is available yet.**
- **Visual styles:** **all four** sample styles are wanted (see `docs/samples/`):
  - **A. Pictorial icons:** a picture per kind of thing, a colored group per repo, numbered steps.
  - **B. C4-style boxes:** standard architecture boxes with technology labels and a sentence on each arrow.
  - **C. Repo link map:** repo cards listing key files, with lines showing exactly how repos link and where in the code each link was found.
  - **D. Whiteboard sketch:** hand-drawn look for walkthroughs and slides.
- **All four mainframe samples were approved**, and so were the four zoom levels they show (§5).
- **Stand-alone:** the skill shares no code with `mainframe-modernization-analyst`. Its parsers are written fresh.
- **This repo** (`copilot-architecture-diagrams`) is where the skill gets built.

## 3. Goals

1. Scan one or many local repos and build a complete inventory of parts and links, across COBOL, JCL, CICS, DB2, MQ, Java and Angular.
2. Find **cross-repo links** reliably, each backed by file-and-line evidence for both ends.
3. Draw diagrams at four zoom levels, in any of the four styles.
4. Show uncertainty openly: confirmed, partly known, and loose ends look different on every diagram.
5. Produce a links report alongside each diagram so a reviewer can check the picture against the code.
6. Run fully offline on a locked-down Windows machine.

## 4. Non-goals

- Changing client code in any way. The skill only reads.
- Runtime tracing, SMF records, scheduler exports or production data. It works from source code only. (Reading scheduler definitions that happen to sit in a repo is a possible later addition.)
- Recommending how to modernize. It shows what exists; people decide.
- Rendering PNG. SVG is the picture format (§8).
- Any cloud service, CDN, or download at run time.
- Reusing code from `mainframe-modernization-analyst`.

## 5. Zoom levels

At this size, one picture can't hold everything, so the skill draws four levels. Each level has a default style, and the user can ask for any style at any level.

| Level | Shows | Main audience | Default style |
|---|---|---|---|
| 1. Landscape | One box per application or repo group, the shared data stores and queues, outside systems, and every cross-application link | Architects | B (C4) |
| 2. One application | Its jobs, transactions, programs and data stores, plus what it exchanges with the rest | Planning one piece of work | A (pictorial) |
| 3. One flow | One batch job (steps, programs or utilities, data read above the steps, data written below, condition codes) **or** one online transaction (Angular page → Java → MQ/CICS → programs → DB2, including the 3270 route) | New developers | A for batch, D for walkthroughs |
| 4. Repo link map | Repo cards with key files, and every link between repos labeled by what connects them (queue, table, dataset, copybook, endpoint, CICS program) with the evidence lines | "What breaks if I change this?" | C |

Level 2 has no sample yet. It should look like level 1's style A, but scoped to one application with its neighbors shown as grey stubs. (My call. The user can review it in the first build.)

## 6. How it works

```
 repos folder ──► 1. scan (Python) ──► inventory.json
                                           │
                       2. resolve links (Python) ──► links.json (+ evidence, status)
                                           │
                3. group (Copilot) ──► groups.json   ← user can edit and re-run
                                           │
             4. draw (Python) ──► .svg + editable file + links report
```

1. **Scan (Python script).** Walks every repo and writes a single inventory of what it found, with the file and line for each fact. Copilot never reads hundreds of programs one by one; it would run out of room and start guessing.
2. **Resolve links (Python script).** Matches the two ends of every connection across all repos (§7) and gives each link a status.
3. **Group (Copilot).** Copilot reads a compact summary of the inventory and proposes named applications (for example "Claims Online" = these CICS programs + these transactions). It writes this to `groups.json`. The user can rename or regroup by asking Copilot or editing the file. **Copilot may not add links.** If it suspects one, it records it as `suggested`, which is drawn as a dotted line, never a solid one.
4. **Draw (Python script).** Takes the level, the scope (whole estate, one application, one job, one transaction or one repo) and the style, and writes the outputs (§8). The scripts do all layout and drawing, so diagrams come out consistent and repeatable.

**Input assumption:** the client clones every repo into one folder. If that folder is itself a git repo, it's treated as a single repo. Otherwise each child folder that holds a repo is one repo.

## 7. What the scanner finds, and how links are matched

### 7.1 Facts extracted

**JCL:** jobs; steps; `EXEC PGM=` and `EXEC` procedure calls (expanding in-repo PROCs and INCLUDEs); DD statements with `DSN` and `DISP`; GDG relative generations (`(+1)`, `(0)`); temporary datasets (`&&`); `SET` and PROC default symbols; `COND` and `IF/THEN` between steps; utilities (SORT, IEBGENER, IDCAMS, and so on); DB2 programs run through `IKJEFT01` with `DSN RUN PROGRAM(...)` in SYSTSIN; file-transfer steps (Connect:Direct/NDM, FTP), which have targets outside the repos.

**COBOL:** `PROGRAM-ID`; `COPY` (including `REPLACING`); `CALL` with a literal versus a variable; `SELECT ... ASSIGN TO` ddname (tied back to the JCL DD in the step that runs the program); `EXEC SQL` tables and operations (SELECT, INSERT, UPDATE, DELETE, cursor); `EXEC CICS` LINK, XCTL, START, RETURN TRANSID, READ/WRITE FILE and TS/TD queues; MQ calls (MQOPEN/MQPUT/MQGET) with the queue name resolved from a `VALUE` clause where possible. Fixed-format columns (7 to 72) and sequence numbers are handled.

**CICS definitions and maps:** CSD `DEFINE TRANSACTION ... PROGRAM(...)` and FILE definitions; BMS mapsets.

**DB2 DDL:** tables, views, aliases and synonyms, with their schema.

**MQ definitions** (if present in a repo): local, alias and remote queues.

**Java:** Spring endpoints (`@RequestMapping`, `@GetMapping`, and so on); outgoing HTTP calls (RestTemplate, WebClient, Feign) with their URLs; JMS/IBM MQ queue names from literals and `application.yml`/`.properties`; table names in JDBC/JPA SQL; CICS calls through CTG/ECI or z/OS Connect, with the program or API name.

**Angular:** `HttpClient` calls with their URLs, base URLs from `environment*.ts`, and routes to components (so a page name can head a level 3 flow).

### 7.2 Matching the two ends

| Link kind | One end | Other end | Matching rules |
|---|---|---|---|
| Dataset | JCL DD that writes | JCL DD that reads | Resolve symbols, compare GDG base names, ignore temporary `&&` datasets across jobs |
| DB2 table | SQL in COBOL/Java | DDL, or other SQL | Strip or resolve schema qualifiers, follow aliases and synonyms |
| MQ queue | PUT | GET | Follow alias and remote queue definitions when present |
| CICS program | LINK/XCTL, Java CTG call, CSD transaction | `PROGRAM-ID` | Case-insensitive 8-character names |
| COBOL CALL | `CALL 'X'` | `PROGRAM-ID X` | Literal only, otherwise partly known |
| Copybook | `COPY X` | `X.cpy` / member file | Search all repos' copybook folders |
| REST | Angular/Java client URL | Spring endpoint | Join the base URL from config, normalize path parameters (`{id}`, `:id`, `${id}`) |

### 7.3 Status of every link

- **Confirmed (solid line):** both ends found, names match after normalization.
- **Partly known (dotted orange):** one end is computed at run time (`XCTL` to `WS-NEXT-PGM`, `CALL` through a variable, an unresolved `&HLQ`), or the match needed a guess (a symbol default, a fuzzy table name), or Copilot suggested it.
- **Loose end (red line ending in a dot):** only one side was found. For example, a dataset is written and never read in these repos, or Java calls a CICS program that isn't in any repo. These usually mean a repo is missing or the link goes outside the estate.

Every link stores both ends' file and line. Partly known links also record **why** they are partly known.

### 7.4 When a match counts as confirmed (my call)

The rule: **a link is solid only when the name is fully worked out from code in the repos and exactly one thing matches it.**

- **JCL symbols:** values from `SET`, PROC defaults and EXEC overrides count as worked out, because they are in the code, so a match through them is **confirmed**. A symbol with no value anywhere in the repos makes the link **partly known**.
- **Environment qualifiers** (TEST vs PROD high-level qualifiers, DB2 schemas per environment): a configuration file lists which qualifiers count as environment names. It ships empty, and Copilot proposes entries by spotting names that differ only by qualifier. A match that is only possible after dropping a listed qualifier is **confirmed**. Dropping any other qualifier makes it **partly known**. When the same job exists in several environment copies, the diagram draws one, and the report lists the copies.
- **Unqualified SQL table** (schema set at bind time): **confirmed** if exactly one table with that name exists across all scanned DDL, and **partly known (ambiguous)** if more than one does.
- **Duplicate names:** if a program, copybook or table name is defined in more than one repo, or more than once in one repo (for example Endevor or ChangeMan stage folders), every link to it is **partly known (ambiguous)**. The report lists each candidate.

### 7.5 Links made outside the program code (my call)

Online flows often connect through definitions rather than through calls in the COBOL. When these files are in a repo, the scanner reads them and adds a link kind **"triggers"**:

- **MQ process definitions and trigger settings** (`INITQ`, `PROCESS`, `APPLICID`): link the queue to the CICS transaction.
- **CICS-MQ bridge** queues: link the queue to the transaction or program.
- **z/OS Connect** service and API archive definitions: link the API path to the CICS program.

If a queue is used by a program but none of these definitions is found, the queue end is shown as **partly known ("how this queue reaches CICS isn't in these repos")**, not as a red loose end. This keeps a whole online flow from turning red just because the MQ or z/OS Connect definitions live outside source control.

### 7.6 Code the skill doesn't analyze (my call)

Assembler, PL/I, Easytrieve, REXX/CLIST, IMS DL/I and DB2 stored procedures aren't analyzed. The scanner still **registers their program names** from file or member names and obvious entry points. So a `CALL` or `EXEC PGM=` to one of them is shown as reaching a **grey "not analyzed" box**, not as a red loose end. The links report lists which languages were found but not covered.

Files exported from PDS libraries often have no extension or odd ones, so the scanner decides file type by content as well as by extension.

## 8. Outputs

Everything goes in `architecture-diagrams/` in the folder that holds the repos (my call), next to the cached `inventory.json`, `links.json` and `groups.json`.

For every diagram:

| Style | Picture | Editable file |
|---|---|---|
| A. Pictorial | `.svg` | `.drawio` (draw.io / diagrams.net) |
| B. C4 boxes | `.svg` | Mermaid in a `.md` file, so it shows as a picture in GitHub and Azure DevOps wikis |
| C. Repo link map | `.svg` | stand-alone `.html` (offline, no CDN) where clicking a link shows its evidence |
| D. Whiteboard | `.svg` | `.excalidraw` |

Plus a **links report** (`<diagram>-links.md`): every link on the diagram with its status and both evidence lines, then every loose end and partly known link, and a list of names that look like they belong to a repo that wasn't scanned.

**SVG is the main picture format.** It opens in Edge, VS Code, Word and PowerPoint, and it prints sharp. **PNG is not produced** (user decision). Clients use SVG directly.

The whiteboard look must survive Word and PowerPoint, which ignore SVG filters. So the wobble is drawn into the path points, not done with an SVG filter as in the browser sample. Fonts fall back from Segoe Print to Comic Sans MS, both of which ship with Windows.

**Size limit per diagram (my call):** about 40 boxes. Above that, the skill groups the smaller items ("… 35 more programs") and suggests the next zoom level down rather than drawing an unreadable diagram.

## 9. How a client uses it

They ask in plain words in Copilot chat (VS Code agent mode) or in Copilot CLI, for example:

- "Draw the landscape for these repos."
- "Show me batch job CLMD100."
- "Draw the claim details transaction as a whiteboard sketch."
- "Link map for claims-batch: what depends on it?"
- "Draw everything in all four styles."

**If Copilot isn't allowed to run commands** (organization policy or terminal approval), the skill falls back to one command, or a VS Code task, that the user runs. Copilot then reads the outputs and carries on. The README documents this route. (My call.)

The skill scans on first use and reuses the inventory afterwards. It rescans when asked, or when the repos have changed since the last scan (the builder decides how to detect that). After drawing, Copilot replies with the file paths, a two-line summary, and the count of loose ends and partly known links, with the top few named.

## 10. Constraints

- **Python standard library only.** No pip installs, no network. Works with **Python 3.9 and newer** (user confirmed).
- **Windows first:** paths with spaces, long paths, CRLF line endings. Source files may be UTF-8, Windows-1252 or Latin-1, so the scanner reads them with a fallback and never crashes on bad bytes.
- **Offline everything:** HTML outputs carry their own CSS and JS inline.
- **Skill packaging:** a folder with `SKILL.md`, `scripts/`, `assets/` (icon shapes, templates) and a short `README`. It installs as a personal skill (in the user's Copilot skills folder) or as a project skill (inside a repo's `.github/skills/`). **The builder must confirm the current folder locations and `SKILL.md` front-matter for both VS Code and Copilot CLI** against GitHub's documentation before building. I believe they share the Agent Skills format, but haven't verified this.
- **Privacy:** the scripts send nothing anywhere. Copilot itself sees the inventory summary under the client's existing Copilot agreement, and the client README should say so plainly.
- **Performance:** scanning 50 repos with hundreds of programs should take minutes, not hours, on a normal laptop.

## 11. Testing (proving there are no missing links)

- Build a **fixture estate**: the made-up claims system from the samples (6 repos), with a hand-written list of every expected link and its status, including deliberate traps: symbolic dataset names, GDGs, a variable XCTL, an MQ alias queue, a schema-qualified table, a REST path with parameters, a dataset with no reader, and a repo left out on purpose.
- Test the scanner and link resolver against that list. **Every expected link must be found (no misses), and no unexpected solid links may appear.** These two checks are what the anti-goal is about, so they gate every release.
- Snapshot-test the drawn outputs so layout changes are deliberate.
- Run on Windows with a fresh Python and no network access before each delivery.
- **No real client code exists yet** (user). So the fixture estate is the only test before the first delivery, and that is a known weakness. The first client engagement starts with a **calibration step**: run the skill on their repos, have one of their mainframe developers review the links report for a sample of jobs and transactions, and add every missed or wrong link to the fixture estate as a new test before the diagrams are relied on.

## 12. Left to the builder

- The internal shape of `inventory.json`, `links.json` and `groups.json`.
- The layout method for each level, using only the standard library (a layered left-to-right layout for flows, and a grid with grouping for the landscape are the likely choices). **This is the biggest technical risk.** Prove it on the fixture estate early.
- The exact icon drawings, matching the approved samples.
- How rescans detect changes.
- How `SKILL.md` instructions are split between the main file and reference files.
- An optional `install.ps1` that copies the skill into place.

## 13. Calls I made (please check)

- Level 2 drawn in style A by default, with no sample yet.
- Outputs in `architecture-diagrams/` next to the repos.
- A size limit of about 40 boxes per diagram.
- Mermaid (not PlantUML) as the editable form of style B, because PlantUML needs Java.
- The confirmed vs partly known rules in §7.4.
- Reading MQ trigger, CICS-MQ bridge and z/OS Connect definitions, and treating their absence as partly known rather than a loose end (§7.5).
- Registering, but not analyzing, Assembler, PL/I, Easytrieve, REXX and IMS programs (§7.6).
- A fallback where the user runs one command if Copilot can't run commands (§9).
