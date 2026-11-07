from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

CONFIG_NAME = "archdiag.config.json"


@dataclass
class Config:
    environment_qualifiers: List[str] = field(default_factory=list)
    exclude_dirs: List[str] = field(default_factory=list)


def load_config(out_dir: Path) -> Config:
    path = Path(out_dir) / CONFIG_NAME
    if not path.is_file():
        return Config()
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return Config(
        environment_qualifiers=[str(x) for x in data.get("environment_qualifiers", [])],
        exclude_dirs=[str(x) for x in data.get("exclude_dirs", [])],
    )
