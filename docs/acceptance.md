# Acceptance: Windows, offline, Copilot

Task 19 of the architecture-diagrams skill. The build machine is macOS with Python 3.14 only:
no Windows, PowerShell, Copilot, VS Code agent mode, Office or draw.io. So this file has two
parts. **Run here (results)** holds checks that were actually run, with real output.
**To run on Windows (checklist)** holds everything else, with a blank result column. Nothing in
the second part has been run, and none of it is marked as passed.

Date of the run here: 2026-11-07. Commit under test: branch `build/v1` (release 0.2.0 plus later work).

## Run here (results)

Working copy: the fixture was copied to
`<scratchpad>/acceptance/ws` (a copy of `tests/fixtures/claims-estate`); the fixture itself was never written to.
`python3` below is the system Python 3.14.4 (`/Library/Frameworks/Python.framework/Versions/3.14/bin/python3`), not the venv.

| # | Check | Command | Result |
|---|---|---|---|
| 1 | Full test suite | `.venv/bin/python -m pytest -q` | **PASS**: 424 passed in 8.34s |
| 2a | Syntax valid as Python 3.9 | `python3 -I -c "ast.parse(src, f, feature_version=(3,9))"` over all `.py` under `skill/architecture-diagrams/scripts` | **PASS**: 43 files parsed |
| 2b | No 3.10+ constructs | grep for `f"{x=}"`, `match`/`case`, `A \| B` annotations, `removeprefix/removesuffix`, `zip(strict=)`, `dataclass(slots/kw_only)`, `TypeAlias`, `ParamSpec` | **PASS**: no hits. All 43 files have `from __future__ import annotations` |
| 2c | Stdlib only | AST walk of every import, compared with `sys.stdlib_module_names` | **PASS**: only non-stdlib name is `archdiag`, the skill's own package |
| 3 | CLI end to end, system python3, no third-party packages | see list below | **PASS**: every command exit 0 |
| 3b | No network references | grep all outputs for `http://` / `https://` | **PASS** for diagrams (see below) |
| 4 | Every output parses | xml.etree for `.svg`/`.drawio`; json for `.excalidraw`/`.json`; `.md` non-empty; HTML scanned for `src=`/`href=` (non-fragment, non-data), `@import`, `url(http...)` | **PASS**: 58 files checked, 0 failures |
| 5 | Screenshots vs samples | headless Chrome, see "Visual check" | **PASS with known issues** |
| 6 | HTML interaction | headless Chrome `--virtual-time-budget=3000 --dump-dom` | **PASS** |

### 3. Commands and results

All run as `python3 skill/architecture-diagrams/scripts/run.py <cmd> ... --workspace <copy>`; every exit code was 0.

- `scan`: `Scanned 6 repo(s), 79 things found, 79 links (61 confirmed, 8 partly known, 10 loose ends)`; wrote `inventory.json` and `links.json`.
- `summary`: printed the repo, application and link counts and top loose and partial links; wrote `summary.md`.
- `list --what jobs|transactions|pages|endpoints|applications|repos|programs`: all seven exit 0. Examples: jobs gave `CLMD100`, `CLMD100` (test copy) and `CLMD300`; pages gave `claims/:id`; applications gave 6.
- `init-config`: `Wrote .../archdiag.config.json with environment_qualifiers: PROD, TEST` and asked the user to confirm. Note: on the copy it overwrote the fixture's own config (`{"environment_qualifiers": ["PROD","TEST"]}`), which was the same content.
- `draw --style all` for each level. Every run printed nine files (4 SVG, `.drawio`, `.md`, `.html`, `.excalidraw`, `*-links.md`) and a summary:

