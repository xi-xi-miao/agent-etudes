"""End-to-end round trip: ``demo.sh`` must carry an instance all the way from
the generator to a validated, rendered layout, and must measure every committed
dev instance on the way -- the round trip required by ``challenges/c001/SPEC.md``.

The script is exercised as a script -- via ``bash``, into a throwaway output
directory -- because that is how ``make demo CHALLENGE=c001`` and the challenge
README's quickstart run it.  Two deliberate choices keep the test honest and
cheap:

* ``PYTHON`` is set to the interpreter running pytest, so the round trip uses
  the same virtual environment as the rest of the suite (and no nested ``uv``).
  The "uv if available, else python3" default is a convenience for humans and is
  not what this test is about.
* ``C001_DEMO_FIGURES=0``, so the run cannot rewrite the committed files in
  ``challenges/c001/demo/``.  A test that mutates the working tree is a trap for
  whoever runs the suite next.

Marked ``slow`` (it shells out ~35 times) but not deselected by default: the
round trip is the acceptance criterion, so it should run every time.  The
marker is not registered in ``pyproject.toml``; pytest therefore emits a
``PytestUnknownMarkWarning``, which is cosmetic.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("shapely")

pytestmark = pytest.mark.slow

C001_DIR = Path(__file__).resolve().parent.parent
DEMO_SH = C001_DIR / "demo.sh"
DEV_DIR = C001_DIR / "instances" / "dev"

#: ``| c001-t1-dev-01 | 44.6 | 4800.621 |``
ROW_RE = re.compile(r"^\|\s*(c001-\S+)\s*\|\s*([0-9.]+)\s*\|\s*([0-9.]+)\s*\|\s*$")

TABLE_HEADER = "| instance | utilization % | used length |"

#: Vocabulary this repository does not use (assembled from fragments so that
#: this file does not match its own check).  See scripts/check_words.sh.
FORBIDDEN_RE = re.compile(
    r"\b(" + "|".join(["leader" + "board", "sco" + "res?", "ra" + "nk(s|ing|ings)?", "win" + "ner"]) + r")\b",
    re.IGNORECASE,
)


@pytest.fixture(scope="module")
def demo_run(tmp_path_factory):
    """Run ``demo.sh`` once into a throwaway directory; reused by every test."""
    if not DEMO_SH.is_file():
        pytest.skip("challenges/c001/demo.sh is missing")
    out_dir = tmp_path_factory.mktemp("c001-demo")
    env = dict(os.environ)
    env["PYTHON"] = sys.executable
    env["C001_DEMO_FIGURES"] = "0"
    proc = subprocess.run(
        ["bash", str(DEMO_SH), str(out_dir)],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    return proc, out_dir


@pytest.fixture(scope="module")
def dev_ids():
    ids = sorted(path.stem for path in DEV_DIR.glob("*.json"))
    if not ids:
        pytest.skip("challenges/c001/instances/dev is empty")
    return ids


def table_rows(stdout):
    """The parsed measurement rows of the markdown table."""
    return [ROW_RE.match(line) for line in stdout.splitlines() if ROW_RE.match(line)]


def test_demo_sh_is_executable_bash():
    assert DEMO_SH.is_file()
    assert DEMO_SH.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")
    assert os.access(DEMO_SH, os.X_OK), "demo.sh should keep its executable bit"
    syntax = subprocess.run(["bash", "-n", str(DEMO_SH)], capture_output=True, text=True)
    assert syntax.returncode == 0, syntax.stderr


def test_round_trip_exits_clean(demo_run):
    proc, _ = demo_run
    assert proc.returncode == 0, f"demo.sh failed:\n{proc.stdout}\n{proc.stderr}"


def test_every_layout_validated(demo_run, dev_ids):
    """The tally line is the single source of truth for "all validations passed"."""
    proc, _ = demo_run
    tally = [line for line in proc.stdout.splitlines() if "layout(s) validated" in line]
    assert len(tally) == 1, proc.stdout
    match = re.search(r"(\d+) layout\(s\) validated, (\d+) failed", tally[0])
    assert match, tally[0]
    checked, failed = int(match.group(1)), int(match.group(2))
    assert failed == 0
    # the fresh demo instance plus every dev instance
    assert checked == len(dev_ids) + 1
    assert "NOT VALID" not in proc.stdout


def test_table_has_one_row_per_dev_instance(demo_run, dev_ids):
    proc, _ = demo_run
    assert TABLE_HEADER in proc.stdout
    rows = table_rows(proc.stdout)
    assert len(rows) == len(dev_ids) == 15
    assert [row.group(1) for row in rows] == dev_ids, "rows must be sorted by instance id"


def test_table_numbers_are_plausible_measurements(demo_run):
    proc, _ = demo_run
    for row in table_rows(proc.stdout):
        utilization = float(row.group(2))
        used_length = float(row.group(3))
        # The measured band is 44.6-51.0%; the bounds are wide enough to absorb
        # a re-generated dev set but tight enough that a baseline regression
        # which halves the packing quality trips this test.
        assert 35.0 < utilization < 65.0, f"{row.group(1)}: utilization {utilization}"
        assert used_length > 0.0, f"{row.group(1)}: used length {used_length}"


def test_artefacts_are_written(demo_run, dev_ids):
    _, out_dir = demo_run
    assert (out_dir / "c001-t1-demo-01.json").is_file()
    assert (out_dir / "c001-t1-demo-01.solution.json").is_file()
    svg = out_dir / "c001-t1-demo-01.svg"
    assert svg.is_file()
    assert svg.read_text(encoding="utf-8").lstrip().startswith("<svg")
    assert sorted(p.stem for p in (out_dir / "dev").glob("*.json")) == dev_ids


def test_gallery_holds_every_dev_layout(demo_run, dev_ids):
    _, out_dir = demo_run
    gallery = out_dir / "gallery.html"
    assert gallery.is_file()
    html = gallery.read_text(encoding="utf-8")
    assert html.count("<svg") == len(dev_ids)
    for instance_id in dev_ids:
        assert instance_id in html


def test_committed_demo_figures_are_left_alone(demo_run):
    """With C001_DEMO_FIGURES=0 the run must not touch challenges/c001/demo/."""
    proc, _ = demo_run
    assert "leaving demo/ untouched" in proc.stdout


def test_usage(tmp_path):
    helped = subprocess.run(
        ["bash", str(DEMO_SH), "--help"], capture_output=True, text=True
    )
    assert helped.returncode == 0
    assert "usage: bash demo.sh" in helped.stdout

    misused = subprocess.run(
        ["bash", str(DEMO_SH), str(tmp_path), "extra"], capture_output=True, text=True
    )
    assert misused.returncode == 2
    assert "usage: bash demo.sh" in misused.stderr


def test_round_trip_output_avoids_the_forbidden_vocabulary(demo_run):
    proc, _ = demo_run
    for name, text in (
        ("demo.sh", DEMO_SH.read_text(encoding="utf-8")),
        ("stdout", proc.stdout),
        ("stderr", proc.stderr),
    ):
        hit = FORBIDDEN_RE.search(text)
        assert hit is None, f"{name} uses the word {hit.group(0)!r}"
