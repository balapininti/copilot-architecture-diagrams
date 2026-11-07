# Copilot skill format: what the official documentation says

Checked on 2026-11-07 against GitHub's and VS Code's own documentation, plus the open
Agent Skills specification that both point to. This is the basis for `SKILL.md`,
`install.ps1` and `tests/test_skill_package.py`.

## Result: one folder serves both

VS Code agent mode and Copilot CLI read the same Agent Skills format (a folder holding
`SKILL.md` with YAML front matter) from the same folders. No conflict with the design
(spec section 10).

| | VS Code agent mode | Copilot CLI |
|---|---|---|
| Personal skills | `~/.copilot/skills/<name>/` (also reads `~/.claude/skills/`, `~/.agents/skills/`) | `~/.copilot/skills/<name>/` or `~/.agents/skills/<name>/` |
| Project skills | `.github/skills/<name>/` (also `.claude/skills/`, `.agents/skills/`) | `.github/skills/<name>/`, `.claude/skills/` or `.agents/skills/` |
| On Windows | `~` is the user's home folder: `%USERPROFILE%\.copilot\skills\<name>\` | same |

**Chosen for this skill:**

- Personal: `%USERPROFILE%\.copilot\skills\architecture-diagrams\` (the one personal folder
  both products list first). The installer copies there only. Installing into a second
  folder as well (for example `~/.agents/skills`) would make VS Code see the skill twice.
- Project: `<workspace>\.github\skills\architecture-diagrams\` (`install.ps1 -Project <workspace>`),
  where `<workspace>` is the folder the user opens, the one holding the cloned repos. The
  scanner skips any folder named `architecture-diagrams`, so the installed skill is never
  scanned as code.

## SKILL.md front matter

| Field | Required | Limits |
|---|---|---|
| `name` | yes | 1 to 64 characters; lowercase letters, digits and hyphens only; no leading, trailing or double hyphen; **must match the folder name**. VS Code: "Names with invalid characters cause the skill to silently fail to load." |
| `description` | yes | 1 to 1024 characters; says what the skill does and when to use it. Copilot picks a skill from its description. |
| `license`, `compatibility` (max 500), `metadata`, `allowed-tools` | no | `allowed-tools` pre-approves tools. GitHub warns against pre-approving `shell`/`bash`, so this skill leaves it out. |
| VS Code only: `argument-hint`, `user-invocable`, `disable-model-invocation`, `context` | no | Not needed here. |

GitHub's pages give no length limits. The limits above come from the Agent Skills
specification and VS Code's page, and VS Code's page says the same for `name`. This skill
uses `name: architecture-diagrams` (21 characters, matching its folder) and a description
under 1024 characters (a test checks this).

## Enabled by default?

- VS Code: setting `chat.useAgentSkills`, "Enable support for agent skills in VS Code",
  **default `true`**. Agent mode must be in use. Organization policy can restrict the skill
  marketplace, but the docs name no policy that turns off local skills.
  `chat.agentSkillsLocations` is deprecated, so the skill does not depend on it.
- Copilot CLI: skills are found automatically. `/skills list` shows them, `/skills info
  <name>` shows where a skill was loaded from, and `/skills reload` picks up a skill added
  during a session. `copilot skill list` works outside a session.

## How a skill runs its scripts

- Copilot discovers every file in the skill folder and makes them available alongside the
  instructions (GitHub). Other files are referenced by paths relative to `SKILL.md`, using
  `/` separators (VS Code, Agent Skills specification).
- GitHub's example tells Copilot to "run the script from this skill's base directory",
  meaning the folder that holds `SKILL.md`. Neither product documents a variable for that
  folder. So `SKILL.md` tells Copilot to use the folder it read `SKILL.md` from, gives the
  installed locations as a fallback, and points to `/skills info architecture-diagrams` in
  the CLI.
- Terminal commands need the user's approval unless auto-approve is set
  (`chat.tools.terminal.autoApprove` in VS Code). When commands are blocked, the skill falls
  back to the user running the command or the VS Code task in `assets/tasks.json`
  (spec section 9).

## Sources

- VS Code, Use Agent Skills in VS Code: https://code.visualstudio.com/docs/copilot/customization/agent-skills
  (also served at https://code.visualstudio.com/docs/agent-customization/agent-skills)
- VS Code, Copilot settings reference (`chat.useAgentSkills` default true): https://code.visualstudio.com/docs/copilot/reference/copilot-settings
- GitHub Docs, Adding agent skills for GitHub Copilot CLI: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills
- GitHub Docs, Creating agent skills (cloud agent and VS Code): https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/create-skills
- GitHub Docs, About agent skills (supported products): https://docs.github.com/en/copilot/concepts/agents/about-agent-skills
- Agent Skills specification: https://agentskills.io/specification
