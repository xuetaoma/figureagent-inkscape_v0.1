from __future__ import annotations

import argparse
import json
import sys

from .bridge import pending_jobs, read_status, reset_state
from .chat import run_chat
from .defaults import default_document_context
from .harness import add_harness_arguments, print_harness_report, run_harness
from .openai_bridge import OpenAIPlannerError, plan_with_openai
from .schema import ActionPlan
from .interpreter import PromptError, interpret_prompt
from .mcp_server import serve_stdio
from .tools import call_tool, list_tools
from .webapp import run_web_app


def _local_plan(prompt: str) -> ActionPlan:
    return ActionPlan(
        summary=f"Local interpreter plan for: {prompt}",
        actions=interpret_prompt(prompt),
        needs_confirmation=False,
    )


def cmd_send(args: argparse.Namespace) -> int:
    try:
        if args.mode == "openai":
            plan = plan_with_openai(
                args.prompt,
                default_document_context(),
                model=args.model,
            )
        else:
            plan = _local_plan(args.prompt)
    except (PromptError, OpenAIPlannerError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps({"prompt": args.prompt, "mode": args.mode, "plan": plan.to_dict()}, indent=2))
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    print(json.dumps(read_status(), indent=2))
    return 0


def cmd_queue(_: argparse.Namespace) -> int:
    print(json.dumps([job.to_dict() for job in pending_jobs()], indent=2))
    return 0


def cmd_reset(_: argparse.Namespace) -> int:
    reset_state()
    print(json.dumps({"state": "idle", "queue_cleared": True}, indent=2))
    return 0


def cmd_tools(_: argparse.Namespace) -> int:
    print(json.dumps(list_tools(), indent=2))
    return 0


def cmd_tool_call(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(args.payload) if args.payload else {}
        if not isinstance(payload, dict):
            raise ValueError("Tool payload must be a JSON object.")
        result = call_tool(args.name, payload)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


def cmd_mcp(_: argparse.Namespace) -> int:
    return serve_stdio()


def cmd_worker(args: argparse.Namespace) -> int:
    payload = {}
    if args.worker_command == "start":
        payload["interval_seconds"] = args.interval
        if args.document_name:
            payload["document_name"] = args.document_name
        if args.document_id:
            payload["document_id"] = args.document_id
        payload["worker_origin"] = "cli"
        result = call_tool("start_always_on_worker", payload)
    elif args.worker_command == "stop":
        result = call_tool("stop_always_on_worker", payload)
    else:
        result = call_tool("get_always_on_worker_status", payload)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok", True) else 1


def cmd_harness(args: argparse.Namespace) -> int:
    report = run_harness(args)
    print_harness_report(report, out=args.out)
    return 0 if report["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FigureAgent for Inkscape local preview tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    send_parser = subparsers.add_parser("send", help="Interpret a prompt into explicit actions")
    send_parser.add_argument("prompt", help="Prompt to translate into Inkscape actions")
    send_parser.add_argument(
        "--mode",
        choices=("local", "openai"),
        default="local",
        help="Use the local fallback planner or the configured API-backed planner",
    )
    send_parser.add_argument(
        "--model",
        help="Optional model override when using an API-backed planner",
    )
    send_parser.add_argument(
        "--preview-only",
        action="store_true",
        help="Accepted for compatibility with future queue-based flows",
    )
    send_parser.set_defaults(func=cmd_send)

    chat_parser = subparsers.add_parser("chat", help="Start an interactive streaming FigureAgent session")
    chat_parser.add_argument(
        "--model",
        help="Optional model override for chat mode",
    )
    chat_parser.add_argument(
        "--context-file",
        help="Optional JSON file containing document context to use during chat mode",
    )
    chat_parser.set_defaults(func=lambda args: run_chat(model=args.model, context_path=args.context_file))

    serve_parser = subparsers.add_parser("serve", help="Start the non-blocking local FigureAgent web UI")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host to bind the local web UI to")
    serve_parser.add_argument("--port", type=int, default=8765, help="Port to bind the local web UI to")
    serve_parser.add_argument("--model", help="Optional model override for web UI mode")
    serve_parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the web UI in a browser after the server starts",
    )
    serve_parser.set_defaults(
        func=lambda args: run_web_app(
            host=args.host,
            port=args.port,
            model=args.model,
            open_browser=args.open_browser,
        )
    )

    status_parser = subparsers.add_parser("status", help="Show the current bridge status")
    status_parser.set_defaults(func=cmd_status)

    queue_parser = subparsers.add_parser("queue", help="Show pending queued jobs")
    queue_parser.set_defaults(func=cmd_queue)

    reset_parser = subparsers.add_parser("reset", help="Clear queued jobs and reset bridge status")
    reset_parser.set_defaults(func=cmd_reset)

    tools_parser = subparsers.add_parser("tools", help="List FigureAgent local tools")
    tools_parser.set_defaults(func=cmd_tools)

    tool_call_parser = subparsers.add_parser("tool-call", help="Call one FigureAgent local tool with a JSON payload")
    tool_call_parser.add_argument("name", help="Tool name to call")
    tool_call_parser.add_argument("payload", nargs="?", default="{}", help="JSON object payload")
    tool_call_parser.set_defaults(func=cmd_tool_call)

    mcp_parser = subparsers.add_parser("mcp", help="Start the FigureAgent MCP stdio server")
    mcp_parser.set_defaults(func=cmd_mcp)

    worker_parser = subparsers.add_parser("worker", help="Manage the always-on FigureAgent Inkscape worker")
    worker_subparsers = worker_parser.add_subparsers(dest="worker_command", required=True)

    worker_start = worker_subparsers.add_parser("start", help="Start the always-on worker")
    worker_start.add_argument("--interval", type=float, default=0.75)
    worker_start.add_argument("--document-name")
    worker_start.add_argument("--document-id")
    worker_start.set_defaults(func=cmd_worker)

    worker_stop = worker_subparsers.add_parser("stop", help="Stop the always-on worker")
    worker_stop.set_defaults(func=cmd_worker)

    worker_status = worker_subparsers.add_parser("status", help="Show always-on worker status")
    worker_status.set_defaults(func=cmd_worker)

    harness_parser = subparsers.add_parser("harness", help="Run fixture-backed FigureAgent tool/MCP scenarios")
    add_harness_arguments(harness_parser)
    harness_parser.set_defaults(func=cmd_harness)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
