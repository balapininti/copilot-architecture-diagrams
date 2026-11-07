# Acceptance: Windows, offline, Copilot

Task 19 of the architecture-diagrams skill. The build machine is macOS (Python 3.14 in `.venv`, plus the system Python 3.9.6), with
no Windows, PowerShell, Copilot, VS Code agent mode, Office or draw.io. So this file has two
parts. **Run here (results)** holds checks that were actually run, with real output.
**To run on Windows (checklist)** holds everything else, with a blank result column. Nothing in
the second part has been run, and none of it is marked as passed.

Date of the run here: 2026-11-07. Release under acceptance: archdiag **0.1.3** (`archdiag/__init__.py`, `pyproject.toml`; cache schema 4). Commit under test: branch `fix/outstanding`, HEAD `ab5a151` (all fix batches A to E applied; this file is committed on top of it and changes no code). Every check in the table below was run on that commit; earlier results (0.1.0 at `f69d1de`) are replaced. After the review cleanups (`69c3b29`: label placement tie-break, layout notes, test robustness) checks 1, 2a, 2c and 3 were run again on `69c3b29` with the same results (suite: 608 passed; 43 files parsed and 42 modules imported under 3.9.6; 17 CLI commands exit 0, same summary lines, 74 files); checks 4 to 6 were not repeated there.

Two Pythons were used. `.venv/bin/python` is Python 3.14.4 and runs the pytest suite. `/usr/bin/python3` is the macOS system **Python 3.9.6** (the lowest supported version), run with `-I` (isolated: no user site-packages, no environment variables, no current folder on the path); it has no pytest and none could be installed offline (pytest 9 no longer supports 3.9; a pytest 8.3 or older wheel is needed once), so **the full pytest suite was not run on 3.9 here**. That is now Windows step W1.4 (see W1.4a).

## Run here (results)

Working copy: the fixture was copied to
`/private/tmp/claude-501/-Users-balakrishnapininti-workspace-mainframe-modernization-analyst/d6db0ae9-eb9a-402e-a301-bfac84499e51/scratchpad/acc_e/ws` (a copy of `tests/fixtures/claims-estate`); the fixture itself was never written to.

| # | Check | Command | Result |
|---|---|---|---|
| 1 | Full test suite (Python 3.14.4) | `.venv/bin/python -m pytest -q` | **PASS**: 607 passed in 19.97s (608 on `69c3b29`). Includes the headless-Chrome HTML test (E9), which ran (Chrome is installed here) |
| 1b | Full test suite on Python 3.9 | needs pytest on 3.9 | **NOT RUN**: no pytest for the system 3.9.6 offline. Windows W1 runs it |
| 2a | Syntax valid as Python 3.9 | `/usr/bin/python3 -I`: `ast.parse(src, f, feature_version=(3, 9))` over every `.py` under `skill/architecture-diagrams/scripts` | **PASS**: 43 files parsed by Python 3.9.6 itself |
| 2b | No 3.10+ constructs | grep for `f"{x=}"`, `match`/`case`, `removeprefix/removesuffix`, `zip(strict=)`, `dataclass(slots/kw_only)`, `TypeAlias`, `ParamSpec`; check every file has `from __future__ import annotations` | **PASS**: no hits; all 43 files have the future import |
| 2c | Imports work on 3.9 and are stdlib only | `/usr/bin/python3 -I`: import `archdiag` and every submodule (`pkgutil.walk_packages`); compare every top-level import name with `tests/stdlib39.py` (the fixed 3.9 list) | **PASS**: 42 modules imported under 3.9.6; the only non-stdlib name is `archdiag` |
| 3 | CLI end to end on Python 3.9.6, isolated | `/usr/bin/python3 -I skill/architecture-diagrams/scripts/run.py <cmd> --workspace <copy>`, every level with `--style all` (list below) | **PASS**: 17 commands, every exit code 0, nothing on stderr |
| 3b | No network references | regex `https?://` over every output | **PASS** for diagrams (see below) |
| 4 | Every output parses | xml.etree for `.svg`/`.drawio`; json for `.excalidraw`/`.json`; `.md` non-empty; HTML scanned for `src=`/`href=` (non-fragment, non-data), `@import`, `url(http...)` | **PASS**: 74 files checked, 0 failures |
| 5 | Screenshots vs samples | headless Chrome at each SVG's own size, all 28 SVGs of check 3 | **PASS with known issues** (see Visual check) |
| 6 | HTML interaction | headless Chrome `--virtual-time-budget=3000 --dump-dom` on `repomap-c.html` with a probe script | **PASS** |

