# Gitdiagram View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a new `gitdiagram` zoom level that draws one locally cloned repo as named groups of related files. Arrows come from code evidence (solid) or from Copilot's suggestions (dotted). Boxes are clickable to the local files, and the result is in all four styles plus Mermaid.

**Architecture:**
- The scan records every classified file.
- A new `gitdiagram.py` loads the editable `architecture-diagrams/gitdiagram-<repo>.json`, falling back to a per-folder grouping when there is none.
- `summary.gitdiagram_context` gives Copilot what it needs to propose groups.
- A new view (`views/gitdiagram.py`) maps resolver edges onto groups using the settled rules in spec §10.
- Layout reuses the context layout: entry actors on the left, groups in the centre, outside stubs on the right.
- Renderers gain per-box links and an overview block.

**Tech Stack:** Python 3.9+ standard library only at run time; pytest for development.

**Spec:** `docs/superpowers/specs/2026-11-07-gitdiagram-view-design.md`, which builds on `docs/superpowers/specs/2026-11-06-architecture-diagram-skill-design.md`.

## Global Constraints

- Run-time code uses the Python 3.9 standard library only (`tests/stdlib39.py`). Every module has `from __future__ import annotations`. No `match`, no walrus operator, no `X | Y` at runtime.
- "a solid arrow without code evidence" is an anti-goal. A line is never more certain than the least certain target its label names (`views/common.py` `_least_certain` / landscape C3 rule).
- "A file that quietly disappears from the picture" is an anti-goal. Every classified file is in a group, in "Not yet grouped", or listed as not scanned.
- Same groups every time: the CLI never writes `gitdiagram-<repo>.json`; only Copilot or the user does.
- Repos are cloned locally. Box links are relative, from `architecture-diagrams/` to `../<repo path>/<file or folder>`.
- Line types are unchanged: confirmed #334155 solid, partial #d97706 dotted, loose #dc2626 with a dot, shared #a16207 dashed. The new structural Scheduler line is thin plain grey `#94a3b8`, labelled "starts". Its legend text is "starts — the job exists; who schedules it isn't in these repos".
- `MAX_NODES = 40`, the existing cap (`views/cap.py`).
- SVG stays Office-safe: no filter/style/use/marker/foreignObject/image. `<a href>` is allowed.
- CLI: `draw --level gitdiagram --scope <repo>`; default style `b`; new command `gitdiagram-context --repo <repo>`.
- Version `0.1.4` and `SCHEMA_VERSION = 5`, because the inventory gains a field.
- Tests: `.venv/bin/python -m pytest -q` (608 passing at start). The release gate `tests/test_gate.py` stays green.

## Review Focus

1. **A gitdiagram file whose paths are all stale** (repo reorganised). Every file lands in "Not yet grouped", the problems list names each unmatched pattern, and stdout says so. The draw never shows an unexplained empty picture. Test: Task 4.
2. **Patterns written with Windows backslashes, a leading `./`, or a different case on Windows-exported repos.** They still match. Test: Task 2.
3. **Group names or overview text containing `&`, quotes, `[ ]`, `|` or `<`.** They are escaped in SVG, draw.io, Mermaid, Excalidraw and HTML, and every output still parses. Test: Task 6.
4. **A repo folder name with spaces or `#`.** Box links are percent-encoded relative URLs that open the file. Test: Task 5.
5. **A repo with ~3,000 classified files.** `gitdiagram-context` output stays under ~1,500 lines (it summarises per folder) and the drawing stays at ≤40 boxes. Test: Tasks 3 and 4.

---

## File Structure

