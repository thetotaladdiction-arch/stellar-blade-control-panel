"""Read-only acceptance checks for SBMovementNative heartbeat telemetry.

This module never drives the game and never writes an Unreal object.  It turns
the native mod's atomic heartbeat into a repeatable pass/fail result that can be
used while a human or the panel changes Movement/FOV settings.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping


                                                                         
                                                                             
                                                                              
                                                                          
                                                                  
                                      
EXPECTED_VERSION = "1.4.1"
EXPECTED_ARCHITECTURE = "fully_event_driven_taskgraph_game_thread_one_shot"
EXPECTED_DLL_SHA256 = "2EC681952F6F737951816C59E41769D235C478B0E50F980548015E893166B88C"
# The installed 1.3.6 stays trusted so a partial install never reads as
# untrusted; each build must report its own version.
TRUSTED_BUILDS = {
    EXPECTED_DLL_SHA256: EXPECTED_VERSION,
    "88500DC7E30C115C3FA890CAB6A22148C2D1C8C13B0CA13FADF5ED2C210A7A8B": "1.3.6",
}
TRUSTED_DLL_SHA256 = frozenset(TRUSTED_BUILDS)
ACCEPTED_VERSIONS = frozenset(TRUSTED_BUILDS.values())
SPEED_FIELDS = (
    "walk",
    "guard_run",
    "lockon_run",
    "lockon_walk",
    "jog",
    "run_override",
    "walk_override",
)
COUNTER_FIELDS = ("submit_count", "callback_count", "destroy_count", "writes")


class HeartbeatError(ValueError):
    """The heartbeat is missing, malformed, or internally inconsistent."""


def parse_kv_text(text: str) -> dict[str, str]:
    """Parse a strict key=value heartbeat and reject ambiguous duplicates."""
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if "=" not in line:
            raise HeartbeatError(f"line {line_number} has no '=' separator")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise HeartbeatError(f"line {line_number} has an empty key or value")
        if key in values:
            raise HeartbeatError(f"duplicate heartbeat key: {key}")
        values[key] = value
    if not values:
        raise HeartbeatError("heartbeat is empty")
    return values


def read_heartbeat(path: Path) -> dict[str, str]:
    """Read one atomic heartbeat, tolerating its brief Windows replace window."""
    last_error: OSError | None = None
    for attempt in range(8):
        try:
            return parse_kv_text(path.read_text(encoding="ascii"))
        except OSError as exc:
            last_error = exc
            if attempt < 7:
                time.sleep(0.025)
        except UnicodeError as exc:
            raise HeartbeatError(f"heartbeat is not ASCII: {exc}") from exc
    raise HeartbeatError(f"could not read heartbeat: {last_error}") from last_error


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _integer(values: Mapping[str, str], key: str) -> int:
    try:
        return int(values[key], 0)
    except KeyError as exc:
        raise HeartbeatError(f"missing heartbeat key: {key}") from exc
    except ValueError as exc:
        raise HeartbeatError(f"heartbeat key {key} is not an integer") from exc


def _number(values: Mapping[str, str], key: str) -> float:
    try:
        value = float(values[key])
    except KeyError as exc:
        raise HeartbeatError(f"missing heartbeat key: {key}") from exc
    except ValueError as exc:
        raise HeartbeatError(f"heartbeat key {key} is not numeric") from exc
    if not math.isfinite(value):
        raise HeartbeatError(f"heartbeat key {key} is not finite")
    return value


def _live_base(values: Mapping[str, str], key: str) -> tuple[float, float]:
    try:
        live_text, base_text = values[key].split("/", 1)
        live = float(live_text)
        base = float(base_text)
    except KeyError as exc:
        raise HeartbeatError(f"missing heartbeat key: {key}") from exc
    except (ValueError, TypeError) as exc:
        raise HeartbeatError(f"heartbeat key {key} is not live/base telemetry") from exc
    if not math.isfinite(live) or not math.isfinite(base) or base <= 0.0:
        raise HeartbeatError(f"heartbeat key {key} has invalid live/base telemetry")
    return live, base


def _close(actual: float, expected: float, tolerance: float) -> bool:
    return abs(actual - expected) <= tolerance


@dataclass
class Verdict:
    profile: str
    checks: list[dict[str, object]] = field(default_factory=list)
    heartbeat: dict[str, str] = field(default_factory=dict)

    def add(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append({"name": name, "passed": bool(passed), "detail": detail})

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(bool(check["passed"]) for check in self.checks)

    @property
    def failures(self) -> list[str]:
        return [str(check["detail"]) for check in self.checks if not check["passed"]]

    def as_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "passed": self.passed,
            "checks": self.checks,
            "heartbeat": self.heartbeat,
        }


def evaluate_heartbeat(
    values: Mapping[str, str],
    *,
    profile: str,
    expected_speed: float = 1.0,
    expected_jump: float = 1.0,
    expected_fov: float = 0.0,
) -> Verdict:
    """Evaluate one settled heartbeat against a named acceptance profile.

    Profiles:
      active: Movement is enabled and the requested values are applied.
      disabled-live: a fresh panel lease is present but Movement is disabled.
      restored: the panel lease expired and every owned value was restored.
      ready: native architecture/scheduler safety only.
    """
    if profile not in {"active", "disabled-live", "restored", "ready"}:
        raise ValueError(f"unknown movement stability profile: {profile}")
    verdict = Verdict(profile=profile, heartbeat=dict(values))

    def equal(name: str, expected: str) -> None:
        actual = values.get(name)
        verdict.add(name, actual == expected, f"{name}: expected {expected}, got {actual!r}")

    version = values.get("version")
    accepted = ACCEPTED_VERSIONS | {EXPECTED_VERSION}
    verdict.add(
        "version",
        version in accepted,
        f"version: expected one of {sorted(accepted)}, got {version!r}",
    )
    equal("architecture", EXPECTED_ARCHITECTURE)
    equal("ready", "1")
    equal("module_pinned", "1")
    equal("dispatch_poisoned", "0")
    equal("last_exception", "0x00000000")

    try:
        submit = _integer(values, "submit_count")
        callback = _integer(values, "callback_count")
        destroy = _integer(values, "destroy_count")
        verdict.add(
            "balanced_taskgraph_counts",
            submit == callback == destroy,
            f"TaskGraph counts must settle equal; submit={submit}, callback={callback}, destroy={destroy}",
        )
        callback_thread = _integer(values, "callback_thread")
        certified_thread = _integer(values, "certified_game_thread")
        callback_required = profile != "ready" or callback > 0
        callback_ok = (not callback_required) or (
            callback_thread != 0
            and callback_thread == certified_thread
            and values.get("callback_on_game_thread") == "1"
        )
        verdict.add(
            "callback_on_certified_game_thread",
            callback_ok,
            "GameThread callback identity is absent or does not match the certified thread",
        )
    except HeartbeatError as exc:
        verdict.add("taskgraph_telemetry", False, str(exc))

    if profile == "ready":
        return verdict

    expected_enabled = profile == "active"
    expected_fresh = profile != "restored"
    equal("enabled", "1" if expected_enabled else "0")
    equal("request_fresh", "1" if expected_fresh else "0")
    equal("movement_applied", "1" if expected_enabled else "0")

    allowed_errors = {"none"} if expected_fresh else {"none", "state-stale"}
    error = values.get("error")
    verdict.add("error", error in allowed_errors, f"unexpected native error: {error!r}")

    try:
        speed = _number(values, "speed")
        jump = _number(values, "jump")
        fov = _number(values, "fov_target")
        # A fail-closed restore deliberately preserves the last requested
        # multipliers as diagnostic telemetry.  They are no longer live once
        # request_fresh=0, enabled=0, and movement_applied=0; the live/base
        # fields below are the authoritative restoration proof.
        if profile != "restored":
            verdict.add("speed_request", _close(speed, expected_speed, 0.011), f"speed expected {expected_speed:.2f}, got {speed:.2f}")
            verdict.add("jump_request", _close(jump, expected_jump, 0.011), f"jump expected {expected_jump:.2f}, got {jump:.2f}")
        verdict.add("fov_request", _close(fov, expected_fov, 0.11), f"FOV expected {expected_fov:.1f}, got {fov:.1f}")

        base_jump = _number(values, "base_jump")
        live_jump = _number(values, "live_jump")
        wanted_jump = base_jump * (expected_jump if expected_enabled else 1.0)
        verdict.add(
            "live_jump",
            base_jump > 0.0 and _close(live_jump, wanted_jump, 0.6),
            f"live jump expected {wanted_jump:.1f} from base {base_jump:.1f}, got {live_jump:.1f}",
        )
        for field_name in SPEED_FIELDS:
            live, base = _live_base(values, field_name)
            wanted = base * (expected_speed if expected_enabled else 1.0)
            verdict.add(
                f"live_{field_name}",
                _close(live, wanted, 0.6),
                f"{field_name} expected {wanted:.1f} from base {base:.1f}, got {live:.1f}",
            )
    except HeartbeatError as exc:
        verdict.add("movement_values", False, str(exc))

    try:
        fov_applied = values.get("fov_applied") == "1"
        manual_live = _number(values, "ManualCameraFov")
        manual_base = _number(values, "base_ManualCameraFov")
        manual_mode = values.get("bManualCameraFovMode") == "1"
        base_mode = values.get("base_bManualCameraFovMode") == "1"
        if expected_fresh and expected_fov > 0.05:
            target_is_base = _close(expected_fov, manual_base, 0.11)
            fov_changed = not target_is_base
            expected_manual_mode = base_mode if target_is_base else True
            verdict.add("fov_applied", fov_applied == fov_changed, f"fov_applied={int(fov_applied)}, expected {int(fov_changed)}")
            verdict.add("live_manual_fov", _close(manual_live, expected_fov, 0.11), f"ManualCameraFov expected {expected_fov:.1f}, got {manual_live:.1f}")
            verdict.add("live_manual_mode", manual_mode == expected_manual_mode,
                        f"manual FOV mode expected {int(expected_manual_mode)}, got {int(manual_mode)}")
        else:
            verdict.add("fov_restored", not fov_applied and _close(manual_live, manual_base, 0.11) and manual_mode == base_mode,
                        f"FOV did not restore exactly: applied={int(fov_applied)}, live={manual_live:.1f}, base={manual_base:.1f}")
    except HeartbeatError as exc:
        verdict.add("fov_values", False, str(exc))

    return verdict


def wait_for_profile(
    path: Path,
    *,
    profile: str,
    expected_speed: float = 1.0,
    expected_jump: float = 1.0,
    expected_fov: float = 0.0,
    timeout_seconds: float = 8.0,
    poll_seconds: float = 0.2,
    reader: Callable[[Path], dict[str, str]] = read_heartbeat,
) -> Verdict:
    """Wait for the asynchronous one-shot native callback to settle."""
    deadline = time.monotonic() + timeout_seconds
    last: Verdict | None = None
    last_error = "heartbeat was not evaluated"
    while time.monotonic() <= deadline:
        try:
            last = evaluate_heartbeat(
                reader(path),
                profile=profile,
                expected_speed=expected_speed,
                expected_jump=expected_jump,
                expected_fov=expected_fov,
            )
            if last.passed:
                return last
            last_error = "; ".join(last.failures)
        except HeartbeatError as exc:
            last_error = str(exc)
        time.sleep(poll_seconds)
    if last is not None:
        last.add("settled_before_timeout", False, f"profile did not settle in {timeout_seconds:.1f}s: {last_error}")
        return last
    failed = Verdict(profile=profile)
    failed.add("heartbeat_read", False, f"profile did not settle in {timeout_seconds:.1f}s: {last_error}")
    return failed


def counter_snapshot(values: Mapping[str, str]) -> dict[str, int]:
    return {key: _integer(values, key) for key in COUNTER_FIELDS} | {
        "steady_dispatch_skips": _integer(values, "steady_dispatch_skips")
    }


def evaluate_steady_state(before: Mapping[str, str], after: Mapping[str, str]) -> Verdict:
    """Prove an idle lease generated zero new Unreal work."""
    verdict = Verdict(profile="steady-state", heartbeat=dict(after))
    try:
        start = counter_snapshot(before)
        end = counter_snapshot(after)
        for key in COUNTER_FIELDS:
            delta = end[key] - start[key]
            verdict.add(f"zero_delta_{key}", delta == 0, f"{key} delta must be 0, got {delta}")
        skip_delta = end["steady_dispatch_skips"] - start["steady_dispatch_skips"]
        verdict.add("worker_remained_live", skip_delta > 0, f"steady_dispatch_skips did not increase (delta={skip_delta})")
    except HeartbeatError as exc:
        verdict.add("steady_counters", False, str(exc))
    return verdict