### 3. Commands and results

All run as `/usr/bin/python3 -I skill/architecture-diagrams/scripts/run.py <cmd> ... --workspace <copy>` (Python 3.9.6); every exit code was 0 and stderr was empty.

- `scan`: `Scanned 6 repo(s), 94 things found, 94 links (68 confirmed, 16 partly known, 10 loose ends)`; wrote `inventory.json` and `links.json`.
- `summary`: printed the repo, application and link counts and the loose and partly known links (47 lines); wrote `summary.md`.
- `list --what jobs|transactions|pages|endpoints|applications|repos|programs`: all seven exit 0, one `NAME<TAB>description (repo/path)` line per item. Examples: `CLMD100	steps run SORT, CLMB200, IKJEFT01 +2 more (claims-batch/jcl/CLMD100.jcl)` (and the `test/` copy), `claims/:id	component ClaimDetailsComponent (claims-portal/src/app/app-routing.module.ts)`, `GET /api/claims/{}	handler class ClaimController (...)`; applications gave 6, programs 10.
- `init-config`: `Wrote .../archdiag.config.json with environment_qualifiers: PROD, TEST`.
- `draw --style all` for each level. Every run wrote nine files (4 SVG, `.drawio`, `.md`, `.azure.md`, `.html`, `.excalidraw`, plus `*-links.md`) and a summary:

| Command | Summary line printed |
|---|---|
| `draw --level landscape` | 20 nodes, 30 links: 18 confirmed, 6 partly known, 6 loose ends |
| `draw --level application --scope claims-online` | 33 nodes, 26 links: 15 confirmed, 6 partly known, 5 loose ends |
| `draw --level flow --scope CLMD100` | 18 nodes, 20 links: 16 confirmed, 2 partly known, 2 loose ends (also printed `Note: Also exists as: claims-batch/jcl/test/CLMD100.jcl`) |
| `draw --level flow --scope claims/:id` | 25 nodes, 27 links: 19 confirmed, 4 partly known, 4 loose ends. File names are `flow-claims--id-*` |
| `draw --level flow --scope CLMI` | 14 nodes, 15 links: 10 confirmed, 3 partly known, 2 loose ends |
| `draw --level repomap` | exit 0, nine files |
| `draw --level repomap --scope claims-batch` | exit 0, nine files |

Total files in the output folder: 74 (including `inventory.json`, `links.json`, `summary.md`, `archdiag.config.json`).

### 3b. Network references

- In the `.svg`, `.html`, `.drawio` and `.excalidraw` outputs the only URL is the SVG namespace `http://www.w3.org/2000/svg` (35 occurrences). No external script, stylesheet, font or image.
- `inventory.json`, `links.json`, `landscape-links.md` and `repomap-links.md` contain `https://rates.example.com/...`, `https://partner.example.com/...` and `https://zcee.internal:9443/...`. These are strings copied from the fixture's source code as evidence, not references the tool loads.
- The HTML pages embed the same evidence text inside a JSON block with escaped slashes (`https:\/\/rates.example.com/...`). It is displayed text only.

### 6. HTML interaction

A copy of `repomap-c.html` had a probe script appended that clicks the first `g[data-edge]`, records the `#panel` text, then types `CLMREC.cpy` in the search box. Run with `--virtual-time-budget=3000 --dump-dom`. The panel showed
`← all links table CLMS.CLMHIST partial claims-api → claims-batch Repo File Line Code claims-api src/main/java/com/acme/claims/ClaimHistoryRepository.java 16 return jdbcTemplate.queryForList("SELECT CLM_ID FROM CLMS.CLMHIST"); claims-batch cobol/CLMB510.cbl 9 EXEC SQL INSERT INTO CLMS.CLMHIST ...`,
the dumped DOM contains the evidence `<table>` (columns Repo, File, Line, Code), and the search left 4 of 70 clickable groups lit (the lines whose evidence names `CLMREC.cpy`). Pass. The same search and click run in the test suite (`tests/test_style_c.py::test_html_search_and_click_run_in_a_browser`).