```
skill/architecture-diagrams/scripts/archdiag/
  model.py                 Inventory.files (Task 1)
  scan/__init__.py         record classified files (Task 1)
  store.py, __init__.py    schema 5 / version 0.1.4 (Task 1)
  gitdiagram.py            NEW: GitGroup, GitDiagram, load/default/group_of/file_of (Task 2)
  summary.py               gitdiagram_context (Task 3)
  views/gitdiagram.py      NEW: build the gitdiagram ViewGraph (Task 4)
  views/__init__.py, views/common.py   level registration, VNode.link, ViewGraph.overview (Tasks 4–5)
  layout.py                gitdiagram → context layout (Task 5)
  render/common.py, style_a..d.py      links, overview block, "starts" legend (Tasks 5–6)
  render/report.py         gitdiagram report sections (Task 7)
  cli.py                   draw level + gitdiagram-context command (Task 8)
skill/architecture-diagrams/SKILL.md, reference/*.md, README.md   (Task 10)
tests/fixtures/claims-estate/architecture-diagrams/gitdiagram-claims-batch.json, gitdiagram-claims-api.json (Task 9)
tests/fixtures/expected_gitdiagram.json + notes (Task 9)
tests/test_gitdiagram_*.py
```

---

### Task 1: Record every classified file in the inventory

**Files:**
- Modify: `archdiag/model.py` (Inventory), `archdiag/scan/__init__.py` (`scan_workspace`), `archdiag/store.py` (`SCHEMA_VERSION = 5`), `archdiag/__init__.py` (`__version__ = "0.1.4"`), `pyproject.toml`, and the version tests.
- Test: `tests/test_inventory_files.py`

**Interfaces:**
- Produces: `Inventory.files: List[Dict[str, str]]`, defaulting to an empty list. Each entry has keys `repo`, `path` (repo-relative, forward slashes) and `kind` (the classify result: cobol, copybook, jcl, proc, csd, bms, ddl, mqsc, java, properties, yaml, angular_ts, zosconnect, asm, pli, easytrieve, rexx).
- Include: config files the scanner reads, and unanalysed-language files.
- Exclude: archive members (the `.aar` / `.sar` file itself is included) and files read only as SYSIN members (`ctx.used_files`).
- The list is sorted by (repo, path). It round-trips through `store`.

- [ ] **Step 1: Write the failing tests.**
  - `test_files_lists_every_classified_file`: on the fixture, `claims-batch/jcl/CLMD100.jcl` is present with kind `jcl` and `shared-copybooks/CLMREC.cpy` with kind `copybook`; `claims-api/src/main/resources/application.yml` is present; no path contains `!/`.
  - `test_files_round_trip`: save, load, compare equal.
  - `test_schema_5_rescans_schema_4_cache`.
  - `test_version_is_0_1_4`.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_inventory_files.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. Append to the list where `scan_workspace` classifies each file (around line 553), skipping archive members and `ctx.used_files`.
- [ ] **Step 4:** Run the tests again, then the full suite. Expected: all PASS.
- [ ] **Step 5:** Commit with message `feat: inventory lists every classified file (schema 5, 0.1.4)`.

---

### Task 2: The gitdiagram file

**Files:**
- Create: `archdiag/gitdiagram.py`
- Test: `tests/test_gitdiagram_file.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass class GitGroup: name: str; tech: str = ""; files: List[str] = []; description: str = ""
  @dataclass class GitDiagram: repo: str; overview: str; groups: List[GitGroup]
                               suggested_links: List[Dict[str, str]]   # {"from","to","label","note"}
                               problems: List[str]; from_file: bool    # False = folder fallback
  def gitdiagram_path(out_dir: Path, repo: str) -> Path                  # out_dir / f"gitdiagram-{repo}.json"
  def load_gitdiagram(out_dir: Path, r: Resolved, repo: str) -> GitDiagram
  def default_gitdiagram(r: Resolved, repo: str) -> GitDiagram          # one group per top-level folder
  def repo_files(r: Resolved, repo: str) -> List[Dict[str, str]]        # Inventory.files for that repo
  def group_of(gd: GitDiagram, path: str) -> Optional[str]              # first group whose pattern matches
  def file_of(node: Node, r: Resolved) -> Optional[Tuple[str, str]]     # (repo, path) of the defining file
  ```
