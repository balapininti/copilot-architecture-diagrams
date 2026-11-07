# Architecture diagrams: a GitHub Copilot skill

Ask Copilot in plain words for a picture of your repos, and it draws one from the code:

- "Draw the landscape for these repos."
- "Show me batch job CLMD100."
- "Draw the claim details transaction as a whiteboard sketch."
- "Link map for claims-batch: what depends on it?"
- "Create a gitdiagram for claims-batch."
- "Draw everything in all four styles."

The skill reads COBOL, JCL, CICS definitions and BMS maps, DB2 DDL, MQ definitions, Java
(Spring, JMS, CTG, z/OS Connect) and Angular. Every line on a diagram comes from the code,
and each one is listed in a links report with the file and line for both ends.

## What you need

- Windows, with **Python 3.9 or newer**. Check with `python --version` or `py -3 --version`.
  Nothing else is installed. No pip packages, no internet.
- **VS Code** with **GitHub Copilot** in agent mode, or the **Copilot CLI**. Agent skills
  are on by default in VS Code (setting `chat.useAgentSkills`).
- If your organization manages VS Code settings: check that `chat.useAgentSkills` is on.
  If the setting is managed and off, ask your admin. Until then, the run-it-yourself route
  below works without the skill.

## Install

In PowerShell, from the root of the delivered package (the folder that holds
`install.ps1` and `skill\`), run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

This is the **recommended** install: it copies the skill to the personal skills folder,
`%USERPROFILE%\.copilot\skills\architecture-diagrams`. VS Code and Copilot CLI both read
skills from there, in every workspace, wherever you start them.

A project install is the alternative, for one workspace only. Copilot CLI may only find
project skills when it is started at a git root (the folder that holds `.git`); if the
workspace folder is not one, use the personal install above. To use it, point `-Project` at **the folder you open
in VS Code or start Copilot CLI in**. That is the folder holding the cloned repos (see below), not
one of the repos inside it:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Project C:\work\claims
```

This copies it to `C:\work\claims\.github\skills\architecture-diagrams`. That folder is
named `architecture-diagrams`, and the scanner always skips folders with that name, so the
skill's own files never show up on the diagrams. If you work on a single repo and open
that repo itself, `-Project` can point at the repo. You can then commit the folder so
others who clone the repo get the skill.

The installer also checks for Python 3.9 or newer and says how to fix it if Python is
missing. Without the installer, copy this whole `architecture-diagrams` folder to either
place yourself.

To check it loaded: in Copilot CLI run `/skills list`. If you added it during a session,
run `/skills reload` first. In VS Code, type `/` in agent-mode chat and look for
`architecture-diagrams`.

## Put the repos in one folder

Clone every repo you want on the diagrams into **one folder**, then open that folder in VS
Code, or start Copilot CLI in it:

```
C:\work\claims\
    claims-batch\
    claims-online\
    claims-api\
    claims-db\
    ...
```

A repo left out shows up as red loose ends wherever something points at it. If the folder
is itself a git repo, it is treated as one repo.

Everything the skill writes goes into `C:\work\claims\architecture-diagrams\`: the scan
(`inventory.json`, `links.json`), `summary.md`, `groups.json` (your application names),
`archdiag.config.json`, and the diagrams. The skill never changes your code.

## What you get

For each diagram, an `.svg` picture, which opens in Edge, VS Code, Word and PowerPoint,
plus an editable copy and a links report (`*-links.md`):

| Style | Look | Editable copy |
|---|---|---|
| a | Pictorial icons | `.drawio` (draw.io) |
| b | C4 boxes | `.md` with Mermaid (GitHub, VS Code), and `.azure.md`, the same diagram for an Azure DevOps wiki |
| c | Repo link map | `.html`: click a line to see its evidence (works offline) |
| d | Whiteboard sketch | `.excalidraw` |

The five zoom levels (landscape, one application, one flow, repo link map, one repo's gitdiagram) are described
in `reference/levels-and-styles.md`.

## What the lines mean

| Line | Meaning |
|---|---|
| **Solid dark grey** | Confirmed. Both ends were found in the code, and exactly one thing matches the name. |
| **Dotted orange** | Partly known. One end is worked out at run time (for example `XCTL` to a variable), the match needed a guess or is ambiguous, or Copilot suggested it. The links report says why. |
| **Red, ending in a dot** | Loose end. Only one side was found in these repos. A repo may be missing, or the link goes outside the estate. |
| **Dashed brown** | Shared code (a copybook used by both sides). |

Copilot may not add links. Anything it suspects is connected is recorded as a suggestion
in `groups.json` (or the gitdiagram file) and drawn dotted, never solid.

## Diagram of one repo (gitdiagram)

Ask "create a gitdiagram for claims-batch" (or "how is claims-batch put together?"). The
diagram shows the repo as a few named groups of files, with arrows between them taken from
the code. Entry points (jobs, CICS transactions, endpoints, pages) sit on the left.

1. Copilot runs `gitdiagram-context --repo claims-batch`, reads it, and proposes 6 to 15
   groups with a short overview. **It shows you the groups and waits for your changes.**
2. It saves them to `architecture-diagrams\gitdiagram-claims-batch.json` and runs
   `draw --level gitdiagram --scope claims-batch`.

Later runs reuse that file. Edit it by hand or ask Copilot; your groups are kept, and
files added since are listed in a "Not yet grouped" box until they are placed. Without the
file, `draw` groups by top-level folder and says so.

An example, abbreviated from the test fixture `gitdiagram-claims-batch.json`:

```json
{
  "repo": "claims-batch",
  "overview": "Nightly claims batch. CLMD100 sorts the claim master, prices each claim and posts payments to DB2.",
  "groups": [
    {"name": "Nightly jobs", "tech": "JCL", "files": ["jcl/**", "proc/**"],
     "description": "Job streams and the procs they call"},
    {"name": "Claim pricing", "tech": "COBOL", "files": ["cobol/CLMB200.cbl", "cobol/CLMB210.cbl"],
     "description": "Prices each claim"}
  ],
  "suggested_links": []
}
```

Patterns are relative to the repo and not case-sensitive; a folder name matches everything
under it. Each file goes to the first group that matches. The full format is in
`reference/groups-format.md`.

The lines mean the same as above, plus one: a thin **grey** line labelled **starts** only
says a job exists; who schedules it isn't in these repos. Copilot's suggested links are
always dotted and are never evidence.

**Clicking a box** opens its file or folder. In the SVG, opened in a browser or VS Code,
and in the draw.io file, it works. Mermaid links work in the VS Code preview but are off on
GitHub and Azure DevOps. Excalidraw resolves relative links against the app, so they will
probably not open. The links are relative, so keep the `architecture-diagrams` folder
beside the cloned repos.

## Before you rely on the diagrams: the calibration step

The skill has been tested on a made-up claims estate, not on your code. On first use, have
**one of your mainframe developers** check the links report for a sample of jobs and
transactions against the code they know. Do this before anyone plans work from the
diagrams.

- Pick, say, five batch jobs and five online transactions. Draw each one, for example
  "show me batch job X", and read its `*-links.md`.
- Look for missing links (a dataset, table, queue, `CALL`, `LINK` or `XCTL` you know is
  there but isn't listed) and wrong links (a solid line that isn't real).
- Send every missed or wrong link, with the file and line, to your delivery contact. Each
  one becomes a test in the skill before the diagrams are relied on.

## If Copilot can't run commands

Your organization's policy may block Copilot from running terminal commands, or you may
prefer to approve nothing. In that case, run the command yourself, and Copilot reads the
results:

1. In a terminal, run the command Copilot gives you, for example:

   ```
   python "%USERPROFILE%\.copilot\skills\architecture-diagrams\scripts\run.py" scan --workspace "C:\work\claims"
   ```

   Use `py -3` in place of `python` if that's what works on your machine.
2. Or use the VS Code tasks: copy `assets/tasks.json` into `C:\work\claims\.vscode\tasks.json`,
   then run *Terminal > Run Task > Architecture diagrams: scan* (or *summary*, *list*,
   *draw*). Copy it from the installed skill folder: the installer sets it up for where
   it installed the skill and for the Python command it found.
3. Paste the output into the chat. Copilot can also read
   `architecture-diagrams\summary.md` and the `*-links.md` reports directly.

## Privacy

The scripts send nothing anywhere. They run on your machine, use no network, and only read
your repos. They write only into the `architecture-diagrams` folder. Copilot itself sees
the command output and the summary (repo, program, job and dataset names, and the links
found), as it would any file you show it. This is covered by your organization's existing
GitHub Copilot agreement. The scripts do not send your source code. Copilot sees a file's
contents only if it opens that file, as it does in any other chat.

## Files in this skill

- `SKILL.md`: the instructions Copilot follows.
- `reference/levels-and-styles.md`: levels, scopes, styles and example requests.
- `reference/groups-format.md`: the `groups.json` and `archdiag.config.json` formats.
- `assets/tasks.json`: VS Code tasks for the run-it-yourself route.
- `scripts/run.py`: the command line (`scan`, `summary`, `list`, `draw`, `init-config`).
