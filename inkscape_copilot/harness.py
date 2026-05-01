from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTEXT = PACKAGE_ROOT / "tests/fixtures/contexts/multi_panel_publication.json"
DEFAULT_SCENARIOS = PACKAGE_ROOT / "tests/fixtures/harness_scenarios.json"

JsonDict = dict[str, Any]


class HarnessFailure(AssertionError):
    """Raised when a fixture-backed harness expectation is not met."""


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _configure_runtime(runtime_root: Path, context_path: Path) -> None:
    os.environ["INKSCAPE_COPILOT_HOME"] = str(runtime_root)

    from . import bridge

    bridge.configure_runtime_root(runtime_root)
    bridge.ensure_state_files()
    context = _load_json(context_path)
    context.setdefault("updated_at", "fixture")
    _write_json(bridge.DOCUMENT_CONTEXT_FILE, context)


def _first_candidate(result: JsonDict) -> JsonDict:
    candidates = result.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise HarnessFailure("Expected at least one ranked candidate.")
    first = candidates[0]
    if not isinstance(first, dict):
        raise HarnessFailure("First ranked candidate is not an object.")
    return first


def _assert_expectation(result: JsonDict, expect: JsonDict) -> list[str]:
    notes: list[str] = []
    if "ok" in expect and bool(result.get("ok")) != bool(expect["ok"]):
        raise HarnessFailure(f"Expected ok={expect['ok']}, got {result.get('ok')!r}.")
    if "apply" in expect and bool(result.get("apply")) != bool(expect["apply"]):
        raise HarnessFailure(f"Expected apply={expect['apply']}, got {result.get('apply')!r}.")
    if "action_count" in expect and result.get("action_count") != expect["action_count"]:
        raise HarnessFailure(f"Expected action_count={expect['action_count']}, got {result.get('action_count')!r}.")
    if "min_ranked_count" in expect and int(result.get("ranked_count") or 0) < int(expect["min_ranked_count"]):
        raise HarnessFailure(
            f"Expected at least {expect['min_ranked_count']} ranked targets, got {result.get('ranked_count')!r}."
        )
    if "min_matched_count" in expect and int(result.get("matched_count") or 0) < int(expect["min_matched_count"]):
        raise HarnessFailure(
            f"Expected at least {expect['min_matched_count']} matches, got {result.get('matched_count')!r}."
        )
    if "contains_object_id" in expect:
        object_ids = result.get("object_ids")
        if not isinstance(object_ids, list) or expect["contains_object_id"] not in object_ids:
            raise HarnessFailure(f"Expected object_ids to contain {expect['contains_object_id']!r}, got {object_ids!r}.")
    if "first_action_kind" in expect:
        plan = result.get("plan")
        actions = plan.get("actions") if isinstance(plan, dict) else None
        if not isinstance(actions, list) or not actions:
            raise HarnessFailure("Expected a preview plan with at least one action.")
        first_action = actions[0]
        if not isinstance(first_action, dict) or first_action.get("kind") != expect["first_action_kind"]:
            raise HarnessFailure(f"Expected first action kind {expect['first_action_kind']!r}, got {first_action!r}.")

    candidate_expectations = {
        "first_object_id": "object_id",
        "first_role": "role",
        "first_panel": "panel",
        "first_axis": "axis",
    }
    if any(key in expect for key in candidate_expectations):
        first = _first_candidate(result)
        notes.append(
            f"first={first.get('object_id')} role={first.get('role')} "
            f"panel={first.get('panel')} axis={first.get('axis')}"
        )
        for expect_key, result_key in candidate_expectations.items():
            if expect_key in expect and first.get(result_key) != expect[expect_key]:
                raise HarnessFailure(
                    f"Expected first candidate {result_key}={expect[expect_key]!r}, got {first.get(result_key)!r}."
                )
    return notes


def _run_scenarios(scenarios_path: Path) -> list[JsonDict]:
    from .tools import call_tool

    scenarios = _load_json(scenarios_path)
    if not isinstance(scenarios, list):
        raise HarnessFailure("Scenario file must contain a JSON list.")

    results: list[JsonDict] = []
    for index, scenario in enumerate(scenarios, start=1):
        if not isinstance(scenario, dict):
            raise HarnessFailure(f"Scenario #{index} is not an object.")
        name = str(scenario.get("name") or f"scenario-{index}")
        tool = scenario.get("tool")
        payload = scenario.get("payload") or {}
        expect = scenario.get("expect") or {}
        if not isinstance(tool, str) or not tool:
            raise HarnessFailure(f"{name}: missing tool name.")
        if not isinstance(payload, dict) or not isinstance(expect, dict):
            raise HarnessFailure(f"{name}: payload and expect must be objects.")

        record: JsonDict = {"name": name, "tool": tool, "payload": payload}
        try:
            result = call_tool(tool, payload)
            notes = _assert_expectation(result, expect)
            record.update({"ok": True, "notes": notes, "result": result})
        except Exception as exc:
            record.update({"ok": False, "error": str(exc)})
        results.append(record)
    return results