### 5. Visual check (headless Chrome, macOS)

Screenshots were taken of all 28 SVGs of check 3 at their own size, and of `repomap-c.html` at 1500x1000; landscape, application, both flows, CLMI and the repomap were read in all four styles and compared with `docs/samples/mainframe-samples.html`. Reference PNGs are committed in `docs/acceptance/` (`style-a-flow-clmd100.png`, `style-b-flow-clmd100.png`, `style-c-flow-clmd100-svg.png`, `style-d-flow-clmd100.png`, `style-c-repomap-html.png`, `style-a-flow-claims-id.png`, `style-a-landscape.png`; refreshed after Batch E). Windows checks compare against them.

What matches the samples:
- Style A: same icon set (JCL page, gear utilities, CBL files, DB2/VSAM cylinders, GDG stack, printer, cloud), the same STEP lane, edge labels in pills, red loose-end dots with "no reader/writer found", orange dotted partial lines, legend.
- Style B: blue C4 boxes with `[type]` subtitles, cylinders for datasets, red loose-end boxes.
- Style D: hand-drawn rough boxes, pastel fills per kind, yellow sticky notes for loose ends and notes.
- Style C HTML: repo cards with file rows, dark pill labels on links, side panel "Links between repos" with search box and a list tagged confirmed/partial/loose/shared code; the click test shows the evidence table.
- Step numbers: `flow-claims--id-*.svg` draws every step number (1 to 27) as a small circle with the number in it.
- Line labels: a label sits on its own line; where no spot on the line is clear, the line carries a small numbered marker (circle for a step, square otherwise) and the label is listed under "Line labels (marked on the lines)". After Batch E the `claims/:id` flow keys 2 labels over the four styles (style C only; it keyed 18), CLMD100 and CLMI key none, the landscape keys 1 to 3 per style and the whole-estate repo map 9 to 14 per style.

### Known issues

These are readability gaps, not failures of any check.

1. **Busy landscape.** The landscape (all styles) still has long parallel runs between the middle columns; every label sits on its own line or is keyed, but following one line end to end takes effort. The sample's landscape has far fewer links.
2. **Repo map keys many labels.** The whole-estate repo map has 27+ links between few cards; 9 to 14 per style go to the key. Loose stubs now go straight to their missing box, or round the cards at right angles where a straight line would cross a card (E7).
3. **Wide pictures.** Wide layered views wrap into bands (Batch C): `flow-claims--id-*.svg` is now 1796 to 1978 px wide (it was 3300 to 3774), the landscape 1941 to 2014 px. At Word page width the text is small; use A3 landscape or the HTML for those.
4. **Style C HTML at 1500 px.** The whole-estate map (1920 px wide) is wider than the map pane at 1500 px, so the right-hand cards are cut off until the pane is scrolled. Not checked: behaviour in a real browser at 1920 px (W5.11).
5. Fixed since the last run and checked here: the CLMD100 "write" / "read (0)" pills at a line crossing (E6), lines crossing in the channel between bands (E2), loose-stub curves looping round their own card (E7), close line ends on short application-view boxes (E8).

## To run on Windows (checklist)

**None of these steps has been run.** The Result column is blank on purpose. Run each on a Windows machine
(or Windows CI runner) with the delivered package, and write PASS, FAIL or the observation in it.
Use `tests\fixtures\claims-estate` as the workspace unless a step says otherwise; `<fixture>` means the full
path of a copy of that folder. Turn the network back on after any step that turns it off.

### Status summary (fill in as you go)

| Step | What | Status (PASS / FAIL / not run) |
|---|---|---|
| W1 | Python 3.9 test suite, network off | not run |
| W2 | `install.ps1` on PowerShell 5.1 | not run |
| W3 | VS Code agent mode, five requests | not run |
| W4 | Copilot CLI, five requests, project-install discovery | not run |
| W5 | Outputs in Edge, VS Code, Word, PowerPoint, draw.io, Mermaid, Excalidraw, HTML offline | not run |
| W6 | Blocked-commands fallback | not run |
| W7 | Long paths over 260 characters | not run |
| W8 | First-client calibration | not run |

