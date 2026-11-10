"""The Stellar Blade update adapter.

Public contract (all errors are UpdateError):
  inspect_install(game_root) -> dict: version, game_root, supported_build,
      supported, install_available, ready_for_update, blockers, recovery_transaction.
  load_signed_manifest(envelope_bytes_or_dict, pinned_keyring) -> ordinary dict.
  download_and_stage(manifest, stage_parent, cancel_event=None) -> pathlib.Path.
  apply_update(game_root, stage_dir, manifest, backup_parent) -> dict:
      transaction_dir (absolute str), status, version, files_changed.
  describe_transaction(transaction_dir) -> dict: game_root, version, status.
  rollback(transaction_dir, expected_game_root=None) -> dict.

Only load_signed_manifest issues in-process trust; saved payload dictionaries
are not verification evidence. Reload the signed envelope after restarting.
"""

__all__ = [
    "UpdateError", "inspect_install", "load_signed_manifest", "download_and_stage",
    "apply_update", "describe_transaction", "rollback",
]


def __getattr__(name):
    # Importing the library UI does not initialize the Windows update engine.
    # No placeholder implementation is supplied for an unavailable operation.
    if name in __all__:
        from . import core
        return getattr(core, name)
    raise AttributeError(name)
