.pragma library

// One status vocabulary for every chip in the panel. Feature chips use
// only these words: Ready, Waiting for game, Safety check, Active, Off,
// Needs update, Couldn't start safely (plus short action words such as
// Adding / Added / Restarting while something is happening).
//
//   ok    - Active, Saved, Running, Added          (green)
//   ready - Ready: available, not yet on           (bright outline)
//   warn  - Waiting for game, Safety check, Adding (amber)
//   error - Needs update, Couldn't start safely    (red)
//   off   - Off, Game closed, Not installed        (grey)
//   info  - neutral highlight, never a verdict     (accent)
//
// kindForState("ready") stays "ok" so older callers keep their colour;
// StatusChip draws an "ok" chip whose words are "Ready" as the ready
// variant (FINAL-VISUAL-SPEC.md 5.3), so Ready and Active never look alike.
//
// Components never pick status colours themselves; they pass a kind to
// StatusChip, which asks toneColor() here.

function kindForState(state) {
    var s = String(state || "").toLowerCase()
    if (s === "ready" || s === "active" || s === "added" || s === "ok" || s === "running")
        return "ok"
    if (s === "waiting" || s === "checking" || s === "adding" || s === "starting" || s === "warn")
        return "warn"
    if (s === "needs_update" || s === "unsafe" || s === "error" || s === "fail" || s === "failed")
        return "error"
    if (s === "off" || s === "" || s === "none")
        return "off"
    return "warn"
}

// A native card entry {state, label, detail, ready} from appBackend.nativeStatus.
function nativeKind(status) {
    return status && status.state ? kindForState(status.state) : "warn"
}

function nativeLabel(status, fallback) {
    if (status && status.label)
        return String(status.label)
    return fallback === undefined ? "Waiting for game" : fallback
}

// A feature whose game mod is missing or failed its check: the game mod's
// own word ("Off" when it is not installed, "Couldn't start safely" or
// "Needs update" when its file failed a check), never a vaguer word such
// as "Unavailable" or "Not installed".
function unusableLabel(status) {
    return nativeLabel(status, "Off")
}

function unusableKind(status) {
    return status && status.state ? kindForState(status.state) : "off"
}

function toneColor(kind, tokens) {
    if (!tokens) {
        if (kind === "ok") return "#62dca0"
        if (kind === "ready") return "#e4edf1"
        if (kind === "warn") return "#ffb45e"
        if (kind === "error") return "#ff7a72"
        if (kind === "info") return "#56e0d3"
        return "#86939c"
    }
    if (kind === "ok") return tokens.statusOk
    if (kind === "ready") return tokens.statusReady
    if (kind === "warn") return tokens.statusWarn
    if (kind === "error") return tokens.statusError
    if (kind === "info") return tokens.statusInfo
    return tokens.statusOff
}

// Install-health words from the support checks.
function healthKind(level) {
    var v = String(level || "").toUpperCase()
    if (v === "OK" || v === "PASS" || v === "SAFE") return "ok"
    if (v === "FAIL" || v === "ERROR" || v === "BLOCKED") return "error"
    if (v === "UNKNOWN" || v === "") return "off"
    return "warn"
}

function healthLabel(level) {
    var v = String(level || "").toUpperCase()
    if (v === "OK" || v === "PASS" || v === "SAFE") return "Healthy"
    if (v === "WARN") return "Needs attention"
    if (v === "MISSING") return "Files missing"
    if (v === "FAIL" || v === "ERROR") return "Problem found"
    if (v === "BLOCKED") return "Blocked"
    if (v === "UNKNOWN" || v === "") return "Not checked"
    return String(level)
}

// ── Feature verdicts shared by the Dashboard and the Gameplay cards ──────
// One function per feature, so the two cards can never disagree
// (FINAL-VISUAL-SPEC.md 4.1 / 4.2 chip words).

// God Mode: Active / Off / Safety check, plus Waiting for game and the
// fault words. "Safety check" is on in the panel with the game running and
// the game mod ready, before it confirms Eve is protected. "Protection warning"
// (SBGodNative 1.3.0+): armed, but a protection event was reported - still on, never
// shown as Active (services/god_service.py GOD_DAMAGE_GOT_THROUGH_LABEL).
var GOD_HIT_GOT_THROUGH = "Protection warning"

function godState(backend, status) {
    if (!backend)
        return "off"
    if (!!status && status.state === "needs_update")
        return "needs-update"
    if (!backend.nativeGodReady)
        return !!status && status.state === "off" ? "mod-off" : "unavailable"
    if (backend.nativeGodApplied)
        return !!status && status.label === GOD_HIT_GOT_THROUGH ? "hit-got-through" : "active"
    if (backend.godMode)
        return backend.gameRunning ? "safety-check" : "waiting"
    return "off"
}