- **Loading:**
  - Read the JSON as UTF-8 (BOM tolerated). Any problem goes to `problems` and never raises.
  - Patterns are normalised: `\` becomes `/`, a leading `./` is stripped, and matching is case-insensitive via `fnmatch` on the lowercased path. A pattern without a glob matches the file exactly, or every file under it when it names a folder.
  - A missing file returns `default_gitdiagram(...)` with `from_file=False`.
  - `default_gitdiagram` makes one group per top-level folder (files at the repo root go to a group named after the repo). `tech` is set from the most common kind. The overview is empty, and a note says "Grouped by folder. Ask Copilot to name groups for this repo."
- **`file_of`:** a definition node maps to `evidence[0]`; a `step:` maps to its job's file; resolver-made nodes (dataset, missing, external, utility) map to None.

- [ ] **Step 1: Write the failing tests.**
  - `test_load_valid_file` (a tmp file with 2 groups).
  - `test_patterns_normalised`: `"cobol\\CLMB2*.CBL"` and `"./cobol/"` both match `cobol/CLMB200.cbl`.
  - `test_first_group_wins`.
  - `test_bad_json_and_wrong_types_are_problems_not_errors`: null files, a numeric name, a duplicate name, an unknown suggested-link end.
  - `test_missing_file_falls_back_to_folders`: the claims-batch groups are cobol, cobol.pds, jcl, jcl.pds, proc, asm, …, and `from_file` is False.
  - `test_file_of_step_is_job_file`.
  - `test_file_of_dataset_is_none`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests again. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: load the editable gitdiagram grouping file`.

---

### Task 3: `gitdiagram_context` for Copilot

**Files:**
- Modify: `archdiag/summary.py`
- Test: `tests/test_gitdiagram_context.py`

**Interfaces:**
- Consumes: `repo_files`, `file_of` (Task 2).
- Produces: `gitdiagram_context(r: Resolved, repo: str, max_lines: int = 1500) -> str`. The output is Markdown with these sections in order:
  1. `# Repo <name>`
  2. `## Files`: a tab-separated table of path, kind and main names. Main names are the node names defined in the file, at most 3, e.g. `program:CLMB200`, `job CLMD100`, `class ClaimController`.
  3. `## README`: the first 200 lines of `README*` at the repo root, if present.
  4. `## Code links between files`: one line per resolver edge whose two ends map to files in this repo, as `from_path → to_path  op  status`, deduplicated. Then a count of links leaving the repo, per outside repo or kind.
  5. `## Entry points`: jobs, transactions, endpoints, pages and z/OS Connect APIs.
- When the Files table would push the total past `max_lines`, it is replaced by one line per folder (`folder/  N files  kinds`), followed by the line "Too many files to list: summarised per folder."

