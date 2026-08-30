"""Tests for ``challenges/c001/tools/validate.py``.

The fixtures under ``tests/fixtures/`` are hand-built so that each negative case
triggers exactly one error code -- the assertions compare the whole set of codes,
not just membership, which is what keeps the checks honest as validate.py grows.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

pytest.importorskip("shapely")

import geom  # noqa: E402  (conftest puts tools/ on sys.path)
import validate  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SQUARES = FIXTURES / "instance-two-squares.json"
STRIP100 = FIXTURES / "instance-strip100.json"
ROTATIONS = FIXTURES / "instance-rotations.json"
TRIANGLES = FIXTURES / "instance-touching-triangles.json"
HOLE = FIXTURES / "instance-hole.json"
NESTED = FIXTURES / "instance-nested-holes.json"
BOWTIE = FIXTURES / "instance-bowtie.json"


def sol(name):
    return FIXTURES / name


def last_json(proc):
    """Parse the last stdout line as JSON (the ``--json`` contract)."""
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert lines, "expected output on stdout, got nothing (stderr: {})".format(proc.stderr)
    return json.loads(lines[-1])


def codes(report):
    return {error["code"] for error in report["errors"]}


def run(run_tool, instance, solution, *extra):
    return run_tool("validate", instance, solution, "--json", *extra)


# --------------------------------------------------------------------------
# Fixture sanity: every fixture file loads under the geom schema
# --------------------------------------------------------------------------


def test_fixture_instances_load():
    found = sorted(FIXTURES.glob("instance-*.json"))
    assert found, "no instance fixtures found in {}".format(FIXTURES)
    for path in found:
        instance = geom.load_instance(path)
        assert instance["challenge"] == geom.CHALLENGE_ID


# --------------------------------------------------------------------------
# Positives
# --------------------------------------------------------------------------


def test_two_squares_fill_the_strip_exactly(run_tool):
    """Two 100x100 squares stacked on a width-100 strip: full utilization, exit 0."""
    proc = run(run_tool, STRIP100, sol("solution-strip100-valid.json"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.startswith("VALID  used_height=200.000  utilization=100.0%")
    report = last_json(proc)
    assert report["valid"] is True
    assert report["errors"] == []
    assert report["used_height"] == 200.0
    assert report["utilization_pct"] == 100.0


def test_touching_edge_after_rotation_is_valid(run_tool):
    """Two triangles sharing an edge exactly, both rotated 30 degrees."""
    proc = run(run_tool, TRIANGLES, sol("solution-touching-triangles.json"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = last_json(proc)
    assert report["valid"] is True
    assert report["errors"] == []


def test_part_nested_in_a_hole_is_valid_and_area_excludes_the_hole(run_tool):
    """Tier-3 style: a 40x40 part inside a 60x60 hole of a 200x200 host."""
    proc = run(run_tool, HOLE, sol("solution-hole.json"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = last_json(proc)
    assert report["valid"] is True

    instance = geom.load_instance(HOLE)
    expected_area = geom.total_area(instance)
    assert expected_area == pytest.approx(200.0 * 200.0 - 60.0 * 60.0 + 40.0 * 40.0)
    expected_pct = float(
        geom.format_pct(geom.utilization(expected_area, instance["strip_width"], report["used_height"]))
    )
    assert report["utilization_pct"] == expected_pct
    # The hole must actually be subtracted: not counting it would read higher.
    naive_pct = float(
        geom.format_pct(
            geom.utilization(200.0 * 200.0 + 40.0 * 40.0, instance["strip_width"], report["used_height"])
        )
    )
    assert naive_pct > expected_pct


@pytest.mark.parametrize(
    "solution_name",
    ["solution-rotation-ok.json", "solution-rotation-neg270.json", "solution-rotation-wrap.json"],
)
def test_rotation_list_accepts_equivalent_angles(run_tool, solution_name):
    """90.0000001 is within tolerance of 90; -270 is 90 mod 360; 359.9999999 is
    1e-7 degrees from the allowed 0 -- the tolerance has to survive the wrap."""
    proc = run(run_tool, ROTATIONS, sol(solution_name))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert last_json(proc)["valid"] is True


def test_part_nested_two_holes_deep_is_valid(run_tool):
    """pC sits in pB's hole and pB sits in pA's hole: no pair intersects."""
    proc = run(run_tool, NESTED, sol("solution-nested-holes.json"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = last_json(proc)
    assert report["valid"] is True
    assert report["errors"] == []


def test_innermost_part_straddling_its_hole_is_an_overlap(run_tool):
    """Move pC 10 units and it crosses pB's hole rim -- only that pair is named."""
    proc = run(run_tool, NESTED, sol("solution-nested-holes-straddle.json"))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    (error,) = last_json(proc)["errors"]
    assert error["code"] == "OVERLAP"
    assert sorted(error["part_ids"]) == ["pB", "pC"]


