# Architecture Diagram Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A GitHub Copilot skill (VS Code agent mode and Copilot CLI) that scans one or many local repos of COBOL/JCL/CICS/DB2/MQ, Java and Angular code, finds every cross-repo link with file-and-line evidence, and draws pictorial architecture diagrams at four zoom levels in four styles, as SVG plus an editable file and a links report.

**Architecture:** A stdlib-only Python package (`archdiag`) shipped inside the skill folder. Its pipeline is scan, then resolve, then group, then view, then layout, then render. Scanners turn source files into `Node` definitions and `Ref` uses. The resolver turns refs into `Edge`s with a status (confirmed, partial or loose). Copilot only edits `groups.json` (application names, suggested links). Views cut the resolved graph into one of four levels. One layout engine positions it, and four renderers draw it. `SKILL.md` tells Copilot which commands to run.

**Tech Stack:** Python 3.9+ standard library only at run time. pytest for development tests only. Output formats: SVG, draw.io XML, Mermaid, HTML, Excalidraw JSON, Markdown.

**Spec:** `docs/superpowers/specs/2026-11-06-architecture-diagram-skill-design.md`. Approved samples are in `docs/samples/` (`style-options.html`, `mainframe-samples.html`).

## Global Constraints

- Run-time code imports the Python standard library only: "No pip installs, no network." A test enforces this (Task 1).
- Python 3.9 compatible: no `match`, no `X | Y` outside annotations, no `dataclass(slots=True)`. Every module starts with `from __future__ import annotations`.
- Windows first: "paths with spaces, long paths, CRLF line endings". Source is read as UTF-8, then Windows-1252, then Latin-1, and the reader "never crashes on bad bytes".
- Evidence paths are repo-relative with forward slashes. Line numbers are 1-based.
- Offline: "HTML outputs carry their own CSS and JS inline". No URLs to CDNs or fonts in any output.
- SVG must survive Word and PowerPoint: no `<filter>`, no `<style>` blocks, no `<use>`, no `<marker>`. Arrowheads are drawn as polygons, and all styling is done with presentation attributes. Whiteboard wobble is jitter in the path points.
- Fonts: `Segoe UI, Arial, sans-serif` for A, B and C. `Segoe Print, Comic Sans MS, cursive` for D. Code text uses `Consolas, monospace`.
- Line types are the same on every diagram. **Confirmed:** solid `#334155`, 2px. **Partial:** dotted `#d97706` (`stroke-dasharray="3 4"`). **Loose:** solid `#dc2626` ending in a filled dot r=6. **Shared code:** dashed `#a16207` (`7 4`).
- "a link is solid only when the name is fully worked out from code in the repos and exactly one thing matches it." (spec §7.4)
- "Copilot may not add links." Copilot's suggestions are only ever drawn as partial.
- Size limit: `MAX_NODES = 40` drawn boxes per diagram.
- Output folder: `<workspace>/architecture-diagrams/`, holding `inventory.json`, `links.json`, `groups.json`, `archdiag.config.json` and all diagrams.
- IBM-supplied copybooks are never reported as loose: `DFHAID`, `DFHBMSCA`, `DFHEIBLK`, `DFHCOMMAREA`, `SQLCA`, `SQLDA`, `CMQV`, `CMQODV`, `CMQMDV`, `CMQPMOV`, `CMQGMOV`.

## Review Focus

1. **Names that break XML:** `&&SORTED`, `CLM#01`, `<`/`>` in SQL, and quotes in labels must be escaped in SVG, draw.io and HTML. Each output must still parse with `xml.etree` (test in Task 12, reused by 13–15).
2. **Non-source content in repos:** `.git/`, `node_modules/`, `target/`, `bin/`, `.class`, `.jar`, images and load modules are skipped without being read as text (test in Task 1).
3. **Comment lines that look like code:** COBOL column-7 `*` or `/` lines and JCL `//*` lines that contain `CALL`, `EXEC SQL` or `DSN=` produce no facts (tests in Tasks 3 and 4).
4. **Unknown scope or empty workspace:** a misspelled job or transaction name gets close-match suggestions and exit code 2. A folder with no repos gets a plain message and exit code 3, never a traceback (test in Task 17).
5. **Large estates:** a generated 50-repo, 3,000-file workspace must scan and resolve in under 120 s, and no drawn diagram may exceed `MAX_NODES` (tests in Tasks 11 and 17).

---

## File Structure

```
skill/architecture-diagrams/          # the deliverable folder that gets installed
  SKILL.md                            # Copilot instructions (Task 18)
  README.md                           # client install + fallback route (Task 18)
  reference/levels-and-styles.md      # how to pick level/scope/style (Task 18)
  reference/groups-format.md          # groups.json + config format (Task 18)
  scripts/run.py                      # entry point: puts scripts/ on sys.path, calls archdiag.cli.main
  scripts/archdiag/
    __init__.py                       # __version__ = "0.1.0"
    model.py                          # Evidence, Node, Ref, Edge, Repo, Inventory, Resolved, status constants
    textio.py                         # read_source, classify
    repos.py                          # discover_repos, iter_source_files
    config.py                         # Config, load_config
    store.py                          # JSON save/load, fingerprint
    scan/__init__.py                  # ScanContext, scan_workspace (two passes)
    scan/jcl.py  scan/cobol.py  scan/cics.py  scan/ddl.py  scan/mq.py
    scan/zosconnect.py  scan/other.py  scan/java.py  scan/angular.py
    resolve/__init__.py               # resolve()
    resolve/names.py                  # name normalization
    resolve/programs.py               # program / copybook / CICS / call matching
    resolve/data.py                   # dataset / table / queue / trigger / REST / transfer matching
    groups.py                         # groups.json
    summary.py                        # summary + list for Copilot
    views.py                          # ViewGraph + build_view
    layout.py                         # Layout + layered / job_rows / card_grid
    render/common.py                  # escaping, text width, arrowheads, legend, palette
    render/style_a.py style_b.py style_c.py style_d.py
    render/report.py                  # links report
    cli.py
install.ps1                           # copies skill folder into Copilot skills dir (Task 18)
pyproject.toml                        # pytest config only
tests/
  conftest.py                         # ESTATE path, run_pipeline() helper
  fixtures/claims-estate/<6 repos>/   # built up in Tasks 3–6
  fixtures/claims-estate/architecture-diagrams/archdiag.config.json
  fixtures/expected_links.json        # Task 9
  test_*.py
```

---

### Task 1: Skeleton, model, file reading, repo discovery

**Files:**
- Create: `pyproject.toml`, `skill/architecture-diagrams/scripts/run.py`, `scripts/archdiag/{__init__,model,textio,repos,config,store,cli}.py`, `scripts/archdiag/scan/__init__.py`, `tests/conftest.py`
- Test: `tests/test_foundation.py`

**Interfaces:**
- Produces (`model.py`):
  ```python
  CONFIRMED, PARTIAL, LOOSE = "confirmed", "partial", "loose"
  @dataclass(frozen=True) class Evidence: repo: str; path: str; line: int; text: str
  @dataclass class Repo: name: str; path: str            # path relative to workspace, "." for single-repo
  @dataclass class Node: id: str; kind: str; name: str; repo: Optional[str]; evidence: List[Evidence]; attrs: Dict[str, Any] = {}
  @dataclass class Ref: src: str; op: str; target_kind: str; target_name: Optional[str]; evidence: Evidence
                        reason: Optional[str] = None; candidates: List[str] = []; attrs: Dict[str, Any] = {}
  @dataclass class Edge: src: str; op: str; dst: str; status: str; reason: Optional[str]; evidence: List[Evidence]
  @dataclass class Inventory: workspace: str; repos: List[Repo]; nodes: Dict[str, Node]; refs: List[Ref]
                              fingerprint: str; languages_not_analyzed: Dict[str, int]
  @dataclass class Resolved: inventory: Inventory; nodes: Dict[str, Node]; edges: List[Edge]
  ```
  Node id conventions, used everywhere: `program:CLMO100`, `copybook:CLMREC`, `transaction:CLMI`, `map:CLMM01`, `table:CLMS.CLAIM`, `queue:CLM.REQ.LQ`, `dataset:<normalized key>`, `job:<repo>/<relpath>`, `step:<repo>/<relpath>#<STEPNAME>`, `utility:SORT`, `class:<repo>/<SimpleName>`, `component:<repo>/<ClassName>`, `page:<repo>/<route>`, `endpoint:<METHOD> <norm path>`, `zosapi:<METHOD> <norm path>`, `missing:<kind>:<name>`, `external:<label>`, `notanalyzed:<NAME>`. Names of mainframe entities are upper-cased.
- Produces: `textio.read_source(path: Path) -> str` (normalizes CRLF to LF) and `textio.classify(relpath: str, text: str) -> Optional[str]`. File types: `jcl, proc, cobol, copybook, csd, bms, ddl, mqsc, zosconnect, java, properties, yaml, angular_ts, asm, pli, easytrieve, rexx`, or `None`.
- Produces: `repos.discover_repos(workspace: Path) -> List[Repo]` and `repos.iter_source_files(root: Path) -> Iterator[Path]`.
- Produces: `config.Config(environment_qualifiers: List[str] = [], exclude_dirs: List[str] = [])` and `config.load_config(out_dir: Path) -> Config`, reading `archdiag.config.json` (missing file gives defaults).
- Produces: `store.fingerprint(workspace: Path, repos) -> str` (sha1 over sorted relpath|size|mtime_ns), plus `store.save_json(path, obj)` and `store.load_inventory(path) -> Inventory`, `store.load_resolved(path) -> Resolved`. Dataclasses round-trip through `dataclasses.asdict`.
- Produces: `scan.ScanContext` (fields `procs: Dict[str, str]`, `props: Dict[str, Dict[str, str]]` per repo, `ts_env: Dict[str, Dict[str, str]]` per repo) and `scan.scan_workspace(workspace: Path, config: Config) -> Inventory`. In this task it discovers repos, classifies files and returns an empty node/ref set. Tasks 3–6 register the scanners in `SCANNERS: Dict[str, Callable[[str, str, str, ScanContext], Tuple[List[Node], List[Ref]]]]`.
- Produces: `cli.main(argv: List[str]) -> int` with subcommand `scan --workspace PATH`, which writes `architecture-diagrams/inventory.json`.

- [ ] **Step 1: Write the failing tests**

