#!/usr/bin/env python3
"""Fail if a built binary contains a hardcoded install path (plan P1).

Scans each file for the needles in ASCII and UTF-16LE, case-insensitively.
Default needle: SteamLibrary. Exit 0 = clean, 1 = found, 2 = unreadable.
"""
from __future__ import annotations

import sys
from pathlib import Path

NEEDLES = ["SteamLibrary"]


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: check_no_hardcoded_paths.py FILE...")
        return 2
    status = 0
    for name in argv:
        path = Path(name)
        try:
            blob = path.read_bytes().lower()
        except OSError as error:
            print(f"UNREADABLE {path}: {error}")
            return 2
        hits = []
        for needle in NEEDLES:
            for encoding in ("ascii", "utf-16-le"):
                offset = blob.find(needle.lower().encode(encoding))
                if offset >= 0:
                    hits.append(f"{needle!r} ({encoding}) at 0x{offset:X}")
        if hits:
            print(f"FAIL {path}: " + "; ".join(hits))
            status = 1
        else:
            print(f"OK {path}: no hardcoded install path ({len(blob)} bytes)")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
