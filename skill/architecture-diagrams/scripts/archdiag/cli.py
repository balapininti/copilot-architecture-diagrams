from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from .config import load_config
from .scan import scan_workspace
from .store import save_json

OUT_DIR_NAME = "architecture-diagrams"


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="archdiag")
    sub = parser.add_subparsers(dest="command")
    p_scan = sub.add_parser("scan", help="scan a workspace and write inventory.json")
    p_scan.add_argument("--workspace", required=True)
    args = parser.parse_args(argv)
    if args.command != "scan":
        parser.print_usage(sys.stderr)
        return 2
    workspace = Path(args.workspace)
    out_dir = workspace / OUT_DIR_NAME
    inventory = scan_workspace(workspace, load_config(out_dir))
    save_json(out_dir / "inventory.json", inventory)
    print("Scanned %d repo(s); wrote %s" % (len(inventory.repos), out_dir / "inventory.json"))
    return 0