```python
def test_single_repo_when_workspace_is_git(tmp_path):
    (tmp_path/".git").mkdir(); assert [r.path for r in discover_repos(tmp_path)] == ["."]
def test_child_repos(tmp_path):
    for n in ("b-repo","a repo"): (tmp_path/n/".git").mkdir(parents=True)
    (tmp_path/"notes").mkdir()
    assert [r.name for r in discover_repos(tmp_path)] == ["a repo","b-repo"]   # sorted; spaces OK; non-repo skipped
def test_read_source_falls_back_and_normalizes(tmp_path):
    p = tmp_path/"X.cbl"; p.write_bytes("      * caf\xe9\r\n".encode("cp1252"))
    assert read_source(p) == "      * café\n"
def test_skips_non_source(tmp_path):
    for rel in (".git/HEAD","node_modules/a.ts","target/A.class","bin/x.jar","img/a.png","src/A.java"):
        f = tmp_path/rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text("x")
    assert [p.relative_to(tmp_path).as_posix() for p in iter_source_files(tmp_path)] == ["src/A.java"]
def test_classify_by_content_without_extension():
    assert classify("cobol.pds/CLMB400", "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CLMB400.\n") == "cobol"
    assert classify("jcl.pds/CLMD300", "//CLMD300 JOB (ACCT),'X'\n") == "jcl"
    assert classify("x/README", "hello") is None
def test_runtime_imports_are_stdlib_only():
    # walk scripts/archdiag/**/*.py with ast; every top-level import name must be "archdiag" or in STDLIB_39 (frozen list in the test)
def test_cli_scan_writes_inventory(tmp_path):
    (tmp_path/"r"/".git").mkdir(parents=True)
    assert main(["scan","--workspace",str(tmp_path)]) == 0
    assert (tmp_path/"architecture-diagrams"/"inventory.json").exists()
```

- [ ] **Step 2: Run `python -m pytest tests/test_foundation.py -v`.** Expected: FAIL (modules missing).

- [ ] **Step 3: Implement the interfaces above.** Skipped directories: `.git .svn node_modules target build bin obj dist .idea .vscode architecture-diagrams`, plus `config.exclude_dirs`. Skipped extensions: `.class .jar .war .ear .zip .png .jpg .gif .ico .pdf .exe .dll .so .lock`, and any file over 5 MB. In `classify`, the extension decides first (`.cbl .cob` cobol; `.cpy` copybook; `.jcl` jcl; `.proc .prc` proc; `.csd` csd; `.bms` bms; `.sql .ddl` ddl; `.mqsc` mqsc; `.java` java; `.properties` properties; `.yml .yaml` yaml; `.ts` angular_ts; `.asm .mac` asm; `.pli .pl1` pli; `.ezt` easytrieve; `.rexx .rex .clist` rexx; `.sar .aar` and `zosconnect/**` zosconnect). Otherwise content sniffing looks at the first 20 non-blank lines: `//name JOB` gives jcl, `//name PROC` gives proc, `PROGRAM-ID` gives cobol, ` CSECT`/` DFHMSD` gives asm/bms, `PROCEDURE OPTIONS(MAIN)` gives pli, `/* REXX` gives rexx. `run.py` inserts its own directory at `sys.path[0]` and calls `sys.exit(cli.main(sys.argv[1:]))`.

- [ ] **Step 4: Run the tests again.** Expected: PASS.

- [ ] **Step 5: Commit** with message `feat: skeleton, model, source reading and repo discovery`.

---

### Task 2: Layout engine spike (biggest risk, proven early)

**Files:**
- Create: `scripts/archdiag/views.py` (types only in this task), `scripts/archdiag/layout.py`
- Test: `tests/test_layout.py`

**Interfaces:**
- Produces (`views.py` types):
  ```python
  @dataclass class VNode: id: str; label: str; sublabel: str = ""; kind: str = "program"; group: Optional[str] = None
                          status: Optional[str] = None; detail_lines: List[str] = []; row: Optional[str] = None  # "above"|"lane"|"below" for job flows
  @dataclass class VEdge: src: str; dst: str; label: str = ""; status: str = "confirmed"; kind: str = "runtime"  # or "shared_code"
                          evidence: List[Evidence] = []; number: Optional[int] = None
  @dataclass class VGroup: id: str; label: str; color: str
  @dataclass class ViewGraph: title: str; level: str; scope: Optional[str]; nodes: List[VNode]; edges: List[VEdge]
                              groups: List[VGroup]; notes: List[str] = []
  ```
  `level` is one of `landscape`, `application`, `flow_job`, `flow_tx`, `repomap`.
- Produces (`layout.py`):
  ```python
  @dataclass class Box: x: float; y: float; w: float; h: float
  @dataclass class Layout: width: float; height: float; boxes: Dict[str, Box]; groups: Dict[str, Box]
                           routes: List[List[Tuple[float, float]]]      # one polyline per view.edges index
                           label_at: List[Tuple[float, float]]          # one label anchor per edge
  def layout_for(view: ViewGraph, node_size: Callable[[VNode], Tuple[float, float]]) -> Layout
  ```
  `node_size` comes from the renderer, so each style can size its own boxes.

- [ ] **Step 1: Write the failing tests** on hand-built graphs. Copy the landscape from `docs/samples/mainframe-samples.html` diagram 1 into a helper `claims_landscape()`, and job CLMD100 from diagram 2 into `claims_job()`.

```python
def test_layered_no_overlaps_and_left_to_right():
    v = claims_landscape(); L = layout_for(v, lambda n: (170, 90))
    assert no_box_overlaps(L.boxes, margin=20)
    for e, r in zip(v.edges, L.routes):                     # routes start/end on their boxes' borders
        assert on_border(r[0], L.boxes[e.src]) and on_border(r[-1], L.boxes[e.dst])
    assert L.boxes["app:portal"].x < L.boxes["app:api"].x < L.boxes["queue:CLM.REQ"].x
def test_groups_enclose_members():
    v = claims_landscape(); L = layout_for(v, lambda n: (170, 90))
    for n in v.nodes:
        if n.group: assert contains(L.groups[n.group], L.boxes[n.id])
def test_cycles_do_not_hang():
    v = graph_with_cycle(); L = layout_for(v, lambda n: (100, 60)); assert len(L.boxes) == len(v.nodes)
def test_job_rows():
    v = claims_job(); L = layout_for(v, lambda n: (140, 80))
    lane_y = {L.boxes[n.id].y for n in v.nodes if n.row == "lane"}; assert len(lane_y) == 1
    assert all(L.boxes[n.id].y < min(lane_y) for n in v.nodes if n.row == "above")
    assert all(L.boxes[n.id].y > min(lane_y) for n in v.nodes if n.row == "below")
    steps = [n for n in v.nodes if n.row == "lane"]
    assert [L.boxes[s.id].x for s in steps] == sorted(L.boxes[s.id].x for s in steps)   # step order kept
def test_repomap_card_grid_no_overlaps():
    v = repomap_of(6); L = layout_for(v, lambda n: (260, 150)); assert no_box_overlaps(L.boxes, 40)
def test_crossings_reduced():
    v = crossing_bait(); L = layout_for(v, lambda n: (100, 60)); assert count_crossings(v, L) <= 1
def test_writes_debug_svg(tmp_path):
    # writes tmp_path/landscape.svg using only rects + polylines, for a human to look at; asserts it parses with xml.etree
```

- [ ] **Step 2: Run `python -m pytest tests/test_layout.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement `layout_for`.** It dispatches by level: `flow_job` goes to `job_rows`, `repomap` goes to `card_grid`, and everything else goes to `layered`.
  - **`layered`:** break cycles by reversing DFS back edges. Assign layers by longest path. Order nodes within a layer with 4 down/up barycenter sweeps, keeping members of one group contiguous. Space columns at max width + 90 and rows at max height + 50. Pad groups by 20 with 24 extra on top for the title. Edges use orthogonal or straight routes from border to border, and the label sits at the route midpoint.
  - **`job_rows`:** lane nodes go left to right in list order. Each `above`/`below` node goes at the x of the mean of the lane nodes it connects to, and the row is spread apart to stop overlaps.
  - **`card_grid`:** a `ceil(sqrt(n))`-column grid ordered by number of links (most connected in the middle). Routes are cubic Béziers between the closest card sides, flattened into a polyline of 12 points.

- [ ] **Step 4: Run the tests and open the debug SVG.** Run `python -m pytest tests/test_layout.py -v`. Expected: PASS. Open the debug SVG and compare it by eye with diagram 1 of the samples. If it reads badly, fix it here before going on.

- [ ] **Step 5: Commit** with message `feat: layout engine for layered, job-row and card-grid diagrams`.

---

### Task 3: JCL scanner + batch fixture

**Files:**
- Create: `scripts/archdiag/scan/jcl.py`, `tests/fixtures/claims-estate/claims-batch/` (`.git/` marker dir plus the files below)
- Modify: `scan/__init__.py` (register `jcl` and `proc` scanners, plus the pass-1 proc collection)
- Test: `tests/test_scan_jcl.py`

**Interfaces:**
- Consumes: `Node`, `Ref`, `Evidence`, `ScanContext` (Task 1).
- Produces: `collect_procs(repo, relpath, text, ctx) -> None` (pass 1, fills `ctx.procs[NAME] = text`) and `scan_jcl(repo, relpath, text, ctx) -> Tuple[List[Node], List[Ref]]`.
  - It emits a `job:` node and `step:` nodes. Step attrs: `order: int`, `cond: str` (normalized, e.g. `"RC <= 4"` or `"COND=(0,NE)"`), `pgm: str`, `proc: Optional[str]`.
  - It emits Refs with `src = step id`:
    - `runs` → `program` (`EXEC PGM=X`, or `DSN RUN PROGRAM(X)` in `SYSTSIN` when PGM is `IKJEFT01/IKJEFT1B`) or → `utility` (when X is in `UTILITIES = {SORT, ICETOOL, SYNCSORT, IEBGENER, IEBCOPY, IDCAMS, IEFBR14, IKJEFT01, IKJEFT1B, DMBATCH, FTP, ADRDSSU, DFSRRC00}`; the IKJEFT01 case reports the inner program).
    - `read`, `write` or `update` → `dataset`, with `attrs={"ddname", "disp", "gdg": "+1"|"0"|None}`.
    - `transfer` → `external` for `DMBATCH` (Connect:Direct `SNODE=`) and FTP steps, with `target_name = "NDM:<SNODE>"` or `"FTP:<host>"`.
  - DISP rules: `SHR` → read; `NEW`, `(NEW,…)` and `MOD` → write; `OLD` → update. Temporary `&&X` datasets give a `read`/`write` Ref with `attrs["temp"] = True`, and the resolver keeps them inside their job. `SYSOUT=` gives no Ref; the report node is a `step.attrs["sysout"]` list.
  - Symbols: `// SET`, PROC defaults (`//CLMPRC PROC ENV=TEST`) and EXEC overrides (`EXEC CLMPRC,ENV=PROD`) are applied, override first. `&X.` and `&X..` are handled. An unresolved symbol leaves `&X` in `target_name` with `reason="symbol &X has no value in these repos"`. In-repo PROCs and `// INCLUDE MEMBER=` members are expanded inline, with steps named `<procstep>` and evidence pointing at the proc file line.

