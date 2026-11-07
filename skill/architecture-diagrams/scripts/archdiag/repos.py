from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Callable, Iterable, Iterator, List, Optional, Tuple

from .model import Repo

SKIP_DIRS = frozenset([
    ".git", ".svn", "node_modules", "target", "build", "bin", "obj", "dist",
    ".idea", ".vscode", "architecture-diagrams",
])
SKIP_EXTS = frozenset([
    ".class", ".jar", ".war", ".ear", ".zip", ".png", ".jpg", ".gif", ".ico",
    ".pdf", ".exe", ".dll", ".so", ".lock",
])
MAX_BYTES = 5 * 1024 * 1024
MAX_PATH = 260  # Windows MAX_PATH: longer paths need the \\?\ prefix


def extended_path(path: str, abspath: Callable[[str], str] = os.path.abspath) -> str:
    """The Windows extended-length form of ``path`` (``\\\\?\\C:\\x`` or ``\\\\?\\UNC\\srv\\x``)."""
    full = abspath(path)
    if full.startswith("\\\\?\\"):
        return full
    if full.startswith("\\\\"):
        return "\\\\?\\UNC\\" + full[2:]
    return "\\\\?\\" + full


def with_long_path(func: Callable, path) -> object:
    """``func(path)``; on Windows, when that fails for a path of 260 characters or more, once
    more with the extended-length form (the original error is raised if that fails too)."""
    try:
        return func(path)
    except OSError:
        if os.name != "nt" or len(str(path)) < MAX_PATH:
            raise
        try:
            return func(extended_path(str(path)))
        except OSError as e2:
            raise e2


REPO_MARKER_FILE = ".archdiag-repo"


def _is_repo(path: Path) -> bool:
    """A repo has a .git entry, or a plain .archdiag-repo marker file (test-friendly)."""
    return (path / ".git").exists() or (path / REPO_MARKER_FILE).is_file()


def discover_repos(workspace: Path) -> List[Repo]:
    workspace = Path(workspace)
    if _is_repo(workspace):
        return [Repo(workspace.resolve().name, ".")]
    repos = []
    try:
        children = sorted(workspace.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    for child in children:
        if child.is_dir() and _is_repo(child):
            repos.append(Repo(child.name, child.name))
    return repos


def iter_source_files(root: Path, exclude_dirs: Iterable[str] = (),
                      skipped: Optional[List[Tuple[Path, str]]] = None) -> Iterator[Path]:
    """Source files under root. Files too large or not stat-able are left out, and, when
    ``skipped`` is given, appended to it as (path, reason)."""
    skip = set(d.lower() for d in SKIP_DIRS) | set(str(d).lower() for d in exclude_dirs)

    def walk_error(e: OSError) -> None:
        if skipped is not None:
            skipped.append((Path(e.filename or str(root)),
                            "cannot read folder: %s" % (e.strerror or e)))
    for dirpath, dirnames, filenames in os.walk(str(root), onerror=walk_error):
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in skip)
        for name in sorted(filenames):
            if os.path.splitext(name)[1].lower() in SKIP_EXTS:
                continue
            p = Path(dirpath) / name
            try:
                st = with_long_path(os.stat, str(p))
                if not stat.S_ISREG(st.st_mode):
                    continue
                size = st.st_size
            except FileNotFoundError:
                continue  # a broken link, or a file that went away
            except OSError as e:
                if skipped is not None:
                    skipped.append((p, "cannot read file: %s" % (e.strerror or e)))
                continue
            if size > MAX_BYTES:
                if skipped is not None:
                    skipped.append((p, "larger than %d MB (%d bytes)"
                                    % (MAX_BYTES // (1024 * 1024), size)))
                continue
            yield p