- [ ] **Step 1: Write the failing tests.**
  - `test_context_lists_files_and_names` (claims-batch has `cobol/CLMB200.cbl\tcobol\tprogram:CLMB200`).
  - `test_context_links_between_files`: `jcl/CLMD100.jcl → cobol/CLMB200.cbl  runs  confirmed` is present.
  - `test_context_entry_points`: CLMD100 is listed.
  - `test_context_summarises_huge_repo`: a synthetic Resolved with 3,000 files gives ≤1,500 lines and contains "summarised per folder".
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests again. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: gitdiagram context for Copilot`.

---

### Task 4: The gitdiagram view

**Files:**
- Create: `archdiag/views/gitdiagram.py`
- Modify: `archdiag/views/common.py` and `archdiag/views/__init__.py`
- Test: `tests/test_gitdiagram_view.py`

**Interfaces:**
- Consumes: `GitDiagram`, `group_of`, `file_of`, `repo_files` (Task 2); `_Ctx`, `_combine`, `_least_certain`, `combine_status`, `cap` (existing).
- Produces:
  - `views/common.py`:
    - `LEVELS` gains `"gitdiagram"`.
    - `VNode.link: str = ""`, a repo-relative target path set by the view; renderers turn it into an href.
    - `ViewGraph.overview: str = ""`.
    - VNode kinds: `"group"`, `"actor"` and `"outside"`.
    - VEdge kind `"sequence"` is reused for Scheduler lines, with `label="starts"`.
  - `views/__init__.py`: `build_view(r, g, level, scope, gitdiagram: Optional[GitDiagram] = None)`. For level `gitdiagram`, scope is a repo name, checked with `_scope_error` against the repos.
  - `views/gitdiagram.py`: `gitdiagram_view(ctx: _Ctx, gd: GitDiagram, repo: str) -> ViewGraph`.
- **Rules** (spec §4.2 and §10):
  - **Group boxes.** One VNode `grp:<name>` per group that has at least one file. `label` is the name and `sublabel` is `[tech]`. `detail_lines` holds up to 4 file names (basename, plus the parent folder when basenames collide), then `… N more files`, then the description. `link` is the folder when all files share one, else the first file.
  - **"Not yet grouped".** Classified files that no group claims go in VNode `grp:?` labelled "Not yet grouped", listing up to 4 files and `… N more`. The view notes say `N files not yet grouped`.
  - **Edges.** For every resolver edge with both ends in this repo, map each end to its group via `file_of` and `group_of`:
    - Group to a different group: keep it.
    - Same group: count it for a detail line, "N links inside" (and "N partly known links inside" when any is partial).
    - Combine per (src group, dst group, family) with a label of the family plus up to 2 names. Status is `_least_certain` over the targets the label names, as the landscape does.
  - **Dataset attribution (§10.1).**
    - When an edge starts at a `step:` that has a confirmed `runs` edge to a program in this repo, and the program's `attrs["files"]` has the edge's ddname, the arrow starts at the program's group. Its status is the less certain of the dataset edge and the `runs` edge.
    - Otherwise it starts at the job's group. Utilities stay with the job.
  - **Defined resources (§10.2).** A table, copybook, queue, transaction or map whose defining file is in a group belongs to that group: arrows go into it.
  - **Shared boxes.** A resource with no defining file in this repo, touched by ≥2 groups, becomes a shared VNode as on the landscape. If only one group touches it, it is a detail line on that group.
  - **Outside stubs.** Edges leaving the repo collapse to one VNode `out:<repo or kind>` per outside repo, or per missing/external kind. The label is e.g. `claims-db (3 tables)` or `2 loose ends`. Status is the least certain of the underlying edges, so loose and partial stay visible.
  - **Entry actors (§10.3).** One VNode `act:<kind>` per entry kind present, labelled `Scheduler`, `CICS transactions (N)`, `REST endpoints (N)`, `Angular pages (N)` or `z/OS Connect APIs (N)`, with up to 6 names in `detail_lines`.
    - CICS, REST, page and API actors connect to the groups holding their handler or program, via the existing `runs` / `uses` edges and the normal status.
    - The Scheduler connects to the group of each job that no step in the repo submits, using a `sequence`-kind VEdge labelled "starts". It is never confirmed, partial or loose; its status is `"structural"`.
  - **Suggested links.** These come from `gd.suggested_links`. Ends must name a group or actor; others are reported in the notes. Each gets a VEdge with status partial and reason "suggested by Copilot: <note>", labelled with the link's label.
  - **Notes and overview.** `view.overview = gd.overview`. `gd.problems` and the folder-fallback note go into `view.notes`.
  - **Cap.** The existing `cap` runs at `MAX_NODES`.

- [ ] **Step 1: Write the failing tests** (fixture plus synthetic).
  - `test_groups_become_boxes_with_links`
  - `test_every_classified_file_is_accounted_for`: for claims-batch with a hand-written gitdiagram, the union of group files, "Not yet grouped" files and not-scanned files equals `repo_files`.
  - `test_dataset_arrow_starts_at_program_group`: CLMD100 STEP020 writes CLAIMS.DAILY, so the arrow starts at the group holding CLMB200.
  - `test_utility_dataset_arrow_stays_with_job_group`
  - `test_defined_table_arrow_goes_into_ddl_group`: synthetic repo with a DDL group.
  - `test_undefined_shared_resource_box_only_when_two_groups`
  - `test_outside_stubs_collapse_per_repo`
  - `test_scheduler_lines_are_structural_and_only_for_unsubmitted_jobs`
  - `test_entry_actor_folding`: 50 synthetic transactions give one actor, 6 names and "(50)".
  - `test_suggested_links_are_dotted`
  - `test_no_line_more_certain_than_its_named_targets`, reusing `tests/test_view_invariants.py`'s check.
  - `test_all_stale_patterns_leave_everything_not_yet_grouped_with_problems` (Review Focus 1).
  - `test_huge_repo_capped_at_40` (Review Focus 5).
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests again, then the full suite (existing view invariants must stay green). Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: gitdiagram view of one repo`.