- [ ] **Step 1: Create the fixture files** in `claims-batch/`:
  - `jcl/CLMD100.jcl`: `// SET HLQ=PROD`.
    - STEP010 `PGM=SORT`: `SORTIN DSN=&HLQ..CLM.MASTER.KSDS,DISP=SHR`, `SORTOUT DSN=&&SORTED,DISP=(NEW,PASS)`.
    - STEP020 `PGM=CLMB200` with `COND=(0,NE)`: `CLMIN DSN=&&SORTED,DISP=(OLD,DELETE)`, `CLMOUT DSN=&HLQ..CLAIMS.DAILY(+1),DISP=(NEW,CATLG)`.
    - STEP030 `PGM=IKJEFT01`: `SYSTSIN DD *` holding `DSN SYSTEM(DB2P)` / `RUN PROGRAM(CLMB300) PLAN(CLMP300)`, plus `DAILYIN DSN=&HLQ..CLAIMS.DAILY(0),DISP=SHR` and `REPORT DD SYSOUT=A`.
    - `// IF (RC <= 4) THEN`.
    - STEP040 `PGM=IEBGENER`: `SYSUT1 DSN=&HLQ..CLAIMS.DAILY(0),DISP=SHR`, `SYSUT2 DSN=PROD.CLAIMS.EXTRACT,DISP=(NEW,CATLG)`, `AUDIT DSN=PROD.CLAIMS.AUDIT,DISP=(MOD,CATLG)`.
    - STEP050 `PGM=DMBATCH`, whose SYSIN has `COPY FROM (DSN=PROD.CLAIMS.EXTRACT) TO (SNODE=FINANCE DSN=FIN.IN.CLAIMS)`.
    - A `//* EXEC PGM=FAKEPGM DSN=FAKE.DS` comment line.
  - `jcl/test/CLMD100.jcl`: the same job with `// SET HLQ=TEST` (an environment copy).
  - `proc/CLMPRC.proc`: `//CLMPRC PROC ENV=TEST`, then `//RUN EXEC PGM=CLMB400` with `FEED DD DSN=&ENV..PAYMENT.FEED,DISP=SHR`.
  - `jcl.pds/CLMD300` (no extension): `//S1 EXEC CLMPRC,ENV=PROD`, then `//S2 EXEC PGM=IEFBR14` with `OUT DD DSN=&UNDEF..OUT.FILE,DISP=(NEW,CATLG)`.

- [ ] **Step 2: Write the failing tests**

```python
def refs_of(step): ...   # helper: scan fixture repo, return {(op, target_kind, target_name)} for that step
def test_symbols_and_disp():
    assert ("read","dataset","PROD.CLM.MASTER.KSDS") in refs_of("claims-batch/jcl/CLMD100.jcl#STEP010")
    assert ("write","dataset","PROD.CLAIMS.DAILY") in refs_of("claims-batch/jcl/CLMD100.jcl#STEP020")
def test_gdg_attr():  # STEP020 CLMOUT ref.attrs["gdg"] == "+1"; STEP030 DAILYIN gdg == "0"
def test_ikjeft01_runs_inner_program():
    assert ("runs","program","CLMB300") in refs_of("claims-batch/jcl/CLMD100.jcl#STEP030")
def test_utilities_and_transfer():
    assert ("runs","utility","IEBGENER") in refs_of("claims-batch/jcl/CLMD100.jcl#STEP040")
    assert ("transfer","external","NDM:FINANCE") in refs_of("claims-batch/jcl/CLMD100.jcl#STEP050")
def test_mod_is_write():  ("write","dataset","PROD.CLAIMS.AUDIT") in STEP040
def test_temp_dataset_flagged():  # STEP010 SORTOUT ref.attrs["temp"] is True, target_name "&&SORTED"
def test_proc_override_beats_default():
    assert ("read","dataset","PROD.PAYMENT.FEED") in refs_of("claims-batch/jcl.pds/CLMD300#RUN")
def test_unresolved_symbol_kept_with_reason():
    r = one_ref("claims-batch/jcl.pds/CLMD300#S2", "write"); assert r.target_name == "&UNDEF..OUT.FILE"
    assert r.reason == "symbol &UNDEF has no value in these repos"
def test_cond_and_order():  # STEP020.attrs["cond"] == "COND=(0,NE)"; STEP040.attrs["cond"] == "RC <= 4"; orders 1..5
def test_comment_lines_ignored():  # no ref anywhere with target_name "FAKE.DS" or "FAKEPGM"
def test_continuation_lines():  # a DD split across two lines with trailing comma parses the same (add inline to a tmp file)
def test_evidence_points_to_line():  # STEP020 CLMOUT evidence.line == the line number of "CLMOUT" in the fixture
```

- [ ] **Step 3: Run `python -m pytest tests/test_scan_jcl.py -v`.** Expected: FAIL.

- [ ] **Step 4: Implement `collect_procs` and `scan_jcl`.** Join continuation lines (a statement ending in `,` continues on the next `//` line starting at column 4–16) before tokenizing parameters, splitting on commas outside parentheses and quotes. Statements are `JOB`, `EXEC`, `DD`, `SET`, `IF`/`ELSE`/`ENDIF`, `INCLUDE`, `PROC`/`PEND`, plus inline `DD *` data up to `/*` or the next `//`.

- [ ] **Step 5: Run the tests again.** Expected: PASS.

- [ ] **Step 6: Commit** with message `feat: JCL scanner with symbols, procs, GDGs and utilities`.

---

### Task 4: COBOL scanner + COBOL fixtures

**Files:**
- Create: `scripts/archdiag/scan/cobol.py`, fixture files below
- Modify: `scan/__init__.py` (register `cobol` and `copybook`)
- Test: `tests/test_scan_cobol.py`

**Interfaces:**
- Produces: `scan_cobol(repo, relpath, text, ctx) -> Tuple[List[Node], List[Ref]]`.
  - It emits a `program:<PROGRAM-ID>` node with `attrs={"files": {ddname: "input"|"output"|"i-o"|"extend"}}`, built from `SELECT … ASSIGN TO ddname` plus `OPEN` modes.
  - Copybook files emit `copybook:<NAME>` (the name is the file stem).
  - Refs with `src = program id`:
    - `copy` → `copybook`. `REPLACING` is ignored for matching.
    - `call` → `program`. A literal gives the name. A variable gives `target_name=None`, `reason="CALL through variable WS-X"` and `candidates=[VALUE literal]` when the data item has a `VALUE '…'`.
    - `select`, `insert`, `update` or `delete` → `table`, from `EXEC SQL … END-EXEC`. Tables are read from `FROM`, `JOIN`, `INTO` (INSERT only), `UPDATE` and `DELETE FROM`. Cursor declarations count as select. The name is kept as written, with or without a qualifier.
    - `link`, `xctl` or `start` → `program`/`transaction` from `EXEC CICS LINK PROGRAM(...)`, `XCTL PROGRAM(...)` and `START TRANSID(...)`. A variable argument is handled the same way as a variable `CALL` (`reason="XCTL to WS-NEXT-PGM, name set at run time"`, with candidates from VALUE).
    - `return_transid` → `transaction`, from `RETURN TRANSID('X')`.
    - `send_map` → `map`, from `SEND MAP(...) MAPSET('X')`. The mapset is the target.
    - `cics_file` → `cicsfile`, from `READ/WRITE/REWRITE/STARTBR FILE('X')`, with `attrs={"io": "read"|"write"}`.
    - `put` or `get` → `queue`, from `CALL 'MQPUT'/'MQGET'/'MQPUT1'`. The queue is found from the `MQOD-OBJECTNAME` MOVE source, or the data item passed to MQOPEN, resolved through `VALUE` or a `MOVE 'lit' TO` in the same program. If it can't be resolved, `target_name=None` with `reason="queue name not found in program"`.
  - Source format: columns 1–6 and 73+ are dropped. Column 7 `*` or `/` marks a comment. Column 7 `-` marks a continuation. If no line has a sequence area, free format is assumed.

- [ ] **Step 1: Create the fixtures.**
  - `claims-batch/cobol/CLMB200.cbl`:
    - `COPY CLMREC`.
    - `EXEC SQL SELECT … FROM CLAIM`.
    - `CALL 'DATEUTIL'`.
    - `01 WS-PGM PIC X(8) VALUE 'CLMB210'` with `CALL WS-PGM`.
    - `SELECT CLMIN ASSIGN TO CLMIN` / `OPEN INPUT CLMIN`, and `CLMOUT` opened OUTPUT.
    - A comment line `*    CALL 'NOTREAL'`.
  - `claims-batch/cobol/CLMB210.cbl` and `CLMB300.cbl` (`COPY PAYREC`, `INSERT INTO CLMS.PAYMENT`). Save CLMB300 as CRLF + cp1252 with `é` in a comment.
  - `claims-batch/cobol.pds/CLMB400` (no extension).
  - `claims-batch/asm/DATEUTIL.asm`.
  - `claims-online/cobol/CLMO100.cbl`:
    - `COPY CLMREC`, `COPY DFHAID`.
    - `SELECT … FROM CLAIM`, `FROM POLICY`, `FROM CLMS.CLM`.
    - `EXEC CICS LINK PROGRAM('CLMO110')`, `EXEC CICS XCTL PROGRAM(WS-NEXT-PGM)` (no VALUE), `EXEC CICS READ FILE('CLMMAST')`, `EXEC CICS RETURN TRANSID('CLMU')`, `EXEC CICS SEND MAP('CLMM1') MAPSET('CLMM01')`.
    - `MOVE 'CLM.REQ.LQ' TO MQOD-OBJECTNAME` then `CALL 'MQGET'`; `01 WS-RSPQ VALUE 'CLM.RSP'` moved into MQOD then `CALL 'MQPUT'`.
  - `claims-online/cobol/CLMO110.cbl` (`COPY ERRMSG`) and a duplicate `claims-online/endevor/qa/CLMO110.cbl`.
  - `claims-online/cobol/CLMO130.cbl`.
  - `shared-copybooks/CLMREC.cpy`, `shared-copybooks/PAYREC.cpy`, each with a `.git/` marker in the repo root. Create `claims-online/.git/` and `shared-copybooks/.git/`.

- [ ] **Step 2: Write the failing tests**

