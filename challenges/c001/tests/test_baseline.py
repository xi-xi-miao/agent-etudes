"""Tests for the c001 bounding-box shelf-packing baseline solver.

Covered here: the 0/90 orientation rule, the translation that compensates for a
rotation about the local origin, an end-to-end pack of a synthetic instance
through ``validate.py``, the same over every committed dev instance, and the
CLI surface participants have to mirror (``--out``/``--time-budget``/``--seed``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("shapely")

import baseline  # noqa: E402  (conftest puts tools/ on sys.path)
import geom  # noqa: E402

C001_DIR = Path(__file__).resolve().parent.parent
DEV_DIR = C001_DIR / "instances" / "dev"
DEV_INSTANCES = sorted(DEV_DIR.glob("*.json")) if DEV_DIR.is_dir() else []

#: One visible skip beats a parametrized test that silently expands to nothing
#: while generate.py has not written the dev set yet.
DEV_PARAMS = DEV_INSTANCES or [
    pytest.param(None, marks=pytest.mark.skip(reason="instances/dev is empty"))
]
DEV_IDS = [p.stem for p in DEV_INSTANCES] or ["none"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def rect_part(part_id, width, height):
    """A CCW axis-aligned rectangle with its bbox minimum at the local origin."""
    return {
        "id": part_id,
        "exterior": [[0.0, 0.0], [width, 0.0], [width, height], [0.0, height]],
        "holes": [],
    }


def make_instance(parts, strip_width=1000.0, **overrides):
    instance = {
        "instance_id": "c001-t1-dev-99",
        "challenge": "c001",
        "tier": 1,
        "seed": 99,
        "strip_width": float(strip_width),
        "rotations_allowed": "free",
        "parts": parts,
    }
    instance.update(overrides)
    return instance


def require_validator(tools_dir):
    if not (tools_dir / "validate.py").is_file():
        pytest.skip("tools/validate.py does not exist yet")


# --------------------------------------------------------------------------
# orientation rule
# --------------------------------------------------------------------------


def test_orientation_prefers_the_thinner_column():
    """A 100x800 part fits both ways at W=1000; the thin 0 deg column wins."""
    part = rect_part("p001", 100.0, 800.0)
    rotation, minx, miny, x_extent, y_extent = baseline.choose_orientation(part, 1000.0)

    assert rotation == 0.0
    assert x_extent == pytest.approx(100.0)
    assert y_extent == pytest.approx(800.0)
    assert (minx, miny) == pytest.approx((0.0, 0.0))


def test_orientation_rotates_a_part_too_tall_for_the_strip():
    """A 100x1200 part cannot stand upright at W=1000, so it must lie down."""
    part = rect_part("p001", 100.0, 1200.0)
    rotation, minx, miny, x_extent, y_extent = baseline.choose_orientation(part, 1000.0)

    assert rotation == 90.0
    assert x_extent == pytest.approx(1200.0)
    assert y_extent == pytest.approx(100.0)
    # Rotating CCW about the local origin swings the box into negative x.
    assert minx == pytest.approx(-1200.0)
    assert miny == pytest.approx(0.0)


def test_orientation_tie_prefers_the_shorter_part():
    """Both orientations of a square are equally thin; the rule stays total."""
    rotation, _minx, _miny, x_extent, y_extent = baseline.choose_orientation(
        rect_part("p001", 50.0, 50.0), 1000.0
    )
    assert rotation == 0.0
    assert (x_extent, y_extent) == pytest.approx((50.0, 50.0))


def test_orientation_honours_a_rotation_list():
    """With rotations restricted to 90 deg, the 0 deg option is not available."""
    part = rect_part("p001", 100.0, 800.0)
    rotation, _minx, _miny, x_extent, _y_extent = baseline.choose_orientation(
        part, 1000.0, allowed=[90.0]
    )
    assert rotation == 90.0
    assert x_extent == pytest.approx(800.0)


def test_part_that_fits_no_orientation_is_rejected():
    part = rect_part("p001", 1500.0, 1200.0)
    with pytest.raises(baseline.BaselineError) as excinfo:
        baseline.choose_orientation(part, 1000.0)
    assert "p001" in str(excinfo.value)


# --------------------------------------------------------------------------
# translation compensation and column layout
# --------------------------------------------------------------------------


def placed_bounds(instance, solution):
    return {pid: poly.bounds for pid, poly in geom.placed_polygons(instance, solution).items()}


def test_rotated_part_lands_flush_against_its_column():
    """translation = (col_x - minx_rot, y - miny_rot) must undo the negative-x
    swing of a 90 deg rotation, so the placed part starts exactly at x = 0."""
    instance = make_instance([rect_part("p001", 100.0, 1200.0)])
    solution = baseline.solve(instance)

    placement = solution["placements"][0]
    assert placement["rotation_deg"] == 90.0
    assert placement["translation"][0] == pytest.approx(1200.0)

    minx, miny, maxx, maxy = placed_bounds(instance, solution)["p001"]
    assert minx == pytest.approx(0.0, abs=1e-9)
    assert miny == pytest.approx(0.0, abs=1e-9)
    assert maxx == pytest.approx(1200.0, abs=1e-9)
    assert maxy == pytest.approx(100.0, abs=1e-9)


def test_columns_start_where_the_previous_one_ended():
    """Two 600-tall parts cannot share a 1000-wide column, so the second one
    opens a new column at x = the first column's thickness."""
    instance = make_instance(
        [rect_part("p001", 300.0, 600.0), rect_part("p002", 200.0, 600.0)],
        strip_width=1000.0,
    )
    solution = baseline.solve(instance)
    bounds = placed_bounds(instance, solution)

    # Thickest column first: p001 (300 wide) opens column 0 at x = 0.
    assert bounds["p001"][0] == pytest.approx(0.0, abs=1e-9)
    assert bounds["p002"][0] == pytest.approx(300.0, abs=1e-9)
    assert bounds["p001"][1] == pytest.approx(0.0, abs=1e-9)
    assert bounds["p002"][1] == pytest.approx(0.0, abs=1e-9)