### W1. Python 3.9 test suite, network off

Python 3.9 is the lowest supported version, so this is the version to test. **Recording failures:** for every failing
test write its name (`tests\test_x.py::test_y`) and the first 5 lines of its traceback in the Result column or in an attached
`w1-failures.txt` (`pytest -q 2>&1 | Tee-Object w1-failures.txt`).

| Step | Command | Pass when | Result |
|---|---|---|---|
| 1 | `py -3.9 --version` | prints `Python 3.9.x` | |
| 2 | `py -3.9 -m venv .venv39` then `.venv39\Scripts\python -m pip install "pytest<8.4"` (the only install; the only step that needs a network or an internal index) | pytest installs | |
| 3 | Turn the network off (Wi-Fi off, Ethernet disabled). Confirm: `Test-NetConnection github.com -Port 443` | `TcpTestSucceeded : False` | |
| 4 | `.venv39\Scripts\python -m pytest -q -rs` from the repo root | `608 passed`, or `607 passed, 1 skipped` where the one skip is `tests/test_style_c.py::test_html_search_and_click_run_in_a_browser` (it runs only when Chrome is found: on Windows Chrome is not on PATH, so set `$env:ARCHDIAG_CHROME` to the full path of `chrome.exe` to run it; it also skips if Chrome returns no page). Record whether that test ran. No other skips; no errors that mention the network | |
| 4a | Note, nothing to type: step 4 is the first full pytest run on Python 3.9 anywhere (the macOS check ran only 3.9.6 syntax, imports and the CLI). Record the pytest version step 2 installed (`.venv39\Scripts\python -m pytest --version`) | a pytest 8.x version is shown and step 4 passed | |
| 5 | Copy the repo to `C:\work dir\repo` (path with a space) and run `.venv39\Scripts\python -m pytest -q -p no:cacheprovider` there | same count passes | |
| 6 | Turn the network back on; `Test-NetConnection github.com -Port 443` | `TcpTestSucceeded : True` | |

### W2. `install.ps1` on Windows PowerShell 5.1

Open "Windows PowerShell" (blue icon, not PowerShell 7). Check `$PSVersionTable.PSVersion` shows 5.1. Run steps 1 to 4 with the network **off** (the installer needs none).
Exact messages the installer prints (from `install.ps1`):

- Success: `Installed the personal skill at <target>` or, with `-Project`, `Installed the project skill for the workspace <root> at <target>` (green), then `Python OK: <cmd> (<version>)` (green), then `Next:` with three numbered lines. Exit code 0.
- Existing copy: `Replacing the existing copy at <path>`.
- No Python: `Python 3.9 or newer was not found (tried: py -3, python, python3).` then `To fix it:` with four numbered lines, ending `The skill is installed and will work once Python is available.` Exit code **2** (the skill is still installed).
- Errors (red, exit 1): `Cannot find the skill at <path>. Run install.ps1 from the folder that holds 'skill\architecture-diagrams'.`, `The folder <path> does not exist.`, `USERPROFILE is not set; cannot find your home folder.`