```python
def test_copy_call_sql():  # CLMB200 refs ⊇ {("copy","copybook","CLMREC"),("call","program","DATEUTIL"),("select","table","CLAIM")}
def test_variable_call_has_candidate():
    r = one(prog="CLMB200", op="call", target_name=None); assert r.candidates == ["CLMB210"] and "WS-PGM" in r.reason
def test_xctl_unresolved():
    r = one(prog="CLMO100", op="xctl"); assert r.target_name is None and r.candidates == []
    assert r.reason == "XCTL to WS-NEXT-PGM, name set at run time"
def test_cics_ops():  # CLMO100 ⊇ link CLMO110, return_transid CLMU, send_map CLMM01, cics_file CLMMAST(io=read)
def test_mq_queue_names_resolved():  # CLMO100 ⊇ ("get","queue","CLM.REQ.LQ"), ("put","queue","CLM.RSP")
def test_qualified_and_alias_names_kept_raw():  # CLMO100 selects ⊇ {"CLAIM","POLICY","CLMS.CLM"}
def test_file_modes():  # program:CLMB200 attrs["files"] == {"CLMIN":"input","CLMOUT":"output"}
def test_comment_not_scanned():  # no ref target_name == "NOTREAL"
def test_cp1252_crlf_file_scans():  # program:CLMB300 exists; ("insert","table","CLMS.PAYMENT")
def test_pds_member_without_extension():  # program:CLMB400 exists
def test_sequence_area_ignored():  # tmp file with "CALL 'ABC'" in cols 12-21 and "XYZ12345" in cols 73-80 → call ABC only
def test_multiline_exec_sql():  # SELECT split over 3 lines with FROM on the last → table found, evidence line = line of FROM
```

- [ ] **Step 3: Run `python -m pytest tests/test_scan_cobol.py -v`.** Expected: FAIL.

- [ ] **Step 4: Implement `scan_cobol`.** It works on a list of `(line_no, code_text)` after the column handling. EXEC blocks are collected up to `END-EXEC` before parsing. Each table or argument records the line where its token appears.

- [ ] **Step 5: Run the tests again.** Expected: PASS.

- [ ] **Step 6: Commit** with message `feat: COBOL scanner for copybooks, calls, SQL, CICS and MQ`.

---

### Task 5: Definition scanners (CSD, BMS, DDL, MQSC, z/OS Connect, other languages)

**Files:**
- Create: `scan/cics.py`, `scan/ddl.py`, `scan/mq.py`, `scan/zosconnect.py`, `scan/other.py`, fixtures below, and repo `claims-db/`
- Modify: `scan/__init__.py`
- Test: `tests/test_scan_defs.py`

**Interfaces:**
- Produces:
  - `scan_csd(...)` emits `transaction:X` nodes and `cicsfile:X` nodes (`attrs={"dsname": …}`), plus Refs `runs` (transaction → program) and `file_dataset` (cicsfile → dataset).
  - `scan_bms(...)` emits `map:<MAPSET>`.
  - `scan_ddl(...)` emits `table:<SCHEMA>.<NAME>` for TABLE and VIEW, with `attrs={"schema", "name", "type"}`. `CREATE ALIAS`/`SYNONYM A FOR B` gives `attrs["alias_of"]` on a `table:` node for A.
  - `scan_mqsc(...)` emits `queue:` nodes with `attrs={"type": "local"|"alias"|"remote", "target": …, "process": …, "initq": …, "bridge": bool}` and `mqprocess:` nodes with `attrs={"applicid": …}`. `bridge` is true when `INITQ` is the CICS bridge initiation queue or the queue name is listed in a CKBR start in the repo; fixture uses `DESCR('CICS BRIDGE')`.
  - `scan_zosconnect(...)` emits `zosapi:<METHOD> <path>` nodes with Refs `runs` → `program`.
  - `register_other(...)` emits `notanalyzed:<NAME>` with `attrs={"language"}`, where NAME is the file stem upper-cased, or the `CSECT`/`ENTRY` label for asm. It also counts files into `Inventory.languages_not_analyzed`.

- [ ] **Step 1: Research the z/OS Connect formats.** Use the web or the user's docs to confirm the on-disk layout of z/OS Connect EE service projects (`.sar`) and API projects (`.aar`): which file names the CICS program, and which maps an API path and method to a service. Write the findings, with source URLs, at the top of `scan/zosconnect.py` as a docstring. Read `.sar`/`.aar` with `zipfile`, and read unpacked project folders too. **If the formats can't be confirmed, stop and tell the user.** Don't invent a format.

- [ ] **Step 2: Create the fixtures.**
  - `claims-online/csd/CLAIMS.csd`: `DEFINE TRANSACTION(CLMI) PROGRAM(CLMO100)`, `DEFINE TRANSACTION(CLMU) PROGRAM(CLMO120)`, `DEFINE FILE(CLMMAST) DSNAME(PROD.CLM.MASTER.KSDS)`.
  - `claims-online/maps/CLMM01.bms`.
  - `claims-online/mq/claims.mqsc`: `DEFINE QLOCAL(CLM.REQ.LQ) TRIGGER INITQ(CICS01.INITQ) PROCESS(CLM.PROC)`, `DEFINE QALIAS(CLM.REQ) TARGET(CLM.REQ.LQ)`, `DEFINE PROCESS(CLM.PROC) APPLICID(CLMI)`, `DEFINE QLOCAL(CLM.RSP)`, `DEFINE QLOCAL(CLM.BRIDGE.Q) DESCR('CICS BRIDGE') PROCESS(CLM.BPROC)`, `DEFINE PROCESS(CLM.BPROC) APPLICID(CLMB)`.
  - `claims-online/zosconnect/`: a claim-status service mapping `GET /zos/claims/{id}/status` to program `CLMO130`, in the format confirmed in Step 1.
  - `claims-db/ddl/CLAIM.sql` (`CREATE TABLE CLMS.CLAIM`, `CREATE ALIAS CLMS.CLM FOR CLMS.CLAIM`), `PAYMENT.sql` (`CLMS.PAYMENT`) and `POLICY.sql` (`CLMS.POLICY` and `ARCH.POLICY`).

- [ ] **Step 3: Write the failing tests**

```python
def test_csd():  # transaction:CLMI runs CLMO100; transaction:CLMU runs CLMO120; cicsfile:CLMMAST dsname PROD.CLM.MASTER.KSDS
def test_ddl_tables_and_alias():  # nodes table:CLMS.CLAIM, CLMS.PAYMENT, CLMS.POLICY, ARCH.POLICY; table:CLMS.CLM attrs alias_of == "CLMS.CLAIM"
def test_mqsc():  # queue:CLM.REQ alias target CLM.REQ.LQ; queue:CLM.REQ.LQ process CLM.PROC; mqprocess:CLM.PROC applicid CLMI
def test_mq_bridge_flag():  # queue:CLM.BRIDGE.Q attrs["bridge"] is True
def test_zosconnect():  # node "zosapi:GET /zos/claims/{}/status" runs program CLMO130
def test_not_analyzed_registered():  # notanalyzed:DATEUTIL language "asm"; inventory.languages_not_analyzed["asm"] == 1
def test_ddl_comments_and_case():  # "-- CREATE TABLE FAKE.T" ignored; lower-case "create table clms.x" → table:CLMS.X
```

- [ ] **Step 4: Run `python -m pytest tests/test_scan_defs.py -v`.** Expected: FAIL.

- [ ] **Step 5: Implement the scanners.** Normalize REST paths through `resolve.names.norm_path` (Task 7). Define that function in this task if Task 7 isn't done yet, but keep its signature exactly as in Task 7.

- [ ] **Step 6: Run the tests again.** Expected: PASS.

- [ ] **Step 7: Commit** with message `feat: scanners for CSD, BMS, DDL, MQSC, z/OS Connect and unanalyzed languages`.

---

### Task 6: Java and Angular scanners + fixtures

**Files:**
- Create: `scan/java.py`, `scan/angular.py`, repos `claims-api/` and `claims-portal/`
- Modify: `scan/__init__.py` (pass 1 also loads `application*.yml`/`*.properties` into `ctx.props[repo]` and `environment*.ts` into `ctx.ts_env[repo]`)
- Test: `tests/test_scan_java_angular.py`

**Interfaces:**
- Produces: `scan_java(...)` emits `class:<repo>/<Simple>` nodes, and `endpoint:<METHOD> <norm path>` nodes (`attrs={"handler": class id}`) from `@RequestMapping` class prefix + `@Get/Post/Put/Delete/PatchMapping`. Refs:
  - `uses` → `class`, from constructor parameters and `@Autowired` fields whose type is a class in the same repo.
  - `http` → `endpoint`, with `target_name = "<METHOD> <url>"`. The URL comes from `RestTemplate`/`WebClient`/Feign `@*Mapping` on interfaces, joined with `${prop}` values from `ctx.props`. If the URL starts with `http(s)://` it's kept whole.
  - `put` or `get` → `queue`, from `jmsTemplate.convertAndSend/receive`, `MQQueue`/`accessQueue`, and `@JmsListener(destination=…)`, with `${prop}` resolved.
  - `select`, `insert`, `update` or `delete` → `table`, from SQL string literals in `jdbcTemplate.*`, `@Query(nativeQuery=true)` and `prepareStatement`.
  - `ctg_call` → `program`, from `ECIRequest(…, "PROG", …)`.
  - An unresolved `${prop}` gives a reason like `property mq.audit not found`.
- Produces: `scan_angular(...)` emits `component:<repo>/<ClassName>` for `@Component` and `@Injectable` classes, and `page:<repo>/<route path>` from `Routes` arrays, with a `uses` Ref → component. Refs:
  - `uses` → `component`, from constructor injection.
  - `http` → `endpoint`, from `this.http.get|post|put|delete|patch(...)`. Template literals and `+` concatenation are joined using `ctx.ts_env[repo]` (`environment.apiBase` and so on).

- [ ] **Step 1: Create the fixtures.**
  - `claims-api/src/main/resources/application.yml`: `mq: {request: CLM.REQ, reply: CLM.RSP}`, `zosconnect.url: https://zcee.internal:9443`.
  - `claims-api/.../ClaimController.java`: `@RequestMapping("/api")`, `@GetMapping("/claims/{id}")`, `@PostMapping("/claims")`, and a constructor taking `MqClaimGateway` and `ClaimStatusClient`.
  - `MqClaimGateway.java`: `convertAndSend("${mq.request}")` via `@Value` field, and `receive("${mq.reply}")`.
  - `ClaimStatusClient.java`: `restTemplate.getForObject(zosUrl + "/zos/claims/{id}/status", …)` with `@Value("${zosconnect.url}") String zosUrl`.
  - `ClaimRepository.java`: `jdbcTemplate.query("SELECT * FROM CLMS.POLICY WHERE …")`.
  - `AuditPublisher.java`: `convertAndSend("CLM.AUDIT", …)`.
  - `RatesClient.java`: `getForObject("https://rates.example.com/v1/rates", …)`.
  - `claims-portal/src/environments/environment.ts`: `apiBase: '/api'`.
  - `claim.service.ts`: `http.get(\`${environment.apiBase}/claims/${id}\`)`, `http.post(environment.apiBase + '/claims', c)`, `http.delete(\`${environment.apiBase}/claims/${id}\`)`.
  - `claim-details.component.ts`: injects ClaimService.
  - `app-routing.module.ts`: `{ path: 'claims/:id', component: ClaimDetailsComponent }`.
  - `.git/` markers in both repos.

- [ ] **Step 2: Write the failing tests**