# --------------------------------------------------------------------------
# Negatives -- one code each
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "instance,solution_name,expected",
    [
        (SQUARES, "solution-overlap.json", {"OVERLAP"}),
        (STRIP100, "solution-outside-x.json", {"OUTSIDE_STRIP"}),
        (STRIP100, "solution-negative-y.json", {"OUTSIDE_STRIP"}),
        (STRIP100, "solution-negative-x.json", {"OUTSIDE_STRIP"}),
        (SQUARES, "solution-missing.json", {"MISSING_PLACEMENT"}),
        (SQUARES, "solution-duplicate.json", {"DUPLICATE_PLACEMENT"}),
        (SQUARES, "solution-unknown.json", {"UNKNOWN_PART"}),
        (SQUARES, "solution-mismatch.json", {"INSTANCE_MISMATCH"}),
        (ROTATIONS, "solution-rotation-bad.json", {"ROTATION_NOT_ALLOWED"}),
        (BOWTIE, "solution-bowtie.json", {"INVALID_GEOMETRY"}),
    ],
    ids=[
        "overlap",
        "protrudes-past-w",
        "negative-y",
        "negative-x",
        "missing",
        "duplicate",
        "unknown",
        "instance-mismatch",
        "rotation-not-allowed",
        "invalid-geometry",
    ],
)
def test_negative_cases_report_exactly_their_code(run_tool, instance, solution_name, expected):
    proc = run(run_tool, instance, sol(solution_name))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[0] == "INVALID"
    report = last_json(proc)
    assert report["valid"] is False
    assert codes(report) == expected
    for error in report["errors"]:
        assert error["message"]
        assert "{}: {}".format(error["code"], error["message"]) in proc.stdout


def test_overlap_names_both_parts_and_the_area(run_tool):
    proc = run(run_tool, SQUARES, sol("solution-overlap.json"))
    assert proc.returncode == 1
    (error,) = last_json(proc)["errors"]
    assert error["code"] == "OVERLAP"
    assert sorted(error["part_ids"]) == ["p001", "p002"]
    assert error["area"] > geom.TOL_AREA
    assert error["area"] == pytest.approx(5000.0)
    assert "5000.000000" in error["message"]


def test_outside_strip_reports_the_protruding_area(run_tool):
    """A square hanging half over the strip's right edge: 50 x 100 outside."""
    proc = run(run_tool, STRIP100, sol("solution-outside-x.json"))
    (error,) = last_json(proc)["errors"]
    assert error["code"] == "OUTSIDE_STRIP"
    assert error["part_id"] == "p002"
    assert error["area"] > geom.TOL_AREA
    assert error["area"] == pytest.approx(5000.0)


def test_negative_y_area_is_measured_not_swallowed(run_tool):
    """A square 10 units below the floor: 100 x 10 outside."""
    proc = run(run_tool, STRIP100, sol("solution-negative-y.json"))
    (error,) = last_json(proc)["errors"]
    assert error["code"] == "OUTSIDE_STRIP"
    assert error["part_id"] == "p001"
    assert error["area"] == pytest.approx(1000.0)


