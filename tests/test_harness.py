import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def test_fixture_harness_runs_tool_and_mcp_scenarios() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="figureagent-harness-test-") as runtime:
        out = Path(runtime) / "report.json"
        env = {**os.environ, "INKSCAPE_COPILOT_HOME": runtime}
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/run_harness.py",
                "--runtime",
                runtime,
                "--mcp-smoke",
                "--out",
                str(out),
            ],
            cwd=root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["ok"] is True
        assert report["scenario_count"] >= 5
        assert report["mcp_smoke"]["ok"] is True
