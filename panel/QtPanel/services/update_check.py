"""Quiet update notice: is a newer panel version out?

The release step publishes a small ``version.json`` next to the release zip on
Google Drive::

    {"version": "2.6.1", "url": "https://drive.google.com/..."}

and writes that file's Drive id into ``update_source.json`` next to the
panel's ``VERSION`` file::

    {"version_file_id": "<FILE_ID>", "download_page": "https://drive.google.com/..."}

Rules this module keeps (the Backend runs it):

* At most once a day, in the background, with a short timeout. Any failure
  (offline, Drive's HTML page instead of JSON, a bad file) is silent: no
  message, no retry until the next day.
* No file id -> no check at all.
* Nothing is downloaded or installed. A newer version only shows one quiet
  line with a button that opens the download page in the browser, and only
  ``https`` links to the hosts below are ever opened.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

# The one place the version file's address is built.
VERSION_URL_TEMPLATE = "https://drive.google.com/uc?export=download&id={file_id}"
SOURCE_FILE_NAME = "update_source.json"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
TIMEOUT_SECONDS = 6.0
MAX_BYTES = 64 * 1024
ALLOWED_DOWNLOAD_HOSTS = frozenset({
    "drive.google.com",
    "docs.google.com",
    "drive.usercontent.google.com",
    "www.nexusmods.com",
    "nexusmods.com",
    "github.com",
})
_FILE_ID = re.compile(r"[A-Za-z0-9_-]{10,200}")
_VERSION = re.compile(r"v?([0-9]+(?:\.[0-9]+)*)(?: build [A-Za-z0-9][A-Za-z0-9._-]*)?")
MAX_VERSION_CHARS = 40


@dataclass(frozen=True)
class UpdateSource:
    version_url: str = ""
    download_page: str = ""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str = ""


def safe_download_url(url: object) -> str:
    """``url`` when it is an https link to a known download host, else ""."""
    text = str(url or "").strip()
    try:
        parts = urlsplit(text)
    except ValueError:
        return ""
    if parts.scheme != "https" or (parts.hostname or "").casefold() not in ALLOWED_DOWNLOAD_HOSTS:
        return ""
    if parts.username or parts.password or any(ch.isspace() for ch in text):
        return ""
    return text


def read_update_source(mod_root: Path) -> UpdateSource:
    """The version file's URL from ``update_source.json`` (empty when unset)."""
    try:
        data = json.loads((Path(mod_root) / SOURCE_FILE_NAME).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return UpdateSource()
    if not isinstance(data, dict):
        return UpdateSource()
    file_id = str(data.get("version_file_id") or "").strip()
    url = VERSION_URL_TEMPLATE.format(file_id=file_id) if _FILE_ID.fullmatch(file_id) else ""
    return UpdateSource(url, safe_download_url(data.get("download_page")))


def parse_version(text: object) -> tuple[int, ...] | None:
    """Bounded version/build syntax; reject controls before converting any digits."""
    value = str(text or "")
    if len(value) > MAX_VERSION_CHARS or any(ch.isspace() and ch != " " for ch in value):
        return None
    match = _VERSION.fullmatch(value.strip(" "))
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(candidate: object, current: object) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    if new is None or old is None:
        return False
    width = max(len(new), len(old))
    return new + (0,) * (width - len(new)) > old + (0,) * (width - len(old))


def parse_version_file(raw: bytes) -> UpdateInfo | None:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    if not isinstance(version, str) or parse_version(version) is None:
        return None
    return UpdateInfo(version.strip(" "), safe_download_url(data.get("url") or data.get("download_url")))


def check_due(last_checked: float, now: float, interval: float = CHECK_INTERVAL_SECONDS) -> bool:
    """True once a day; a clock that went backwards also allows a check."""
    return last_checked <= 0 or now - last_checked >= interval or now < last_checked


def fetch_update_info(url: str, opener=urllib.request.urlopen, timeout: float = TIMEOUT_SECONDS) -> UpdateInfo | None:
    """Read the version file; None on any failure (never raises)."""
    if not url:
        return None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "StellarBladeModSuite-UpdateCheck"})
        with opener(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return None
        return parse_version_file(raw)
    except Exception:  # noqa: BLE001 - any failure is silent (offline, blocked, bad reply)
        return None
