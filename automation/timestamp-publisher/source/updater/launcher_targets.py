"""Compiled launcher roles and canonical bundle bindings; never install authority.

Callers authenticate target bytes and parse the unchanged schema-1 notice before
using the notice helpers. Version selection comes from the compiled launcher,
never catalog data, a URL, a package or the contents of a downloaded notice.
"""
from __future__ import annotations

import re

from . import channel

_VERSION = re.compile(r"(?:0|[1-9][0-9]{0,5})(?:\.(?:0|[1-9][0-9]{0,5})){2}\Z", re.ASCII)
_PREFIX = "launcher-"
_SUFFIX = "-stable.json"
MAX_NOTICE_BINDINGS = 256  # At most 128 current plus 128 previous publisher roles.


def _version(value):
    if type(value) is not str or len(value) > 20 or not _VERSION.fullmatch(value):
        raise ValueError("A launcher baseline needs a canonical three-part version.")
    return value


def target_for_baseline(version=None):
    """Select the exact compiled baseline; explicit versions are for author tools."""
    return _PREFIX + _version(channel.LAUNCHER_VERSION if version is None else version) + _SUFFIX


def baseline_for_target(name):
    if (type(name) is not str or len(name) > len(_PREFIX) + 20 + len(_SUFFIX)
            or not name.startswith(_PREFIX) or not name.endswith(_SUFFIX)):
        raise ValueError("This is not a supported launcher baseline target.")
    return _version(name[len(_PREFIX):-len(_SUFFIX)])


def is_launcher_target(name):
    try:
        baseline_for_target(name)
        return True
    except ValueError:
        return False


def reserved_for_launcher(name):
    """Reserve even malformed/legacy launcher-family names from game bindings."""
    return type(name) is str and name.startswith(_PREFIX)


def validate_notice(name, notice):
    """Bind an already parsed schema-1 notice to its exact baseline role."""
    if notice["baseline"]["version"] != baseline_for_target(name):
        raise ValueError("The launcher notice does not match its baseline target.")
    _version(notice["version"])


def validate_canonical_notices(notices):
    """Refuse conflicting bundle/ZIP bytes in the supplied public generations.

The publisher verifies previous notice bytes against its authenticated previous
Targets before supplying them. This does not establish which repository state
is currently published: the release operator still needs the reconciled ledger.
"""
    bundles, archives = {}, {}
    for count, (name, notice) in enumerate(notices, 1):
        if count > MAX_NOTICE_BINDINGS:
            raise ValueError("Too many launcher notice bindings.")
        validate_notice(name, notice)
        for version, files in ((notice["baseline"]["version"], notice["baseline"]["files"]),
                               (notice["version"], notice["files"])):
            _version(version)
            identity = tuple(sorted((row["path"], row["size"], row["sha256"]) for row in files))
            if bundles.setdefault(version, identity) != identity:
                raise ValueError("A public launcher version has conflicting bundle bytes.")
        archive = notice["archive"]
        identity = tuple(archive[key] for key in ("url", "size", "sha256", "prefix"))
        if archives.setdefault(notice["version"], identity) != identity:
            raise ValueError("A public launcher version has conflicting archive bindings.")
