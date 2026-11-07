from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Iterator, List

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


def discover_repos(workspace: Path) -> List[Repo]:
    workspace = Path(workspace)
    if (workspace / ".git").exists():
        return [Repo(workspace.resolve().name, ".")]
    repos = []
    try:
        children = sorted(workspace.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    for child in children:
        if child.is_dir() and (child / ".git").exists():
            repos.append(Repo(child.name, child.name))
    return repos


def iter_source_files(root: Path, exclude_dirs: Iterable[str] = ()) -> Iterator[Path]:
    skip = set(SKIP_DIRS) | set(exclude_dirs)
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        for name in sorted(filenames):
            if os.path.splitext(name)[1].lower() in SKIP_EXTS:
                continue
            p = Path(dirpath) / name
            try:
                if not p.is_file() or p.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            yield p