def test_parts_stack_upward_inside_one_column():
    instance = make_instance(
        [rect_part("p001", 300.0, 400.0), rect_part("p002", 200.0, 400.0)],
        strip_width=1000.0,
    )
    solution = baseline.solve(instance)
    bounds = placed_bounds(instance, solution)

    assert bounds["p001"][0] == pytest.approx(0.0, abs=1e-9)
    assert bounds["p002"][0] == pytest.approx(0.0, abs=1e-9)
    assert bounds["p001"][1] == pytest.approx(0.0, abs=1e-9)
    assert bounds["p002"][1] == pytest.approx(400.0, abs=1e-9)
    # One column only: the used length is the single column's thickness.
    assert geom.used_length(geom.placed_polygons(instance, solution).values()) == pytest.approx(
        300.0, abs=1e-9
    )


def test_first_fit_reuses_an_earlier_column_not_just_the_last():
    """First fit means *first* open column, not the most recently opened one.

    Three parts at W=1000, in the order the thickness sort puts them:

    * p001 300x850 opens column 0 at x=0, leaving 150 of y-room;
    * p002 200x950 does not fit column 0, so it opens column 1 at x=300;
    * p003 100x100 fits column 0 (850+100) but not column 1 (950+100).

    A next-fit regression that only looked at ``columns[-1]`` would open a third
    column for p003 and stretch the used length from 500 to 600, so both the
    placement and the used length are pinned here.
    """
    instance = make_instance(
        [
            rect_part("p001", 300.0, 850.0),
            rect_part("p002", 200.0, 950.0),
            rect_part("p003", 100.0, 100.0),
        ],
        strip_width=1000.0,
    )
    solution = baseline.solve(instance)
    bounds = placed_bounds(instance, solution)

    assert bounds["p003"][0] == pytest.approx(0.0, abs=1e-9), "p003 skipped column 0"
    assert bounds["p003"][1] == pytest.approx(850.0, abs=1e-9)
    assert geom.used_length(geom.placed_polygons(instance, solution).values()) == pytest.approx(
        500.0, abs=1e-9
    ), "a third column was opened, so the scan is next-fit rather than first-fit"


