from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Tuple

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
    skip = set(SKIP_DIRS) | set(exclude_dirs)
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        for name in sorted(filenames):
            if os.path.splitext(name)[1].lower() in SKIP_EXTS:
                continue
            p = Path(dirpath) / name
            try:
                if not p.is_file():
                    continue
                size = p.stat().st_size
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