```python
def test_endpoints():  # nodes "endpoint:GET /api/claims/{}", "endpoint:POST /api/claims", handler class:claims-api/ClaimController
def test_java_queue_props_resolved():  # MqClaimGateway ⊇ ("put","queue","CLM.REQ"), ("get","queue","CLM.RSP")
def test_java_http_join():  # ClaimStatusClient ("http","endpoint","GET https://zcee.internal:9443/zos/claims/{id}/status")
def test_java_sql():  # ClaimRepository ("select","table","CLMS.POLICY")
def test_java_uses():  # ClaimController uses class:claims-api/MqClaimGateway and ClaimStatusClient
def test_angular_http():  # ClaimService ⊇ ("http","endpoint","GET /api/claims/${id}"), POST /api/claims, DELETE …
def test_angular_route_page():  # page:claims-portal/claims/:id uses component:claims-portal/ClaimDetailsComponent
def test_angular_uses():  # ClaimDetailsComponent uses ClaimService
def test_unresolved_property_reason():  # tmp class with convertAndSend("${mq.nope}") → target_name None, reason "property mq.nope not found"
```

- [ ] **Step 3: Run `python -m pytest tests/test_scan_java_angular.py -v`.** Expected: FAIL.

- [ ] **Step 4: Implement the scanners.** Use regex over comment-stripped source (remove `//…` and `/*…*/` while keeping line numbers). Resolve a variable's string value when it's assigned from a literal, a `@Value` field, or a `static final` constant in the same file.

- [ ] **Step 5: Run the tests again.** Expected: PASS.

- [ ] **Step 6: Commit** with message `feat: Java and Angular scanners`.

---

### Task 7: Resolver part 1: names, config, programs, copybooks, CICS

**Files:**
- Create: `resolve/__init__.py`, `resolve/names.py`, `resolve/programs.py`, `tests/fixtures/claims-estate/architecture-diagrams/archdiag.config.json` (`{"environment_qualifiers": ["PROD","TEST"]}`)
- Test: `tests/test_resolve_programs.py`

**Interfaces:**
- Consumes: `Inventory` (Tasks 1–6), `Config`.
- Produces (`names.py`):
  - `norm_dataset(name: str, env_quals: List[str]) -> Tuple[str, Optional[str]]` returns `(key, dropped_qualifier)`. The key is upper-case with the GDG suffix removed and, if the first qualifier is in `env_quals`, that qualifier removed. For example, `"PROD.CLAIMS.DAILY(+1)"` gives `("CLAIMS.DAILY", "PROD")`.
  - `norm_path(path: str) -> str` turns every `{x}`, `:x` and `${x}` segment into `{}`, strips trailing `/`, and drops scheme/host/port if present.
  - `split_http(target: str) -> Tuple[str, str, Optional[str]]` returns `(METHOD, norm_path, host_or_None)`.
- Produces (`resolve/__init__.py`): `resolve(inv: Inventory, config: Config) -> Resolved`. It calls `programs.resolve_programs(inv, nodes, edges)` and `data.resolve_data(inv, config, nodes, edges)` (Task 8). Both functions append to `nodes: Dict[str, Node]` and `edges: List[Edge]`.
- Rules in `programs.py`:
  - **Program targets** (`runs`, `call`, `link`, `xctl`, `ctg_call`): definitions are `program:` nodes, plus `notanalyzed:` nodes, plus the `zosapi` and transaction `runs` targets.
    - Exactly one definition location gives confirmed.
    - More than one (`len(node.evidence) > 1` for `program:` nodes, where each scanner appends its definition evidence) gives partial, `reason="ambiguous: defined in N places: <path>, <path>"`.
    - A `notanalyzed:X` match gives confirmed to `notanalyzed:X`.
    - No match gives loose to `missing:program:X`.
    - `target_name=None` gives partial to `missing:program:?<srcname>:<line>`, keeping `reason` and `candidates`. If there's exactly one candidate and it's defined, the edge goes to that program instead, still partial.
  - **Copybooks:** a name in the IBM list (Global Constraints) gives no edge. One definition gives confirmed (`op="copy"`). Duplicates give partial ambiguous. None gives loose to `missing:copybook:X`.
  - **Transactions:** `return_transid`/`start` → `transaction:X` gives confirmed, or loose if undefined.
  - **Maps:** `send_map` → `map:X` gives confirmed, or loose.
  - **Utilities:** `runs` → `utility:X`, where the node is created on demand, gives confirmed.

- [ ] **Step 1: Write the failing tests**

```python
def edge(src, op, dst): ...  # helper over resolve(scan(ESTATE)) returning the single matching Edge
def test_norm_dataset():  assert norm_dataset("PROD.CLAIMS.DAILY(+1)", ["PROD","TEST"]) == ("CLAIMS.DAILY","PROD")
                          assert norm_dataset("&&SORTED", []) == ("&&SORTED", None)
def test_norm_path():  assert norm_path("https://h:9443/zos/claims/${id}/status/") == "/zos/claims/{}/status"
def test_runs_confirmed():  assert edge("step:claims-batch/jcl/CLMD100.jcl#STEP020","runs","program:CLMB200").status == "confirmed"
def test_ambiguous_link():  e = edge("program:CLMO100","link","program:CLMO110"); assert e.status == "partial" and e.reason.startswith("ambiguous")
def test_variable_call_single_candidate():  e = edge("program:CLMB200","call","program:CLMB210"); assert e.status == "partial"
def test_xctl_unknown():  e = edge_from("program:CLMO100","xctl"); assert e.status == "partial" and e.dst.startswith("missing:program:?")
def test_not_analyzed_is_confirmed():  assert edge("program:CLMB200","call","notanalyzed:DATEUTIL").status == "confirmed"
def test_missing_program_loose():  assert edge("transaction:CLMU","runs","missing:program:CLMO120").status == "loose"
def test_copybooks():  # CLMB200→copybook:CLMREC confirmed; no edge to DFHAID; CLMO110→missing:copybook:ERRMSG loose
```

- [ ] **Step 2: Run `python -m pytest tests/test_resolve_programs.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement the rules above.**

- [ ] **Step 4: Run the tests again.** Expected: PASS.

- [ ] **Step 5: Commit** with message `feat: resolve program, copybook and CICS links with status`.

---

### Task 8: Resolver part 2: datasets, tables, queues, triggers, REST, transfers

**Files:**
- Create: `resolve/data.py`
- Test: `tests/test_resolve_data.py`

**Interfaces:**
- Produces: `resolve_data(inv, config, nodes, edges) -> None`.
- **Datasets** (spec §7.4):
  - Node id `dataset:<key>` from `norm_dataset`, with `attrs={"names": set of full names seen, "env_dropped": bool}`.
  - The edge is `step → dataset` (op from the Ref). The `cics_file` Ref goes through `cicsfile` `file_dataset` to an edge `program → dataset` with op from `io`.
  - Status: confirmed if the name has no `&`. If the name has `&`, it's partial with the scanner's reason. If a non-environment qualifier was the only difference, that's a different key, so no match is made.
  - Temp datasets (`attrs.temp`) get the node id `dataset:<job id>#&&SORTED`, so they never link across jobs. They never count for loose detection.
  - **DISP=OLD (`update`) is refined by the program:** if the step's program has `attrs["files"][ddname]` equal to `input`, the op becomes `read`. If it's `output` or `extend`, the op becomes `write`. If the program isn't known, the op stays `update`, which counts as both read and write. This ties COBOL `SELECT … ASSIGN TO` back to the JCL DD (spec §7.1).
  - **Loose detection, after all edges are built:** a dataset with writers and no readers gets an extra `Edge(src=dataset, op="loose", dst="missing:reader:<key>", status=LOOSE, reason="written but never read in these repos")`. Readers with no writers get `reason="read but never written in these repos"`. A dataset read by a `transfer` step counts as read.
- **Transfers:** `transfer` → `external:<target_name>` gives partial, `reason="file transfer target is outside these repos"`.
- **Tables:**
  - A qualified name gives an exact `table:` match.
  - If the qualifier is in `env_quals` and the exact match fails, the same name under any schema is tried, and exactly one match gives confirmed.
  - An unqualified name: exactly one table with that name across the DDL gives confirmed. More than one gives partial (`reason="ambiguous: CLMS.POLICY, ARCH.POLICY"`, dst `missing:table:?POLICY`, `candidates` filled). None gives loose to `missing:table:X`.
  - Aliases are followed to their `alias_of` target, which is the edge dst, and stay confirmed.
- **Queues:**
  - Alias queues are followed to their target, and the edge dst is the target `queue:`.
  - A queue with both `put` and `get`, or `put` plus a trigger or bridge, gives confirmed edges.
  - A trigger gives `Edge(queue, "triggers", transaction:<applicid>, confirmed)`. A bridge gives `Edge(queue, "triggers", transaction:<applicid>, confirmed)` with `reason="CICS-MQ bridge"`.
  - A queue used on only one side with no MQSC definition: the edge stays confirmed (the use is certain), and an extra `Edge(queue, "partial", "missing:queue-consumer:<Q>", PARTIAL, reason="how this queue reaches CICS isn't in these repos")` is added. For get-only, the reason is `"nothing in these repos puts to this queue"`.
- **REST:**
  - `http` targets are matched by `(METHOD, norm_path)` against `endpoint:` nodes, then `zosapi:` nodes. Hosts are ignored when the path matches an endpoint uniquely.
  - Exactly one match gives confirmed.
  - No match with an absolute host gives loose to `external:<host>` with `reason="external or missing service"`. No match without a host gives loose to `missing:endpoint:<METHOD> <path>`.
- **Uses:** `uses` Refs give confirmed edges inside the repo.
- Produces: `repo_links(resolved) -> List[Tuple[str, str, str, List[Edge]]]` returns `(repo_a, repo_b, via_label, edges)` for every shared resource or direct edge whose ends are in different repos. The resource's repo is the repo of its definition (a DDL table belongs to claims-db, a copybook to shared-copybooks). Datasets and queues without definitions belong to no repo and link every repo that touches them.

- [ ] **Step 1: Write the failing tests**

