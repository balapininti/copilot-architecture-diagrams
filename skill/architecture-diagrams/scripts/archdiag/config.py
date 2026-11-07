from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

CONFIG_NAME = "archdiag.config.json"


@dataclass
class Config:
    environment_qualifiers: List[str] = field(default_factory=list)
    exclude_dirs: List[str] = field(default_factory=list)


def _names(value: object) -> List[str]:
    return [str(x) for x in value] if isinstance(value, list) else []


def load_config(out_dir: Path, notice: Optional[Callable[[str], None]] = None) -> Config:
    """archdiag.config.json from ``out_dir``. A missing file gives the defaults; one that is
    unreadable, not JSON or not an object also gives the defaults, after one plain line sent
    to ``notice`` (default: stdout)."""
    path = Path(out_dir) / CONFIG_NAME
    if not path.is_file():
        return Config()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        (notice or print)("archdiag.config.json is not valid JSON \u2014 using defaults")
        return Config()
    return Config(
        environment_qualifiers=_names(data.get("environment_qualifiers", [])),
        exclude_dirs=_names(data.get("exclude_dirs", [])),
    )
