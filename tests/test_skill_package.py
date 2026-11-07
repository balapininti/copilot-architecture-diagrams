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
    for level in ("landscape", "application", "flow", "repomap"):
        assert "--level %s" % level in text or level in _text(SKILL / "reference" / "levels-and-styles.md")


def test_skill_forbids_inventing_links():
    text = _text(SKILL / "SKILL.md").lower()
    assert "never add links" in text
    assert "suggested_links" in text and "dotted" in text


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
    assert "3, 9" in ps1 or "(3,9)" in ps1.replace(" ", "")
    assert not re.search(r"Invoke-WebRequest|Invoke-RestMethod|DownloadString|https?://", ps1, re.I)
    assert "?." not in ps1 and "??" not in ps1, "PowerShell 5.1 has no ?. or ?? operators"
