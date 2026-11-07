---
name: architecture-diagrams
description: Draws architecture diagrams (SVG, plus draw.io, Mermaid, HTML or Excalidraw and a links report) of mainframe COBOL, JCL, CICS, DB2, MQ, Java and Angular repos, from a scan of the code with file-and-line evidence for every link. Use when the user asks for an architecture diagram, to draw the landscape, to show a batch job or online transaction end to end, for an application diagram, a repo link map, what depends on this repo or what breaks if it changes, a whiteboard or C4 picture of their repos, or a gitdiagram (a diagram of one repo, how a repo is put together, its structure).
---

# Architecture diagrams

Python scripts in this skill scan the user's repos, match both ends of every link, and
draw the diagrams. Your job is to run the right commands, ask the user what only they can
answer, and pass on what the scripts report. **Never draw, edit or guess a diagram or a
link yourself.** People plan modernization around these pictures, and a missing or
made-up link is the worst failure.

**Never edit, create or delete files in the user's repos.** The skill only reads them.
Only write inside `<ws>/architecture-diagrams/`, and there only `groups.json`,
`archdiag.config.json` and `gitdiagram-<repo>.json`. The scripts write everything else.
The one exception is `<ws>/.vscode/tasks.json` (see below). Only when the user asks you to,
copy `assets/tasks.json` there, and never overwrite a `tasks.json` that already exists
(show them the entries to merge instead). Otherwise just tell them how to copy it.

## Paths and how to run a command

- `<skill>` is the folder holding this `SKILL.md`: the path you read this file from.
  Installed copies are at `%USERPROFILE%\.copilot\skills\architecture-diagrams` (personal)
  or `<ws>\.github\skills\architecture-diagrams` (project, in the folder holding the clones). In Copilot CLI,
  `/skills info architecture-diagrams` shows it.
- `<ws>`, the workspace, is the folder that holds the cloned repos. Usually it is the open
  VS Code folder or the CLI's current folder. If that folder is itself a git repo, it is
  scanned as one repo. If you can't tell which folder the user means, ask.
- Every command has this form. Quote both paths, since Windows paths often have spaces:

  `python "<skill>/scripts/run.py" <command> --workspace "<ws>"`

  If `python` is not found, use `py -3` instead of `python`. Python 3.9 or newer is
  needed. Nothing is installed, and nothing goes over the network.
- Output goes to `<ws>/architecture-diagrams/`. Exit codes: `0` ok. `1` error: say what it
  printed and point to `architecture-diagrams/error.log`. `2` bad level, style or scope:
  it prints `Did you mean: ...`, so offer those names. `3` no repos found: tell the user
  to clone the repos into one folder and give you that folder.

**If you can't run commands** (blocked by policy, or the user declines the terminal
approval), give the user the exact command to run in a terminal. Or, in VS Code, they can
copy `assets/tasks.json` into `<ws>/.vscode/tasks.json` themselves (you do not create it
unless they ask) and run *Terminal > Run Task >
Architecture diagrams: ...*. Ask them to paste the output back, then carry on from it.
You can also read `<ws>/architecture-diagrams/summary.md` and the `*-links.md` reports
yourself.

## Steps

### 1. Scan

On first use in a workspace (no `<ws>/architecture-diagrams/inventory.json` yet), or when
the user asks to rescan, run:

`python "<skill>/scripts/run.py" scan --workspace "<ws>"`

Later commands reuse the scan and rescan by themselves if the repos changed. They say
`Repos changed since last scan; rescanned.` when they do. If it prints a `WARNING:` line
about files that could not be analyzed, tell the user. Links involving those files may be
missing.

**First use at a client:** tell the user once that before anyone relies on the diagrams,
one of their mainframe developers should do the **calibration step**. That means checking
the links report for a sample of jobs and transactions against the code, and reporting
any missed or wrong link (see the README).

### 2. Read the summary, and settle environment names once

`python "<skill>/scripts/run.py" summary --workspace "<ws>"`