| Step | Command | Pass when | Result |
|---|---|---|---|
| 1 | `powershell -ExecutionPolicy Bypass -File .\install.ps1` from the package root; then `$LASTEXITCODE` | success and `Python OK:` lines above; `$LASTEXITCODE` is 0 | |
| 2 | `dir "$env:USERPROFILE\.copilot\skills\architecture-diagrams"` | contains `SKILL.md`, `README.md`, `scripts\`, `assets\`, `reference\` | |
| 3 | `powershell -ExecutionPolicy Bypass -File .\install.ps1 -Project C:\work\claims-estate` (the folder that holds the cloned repos; create it first with a copy of the fixture) | `Installed the project skill for the workspace C:\work\claims-estate at C:\work\claims-estate\.github\skills\architecture-diagrams`; exit 0 | |
| 4 | Run step 3 again | prints `Replacing the existing copy at ...`; no `architecture-diagrams\architecture-diagrams` nesting | |
| 5 | Path with a space: `mkdir "C:\work dir\ws"` then `... .\install.ps1 -Project "C:\work dir\ws"` | installs under `C:\work dir\ws\.github\skills\architecture-diagrams`; exit 0 | |
| 6 | Missing folder: `... .\install.ps1 -Project C:\does\not\exist` | prints `The folder C:\does\not\exist does not exist.`; exit 1 | |
| 7 | No-Python test, safe (changes nothing permanently): open a **new** PowerShell and run `$env:PATH = (($env:PATH -split ';') \| Where-Object { $_ -notmatch 'Python\|WindowsApps' }) -join ';'`, then `.\install.ps1` in that window. Note: the `py` launcher lives in `C:\Windows`, so it may still be found; if `py -3` still works, also run `Get-Command py` and record it, and rename nothing | if Python is found only via `py`, record it as "py launcher found". If nothing is found: the fix message above is printed, exit code 2, no stack trace | |
| 8 | `type "$env:USERPROFILE\.copilot\skills\architecture-diagrams\assets\tasks.json"` | commands refer to the installed path and the Python command found (`python` or `py -3`) | |
| 9 | Close that PowerShell window; network back on | | |

Note on W2 step 7: the `\|` in that command is a Markdown table escape. In PowerShell type a plain `|`.

### W3. VS Code agent mode, the five spec section 9 requests

**Check that agent skills are on.** Names can vary by VS Code version, so record what you see.
1. File > Preferences > Settings, search `chat.useAgentSkills` (or "agent skills"). The box should be ticked.
2. Or open the settings JSON (Ctrl+Shift+P > "Preferences: Open User Settings (JSON)") and look for `"chat.useAgentSkills": true`. If the line is missing, the default applies (on in current versions); if it shows as managed or greyed out, your organisation controls it.
3. Open Copilot chat, switch to Agent mode, type `/` and look for `architecture-diagrams`. Record the VS Code version (Help > About) and whether the entry appears.

Open `<fixture>` (or the workspace from W2 step 3) in VS Code. For each request record: **skill fired?** (the chat shows the skill being used), **commands run** (exact text), **files written**, **stdout relayed** (reply carries the file paths, the two-line summary, the loose and partly-known counts, and every `WARNING:` and `Note:` line). **Overall Result rule: PASS only if the right command was run AND the expected files were written AND the stdout was relayed including any WARNING lines; otherwise FAIL with the reason.**

| # | Request to type | Expected | Skill fired? | Commands run | Files written | Stdout relayed? | Overall Result |
|---|---|---|---|---|---|---|---|
| 1 | `Draw the landscape for these repos.` | `scan` then `draw --level landscape`; style B by default; `landscape-*.svg`, `.md`, `-links.md` in `architecture-diagrams\` | | | | | |
| 2 | `Show me batch job CLMD100.` | `draw --level flow --scope CLMD100`; style A by default; relays the `Note: Also exists as: claims-batch/jcl/test/CLMD100.jcl` line | | | | | |
| 3 | `Draw the claim details transaction as a whiteboard sketch.` | asks, or picks, the flow for `claims/:id` (or CLMI); style D; `.excalidraw` written | | | | | |
| 4 | `Link map for claims-batch: what depends on it?` | `draw --level repomap --scope claims-batch`; style C `.html` written | | | | | |
| 5 | `Draw everything in all four styles.` | `--style all`; four SVGs plus `.drawio`, `.md`, `.html`, `.excalidraw` | | | | | |

Also check: the second request reuses the scan (no full rescan) and a rescan happens when asked; Copilot edits no repo file and invents no links beyond `*-links.md`; the approval prompt shows `python ... run.py ...` with quoted paths; `→` and `·` are not garbled in the terminal.

### W4. Copilot CLI, the same five requests

Start `copilot` in `<fixture>` (or the workspace folder).

| Step | What to do | Pass when | Result |
|---|---|---|---|
| 1 | With the **personal** install only: `/skills list`. Paste the output as text into the Result column | `architecture-diagrams` is listed | |
| 2 | Ask the five requests from W3 and fill a copy of the W3 table | each passes by the W3 rule | |
| 3 | Non-git workspace: `mkdir C:\temp\nogit`, copy the fixture repos in, check no `.git` exists in `C:\temp\nogit` or any parent (`git -C C:\temp\nogit rev-parse --show-toplevel` must fail). Remove the personal install first (rename `$env:USERPROFILE\.copilot\skills\architecture-diagrams`), run `install.ps1 -Project C:\temp\nogit`, start `copilot` in `C:\temp\nogit`, run `/skills list`, paste the text | **Record whether the project install is found.** If not, record what is needed (a `.git` folder, or the personal install). If not found, the README's `-Project` advice must change | |
| 4 | Same with `git init` run in `C:\temp\nogit` | listed | |
| 5 | Add the skill while a session is open, then `/skills reload` and `/skills list` | listed after reload | |
| 6 | Ask for a diagram and watch the approval prompt | command shown and approvable once; the answer relays the paths | |
| 7 | Restore the renamed personal install | | |

### W5. Open the outputs in other tools

Reference images are in `docs/acceptance/` (committed): `style-a-flow-clmd100.png`, `style-b-flow-clmd100.png`, `style-c-flow-clmd100-svg.png`, `style-d-flow-clmd100.png`, `style-c-repomap-html.png`, `style-a-flow-claims-id.png`, `style-a-landscape.png`. Use the same scopes to compare (`CLMD100` flow, `claims/:id` flow, landscape).
**Objective pass criteria for every picture:** (a) every label visible, none clipped at a box edge; (b) line colours match the legend (dark grey confirmed, dotted orange partly known, red ending in a dot loose end, dashed brown shared code); (c) text uses a sans-serif font, no empty boxes in place of characters; (d) looks like the reference PNG apart from font rendering. **Word at 100% zoom:** for the CLMD100 flow and the landscape, inserted at page width, body text is legible without zooming; record whether the `claims/:id` flow is (Known issue 3).

| Step | What to open | Pass when | Result |
|---|---|---|---|
| 1 | `flow-clmd100-a.svg`, `-b.svg`, `-c.svg`, `-d.svg` in Edge | criteria (a) to (d) | |
| 2 | The same four in VS Code (open the `.svg`, then the preview) | criteria (a) to (d) | |
| 3 | Word: Insert > Pictures > This Device, each of the four | inserted as a vector picture; criteria (a) to (d) at 100% | |
| 4 | PowerPoint: Insert > Pictures > This Device, each of the four. Optionally Graphics Format > Convert to Shape | picture renders. Record what Convert to Shape does (works / errors / loses text); it is optional, not a failure | |
| 5 | `flow-claims--id-a.svg` in Edge, Word and PowerPoint | every step number (1 to 27) shows as a small circle with the number centred in it; every label sits on its own line (style A keys none; `flow-claims--id-c.svg` lists RETURN TRANSID and SELECT under "Line labels") | |
| 6 | `landscape-a.drawio` in draw.io desktop or the VS Code draw.io extension | opens without error; shapes editable; edges stay attached when a box is moved | |
| 7 | `landscape-b.md` in a GitHub preview. Open the file first: it starts with `# Landscape` then a fence of three backticks plus `mermaid`. GitHub renders that fence | flowchart renders; `<b>` and `<br/>` show as bold and line breaks | |
| 8 | Same content in an Azure DevOps wiki. **Azure DevOps wikis need `::: mermaid` ... `:::` instead of the backtick fence.** Paste as is first | **Record whether it renders.** If not, record that the fence must be changed for Azure DevOps (a product change; do not edit it by hand in the deliverable) | |
| 9 | `landscape-d.excalidraw` at excalidraw.com (File > Open) or the VS Code Excalidraw extension | opens; boxes and arrows present; text editable | |
| 10 | `repomap-c.html` in Edge with the network **off** | loads fully; clicking a line or a list row shows the evidence table (Repo, File, Line, Code); search filters the list; DevTools Network shows no external requests | |
| 11 | Same file at 1920x1080 | note whether the map pane scrolls or fits (Known issue 4) | |