```python
def test_disp_old_refined_by_open_mode():  assert edge_from("step:claims-batch/jcl/CLMD100.jcl#STEP020","read").dst.endswith("#&&SORTED")
def test_dataset_cross_repo_via_csd():  assert edge("program:CLMO100","read","dataset:CLM.MASTER.KSDS").status == "confirmed"
def test_env_copies_share_dataset_key():  # both CLMD100.jcl copies write dataset:CLAIMS.DAILY; node attrs names == {"PROD.CLAIMS.DAILY","TEST.CLAIMS.DAILY"}
def test_without_env_config_keys_differ():  # resolve with Config() → dataset:PROD.CLAIMS.DAILY and dataset:TEST.CLAIMS.DAILY both exist
def test_loose_written_never_read():  assert edge("dataset:CLAIMS.AUDIT","loose","missing:reader:CLAIMS.AUDIT").status == "loose"
def test_loose_read_never_written():  # dataset:PAYMENT.FEED has loose edge reason "read but never written in these repos"
def test_transfer_partial():  assert edge("step:claims-batch/jcl/CLMD100.jcl#STEP050","transfer","external:NDM:FINANCE").status == "partial"
def test_extract_not_loose():  # dataset:CLAIMS.EXTRACT has no loose edge (read by STEP050)
def test_unresolved_symbol_partial():  # STEP S2 write edge status partial, reason mentions &UNDEF
def test_table_rules():  # CLMB200 select CLMS.CLAIM confirmed; CLMO100 POLICY → missing:table:?POLICY partial; CLMO100 CLMS.CLM → table:CLMS.CLAIM confirmed
def test_queue_alias_and_trigger():  # MqClaimGateway put queue:CLM.REQ.LQ confirmed; CLMO100 get same; queue:CLM.REQ.LQ triggers transaction:CLMI confirmed
def test_queue_one_sided_partial():  # queue:CLM.AUDIT has partial edge reason "how this queue reaches CICS isn't in these repos"
def test_rest():  # ClaimService http endpoint:GET /api/claims/{} confirmed; DELETE → missing:endpoint:DELETE /api/claims/{} loose;
                  # ClaimStatusClient → zosapi:GET /zos/claims/{}/status confirmed; RatesClient → external:rates.example.com loose
def test_repo_links():  # contains ("claims-api","claims-online","queue CLM.REQ.LQ", …) and ("claims-batch","claims-db","table CLMS.CLAIM", …)
```

- [ ] **Step 2: Run `python -m pytest tests/test_resolve_data.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement the rules above.**

- [ ] **Step 4: Run the tests again.** Expected: PASS.

- [ ] **Step 5: Commit** with message `feat: resolve dataset, table, queue, trigger and REST links`.

---

### Task 9: The release gate: no missed links, no unexpected solid links

**Files:**
- Create: `tests/fixtures/expected_links.json`, `tests/test_gate.py`

**Interfaces:**
- Consumes: `scan_workspace`, `resolve`, `load_config` on `tests/fixtures/claims-estate`.

- [ ] **Step 1: Write `expected_links.json`.** It's a list of `{"src", "op", "dst", "status"}`, with one entry for **every** edge the resolver should produce from the fixture, all `uses` edges included. Build the list by hand from the fixture descriptions in Tasks 3–8, **not** by dumping the resolver's output. At minimum it holds every edge named in the Task 7 and 8 tests, plus:
  - Every `runs` edge.
  - Every dataset read/write for CLMD100 in both environment copies.
  - The CLMD300 `RUN` and `S2` steps.
  - The CLM.RSP put and get.
  - `transaction:CLMI runs program:CLMO100`.
  - `zosapi:GET /zos/claims/{}/status runs program:CLMO130`.
  - The CLM.BRIDGE.Q trigger.
  - All copy edges.

- [ ] **Step 2: Write the gate tests**

```python
def test_no_missed_links():
    missing = expected - actual_set(); assert not missing, f"missed links: {sorted(missing)}"
def test_no_unexpected_confirmed_links():
    extra = {e for e in actual_set() if e[3] == "confirmed"} - expected; assert not extra, f"unexpected solid links: {sorted(extra)}"
def test_status_matches():
    # for every (src, op, dst) present in both, the status must be equal
```

- [ ] **Step 3: Run `python -m pytest tests/test_gate.py -v`.** Expected: PASS. If anything fails, fix the scanner or resolver, never the expected list, unless the expected entry contradicts the spec, in which case say why in the commit message.

- [ ] **Step 4: Commit** with message `test: release gate over the claims fixture estate`.

---

### Task 10: Groups, summary and listing for Copilot

**Files:**
- Create: `groups.py`, `summary.py`
- Test: `tests/test_groups_summary.py`

**Interfaces:**
- Produces (`groups.py`):
  ```python
  @dataclass class App: name: str; kind: str = "application"; members: List[str] = []   # kind: application|datastore|external
  @dataclass class Groups: apps: List[App]; suggested_links: List[Dict[str, str]]      # {"from","to","note"}
  def default_groups(r: Resolved) -> Groups        # one App per repo, named after the repo; a repo with only DDL gets kind "datastore"
  def load_groups(path: Path, r: Resolved) -> Groups   # missing file → default_groups; unknown selectors are reported, not fatal
  def app_of(groups: Groups, r: Resolved, node_id: str) -> Optional[str]
  ```
  Selectors in `members`:
  - `repo:<name>`.
  - `<kind>:<NAME>`, with `*` glob allowed (`program:CLMO*`).
  - `path:<repo>/<glob>`.
  
  The first matching app wins, in list order. A node that matches nothing falls back to its repo's default app. A resource node (dataset or queue without a repo) gets `None`, so it's drawn as a shared resource.
  
  Suggested links become `Edge(op="suggested", status=PARTIAL, reason="suggested by Copilot: <note>")`. The `from`/`to` value can be any node id or app name. These are added only at view time, never written into `links.json`.
- Produces (`summary.py`):
  - `build_summary(r: Resolved, g: Groups, cfg: Config) -> str`: Markdown of at most about 120 lines. It covers the repos with counts per node kind, the current apps and their member counts, and environment-qualifier candidates. A candidate is a first qualifier that is the only difference between two or more dataset or table names, listed with 2 examples each, and only when it isn't already in the config. It also gives the counts of confirmed, partial and loose edges, the top 10 loose and partial edges with reasons, and `languages_not_analyzed`.
  - `list_items(r, g, what: str) -> List[str]` for `what` in `jobs, transactions, pages, endpoints, applications, repos, programs`.

- [ ] **Step 1: Write the failing tests**

```python
def test_default_groups_one_per_repo():  # 6 apps; "claims-db" kind == "datastore"
def test_selector_precedence(tmp_path):  # groups.json: [{"name":"Claims Online","members":["program:CLMO1*","transaction:CLMI"]}] → app_of("program:CLMO100") == "Claims Online"; app_of("program:CLMB200") == "claims-batch"
def test_suggested_link_is_partial():  # suggested {"from":"dataset:CLAIMS.EXTRACT","to":"external:NDM:FINANCE","note":"x"} → status partial, reason "suggested by Copilot: x"
def test_summary_env_candidates():  # resolve with Config() → summary contains "TEST" and "PROD" as candidates
def test_summary_size():  assert len(build_summary(...).splitlines()) <= 120
def test_list_jobs():  assert "CLMD100 (claims-batch/jcl/CLMD100.jcl)" in list_items(r, g, "jobs")
```

- [ ] **Step 2: Run `python -m pytest tests/test_groups_summary.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests again.** Expected: PASS.

- [ ] **Step 5: Commit** with message `feat: application groups, summary and listing for Copilot`.

---

### Task 11: Views for the four levels

**Files:**
- Modify: `views.py`
- Test: `tests/test_views.py`

**Interfaces:**
- Consumes: `Resolved`, `Groups`, `repo_links`, `MAX_NODES`.
- Produces: `build_view(r: Resolved, g: Groups, level: str, scope: Optional[str]) -> ViewGraph`, with `level` in `landscape, application, flow_job, flow_tx, repomap`. A bad scope raises `ScopeError(message, suggestions: List[str])`, with suggestions from `difflib.get_close_matches` over `list_items`.
  - **landscape:**
    - One VNode per app (`kind` = app kind), and one per resource touched by 2 or more apps (dataset, table outside a datastore app, or queue).
    - One VNode per `external:`, and one per `missing:` loose target that's reached from 2 or more apps or that crosses apps. Other loose ends attach as `missing` nodes on their app.
    - Edges are combined per `(src_app_or_resource, dst, op family)`. The label is the op family plus up to 2 names, e.g. `"SQL · CLAIM, POLICY"`.
    - Status of a combined edge: confirmed if any underlying edge is confirmed; otherwise partial if any is partial; otherwise loose. `VEdge.evidence` gathers all of it.
    - Copy edges give `kind="shared_code"`, labeled `"COPY ×N"`.
  - **application:** the app's member nodes, plus each neighbor outside the app as a VNode with `kind="neighbor"` (drawn grey).
  - **flow_job:** scope is a job name, or a job id when there are several copies. Steps are the lane, in order, labeled with the program or utility. Reads go `above` and writes go `below`. A dataset that's both written and read by later steps is `below`. Step-to-step edges are labeled with the cond (`"if RC = 0"` for `COND=(0,NE)`). Environment copies: when the name matches more than one job, the first by path is drawn and `notes` gets `"Also exists as: <paths>"`.
  - **flow_tx:** scope is a transaction id, a page route or an endpoint. The view is a BFS along runtime edges (`uses, http, put, triggers, runs, link, xctl, call, select…, get, send_map`) to depth 8. `get` is followed backwards from the queue. 3270 maps attached to the transaction's programs are included. Edges are numbered in BFS order (`number`).
  - **repomap:** scope is optional (a repo name means only links touching it). One VNode per repo (`kind="repo"`). `detail_lines` lists the files holding evidence for cross-repo links (highlighted first, then up to 3 other notable files and `"… N more"`). One VEdge per `repo_links` entry, labeled `via_label`. Loose cross-repo targets become `missing` VNodes.
- **Cap:** if more than `MAX_NODES` nodes remain, the lowest-degree nodes are folded per `(group, kind)` into `VNode(id=f"more:{group}:{kind}", label=f"… {n} more {kind}s")`, keeping every node with a cross-app edge or a non-confirmed status. Then `notes` gets `"Too big for one picture: try level application with scope <biggest app>"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_landscape_shape():  # default groups: the 6 repo apps; shared resource nodes include dataset:CLM.MASTER.KSDS (claims-batch + claims-online)
                             # and queue:CLM.REQ.LQ (claims-api + claims-online); an edge claims-api → queue:CLM.REQ.LQ exists
def test_flow_job_rows():  v = build_view(r,g,"flow_job","CLMD100"); lane = [n.label for n in v.nodes if n.row=="lane"]
                           assert lane == ["SORT","CLMB200","CLMB300","IEBGENER","DMBATCH"]
                           assert "Also exists as: claims-batch/jcl/test/CLMD100.jcl" in v.notes
def test_flow_tx_from_page():  v = build_view(r,g,"flow_tx","claims/:id"); ids = {n.id for n in v.nodes}
                               assert {"queue:CLM.REQ.LQ","transaction:CLMI","program:CLMO100","table:CLMS.CLAIM"} <= ids
def test_repomap_has_evidence_files():  v = build_view(r,g,"repomap",None); card = node(v,"repo:claims-api")
                                        assert "MqClaimGateway.java" in " ".join(card.detail_lines)
def test_status_combination():  # landscape edge claims-online→claims-online? use synthetic Resolved: confirmed+partial → confirmed; partial+loose → partial
def test_scope_error_suggests():  with pytest.raises(ScopeError) as e: build_view(r,g,"flow_job","CLMD10")
                                  assert "CLMD100" in e.value.suggestions
def test_cap():  # synthetic Resolved with 200 programs in one app → len(v.nodes) <= 40 and a "more:" node exists and notes mention "Too big"
```