| Command | Summary line printed |
|---|---|
| `draw --level landscape` | 17 nodes, 22 links: 14 confirmed, 2 partly known, 6 loose ends |
| `draw --level application --scope claims-online` | 26 nodes, 21 links: 13 confirmed, 3 partly known, 5 loose ends |
| `draw --level flow --scope CLMD100` | 18 nodes, 20 links: 16 confirmed, 2 partly known, 2 loose ends (also printed `Note: Also exists as: claims-batch/jcl/test/CLMD100.jcl`) |
| `draw --level flow --scope claims/:id` | 25 nodes, 27 links: 20 confirmed, 3 partly known, 4 loose ends. File names are `flow-claims--id-*` (`/` and `:` become `-`) |
| `draw --level repomap` | 19 nodes, 27 links: 13 confirmed, 4 partly known, 10 loose ends |
| `draw --level repomap --scope claims-batch` | 8 nodes, 9 links: 5 confirmed, 1 partly known, 3 loose ends |

Total files in the output folder: 58 (including `inventory.json`, `links.json`, `summary.md`, `archdiag.config.json`).

### 3b. Network references

- In the `.svg`, `.html`, `.drawio` and `.excalidraw` outputs the only URL is the SVG namespace `http://www.w3.org/2000/svg` (30 occurrences). No external script, stylesheet, font or image.
- `inventory.json`, `links.json` and `*-links.md` contain `https://rates.example.com/v1/rates` and `https://zcee.internal:9443/...`. These are strings copied from the fixture's source code as evidence, not references the tool loads.
- The HTML embeds the same evidence text inside a JSON block with escaped slashes (`https:\/\/rates.example.com/v1/rates`). It is displayed text only.

### 6. HTML interaction

A copy of `repomap-c.html` had a script appended that dispatches a click on the first `g[data-edge]` and writes `#panel` text to `document.title`. Run with `--virtual-time-budget=3000 --dump-dom`. Title became:
`PANEL:← all links table CLMS.POLICYconfirmed claims-api → claims-db Repo File Line Code claims-api src/main/java/com/acme/claims/ClaimRepository.java 15 return jdbcTemplate.query(...) claims-db ddl/POLICY.sql 1 CREATE TABLE CLMS.POLICY`,
and the dumped DOM contains the evidence `<table>` (columns Repo, File, Line, Code). Pass.

### 5. Visual check (headless Chrome, macOS)

Screenshots were taken at each SVG's own size: `flow-clmd100` styles a, b, d (and c SVG), `landscape-a`, `landscape-c`, `flow-claims--id-a`, and the repomap HTML; compared with `docs/samples/mainframe-samples.html`. The PNGs are in the scratchpad `acceptance/shots/` folder; they are not committed.

What matches the samples:
- Style A: same icon set (JCL page, gear utilities, CBL files, DB2/VSAM cylinders, GDG stack, printer, cloud), the same STEP lane, edge labels in pills, red loose-end dots with "no reader/writer found", orange dotted partial lines, legend. Close to the sample.
- Style B: blue C4 boxes with `[type]` subtitles, cylinders for datasets, red loose-end boxes. Matches the sample's look.
- Style D: hand-drawn rough boxes, pastel fills per kind, yellow sticky notes for loose ends and notes. Matches the sample's whiteboard look.
- Style C HTML: repo cards with file rows, dark pill labels on links, side panel "Links between repos" with search box and a list tagged confirmed/partial/loose/shared code. Matches the sample's card style; the click test shows the evidence table.
- Circled numbers: `flow-claims--id-a.svg` contains ①–⑳ and they render in Chrome (1 to 20). The CLMD100 flow has no numbered requests (steps are labelled STEP010 and so on), so use the `claims/:id` flow for that check.

### Known issues

These are readability gaps, not failures of any check. The controller decides which to fix.

