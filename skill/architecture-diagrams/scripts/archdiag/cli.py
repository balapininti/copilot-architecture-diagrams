"""Command line: scan, summary, list, draw, gitdiagram-context, init-config. Never shows a traceback."""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import resolve as _resolve_pkg
from .config import CONFIG_NAME, Config, load_config
from .groups import Groups, load_groups
from .model import CONFIRMED, LOOSE, PARTIAL, Inventory, Resolved
from .repos import discover_repos
from .scan import scan_workspace
from .store import cache_is_current, fingerprint, load_inventory, load_resolved, save_json
from .summary import _env_pairs, build_summary, count_unanalyzed, list_items
from .views.common import STRUCTURAL

OUT_DIR_NAME = "architecture-diagrams"
CLI_LEVELS = ("landscape", "application", "flow", "repomap", "gitdiagram")
DEFAULT_STYLE = {"landscape": "b", "application": "a", "flow": "a", "repomap": "c",
                 "gitdiagram": "b"}
STYLES = ("a", "b", "c", "d")
LISTINGS = ("jobs", "transactions", "pages", "endpoints", "applications", "repos", "programs")
# what to list for a level, to find a valid scope
LEVEL_LISTING = {"application": ["applications"], "repomap": ["repos"], "gitdiagram": ["repos"],
                 "flow": ["jobs", "transactions", "pages", "endpoints"]}


def resolve(inv: Inventory, config: Config) -> Resolved:
    return _resolve_pkg.resolve(inv, config)


def _make_notice(to_stderr: bool) -> Callable[[str], None]:
    """A sink for notices about what was done: stdout, except for `list`, whose stdout is
    read by machines (Copilot) and must hold the listing only."""
    def notice(message: str) -> None:
        print(message, file=sys.stderr if to_stderr else sys.stdout, flush=True)
    return notice