---

### Task 5: Layout, links and overview in the four SVG styles

**Files:**
- Modify: `archdiag/layout.py`, `archdiag/render/common.py`, `render/style_a.py`, `style_b.py`, `style_c.py` and `style_d.py`
- Test: `tests/test_gitdiagram_render.py`

**Interfaces:**
- Consumes: `VNode.link`, `ViewGraph.overview`, and kinds `group` / `actor` / `outside` (Task 4).
- Produces:
  - **Layout.** `layout_for` sends level `gitdiagram` to the context layout, with the roles swapped: `act:*` nodes are the left column, `out:*` nodes the right column, and groups plus shared boxes the centre (layered, at most 5 columns).
  - **Links.** `common.href(view_repo_path: str, link: str) -> str` returns a percent-encoded relative URL `../<repo path>/<link>`.
  - **SVG.** Each box with a link is wrapped in `<a href="…">`. `common.overview_block(text, width) -> (svg_fragment, height)` draws the overview, wrapped, above the picture, and the canvas grows to fit.
  - **Icons.** `group` boxes use their tech's icon (COBOL, JCL, Java, Angular, DDL, …), `actor` boxes a person or clock icon, and `outside` boxes the grey neighbour look.
  - **Legend.** It gains the "starts" entry when a structural line is present.
- Styles B and D keep their own look, but every style draws links, the overview and the legend entry.

- [ ] **Step 1: Write the failing tests.**
  - `test_boxes_are_links_in_every_style`: each group VNode's href appears in the SVG for A–D, and `assert_office_safe` passes.
  - `test_overview_drawn_in_every_style`
  - `test_structural_line_style_and_legend`: grey `#94a3b8`, not a certainty colour; the legend text is the exact Global Constraints string.
  - `test_href_encodes_spaces_and_hash` (Review Focus 4): repo path `client repos/claims#1` gives `../client%20repos/claims%231/…`.
  - `test_gitdiagram_layout_columns`: actors are left of the groups, and outside stubs right of them.
  - `test_deterministic`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests again, then the full suite (the existing line-encoding and pill tests must stay green). Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: draw the gitdiagram view with clickable boxes`.

---

### Task 6: Links and overview in the editable exports

**Files:**
- Modify: `render/style_a.py` (drawio), `style_b.py` (Mermaid `.md` / `.azure.md`), `style_c.py` (HTML) and `style_d.py` (Excalidraw)
- Test: `tests/test_gitdiagram_exports.py`

**Interfaces:**
- draw.io: a `link="<href>"` attribute on each vertex cell.
- Mermaid: `click n<i> "<href>"` lines, and the overview as a paragraph above the block.
- HTML: boxes wrapped in `<a>`, and the overview at the top.
- Excalidraw: a `"link": "<href>"` property on box elements, and an overview text element.

- [ ] **Step 1: Write the failing tests.**
  - `test_drawio_cells_have_links`
  - `test_mermaid_click_lines`
  - `test_excalidraw_links`
  - `test_html_box_links`
  - `test_special_characters_escaped_everywhere` (Review Focus 3): a group named `Pay & "Post" [v2] | <A>` gives drawio/HTML/SVG that parse with `xml.etree`, Excalidraw that parses with `json`, and Mermaid that uses `#quot;` with no raw `[`, `|` or `<` in labels.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests again. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: gitdiagram links in the editable exports`.