1. **Edge bundles in the landscape (style A).** In `landscape-a.svg` several orthogonal lines run in parallel and overlap in the middle column (around the claims-online and claims-batch boxes). Labels such as "SQL · CLAIM", "SQL · POLICY", "MQ GET" sit on top of the bundle, so it is hard to follow one line from end to end. The sample's landscape has far fewer crossings.
2. **Lines cross through boxes.** In the landscape, lines from claims-api and claims-batch cross the claims-online group box and pass close to the claims-batch box. Same for the `claims/:id` flow, where the lines out of CLMO100 form a thick bundle down to CLMU, CLMS.CLAIM and PROD.CLM.MASTER.KSDS.
3. **Very wide flow diagram.** `flow-claims--id-*.svg` is 3300 to 3774 px wide (the sample is about 1100 px). It scales down in Word and PowerPoint, and the 7 to 8 px text then becomes unreadable on a page; edge pills are small.
4. **Step numbers above 20.** The `claims/:id` flow has 27 numbered steps. ①–⑳ render as circled characters; 21 and above fall back to `(21)`. That is by design, but the Windows checklist confirms it also looks acceptable in Word.
5. **Style A flow labels.** In `flow-clmd100-a`, "read (0)" and "write" pills near PROD.CLAIMS.DAILY and REPORT sit close together on crossing diagonals. Readable, but the sample lays them out more cleanly.
6. **Style C HTML at 1500 px.** The map is wider than the map pane (about 1919 px wide for the whole-estate map), so the right-hand cards are cut off until the page is scrolled. Not checked: whether the pane scrolls or zooms in a real browser at 1920 px.
7. **Not compared:** `landscape-b` and `repomap-b/d` screenshots were not individually inspected; they were only parsed.

## To run on Windows (checklist)

**None of these steps has been run.** The Result column is blank on purpose. Run each on a Windows machine
(or Windows CI runner) and write PASS, FAIL or the observation in it. Use the delivered package,
and the fixture `tests\fixtures\claims-estate` as the workspace unless a step says otherwise.
`<fixture>` below means the full path of that folder. Work on a copy if you want the fixture untouched.

### W1. Python 3.9 test suite, network off

Python 3.9 is the lowest supported version, so this is the version to test.

| Step | Command | Pass when | Result |
|---|---|---|---|
| 1 | `py -3.9 --version` | prints `Python 3.9.x` | |
| 2 | `py -3.9 -m venv .venv39` then `.venv39\Scripts\python -m pip install pytest` (pytest is the only install; the one step that needs a network, or an internal index) | pytest installs | |
| 3 | Disable the network adapter or unplug (Wi-Fi off, Ethernet disabled). Confirm with `ping 8.8.8.8` failing | ping fails | |
| 4 | `.venv39\Scripts\python -m pytest -q` from the repo root | `424 passed` (or the current count) and no skips or errors that mention the network | |
| 5 | Re-run `.venv39\Scripts\python -m pytest -q -p no:cacheprovider` in a folder whose path has a space, e.g. `C:\work dir\repo` | same count passes | |

### W2. `install.ps1` on Windows PowerShell 5.1

Open "Windows PowerShell" (blue icon, not PowerShell 7). Check `$PSVersionTable.PSVersion` shows 5.1.

