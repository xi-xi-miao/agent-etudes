"""Challenge-level tests for the fixture challenge c999.

A real challenge keeps its own tests next to its tools; this file stands in for
that so the shared tooling has something to point at. It uses the standard
library only and must stay instant.
"""

import json
import subprocess
import sys
from pathlib import Path

CHALLENGE_DIR = Path(__file__).resolve().parents[1]


def test_baseline_solution_validates(tmp_path):
    instance = CHALLENGE_DIR / "instances" / "dev" / "c999-dev-01.json"
    solution = tmp_path / "c999-dev-01.json"

    subprocess.run(
        [sys.executable, str(CHALLENGE_DIR / "tools" / "baseline.py"),
         str(instance), "--out", str(solution)],
        check=True,
        capture_output=True,
        text=True,
    )

    proc = subprocess.run(
        [sys.executable, str(CHALLENGE_DIR / "tools" / "validate.py"),
         str(instance), str(solution), "--json"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    assert report["valid"] is True
    assert report["measures"]["value"] == 10