### W6. Blocked-commands fallback

| Step | What to do | Pass when | Result |
|---|---|---|---|
| 1 | Block terminal commands. In VS Code agent mode, when Copilot asks to run the command, click **Skip** or deny the approval prompt each time (this is the reliable way). If your organisation has a setting for it, use that; the setting name varies by version (look in Settings for `chat.tools` and "terminal"). Record which route you used and the VS Code version | commands do not run | |
| 2 | Ask `Draw the landscape for these repos.` | Copilot says it cannot run it and gives the command with the real installed path and workspace | |
| 3 | Run that command in a terminal yourself | outputs appear in `architecture-diagrams\` | |
| 4 | Copy `assets\tasks.json` from the installed skill to `<workspace>\.vscode\tasks.json`. Terminal > Run Task > "Architecture diagrams: scan", then summary, list, draw | each task runs and exits 0; the prompts for level, scope and style work | |
| 5 | Paste the output into chat, or ask Copilot to read `architecture-diagrams\summary.md` and `landscape-links.md` | Copilot carries on from the files and does not rescan | |
| 6 | Follow the README section "If Copilot can't run commands" word for word | every step works as written (`python` vs `py -3`) | |

### W7. Long paths (more than 260 characters)

Run in Windows PowerShell inside the copied workspace (`C:\work\claims-estate`). This creates a nested folder about 300 characters long and puts a COBOL file in it:

```powershell
$d = "\\?\C:\work\claims-estate\claims-batch\cobol"; 1..12 | ForEach-Object { $d += "\" + ("longfolder_" + $_ + "_" + ("x" * 12)) }; New-Item -ItemType Directory -Path $d -Force | Out-Null; Copy-Item "\\?\C:\work\claims-estate\claims-batch\cobol\CLMB200.cbl" "$d\LONGPATH1.cbl"; "$d\LONGPATH1.cbl".Length
```

The last number printed is 373 (the string includes the 4-character `\\?\` prefix; the real path is 369 characters), so it is over 260. Then:

| Step | What to do | Pass when | Result |
|---|---|---|---|
| 1 | `python "$env:USERPROFILE\.copilot\skills\architecture-diagrams\scripts\run.py" scan --workspace C:\work\claims-estate` with long paths **not** enabled (default on most machines) | finishes without a traceback. Record which happened: **(A) file read, or (B) clear "skipped / path too long" message naming the file, then the scan continues.** A silent skip with no message = **FAIL** | |
| 2 | `python ... list --what programs --workspace C:\work\claims-estate` and look for `LONGPATH1` | listed (A), or reported as skipped in step 1 (B) | |
| 3 | Repeat step 1 after enabling long paths (`LongPathsEnabled` = 1 under `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem`, then sign out and in) | file read | |
| 4 | Deep workspace: put the whole workspace at a path about 200 characters long and run `draw --level landscape` | outputs are written, or a clear error names the path | |
| 5 | Clean up: `Remove-Item -Recurse "\\?\C:\work\claims-estate\claims-batch\cobol\longfolder_1_xxxxxxxxxxxx"` | removed | |

### W8. First-client calibration (spec section 11)

No real client code exists yet, so the fixture is the only test so far. Before anyone relies on the diagrams:

| Step | What to do | Pass when | Result |
|---|---|---|---|
| 1 | Clone the client's repos into one folder and run `scan` and `summary` | completes; counts look plausible to the client | |
| 2 | A client mainframe developer picks about five batch jobs and five online transactions and draws each (`Show me batch job X`) | each draws | |
| 3 | The developer checks each `*-links.md` against the code they know | list every **missing** link (dataset, table, queue, CALL, LINK, XCTL they know exists) and every **wrong** solid link, each with file and line | |
| 4 | Send the list to the delivery contact | each item becomes a new test in `tests\fixtures\claims-estate` with its expected status, before the diagrams are relied on | |
| 5 | Check the "partly known" and "loose end" lines are fair | no solid line that is wrong; loose ends are real gaps or missing repos | |
| 6 | Time the scan on the client's real repo count (spec target: minutes, not hours, for 50 repos) | record the time | |
