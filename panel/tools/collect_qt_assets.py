"""Stage only artwork reachable from the production Qt Quick interface."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


ASSET_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"([A-Za-z0-9][A-Za-z0-9_.-]*\.(?:png|jpe?g|webp|svg|gif|webm|mp4))",
    re.I,
)
COMPONENT_RE = re.compile(r"\b(?:Ui\.|Pages\.)?([A-Z][A-Za-z0-9_]*)\s*\{")
SIGN_STEM_RE = re.compile(r'\bassetStem\s*:\s*"([A-Za-z0-9_-]+)"')
# Images inside the QML tree (the alpha-cut mark in DesignSystem/brand) ship
# with the QML folder, not the art folder.
QML_BUNDLED_RE = re.compile(r"DesignSystem/brand/([A-Za-z0-9][A-Za-z0-9_.-]*)")


def reachable_qml(qt_root: Path) -> list[Path]:
    qml_files = list(qt_root.rglob("*.qml"))
    by_stem = {path.stem: path for path in qml_files}
    main = qt_root / "main.qml"
    queue = [main]
    seen: set[Path] = set()

    while queue:
        path = queue.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        source = path.read_text(encoding="utf-8", errors="replace")
        for component in COMPONENT_RE.findall(source):
            candidate = by_stem.get(component)
            if candidate is not None and candidate not in seen:
                queue.append(candidate)
    return sorted(seen)


def required_brand_assets(qt_root: Path, brand_root: Path) -> tuple[list[Path], list[Path]]:
    qml_files = reachable_qml(qt_root)
    scan_files = qml_files + list((qt_root / "DesignSystem").glob("*.js"))
    names: set[str] = set()
    for path in scan_files:
        source = path.read_text(encoding="utf-8", errors="replace")
        names.update(set(ASSET_RE.findall(source)) - set(QML_BUNDLED_RE.findall(source)))
        for stem in SIGN_STEM_RE.findall(source):
            names.add(f"neon/{stem}-dimmer.png")
            names.add(f"neon/{stem}-emission.png")

    found = sorted((brand_root / name for name in names if (brand_root / name).is_file()), key=lambda p: p.as_posix().lower())
    missing = sorted((brand_root / name for name in names if not (brand_root / name).is_file()), key=lambda p: p.as_posix().lower())
    return found, missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qt-root", required=True, type=Path)
    parser.add_argument("--brand-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()

    qt_root = args.qt_root.resolve()
    brand_root = args.brand_root.resolve()
    output = args.output.resolve()
    assets, missing = required_brand_assets(qt_root, brand_root)
    output.mkdir(parents=True, exist_ok=True)
    for source in assets:
        relative = source.relative_to(brand_root)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    total = sum(path.stat().st_size for path in assets)
    lines = [
        "SBCheatGUI production asset manifest",
        f"reachable_qml={len(reachable_qml(qt_root))}",
        f"assets={len(assets)}",
        f"bytes={total}",
        "",
        *[path.relative_to(brand_root).as_posix() for path in assets],
    ]
    if missing:
        lines.extend(("", "Optional references not present:", *[path.relative_to(brand_root).as_posix() for path in missing]))
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Staged {len(assets)} production assets ({total / 1048576:.1f} MB) from {len(reachable_qml(qt_root))} reachable QML files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
