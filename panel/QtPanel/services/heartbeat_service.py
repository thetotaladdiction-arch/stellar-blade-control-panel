from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LUA_HEARTBEAT_FILE = "sbcheat_heartbeat.txt"
NATIVE_HEARTBEAT_FILE = "native_heartbeat.txt"
LUA_FRESH_SEC = 8.0
NATIVE_FRESH_SEC = 15.0
LUA_ACTION_GRACE_SEC = 600.0


def file_age_sec(path: Path) -> float | None:
    if not path.exists():
        return None
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def file_fresh(path: Path, max_age: float = LUA_FRESH_SEC) -> bool:
    age = file_age_sec(path)
    return age is not None and age <= max_age


def read_kv_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in raw:
                k, v = raw.split("=", 1)
                data[k.strip()] = v.strip()
    except OSError:
        pass
    return data


@dataclass(frozen=True)
class ConnectionStatus:
    tier: str  # full | native | offline | closed
    mod_connected: bool
    lua_ready: bool
    lua_fresh: bool
    native_fresh: bool
    status_text: str
    status_detail: str
    lua_heartbeat: dict[str, str]
    native_heartbeat: dict[str, str]


def evaluate_connection(
    mod_root: Path,
    game_running: bool,
    spawn_api: str = "",
    *,
    external_ready: bool = False,
    external_active: bool = False,
    allow_legacy: bool = True,
    allow_lua: bool | None = None,
    allow_native: bool | None = None,
) -> ConnectionStatus:
    lua_allowed = allow_legacy if allow_lua is None else bool(allow_lua)
    native_allowed = allow_legacy if allow_native is None else bool(allow_native)
    lua_path = mod_root / LUA_HEARTBEAT_FILE
    native_path = mod_root / NATIVE_HEARTBEAT_FILE
    lua = read_kv_file(lua_path)
    native = read_kv_file(native_path)
    lua_fresh = file_fresh(lua_path, LUA_FRESH_SEC)
    native_fresh = file_fresh(native_path, NATIVE_FRESH_SEC)
    # The game pauses Lua while this desktop panel has focus. Keep a bounded
    # action-ready lease only after a gameplay heartbeat proved that both Eve
    # and CheatManager were loaded. Commands queue in gui_state.txt and are
    # consumed as soon as the game thread resumes.
    lua_ready = lua_allowed and (
        file_fresh(lua_path, LUA_ACTION_GRACE_SEC)
        and lua.get("cheatmanager") == "1"
        and lua.get("eve") == "1"
    )

    if not game_running:
        return ConnectionStatus(
            tier="closed",
            mod_connected=False,
            lua_ready=False,
            lua_fresh=False,
            native_fresh=native_fresh,
            status_text="Not connected — game is closed",
            status_detail="Game actions can auto-open through Steam.",
            lua_heartbeat=lua,
            native_heartbeat=native,
        )

    native_god = native.get("godlive") == "1"
    native_alive = native_allowed and native_fresh and native_god

    if lua_ready:
        api = spawn_api or lua.get("spawnapi") or "unknown"
        detail = (
            f"Lua heartbeat active • Spawn API {api}"
            if lua_fresh
            else f"Gameplay link ready • command resumes in game • Spawn API {api}"
        )
        return ConnectionStatus(
            tier="full",
            mod_connected=True,
            lua_ready=True,
            lua_fresh=lua_fresh,
            native_fresh=native_fresh,
            status_text="Connected to Stellar Blade",
            status_detail=detail,
            lua_heartbeat=lua,
            native_heartbeat=native,
        )

    if native_alive:
        hits = native.get("hits", "?")
        blocks = native.get("blocks", "0")
        learned = native.get("learned", "0")
        return ConnectionStatus(
            tier="native",
            mod_connected=True,
            lua_ready=False,
            lua_fresh=lua_fresh,
            native_fresh=True,
            status_text="Connected (native bridge)",
            status_detail=(
                f"Unsafe Lua hooks disabled — experimental SBGodNative telemetry active "
                f"(hits={hits}, blocks={blocks}, learned={learned})"
            ),
            lua_heartbeat=lua,
            native_heartbeat=native,
        )

    if external_ready:
        return ConnectionStatus(
            tier="external",
            mod_connected=True,
            lua_ready=False,
            lua_fresh=False,
            native_fresh=False,
            status_text="Connected to Stellar Blade",
            status_detail=(
                "Instant Boss Restart's game mod reported in and is on; unsafe Lua hooks stay disabled."
                if external_active
                else "Instant Boss Restart's game mod reported in (switched off); unsafe Lua hooks stay disabled."
            ),
            lua_heartbeat=lua,
            native_heartbeat=native,
        )

    if native_allowed and native_fresh and not native_god:
        return ConnectionStatus(
            tier="native",
            mod_connected=True,
            lua_ready=False,
            lua_fresh=lua_fresh,
            native_fresh=True,
            status_text="Connected (native gameplay bridge)",
            status_detail="SBGodNative is alive; God Mode is currently off and unsafe Lua hooks remain disabled.",
            lua_heartbeat=lua,
            native_heartbeat=native,
        )

    return ConnectionStatus(
        tier="offline",
        mod_connected=False,
        lua_ready=False,
        lua_fresh=lua_fresh,
        native_fresh=native_fresh,
        status_text="Game running — waiting for mod heartbeat",
        status_detail="Load into Eve; UE4SS heartbeat has not refreshed yet.",
        lua_heartbeat=lua,
        native_heartbeat=native,
    )


