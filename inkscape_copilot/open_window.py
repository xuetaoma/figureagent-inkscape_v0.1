from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PACKAGE_PARENT = str(PACKAGE_ROOT.parent)
if PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, PACKAGE_PARENT)

try:
    import inkex
except ModuleNotFoundError:  # pragma: no cover - local CLI tests do not have inkex installed
    inkex = None

from inkscape_copilot.bridge import STATE_DIR, reset_state
from inkscape_copilot.always_on_worker import start_worker
from inkscape_copilot.platform_support import (
    detached_process_kwargs,
    is_macos,
    is_windows,
    list_listening_pids,
    python_executable,
    terminate_process,
)
from inkscape_copilot.worker import register_current_document, sync_document_context

HOST = "127.0.0.1"
PORT = 8767
URL = f"http://{HOST}:{PORT}"
WEB_UI_SESSION_FILE = STATE_DIR / "web_ui_session.json"
WEB_UI_LOG_FILE = STATE_DIR / "web_ui_server.log"


def _server_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/api/state", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


def _read_web_ui_session() -> dict[str, object]:
    if not WEB_UI_SESSION_FILE.exists():
        return {}
    try:
        return json.loads(WEB_UI_SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_web_ui_session(payload: dict[str, object]) -> None:
    WEB_UI_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    WEB_UI_SESSION_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _clear_web_ui_session() -> None:
    try:
        WEB_UI_SESSION_FILE.unlink()
    except FileNotFoundError:
        pass


def _clear_web_ui_log() -> None:
    try:
        WEB_UI_LOG_FILE.unlink()
    except FileNotFoundError:
        pass


def _list_server_pids() -> list[int]:
    return list_listening_pids(PORT)


def _stop_previous_server() -> None:
    payload = _read_web_ui_session()
    known_pids = _list_server_pids()
    pid = payload.get("server_pid")
    if isinstance(pid, int) and pid not in known_pids:
        known_pids.append(pid)
    if not known_pids:
        _clear_web_ui_session()
        return

    for known_pid in known_pids:
        terminate_process(known_pid)

    deadline = time.time() + 3
    while time.time() < deadline:
        if not _list_server_pids() and not _server_alive():
            _clear_web_ui_session()
            return
        time.sleep(0.1)

    for known_pid in _list_server_pids():
        terminate_process(known_pid, force=True)
    _clear_web_ui_session()


def _kill_copilot_processes_by_pattern() -> None:
    if is_windows():
        return
    patterns = [
        "inkscape_copilot.cli serve --port 8767",
        "run_web_app(host=\"127.0.0.1\", port=8767",
        "from inkscape_copilot.webapp import run_web_app",
    ]
    for pattern in patterns:
        subprocess.run(
            ["pkill", "-f", pattern],
            check=False,
            capture_output=True,
            text=True,
        )


def _close_previous_browser_windows() -> None:
    if not is_macos():
        return
    script = f'''
set targetUrls to {{"http://127.0.0.1:8767", "http://127.0.0.1:8768"}}

on matchesTarget(theUrl)
\trepeat with targetUrl in targetUrls
\t\tif theUrl starts with targetUrl then
\t\t\treturn true
\t\tend if
\tend repeat
\treturn false
end matchesTarget

try
\ttell application "Safari"
\t\trepeat with w in (every window)
\t\t\tset shouldClose to false
\t\t\ttry
\t\t\t\trepeat with t in (every tab of w)
\t\t\t\t\tif my matchesTarget(URL of t) then
\t\t\t\t\t\tset shouldClose to true
\t\t\t\t\t\texit repeat
\t\t\t\t\tend if
\t\t\t\tend repeat
\t\t\tend try
\t\t\tif shouldClose then close w
\t\tend repeat
\tend tell
end try

try
\ttell application "Google Chrome"
\t\trepeat with w in (every window)
\t\t\tset shouldClose to false
\t\t\ttry
\t\t\t\trepeat with t in (every tab of w)
\t\t\t\t\tif my matchesTarget(URL of t) then
\t\t\t\t\t\tset shouldClose to true
\t\t\t\t\t\texit repeat
\t\t\t\t\tend if
\t\t\t\tend repeat
\t\t\tend try
\t\t\tif shouldClose then close w
\t\tend repeat
\tend tell
end try
'''
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)


def _launch_server() -> int:
    WEB_UI_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = PACKAGE_PARENT if not pythonpath else f"{PACKAGE_PARENT}{os.pathsep}{pythonpath}"
    log_handle = WEB_UI_LOG_FILE.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [python_executable(), "-m", "inkscape_copilot.cli", "serve", "--port", str(PORT)],
        cwd=PACKAGE_PARENT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        **detached_process_kwargs(),
    )
    log_handle.close()
    _write_web_ui_session(
        {
            "server_pid": process.pid,
            "url": URL,
            "opened_at": time.time(),
            "log_file": str(WEB_UI_LOG_FILE),
        }
    )
    return process.pid


def open_fresh_interactive_window(*, reset_runtime_state: bool = True) -> None:
    _close_previous_browser_windows()
    _stop_previous_server()
    _kill_copilot_processes_by_pattern()
    _clear_web_ui_session()
    _clear_web_ui_log()

    if reset_runtime_state:
        reset_state()
    _launch_server()

    deadline = time.time() + 10
    while time.time() < deadline:
        if _server_alive():
            break
        time.sleep(0.25)

    if not _server_alive():
        manual_command = f"cd {PACKAGE_PARENT} && {python_executable()} -m inkscape_copilot.cli serve --port {PORT}"
        details = ""
        try:
            details = WEB_UI_LOG_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            details = ""
        if details:
            raise RuntimeError(
                "Could not start the FigureAgent interactive window.\n\n"
                f"Try this in Terminal:\n{manual_command}\n\n"
                f"Startup log:\n{details}"
            )
        raise RuntimeError(
            "Could not start the FigureAgent interactive window.\n\n"
            f"Try this in Terminal:\n{manual_command}"
        )

    if is_macos():
        launched = subprocess.run(["open", "-a", "Safari", URL], check=False, capture_output=True, text=True)
        if launched.returncode == 0:
            return
    webbrowser.open(URL)


if inkex is not None:
    class OpenInteractiveFigureAgentExtension(inkex.EffectExtension):
        def effect(self) -> None:
            try:
                open_fresh_interactive_window()
            except RuntimeError as exc:
                raise inkex.AbortExtension(str(exc)) from exc

            selected = list(self.svg.selection.values())
            sync_document_context(self.svg, selected)
            document = register_current_document(self.svg)
            start_worker(
                document_name=document.get("document_name"),
                document_id=document.get("document_id"),
                worker_origin="inkscape-extension",
            )

            inkex.utils.debug(f"FigureAgent for Inkscape: Opened a fresh interactive window at {URL}")


if __name__ == "__main__":
    if inkex is None:
        raise SystemExit("inkex is required when running this module as an Inkscape extension.")
    OpenInteractiveFigureAgentExtension().run()
