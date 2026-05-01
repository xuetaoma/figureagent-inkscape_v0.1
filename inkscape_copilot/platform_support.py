from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def system_name() -> str:
    return platform.system().lower()


def is_macos() -> bool:
    return system_name() == "darwin"


def is_windows() -> bool:
    return system_name() == "windows"


def is_linux() -> bool:
    return system_name() == "linux"


def default_runtime_root() -> Path:
    """Return an OS-appropriate runtime state directory."""

    if is_macos():
        return (
            Path.home()
            / "Library/Application Support/org.inkscape.Inkscape/config/inkscape/extensions/inkscape_copilot_runtime"
        ).resolve()

    if is_windows():
        base = (
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or str(Path.home() / "AppData/Local")
        )
        return (Path(base) / "FigureAgentForInkscape" / "inkscape_copilot_runtime").resolve()

    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config).expanduser() if xdg_config else Path.home() / ".config"
    return (base / "inkscape/extensions/inkscape_copilot_runtime").resolve()


def user_extensions_dir() -> Path:
    """Return the common Inkscape user extensions directory for this OS."""

    if is_macos():
        return (Path.home() / "Library/Application Support/org.inkscape.Inkscape/config/inkscape/extensions").resolve()
    if is_windows():
        appdata = os.environ.get("APPDATA")
        base = Path(appdata).expanduser() if appdata else Path.home() / "AppData/Roaming"
        return (base / "inkscape/extensions").resolve()
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config).expanduser() if xdg_config else Path.home() / ".config"
    return (base / "inkscape/extensions").resolve()


def executable_candidates(name: str) -> list[str]:
    if not is_windows():
        found = shutil.which(name)
        return [found] if found else []

    names = [name]
    if not name.lower().endswith((".exe", ".com", ".bat", ".cmd")):
        names.extend([f"{name}.com", f"{name}.exe", f"{name}.cmd", f"{name}.bat"])
    candidates: list[str] = []
    for candidate in names:
        found = shutil.which(candidate)
        if found and found not in candidates:
            candidates.append(found)
    return candidates


def command_exists(name: str) -> bool:
    return bool(executable_candidates(name))


def list_listening_pids(port: int) -> list[int]:
    """Best-effort cross-platform lookup for processes listening on a TCP port."""

    if is_windows():
        command = ["netstat", "-ano", "-p", "tcp"]
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=3.0)
        except Exception:
            return []
        if result.returncode != 0:
            return []
        pids: set[int] = set()
        marker = f":{port}"
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            local_address = parts[1]
            state = parts[3].upper() if len(parts) >= 5 else ""
            pid_text = parts[-1]
            if marker in local_address and state == "LISTENING":
                try:
                    pids.add(int(pid_text))
                except ValueError:
                    continue
        return sorted(pids)

    if command_exists("lsof"):
        try:
            result = subprocess.run(
                ["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3.0,
            )
        except Exception:
            return []
        if result.returncode != 0:
            return []
        pids: list[int] = []
        for line in result.stdout.splitlines():
            try:
                pids.append(int(line.strip()))
            except ValueError:
                continue
        return pids

    return []


def detached_process_kwargs() -> dict[str, object]:
    if is_windows():
        creationflags = 0
        for flag_name in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS"):
            creationflags |= int(getattr(subprocess, flag_name, 0))
        return {"creationflags": creationflags} if creationflags else {}
    return {"start_new_session": True}


def terminate_process(pid: int, *, force: bool = False) -> bool:
    if pid <= 0:
        return False
    if is_windows():
        command = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            command.append("/F")
        try:
            return subprocess.run(command, check=False, capture_output=True, text=True, timeout=5.0).returncode == 0
        except Exception:
            return False

    try:
        os.kill(pid, 9 if force else 15)
        return True
    except Exception:
        return False


def python_executable() -> str:
    return sys.executable or "python"
