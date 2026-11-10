"""Authenticated release notices using python-tuf's maintained client.

No production root is shipped in this checkout. There is no direct-feed
fallback: configuration, refresh, expiry or signature failures stop the check.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from . import channel, launcher_targets

MAX_TARGET = 2 * 1024 * 1024
MAX_ARTWORK_TARGET = 8 * 1024 * 1024
_NOTICE_LIMITS = {
    "stellar-blade-stable.json": MAX_TARGET,
    "stellar-blade-install-stable.json": MAX_TARGET,
    "catalog-stable.json": 512 * 1024,
}
_ARTWORK_TARGET = re.compile(r"assets/[a-z0-9][a-z0-9_-]{0,95}\.(?:png|jpg|jpeg|webp)\Z")


class TargetNotPublished(ValueError):
    """Only raised after trusted fresh metadata confirms this target is absent."""
    def __init__(self, target_name):
        self.target_name = target_name
        super().__init__('The authenticated channel has not published ' + target_name + '.')


def target_limit(target_name):
    """Compiled content roles; a catalog cannot supply a URL or destination."""
    if type(target_name) is not str:
        raise ValueError("The update target name is invalid.")
    if target_name in _NOTICE_LIMITS:
        return _NOTICE_LIMITS[target_name]
    if launcher_targets.is_launcher_target(target_name):
        return MAX_TARGET
    if _ARTWORK_TARGET.fullmatch(target_name):
        return MAX_ARTWORK_TARGET
    raise ValueError("This launcher does not support that update target.")


def trust_configured():
    return bool(channel.TUF_ROOT_JSON and channel.TUF_METADATA_URL and
                channel.TUF_TARGETS_URL)


def configured():
    return bool(trust_configured() and channel.TRUSTED_KEYS)


def _directory(path):
    """Use only ordinary local directories for trusted-state persistence."""
    if not path.is_absolute() or str(path).startswith("\\\\"):
        raise ValueError("The update cache must be on a local drive.")
    for part in reversed((path, *path.parents)):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("The update cache contains a redirected directory.")
        else:
            part.mkdir()


def _cache_layout(metadata, targets):
    history = metadata / "root_history"
    _directory(history)
    roots = {}
    entries = list(history.iterdir())
    if len(entries) > 512:
        raise ValueError("The update root history exceeds its supported limit.")
    for path in entries:
        info = path.lstat()
        if (not re.fullmatch(r"[1-9][0-9]{0,9}\.root\.json", path.name) or
                not stat.S_ISREG(info.st_mode) or info.st_size > 512000 or
                getattr(info, "st_file_attributes", 0) & 0x400 or info.st_nlink not in (1, 2)):
            raise ValueError("The update root history contains an unsupported entry.")
        roots[path.name] = info
    alias = metadata / "root.json"
    alias_id = None
    if alias.exists() or alias.is_symlink():
        info = alias.lstat()
        if stat.S_ISLNK(info.st_mode):
            linked = Path(os.readlink(alias))
            if linked.is_absolute() or linked.parts != ("root_history", linked.name) or linked.name not in roots:
                raise ValueError("The cached root alias points outside the root history.")
            # A symbolic alias adds no hard link. Only an actual hardlink
            # alias below may account for a second link to a history inode.
        elif (stat.S_ISREG(info.st_mode) and info.st_nlink == 2 and
              not getattr(info, "st_file_attributes", 0) & 0x400):
            alias_id = (info.st_dev, info.st_ino)
            if not any((r.st_dev, r.st_ino) == alias_id for r in roots.values()):
                raise ValueError("The cached root hardlink has no matching root history file.")
        elif (stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 512000 and
              not getattr(info, "st_file_attributes", 0) & 0x400):
            # A crash between replacing a history file and refreshing its
            # hardlink can leave the old alias as an ordinary single-link file.
            # Accept only byte identity with the named history version; never
            # trust this alias as the bootstrap or accept unrelated contents.
            try:
                raw = alias.read_bytes()
                version = json.loads(raw)["signed"]["version"]
                if type(version) is not int or not 1 <= version <= 9999999999:
                    raise ValueError
                name = f"{version}.root.json"
                if name not in roots or raw != (history / name).read_bytes():
                    raise ValueError
            except (KeyError, TypeError, ValueError, OSError) as exc:
                raise ValueError("The cached root copy does not match its root history.") from exc
        else:
            raise ValueError("The cached root alias is unsupported.")
    for info in roots.values():
        if info.st_nlink == 2 and (info.st_dev, info.st_ino) != alias_id:
            raise ValueError("The root history contains an unexpected hardlink.")
    for folder in (metadata, targets):
        entries = list(folder.iterdir())
        if len(entries) > 512:
            raise ValueError("The update cache exceeds its supported entry limit.")
        for entry in entries:
            if folder == metadata and entry.name in ("root_history", "root.json"):
                continue
            info = entry.lstat()
            maximum = MAX_ARTWORK_TARGET if folder == targets else MAX_TARGET
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum or
                    getattr(info, "st_file_attributes", 0) & 0x400):
                raise ValueError("The update cache contains an unsupported entry.")


def fetch_manifest(cancel_event=None):
    if not configured():
        raise ValueError("The authenticated update channel is not configured in this development build.")
    return fetch_target("stellar-blade-stable.json", cancel_event)


def fetch_target(target_name, cancel_event=None):
    """Refresh trusted metadata and return only a length/hash-verified target.

    Every call refreshes expiry and rollback protection, including cache hits.
    The caller must additionally validate its role-specific content schema.
    """
    maximum = target_limit(target_name)
    if not trust_configured():
        raise ValueError("The authenticated update channel is not configured in this development build.")
    if os.name != "nt":
        raise ValueError("The launcher update channel supports Windows only.")
    try:
        from tuf.ngclient import Updater
        from tuf.ngclient.config import UpdaterConfig
        from tuf.ngclient.fetcher import FetcherInterface
        from tuf.api.exceptions import DownloadHTTPError, ExpiredMetadataError, RepositoryError
        from tuf.api.metadata import Targets
    except ImportError as exc:
        raise ValueError("The update security component is missing. Reinstall the complete launcher package.") from exc
    from PySide6.QtCore import QLockFile, QCoreApplication, QEventLoop, QTimer, QUrl
    from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest
    from .client import channel_data_url
    if QCoreApplication.instance() is None:
        raise ValueError("Open the launcher to check for updates.")

    # Both roots are release-owned HTTPS locations, not supplied by a feed.
    for base in (channel.TUF_METADATA_URL, channel.TUF_TARGETS_URL):
        if not base.endswith("/"):
            raise ValueError("The authenticated update address is incomplete.")
        channel_data_url(base + "channel-check.json")
    bootstrap = channel.TUF_ROOT_JSON
    if not isinstance(bootstrap, bytes) or len(bootstrap) > 512000:
        raise ValueError("The embedded update root is invalid.")
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        raise ValueError("The local update cache location is unavailable.")
    identity = hashlib.sha256(channel.TUF_METADATA_URL.encode("utf-8")).hexdigest()[:20]
    cache = Path(local) / "Aeroneus" / "update-trust" / identity
    _directory(cache)
    metadata, targets = cache / "metadata", cache / "targets"
    _directory(metadata)
    _directory(targets)
    lock = QLockFile(str(cache / "refresh.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        raise ValueError("Another launcher is checking for updates. Try again shortly.")
    deadline = time.monotonic() + 120

    def check_deadline():
        if cancel_event is not None and cancel_event.is_set():
            raise ValueError("Update check cancelled.")
        if time.monotonic() >= deadline:
            raise ValueError("The update check took too long. Try again later.")

    class Fetcher(FetcherInterface):
        response_limit = MAX_TARGET
        maximum_response = MAX_TARGET

        @contextlib.contextmanager
        def download_file(self, url, max_length):
            # TUF supplies each metadata/target request's individual bound.
            # Apply it during Qt reads, before the base class's second check.
            if type(max_length) is not int or max_length < 0:
                raise ValueError("The update response length is invalid.")
            previous = self.response_limit
            self.response_limit = min(max_length, self.maximum_response)
            try:
                with super().download_file(url, max_length) as downloaded:
                    yield downloaded
            finally:
                self.response_limit = previous

        def _fetch(self, url):
            check_deadline()
            channel_data_url(url)
            manager = QNetworkAccessManager()
            manager.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
            for _ in range(7):
                check_deadline()
                request = QNetworkRequest(QUrl(url))
                request.setRawHeader(b"User-Agent", b"Aeroneus-Updater/1")
                request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                                     QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
                loop = QEventLoop()
                reply = manager.get(request)
                reply.setReadBufferSize(64 * 1024)
                content = bytearray()
                errors = []
                timer = QTimer()
                timer.setInterval(100)

                def abort(message):
                    errors.append(message)
                    reply.abort()
                    loop.quit()

                def tick():
                    try:
                        check_deadline()
                    except ValueError as exc:
                        abort(str(exc))

                def drain():
                    content.extend(bytes(reply.readAll()))
                    if len(content) > self.response_limit:
                        abort("The update server response exceeds its size limit.")

                reply.readyRead.connect(drain)
                reply.finished.connect(loop.quit)
                timer.timeout.connect(tick)
                timer.start()
                try:
                    loop.exec()
                    if errors:
                        raise ValueError(errors[0])
                    drain()
                    if errors:
                        raise ValueError(errors[0])
                    check_deadline()
                    status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                    redirect = reply.attribute(QNetworkRequest.Attribute.RedirectionTargetAttribute)
                    if status in (301, 302, 303, 307, 308) and redirect:
                        url = reply.url().resolved(redirect).toString()
                        channel_data_url(url, redirect=True)
                        continue
                    if status is not None and int(status) >= 400:
                        # A missing next root (404) has defined meaning in TUF.
                        raise DownloadHTTPError("Update metadata request failed.", int(status))
                    if status != 200 or reply.error() != QNetworkReply.NetworkError.NoError:
                        raise ValueError("Could not make a secure connection to the update server.")
                    yield bytes(content)
                    return
                finally:
                    timer.stop()
                    reply.deleteLater()
            raise ValueError("The update server redirected too many times.")

    try:
        _cache_layout(metadata, targets)
        fetcher = Fetcher()
        updater = Updater(str(metadata), channel.TUF_METADATA_URL,
                          target_dir=str(targets), target_base_url=channel.TUF_TARGETS_URL,
                          bootstrap=bootstrap, fetcher=fetcher,
                          config=UpdaterConfig(max_root_rotations=32, max_delegations=8,
                              root_max_length=512000, timestamp_max_length=16384,
                              snapshot_max_length=2_000_000, targets_max_length=2_000_000,
                              app_user_agent="Aeroneus/1"))
        updater.refresh()
        target = updater.get_targetinfo(target_name)
        check_deadline()
        if target is None:
            # TUF may return None after an unavailable delegated role. Only
            # a fresh authenticated flat targets role proves absence here.
            try:
                top = updater._trusted_set.targets  # Pinned python-tuf7.0.1 Targets object.
                if not isinstance(top, Targets) or not isinstance(top.targets, dict):
                    raise ValueError('The authenticated target container has an unsupported shape.')
                flat_absence = top.delegations is None and target_name not in top.targets
            except (AttributeError, KeyError, TypeError) as exc:
                raise ValueError('The channel could not prove whether an update is published.') from exc
            if not flat_absence:
                raise ValueError('The delegated channel could not prove that no update is published.')
            check_deadline()
            raise TargetNotPublished(target_name)
        if not 0 < target.length <= maximum:
            raise ValueError("The authenticated release notice is missing or too large.")
        digest = target.hashes.get("sha256", "")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("The release notice needs a SHA-256 identity.")
        # Refresh and delegated metadata keep the metadata ceiling. Only the
        # already-authenticated target body may use its artwork/content limit.
        fetcher.maximum_response = maximum
        destination = targets / (digest + ".json")
        cached = updater.find_cached_target(target, filepath=str(destination))
        check_deadline()
        if cached is None:
            updater.download_target(target, filepath=str(destination))
        check_deadline()
        with destination.open("rb") as source:
            raw = source.read(maximum + 1)
        target.verify_length_and_hashes(raw)
        check_deadline()
        return raw
    except ExpiredMetadataError as exc:
        raise ValueError("The release information has expired. Check your Windows clock and try again later. "
                         "No update will be installed from expired information.") from exc
    except RepositoryError as exc:
        raise ValueError("The update information could not be authenticated. Your installed files are unchanged.") from exc
    finally:
        lock.unlock()
