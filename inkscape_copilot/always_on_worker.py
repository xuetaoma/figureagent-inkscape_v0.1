from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import bridge
from .bridge import (
    append_event,
    mark_session_heartbeat,
    mark_session_started,
    mark_session_stopped,
    pending_jobs,
    read_execution_result,
    read_session_state,
    utc_now,
)
from .inkscape_control import trigger_apply_pending_jobs
from .platform_support import detached_process_kwargs, is_windows, terminate_process


def _pid_file() -> Path:
    return bridge.STATE_DIR / "always_on_worker.pid"


def _stop_file() -> Path:
    return bridge.STATE_DIR / "always_on_worker.stop"


def _log_file() -> Path:
    return bridge.STATE_DIR / "always_on_worker.log"


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    if is_windows():
        return True
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except Exception:
        return True
    if result.returncode != 0:
        return False
    stat = result.stdout.strip()
    if not stat or "Z" in stat:
        return False
    return True


def _read_pid() -> int | None:
    try:
        raw = _pid_file().read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except Exception:
        return None


def _write_pid(pid: int) -> None:
    bridge.STATE_DIR.mkdir(parents=True, exist_ok=True)
    _pid_file().write_text(str(pid), encoding="utf-8")


def _clear_pid(pid: int | None = None) -> None:
    current = _read_pid()
    if pid is not None and current not in {None, pid}:
        return
    try:
        _pid_file().unlink()
    except FileNotFoundError:
        pass


def worker_status() -> dict[str, Any]:
    pid = _read_pid()
    running = _pid_is_running(pid) if isinstance(pid, int) else False
    if pid and not running:
        _clear_pid(pid)
        pid = None
    return {
        "running": running,
        "pid": pid if running else None,
        "session": read_session_state(),
        "pid_file": str(_pid_file()),
        "stop_file": str(_stop_file()),
        "log_file": str(_log_file()),
        "updated_at": utc_now(),
    }


def start_worker(
    *,
    interval_seconds: float = 0.75,
    document_name: str | None = None,
    document_id: str | None = None,
    worker_origin: str = "tool",
) -> dict[str, Any]:
    status = worker_status()
    if status["running"]:
        if document_name or document_id:
            mark_session_started(
                document_name,
                document_id=document_id,
                worker_pid=status.get("pid") if isinstance(status.get("pid"), int) else None,
                worker_origin=worker_origin,
            )
            status = worker_status()
        return {"ok": True, "already_running": True, **status}

    bridge.STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _stop_file().unlink()
    except FileNotFoundError:
        pass

    command = [
        sys.executable,
        "-m",
        "inkscape_copilot.always_on_worker",
        "run",
        "--interval",
        str(max(0.2, interval_seconds)),
    ]
    if document_name:
        command.extend(["--document-name", document_name])
    if document_id:
        command.extend(["--document-id", document_id])
    if worker_origin:
        command.extend(["--origin", worker_origin])
    env = dict(os.environ)
    package_parent = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = (
        package_parent
        if not env.get("PYTHONPATH")
        else f"{package_parent}{os.pathsep}{env['PYTHONPATH']}"
    )
    log_handle = _log_file().open("a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=package_parent,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        **detached_process_kwargs(),
    )
    log_handle.close()
    _write_pid(process.pid)
    mark_session_started(
        document_name,
        document_id=document_id,
        worker_pid=process.pid,
        worker_origin=worker_origin,
    )
    append_event(
        "always_on_worker_started",
        {
            "pid": process.pid,
            "document_name": document_name,
            "document_id": document_id,
            "worker_origin": worker_origin,
        },
    )
    return {"ok": True, "already_running": False, **worker_status()}