| Step | Command | Pass when | Result |
|---|---|---|---|
| 1 | `powershell -ExecutionPolicy Bypass -File .\install.ps1` from the package root | exits 0; says it found Python 3.9 or newer; prints the install path | |
| 2 | `dir "$env:USERPROFILE\.copilot\skills\architecture-diagrams"` | contains `SKILL.md`, `README.md`, `scripts\`, `assets\`, `reference\` | |
| 3 | `powershell -ExecutionPolicy Bypass -File .\install.ps1 -Project <workspace>` where `<workspace>` is the folder that holds the cloned repos (for the fixture: its parent copy) | skill copied to `<workspace>\.github\skills\architecture-diagrams` | |
| 4 | Run step 3 again | succeeds without error; the folder is replaced, not nested (no `architecture-diagrams\architecture-diagrams`) | |
| 5 | Temporarily rename `python.exe` off the PATH (or use a machine with no Python) and run step 1 | prints a clear fix message; does not crash with a stack trace | |
| 6 | `assets\tasks.json` in the installed copy | refers to the installed path and the Python command found (`python` or `py -3`) | |
| 7 | Install with a user name or target path containing a space | works | |

### W3. VS Code agent mode, the five spec section 9 requests

Open `<fixture>` (or the workspace from W2 step 3) in VS Code with GitHub Copilot in agent mode.
Check `chat.useAgentSkills` is on, and that typing `/` shows `architecture-diagrams`.
For each request below, record: **skill fired?** (the chat shows the skill being used), **commands run** (exact text), **files written**, **stdout relayed** (does the reply carry the file paths, the two-line summary and the loose and partly known counts?).

| # | Request to type | Expected | Skill fired? | Commands run | Files written | Stdout relayed? |
|---|---|---|---|---|---|---|
| 1 | `Draw the landscape for these repos.` | `scan` then `draw --level landscape`; style B by default; `landscape-*.svg`, `.md`, `-links.md` in `architecture-diagrams\` | | | | |
| 2 | `Show me batch job CLMD100.` | `draw --level flow --scope CLMD100`; style A by default; mentions the second copy under `jcl\test` | | | | |
| 3 | `Draw the claim details transaction as a whiteboard sketch.` | asks, or picks, the flow for `claims/:id` (or CLMI); style D; `.excalidraw` written | | | | |
| 4 | `Link map for claims-batch: what depends on it?` | `draw --level repomap --scope claims-batch`; style C `.html` written | | | | |
| 5 | `Draw everything in all four styles.` | `--style all`; all four SVGs plus `.drawio`, `.md`, `.html`, `.excalidraw` | | | | |

Also check, in the same session:
- The second request reuses the scan from the first (no full rescan), and a rescan happens when asked.
- Copilot does not edit any repo file and does not invent links not in `*-links.md`.
- The terminal approval prompt shows `python ... run.py ...` with the workspace path; paths with spaces are quoted.
- Output is not garbled (UTF-8) in the VS Code terminal for `→` and `·` characters.

### W4. Copilot CLI, the same five requests

Start `copilot` in `<fixture>` (or the workspace folder).

| Step | What to do | Pass when | Result |
|---|---|---|---|
| 1 | With the **personal** install only: `/skills list` | `architecture-diagrams` is listed | |
| 2 | Ask the five requests from W3, record the same five columns in a copy of that table | each works as in VS Code | |
| 3 | Install with `-Project` into a workspace that is **not a git repo** (no `.git` in it or above), start `copilot` there, run `/skills list` | **Record whether the project install is found.** If not, record what is needed (a `.git` folder, or the personal install). If it is not found, the README's `-Project` advice must be changed | |
| 4 | Same, workspace **is** a git repo | listed | |
| 5 | Add the skill after the session starts, then `/skills reload` and `/skills list` | listed after reload | |
| 6 | Ask for a diagram and watch the approval prompt | the command is shown and can be approved once; the answer relays the file paths | |

### W5. Open the outputs in other tools

Use one SVG per style, from the `flow-claims--id` set (it has the circled numbers) and from `landscape`.

| Step | What to open | Pass when | Result |
|---|---|---|---|
| 1 | `landscape-a.svg`, `-b.svg`, `-c.svg`, `-d.svg` in Edge | all four look like the Run-here screenshots: text uses Segoe UI, no boxes with missing text | |
| 2 | The same four in VS Code (open the `.svg` file, then the preview or Simple Browser) | renders | |
| 3 | Word: Insert > Pictures > This Device, pick each SVG | inserts as a vector picture, text readable at page width; note whether the text of `flow-claims--id-*` is too small | |
| 4 | PowerPoint: Insert > Pictures, each SVG | renders; right-click > Convert to Shape still works or at least does not error | |
| 5 | `flow-claims--id-a.svg` in Edge, Word and PowerPoint | circled step numbers ①–⑳ render as circled digits (not boxes or question marks); 21 and above show as `(21)` | |
| 6 | `landscape-a.drawio` in draw.io desktop, or the VS Code draw.io extension | opens without an error; shapes are editable; edges stay attached when a box is moved | |
| 7 | `landscape-b.md` in a GitHub preview or Azure DevOps wiki preview (also try the VS Code Markdown preview if a Mermaid extension is present) | the Mermaid flowchart renders; `<b>` and `<br/>` in labels show as bold and line breaks | |
| 8 | `landscape-d.excalidraw` at excalidraw.com (File > Open) or the VS Code Excalidraw extension | opens; boxes and arrows present; text editable | |
| 9 | `repomap-c.html` in Edge with the network **off** (adapter disabled) | page loads fully; clicking a line or a row in the side list shows the evidence table (Repo, File, Line, Code); search box filters the list; DevTools Network tab shows no failed external requests | |
| 10 | Same file at 1920x1080 | note whether the map pane scrolls or fits (see Known issue 6) | |

### W6. Blocked-commands fallback

| Step | What to do | Pass when | Result |
|---|---|---|---|
| 1 | In VS Code, make terminal commands unavailable to Copilot (deny the run-in-terminal tool, or a policy that blocks it) and ask `Draw the landscape for these repos.` | Copilot says it cannot run commands and gives the command to run, with the real installed path and workspace | |
| 2 | Run that command in a terminal yourself | outputs appear in `architecture-diagrams\` | |
| 3 | Copy `assets\tasks.json` from the installed skill to `<workspace>\.vscode\tasks.json`. Terminal > Run Task > "Architecture diagrams: scan", then summary, list, draw | each task runs and exits 0; the prompts for level, scope and style work | |
| 4 | Paste the output into chat, or ask Copilot to read `architecture-diagrams\summary.md` and `landscape-links.md` | Copilot carries on from the files and does not rescan | |
| 5 | Follow the README "If Copilot can't run commands" section word for word | every step works as written (`python` vs `py -3`) | |

### W7. Long paths (more than 260 characters)

| Step | What to do | Pass when | Result |
|---|---|---|---|
| 1 | In a cloned repo being scanned, create a nested folder so that a COBOL file's full path is over 260 characters, for example `cmd /c mkdir "\\?\C:\work\claims\claims-batch\cobol\<many nested folders>"` and copy `CLMB200.cbl` there | folder created | |
| 2 | Run `scan` on the workspace, with and without Windows long paths enabled (`LongPathsEnabled`) | scan finishes without a traceback; the file is read, or a clear "skipped: path too long" note is shown and the scan continues | |
| 3 | Check `inventory.json` for the program | present, or skipped with a reason; never a silent miss | |
| 4 | Put the workspace itself deep (path about 200 characters) and run `draw` | outputs are written, or a clear error names the path | |

### W8. First-client calibration (spec section 11)

No real client code exists yet, so the fixture is the only test so far. Before anyone relies on the diagrams:

| Step | What to do | Pass when | Result |
|---|---|---|---|
| 1 | Clone the client's repos into one folder and run `scan` and `summary` | completes; counts look plausible to the client | |
| 2 | A client mainframe developer picks about five batch jobs and five online transactions and draws each (`Show me batch job X`) | each draws | |
| 3 | The developer checks each `*-links.md` against the code they know | list every **missing** link (dataset, table, queue, CALL, LINK, XCTL they know exists) and every **wrong** solid link, each with file and line | |
| 4 | Send the list to the delivery contact | each item becomes a new test in `tests\fixtures\claims-estate` with its expected status, before the diagrams are relied on | |
| 5 | Confirm the "partly known" and "loose end" lines the developer sees are fair | no solid line that is wrong; loose ends are real gaps or missing repos | |
| 6 | Check scan time on the client's real repo count (spec target: minutes, not hours, for 50 repos) | record the time | |
