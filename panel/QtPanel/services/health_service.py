from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.god_service import (
    get_god_pak_state,
    prepare_live_god_mode,
    read_state_wants_on,
    repair_god_file_set,
)
from services.boss_retry_service import (
    enforce_hook_free_retry_profile,
    inspect_hook_free_retry_profile,
)
from services.heartbeat_service import (
    clear_stale_heartbeat_files,
    connection_summary_for_health,
)
from services.instant_boss_restart import MOD_FOLDER as BOSS_RESTART_FOLDER
from services.instant_boss_restart import ensure_marker, inspect_install


@dataclass(frozen=True)
class HealthContext:
    mod_root: Path
    qt_root: Path
    assets_dir: Path
    version_file: Path
    state_file: Path
    save_tools: Path
    support_script: Path
    support_reports_dir: Path
    paks_mods_dir: Path
    disabled_paks_dir: Path
    catalog_count: int
    game_running: bool
    mod_connected: bool
    default_state: dict[str, str]
    item_policy_file: Path | None = None
    game_exe: Path | None = None
    app_manifest_file: Path | None = None
    steam_exe_candidates: list[Path] | None = None
    hook_free_profile_safe: bool = False


def _write_kv_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(f"{k}={v}" for k, v in data.items()) + "\n", encoding="utf-8")
    tmp.replace(path)


def _save_roots() -> list[Path]:
    roots: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "SB" / "Saved" / "SaveGames")
    profile = os.environ.get("USERPROFILE")
    if profile:
        roots.append(Path(profile) / "Documents" / "My Games" / "SB" / "Saved" / "SaveGames")
    return [p for p in roots if p.exists()]


def _write_health_report(ctx: HealthContext, title: str, rows: list[tuple[str, str, str]], actions: list[str]) -> dict[str, Any]:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    ctx.support_reports_dir.mkdir(parents=True, exist_ok=True)
    report = ctx.support_reports_dir / f"{title.replace(' ', '')}-{stamp}.txt"
    fail = sum(1 for level, _, _ in rows if level == "FAIL")
    warn = sum(1 for level, _, _ in rows if level == "WARN")
    fixed = sum(1 for level, _, _ in rows if level == "FIXED")
    # Plain words: this summary is also the Support toast.
    def things(count: int, word: str) -> str:
        return f"{count} {word}" + ("" if count == 1 else "s")

    if fail:
        level = "FAIL"
        summary = f"{things(fail, 'problem')} to fix"
        if warn:
            summary += f", {things(warn, 'thing')} to check"
    elif warn:
        level = "WARN"
        summary = f"Ready, with {things(warn, 'thing')} to check"
    else:
        level = "OK"
        summary = "Everything important is ready"
    if fixed:
        summary += f" ({fixed} fixed)"

    version = "unknown"
    try:
        version = ctx.version_file.read_text(encoding="utf-8").strip()
    except Exception:
        pass

    lines = [
        f"SBCheatGUI {title}",
        f"Created: {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
        f"Version: {version}",
        f"Result: {level} - {summary}",
        "",
        "Checks:",
    ]
    for row_level, name, detail in rows:
        lines.append(f"{row_level:5} | {name} | {detail}")
    if actions:
        lines.extend(["", "Repair actions:"])
        lines.extend(f"- {action}" for action in actions)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    detail = "\n".join(f"{row_level}: {name} - {detail}" for row_level, name, detail in rows[-8:])
    return {"ok": fail == 0, "level": level, "summary": summary, "detail": detail, "report": str(report)}