- [ ] **Step 2: Run `python -m pytest tests/test_views.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests again.** Expected: PASS.

- [ ] **Step 5: Commit** with message `feat: views for landscape, application, flows and repo map`.

---

### Task 12: Shared SVG helpers + Style A (pictorial, with .drawio)

**Files:**
- Create: `render/__init__.py`, `render/common.py`, `render/style_a.py`
- Test: `tests/test_render_common.py`, `tests/test_style_a.py`
- Modify: `tests/conftest.py`: add `fixture_view(level, scope) -> ViewGraph` (scan, resolve and build over ESTATE, cached per session) and `assert_office_safe(svg: str)` (the tag and URL checks below), both reused by Tasks 13–16

**Interfaces:**
- Produces (`common.py`):
  - `esc(s: str) -> str`: XML escaping, covering `& < > " '`.
  - `text_width(s, size) -> float`: `0.6 * size * len(s)`, or `0.55` for monospace.
  - `wrap(s, max_px, size) -> List[str]`.
  - `arrowhead(p_from, p_to, color) -> str`: a polygon string.
  - `line_attrs(status: str, kind: str) -> str`: returns the exact stroke attributes from Global Constraints.
  - `loose_dot(x, y) -> str`.
  - `legend(x, y, statuses_present: Set[str]) -> Tuple[str, float]`: SVG fragment and its height. Only the line types present are listed.
  - `svg_doc(w, h, body, bg="#ffffff") -> str`: includes the `xmlns` and a `<title>`.
  - `notes_block(notes, x, y) -> str`.
  - `REPO_COLORS`: the 8 colors from the samples (`#3b82f6 #16a34a #9333ea #ca8a04 #ea580c #0891b2 #db2777 #4f46e5`), assigned to groups in order.
  - `ICONS: Dict[str, Callable[[float, float, str], str]]`, keyed by VNode kind: `person, page, component, class, endpoint, program, utility, job, step, dataset, gdg, vsam, table, queue, transaction, map, cicsfile, external, notanalyzed, repo, application, datastore, neighbor`. Each is drawn inline from the shapes in `docs/samples/mainframe-samples.html` diagram 2 and `style-options.html` option A, with the `<use>`/`<defs>` symbols copied inline.
- Produces (`style_a.py`): `render(view: ViewGraph) -> Dict[str, str]` returns `{"svg": …, "drawio": …}`.
  - It calls `layout_for(view, node_size)` itself, with `node_size` = icon area plus wrapped label, minimum `(120, 110)`.
  - Groups are drawn as dashed rounded rectangles in the group color at 8% fill, titled `repo: <label>` (or the app name).
  - Numbered edges show the circled digit (`①`…`⑳`, then `(21)`) before the label.
  - Notes go at the bottom.
  - `drawio` is an uncompressed `<mxfile><diagram><mxGraphModel>…` with one `mxCell vertex` per node (style per kind: `shape=cylinder3` for table/dataset, `shape=mxgraph.basic.person`… or plain rounded rect, `fillColor` group color), one container cell per group, and edges with `dashed=1;dashPattern=3 4;strokeColor=#d97706` for partial, `strokeColor=#dc2626` for loose. Geometry comes from the same Layout.

- [ ] **Step 1: Write the failing tests**

```python
def test_esc():  assert esc('&&SORTED <x> "q"') == "&amp;&amp;SORTED &lt;x&gt; &quot;q&quot;"
def test_line_attrs():  assert 'stroke-dasharray="3 4"' in line_attrs("partial","runtime") and "#d97706" in line_attrs("partial","runtime")
def test_svg_is_office_safe_and_parses():
    out = style_a.render(fixture_view("flow_job","CLMD100"))
    root = ET.fromstring(out["svg"]); tags = {el.tag.split('}')[-1] for el in root.iter()}
    assert not tags & {"filter","style","use","marker","foreignObject","image"}
    assert "http://" not in out["svg"].replace("http://www.w3.org","") and "https://" not in out["svg"]
def test_special_names_escaped():  # synthetic view with node label "&&SORTED" and "CLM#01" → svg and drawio both parse
def test_every_node_and_label_present():  # each VNode.label appears in svg text; each edge with label appears
def test_drawio_parses_and_has_cells():  # ET.fromstring(drawio); count of vertex cells == len(view.nodes) + len(view.groups)
def test_legend_lists_only_present_statuses():  # flow_job CLMD100 has partial + loose + confirmed → 3 legend entries; no "shared code"
def test_writes_samples_for_eyeballing(tmp_path):  # writes landscape/flow_job/flow_tx/repomap SVGs to tests/out/ (gitignored)
```

- [ ] **Step 2: Run `python -m pytest tests/test_render_common.py tests/test_style_a.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests and compare by eye.** Run the tests again. Expected: PASS. Open `tests/out/style_a-flow_job-CLMD100.svg` beside diagram 2 in `docs/samples/mainframe-samples.html` and fix any clear readability gaps.

- [ ] **Step 5: Commit** with message `feat: pictorial style A with draw.io export`. Add `tests/out/` to `.gitignore`.

---

### Task 13: Style B (C4 boxes, with Mermaid)

**Files:**
- Create: `render/style_b.py`
- Test: `tests/test_style_b.py`

**Interfaces:**
- Consumes: `common.*`, `layout_for`.
- Produces: `render(view) -> Dict[str, str]` returns `{"svg": …, "md": …}`.
  - SVG: solid boxes `#1168bd` (person `#08427b`, external `#999999`, queue `#438dd5`, notanalyzed `#cbd5e1` with dark text). Each box has 3 text lines: name in bold, `[<Kind>: <tech>]`, and a description from `sublabel`. Tables and datasets are drawn as cylinders. Group boundaries are grey dashed with `"<label> [repo]"` bottom-left. Edge labels are a sentence plus the `[tech]` second line, as in sample B.
  - `md`: a `# <title>` heading, then a fenced `mermaid` block with `flowchart LR`, one `subgraph` per group, node ids sanitized to `n<index>`, labels in `["…"]` with `#quot;` escaping, `-->` for confirmed, `-.->` for partial, and `--x` plus `linkStyle <i> stroke:#dc2626` for loose. `classDef` sets the colors. Then a Markdown legend under it.

- [ ] **Step 1: Write the failing tests**

```python
def test_svg_office_safe():  # same tag/URL checks as Task 12, reuse helper assert_office_safe(svg)
def test_mermaid_structure():  md = style_b.render(fixture_view("landscape",None))["md"]
                               assert "```mermaid\nflowchart LR" in md and md.count("subgraph") == len(view.groups)
                               assert "-.->" in md and "--x" in md
def test_mermaid_escapes_quotes_and_ids():  # label 'say "hi"' → '#quot;'; no raw node ids with ':' or '/'
def test_cylinders_for_tables():  # svg contains an <ellipse> for each table/dataset node
```

- [ ] **Step 2: Run `python -m pytest tests/test_style_b.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests again** and compare by eye with sample B and mainframe diagram 1. Expected: PASS.

- [ ] **Step 5: Commit** with message `feat: C4-style B with Mermaid export`.

---

### Task 14: Style C (repo link map, with offline HTML)

**Files:**
- Create: `render/style_c.py`
- Test: `tests/test_style_c.py`

**Interfaces:**
- Produces: `render(view) -> Dict[str, str]` returns `{"svg": …, "html": …}`.
  - SVG: cards are a white rounded rect with a `#cbd5e1` border. The shadow is a second rect offset 2px at `#0f172a` 8% opacity, not a filter. The colored header shows `⎇ <repo>` and the languages, right-aligned. `detail_lines` are in monospace, with highlighted rows for evidence files. Edge labels are pills (dark for runtime, amber text for shared code). Loose and partial stubs use the sample styles, and an evidence strip at the bottom holds up to 6 lines in the form `<via>  <file>:<line> ↔ <file>:<line>`.
  - HTML: a full document with the SVG inline, plus a side panel. Each edge `<g>` gets `data-edge="<i>"`, and clicking it shows a table of all evidence for that edge (repo, path, line, code text). It also has a search box to filter edges by name, and shows the legend. CSS and JS are inline; there's no external URL.

- [ ] **Step 1: Write the failing tests**

```python
def test_svg_office_safe():  assert_office_safe(style_c.render(v)["svg"])
def test_html_offline():  html = ...["html"]; assert "<script" in html and "src=" not in html and "https://" not in html.replace("http://www.w3.org","")
def test_html_has_every_evidence():  # for each VEdge, every evidence "path:line" string appears in the html data
def test_evidence_strip():  # svg contains "MqClaimGateway.java:" and "CLMO100.cbl:"
```

- [ ] **Step 2: Run `python -m pytest tests/test_style_c.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests again** and compare by eye with mainframe diagram 4. Expected: PASS.

- [ ] **Step 5: Commit** with message `feat: repo link map style C with offline HTML`.

---

### Task 15: Style D (whiteboard, with Excalidraw)

**Files:**
- Create: `render/style_d.py`
- Test: `tests/test_style_d.py`

**Interfaces:**
- Produces: `render(view, seed: int = 7) -> Dict[str, str]` returns `{"svg": …, "excalidraw": …}`.
  - SVG: background `#fffdf7`. Every rect, ellipse and line is drawn as a path whose points are jittered ±2px by `random.Random(seed)`, with each rect edge split into segments of about 30px, and stroke `#1e1e1e` 2.2px. Fills are pastel per group (`#a5d8ff #b2f2bb #d0bfff #ffd8a8 #ffec99 #fcc2d7`) at 0.5 opacity. People are stick figures and queues are pipes, as in sample 3. Notes and partial reasons are yellow sticky notes (`#ffec99`), rotated ±3°. Font: `Segoe Print, Comic Sans MS, cursive`.
  - `excalidraw`: JSON `{"type":"excalidraw","version":2,"source":"archdiag","elements":[…],"appState":{"viewBackgroundColor":"#fffdf7"}}`. It has rectangles, ellipses, arrows (with `startBinding`/`endBinding`) and text elements, all with `roughness: 1` and `fontFamily: 1`. Arrows use `strokeStyle "dotted"` for partial, and `"#e03131"` stroke for loose.
- Determinism: the same view and seed give byte-identical output.

- [ ] **Step 1: Write the failing tests**

```python
def test_office_safe_no_filter():  assert_office_safe(style_d.render(v)["svg"])
def test_deterministic():  assert style_d.render(v)["svg"] == style_d.render(v)["svg"]
def test_jitter_present():  # rendering the same rect twice with seeds 1 and 2 gives different path d strings
def test_excalidraw_valid():  j = json.loads(...["excalidraw"]); assert j["type"] == "excalidraw"
                              assert {e["type"] for e in j["elements"]} >= {"rectangle","arrow","text"}
                              # every arrow binding id refers to an existing element id
```

