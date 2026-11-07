# groups.json, gitdiagram-<repo>.json and archdiag.config.json

Both files live in `<workspace>/architecture-diagrams/`, next to `inventory.json` and
`links.json`. Write them as UTF-8 JSON. Problems in either file are never fatal. The next
command prints them as `groups.json: ...` lines, and `summary` lists them under
"Problems in groups.json". Fix what they name.

## groups.json

```json
{
  "apps": [
    {"name": "Claims Online", "kind": "application",
     "members": ["repo:claims-online", "transaction:CLM*", "path:claims-api/src/main/java/com/acme/claims/online/*"]},
    {"name": "Claims Batch", "kind": "application", "members": ["repo:claims-batch"]},
    {"name": "Claims Data", "kind": "datastore", "members": ["repo:claims-db", "dataset:PROD.CLAIMS.*"]},
    {"name": "Rates Service", "kind": "external", "members": ["external:rates.example.com"]}
  ],
  "suggested_links": [
    {"from": "Claims Batch", "to": "Rates Service",
     "note": "job CLMD300 sends a file by NDM; the receiver is not in these repos"}
  ]
}
```

### apps

| Field | Meaning |
|---|---|
| `name` | The name shown on diagrams. Must be unique. It is also the `--scope` for `--level application`. |
| `kind` | `application` (default), `datastore` (a group of tables or datasets) or `external` (a system outside these repos). |
| `members` | A list of selectors (below). |

Selectors:

| Selector | Picks |
|---|---|
| `repo:<repo>` | Everything found in that repo (the folder name, as `list --what repos` prints it). |
| `<kind>:<glob>` | Things of that kind whose name matches the glob (`*`, `?`, `[ABC]`). Names match regardless of case. Kinds: `job`, `step`, `proc`, `program`, `copybook`, `transaction`, `map`, `cicsfile`, `table`, `dataset`, `queue`, `mqprocess`, `zosapi`, `class`, `endpoint`, `page`, `component`, `notanalyzed`, `external`. |
| `path:<repo>/<glob>` | Things whose evidence file matches, for example `path:claims-api/src/main/java/com/acme/claims/online/*`. |

Rules:

- A thing belongs to the **first** app, in list order, that has a matching selector.
  Otherwise it belongs to the app named after its repo, which is added automatically.
- Datasets and queues sit in no repo. They belong to no app unless a selector picks them,
  and they are drawn as shared stores between apps.
- A selector that matches nothing is reported, not fatal. So is a selector that is not
  one of the three forms.
- With no groups.json, every repo is its own app, and a repo holding only DDL is a
  `datastore`.

### suggested_links: the only place Copilot may record a link

The scanner finds links in the code. **Copilot never adds links.** Not to links.json, not
as a solid line, and not anywhere else. If you believe two things are connected and the
scan does not show it, record it here. It is drawn as a **dotted orange (partly known)**
line marked "suggested by Copilot". Tell the user it is a suggestion.

| Field | Meaning |
|---|---|
| `from`, `to` | An app name from `apps`, or a node id exactly as `summary` and `links.json` print it: `<kind>:<NAME>`, for example `program:CLMO110`, `queue:CLM.AUDIT`, `transaction:CLMI`. A Java class carries its repo: `class:claims-api/RatesClient`. |
| `note` | Why you think they are connected. Required in practice: the links report shows it. |

An end that names nothing is dropped with a `suggested link ... dropped: unknown ...` line.

## archdiag.config.json

```json
{
  "environment_qualifiers": ["PROD", "TEST"],
  "exclude_dirs": ["archive", "old-copies"]
}
```

| Field | Meaning |
|---|---|
| `environment_qualifiers` | First qualifiers of dataset names, or DB2 schemas, that are environment names. Names that differ only by one of these count as the same thing, so their links can be solid. Only list names the user confirmed are environments. A wrong entry joins things that are really different. `init-config` fills this from the candidates in the summary. Empty means none. |
| `exclude_dirs` | Folder names to skip when scanning, in addition to `.git`, `node_modules`, `target`, `bin` and the like. |

After changing either field, run `scan` again.

## gitdiagram-<repo>.json

One file per repo, in `<workspace>/architecture-diagrams/`, written by Copilot or the user.
The scripts never write it. UTF-8 JSON, at most 5 MB. A file that cannot be read is
replaced by a grouping by top-level folder, and `draw` says so.

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
  "suggested_links": [
    {"from": "Claim pricing", "to": "Nightly jobs", "label": "rates file",
     "note": "CLMB200 reads a rates file the JCL does not name"}
  ]
}
```

| Field | Meaning |
|---|---|
| `repo` | The repo folder name. |
| `overview` | A short paragraph, printed above the picture and at the top of the links report. |
| `groups[].name` | Short, human, unique. Shown on the box. |
| `groups[].tech` | Technology label, for example `COBOL`, `JCL`, `Java`, `Angular`, `DB2`. |
| `groups[].description` | One line. |
| `groups[].files` | Patterns (below). |
| `suggested_links[]` | `from` and `to` (group names, or an entry box such as `Scheduler`, `CICS transactions`, `REST endpoints`, `Angular pages`, `z/OS Connect APIs`), `label`, and `note` (why). |

Patterns: relative to the repo, case-insensitive, `\` read as `/`, a leading `./` dropped.
A pattern with no glob matches that file, or everything under that folder. Globs use `*`,
`?` and `[ABC]`; `*` also crosses `/`, so `**` works like `*`. A file belongs to the first
group, in list order, with a matching pattern. A file no group claims goes into the box
"Not yet grouped", so nothing disappears.

Rules for Copilot:

- Every file the scan found sits in exactly one group, or is left for "Not yet grouped" on
  purpose. `gitdiagram-context` lists them.
- Suggested links are always drawn dotted, as a suggestion, and are never evidence. Never
  suggest one the scan already shows. Links the scan finds are never written here.
- Never change groups the user changed unless asked. When files are added later, add
  patterns for them and leave the rest.
- Problems (a pattern that matches nothing, a bad field, a dropped suggested link) are
  never fatal. `draw` prints them as `Problem in gitdiagram-<repo>.json: ...`. Fix them.