def stop_worker(*, timeout_seconds: float = 5.0) -> dict[str, Any]:
    status = worker_status()
    pid = status.get("pid")
    bridge.STATE_DIR.mkdir(parents=True, exist_ok=True)
    _stop_file().write_text(utc_now(), encoding="utf-8")
    if not isinstance(pid, int):
        mark_session_stopped()
        return {"ok": True, "was_running": False, **worker_status()}

    try:
        if not terminate_process(pid):
            if not _pid_is_running(pid):
                _clear_pid(pid)
                mark_session_stopped()
                return {"ok": True, "was_running": False, **worker_status()}
            raise RuntimeError(f"Could not terminate worker pid {pid}.")
    except ProcessLookupError:
        _clear_pid(pid)
        mark_session_stopped()
        return {"ok": True, "was_running": False, **worker_status()}
    except Exception as exc:
        return {"ok": False, "was_running": True, "error": str(exc), **worker_status()}

    deadline = time.time() + max(0.1, timeout_seconds)
    while time.time() < deadline:
        if not _pid_is_running(pid):
            _clear_pid(pid)
            mark_session_stopped()
            append_event("always_on_worker_stopped", {"pid": pid})
            return {"ok": True, "was_running": True, **worker_status()}
        time.sleep(0.1)

    try:
        if not terminate_process(pid, force=True):
            if not _pid_is_running(pid):
                _clear_pid(pid)
                mark_session_stopped()
                append_event("always_on_worker_stopped", {"pid": pid})
                return {"ok": True, "was_running": True, **worker_status()}
            raise RuntimeError(f"Could not force terminate worker pid {pid}.")
    except ProcessLookupError:
        _clear_pid(pid)
        mark_session_stopped()
        append_event("always_on_worker_stopped", {"pid": pid})
        return {"ok": True, "was_running": True, **worker_status()}
    except Exception as exc:
        return {"ok": False, "was_running": True, "error": str(exc), **worker_status()}

    hard_deadline = time.time() + 2.0
    while time.time() < hard_deadline:
        if not _pid_is_running(pid):
            _clear_pid(pid)
            mark_session_stopped()
            append_event("always_on_worker_stopped", {"pid": pid, "forced": True})
            return {"ok": True, "was_running": True, "forced": True, **worker_status()}
        time.sleep(0.1)

    return {
        "ok": False,
        "was_running": True,
        "error": f"Worker pid {pid} did not stop within {timeout_seconds:.1f}s.",
        **worker_status(),
    }


def _should_apply() -> bool:
    if not pending_jobs():
        return False
    execution = read_execution_result()
    # A dispatched state is exactly what the queue writer uses while waiting
    # for Inkscape. The worker should still apply pending jobs in that state.
    return execution.get("state") in {"dispatched", "planned", "idle", "error", "applied"}


def run_worker_loop(
    *,
    interval_seconds: float = 0.75,
    document_name: str | None = None,
    document_id: str | None = None,
    worker_origin: str = "worker-process",
) -> int:
    pid = os.getpid()
    _write_pid(pid)
    mark_session_started(
        document_name,
        document_id=document_id,
        worker_pid=pid,
        worker_origin=worker_origin,
    )
    append_event(
        "always_on_worker_loop_started",
        {
            "pid": pid,
            "document_name": document_name,
            "document_id": document_id,
            "worker_origin": worker_origin,
        },
    )
    try:
        while not _stop_file().exists():
            mark_session_heartbeat("watching", worker_pid=pid)
            if _should_apply():
                append_event("always_on_worker_apply_requested", {"pid": pid})
                ok, error = trigger_apply_pending_jobs()
                append_event(
                    "always_on_worker_apply_result",
                    {"pid": pid, "ok": ok, "error": error},
                )
                if not ok:
                    mark_session_heartbeat("error", worker_pid=pid)
                    time.sleep(max(1.0, interval_seconds * 2))
                    continue
            time.sleep(max(0.2, interval_seconds))
    except KeyboardInterrupt:
        pass
    finally:
        _clear_pid(pid)
        mark_session_stopped()
        append_event("always_on_worker_loop_stopped", {"pid": pid})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FigureAgent always-on Inkscape worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the queue-watching worker loop")
    run_parser.add_argument("--interval", type=float, default=0.75)
    run_parser.add_argument("--document-name")
    run_parser.add_argument("--document-id")
    run_parser.add_argument("--origin", default="worker-process")
    run_parser.set_defaults(
        func=lambda args: run_worker_loop(
            interval_seconds=args.interval,
            document_name=args.document_name,
            document_id=args.document_id,
            worker_origin=args.origin,
        )
    )

    start_parser = subparsers.add_parser("start", help="Start the queue-watching worker in the background")
    start_parser.add_argument("--interval", type=float, default=0.75)
    start_parser.add_argument("--document-name")
    start_parser.add_argument("--document-id")
    start_parser.add_argument("--origin", default="cli")
    start_parser.set_defaults(
        func=lambda args: _print_result(
            start_worker(
                interval_seconds=args.interval,
                document_name=args.document_name,
                document_id=args.document_id,
                worker_origin=args.origin,
            )
        )
    )

    stop_parser = subparsers.add_parser("stop", help="Stop the background queue-watching worker")
    stop_parser.set_defaults(func=lambda _args: _print_result(stop_worker()))

    status_parser = subparsers.add_parser("status", help="Show worker status")
    status_parser.set_defaults(func=lambda _args: _print_result(worker_status()))
    return parser


def _print_result(payload: dict[str, Any]) -> int:
    import json

    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok", True) else 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