This prints repos, applications, top loose and partly known links, languages not analyzed,
and **Environment qualifier candidates**, pairs such as `TEST ~ PROD (2 shared names, e.g.
TEST.CLAIMS.DAILY ~ PROD.CLAIMS.DAILY)`.

If candidates are listed **and** `<ws>/architecture-diagrams/archdiag.config.json` does
not exist yet, ask the user **once**. Show them the pairs and the summary's warning, then
ask which of these are environment names (copies of the same data for PROD, TEST and so
on).

- If they confirm some: run `python "<skill>/scripts/run.py" init-config --workspace "<ws>"`.
  It adds every candidate it found. Open `archdiag.config.json` and remove any qualifier
  the user did not confirm, then run `scan` again.
- If they confirm none: write `archdiag.config.json` as
  `{"environment_qualifiers": [], "exclude_dirs": []}` so you don't ask again.

Never add a qualifier the user did not confirm. A wrong one turns different datasets or
tables into one, which makes false solid links. The config format is in
`reference/groups-format.md`.

### 3. Group the code into applications (first use)

If `<ws>/architecture-diagrams/groups.json` does not exist, propose application groups.
Base them on the summary's repos and applications, and on `list --what programs`,
`list --what transactions` and `list --what jobs` if names show a pattern (for example
`CLMO*` = Claims Online). Write `groups.json` in the format in
`reference/groups-format.md`. Show the user the application names and what each holds,
and say they can rename or regroup by asking you or by editing the file. If the repos
already match the applications one to one, a `groups.json` listing them is fine.

**Never add links.** Links come only from the scan. If you believe two things are
connected and the scan does not show it, put it in `suggested_links` with a `note` saying
why. It is drawn as a dotted orange line marked as your suggestion, never as a solid one.
Tell the user it is a suggestion. Never edit `links.json` or `inventory.json`.

After writing `groups.json`, watch the next command's output for `groups.json: ...` lines,
such as a selector that matches nothing or a dropped suggested link, and fix the file.

### 4. Choose level, scope and style

Map the request using `reference/levels-and-styles.md`.

| Level | Scope | Default style |
|---|---|---|
| `--level landscape` | none | `b` |
| `--level application` | application name | `a` |
| `--level flow` | job, transaction, page route or endpoint | `a` (`d` for walkthroughs) |
| `--level repomap` | optional repo name | `c` |
| `--level gitdiagram` | one repo name (required) | `b` |

`--style` is `a`, `b`, `c`, `d` or `all`. To find a scope name, run:

`python "<skill>/scripts/run.py" list --what jobs|transactions|pages|endpoints|applications|repos|programs --workspace "<ws>"`

Each line is `NAME<TAB>description (repo/path)`. Use the exact NAME (everything before the
tab). The description says what the item is: the program a transaction runs (from the CSD),
a page's component, an endpoint's handler class, the programs a job's steps run. Programs
have only their `(repo/path)`.

**Environment copies of a job.** When the same job name exists in several places (for
example a prod and a test copy), `--scope NAME` draws one of them and the output notes
`Also exists as: <repo/path>, ...`. To draw a specific copy, pass its id
`job:<repo/path>` from the listing, for example
`--scope "job:claims-batch/jcl/test/CLMD100.jcl"`.

**Scope rule.** When the user names a flow in words, for example "the claim details
transaction", list `transactions`, `pages` and `endpoints`, plus `jobs` for batch, and
match their words against the names and the descriptions. To match better, you may open
the CSD, BMS map or Angular route file named in `(repo/path)`. Only read those files. If
exactly one name clearly fits, use it and say which you picked. Otherwise, **show the candidates and ask**.
Never guess between several.

### 5. Draw and report

`python "<skill>/scripts/run.py" draw --level <level> [--scope "<scope>"] [--style <style>] --workspace "<ws>"`

The command prints any `Note:` lines and any `WARNING:` line, then a block like this:

