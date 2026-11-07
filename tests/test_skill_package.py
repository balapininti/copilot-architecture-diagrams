"""The Copilot skill package: SKILL.md front matter, instructions, references and installer."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skill" / "architecture-diagrams"
FORMAT_DOC = ROOT / "docs" / "copilot-skill-format.md"
DESCRIPTION_LIMIT = 1024  # docs/copilot-skill-format.md
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict:
    assert text.startswith("---\n"), "SKILL.md must start with a '---' front matter line"
    end = text.index("\n---\n", 4)
    fields = {}
    for line in text[4:end].splitlines():
        if line.strip() and not line.startswith(" "):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def test_frontmatter():
    fm = _frontmatter(_text(SKILL / "SKILL.md"))
    assert fm["name"] == "architecture-diagrams" == SKILL.name
    assert NAME_RE.match(fm["name"]) and len(fm["name"]) <= 64
    desc = fm["description"]
    assert desc and not desc.startswith((">", "|")), "keep the description on one line"
    if desc[0] in "'\"":
        assert desc[-1] == desc[0]
        desc = desc[1:-1]
    assert 0 < len(desc) <= DESCRIPTION_LIMIT
    for phrase in ("architecture diagram", "landscape", "batch job", "link map", "depends on"):
        assert phrase in desc.lower(), phrase


def test_skill_mentions_every_command():
    text = _text(SKILL / "SKILL.md")
    for cmd in ("scan", "summary", "list --what", "draw --level", "init-config"):
        assert re.search(r"run\.py\"? %s" % re.escape(cmd), text), cmd
    assert "groups.json" in text
    for what in ("jobs", "transactions", "pages", "endpoints", "applications", "repos", "programs"):
        assert what in text, what
    levels_doc = _text(SKILL / "reference" / "levels-and-styles.md")
    for level, style in (("landscape", "b"), ("application", "a"), ("flow", "a"), ("repomap", "c")):
        assert re.search(r"\| `--level %s` \|[^\n]*\| `%s`" % (level, style), text), level
        assert re.search(r"^\| `%s` \|[^\n]*\| `%s`" % (level, style), levels_doc, re.M), level


def test_skill_forbids_inventing_links():
    text = _text(SKILL / "SKILL.md").lower()
    assert "never add links" in text
    assert "suggested_links" in text and "dotted" in text


def test_skill_forbids_changing_client_code():
    text = _text(SKILL / "SKILL.md")
    assert "never edit, create or delete files in the user's repos" in text.lower()
    assert "Only write inside `<ws>/architecture-diagrams/`" in text


def test_scope_rule_in_both_places():
    for doc in (SKILL / "SKILL.md", SKILL / "reference" / "levels-and-styles.md"):
        text = " ".join(_text(doc).split())
        assert "Scope rule." in text, doc.name
        assert "show the candidates and ask" in text.lower(), doc.name
        assert "say which" in text, doc.name


def test_skill_relays_results_and_handles_blocked_commands():
    text = _text(SKILL / "SKILL.md")
    for word in ("Wrote:", "Summary:", "Top issues:", "WARNING", "Too big", "Did you mean",
                 "assets/tasks.json", "calibration"):
        assert word in text, word


def _referenced_paths(text: str):
    paths = set(re.findall(r"\]\(((?!https?:|#)[^)\s]+)\)", text))
    paths |= set(re.findall(r"(?<![\w/.<>-])((?:reference|scripts|assets)/[\w./-]*\w)", text))
    return {p.lstrip("./") for p in paths}


def test_package_is_self_contained():
    for doc in [SKILL / "SKILL.md", SKILL / "README.md"] + sorted((SKILL / "reference").glob("*.md")):
        base = SKILL
        refs = _referenced_paths(_text(doc))
        assert doc.name != "SKILL.md" or refs, "SKILL.md references nothing"
        for ref in refs:
            target = (base / ref) if (base / ref).exists() else (doc.parent / ref)
            assert target.exists(), "%s references missing %s" % (doc.name, ref)
            assert SKILL in target.resolve().parents, "%s points outside the skill: %s" % (doc.name, ref)
    for name in ("SKILL.md", "README.md", "reference/levels-and-styles.md",
                 "reference/groups-format.md", "assets/tasks.json", "scripts/run.py"):
        assert (SKILL / name).is_file(), name


def test_tasks_json_runs_the_three_commands():
    data = json.loads(_text(SKILL / "assets" / "tasks.json"))
    cmds = " ".join(json.dumps(t) for t in data["tasks"])
    for cmd in ("scan", "summary", "draw"):
        assert '"%s"' % cmd in cmds, cmd
    assert "${workspaceFolder}" in cmds
    personal = _confirmed("Personal").rstrip("\\")  # %USERPROFILE%\.copilot\skills\architecture-diagrams
    run_py = personal.replace("%USERPROFILE%", "${userHome}").replace("\\", "/") + "/scripts/run.py"
    for task in data["tasks"]:
        assert task["args"][0] == run_py, task["label"]
    style = next(i for i in data["inputs"] if i["id"] == "archdiagStyle")
    assert style["default"] == "" and {"label": "level default", "value": ""} in style["options"]


def _confirmed(kind: str) -> str:
    m = re.search(r"^- %s: `([^`]+)`" % kind, _text(FORMAT_DOC), re.M)
    assert m, "docs/copilot-skill-format.md names no %s folder" % kind
    return m.group(1)


def test_install_ps1_targets_confirmed_paths():
    ps1 = _text(ROOT / "install.ps1")
    personal = _confirmed("Personal")   # %USERPROFILE%\.copilot\skills\architecture-diagrams\
    project = _confirmed("Project")     # <repo>\.github\skills\architecture-diagrams\
    assert personal.startswith("%USERPROFILE%\\")
    assert "$env:USERPROFILE" in ps1
    for part in (personal.split("\\")[1:3], project.split("\\")[1:3]):  # .copilot\skills, .github\skills
        assert "'%s'" % part[0] in ps1 and "'%s'" % part[1] in ps1, part
    assert "-Project" in ps1 or "[string]$Project" in ps1
    for exe in ("py", "python", "python3"):
        assert "'%s'" % exe in ps1, exe
    assert "$major -gt 3 -or ($major -eq 3 -and $minor -ge 9)" in ps1
    assert "--version" in ps1 and "Python (\\d+)\\.(\\d+)" in ps1
    assert "Replacing the existing copy" in ps1
    assert not re.search(r"Invoke-WebRequest|Invoke-RestMethod|DownloadString|https?://", ps1, re.I)
    assert "?." not in ps1 and "??" not in ps1, "PowerShell 5.1 has no ?. or ?? operators"


def _make_repo(path: Path, cobol: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".archdiag-repo").write_text("", encoding="utf-8")
    (path / "PGM.cbl").write_text(cobol, encoding="utf-8")


def test_installed_project_skill_is_not_scanned(tmp_path):
    """install.ps1 -Project <ws> puts the skill in <ws>/.github/skills/architecture-diagrams:
    neither a repo nor scanned, whether <ws> holds the clones or is itself the repo."""
    import shutil
    from archdiag.repos import discover_repos, iter_source_files

    cobol = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. %s.\n"
    for single in (False, True):
        ws = tmp_path / ("single" if single else "multi")
        if single:
            _make_repo(ws, cobol % "MAINPGM")
        else:
            _make_repo(ws / "claims-batch", cobol % "MAINPGM")
        installed = ws / ".github" / "skills" / "architecture-diagrams"
        shutil.copytree(str(SKILL), str(installed), ignore=shutil.ignore_patterns("__pycache__"))
        _make_repo(installed / "reference", cobol % "SKILLPGM")  # even a marker inside is ignored
        repos = discover_repos(ws)
        assert [r.name for r in repos] == ([ws.resolve().name] if single else ["claims-batch"])
        for r in repos:
            files = list(iter_source_files(ws / r.path))
            assert files, "the repo's own file is scanned"
            assert not any("architecture-diagrams" in f.parts for f in files), files


def test_readme_recommends_personal_install_and_notes_cli_git_root():
    t = " ".join(_text(SKILL / "README.md").split())
    assert "recommended" in t.lower() and "personal" in t.lower()
    assert t.lower().index("recommended") < t.index("-Project")
    assert "git root" in t.lower()  # Copilot CLI may only find project skills at a git root


def test_skill_md_copies_tasks_json_only_when_asked_and_never_overwrites():
    t = " ".join(_text(SKILL / "SKILL.md").split())
    assert "Only when the user asks you to" in t and "never overwrite" in t
    assert ".vscode/tasks.json" in t


def test_skill_mentions_gitdiagram_commands():
    text = _text(SKILL / "SKILL.md")
    assert re.search(r'run\.py" gitdiagram-context --repo', text)
    assert re.search(r'run\.py" draw --level gitdiagram --scope', text)
    assert re.search(r"^\| `--level gitdiagram` \|[^\n]*\| `b`", text, re.M)
    assert "gitdiagram-<repo>.json" in text
    for phrase in ("diagram of this repo", "Not yet grouped", "Grouped by folder",
                   "couldn't be used", "Problem in gitdiagram"):
        assert phrase in text, phrase
    levels = _text(SKILL / "reference" / "levels-and-styles.md")
    assert re.search(r"^\| `gitdiagram` \|[^\n]*\| `b`", levels, re.M)


def test_skill_says_show_groups_before_saving():
    t = " ".join(_text(SKILL / "SKILL.md").split())
    assert "Show them to the user and wait for changes" in t
    assert t.index("wait for changes") < t.index("Write `gitdiagram-<repo>.json`")


def test_skill_forbids_solid_links_from_copilot():
    t = " ".join(_text(SKILL / "SKILL.md").split())
    assert "never add links" in t.lower()
    section = t[t.index("### 7."):]
    assert "Never add links" in section and "`suggested_links`" in section
    assert "dotted" in section and "never evidence" in section
    assert "Never write outside `architecture-diagrams/`" in section


def test_reference_documents_gitdiagram_file_fields():
    t = _text(SKILL / "reference" / "groups-format.md")
    for word in ("gitdiagram-<repo>.json", "overview", "groups[].name", "groups[].tech",
                 "groups[].description", "groups[].files", "suggested_links", "5 MB",
                 "Not yet grouped", "case-insensitive"):
        assert word in t, word
    readme = _text(SKILL / "README.md")
    for word in ("gitdiagram-context", "--level gitdiagram", "starts", "GitHub and Azure DevOps",
                 "Excalidraw", "beside the cloned repos"):
        assert word in readme, word
