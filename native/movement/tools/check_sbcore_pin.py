#!/usr/bin/env python3
"""Fail unless the sbcore checkout is exactly the pinned commit with a clean tree.

Usage: check_sbcore_pin.py SBCORE_PIN.txt SBCORE_DIR
Exit 0 = pinned and clean, 1 = mismatch or dirty, 2 = unreadable / git failed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def git(directory: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_sbcore_pin.py SBCORE_PIN.txt SBCORE_DIR")
        return 2
    pin_file, sbcore_dir = Path(argv[0]), Path(argv[1])
    try:
        values = dict(
            line.split("=", 1) for line in pin_file.read_text(encoding="ascii").splitlines() if "=" in line
        )
        pinned = values["sbcore_commit"].strip().lower()
        head = git(sbcore_dir, "rev-parse", "HEAD").strip().lower()
        dirty = git(sbcore_dir, "status", "--porcelain").strip()
    except (OSError, KeyError, RuntimeError) as error:
        print(f"FAIL sbcore pin check: {error}")
        return 2
    if head != pinned:
        print(f"FAIL sbcore HEAD {head} != pinned {pinned}")
        return 1
    if dirty:
        print(f"FAIL sbcore tree is dirty:\n{dirty}")
        return 1
    print(f"OK sbcore {head} (pinned, clean)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