def test_negative_x_area_is_measured_not_swallowed(run_tool):
    """A square 10 units past the strip's left edge: 10 x 100 outside.  The
    standing strip is bounded on both sides in x, so each edge has its fixture."""
    proc = run(run_tool, STRIP100, sol("solution-negative-x.json"))
    (error,) = last_json(proc)["errors"]
    assert error["code"] == "OUTSIDE_STRIP"
    assert error["part_id"] == "p001"
    assert error["area"] == pytest.approx(1000.0)


def test_instance_mismatch_carries_both_ids(run_tool):
    proc = run(run_tool, SQUARES, sol("solution-mismatch.json"))
    (error,) = last_json(proc)["errors"]
    assert error["expected"] == "c001-fixture-squares"
    assert error["actual"] == "c001-fixture-somewhere-else"


def test_duplicate_placement_reports_the_count_once(run_tool):
    proc = run(run_tool, SQUARES, sol("solution-duplicate.json"))
    (error,) = last_json(proc)["errors"]
    assert error["part_id"] == "p001"
    assert error["count"] == 2


def test_hairline_overlap_below_the_tolerance_is_valid(run_tool):
    """Two 100-unit squares overlapping 9.9e-5 deep: 0.0099 < TOL_AREA."""
    proc = run(run_tool, SQUARES, sol("solution-hairline-under.json"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert last_json(proc)["valid"] is True


def test_hairline_overlap_above_the_tolerance_is_rejected(run_tool):
    """The same pair 1.01e-4 deep: 0.0101 > TOL_AREA, by 1% of the tolerance."""
    proc = run(run_tool, SQUARES, sol("solution-hairline-over.json"))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    (error,) = last_json(proc)["errors"]
    assert error["code"] == "OVERLAP"
    assert geom.TOL_AREA < error["area"] < 2 * geom.TOL_AREA


def test_empty_placement_list_reports_every_part(run_tool):
    """An empty ``placements`` array is a bijection failure, not a crash."""
    proc = run(run_tool, SQUARES, sol("solution-empty.json"))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    report = last_json(proc)
    assert codes(report) == {"MISSING_PLACEMENT"}
    assert {error["part_id"] for error in report["errors"]} == {"p001", "p002"}
    assert report["used_height"] == 0.0
    assert report["utilization_pct"] == 0.0


def test_all_violations_are_collected(run_tool):
    """A solution breaking three rules at once reports all of them."""
    proc = run(run_tool, SQUARES, sol("solution-multi.json"))
    assert proc.returncode == 1
    report = last_json(proc)
    assert codes(report) == {"UNKNOWN_PART", "OUTSIDE_STRIP", "OVERLAP"}
    assert len(report["errors"]) == 4  # two parts outside, one overlapping pair, one unknown id
    assert report["summary"].startswith("INVALID")


# --------------------------------------------------------------------------
# Schema failures -> exit 2
# --------------------------------------------------------------------------


def test_nan_translation_is_a_schema_error(run_tool):
    proc = run(run_tool, SQUARES, sol("solution-nan.json"))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    report = last_json(proc)
    assert codes(report) == {"SCHEMA"}
    assert report["valid"] is False
    assert report["used_height"] == 0.0
    assert report["utilization_pct"] == 0.0
    assert "finite" in report["errors"][0]["message"]


def test_missing_file_is_a_schema_error(run_tool, tmp_path):
    proc = run(run_tool, SQUARES, tmp_path / "nope.json")
    assert proc.returncode == 2
    assert codes(last_json(proc)) == {"SCHEMA"}


def test_malformed_json_is_a_schema_error(run_tool, tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    proc = run(run_tool, SQUARES, broken)
    assert proc.returncode == 2
    assert codes(last_json(proc)) == {"SCHEMA"}


def test_non_object_solution_is_named_once_not_twice(run_tool):
    """geom already prefixes its top-level message; validate must not repeat it."""
    proc = run(run_tool, SQUARES, sol("solution-not-an-object.json"))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    (error,) = last_json(proc)["errors"]
    assert error["code"] == "SCHEMA"
    assert error["file"] == "solution"
    assert "solution: solution:" not in error["message"]
    assert error["message"].startswith("solution: ")
    assert "solution: solution:" not in proc.stdout


def test_schema_message_is_prefixed_when_geom_omits_the_file_word(run_tool, tmp_path):
    """A field-level message carries no file word, so the prefix is still added."""
    broken = tmp_path / "no-placements.json"
    broken.write_text('{"instance_id": "c001-fixture-squares"}', encoding="utf-8")
    proc = run(run_tool, SQUARES, broken)
    assert proc.returncode == 2
    (error,) = last_json(proc)["errors"]
    assert error["message"] == "solution: placements: required field is missing"


def test_schema_report_still_carries_every_required_key(run_tool):
    proc = run(run_tool, SQUARES, sol("solution-nan.json"))
    report = last_json(proc)
    for key in ("valid", "instance_id", "used_height", "utilization_pct", "summary", "errors", "measures"):
        assert key in report


# --------------------------------------------------------------------------
# Output contract
# --------------------------------------------------------------------------


def test_json_object_is_the_last_line_and_has_the_documented_shape(run_tool):
    proc = run(run_tool, SQUARES, sol("solution-overlap.json"))
    report = last_json(proc)
    assert set(report) >= {
        "valid",
        "instance_id",
        "used_height",
        "utilization_pct",
        "summary",
        "errors",
        "measures",
    }
    assert isinstance(report["valid"], bool)
    assert isinstance(report["used_height"], float)
    assert isinstance(report["utilization_pct"], float)
    assert isinstance(report["summary"], str)
    # summary is the human headline, widened on failure with the violation count
    # and the distinct codes (documented in validate.py's module docstring).
    assert report["summary"].startswith("INVALID")
    assert report["measures"] == {
        "utilization_pct": report["utilization_pct"],
        "used_height": report["used_height"],
    }
    assert report["instance_id"] == "c001-fixture-squares"


def test_readme_json_example_carries_exactly_the_keys_the_tool_emits(run_tool, c001_dir):
    """The README block is the participant's key list; drift there is the defect."""
    readme = (c001_dir / "README.md").read_text(encoding="utf-8")
    blocks = [json.loads(block) for block in re.findall(r"```json\n(.*?)```", readme, re.DOTALL)]
    # Select on the report's shape, not on a key the assertions below are about,
    # so a dropped key fails the key-set comparison rather than the selector.
    documented = [block for block in blocks if "summary" in block]
    assert len(documented) == 1, "expected exactly one --json example in the c001 README"
    live = last_json(run(run_tool, STRIP100, sol("solution-strip100-valid.json")))
    assert set(documented[0]) == set(live)
    assert set(documented[0].get("measures", {})) == set(live["measures"])


def test_without_json_flag_nothing_machine_readable_is_printed(run_tool):
    proc = run_tool("validate", STRIP100, sol("solution-strip100-valid.json"))
    assert proc.returncode == 0
    assert proc.stdout.splitlines() == ["VALID  used_height=200.000  utilization=100.0%"]


def test_printed_and_json_measures_agree(run_tool):
    proc = run(run_tool, HOLE, sol("solution-hole.json"))
    report = last_json(proc)
    assert "used_height={:.3f}".format(report["used_height"]) in proc.stdout
    assert "utilization={}%".format(geom.format_pct(report["utilization_pct"] / 100.0)) in proc.stdout


def test_labels_without_svg_is_a_no_op(run_tool):
    proc = run_tool("validate", STRIP100, sol("solution-strip100-valid.json"), "--labels")
    assert proc.returncode == 0
    assert proc.stdout.startswith("VALID")


def test_labels_help_text_says_it_needs_svg():
    """--labels is ignored without --svg; the help text must say so plainly."""
    help_text = " ".join(validate.build_parser().format_help().split())  # argparse rewraps
    assert "--labels label parts with their ids in the rendered SVG" in help_text
    assert "(ignored unless --svg is given)" in help_text


def test_svg_flag_never_changes_the_exit_code(run_tool, tmp_path):
    """render.py is optional here: a missing or failing renderer only warns."""
    out = tmp_path / "layout.svg"
    proc = run(run_tool, STRIP100, sol("solution-strip100-valid.json"), "--svg", out)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert last_json(proc)["valid"] is True
    if not out.exists():
        assert "warning" in proc.stderr.lower()


# --------------------------------------------------------------------------
# In-process API
# --------------------------------------------------------------------------


def test_validate_function_returns_errors_and_measures():
    instance = geom.load_instance(STRIP100)
    solution = geom.load_solution(sol("solution-strip100-valid.json"))
    errors, used_h, util = validate.validate(instance, solution)
    assert errors == []
    assert used_h == pytest.approx(200.0)
    assert util == pytest.approx(1.0)


def test_validate_function_flags_the_overlap():
    instance = geom.load_instance(SQUARES)
    solution = geom.load_solution(sol("solution-overlap.json"))
    errors, _used_h, _util = validate.validate(instance, solution)
    assert [error["code"] for error in errors] == ["OVERLAP"]


def test_main_returns_the_documented_exit_codes(capsys, tmp_path):
    assert validate.main([str(STRIP100), str(sol("solution-strip100-valid.json"))]) == 0
    assert validate.main([str(SQUARES), str(sol("solution-overlap.json"))]) == 1
    assert validate.main([str(SQUARES), str(tmp_path / "absent.json")]) == 2
    capsys.readouterr()


# --------------------------------------------------------------------------
# Performance
# --------------------------------------------------------------------------


def _grid_instance(path, cols=10, rows=6, side=100.0):
    """A 60-part instance of touching unit squares, ten across the strip and
    six high: the worst case for the pairwise stage, since every neighbour pair
    reports ``intersects``."""
    parts = []
    placements = []
    for col in range(cols):
        for row in range(rows):
            part_id = "p{:03d}".format(len(parts) + 1)
            parts.append(
                {
                    "id": part_id,
                    "exterior": [[0.0, 0.0], [side, 0.0], [side, side], [0.0, side]],
                    "holes": [],
                }
            )
            placements.append(
                {
                    "part_id": part_id,
                    "translation": [col * side, row * side],
                    "rotation_deg": 0.0,
                }
            )
    instance = {
        "instance_id": "c001-fixture-grid",
        "challenge": "c001",
        "tier": 1,
        "seed": 60,
        "strip_width": cols * side,
        "rotations_allowed": "free",
        "parts": parts,
    }
    solution = {"instance_id": "c001-fixture-grid", "placements": placements}
    instance_path = path / "grid-instance.json"
    solution_path = path / "grid-solution.json"
    geom.write_json(instance, instance_path)
    geom.write_json(solution, solution_path)
    return instance_path, solution_path


def test_sixty_parts_validate_within_five_seconds(run_tool, tmp_path):
    instance_path, solution_path = _grid_instance(tmp_path)
    started = time.monotonic()
    proc = run(run_tool, instance_path, solution_path)
    elapsed = time.monotonic() - started
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = last_json(proc)
    assert report["valid"] is True
    assert report["errors"] == []
    # The grid really was measured: 6 rows of 100 units, every pair touching.
    assert report["used_height"] == 600.0
    assert report["utilization_pct"] == 100.0
    assert elapsed < 5.0, "validate took {:.2f}s for 60 parts".format(elapsed)


def test_sixty_part_instance_really_has_sixty_parts(tmp_path):
    instance_path, _solution_path = _grid_instance(tmp_path)
    assert len(geom.load_instance(instance_path)["parts"]) == 60
