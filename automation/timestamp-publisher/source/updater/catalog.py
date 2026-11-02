"""Strict, data-only launcher catalog and bounded static artwork decoding.

Parsing is not authentication. Remote bytes must come from the refreshed TUF
target boundary. Nothing in this schema is an executable, URL, module name,
install path or command. Render all display strings as plain text.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
import struct
import unicodedata
import zlib

from . import launcher_targets

CATALOG_TARGET = "catalog-stable.json"
MAX_CATALOG_BYTES = 512 * 1024
MAX_GAMES = 64
MAX_ART_BYTES = 8 * 1024 * 1024
MAX_ART_SIDE = 8192
MAX_ART_PIXELS = 16 * 1024 * 1024
MAX_VALIDITY = timedelta(days=31)
_IDENTIFIER = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z", re.ASCII)
_TARGET = re.compile(r"[a-z][a-z0-9]*(?:[-.][a-z0-9]+)*\.json\Z", re.ASCII)
_ART_TARGET = re.compile(r"assets/[a-z0-9][a-z0-9_-]{0,95}\.png\Z", re.ASCII)
_VERSION = re.compile(r"(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){2,3}\Z", re.ASCII)
_UTC_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z", re.ASCII)
_RESERVED = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)),
                       *(f"lpt{i}" for i in range(10))})


class CatalogError(ValueError):
    """A catalog or artwork input was refused without changing game files."""


def integer(value, minimum: int, maximum: int, label: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CatalogError(f"Invalid {label}.")
    return value


def shape(value, required: set[str], optional: set[str], label: str) -> dict:
    if type(value) is not dict or not required <= value.keys() or value.keys() - required - optional:
        raise CatalogError(f"Unsupported {label} fields.")
    return value


def text(value, maximum: int, label: str, *, empty: bool = False) -> str:
    if (type(value) is not str or len(value) > maximum or (not value and not empty)
            or value != value.strip() or any(c in "<>" or unicodedata.category(c)[0] == "C" for c in value)):
        raise CatalogError(f"Invalid {label} text.")
    return value


def identifier(value, label: str = "identifier") -> str:
    if type(value) is not str or len(value) > 64 or not _IDENTIFIER.fullmatch(value):
        raise CatalogError(f"Invalid {label}.")
    return value


def target_name(value, *, artwork: bool = False) -> str:
    pattern = _ART_TARGET if artwork else _TARGET
    if (type(value) is not str or len(value) > 128 or not pattern.fullmatch(value)
            or value.rsplit("/", 1)[-1].split(".", 1)[0] in _RESERVED
            or (not artwork and launcher_targets.reserved_for_launcher(value))):
        raise CatalogError("Invalid catalog target name.")
    return value


def utc_time(value, label: str = "timestamp") -> datetime:
    if type(value) is not str or not _UTC_TIME.fullmatch(value):
        raise CatalogError(f"Invalid {label}.")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise CatalogError(f"Invalid {label}.") from exc


def utc_now(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CatalogError("A timezone-aware clock is required.")
    return value.astimezone(timezone.utc)


def format_time(value: datetime) -> str:
    return utc_now(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError("Duplicate JSON field.")
        result[key] = value
    return result


def _bad_number(_value):
    raise CatalogError("Only bounded integer JSON numbers are supported.")


def _json_int(value):
    if len(value) > 16:
        raise CatalogError("JSON integer exceeds its limit.")
    return int(value)


def bounded_json(raw: bytes, limit: int = MAX_CATALOG_BYTES):
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        raise CatalogError("Catalog data exceeds its byte limit or is empty.")
    try:
        decoded = raw.decode("utf-8", errors="strict")
        # Check nesting before json.loads can allocate a deep object graph.
        depth, quoted, escaped = 0, False, False
        for char in decoded:
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                depth += 1
                if depth > 8:
                    raise CatalogError("Catalog JSON is nested too deeply.")
            elif char in "]}":
                depth -= 1
        return json.loads(decoded, object_pairs_hook=_pairs, parse_int=_json_int,
                          parse_float=_bad_number, parse_constant=_bad_number)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise CatalogError("Invalid bounded UTF-8 catalog JSON.") from exc


@dataclass(frozen=True)
class Artwork:
    target: str
    width: int
    height: int
    media_type: str = "image/png"


@dataclass(frozen=True)
class Game:
    id: str
    title: str
    summary: str
    adapter: str | None
    status: str
    version: str | None
    release_target: str | None
    artwork: Artwork | None


@dataclass(frozen=True)
class Catalog:
    revision: int
    issued_at: datetime
    expires_at: datetime
    games: tuple[Game, ...]

    def require_current(self, now: datetime) -> None:
        if not self.issued_at <= utc_now(now) < self.expires_at:
            raise CatalogError("The catalog is expired or not yet valid.")


def parse_catalog(raw: bytes) -> Catalog:
    obj = shape(bounded_json(raw), {"schema_version", "revision", "issued_at", "expires_at", "games"},
                set(), "catalog")
    integer(obj["schema_version"], 1, 1, "catalog schema")
    revision = integer(obj["revision"], 1, 2**53 - 1, "catalog revision")
    issued, expires = utc_time(obj["issued_at"]), utc_time(obj["expires_at"])
    if not timedelta(0) < expires - issued <= MAX_VALIDITY:
        raise CatalogError("The catalog validity interval exceeds its limit.")
    if type(obj["games"]) is not list or len(obj["games"]) > MAX_GAMES:
        raise CatalogError("Too many catalog cards.")
    games, ids, releases, artwork_specs = [], set(), set(), {}
    for row in obj["games"]:
        shape(row, {"id", "title", "summary", "adapter", "status"},
              {"version", "release_target", "artwork"}, "game")
        game_id = identifier(row["id"], "game identifier")
        if game_id in ids:
            raise CatalogError("Duplicate game identifier.")
        ids.add(game_id)
        title = text(row["title"], 100, "game title")
        summary = text(row["summary"], 600, "game summary", empty=True)
        adapter = None if row["adapter"] is None else identifier(row["adapter"], "adapter identifier")
        status = row["status"]
        if type(status) is not str or status not in {"available", "unavailable", "coming-soon"}:
            raise CatalogError("Unknown catalog availability.")
        version = row.get("version")
        if version is not None and (type(version) is not str or not _VERSION.fullmatch(version)):
            raise CatalogError("Invalid catalog version.")
        release = row.get("release_target")
        if release is not None:
            release = target_name(release)
            if release in releases or release in {CATALOG_TARGET, "launcher-stable.json"}:
                raise CatalogError("Conflicting catalog release target.")
            releases.add(release)
        if status == "available" and (adapter is None or version is None or release is None):
            raise CatalogError("An available card needs an adapter, version and release target.")
        art = row.get("artwork")
        if art is not None:
            shape(art, {"target", "width", "height", "media_type"}, set(), "artwork")
            if art["media_type"] != "image/png":
                raise CatalogError("Only static RGB or RGBA PNG artwork is supported.")
            name = target_name(art["target"], artwork=True)
            width = integer(art["width"], 1, MAX_ART_SIDE, "artwork width")
            height = integer(art["height"], 1, MAX_ART_SIDE, "artwork height")
            if width * height > MAX_ART_PIXELS:
                raise CatalogError("Artwork exceeds its pixel limit.")
            art = Artwork(name, width, height)
            if name in artwork_specs and art != artwork_specs[name]:
                raise CatalogError("Conflicting artwork declarations.")
            artwork_specs[name] = art
        games.append(Game(game_id, title, summary, adapter, status, version, release, art))
    return Catalog(revision, issued, expires, tuple(games))


def local_seed(now: datetime) -> bytes:
    """Built-in fallback, parsed by the same schema, with no release availability."""
    now = utc_now(now).replace(microsecond=0)
    return json.dumps({"schema_version": 1, "revision": 1, "issued_at": format_time(now),
                       "expires_at": format_time(now + MAX_VALIDITY), "games": [
        {"id": "stellar-blade", "title": "Stellar Blade", "adapter": "stellar-blade",
         "summary": "Manage an existing supported Mod Suite installation. Connect to the authenticated channel to check releases.",
         "status": "unavailable"},
    ]}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def validate_artwork(raw: bytes, art: Artwork) -> bytes:
    """Preflight a deliberately narrow PNG subset before any native decoder.

    Only IHDR, IDAT and IEND are accepted: no animation, profiles, compressed
    text, external metadata, palette, 16-bit samples or interlacing. Inflation
    is bounded to the exact declared scanline size (at most ~64 MiB).
    """
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_ART_BYTES or raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise CatalogError("Invalid or oversized PNG artwork.")
    integer(art.width, 1, MAX_ART_SIDE, "artwork width")
    integer(art.height, 1, MAX_ART_SIDE, "artwork height")
    if art.media_type != "image/png" or art.width * art.height > MAX_ART_PIXELS:
        raise CatalogError("Unsupported artwork dimensions or format.")
    offset, chunks, channels, seen_end = 8, 0, 0, False
    compressed = bytearray()
    while offset < len(raw):
        chunks += 1
        if chunks > 1024 or offset + 12 > len(raw):
            raise CatalogError("Malformed PNG chunks.")
        length = struct.unpack_from(">I", raw, offset)[0]
        end = offset + 12 + length
        if end > len(raw):
            raise CatalogError("Truncated PNG chunk.")
        kind = raw[offset + 4:offset + 8]
        payload = raw[offset + 8:end - 4]
        crc = struct.unpack_from(">I", raw, end - 4)[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != crc:
            raise CatalogError("Corrupt PNG chunk.")
        if chunks == 1:
            if kind != b"IHDR" or length != 13:
                raise CatalogError("Missing PNG header.")
            w, h, bits, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if ((w, h) != (art.width, art.height) or bits != 8 or color not in (2, 6)
                    or (compression, filtering, interlace) != (0, 0, 0)):
                raise CatalogError("Unsupported PNG header or dimensions.")
            channels = 3 if color == 2 else 4
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND" and length == 0 and compressed and end == len(raw):
            seen_end = True
        else:
            raise CatalogError("Unsupported PNG chunk or trailing data.")
        offset = end
    if not seen_end:
        raise CatalogError("Incomplete PNG artwork.")
    expected = (art.width * channels + 1) * art.height
    try:
        inflater = zlib.decompressobj()
        pixels = inflater.decompress(compressed, expected + 1)
        if (len(pixels) != expected or not inflater.eof or inflater.unconsumed_tail or inflater.unused_data
                or any(pixels[row] > 4 for row in range(0, expected, art.width * channels + 1))):
            raise CatalogError("PNG scanlines exceed their limit or are malformed.")
    except zlib.error as exc:
        raise CatalogError("Invalid PNG compression.") from exc
    return raw


def decode_artwork(raw: bytes, art: Artwork):
    """Return a CPU QImage, never a path or QPixmap; no application is opened."""
    validate_artwork(raw, art)
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    from PySide6.QtGui import QImage, QImageReader

    buffer = QBuffer()
    buffer.setData(QByteArray(raw))
    if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
        raise CatalogError("Could not open artwork data.")
    try:
        reader = QImageReader(buffer, b"png")
        reader.setAutoDetectImageFormat(False)
        reader.setDecideFormatFromContent(False)
        reader.setAutoTransform(False)
        size = reader.size()
        if (size.width(), size.height()) != (art.width, art.height) or reader.supportsAnimation():
            raise CatalogError("Artwork decoder dimensions or format disagree.")
        result = reader.read()
        if result.isNull() or (result.width(), result.height()) != (art.width, art.height):
            raise CatalogError("Artwork could not be decoded.")
        result = result.convertToFormat(QImage.Format.Format_RGBA8888)
        if result.isNull() or result.sizeInBytes() > MAX_ART_PIXELS * 4:
            raise CatalogError("Decoded artwork exceeds its limit.")
        return result
    finally:
        buffer.close()