def _run_mcp_smoke(runtime_root: Path) -> JsonDict:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "rank_edit_targets",
            "arguments": {"intent": "panel label c", "role": "panel_label", "panel": "c", "limit": 1},
        },
    }
    env = {**os.environ, "INKSCAPE_COPILOT_HOME": str(runtime_root)}
    completed = subprocess.run(
        [sys.executable, "-m", "inkscape_copilot.cli", "mcp"],
        cwd=PACKAGE_ROOT,
        env=env,
        input=json.dumps(request) + "\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        return {"ok": False, "stderr": completed.stderr, "returncode": completed.returncode}
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        return {"ok": False, "stderr": completed.stderr, "error": "No MCP response."}
    response = json.loads(lines[-1])
    payload = json.loads(response["result"]["content"][0]["text"])
    return {
        "ok": bool(payload.get("ok")) and bool(payload.get("candidates")),
        "response": response,
        "payload": payload,
    }


def run_harness(args: argparse.Namespace) -> JsonDict:
    context_path = Path(args.context).expanduser().resolve()
    scenarios_path = Path(args.scenarios).expanduser().resolve()
    if args.runtime:
        runtime_root = Path(args.runtime).expanduser().resolve()
        runtime_root.mkdir(parents=True, exist_ok=True)
        temp_context = None
    else:
        temp_context = tempfile.TemporaryDirectory(prefix="figureagent-harness-")
        runtime_root = Path(temp_context.name)

    try:
        _configure_runtime(runtime_root, context_path)
        scenario_results = _run_scenarios(scenarios_path)
        mcp_result = _run_mcp_smoke(runtime_root) if args.mcp_smoke else {"ok": True, "skipped": True}
        passed = all(result.get("ok") for result in scenario_results) and bool(mcp_result.get("ok"))
        report: JsonDict = {
            "ok": passed,
            "runtime_root": str(runtime_root),
            "context": str(context_path),
            "scenarios": str(scenarios_path),
            "scenario_count": len(scenario_results),
            "passed_count": sum(1 for result in scenario_results if result.get("ok")),
            "failed_count": sum(1 for result in scenario_results if not result.get("ok")),
            "results": scenario_results,
            "mcp_smoke": mcp_result,
        }
        if args.out:
            _write_json(Path(args.out).expanduser().resolve(), report)
        return report
    finally:
        if temp_context is not None and not args.keep_runtime:
            temp_context.cleanup()


def add_harness_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--context", default=str(DEFAULT_CONTEXT), help="Document-context fixture JSON.")
    parser.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS), help="Harness scenario JSON file.")
    parser.add_argument("--runtime", help="Optional INKSCAPE_COPILOT_HOME runtime directory.")
    parser.add_argument("--keep-runtime", action="store_true", help="Do not delete the temporary runtime directory.")
    parser.add_argument("--mcp-smoke", action="store_true", help="Also smoke-test the stdio MCP server.")
    parser.add_argument("--out", help="Optional JSON report output path.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run FigureAgent fixture-backed tool/MCP harness scenarios.")
    add_harness_arguments(parser)
    return parser


def print_harness_report(report: JsonDict, *, out: str | None = None) -> None:
    summary = {
        "ok": report["ok"],
        "scenario_count": report["scenario_count"],
        "passed_count": report["passed_count"],
        "failed_count": report["failed_count"],
        "mcp_smoke_ok": report["mcp_smoke"].get("ok"),
        "out": out,
    }
    print(json.dumps(summary, indent=2))
    if not report["ok"]:
        failures = [result for result in report["results"] if not result.get("ok")]
        if failures:
            print(json.dumps({"failures": failures}, indent=2), file=sys.stderr)
        if not report["mcp_smoke"].get("ok"):
            print(json.dumps({"mcp_smoke": report["mcp_smoke"]}, indent=2), file=sys.stderr)


def main() -> int:
    args = build_parser().parse_args()
    report = run_harness(args)
    print_harness_report(report, out=args.out)
    return 0 if report["ok"] else 1
