from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# This is the reviewed release authority for direct native inventory changes.
# Catalog files may change display names and discovery metadata, but they can
# never extend this set by changing a row's category. Keep the same aliases
# embedded in SBLiveAddBridge/Scripts/main.lua and verify their equality in the
# release test suite.
APPROVED_LIVE_ALIASES = frozenset(
    alias.lower()
    for alias in (
        "Item_ammo_concussion",
        "Item_ammo_peacemaker",
        "Item_ammo_scatter",
        "Item_ammo_slug",
        "Item_ammo_smartMissile",
        "Item_ConcussionGrenade",
        "Item_Fish_Slice_Bait",
        "Item_FlashGrenade",
        "Item_HealGrenade",
        "Util_Heal_L",
        "Util_Heal_M",
        "Util_Heal_S",
        "Util_Heal_XL",
        "Item_Initializer",
        "Item_Lure_megabateDX",
        "Item_Lure_Weird",
        "Item_Potion",
        "Item_Potion_Large",
        "PulseGrenade",
        "Item_Shrimp_Bait",
        "Item_Special_Bait",
        "TrapGrenade",
        "Item_Worm_Bait",
    )
)


DEFAULT_POLICY_DB: dict[str, Any] = {
    "schema": 1,
    "name": "SBCheatGUI Item Policy Database",
    "safe_stack_categories": ["Usable", "Ammo", "Fish", "Material"],
    "live_stack_categories": ["Usable", "Ammo", "Fish"],
    "singleton_categories": ["Gear", "Design", "Core", "Equipment"],
    "blocked_aliases": [
        "bodycore",
        "betacore",
        "alphacore",
        "item_betacore",
        "item_alphacore",
    ],
    "blocked_prefixes": ["quest_", "mission_"],
    "blocked_categories": ["Mission"],
    "wallet_patterns": [
        "gold",
        "coin",
        "currency",
        "omnibolt",
        "omni.?bolt",
        "vending",
        "betacrystal",
    ],
    "non_stack_save_alias_patterns": [
        "^can_\\d+",
        "^designpattern_",
        "^bs_",
        "^hair_",
        "adamcostume",
        "lilycostume",
        "droneseal",
    ],
    "levels": {
        "SAFE": "Safe backup-save target",
        "SAVE_ONLY": "Likely safe if already in save",
        "CAUTION": "Caution backup-save target",
        "BLOCKED": "Blocked",
        "MISSING": "Missing from current save",
        "NO_COUNT": "No writable count",
        "UNKNOWN": "Validate first",
    },
    "aliases": {
        "Item_Gold": {
            "level": "CAUTION",
            "text": "Save-only caution",
            "detail": "Gold maps through wallet-style save data. Validate and use Save Backup reports; Live Add stays blocked for wallet routes.",
            "save_supported": True,
            "live_supported": False,
        },
        "Item_Gold+": {
            "level": "CAUTION",
            "text": "Save-only caution",
            "detail": "Gold Pack maps through wallet-style save data. Validate and use Save Backup reports; Live Add stays blocked for wallet routes.",
            "save_supported": True,
            "live_supported": False,
        },
        "Item_Gold++": {
            "level": "CAUTION",
            "text": "Save-only caution",
            "detail": "Gold Pack (Large) maps through wallet-style save data. Validate and use Save Backup reports; Live Add stays blocked for wallet routes.",
            "save_supported": True,
            "live_supported": False,
        },
        "GearCore": {
            "level": "CAUTION",
            "text": "Caution / core record",
            "detail": "Gear Core can appear as a counted save record, but it is progression-adjacent. Validate before editing.",
            "save_supported": True,
            "live_supported": False,
        },
        "BodyCore": {
            "level": "BLOCKED",
            "text": "Blocked",
            "detail": "Body Core is progression-sensitive and is blocked from duplication.",
            "save_supported": False,
            "live_supported": False,
        },
        "BetaCore": {
            "level": "BLOCKED",
            "text": "Blocked",
            "detail": "Beta Core is progression-sensitive and is blocked from duplication.",
            "save_supported": False,
            "live_supported": False,
        },
        "AlphaCore": {
            "level": "BLOCKED",
            "text": "Blocked",
            "detail": "Alpha Core is progression-sensitive and is blocked from duplication.",
            "save_supported": False,
            "live_supported": False,
        },
    },
}


