# Levels, scopes and styles

Use this page to turn a request into `draw --level <level> --scope <scope> --style <style>`.

## The four levels

| Level (`--level`) | Shows | For | Scope (`--scope`) | Default style |
|---|---|---|---|---|
| `landscape` | One box per application or repo group, the shared data stores and queues, outside systems, and every link between applications | Architects | none (always the whole estate) | `b` (C4 boxes) |
| `application` | One application's jobs, transactions, programs and data stores, with what it exchanges with the rest shown as grey stubs | Planning one piece of work | an application name, from `list --what applications` | `a` (pictorial) |
| `flow` | One batch job (steps, programs or utilities, data read above the steps, data written below, condition codes) **or** one online path (Angular page, Java, MQ or CICS, programs, DB2, including the 3270 route) | New developers | a job, transaction, page route or endpoint, from `list --what jobs`, `transactions`, `pages` or `endpoints` | `a`. Use `d` for walkthroughs. |
| `repomap` | One card per repo with its key files, and every link between repos labelled by what connects them (queue, table, dataset, copybook, endpoint, CICS program) with the evidence lines | "What breaks if I change this?" | optional: a repo name from `list --what repos`. With a repo, the map is about that repo's links. Leave it out for all repos. | `c` (repo link map) |

The command takes one style at a time (`a`, `b`, `c` or `d`) or `all`. Leaving out
`--style` gives the level's default. Any style works at any level.

## The four styles

| Style | Look | Editable file written next to the `.svg` |
|---|---|---|
| `a` | Pictorial icons, a coloured group per repo, numbered steps | `.drawio` (draw.io / diagrams.net) |
| `b` | C4-style boxes with technology labels and a sentence on each arrow | `.md` with Mermaid (shows as a picture in GitHub and Azure DevOps wikis) |
| `c` | Repo cards listing key files, with the evidence for each link | `.html` (works offline; click a line to see its evidence) |
| `d` | Whiteboard sketch, for walkthroughs and slides | `.excalidraw` |

Every draw also writes `<diagram>-links.md`, the links report. It lists every line with its
status and the file and line for both ends, then every loose end and partly known link.

## Phrases and what to run

| The user says | Level | Scope | Style |
|---|---|---|---|
| "Draw the landscape for these repos." / "big picture" / "how do the applications connect?" | `landscape` | none | default (`b`) |
| "Show me application Claims Online." / "what is in claims-online?" | `application` | the application name | default (`a`) |
| "Show me batch job CLMD100." / "walk me through job X" | `flow` | the job name | default (`a`) |
| "Draw the claim details transaction as a whiteboard sketch." | `flow` | the transaction (or the page or endpoint) that matches "claim details". Find it with `list`, and ask if more than one fits. | `d` |
| "Trace the claims page end to end." | `flow` | the page route from `list --what pages` | default (`a`) |
| "Link map for claims-batch: what depends on it?" / "what breaks if I change this repo?" | `repomap` | `claims-batch` | default (`c`) |
| "Repo link map" / "how do the repos link?" | `repomap` | none | default (`c`) |
| "Draw everything in all four styles." | `landscape` and `repomap` (whole estate) | none | `all` |
| "Make it C4" / "pictorial" / "hand-drawn" / "for slides" | keep the level | keep the scope | `b` / `a` / `d` / `d` |

For "everything", draw the two whole-estate levels with `--style all`. Then list the
applications and offer to draw each one. If there are only a few, say up to five, just
draw them with `--style all`. Don't draw every job and transaction unless the user asks.
There can be hundreds.

## Finding the scope

- Run `list --what <kind>` and pick the exact name from the start of each line. Each line
  is `NAME (repo/path)`.
- A name may appear twice, for example a job kept in both a PROD and a TEST folder. The
  draw uses one and the note `Also exists as: ...` names the others. Mention it.
- A request in words ("the claim details transaction") has to be matched to a name. If
  exactly one transaction, page or endpoint clearly fits, use it and say which one you
  picked. If not, show the user the likely candidates and ask.
- If `draw` exits with code 2, it prints `Did you mean: ...`. Offer those names. Don't
  pick one silently.
- Scopes with spaces, for example the endpoint `GET /api/claims/{}`, go in double quotes.

## Too big for one picture

A diagram holds about 40 boxes. Above that, smaller items are folded into `… N more` and
the draw prints a note:

- `Too big for one picture: try level application with scope X`: offer
  `draw --level application --scope X`.
- `Too big for one picture: try level flow with scope X`: offer
  `draw --level flow --scope X`.
- `Too big for one picture: smaller items are grouped as '… N more'; the links report lists every one`:
  there is no smaller level. Point the user to the links report.
