from __future__ import annotations

import os
import time
import uuid
from pathlib import Path


def mod_autoreload_enabled(mod_root: Path) -> bool:
    return not (mod_root / "dev_modautoreload.off").is_file()


def bump_mod_reload_seq(mod_root: Path, state_file: Path, cooldown_sec: float = 8.0) -> bool:
    """Queue a reload without racing the panel-owned ``gui_state.txt`` file."""
    if not mod_autoreload_enabled(mod_root):
        return False
    if not _game_running():
        return False
    if not state_file.is_file():
        return False

    now = time.monotonic()
    last = getattr(bump_mod_reload_seq, "_last_at", 0.0)
    if now - last < cooldown_sec:
        return False

    request_file = mod_root / "mod_reload_request.txt"
    lock_file = request_file.with_name(request_file.name + ".lock")
    deadline = time.monotonic() + 1.5
    lock_fd: int | None = None
    while lock_fd is None:
        try:
            lock_fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(lock_fd, f"pid={os.getpid()}\ntime={time.time():.6f}\n".encode("ascii"))
        except FileExistsError:
            try:
                if time.time() - lock_file.stat().st_mtime > 10.0:
                    lock_file.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)
        except OSError:
            return False

    tmp = request_file.with_name(
        f".{request_file.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        current = 0
        try:
            for line in request_file.read_text(encoding="ascii", errors="ignore").splitlines():
                if line.strip().startswith("seq="):
                    current = max(0, int(line.split("=", 1)[1].strip()))
                    break
        except (OSError, ValueError):
            current = 0
        with tmp.open("x", encoding="ascii", newline="\n") as stream:
            stream.write(f"seq={current + 1}\nreason=panel\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, request_file)
    except OSError:
        return False
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError:
                pass
        try:
            lock_file.unlink(missing_ok=True)
        except OSError:
            pass
    bump_mod_reload_seq._last_at = now  # type: ignore[attr-defined]
    return True


def _game_running() -> bool:
    try:
        import subprocess

        proc = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq SB-Win64-Shipping.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "SB-Win64-Shipping.exe" in (proc.stdout or "")
    except Exception:
        return False