@dataclass(frozen=True)
class ItemPolicy:
    level: str
    text: str
    detail: str
    category: str = "Other"
    save_supported: bool = False
    live_supported: bool = False
    requires_validation: bool = True
    source: str = "rules"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_policy_database(mod_root: Path) -> dict[str, Any]:
    bundled_root = Path(getattr(sys, "_MEIPASS", mod_root))
    candidates = [
        mod_root / "data" / "item_policy.json",
        bundled_root / "data" / "item_policy.json",
    ]
    path = next((candidate for candidate in candidates if candidate.exists()), None)
    if path is None:
        return dict(DEFAULT_POLICY_DB)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return dict(DEFAULT_POLICY_DB)
        return _deep_merge(DEFAULT_POLICY_DB, loaded)
    except Exception:
        return dict(DEFAULT_POLICY_DB)


def policy_database_summary(policy_db: dict[str, Any], catalog_count: int = 0) -> str:
    aliases = policy_db.get("aliases") or {}
    safe = ", ".join(policy_db.get("safe_stack_categories") or [])
    live = ", ".join(policy_db.get("live_stack_categories") or [])
    return f"{catalog_count} catalog items, {len(aliases)} explicit policies, save stacks: {safe or 'none'}, live stacks: {live or 'none'}"


def _as_list(policy_db: dict[str, Any], key: str) -> list[str]:
    value = policy_db.get(key) or DEFAULT_POLICY_DB.get(key) or []
    return [str(item) for item in value]


def _alias_override(policy_db: dict[str, Any], alias: str) -> dict[str, Any] | None:
    aliases = policy_db.get("aliases") or {}
    if alias in aliases and isinstance(aliases[alias], dict):
        return aliases[alias]
    lower = alias.lower()
    for key, value in aliases.items():
        if str(key).lower() == lower and isinstance(value, dict):
            return value
    return None


