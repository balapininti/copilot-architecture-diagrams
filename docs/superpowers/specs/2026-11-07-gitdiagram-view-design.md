# "Gitdiagram" View for One Repo: Design

Date: 2026-11-07
Status: draft, awaiting approval
Builds on: `docs/superpowers/specs/2026-11-06-architecture-diagram-skill-design.md` (the skill as shipped in 0.1.3). Everything that spec says about certainty, evidence, Office-safe SVG, offline use, Python 3.9 stdlib-only and Windows still holds.

## 1. What this is and why

Clients want the kind of picture [GitDiagram](https://gitdiagram.com) draws for a GitHub repo. The reference is the page it made for this skill's own repo: https://gitdiagram.com/balapininti/copilot-architecture-diagrams. That picture has:

- **Named groups** of related files, like "Repository scanning", "Graph analysis", "Diagram views" and "Layout and output".
- **One box per part**, like "COBOL scanner [cobol.py]".
- **Labelled arrows**, like "starts the scan", "resolves links" and "emit nodes".
- **An actor** ("Engineer") who starts things.
- **Clickable boxes** that open the file or folder.
- **A colour per group**, a short overview paragraph, and Mermaid output.

The skill today shows how repos connect to each other and how one job or one transaction runs. It doesn't show **how a single repo is put together**. That is what a developer just handed a repo, or an architect sizing one piece of modernization, wants first.

The user asks Copilot something like "create a gitdiagram for claims-batch", and gets that picture for a repo they have **cloned locally**.

## 2. Decisions the user made

- **Arrows:** an arrow backed by code evidence is solid. An arrow Copilot only infers is **dotted**, marked "suggested". This is the skill's existing certainty rule. GitDiagram's own arrows are an AI's best guess; ours are not.
- **Repos are cloned locally.** A click on a box opens the **local** file or folder, not a web page.
- **One box = a group of related files that Copilot names.** Example: "Claim pricing" holding CLMB200, CLMB210 and CLMB300. A box is not one file, and not one folder.
- **Same groups every time.** Copilot saves its grouping to a file the user can edit, and later runs reuse that file instead of regrouping.
- The rest of the playback was approved as described in §4–§6: entry points along the edge, a "Not yet grouped" box, the file name, the outputs and the non-goals.

## 3. Goals, non-goals, anti-goals

**Goals**
1. A new zoom level, `gitdiagram`, scoped to one scanned repo.
2. Copilot proposes named groups, a technology label per group and an overview paragraph the first time, and saves them to an editable file.
3. Arrows between groups come from the scanner's evidence. Copilot may add dotted suggested arrows with a short reason.
4. Every box links to its local file or folder.
5. Output in all four existing styles plus Mermaid, with the usual links report.

**Non-goals**
- Working from a GitHub URL without a local clone, or fetching anything from the web.
- Analysing languages the scanner doesn't analyse. Their files can still be placed in groups; they just bring no evidence arrows.
- Diagrams that span several repos. The landscape and repo-map levels already cover those.

**Anti-goals** (a failure even if it works)
- A solid arrow without code evidence.
- Different groups on every run.
- A file that quietly disappears from the picture. Every file the scanner typed is in a group, or in "Not yet grouped", or listed as not scanned.

## 4. How it works

```
user: "create a gitdiagram for claims-batch"
  1. scan (existing)                         → inventory.json / links.json
  2. gitdiagram file missing? Copilot reads:
       - `run.py gitdiagram-context --workspace <ws> --repo claims-batch`
         (file tree with each file's scanner-detected kind and main names,
          the README text if present, and the evidence links between files)
     and writes architecture-diagrams/gitdiagram-claims-batch.json
  3. `run.py draw --level gitdiagram --scope claims-batch --style …`
       → reads the gitdiagram file, builds the view, lays it out, renders
```

### 4.1 The gitdiagram file

`architecture-diagrams/gitdiagram-<repo>.json` is written by Copilot, can be edited by the user, and is read by the CLI. Its shape (field names are the builder's to refine):

```json
{
  "repo": "claims-batch",
  "overview": "Nightly claims batch: sorts the claim master, prices claims (CLMB200/210), posts payments to DB2 (CLMB300) and sends an extract to Finance by Connect:Direct.",
  "groups": [
    {"name": "Claim pricing", "tech": "COBOL", "files": ["cobol/CLMB200.cbl", "cobol/CLMB210.cbl"], "description": "Prices each claim"},
    {"name": "Nightly jobs", "tech": "JCL", "files": ["jcl/CLMD100.jcl", "proc/*.proc"]}
  ],
  "suggested_links": [
    {"from": "Nightly jobs", "to": "Finance feed", "label": "hands the extract to", "note": "inferred from README"}
  ]
}
```

- Files are listed as repo-relative paths or globs.
- A file that matches several groups goes to the first group that matches, the same rule `groups.json` uses.
- Problems in the file never stop a draw. These include unknown files, empty groups, duplicate names and bad JSON. They are listed in the links report and the summary, as `groups.json` problems are today.

### 4.2 What the picture shows

- **Boxes:** one per group. Each box shows:
  - the group name;
  - the `[tech]` label;
  - up to 4 file names, then "… N more" (the full list is in the links report);
  - the description, if there is one.
  - Boxes get a colour per group, in a palette that sits beside the four line-type colours without clashing.
- **Solid and certain arrows:** these come from every resolver edge whose two ends belong to files in different groups of this repo. They are combined per (group pair, link kind) and labelled with the kind plus up to 2 names, like "CALL · CLMB210", "COPY CLMREC", "SELECT CLAIM" or "imports".
  - Status follows the existing combining rule: the line is never more certain than the least certain target its label names (the landscape rule from the C3 fix).
  - Loose and partial ends stay visible, as in the other levels.
- **Shared resources inside the repo:** datasets, tables and queues that two groups of the same repo both touch. These are drawn as their own small boxes between the groups, the same way the landscape does it.
- **Outside this repo:** anything the repo reaches in another scanned repo, or nothing at all (missing or external). This is collapsed to one grey stub per outside repo or kind, like "→ claims-db (3 tables)" or "→ 2 loose ends", so the reader sees the repo's edges without the other repos' insides.
- **Entry points along the left edge,** standing in for GitDiagram's "Engineer". They are taken from the scan, never invented:
  - the scheduler, for JCL jobs;
  - CICS transaction ids, from the CSD;
  - REST endpoints, for a Java service;
  - routes, for Angular pages;
  - z/OS Connect APIs.
  - Each is linked to the group that holds its handler or program.
- **Suggested arrows:** dotted orange, labelled from the file, reason "suggested by Copilot: <note>". They must name existing groups or entry points.
- **"Not yet grouped":** a box listing files the scanner typed that no group claims (for example files added since the grouping was saved). The CLI's stdout names how many there are, so Copilot can offer to place them.
- **Overview:** the paragraph is printed above the picture in the SVG, the Mermaid `.md` and the HTML, and at the top of the links report.

### 4.3 Clickable boxes

- Each box links to its group's first file, or to the folder when all the group's files share one. Entry points and shared resources link to the file that defines them.
- Links are **relative** from `architecture-diagrams/` to `../<repo>/<path>`, so they work when the SVG or HTML is opened from the workspace in a browser or VS Code.
- The SVG uses `<a href>`, which is Office-safe. Office simply ignores it.
- The Mermaid output uses `click <node> "<relative path>"`.
- The draw.io output uses each cell's `link` attribute.
- The Excalidraw output uses each element's `link` property.
- Evidence paths inside archives (`x.aar!/…`) link to the archive file.

### 4.4 Size

- At most 40 boxes, the same `MAX_NODES` cap as the rest of the skill.
- Groups are the user's or Copilot's choice. If they produce more than 40 boxes, the existing cap folds the smallest into "… N more" and adds a note suggesting fewer groups.
- When Copilot first proposes groups, it aims for roughly 6–15. For the README-less mainframe repos clients often have, it groups by what the code shows: job streams, the programs they run, shared copybooks, online transactions.

## 5. Copilot's part (SKILL.md)

- Trigger phrases: "gitdiagram", "diagram of this repo", "how is <repo> put together", "repo structure".
- If no gitdiagram file exists, Copilot runs `gitdiagram-context`, then proposes groups, tech labels, short descriptions and the overview, and **shows them to the user before saving**. The user can rename, merge or split groups. Then Copilot writes the file and runs `draw`.
- If the file exists, Copilot draws straight away. When stdout reports files in "Not yet grouped", Copilot offers to place them.
- Copilot never invents solid arrows. Any link it believes in goes into `suggested_links`, with a note saying why.
- Copilot never edits files outside `architecture-diagrams/`, as the skill already requires.

## 6. Outputs

These go in `architecture-diagrams/`, alongside the existing outputs:

- `gitdiagram-<repo>-{a,b,c,d}.svg`
- the editable copies the other levels already make: `.drawio`, Mermaid `.md` and `.azure.md`, `.html`, `.excalidraw`
- `gitdiagram-<repo>-links.md`

Default style: **B (C4 boxes)**. It is the closest to the GitDiagram look.

## 7. Constraints

- Everything the main spec §10 says still applies: Python 3.9+ stdlib only, offline, Windows paths, Office-safe SVG, the four line colours, deterministic output.
- The gitdiagram file is UTF-8 JSON and is read tolerantly: no crash on bad input, problems are reported.
- `gitdiagram-context` output must fit Copilot's context for a repo of several hundred files. It is a compact table of path, kind and main names, with the README capped at about 200 lines. For bigger repos it summarises per folder and says so.

## 8. Testing

- **Fixture:** add `gitdiagram-claims-batch.json` and `gitdiagram-claims-api.json` to the claims estate, written by hand.
- **Hand-written expected group-to-group arrows** with their statuses, added to the release gate or a sibling gate. The same discipline applies: written from the rules, not from the output.
- **Tests:**
  - every typed file is grouped, in "Not yet grouped", or listed as not scanned;
  - no solid arrow without an underlying confirmed edge;
  - suggested arrows are always dotted;
  - links resolve to existing local files;
  - all four styles and the editable copies carry the links;
  - an edited file is honoured;
  - a malformed file is reported, not fatal;
  - output is deterministic.
- **Visual check:** render claims-batch and claims-api in all four styles and compare them with the GitDiagram reference for readability.

## 9. Left to the builder

- Exact JSON field names and the `gitdiagram-context` format.
- Box layout. Reuse the layered or context layout, whichever reads better.
- The group colour palette.
- How file lists inside boxes are shortened.
- Whether "Not yet grouped" is drawn as a box or as a note when it is empty.

## 10. Settled after the builder check

1. **Dataset arrows start from the program's group, not the job's.**
   - A step's dataset access is drawn from the group that holds the program the step runs. That needs the step's `runs` edge plus the DD/SELECT match.
   - Such an arrow stands on two resolver edges, so its status is the less certain of the two. It is solid only when both are confirmed.
   - When the program isn't in this repo, or the match can't be made, the arrow starts from the job's group.
   - Utilities such as SORT, IEBGENER and IDCAMS count as the job's own work, so their arrows start from the job's group.
2. **A resource defined in a grouped file is part of that group.** Tables whose DDL is in a "Claims schema" group, copybooks in a "Shared copybooks" group, and queues defined in an MQ file all count this way. Arrows go into that group, like "SELECT CLAIM" or "COPY CLMREC", following the landscape's datastore precedent.
   - Only resources with **no defining file in this repo** become their own small shared boxes, and only when two groups touch them.
   - A DDL or copybook file is "grouped" like any other file.
3. **Entry points**
   - **One actor box per kind,** folded: "Scheduler", "CICS transactions (12)", "REST endpoints (8)", "Angular pages (5)", "z/OS Connect APIs (2)". The names are listed inside the box and in full in the links report, so 50 routes don't overrun the cap.
   - **CICS, REST, page and API entries:** their arrows to the handler or program groups come from resolver edges and follow the normal certainty rule.
   - **The Scheduler:**
     - It is drawn only for jobs that no other job or step in the repo submits.
     - Its arrows are a third, **structural** kind of line: thin, plain grey, labelled "starts", with its own legend entry ("starts — the job exists; who schedules it isn't in these repos"). This reuses the existing `sequence` kind.
     - It is never drawn solid in a certainty colour, and never claims a scheduler definition.
4. **No gitdiagram file yet** (for example when the user runs `draw` themselves, without Copilot):
   - The CLI falls back to a default grouping, one group per top-level folder of the repo, named after the folder.
   - It adds a note: "Grouped by folder. Ask Copilot to name groups for this repo."
   - It doesn't write a file. Only Copilot or the user writes `gitdiagram-<repo>.json`, so "same groups every time" applies to groupings someone chose.
5. **Files that must be accounted for** (the completeness rule) are every file the scan classified:
   - source and definition files: COBOL, copybook, JCL, PROC, CSD, BMS, DDL, MQSC, Java, Angular TS, z/OS Connect;
   - the config files the scanner reads (application yml/properties, environment ts);
   - files in languages the scanner registers but doesn't analyse.
   
   Not counted: archive members (the archive file itself counts), and data or control members only read as SYSIN.
   
   The inventory gets a per-file list, with a schema bump, so the view, `gitdiagram-context` and the completeness test all use the same list.

## 11. Calls I made (please check)

- The file name is `gitdiagram-<repo>.json`, and the level name is `gitdiagram` (CLI: `--level gitdiagram --scope <repo>`).
- Default style B.
- Copilot shows the proposed groups to the user before saving them.
- Links outside the repo are collapsed to one stub per outside repo or kind, so the picture stays about this repo.
- A new CLI command, `gitdiagram-context`, gives Copilot what it needs to propose groups.
- Box links point at a group's first file, or at its shared folder.