```
Wrote:
  ...\architecture-diagrams\flow-clmd100-a.svg
  ...\architecture-diagrams\flow-clmd100-a.drawio
  ...\architecture-diagrams\flow-clmd100-links.md
Summary: 18 nodes, 20 links: 16 confirmed, 2 partly known, 2 loose ends
Top issues:
  - PROD.CLAIMS.AUDIT -> no reader found [loose]: written but never read in these repos
  - CLMB200 -> CLMB210 (CALL) [partial]: CALL through variable WS-PGM
```

Reply plainly with:

1. The file paths from `Wrote:`. The `.svg` is the picture, and it opens in Edge, VS Code,
   Word and PowerPoint. The other file is the editable copy.
2. The `Summary:` line, in one or two sentences.
3. The `Top issues:`, as printed. Don't explain them away or claim they are fine.
4. Every `WARNING:` and `Note:` line.
5. An offer to open or walk through the links report (`*-links.md`). It lists every line
   with the file and line for both ends.

What the lines mean, if asked: **solid** = confirmed in the code (both ends found, exactly
one match). **Dotted orange** = partly known (worked out at run time, ambiguous, or your
suggestion). **Red ending in a dot** = loose end (only one side found, so a repo may be
missing or the link leaves the estate). **Dashed brown** = shared copybook.

Don't describe anything as connected unless the diagram or the links report shows it.

### 6. Too big

If a note says `Too big for one picture: try level application with scope X` (or
`level flow with scope X`), offer to draw that level and scope next. If it says items are
grouped as `… N more`, point the user to the links report, which lists every one.

### 7. Diagram of one repo (gitdiagram)

For "gitdiagram", "diagram of this repo", "how is <repo> put together", "repo structure".
It draws one repo as named groups of files, with arrows from the scan. The grouping is a
file you write: `architecture-diagrams/gitdiagram-<repo>.json` (format and rules in
`reference/groups-format.md`). Check `<ws>/architecture-diagrams/` for it first.

**No file yet:**

1. Run `python "<skill>/scripts/run.py" gitdiagram-context --repo "<repo>" --workspace "<ws>"`
   and read it (files with kind and main names, the README, links, entry points).
2. Propose about 6-15 groups, each with a short human name, a tech label and a one-line
   description, plus a short overview. For a repo with no README, group by job streams, the
   programs they run, shared copybooks and online transactions.
3. **Show them to the user and wait for changes** (rename, merge, split). Do not save yet.
4. Write `gitdiagram-<repo>.json`, then run
   `python "<skill>/scripts/run.py" draw --level gitdiagram --scope "<repo>" --workspace "<ws>"`.

**File exists:** just draw. Never change groups the user edited unless they ask. Re-run
`draw` after any edit.

Put every file in exactly one group, or leave it on purpose for "Not yet grouped". Never
add links. Links come from the scan. A suggested link goes only in `suggested_links`, with
a `note`; it is always drawn dotted and is never evidence, so never suggest one the code
already shows. Never write outside `architecture-diagrams/`.

What `draw` prints, and what to do:

- `Grouped by folder. Ask Copilot to name groups for this repo.` No file yet. Do steps 1-4.
- `The gitdiagram file couldn't be used (...); folders were used instead.` Say so, fix the
  file (or ask), draw again.
- `Not yet grouped: N files (see ...)` Offer to place them. Add patterns to the right
  groups, keep the rest as they were, draw again.
- `Problem in gitdiagram-<repo>.json: ...` (a pattern that matches nothing, a dropped
  suggested link). Fix the pattern it names, draw again.

Report as in step 5: paths, the `Summary:` line and `Top issues:` verbatim, every `Note:`
and `WARNING:`. Grey thin "starts" lines only say a job exists; who schedules it is not in
the repos.

Boxes are clickable, with relative links to the files: the SVG (browser or VS Code) and
the draw.io file open them. Mermaid links work in the VS Code preview but are off on
GitHub and Azure DevOps. Excalidraw resolves them against the app, so they will likely not
open. The `architecture-diagrams` folder must stay beside the cloned repos.