def evaluate_quick_policy(alias: str, category: str = "Other", policy_db: dict[str, Any] | None = None) -> ItemPolicy:
    policy_db = policy_db or DEFAULT_POLICY_DB
    alias = (alias or "").strip()
    category = (category or "Other").strip() or "Other"
    if not alias:
        return ItemPolicy(
            level="UNKNOWN",
            text="Pick an item",
            detail="Select an item to see whether it is safe, save-only, caution, blocked, or missing from the current save.",
            category=category,
            source="empty",
        )

    override = _alias_override(policy_db, alias)
    if override:
        return ItemPolicy(
            level=str(override.get("level") or "UNKNOWN").upper(),
            text=str(override.get("text") or policy_db.get("levels", {}).get(str(override.get("level") or "UNKNOWN").upper(), "Validate first")),
            detail=str(override.get("detail") or "Explicit item policy."),
            category=category,
            save_supported=bool(override.get("save_supported", False)),
            # A catalog override can never extend the embedded allowlist.
            live_supported=bool(override.get("live_supported", False))
            and alias.lower() in APPROVED_LIVE_ALIASES,
            requires_validation=bool(override.get("requires_validation", True)),
            source="alias",
        )

    key = alias.lower()
    blocked_aliases = {item.lower() for item in _as_list(policy_db, "blocked_aliases")}
    if key in blocked_aliases or any(key.startswith(prefix.lower()) for prefix in _as_list(policy_db, "blocked_prefixes")) or category in _as_list(policy_db, "blocked_categories"):
        return ItemPolicy(
            level="BLOCKED",
            text="Blocked",
            detail="Story, mission, and main-progression items stay blocked so the panel does not corrupt progression.",
            category=category,
            source="blocked-rule",
        )

    wallet_pattern = "|".join(_as_list(policy_db, "wallet_patterns"))
    fish_gold_name = category == "Fish" and "gold" in key and not re.search(
        "coin|currency|omnibolt|omni.?bolt|vending|betacrystal", key
    )
    if wallet_pattern and re.search(wallet_pattern, key) and not fish_gold_name:
        return ItemPolicy(
            level="CAUTION",
            text="Save-only caution",
            detail="Currency/wallet-style items can share internal routes. Use validation/Save Backup reports only; Live Add stays blocked for wallet paths.",
            category=category,
            save_supported=True,
            live_supported=False,
            source="wallet-rule",
        )

    safe_categories = set(_as_list(policy_db, "safe_stack_categories"))
    live_categories = set(_as_list(policy_db, "live_stack_categories"))
    non_stack_pattern = "|".join(_as_list(policy_db, "non_stack_save_alias_patterns"))
    if category in safe_categories and not (non_stack_pattern and re.search(non_stack_pattern, key)):
                                                                               
                                                                             
                                                                              
        live_supported = category in live_categories and key in APPROVED_LIVE_ALIASES
        return ItemPolicy(
            level="SAVE_ONLY",
            text="Live Bag add supported" if live_supported else "Safe backed-up stack item",
            detail=(
                "Adds directly to the active Bag through the game's authoritative inventory route; no pickup or restart is required."
                if live_supported
                else "This counted item can use the backed-up save edit and automatic game reload fallback."
            ),
            category=category,
            save_supported=True,
            live_supported=live_supported,
            source="category-rule",
        )

    if category in set(_as_list(policy_db, "singleton_categories")):
        return ItemPolicy(
            level="CAUTION",
            text="Caution / usually singleton",
            detail="This item may be a gear, unlock, core, or cosmetic-style record. Validate first and duplicate only if you intentionally want another copy.",
            category=category,
            save_supported=True,
            live_supported=False,
            source="singleton-rule",
        )

    return ItemPolicy(
        level="UNKNOWN",
        text="Validate first",
        detail="The panel needs a save validation result before it can clearly label this item.",
        category=category,
        source="fallback",
    )


def policy_from_validation(result: dict[str, Any]) -> ItemPolicy:
    level = str(result.get("level") or result.get("status") or "UNKNOWN").upper()
    status = str(result.get("status") or level or "Unknown")
    can_add = str(result.get("canadd") or "").lower() == "true"
    detail = str(result.get("message") or result.get("detail") or "Validation finished.")
    save_alias = str(result.get("savealias") or "")
    count = str(result.get("currentcount") or "")
    fields = str(result.get("fields") or "")
    category = str(result.get("category") or "Other")
    live_supported = False

    if can_add and level == "SAFE":
        text = "Safe backup-save target"
    elif can_add:
        text = "Caution backup-save target"
        live_supported = False
    elif level in {"BLOCKED", "MISSION"} or status.lower() == "blocked":
        text = "Blocked"
        level = "BLOCKED"
        live_supported = False
    elif level == "MISSING" or status.lower() == "missing":
        text = "Missing from current save"
        live_supported = False
    elif level == "NO_COUNT":
        text = "No writable count"
        live_supported = False
    else:
        text = f"{status} - validate before adding"
        live_supported = False

    extra: list[str] = []
    if save_alias:
        extra.append(f"save alias {save_alias}")
    if count:
        extra.append(f"count {count}")
    if fields:
        extra.append(f"{fields} writable field(s)")
    if extra:
        detail = detail + " (" + ", ".join(extra) + ")"

    return ItemPolicy(
        level=level,
        text=text,
        detail=detail,
        category=category,
        save_supported=can_add,
        live_supported=live_supported,
        requires_validation=False,
        source="validation",
    )