def health_watcher_mod_alive(mod_root: Path) -> bool:
    """True when Lua or native heartbeat is fresh — suppress soft mod reload."""
    lua_path = mod_root / LUA_HEARTBEAT_FILE
    native_path = mod_root / NATIVE_HEARTBEAT_FILE
    return file_fresh(lua_path, 120.0) or file_fresh(native_path, 120.0)


def clear_stale_heartbeat_files(
    mod_root: Path,
    stale_after_sec: float = 120.0,
    *,
    force: bool = False,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Remove stale leases without ever fabricating a connected heartbeat.

    ``force`` is reserved for a caller that has already proved the game process
    is closed. In that state even a recently written heartbeat is orphaned and
    keeping it only makes the next panel session look as if it needs repair.
    """
    removed: list[str] = []
    errors: list[str] = []
    limits = {
        LUA_HEARTBEAT_FILE: max(LUA_FRESH_SEC, float(stale_after_sec)),
        NATIVE_HEARTBEAT_FILE: max(NATIVE_FRESH_SEC, float(stale_after_sec)),
    }
    for name, limit in limits.items():
        path = Path(mod_root) / name
        if force:
            if not path.exists():
                continue
            try:
                path.unlink()
                removed.append(name)
            except OSError as exc:
                errors.append(f"{name}:{type(exc).__name__}")
            continue
        age = file_age_sec(path)
        if age is None or age <= limit:
            continue
        try:
            path.unlink()
            removed.append(name)
        except OSError as exc:
            errors.append(f"{name}:{type(exc).__name__}")
    return tuple(removed), tuple(errors)


def connection_summary_for_health(
    ctx: Any,
    hook_free_profile_safe: bool | None = None,
    native_bridge_ready: bool | None = None,
) -> tuple[str, str]:
    hook_free_safe = (
        bool(getattr(ctx, "hook_free_profile_safe", False))
        if hook_free_profile_safe is None
        else bool(hook_free_profile_safe)
    )
    native_ready = (
        bool(getattr(ctx, "native_bridge_ready", False))
        if native_bridge_ready is None
        else bool(native_bridge_ready)
    )
    conn = evaluate_connection(
        ctx.mod_root,
        ctx.game_running,
        allow_legacy=not hook_free_safe,
        allow_lua=not hook_free_safe,
        allow_native=native_ready or not hook_free_safe,
    )
    if conn.tier == "full":
        return "PASS", "Full (Lua + CheatManager)"
    if conn.tier == "native":
        return "PASS", "Native God Mode bridge (unsafe Lua hooks disabled)"
    if conn.tier == "closed":
        return "INFO", "Game closed"
    if conn.native_fresh:
        return "WARN", "Native hook alive; Lua stale"
    return "INFO", "Not connected right now"
