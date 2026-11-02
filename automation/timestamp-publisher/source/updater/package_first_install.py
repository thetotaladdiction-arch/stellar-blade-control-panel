"""Build an UNSIGNED, exact first-install ZIP from the approved retained release.

Offline Windows/NTFS author tool. No game inspection, key handling or network.
The output directory must be new; failures retain partial outputs. Supply the
owner's immutable GitHub release asset URL explicitly. This does not publish it.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import stat
import sys
import zipfile
import zlib
from pathlib import Path

from . import core, fresh_install as fresh

PAYLOAD_NAME = "first-install-payload.json"
RECEIPT_NAME = "candidate-receipt.json"
NOTES = "First installation of the approved Stellar Blade Mod Suite 2.6.11."
MIN_FREE_BYTES = 80 * 1024**3
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def _source_index(package: zipfile.ZipFile) -> dict:
    """The caller must first verify the whole archive against compiled pins."""
    infos = package.infolist()
    if len(infos) > core.MAX_ZIP_ENTRIES:
        raise core.UpdateError("The approved archive has too many entries.")
    found, seen = {}, set()
    for entry in infos:
        name = entry.orig_filename
        directory = entry.is_dir()
        clean = name[:-1] if directory else name
        core._relative(clean, "Source ZIP path")
        if name != entry.filename or clean.casefold() in seen:
            raise core.UpdateError("The source ZIP has truncated or colliding names.")
        seen.add(clean.casefold())
        kind = stat.S_IFMT(entry.external_attr >> 16)
        if (kind not in (0, stat.S_IFDIR if directory else stat.S_IFREG)
                or entry.external_attr & (0x400 | 0x40 | 0x08)
                or entry.flag_bits & (0x01 | 0x40)
                or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
            raise core.UpdateError("The source ZIP contains a link or unsupported entry.")
        if directory or not name.startswith(fresh.APPROVED_SOURCE_PREFIX):
            continue
        path = name.removeprefix(fresh.APPROVED_SOURCE_PREFIX)
        if path not in fresh.ALLOWED_FILES:
            raise core.UpdateError("The source game subtree contains an unowned file.")
        core._integer(entry.file_size, 0, core.MAX_FILE_BYTES, "Source member size")
        if entry.file_size > max(1, entry.compress_size) * core.MAX_COMPRESSION_RATIO:
            raise core.UpdateError("The source member exceeds the compression ratio limit.")
        found[path] = entry
    if set(found) != set(fresh.ALLOWED_FILES) or len(found) != 42:
        raise core.UpdateError("The source must contain all and only the 42 owned files.")
    if sum(entry.file_size for entry in found.values()) > core.MAX_UNCOMPRESSED_BYTES:
        raise core.UpdateError("The source inventory exceeds its expanded size limit.")
    return found


def _transfer(source, size: int, output=None) -> dict:
    digest, total = hashlib.sha256(), 0
    while True:
        data = source.read(min(core.IO_CHUNK, size - total + 1))
        if not data:
            break
        total += len(data)
        if total > size:
            raise core.UpdateError("A ZIP member exceeds its declared size.")
        digest.update(data)
        if output is not None:
            output.write(data)
    if total != size:
        raise core.UpdateError("A ZIP member is shorter than its declared size.")
    return {"size": total, "sha256": digest.hexdigest()}


def _inventory(package: zipfile.ZipFile, entries: dict) -> list[dict]:
    files = []
    for path in sorted(entries):
        with package.open(entries[path]) as source:
            spec = {"path": path, **_transfer(source, entries[path].file_size)}
        if path in fresh.BOOTSTRAP_FILES:
            if (spec["size"], spec["sha256"]) != fresh.BOOTSTRAP_FILES[path]:
                raise core.UpdateError("A bootstrap file differs from the approved bytes.")
        if path in core.APPROVED_RUNTIME:
            if (spec["size"], spec["sha256"]) != core.APPROVED_RUNTIME[path]:
                raise core.UpdateError("A runtime file differs from the approved bytes.")
        files.append(spec)
    with package.open(entries[core.VERSION_PATH]) as source:
        if source.read(64).decode("ascii").strip() != fresh.APPROVED_SOURCE_VERSION:
            raise core.UpdateError("The approved source VERSION is inconsistent.")
    return files


def _write_archive(package, entries, files, stream) -> None:
    # Fixed order, metadata and compression settings; no source times/ACLs.
    # Reproducibility is bound to the recorded Python/zlib toolchain.
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9, allowZip64=False) as output:
        for spec in files:
            info = zipfile.ZipInfo(spec["path"], date_time=FIXED_TIME)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            info._compresslevel = 9
            info.file_size = spec["size"]
            with package.open(entries[spec["path"]]) as source, output.open(info, "w") as target:
                actual = _transfer(source, spec["size"], target)
            if actual != {k: spec[k] for k in ("size", "sha256")}:
                raise core.UpdateError("Source bytes changed during packaging.")
    stream.flush()
    os.fsync(stream.fileno())


def _payload(url: str, archive: dict, files: list) -> dict:
    payload = {
        "schema": 1, "product": core.PRODUCT, "operation": fresh.OPERATION,
        "version": fresh.APPROVED_SOURCE_VERSION, "build_id": core.SUPPORTED_BUILD_ID,
        "archive": {"url": url, "size": archive["size"], "sha256": archive["sha256"], "prefix": ""},
        "files": files, "notes": NOTES,
    }
    # Validate the exact serialized payload, including the compiled URL policy.
    return fresh._validate_payload(core._json(core._canonical(payload), core.MAX_PAYLOAD_BYTES, "Payload"))


def _verify_archive(stream, payload: dict) -> None:
    package, entries = core._zip_index(stream, payload)
    with package:
        if len(package.infolist()) != 42:
            raise core.UpdateError("The narrow ZIP must contain exactly 42 files and no directory records.")
        for spec in payload["files"]:
            with package.open(entries[spec["path"]]) as source:
                actual = _transfer(source, spec["size"])
            if actual != {k: spec[k] for k in ("size", "sha256")}:
                raise core.UpdateError("The generated ZIP failed independent member readback.")


def _write_json(path: Path, value) -> dict:
    raw = core._canonical(value)
    with core._HeldFile(path, create=True) as output:
        output.fp.write(raw)
        output.fp.flush()
        os.fsync(output.fp.fileno())
        pin = output.fingerprint(core.MAX_JOURNAL_BYTES)
        if (pin["size"], pin["sha256"]) != (len(raw), hashlib.sha256(raw).hexdigest()):
            raise core.UpdateError("An output JSON failed readback.")
    return {k: pin[k] for k in ("size", "sha256")}


def build(source_zip, output_dir, asset_url: str) -> dict:
    """Create a new candidate; never sign it or grant installation authority."""
    parts = core._url(asset_url, initial=True)
    asset_name = parts.path.rsplit("/", 1)[1]
    core._relative(asset_name, "Asset filename")
    source_path, output_path = core._absolute(source_zip), core._absolute(output_dir)
    if fresh.APPROVED_SOURCE_VERSION != "2.6.11":
        raise core.UpdateError("This packager requires the reviewed 2.6.11 source policy.")
    try:
        core._ntfs(output_path)
        with core._Guard() as guard:
            guard.directory(source_path.parent)
            guard.directory(output_path.parent)
            if core._exists(output_path):
                raise core.UpdateError("Candidate directory already exists; choose a new directory.")
            with core._HeldFile(source_path) as source:
                source_pin = source.fingerprint(fresh.APPROVED_SOURCE_ARCHIVE_SIZE)
                if (source_pin["size"], source_pin["sha256"]) != (
                        fresh.APPROVED_SOURCE_ARCHIVE_SIZE, fresh.APPROVED_SOURCE_ARCHIVE_SHA256):
                    raise core.UpdateError("Source ZIP does not match the compiled approved archive pins.")
                # The complete approved byte hash is checked before ZIP parsing.
                with zipfile.ZipFile(source.fp) as package:
                    entries = _source_index(package)
                    files = _inventory(package, entries)
                    total = sum(spec["size"] for spec in files)
                    core._space(output_path.parent, MIN_FREE_BYTES + 2 * total + 16 * 1024**2)
                    output_path.mkdir(mode=0o700)  # Exclusive; never reuse a partial candidate.
                    guard.directory(output_path)
                    with core._HeldFile(output_path / asset_name, create=True) as archive:
                        _write_archive(package, entries, files, archive.fp)
                        archive_pin = archive.fingerprint(core.MAX_ARCHIVE_BYTES)
                        payload = _payload(asset_url, archive_pin, files)
                        _verify_archive(archive.fp, payload)
                        after_pin = archive.fingerprint(core.MAX_ARCHIVE_BYTES)
                        if archive_pin != after_pin:
                            raise core.UpdateError("Generated archive changed during verification.")
                        payload_pin = _write_json(output_path / PAYLOAD_NAME, payload)
                        if source.fingerprint(fresh.APPROVED_SOURCE_ARCHIVE_SIZE) != source_pin:
                            raise core.UpdateError("Approved source changed during packaging.")
                        receipt = {
                            "schema": 1, "status": "unsigned-candidate-verified", "signed": False,
                            "source": {"path": str(source_path), "prefix": fresh.APPROVED_SOURCE_PREFIX,
                                       **{k: source_pin[k] for k in ("size", "sha256")}},
                            "archive": {"file": asset_name, **payload["archive"]},
                            "payload": {"file": PAYLOAD_NAME, **payload_pin},
                            "inventory": files, "file_count": len(files), "expanded_size": total,
                            "bootstrap_files": sorted(fresh.BOOTSTRAP_FILES),
                            "checks": ["compiled-source-pins", "exact-42-inventory", "bootstrap-byte-pins",
                                       "version-2.6.11", "full-payload-schema", "compiled-github-authority",
                                       "zip-index-policy", "all-member-readback", "source-unchanged"],
                            "toolchain": {"python": platform.python_version(), "zlib": zlib.ZLIB_RUNTIME_VERSION,
                                          "compression": "deflate-9", "zip_time": list(FIXED_TIME)},
                        }
                        _write_json(output_path / RECEIPT_NAME, receipt)  # Completion marker, always last.
                        return receipt
    except core.UpdateError:
        raise
    except (OSError, ValueError, RuntimeError, UnicodeError, zipfile.BadZipFile, zlib.error) as exc:
        raise core.UpdateError("Packaging failed; partial outputs were retained. Use a new candidate directory.") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--asset-url", required=True, help="Owner-supplied immutable release asset URL; no default.")
    args = parser.parse_args()
    try:
        result = build(args.source_zip, args.output_dir, args.asset_url)
    except core.UpdateError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(core._canonical({"status": result["status"], "output_dir": str(args.output_dir),
                           "archive": result["archive"], "payload": result["payload"]}).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