def run_health_check(ctx: HealthContext, repair: bool = False) -> dict[str, Any]:
    rows: list[tuple[str, str, str]] = []
    actions: list[str] = []

    def add(level: str, name: str, detail: str) -> None:
        rows.append((level, name, detail))

    add("PASS" if ctx.mod_root.exists() else "FAIL", "Mod folder", str(ctx.mod_root))
    add("PASS" if ctx.version_file.exists() else "FAIL", "VERSION file", str(ctx.version_file))
    qml_ok = (ctx.mod_root / "QtPanel" / "main.qml").exists() or (ctx.qt_root / "main.qml").exists()
    add("PASS" if qml_ok else "FAIL", "Qt panel QML", "main.qml")
    add("PASS", "Save editing", "Excluded from the public safe profile; SaveTools.ps1 is not required")
    add("PASS" if ctx.support_script.exists() else "FAIL", "Support report script", str(ctx.support_script))
    if ctx.game_exe is not None:
        add("PASS" if ctx.game_exe.exists() else "FAIL", "Game executable", str(ctx.game_exe))
    if ctx.app_manifest_file is not None:
        add("PASS" if ctx.app_manifest_file.exists() else "WARN", "Steam app manifest", str(ctx.app_manifest_file))
    if ctx.steam_exe_candidates:
        steam_found = next((path for path in ctx.steam_exe_candidates if path.exists()), None)
        detail = str(steam_found) if steam_found else ", ".join(str(path) for path in ctx.steam_exe_candidates)
        add("PASS" if steam_found else "WARN", "Steam client", detail)
    add("PASS" if (ctx.assets_dir / "brand" / "liquid-glass-hero.png").exists() else "WARN", "Custom artwork", str(ctx.assets_dir / "brand"))
    # Item/save tooling is retained only in the private development tree. It is
    # not part of the public feature surface and therefore cannot make public
    # install health stale or yellow.

    if repair:
        ctx.support_reports_dir.mkdir(parents=True, exist_ok=True)
        (ctx.support_reports_dir / "SaveBackups").mkdir(parents=True, exist_ok=True)
        actions.append("Ensured SupportReports and SaveBackups folders exist.")

    try:
        ctx.support_reports_dir.mkdir(parents=True, exist_ok=True)
        probe = ctx.support_reports_dir / ".healthcheck.tmp"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
        add("PASS", "Reports folder writable", str(ctx.support_reports_dir))
    except Exception as exc:
        add("FAIL", "Reports folder writable", str(exc))

    if repair and not ctx.state_file.exists():
        _write_kv_atomic(ctx.state_file, ctx.default_state)
        actions.append("Created missing gui_state.txt with safe defaults.")
        add("FIXED", "gui_state.txt", "Created safe default state file.")
    else:
        add("PASS" if ctx.state_file.exists() else "WARN", "gui_state.txt", str(ctx.state_file))

    # No hotkeys.ini row: none of the shipped game mods reads it (RELEASE-GATE
    # B5). No "Boss Retry helper" row either: it checked Mods/BossAutoReturn,
    # the legacy Lua helper the player package never ships, so every player
    # install showed a warning (B11). Instant Boss Restart is the
    # SBInstantBossRestart game mod: its approved script and its UE4SS
    # enabled.txt (Repair puts back a missing one; it loads at the next game
    # start). Its on/off switch is the player's choice and is not checked.
    boss_folder = ctx.mod_root.parent / BOSS_RESTART_FOLDER
    boss = inspect_install(boss_folder)
    if not boss.installed:
        add("FAIL", "Instant Boss Restart game mod", f"missing: {boss_folder / 'Scripts' / 'main.lua'}")
    elif not boss.trusted:
        add("FAIL", "Instant Boss Restart game mod", f"not the approved version ({boss.identity[:12]})")
    elif boss.marker:
        add("PASS", "Instant Boss Restart game mod", f"{BOSS_RESTART_FOLDER} {boss.version}")
    elif repair and ensure_marker(boss_folder):
        actions.append("Turned the Instant Boss Restart game mod back on (enabled.txt).")
        add("FIXED", "Instant Boss Restart game mod", "enabled.txt put back; it starts with the next game start")
    else:
        add("WARN", "Instant Boss Restart game mod", "enabled.txt is missing, so UE4SS doesn't load it")

    profile = (
        enforce_hook_free_retry_profile(ctx.mod_root.parent)
        if repair
        else inspect_hook_free_retry_profile(ctx.mod_root.parent)
    )
    if profile.safe:
        profile_level = "FIXED" if profile.changed else "PASS"
        profile_detail = (
            "Disabled unsafe UE4SS hooks and repaired the native gameplay bridge; restart Stellar Blade once."
            if profile.changed and ctx.game_running
            else (
                "Unsafe Lua/retry hooks are disabled; SBGodNative is enabled for live God Mode."
                if profile.native_bridge_ready
                else "Unsafe in-process UE4SS modules are disabled."
            )
        )
        add(profile_level, "Game mod safety profile", profile_detail)
        if profile.changed:
            actions.append(
                "Disabled unsafe in-process hooks and enabled the shutdown-hardened native gameplay bridge."
            )
            if ctx.game_running:
                add("WARN", "Game restart needed", "Restart Stellar Blade once so the game mods load as repaired.")
    else:
        add(
            "FAIL" if repair else "WARN",
            "Game mod safety profile",
            profile.detail,
        )

    if repair:
        cleared, heartbeat_errors = clear_stale_heartbeat_files(
            ctx.mod_root,
            force=not ctx.game_running,
        )
        if cleared:
            actions.append("Cleared stale heartbeat lease files: " + ", ".join(cleared) + ".")
            add("FIXED", "Heartbeat leases", "Removed stale status files; no heartbeat was fabricated.")
        elif heartbeat_errors:
            add("FAIL", "Heartbeat leases", ", ".join(heartbeat_errors))
        else:
            add("PASS", "Heartbeat leases", "No stale heartbeat files needed cleanup.")

    save_count = 0
    for root in _save_roots():
        try:
            save_count += len(list(root.rglob("StellarBladeSave*.sav")))
        except Exception:
            pass
    add("PASS" if save_count else "WARN", "Save files", f"{save_count} StellarBladeSave*.sav found")

    required_paks = ["EveStanceNoDamage_P.pak", "EveStanceNoDamage_P.ucas", "EveStanceNoDamage_P.utoc"]

    repair_god_file_set(ctx.paks_mods_dir, ctx.disabled_paks_dir)
    if repair:
        live_result = prepare_live_god_mode(ctx.mod_root, ctx.paks_mods_dir, ctx.disabled_paks_dir)
        if live_result is not None and live_result.ok and live_result.message:
            actions.append(live_result.message)
    pak_state = get_god_pak_state(ctx.paks_mods_dir, ctx.disabled_paks_dir)
    wants_god = read_state_wants_on(ctx.mod_root)
    for name in required_paks:
        active = ctx.paks_mods_dir / name
        disabled = ctx.disabled_paks_dir / name
        if pak_state == "on" and active.exists():
            add(
                "WARN",
                f"God pak active in ~mods: {name}",
                "Live god mode needs pak files stored in disabled_paks, not ~mods. Panel moved them aside.",
            )
        elif pak_state == "off" and disabled.exists():
            add(
                "PASS",
                f"God pak stored (live mode): {name}",
                "God Mode toggles live through SBGodNative (no pak files in ~mods)."
                if wants_god
                else str(disabled),
            )
        elif disabled.exists():
            add("WARN", f"God pak disabled: {name}", f"Available in {disabled}")
        elif active.exists():
            add("WARN", f"God pak partial active: {name}", str(active))
        else:
            add("FAIL", f"God pak missing: {name}", "Not found in ~mods or disabled_paks.")

    add("PASS" if ctx.game_running else "INFO", "Game process", "Running" if ctx.game_running else "Closed")
    hb_level, hb_detail = connection_summary_for_health(
        ctx,
        profile.safe,
        profile.native_bridge_ready,
    )
    add(hb_level, "Panel connection", hb_detail)

    result = _write_health_report(
        ctx,
        "One Click Repair" if repair else "Health Check",
        rows,
        actions,
    )
    result["profile_safe"] = profile.safe
    result["profile_changed"] = profile.changed
    result["native_bridge_ready"] = profile.native_bridge_ready
    return result