class _Exit(Exception):
    """A planned early end of a command: print ``message`` and return ``code``."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # no usage dump on stderr, no sys.exit
        raise _Exit(2, "%s\n%s" % (message, self.format_usage().strip()))


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="archdiag")
    sub = parser.add_subparsers(dest="command", parser_class=_Parser)

    def common(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--workspace", default=".",
                       help="folder that holds the repos (default: current folder)")
        return p
    common(sub.add_parser("scan", help="scan the repos and write inventory.json and links.json"))
    common(sub.add_parser("summary", help="print the scan summary and write summary.md"))
    p = common(sub.add_parser("list", help="list jobs, transactions, pages and so on"))
    p.add_argument("--what", required=True, help="one of: " + ", ".join(LISTINGS))
    p = common(sub.add_parser("draw", help="draw a diagram"))
    p.add_argument("--level", required=True, help="one of: " + ", ".join(CLI_LEVELS))
    p.add_argument("--scope", default=None, help="application, job, transaction, page, "
                   "endpoint or repo, depending on the level")
    p.add_argument("--style", default=None, help="a, b, c, d or all (default depends on the level)")
    p = common(sub.add_parser("gitdiagram-context", help="print what is needed to group one "
                              "repo's files into a gitdiagram"))
    p.add_argument("--repo", required=True, help="the repo folder name")
    common(sub.add_parser("init-config", help="write archdiag.config.json from the scan"))
    return parser


# ------------------------------------------------------------------ workspace and cache

def _check_workspace(workspace: Path) -> None:
    if not workspace.is_dir() or not discover_repos(workspace):
        raise _Exit(3, "No git repos found under %s. Clone the repos into one folder and run "
                       "again." % workspace)


def _scan_and_save(workspace: Path, out_dir: Path, config: Config) -> Tuple[Inventory, Resolved]:
    """Scan, resolve, then write links.json and, last, inventory.json: a crash part way
    never leaves a new inventory beside old links."""
    inventory = scan_workspace(workspace, config)
    resolved = resolve(inventory, config)
    save_json(out_dir / "links.json", resolved)
    save_json(out_dir / "inventory.json", inventory)
    return inventory, resolved


def _warn_unanalyzed(inv: Inventory, see: Path) -> None:
    n = count_unanalyzed(inv)
    if n:
        print("WARNING: %d file(s) could not be analyzed; links involving them may be missing "
              "(see %s)" % (n, see))


def _counts_line(inv: Inventory, r: Resolved) -> str:
    st = {CONFIRMED: 0, PARTIAL: 0, LOOSE: 0}
    for e in r.edges:
        st[e.status] = st.get(e.status, 0) + 1
    line = "%d repo(s), %d things found, %d links (%d confirmed, %d partly known, %d loose ends)" % (
        len(inv.repos), len(r.nodes), len(r.edges), st[CONFIRMED], st[PARTIAL], st[LOOSE])
    if inv.skipped:
        line += "; %d file(s) skipped" % len(inv.skipped)
    return line


def _load_current(workspace: Path, out_dir: Path, config: Config,
                  notice: Callable[[str], None]) -> Resolved:
    """The resolved links for the workspace as it is now: the cache when the repos have not
    changed, otherwise a fresh scan (stating so). The fingerprint inside links.json (its
    inventory) decides, so links from an older scan are never served."""
    links_path = out_dir / "links.json"
    cached: Optional[Resolved] = None
    if links_path.is_file():
        try:
            cached = load_resolved(links_path)
        except (OSError, ValueError, KeyError, TypeError):
            cached = None
    if cached is not None and not cache_is_current(cached.inventory):
        notice("Saved scan was made by another archdiag version; rescanned.")
    elif cached is not None:
        repos = discover_repos(workspace)
        if fingerprint(workspace, repos, config) == cached.inventory.fingerprint:
            cfg_path = out_dir / CONFIG_NAME
            try:
                if not (cfg_path.is_file() and cfg_path.stat().st_mtime > links_path.stat().st_mtime):
                    return cached
            except OSError:
                pass
            resolved = resolve(cached.inventory, config)  # settings changed: no rescan
            save_json(links_path, resolved)
            return resolved
        notice("Repos changed since last scan; rescanned.")
    else:
        print("No earlier scan found; scanning.", file=sys.stderr)
    inv, resolved = _scan_and_save(workspace, out_dir, config)
    print("Scanned: " + _counts_line(inv, resolved), file=sys.stderr)
    return resolved


def _groups(out_dir: Path, r: Resolved, notice: Callable[[str], None]) -> Groups:
    g = load_groups(out_dir / "groups.json", r)
    for problem in g.problems:
        notice("groups.json: %s" % problem)
    return g


# ------------------------------------------------------------------ commands

def _cmd_scan(args, workspace: Path, out_dir: Path, notice: Callable[[str], None]) -> int:
    _check_workspace(workspace)
    inv, resolved = _scan_and_save(workspace, out_dir, load_config(out_dir, notice))
    print("Scanned " + _counts_line(inv, resolved))
    _warn_unanalyzed(inv, out_dir / "inventory.json")
    print("Wrote %s and %s" % (out_dir / "inventory.json", out_dir / "links.json"))
    return 0


def _cmd_summary(args, workspace: Path, out_dir: Path, notice: Callable[[str], None]) -> int:
    _check_workspace(workspace)
    config = load_config(out_dir, notice)
    r = _load_current(workspace, out_dir, config, notice)
    text = build_summary(r, load_groups(out_dir / "groups.json", r), config)
    _write(out_dir / "summary.md", text)
    print(text, end="")
    _warn_unanalyzed(r.inventory, out_dir / "summary.md")
    print("Wrote %s" % (out_dir / "summary.md"))
    return 0


def _cmd_list(args, workspace: Path, out_dir: Path, notice: Callable[[str], None]) -> int:
    if args.what not in LISTINGS:
        raise _Exit(2, _did_you_mean(args.what, list(LISTINGS), "what", "list --what <one of "
                                     + ", ".join(LISTINGS) + ">"))
    _check_workspace(workspace)
    r = _load_current(workspace, out_dir, load_config(out_dir, notice), notice)
    items = list_items(r, _groups(out_dir, r, notice), args.what)
    for line in items:
        print(line)
    if not items:
        print("No %s found." % args.what)
    return 0


def _repo_name(r: Resolved, repo: str) -> Optional[str]:
    names = [x.name for x in r.inventory.repos]
    if repo in names:
        return repo
    return next((x for x in names if x.lower() == repo.lower()), None)


def _cmd_gitdiagram_context(args, workspace: Path, out_dir: Path,
                            notice: Callable[[str], None]) -> int:
    from .summary import gitdiagram_context
    _check_workspace(workspace)
    r = _load_current(workspace, out_dir, load_config(out_dir, notice), notice)
    name = _repo_name(r, args.repo)
    if name is None:
        raise _Exit(2, _did_you_mean(args.repo, [x.name for x in r.inventory.repos], "repo",
                                     "list --what repos"))
    print(gitdiagram_context(r, name))
    return 0


def _cmd_init_config(args, workspace: Path, out_dir: Path, notice: Callable[[str], None]) -> int:
    _check_workspace(workspace)
    config = load_config(out_dir, notice)
    r = _load_current(workspace, out_dir, config, notice)
    found: List[str] = []
    for kind in ("dataset", "table"):
        for q1, q2, _n, _ex in _env_pairs(r, config, kind):
            for q in (q1, q2):
                if q.upper() not in [x.upper() for x in found]:
                    found.append(q.upper())
    quals = list(config.environment_qualifiers)
    for q in found:
        if q.upper() not in [x.upper() for x in quals]:
            quals.append(q)
    path = out_dir / CONFIG_NAME
    _write(path, json.dumps({"environment_qualifiers": quals,
                             "exclude_dirs": list(config.exclude_dirs)}, indent=2) + "\n")
    print("Wrote %s with environment_qualifiers: %s" % (path, ", ".join(quals) or "(none found)"))
    print("Please confirm these are real environment names (for example PROD and TEST) "
          "and delete any that are not, then run scan again.")
    return 0


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9._-]", "-", text.lower())


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _did_you_mean(bad: str, options: List[str], noun: str, listing: str) -> str:
    hits = difflib.get_close_matches(bad, options, n=3, cutoff=0.5)
    lines = ["No %s named %r." % (noun, bad)]
    if hits:
        lines.append("Did you mean: %s" % ", ".join(hits))
    lines.append("To see the choices, run: %s" % listing)
    return "\n".join(lines)


def _is_job(r: Resolved, scope: str) -> bool:
    up = scope.strip().upper()
    return any(n.kind == "job" and (n.id == scope or n.name.upper() == up)
               for n in r.nodes.values())


def _top_issues(view, r: Resolved) -> List[str]:
    names = {n.id: n.label for n in view.nodes}
    out = []
    # the Scheduler's grey "starts" line is structure, not an issue (Ruling 2)
    for e in sorted((e for e in view.edges if e.status not in (CONFIRMED, STRUCTURAL)),
                    key=lambda e: (e.status != LOOSE, e.src, e.dst)):
        reason = next((u.reason for u in e.underlying if u.reason), None) or (
            "link is not confirmed" if e.status == PARTIAL else "nothing found at the other end")
        src, dst = names.get(e.src, e.src), names.get(e.dst, e.dst)
        label = " (%s)" % e.label if e.label and e.label not in (src, dst) else ""
        out.append("- %s -> %s%s [%s]: %s" % (src, dst, label, e.status, reason))
        if len(out) == 3:
            break
    return out


def _gitdiagram_lines(view, gd, links: Path) -> None:
    from .gitdiagram import FALLBACK_NOTE, no_files_note
    ung = next((n for n in view.nodes if n.role == "ungrouped"), None)
    n = len(ung.members) if ung is not None else 0
    if n:
        print("Not yet grouped: %d file%s (see %s)" % (n, "" if n == 1 else "s", links))
    problems = [" ".join(p.split()) for p in view.problems if p != FALLBACK_NOTE]
    if no_files_note(gd.repo) in view.notes:
        print(no_files_note(gd.repo))
    elif gd.file_state == "missing":
        print(FALLBACK_NOTE)
    if gd.file_state == "unusable":
        print("The gitdiagram file couldn't be used (%s); folders were used instead."
              % (problems[0] if problems else "unknown problem"))
        problems = problems[1:]  # its reason, said on the line above
    for p in problems[:5]:
        print("Problem in gitdiagram-%s.json: %s" % (gd.repo, p))
    if len(problems) > 5:
        print("... and %d more (see %s)" % (len(problems) - 5, links))


def _stray_gitdiagram_files(out_dir: Path, r) -> List[str]:
    """A note for each gitdiagram-<repo>.json whose repo is not in the scan (a renamed or
    removed repo): its groups are used by no drawing."""
    repos = {x.name for x in r.inventory.repos}
    out = []
    for p in sorted(Path(out_dir).glob("gitdiagram-*.json")):
        name = p.name[len("gitdiagram-"):-len(".json")]
        if name not in repos:
            out.append("%s is for a repo that is not in the scan (%s); was it renamed?"
                       % (p.name, name))
    return out


def _cmd_draw(args, workspace: Path, out_dir: Path, notice: Callable[[str], None]) -> int:
    from .render import report, style_a, style_b, style_c, style_d
    from .layout import layout_notes
    from .views import ScopeError, build_view
    from .gitdiagram import FALLBACK_NOTE, no_files_note
    level = args.level
    if level not in CLI_LEVELS:
        raise _Exit(2, _did_you_mean(level, list(CLI_LEVELS), "level",
                                     "draw --level <%s>" % "|".join(CLI_LEVELS)))
    style = (args.style or DEFAULT_STYLE[level]).lower()
    if style != "all" and style not in STYLES:
        raise _Exit(2, _did_you_mean(style, list(STYLES) + ["all"], "style", "draw --style a|b|c|d|all"))
    styles = list(STYLES) if style == "all" else [style]
    _check_workspace(workspace)
    config = load_config(out_dir, notice)
    r = _load_current(workspace, out_dir, config, notice)
    g = _groups(out_dir, r, notice)
    scope = args.scope
    view_level = level
    if level == "flow":
        view_level = "flow_job" if scope and _is_job(r, scope) else "flow_tx"
    gd = None
    if level == "gitdiagram":
        from .gitdiagram import load_gitdiagram
        name = _repo_name(r, scope) if scope else None
        if name is not None:
            scope = name
            gd = load_gitdiagram(out_dir, r, name)
    try:
        view = build_view(r, g, view_level, scope, gitdiagram=gd)
    except ScopeError as e:
        if level == "flow" and scope:  # a job name may be what was meant
            jobs = sorted(set(n.name for n in r.nodes.values() if n.kind == "job"))
            close = difflib.get_close_matches(scope.upper(), jobs, n=3, cutoff=0.6)
            e.suggestions = close + [x for x in e.suggestions if x not in close]
        hint = "; ".join("list --what %s" % w for w in LEVEL_LISTING.get(level, ["applications"]))
        lines = [e.message]
        if e.suggestions and "did you mean" not in e.message.lower():
            lines.append("Did you mean: %s" % ", ".join(e.suggestions))
        elif e.suggestions:
            lines = [e.message.split("; did you mean")[0] + ".",
                     "Did you mean: %s" % ", ".join(e.suggestions)]
        lines.append("To see the choices, run: " + " or ".join(
            "python run.py %s --workspace <folder>" % h for h in hint.split("; ")))
        raise _Exit(2, "\n".join(lines))
    if gd is not None:
        view.notes += _stray_gitdiagram_files(out_dir, r)
    renderers = {"a": style_a.render, "b": style_b.render, "c": style_c.render, "d": style_d.render}
    base = level + ("-" + _slug(scope) if scope else "")
    written: List[Path] = []
    for s in styles:
        for ext, text in renderers[s](view).items():
            path = out_dir / ("%s-%s.%s" % (base, s, ext))
            _write(path, text)
            written.append(path)
    links = out_dir / ("%s-links.md" % base)
    _write(links, report.links_report(view, r))
    written.append(links)
    # the gitdiagram's own notes are said once, by the lines printed below
    said = set(view.problems) | {FALLBACK_NOTE, no_files_note(gd.repo)} if gd is not None \
        else set()
    for note in view.notes + layout_notes(view):
        if note in said or (gd is not None and re.match(r"^\d+ files? not yet grouped$", note)):
            continue  # the "Not yet grouped: N files" line below says it
        notice("Note: %s" % note)
    st = {CONFIRMED: 0, PARTIAL: 0, LOOSE: 0}
    for e in view.edges:
        st[e.status] = st.get(e.status, 0) + 1
    _warn_unanalyzed(r.inventory, links)
    if gd is not None:
        _gitdiagram_lines(view, gd, links)
    print("Wrote:")
    for p in written:
        print("  %s" % p)
    # Ruling 10: the total adds up; job-structure ("starts") lines are not links
    struct = sum(1 for e in view.edges if e.status == STRUCTURAL)
    summary = ("Summary: %d nodes, %d links: %d confirmed, %d partly known, %d loose ends"
               % (len(view.nodes), len(view.edges) - struct, st[CONFIRMED], st[PARTIAL],
                  st[LOOSE]))
    if struct:
        summary += "; %d job-structure line%s" % (struct, "" if struct == 1 else "s")
    print(summary)
    print("Top issues:")
    issues = _top_issues(view, r)
    for line in issues or ["- none"]:
        print("  " + line)
    return 0


COMMANDS = {"scan": _cmd_scan, "summary": _cmd_summary, "list": _cmd_list,
            "draw": _cmd_draw, "gitdiagram-context": _cmd_gitdiagram_context,
            "init-config": _cmd_init_config}


def _plain_output() -> None:
    """Windows consoles may not encode every character; never fail on printing."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass


def _log_error(out_dir: Path) -> Optional[Path]:
    try:
        path = out_dir / "error.log"
        _write(path, traceback.format_exc())
        return path
    except Exception:
        return None


def main(argv: List[str]) -> int:
    _plain_output()
    machine = argv[:1] in (["list"], ["gitdiagram-context"])  # list's stdout is read by machines: messages go to stderr
    err = sys.stderr if machine else sys.stdout
    try:
        args = _build_parser().parse_args(argv)
        if not args.command:
            raise _Exit(2, "Choose a command: scan, summary, list, draw, gitdiagram-context, "
                           "init-config. "
                           "Example: python run.py scan --workspace <folder>")
    except _Exit as e:
        print(e.message, file=err)
        return e.code
    except SystemExit as e:  # --help
        return e.code if isinstance(e.code, int) else 0
    notice = _make_notice(args.command in ("list", "gitdiagram-context"))
    workspace = Path(os.path.abspath(args.workspace))  # real lengths for the 260-char checks
    out_dir = workspace / OUT_DIR_NAME
    try:
        return COMMANDS[args.command](args, workspace, out_dir, notice)
    except _Exit as e:
        print(e.message, file=err)
        return e.code
    except KeyboardInterrupt:
        print("Stopped.", file=err)
        return 1
    except Exception as e:  # never show a traceback
        msg = " ".join(str(e).split())
        log = _log_error(out_dir) if workspace.is_dir() else None
        if log is not None:
            print("Something went wrong (%s: %s). Details: %s" % (type(e).__name__, msg, log), file=err)
        else:
            print("Something went wrong (%s: %s)." % (type(e).__name__, msg), file=err)
        return 1
