"""Build eve.ico (multi-size) from assets/eve-mod-icon-source.png."""
from __future__ import annotations

import struct
from collections import deque
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

MOD_ROOT = Path(__file__).resolve().parents[1]
SOURCE = MOD_ROOT / "assets" / "eve-mod-icon-source.png"
OUT_ICO = MOD_ROOT / "eve.ico"
OUT_PNG = MOD_ROOT / "assets" / "eve-mod-icon-256.png"
# Windows taskbar / Start / Explorer sizes
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def strip_matte_black(img: Image.Image, threshold: int = 28) -> Image.Image:
    """Flood-fill source corner matte black to transparent (fixes square black corners)."""
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()
    q: deque[tuple[int, int]] = deque(
        (x, y) for x in (0, w - 1) for y in (0, h - 1)
    )
    seen: set[tuple[int, int]] = set()

    while q:
        x, y = q.popleft()
        if (x, y) in seen or x < 0 or y < 0 or x >= w or y >= h:
            continue
        seen.add((x, y))
        r, g, b, a = px[x, y]
        if a == 0:
            continue
        if r <= threshold and g <= threshold and b <= threshold:
            px[x, y] = (0, 0, 0, 0)
            q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))

    return img


def fit_icon_canvas(img: Image.Image, canvas: int, content_scale: float) -> Image.Image:
    """Center art on a transparent canvas with safe margins for Windows squircle masks."""
    img = img.convert("RGBA")
    side = min(img.size)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side))
    img = strip_matte_black(img)

    target = max(1, int(canvas * content_scale))
    resized = img.resize((target, target), Image.Resampling.LANCZOS)

    bg = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    offset = (canvas - target) // 2
    bg.alpha_composite(resized, (offset, offset))
    return bg


def build_frame(img: Image.Image, size: int) -> Image.Image:
    scale = 0.86 if size <= 24 else 0.90 if size <= 48 else 0.92
    frame = fit_icon_canvas(img, size, scale)
    frame = ImageEnhance.Contrast(frame).enhance(1.04)
    frame = ImageEnhance.Color(frame).enhance(1.03)
    if size <= 32:
        frame = frame.filter(ImageFilter.UnsharpMask(radius=0.7, percent=150, threshold=2))
    return frame


def count_ico_entries(path: Path) -> list[tuple[int, int]]:
    data = path.read_bytes()
    count = struct.unpack_from("<HHH", data, 0)[2]
    entries: list[tuple[int, int]] = []
    off = 6
    for _ in range(count):
        w, h, _, _, _, _, _, _ = struct.unpack_from("<BBBBHHII", data, off)
        entries.append((256 if w == 0 else w, 256 if h == 0 else h))
        off += 16
    return entries


def main() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(f"Missing source art: {SOURCE}")

    OUT_PNG.parent.mkdir(exist_ok=True)
    source = Image.open(SOURCE)
    frames = [build_frame(source, size) for size in SIZES]
    frames[-1].save(OUT_PNG, format="PNG")

    master = frames[-1]
    master.save(
        OUT_ICO,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
    )

    embedded = count_ico_entries(OUT_ICO)
    print(f"Source: {SOURCE}")
    print(f"ICO:    {OUT_ICO} ({OUT_ICO.stat().st_size} bytes)")
    print(f"Sizes:  {embedded}")
    print(f"PNG:    {OUT_PNG}")


if __name__ == "__main__":
    main()