def test_every_part_gets_exactly_one_placement(tiny_instance):
    instance = tiny_instance()
    solution = baseline.solve(instance)
    placed = [p["part_id"] for p in solution["placements"]]
    assert sorted(placed) == sorted(part["id"] for part in instance["parts"])
    assert len(placed) == len(set(placed))


# --------------------------------------------------------------------------
# end to end: a synthetic instance through baseline.py and validate.py
# --------------------------------------------------------------------------


def synthetic_five_part_instance():
    """Five mixed parts: three rectangles, a tall sliver and a right triangle."""
    parts = [
        rect_part("p001", 420.0, 610.0),
        rect_part("p002", 260.0, 340.0),
        rect_part("p003", 180.0, 900.0),
        rect_part("p004", 90.0, 1150.0),  # too tall upright -> must be rotated
        {
            "id": "p005",
            "exterior": [[0.0, 0.0], [300.0, 0.0], [0.0, 250.0]],
            "holes": [],
        },
    ]
    return make_instance(parts, strip_width=1000.0)


def test_five_part_instance_packs_and_validates(tmp_path, tools_dir, run_tool):
    require_validator(tools_dir)

    instance = synthetic_five_part_instance()
    instance_path = tmp_path / "synthetic.json"
    geom.write_json(instance, instance_path)
    solution_path = tmp_path / "synthetic.baseline.json"

    packed = run_tool("baseline", instance_path, "--out", solution_path)
    assert packed.returncode == 0, packed.stderr
    assert "placed 5 parts" in packed.stderr
    assert "used_length=" in packed.stderr
    assert "utilization=" in packed.stderr

    checked = run_tool("validate", instance_path, solution_path, "--json")
    assert checked.returncode == 0, checked.stdout + checked.stderr

    written = json.loads(solution_path.read_text(encoding="utf-8"))
    assert written["instance_id"] == instance["instance_id"]
    assert len(written["placements"]) == 5

    used, util = baseline.measure(instance, written)
    assert used > 0
    assert 0.0 < util < 1.0


def test_summary_line_matches_the_computed_measure(tmp_path, run_tool):
    instance = synthetic_five_part_instance()
    instance_path = tmp_path / "synthetic.json"
    geom.write_json(instance, instance_path)
    solution_path = tmp_path / "out.json"

    packed = run_tool("baseline", instance_path, "--out", solution_path)
    assert packed.returncode == 0, packed.stderr

    solution = geom.load_solution(solution_path)
    _used, util = baseline.measure(geom.load_instance(instance_path), solution)
    assert "utilization={}%".format(geom.format_pct(util)) in packed.stderr


def test_quiet_suppresses_the_summary_line(tmp_path, run_tool):
    instance_path = tmp_path / "synthetic.json"
    geom.write_json(synthetic_five_part_instance(), instance_path)

    packed = run_tool("baseline", instance_path, "--out", tmp_path / "out.json", "--quiet")
    assert packed.returncode == 0, packed.stderr
    assert "placed" not in packed.stderr
    assert "utilization=" not in packed.stderr


# --------------------------------------------------------------------------
# CLI surface
# --------------------------------------------------------------------------