---

### Task 7: Links report for the gitdiagram

**Files:**
- Modify: `archdiag/render/report.py`
- Test: `tests/test_gitdiagram_report.py`

**Interfaces:**
- `links_report(view, r)` for level `gitdiagram` adds sections in this order:
  1. `## Overview` (the text);
  2. `## Groups`, each group with its full file list as relative links;
  3. `## Entry points`, the full lists per actor;
  4. then the existing sections;
  5. `## Not yet grouped`, the full list;
  6. `## Problems in the gitdiagram file`.
- Rows for combined arrows list every underlying edge, as today. Rows for Scheduler lines are listed under "Job structure", never as links.

- [ ] **Step 1: Write the failing tests.**
  - `test_report_has_gitdiagram_sections_in_order`
  - `test_every_group_file_listed`
  - `test_scheduler_lines_not_listed_as_links`
  - `test_problems_listed`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests again. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: gitdiagram links report`.

---

### Task 8: CLI: `draw --level gitdiagram` and `gitdiagram-context`

**Files:**
- Modify: `archdiag/cli.py`
- Test: `tests/test_gitdiagram_cli.py`

**Interfaces:**
- `CLI_LEVELS` gains `"gitdiagram"`, and `DEFAULT_STYLE["gitdiagram"] = "b"`.
- `draw --level gitdiagram --scope <repo>` loads `load_gitdiagram(out_dir, r, repo)` and passes it to `build_view`. A bad repo gives exit 2 with "Did you mean".
- **Outputs:** `gitdiagram-<repo slug>-<style>.*` and `gitdiagram-<repo slug>-links.md`.
- **Stdout** adds these lines before `Wrote:`:
  - `Not yet grouped: N files (see <report>)` when N > 0;
  - `Grouped by folder. Ask Copilot to name groups for this repo.` when `from_file` is False;
  - one `Problem in gitdiagram-<repo>.json: …` line each, up to 5.
- `gitdiagram-context --workspace <ws> --repo <repo>` prints `gitdiagram_context(...)`. It is machine-read, so notices go to stderr, like `list`.

- [ ] **Step 1: Write the failing tests** (on a fixture copy).
  - `test_draw_gitdiagram_all_styles_writes_files`
  - `test_draw_without_file_uses_folders_and_says_so`
  - `test_not_yet_grouped_line`
  - `test_bad_repo_scope_suggests`
  - `test_context_command_stdout_clean`
  - `test_cli_never_writes_gitdiagram_file`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests again, then the full suite. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: gitdiagram commands`.

---

### Task 9: Fixture gitdiagram files and a release gate for group arrows

