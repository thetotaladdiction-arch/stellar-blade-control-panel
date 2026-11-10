"""Release-owned update channel. Private signing keys never belong here.

The production release process must pin its Ed25519 public key here and
publish the signed manifest before distributing the launcher. An unconfigured
checkout can open the existing panel but cannot download or install updates.
"""

TRUSTED_KEYS: dict[str, bytes] = {}
# Release-owned trust anchor and stable metadata/target directories. Never fetch
# the initial root from a server or accept a key from unverified metadata.
TUF_ROOT_JSON: bytes = b""
TUF_METADATA_URL = ""
TUF_TARGETS_URL = ""
REPOSITORY = "thetotaladdiction-arch/stellar-blade-control-panel"
APP_NAME = "Aeroneus"
# Private bootstrap version. Independent of the frozen public Mod Suite 2.6.11.
LAUNCHER_VERSION = "0.1.0"
NEXUS_URL = "https://www.nexusmods.com/stellarblade/mods/3479"