- [ ] **Step 2: Run `python -m pytest tests/test_style_d.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests again** and compare by eye with mainframe diagram 3. Expected: PASS.

- [ ] **Step 5: Commit** with message `feat: whiteboard style D with Excalidraw export`.

---

### Task 16: Links report

**Files:**
- Create: `render/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Produces: `links_report(view: ViewGraph, r: Resolved) -> str`, which returns Markdown with these sections in order:
  1. `# Links: <title>`, then a one-line count: `N confirmed · N partly known · N loose ends`.
  2. `## Links on this diagram`: a table with columns `From | Link | To | Status | Evidence (from) | Evidence (to)`. Every underlying `Edge` in every VEdge is listed, as `repo/path:line`.
  3. `## Loose ends`: each loose edge with its reason and evidence.
  4. `## Partly known`: each partial edge with its reason and any `candidates`.
  5. `## Possibly missing repos`: names that appear as `missing:` or `external:` targets 2 or more times, grouped by first qualifier or prefix (for example `FIN.*`, `NDM:FINANCE`), each with the line "may live in a repo that wasn't scanned".
  6. `## Not analyzed`: from `languages_not_analyzed`, as `"<n> <language> files: program names registered, contents not analyzed"`.
  7. `## Notes`: `view.notes`.

- [ ] **Step 1: Write the failing tests**

```python
def test_sections_in_order():  # headings appear in the order above
def test_every_edge_listed():  # for flow_job CLMD100, every underlying Edge evidence path:line appears
def test_partial_shows_candidates():  # report for flow_tx CLMI contains "CLMO110" ambiguity reason with both paths
def test_not_analyzed():  assert "1 asm files: program names registered, contents not analyzed" in report
```

- [ ] **Step 2: Run `python -m pytest tests/test_report.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests again.** Expected: PASS.

- [ ] **Step 5: Commit** with message `feat: links report`.

---

### Task 17: CLI: draw, caching, errors, performance

**Files:**
- Modify: `cli.py`
- Create: `tests/test_cli.py`, `tests/test_perf.py` (marked `@pytest.mark.slow`, and included in the default run)

**Interfaces:**
- Produces these commands (all take `--workspace PATH`, default the current directory):
  - `scan`: writes `inventory.json` and `links.json` and prints the counts.
  - `summary`: prints `build_summary`, and writes `summary.md`.
  - `list --what jobs|transactions|pages|endpoints|applications|repos|programs`.
  - `draw --level landscape|application|flow|repomap [--scope S] [--style a|b|c|d|all]`. The style defaults to the level's default (landscape b, application a, flow a, repomap c). `flow` becomes `flow_job` when the scope is a job, and `flow_tx` otherwise.
  - `init-config`: writes `archdiag.config.json` with `environment_qualifiers` filled from the summary candidates, for Copilot or the user to confirm.
- **Staleness:** `draw`, `summary` and `list` recompute the `fingerprint`. If it differs from the inventory's, they rescan first and print `"Repos changed since last scan; rescanned."`. `scan` always rescans.
- **Outputs:** `architecture-diagrams/<level>[-<scope-slug>]-<style>.{svg,drawio|md|html|excalidraw}` and `<level>[-<scope-slug>]-links.md`. The slug is lower-case, with characters outside `[a-z0-9._-]` turned into `-`.
- **Stdout** of `draw` ends with a block that Copilot relays to the user:
  ```
  Wrote:
    <paths, one per line>
  Summary: <N nodes>, <N links>: <n> confirmed, <n> partly known, <n> loose ends
  Top issues:
    - <up to 3 loose/partial edges with reason>
  ```
- **Exit codes:** `0` ok. `2` bad scope or level, printing `Did you mean: …` and the `list` command to run. `3` no repos found, printing `No git repos found under <path>. Clone the repos into one folder and run again.` `1` an unexpected error, printing one line plus the path of `architecture-diagrams/error.log` with the traceback.

- [ ] **Step 1: Write the failing tests**

```python
def test_draw_all_styles_on_fixture(tmp_path):  # copytree ESTATE → tmp; main(["draw","--workspace",w,"--level","flow","--scope","CLMD100","--style","all"]) == 0
                                                 # files: flow-clmd100-{a,b,c,d}.* and flow-clmd100-links.md exist
def test_rescan_on_change(tmp_path, capsys):  # draw once, touch a .cbl, draw again → "rescanned" in output
def test_bad_scope(tmp_path, capsys):  assert main([... "--scope","CLMD10"]) == 2 and "Did you mean: CLMD100" in capsys.readouterr().out
def test_no_repos(tmp_path, capsys):  assert main(["scan","--workspace",str(tmp_path)]) == 3
def test_unexpected_error_logged(tmp_path, monkeypatch):  # monkeypatch resolve to raise → exit 1, error.log exists, no traceback on stdout
def test_path_with_spaces(tmp_path):  # workspace "client repos/" works end to end
def test_init_config(tmp_path):  # after scan without config, init-config writes environment_qualifiers containing "PROD" and "TEST"
# test_perf.py
def test_large_estate_under_120s(tmp_path):  # generate 50 repos × 60 files (30 cbl, 20 jcl, 10 java) with cross refs; scan+resolve+draw landscape < 120 s; drawn nodes <= 40
```

- [ ] **Step 2: Run `python -m pytest tests/test_cli.py tests/test_perf.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement.** If the performance test fails, profile with `cProfile` before changing the design. The usual causes are regexes recompiled per line and quadratic matching. Fix them with name indexes built once.

- [ ] **Step 4: Run the full suite** with `python -m pytest -v`. Expected: all PASS.

- [ ] **Step 5: Commit** with message `feat: CLI draw, caching, errors and performance`.

---

### Task 18: The skill itself: SKILL.md, references, README, installer

**Files:**
- Create: `skill/architecture-diagrams/SKILL.md`, `reference/levels-and-styles.md`, `reference/groups-format.md`, `README.md`, `install.ps1`, `.vscode/tasks.json` template inside `skill/architecture-diagrams/assets/`
- Test: `tests/test_skill_package.py`

- [ ] **Step 1: Confirm the Copilot skill format.** Use GitHub's current documentation to check four things for both VS Code agent mode and Copilot CLI: the personal and project skill folder locations, the required `SKILL.md` front-matter fields, the name and description limits, and how a skill runs scripts in its folder (including the path the agent should use). Write the findings with source URLs into `docs/copilot-skill-format.md`. **If VS Code and the CLI differ in a way one folder can't serve, stop and tell the user.**

- [ ] **Step 2: Write the failing tests**

```python
def test_frontmatter():  # SKILL.md starts with '---', has name "architecture-diagrams" and a description <= the confirmed limit
def test_skill_mentions_every_command():  # SKILL.md references scan, summary, list, draw, init-config and the groups.json file
def test_skill_forbids_inventing_links():  assert "never add links" in skill_text.lower()
def test_package_is_self_contained():  # every file referenced from SKILL.md/README exists inside skill/architecture-diagrams/
def test_install_ps1_targets_confirmed_paths():  # install.ps1 contains the personal skill path from docs/copilot-skill-format.md
```

- [ ] **Step 3: Run `python -m pytest tests/test_skill_package.py -v`.** Expected: FAIL.

- [ ] **Step 4: Write `SKILL.md`.** Use the confirmed front-matter. The description must fire on requests like "architecture diagram", "draw the landscape", "show batch job X", "repo link map", "what depends on this repo". The body says, in order:
  1. Find the workspace (the folder holding the cloned repos) and run `python <skill>/scripts/run.py scan --workspace <ws>`. If running commands is blocked, ask the user to run that command (or the VS Code task from `assets/tasks.json`) and paste the output.
  2. Run `summary`. If it lists environment-qualifier candidates and no config exists, ask the user once whether they're environment names, then run `init-config`.
  3. On first use, propose application groups from the summary, write `groups.json` in the format in `reference/groups-format.md`, and show the user the names. **Never add links.** Anything Copilot believes is connected goes in `suggested_links`, which are drawn as dotted lines.
  4. Map the request to level, scope and style using `reference/levels-and-styles.md`. Use `list` to find scope names. If the scope is unclear, ask.
  5. Run `draw`, then relay the stdout block: file paths, the summary line and the top issues. Offer the links report.
  6. If a diagram notes it's too big, suggest the zoom level named in the note.
  
  Also write `levels-and-styles.md` (the level table and defaults from spec §5, and the example phrases from spec §9), `groups-format.md` (the selectors and `suggested_links` from Task 10, plus the config fields), the client `README.md` (prerequisites: Python 3.9+, VS Code, Copilot; installing; cloning repos into one folder; the fallback route for blocked commands; the privacy note from spec §10; what solid, dotted and red lines mean, and the first-run calibration step from spec §11: a client mainframe developer checks the links report for a sample of jobs and transactions before anyone relies on the diagrams), and `install.ps1` (copies the folder to the personal skills path; `-Project <repo>` copies to the project path; it checks for `python --version` >= 3.9 and prints how to fix it).

- [ ] **Step 5: Run the tests again.** Expected: PASS.

- [ ] **Step 6: Commit** with message `feat: Copilot skill instructions, references, README and installer`.

---

### Task 19: Acceptance on Windows, offline, with Copilot

**Files:**
- Create: `docs/acceptance.md` (the checklist below, with results filled in)

- [ ] **Step 1: Run the Python 3.9 suite.** On a Windows machine (or a Windows CI runner) with Python 3.9 and the network disabled, run `python -m pytest -v`. Expected: all PASS.
- [ ] **Step 2: Install and run in VS Code.** Run `install.ps1` and open `tests/fixtures/claims-estate` in VS Code. In Copilot agent mode, ask the five example requests from spec §9. Record for each: whether the skill fired, the commands Copilot ran, the files written, and the stdout block relayed.
- [ ] **Step 3: Repeat in Copilot CLI** with the same five requests.
- [ ] **Step 4: Open the outputs in other tools.** Open one SVG of each style in Edge, VS Code, Word and PowerPoint (Insert → Pictures). Open the `.drawio` in draw.io desktop or the VS Code extension, the `.md` Mermaid in a GitHub preview, the `.excalidraw` at excalidraw.com or in the VS Code extension (it's offline after load), and the HTML in Edge with the network off. Record anything that renders wrong.
- [ ] **Step 5: Test the fallback route.** Block terminal commands in Copilot settings, then confirm that the fallback route in the README works.
- [ ] **Step 6: Compare against the samples.** Put each style's fixture output side by side with `docs/samples/mainframe-samples.html` and note readability gaps. Fix them, or list them as known issues.
- [ ] **Step 7: Commit** `docs/acceptance.md` with message `docs: acceptance results for Windows, offline and Copilot`.