def test_cli_accepts_time_budget_and_records_the_seed(tmp_path, run_tool):
    instance_path = tmp_path / "synthetic.json"
    geom.write_json(synthetic_five_part_instance(), instance_path)
    solution_path = tmp_path / "seeded.json"

    packed = run_tool(
        "baseline",
        instance_path,
        "--out",
        solution_path,
        "--time-budget",
        "5",
        "--seed",
        "7",
    )
    assert packed.returncode == 0, packed.stderr

    written = json.loads(solution_path.read_text(encoding="utf-8"))
    assert written["solver"] == {"name": "baseline-shelf", "version": "1.0", "seed": 7}


def test_seed_does_not_change_the_layout(tmp_path, run_tool):
    instance_path = tmp_path / "synthetic.json"
    geom.write_json(synthetic_five_part_instance(), instance_path)

    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    assert run_tool("baseline", instance_path, "--out", first, "--seed", "0").returncode == 0
    assert run_tool("baseline", instance_path, "--out", second, "--seed", "12345").returncode == 0

    a = json.loads(first.read_text(encoding="utf-8"))
    b = json.loads(second.read_text(encoding="utf-8"))
    assert a["placements"] == b["placements"]


def test_pack_honours_a_rotation_list_end_to_end(tmp_path, tools_dir, run_tool):
    """``rotations_allowed`` must survive the trip from the instance file into
    every emitted placement.

    ``choose_orientation`` has its own unit test, but the interesting failure is
    a plumbing one: if ``pack`` stopped forwarding ``allowed`` the default of
    ``"free"`` would silently re-admit 0 deg and the validator would answer
    ROTATION_NOT_ALLOWED.  README.md ("File formats", Instance) makes the list
    binding, so it is checked through both CLIs.
    """
    require_validator(tools_dir)

    instance = make_instance(
        [rect_part("p001", 300.0, 600.0), rect_part("p002", 200.0, 400.0)],
        strip_width=1000.0,
        rotations_allowed=[90.0],
    )
    instance_path = tmp_path / "rot90.json"
    geom.write_json(instance, instance_path)
    solution_path = tmp_path / "rot90.baseline.json"

    packed = run_tool("baseline", instance_path, "--out", solution_path)
    assert packed.returncode == 0, packed.stderr

    written = json.loads(solution_path.read_text(encoding="utf-8"))
    assert [p["rotation_deg"] for p in written["placements"]] == [90.0, 90.0]

    checked = run_tool("validate", instance_path, solution_path, "--json")
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_cli_reports_an_unreadable_instance(tmp_path, run_tool):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    packed = run_tool("baseline", bad, "--out", tmp_path / "out.json")
    assert packed.returncode == 2
    assert "baseline.py:" in packed.stderr


# --------------------------------------------------------------------------
# every committed dev instance
# --------------------------------------------------------------------------


@pytest.mark.parametrize("instance_path", DEV_PARAMS, ids=DEV_IDS)
def test_dev_instance_packs_validly_with_a_plausible_measure(
    instance_path, tmp_path, tools_dir, run_tool
):
    require_validator(tools_dir)

    solution_path = tmp_path / (instance_path.stem + ".baseline.json")
    packed = run_tool("baseline", instance_path, "--out", solution_path)
    assert packed.returncode == 0, packed.stderr

    checked = run_tool("validate", instance_path, solution_path, "--json")
    assert checked.returncode == 0, checked.stdout + checked.stderr

    instance = geom.load_instance(instance_path)
    solution = geom.load_solution(solution_path)
    used, util = baseline.measure(instance, solution)
    pct = float(geom.format_pct(util))
    assert 25.0 <= pct <= 75.0, "{}: utilization {}% (used_length={:.3f}) is outside the " \
        "25-75% band expected of bounding-box shelf packing".format(instance_path.stem, pct, used)


def test_dev_set_is_complete():
    """Re-glob rather than trusting the collection-time snapshot: generate.py may
    have written the dev set after this module was imported."""
    committed = sorted(DEV_DIR.glob("*.json")) if DEV_DIR.is_dir() else []
    if not committed:
        pytest.skip("instances/dev is empty")
    assert len(committed) == 15, "expected 15 dev instances, found {}".format(len(committed))