function godChip(state) {
    if (state === "needs-update") return ["Needs update", "error"]
    if (state === "unavailable") return ["Couldn't start safely", "error"]
    if (state === "active") return ["Active", "ok"]
    if (state === "hit-got-through") return [GOD_HIT_GOT_THROUGH, "warn"]
    if (state === "safety-check") return ["Safety check", "warn"]
    if (state === "waiting") return ["Waiting for game", "warn"]
    return ["Off", "off"]
}

// Unlimited energy (Gameplay, under God Mode): two more switches of the God
// Mode game mod. The verdict is the panel's own status check
// (services/god_service.py energy_status); these are its chip words. Green
// only for "active": the game mod reports it is holding the bars.
function energyChip(status) {
    var state = status && status.state ? String(status.state) : "off"
    if (state === "needs_update") return ["Needs update", "error"]
    if (state === "unsafe") return ["Couldn't start safely", "error"]
    if (state === "active") return ["Active", "ok"]
    if (state === "waiting") return ["Waiting for game", "warn"]
    return ["Off", "off"]
}

// Instant Boss Restart shows its game mod's actual readiness and activity.
// God Mode adds a testing caution; it does not suspend boss restarts.

function bossBroken(status) {
    return !!status && (status.state === "unsafe" || status.state === "needs_update")
}

// Legacy helper name: requested God-on advisory only, not runtime suspension.
function bossPausedByGod(backend, status) {
    return !!backend && backend.bossEnabled && backend.bossReady && backend.godMode
           && !bossBroken(status) && !backend.bossReviving
}

function bossChip(backend, status) {
    if (bossBroken(status)) return [nativeLabel(status), nativeKind(status)]
    if (!backend || !backend.bossEnabled) return ["Off", "off"]
    if (!backend.bossReady) return [nativeLabel(status), nativeKind(status)]
    if (backend.bossReviving) return ["Restarting", "warn"]
    return ["Ready", "ok"]
}

// Keep the God-on testing caution and count without hiding active restart
// activity or the game mod's fault verdict. Requested on is not proof of protection.
function bossLine(backend, status) {
    if (!backend)
        return ""
    var broken = bossBroken(status)
    var advisory = bossPausedByGod(backend, status)
    if (advisory || (!broken && !backend.bossEnabled && backend.godMode)) {
        var line = "Turn God Mode off before testing Revive and boss restarts."
        var count = Math.floor(Number(backend.bossRestartCount) || 0)
        if (advisory && backend.gameRunning && count > 0)
            line += " Restarts so far: " + count + "."
        return line
    }
    return backend.bossStatusText || ""
}

// Retry Point: Ready / Saved / Another area, and the fault words. "Another
// area" as soon as the game mod's own area check (0.2.3, every 3 s while a
// point is saved) finds Eve outside the point's area, before any Return
// (build 4e review: the chip read "Saved" there until Return was pressed).
// Return stays usable: the game mod checks the area again and moves nothing.
function retryPointChip(backend, status) {
    if (!backend || !backend.retryPointInstalled) return [unusableLabel(status), unusableKind(status)]
    if (!backend.retryPointAvailable) return [nativeLabel(status), nativeKind(status)]
    if (!backend.retryPointCanReturn) return ["Ready", "ok"]
    if (backend.retryPointElsewhere) return ["Another area", "warn"]
    return ["Saved", "ok"]
}

// Movement & camera: one game mod, one chip. Active only when every changed
// value is confirmed in the game (speed and jump by the movement mod, the
// field of view separately). Normal is 100 % / 100 % / 75 degrees.
function movementApplied(backend) {
    if (!backend)
        return false
    var moveChanged = backend.speedPct !== 100 || backend.jumpPct !== 100
    var fovChanged = backend.fovDegrees !== 75
    return (backend.nativeMovementApplied || backend.nativeFovApplied)
           && (!moveChanged || backend.nativeMovementApplied)
           && (!fovChanged || backend.nativeFovApplied)
}

function movementChip(backend, status) {
    if (!backend || !backend.movementAvailable) return [unusableLabel(status), unusableKind(status)]
    if (!backend.gameRunning) return ["Waiting for game", "warn"]
    if (movementApplied(backend)) return ["Active", "ok"]
    if (backend.nativeMovementReady) return ["Ready", "ok"]
    return [nativeLabel(status), nativeKind(status)]
}