**Files:**
- Create:
  - `tests/fixtures/claims-estate/architecture-diagrams/gitdiagram-claims-batch.json`. Groups: "Nightly jobs" (jcl/**, jcl.pds/**, proc/**), "Claim pricing" (CLMB200, CLMB210), "Payments" (CLMB300, CLMB400), "Not analyzed" (asm/**). Overview written by hand.
  - `tests/fixtures/claims-estate/architecture-diagrams/gitdiagram-claims-api.json`. Groups: "REST controllers", "MQ gateway", "z/OS Connect client", "Data access", "Outbound clients". Plus one suggested link.
  - `tests/fixtures/expected_gitdiagram.json`: per repo, a list of `{src, dst, label_family, status}` for every drawn arrow, actor line and outside stub.
  - `tests/fixtures/expected_gitdiagram_notes.md`
  - `tests/test_gitdiagram_gate.py`
- **Discipline:** the expected list is written by hand from the fixture sources and spec §4.2/§10, with a note line per entry citing file:line and the rule. It is never copied from output. When the code disagrees: fix the code, unless the expected entry contradicts the spec; then fix the entry and say why in the notes.

- [ ] **Step 1:** Write the two gitdiagram files and the expected list with notes.
- [ ] **Step 2: Write the gate tests.**
  - `test_no_missed_group_arrows`
  - `test_no_unexpected_solid_group_arrows`
  - `test_group_arrow_status_matches`
  - `test_every_file_accounted_for`, for both repos.
- [ ] **Step 3:** Run `.venv/bin/python -m pytest tests/test_gitdiagram_gate.py -v`, then the full suite. Expected: PASS after settling every difference.
- [ ] **Step 4:** Commit with message `test: gitdiagram release gate over the claims fixture`.

---

### Task 10: Skill instructions, references, README

**Files:**
- Modify: `skill/architecture-diagrams/SKILL.md`, `reference/levels-and-styles.md`, `reference/groups-format.md` (add the gitdiagram file format), `skill/architecture-diagrams/README.md`
- Test: `tests/test_skill_package.py` (extend)

**Interfaces:**
- **SKILL.md**
  - Triggers: "gitdiagram", "diagram of this repo", "how is <repo> put together", "repo structure".
  - When no gitdiagram file exists:
    1. Run `gitdiagram-context`.
    2. Propose about 6–15 groups with tech, a short description and an overview. For README-less mainframe repos, group by job streams, the programs they run, shared copybooks and online transactions.
    3. **Show them to the user and wait for changes.**
    4. Write `architecture-diagrams/gitdiagram-<repo>.json`.
    5. Run `draw --level gitdiagram --scope <repo>`.
  - When the file exists: draw. If stdout reports "Not yet grouped", offer to place those files.
  - Never put a link Copilot believes in anywhere except `suggested_links`, with a note.
  - Never write outside `architecture-diagrams/`.
- **levels-and-styles.md:** a row for the gitdiagram level (default style B) and its phrases.
- **README:** a short "Diagram of one repo" section.

- [ ] **Step 1: Write the failing tests.**
  - `test_skill_mentions_gitdiagram_commands`
  - `test_skill_says_show_groups_before_saving`
  - `test_skill_forbids_solid_links_from_copilot`, which keeps the existing "never add links" rule.
  - `test_reference_documents_gitdiagram_file_fields`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Write the docs.
- [ ] **Step 4:** Run the tests again. Expected: PASS.
- [ ] **Step 5:** Commit with message `docs: gitdiagram in the skill instructions and README`.

---

### Task 11: Visual check and acceptance update

**Files:**
- Modify: `docs/acceptance.md`, `docs/acceptance/` (add `style-b-gitdiagram-claims-batch.png` and `style-a-gitdiagram-claims-api.png`)

- [ ] **Step 1: Render and screenshot.** Render `gitdiagram` for claims-batch and claims-api in all four styles on a copy of the fixture. Screenshot each with headless Chrome (`--headless=new --window-size=<w>,<h> --screenshot`) and read the PNGs.
- [ ] **Step 2: Compare and fix.** Compare with the GitDiagram reference (https://gitdiagram.com/balapininti/copilot-architecture-diagrams) for readability: named groups, labelled arrows, actors, overview. Fix clear problems in the owning task's code, with a test where one is possible.
- [ ] **Step 3: Check under Python 3.9.** Run the CLI end to end under `/usr/bin/python3 -I` (3.9.6): `gitdiagram-context` and `draw --level gitdiagram --style all` for both repos.
- [ ] **Step 4: Update the acceptance doc.** Update `docs/acceptance.md`: a Run-here row for the gitdiagram, the version line 0.1.4, and a Windows W3 request "create a gitdiagram for claims-batch".
- [ ] **Step 5:** Commit with message `docs: gitdiagram acceptance and reference images`.
