"""The "what good looks like" figure: ``demo/demo-6.json`` and its two layouts.

The figure only teaches anything if the hand-written layout really is tighter
than the baseline's, so that gap is asserted here rather than eyeballed in the
SVG.  Nothing in this module writes into the working tree: the baseline layout
goes to ``tmp_path`` (``demo.sh`` refreshes the committed copy, a test must not).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("shapely")

import geom  # noqa: E402  (conftest puts challenges/c001/tools on sys.path)

C001_DIR = Path(__file__).resolve().parent.parent
DEMO_DIR = C001_DIR / "demo"
INSTANCE = DEMO_DIR / "demo-6.json"
IMPROVED = DEMO_DIR / "demo-6.improved.json"

#: Artefacts ``demo.sh`` regenerates and the challenge README embeds.  They live
#: in the tree rather than being built on demand, because README.md renders them
#: as ``![...](demo/baseline.svg)`` and a missing file there is a broken image.
BASELINE_JSON = DEMO_DIR / "demo-6.baseline.json"
BASELINE_SVG = DEMO_DIR / "baseline.svg"
IMPROVED_SVG = DEMO_DIR / "improved.svg"

#: How many percentage points the hand layout must beat the baseline by.  The
#: measured gap is ~15.8; the margin here is deliberately slack so that a
#: harmless baseline tweak does not fail the build, while a figure that stopped
#: illustrating anything still would.
MIN_GAP_PP = 10.0


def _validate(solution_path):
    """Run ``tools/validate.py --json`` and return ``(returncode, report)``."""
    proc = subprocess.run(
        [
            sys.executable,
            str(C001_DIR / "tools" / "validate.py"),
            str(INSTANCE),
            str(solution_path),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert lines, "validate.py printed nothing (stderr: {})".format(proc.stderr)
    report = json.loads(lines[-1])
    return proc.returncode, report


def _baseline_solution(tmp_path):
    """Pack ``demo-6.json`` with the baseline solver into ``tmp_path``."""
    out = tmp_path / "demo-6.baseline.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(C001_DIR / "tools" / "baseline.py"),
            str(INSTANCE),
            "--out",
            str(out),
            "--time-budget",
            "60",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, "baseline.py failed: {}".format(proc.stderr)
    return out


def test_demo_files_load():
    """Both committed demo files parse under the geom loaders."""
    instance = geom.load_instance(INSTANCE)
    assert instance["instance_id"] == "c001-demo-6"
    assert instance["challenge"] == "c001"
    assert instance["tier"] == 2
    assert instance["strip_width"] == 200.0
    assert instance["rotations_allowed"] == "free"
    assert len(instance["parts"]) == 6

    solution = geom.load_solution(IMPROVED)
    assert solution["instance_id"] == instance["instance_id"]
    assert len(solution["placements"]) == 6


def test_demo_instance_conventions():
    """Every part is CCW, bbox-min at the local origin, with holes present."""
    instance = geom.load_instance(INSTANCE)
    for part in instance["parts"]:
        assert part["holes"] == [], "the demo instance is tier 2: no holes"
        assert geom.signed_area(part["exterior"]) > 0, "{} is not CCW".format(part["id"])
        min_x, min_y, _, _ = geom.bbox(part["exterior"])
        assert (min_x, min_y) == pytest.approx((0.0, 0.0)), (
            "{} does not have its bbox minimum at the local origin".format(part["id"])
        )


def test_improved_layout_is_valid():
    """The hand-written layout validates (exit 0)."""
    returncode, report = _validate(IMPROVED)
    assert returncode == 0, report["summary"]
    assert report["valid"] is True
    assert report["errors"] == []


def test_baseline_layout_is_valid(tmp_path):
    """The baseline solver produces a valid layout for the demo instance too."""
    returncode, report = _validate(_baseline_solution(tmp_path))
    assert returncode == 0, report["summary"]
    assert report["valid"] is True


def test_improved_layout_is_visibly_tighter(tmp_path):
    """The whole point of the figure: the hand layout wastes far less strip."""
    _, baseline_report = _validate(_baseline_solution(tmp_path))
    _, improved_report = _validate(IMPROVED)

    baseline_pct = baseline_report["measures"]["utilization_pct"]
    improved_pct = improved_report["measures"]["utilization_pct"]

    assert improved_pct > baseline_pct + MIN_GAP_PP, (
        "the figure no longer illustrates anything: baseline {:.1f}%, "
        "improved {:.1f}% (need at least +{:.0f} points)".format(
            baseline_pct, improved_pct, MIN_GAP_PP
        )
    )
    assert (
        improved_report["measures"]["used_height"]
        < baseline_report["measures"]["used_height"]
    )


def test_improved_layout_interlocks_the_l_shapes():
    """The two L-shapes plus the 50x50 square tile a rectangle exactly.

    This is what makes the figure worth looking at, so it is pinned: the union
    of p001, p002 and p003 is the solid 150x150 block in the bottom-left corner
    of the strip (x and y in [0, 150]) minus two 50x50 corners, i.e. their
    areas add up with no loss at all.
    """
    from shapely.ops import unary_union

    instance = geom.load_instance(INSTANCE)
    solution = geom.load_solution(IMPROVED)
    polys = geom.placed_polygons(instance, solution)

    trio = [polys["p001"], polys["p002"], polys["p003"]]
    union = unary_union(trio)
    assert union.area == pytest.approx(sum(p.area for p in trio), abs=1e-6)
    assert union.bounds == pytest.approx((0.0, 0.0, 150.0, 150.0), abs=1e-6)

    # The 50x50 square sits inside the notch shared by the two L-shapes: it is
    # flush against both of them, and neither reaches into its interior.
    # ``touches()`` is deliberately not used -- the 270 degree placement carries
    # ~1e-14 of floating-point noise, which is well inside TOL_AREA but enough
    # to make an exact-boundary predicate flip.
    for l_id in ("p001", "p002"):
        assert polys[l_id].distance(polys["p003"]) < 1e-6
        assert polys[l_id].intersection(polys["p003"]).area == pytest.approx(0.0, abs=1e-9)


def test_figure_artefacts_exist_and_are_current():
    """The README figure is only a figure while its files are there and fresh.

    ``demo.sh`` writes all three; this pins them so that neither a deleted file
    (broken image in README.md) nor a baseline change that nobody re-ran the
    script after (a picture captioned with a utilization it no longer has) can
    pass unnoticed.  The SVGs are checked by their rendered utilization text
    rather than byte-compared: that catches staleness without welding the test
    to render.py's exact output.
    """
    import xml.etree.ElementTree as ET

    for path in (BASELINE_JSON, BASELINE_SVG, IMPROVED_SVG):
        assert path.is_file(), (
            "{} is missing; run `bash challenges/c001/demo.sh` to rebuild the "
            "README figure".format(path.relative_to(C001_DIR))
        )

    # The committed baseline layout must be exactly what baseline.py produces
    # today -- that one is pure arithmetic, so an exact comparison is fair.
    import baseline as baseline_tool

    fresh = baseline_tool.solve(geom.load_instance(INSTANCE))
    committed = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    assert committed["placements"] == fresh["placements"], (
        "demo/demo-6.baseline.json is stale; re-run bash challenges/c001/demo.sh"
    )

    _, baseline_report = _validate(BASELINE_JSON)
    _, improved_report = _validate(IMPROVED)
    for svg, report in ((BASELINE_SVG, baseline_report), (IMPROVED_SVG, improved_report)):
        root = ET.parse(svg).getroot()
        assert root.tag.endswith("svg")
        texts = " ".join(e.text or "" for e in root.iter() if e.tag.endswith("}text"))
        assert "c001-demo-6" in texts
        expected = "{:.1f}%".format(report["measures"]["utilization_pct"])
        assert expected in texts, "{} shows a stale utilization (expected {})".format(
            svg.name, expected
        )


def test_demo_renders(tmp_path):
    """Both figures render to SVG that parses."""
    import xml.etree.ElementTree as ET

    baseline = _baseline_solution(tmp_path)
    for solution, name in ((baseline, "baseline.svg"), (IMPROVED, "improved.svg")):
        out = tmp_path / name
        proc = subprocess.run(
            [
                sys.executable,
                str(C001_DIR / "tools" / "render.py"),
                str(INSTANCE),
                str(solution),
                "--out",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        root = ET.parse(out).getroot()
        assert root.tag.endswith("svg")
        texts = " ".join(e.text or "" for e in root.iter() if e.tag.endswith("}text"))
        assert "c001-demo-6" in texts
        assert "utilization" in texts
