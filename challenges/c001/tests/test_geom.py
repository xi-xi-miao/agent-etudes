"""Unit tests for ``challenges/c001/tools/geom.py``."""

from __future__ import annotations

import json
import math

import pytest

pytest.importorskip("shapely")

import geom  # noqa: E402  (must follow the importorskip above)

from shapely.geometry import Polygon  # noqa: E402


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def ring_of(poly):
    """Exterior ring of a Shapely polygon, without the repeated closing vertex."""
    return [list(pt) for pt in poly.exterior.coords[:-1]]


def dump(path, obj):
    """Write JSON exactly as given (NaN allowed), bypassing geom.write_json."""
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def valid_instance():
    return {
        "instance_id": "c001-t1-dev-01",
        "challenge": "c001",
        "tier": 1,
        "seed": 1001,
        "strip_width": 1000.0,
        "rotations_allowed": "free",
        "parts": [
            {"id": "p001", "exterior": [[0, 0], [10, 0], [10, 10], [0, 10]], "holes": []},
            {"id": "p002", "exterior": [[0, 0], [5, 0], [0, 5]], "holes": []},
        ],
    }


def valid_solution():
    return {
        "instance_id": "c001-t1-dev-01",
        "solver": {"name": "baseline", "version": "0.1"},
        "placements": [
            {"part_id": "p001", "translation": [0.0, 0.0], "rotation_deg": 0.0},
            {"part_id": "p002", "translation": [20.0, 0.0], "rotation_deg": 90.0},
        ],
    }


# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------


def test_constants():
    assert geom.TOL_AREA == 0.01
    assert geom.CHALLENGE_ID == "c001"
    assert geom.DEFAULT_STRIP_WIDTH == 1000.0
    assert len(geom.PALETTE) == 12
    assert all(isinstance(c, str) and c.startswith("#") and len(c) == 7 for c in geom.PALETTE)
    assert len(set(geom.PALETTE)) == 12
    assert issubclass(geom.InstanceError, ValueError)
    assert issubclass(geom.SolutionError, ValueError)


# --------------------------------------------------------------------------
# transforms
# --------------------------------------------------------------------------


def test_transform_triangle_90_then_translate():
    """Rotate CCW 90 deg, then translate -- the placement transform of README.md
    ("Geometry conventions")."""
    tri = [[0.0, 0.0], [100.0, 0.0], [0.0, 50.0]]
    got = geom.transform_ring(tri, [10.0, 20.0], 90.0)
    expected = [(10.0, 20.0), (10.0, 120.0), (-40.0, 20.0)]
    for (gx, gy), (ex, ey) in zip(got, expected):
        assert gx == pytest.approx(ex, abs=1e-9)
        assert gy == pytest.approx(ey, abs=1e-9)


def test_transform_order_is_rotate_then_translate():
    """Translate-then-rotate would give a different answer; make sure it does not."""
    ring = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]
    got = geom.transform_ring(ring, [100.0, 0.0], 90.0)
    assert got[0][0] == pytest.approx(100.0)
    assert got[0][1] == pytest.approx(0.0)


@pytest.mark.parametrize("rot", [0.0, 37.5, 90.0, 180.0, -45.0, 359.9])
@pytest.mark.parametrize("trans", [[0.0, 0.0], [10.0, 20.0], [-3.25, 7.5]])
def test_transform_ring_agrees_with_transform_polygon(rot, trans):
    ring = [[0.0, 0.0], [40.0, 0.0], [40.0, 25.0], [12.0, 30.0]]
    poly = Polygon(ring)
    via_shapely = ring_of(geom.transform_polygon(poly, trans, rot))
    via_python = geom.transform_ring(ring, trans, rot)
    assert len(via_shapely) == len(via_python)
    for (ax, ay), (bx, by) in zip(via_shapely, via_python):
        assert ax == pytest.approx(bx, abs=1e-9)
        assert ay == pytest.approx(by, abs=1e-9)


def test_transform_polygon_keeps_holes_and_area():
    part = {
        "id": "h",
        "exterior": [[0, 0], [100, 0], [100, 100], [0, 100]],
        "holes": [[[20, 20], [20, 40], [40, 40], [40, 20]]],
    }
    poly = geom.part_polygon(part)
    moved = geom.transform_polygon(poly, [5.0, 5.0], 31.0)
    assert len(moved.interiors) == 1
    assert moved.area == pytest.approx(poly.area)


def test_transform_polygon_rotates_about_local_origin_not_centroid():
    """A centroid-based rotation (shapely.affinity.rotate) would keep the centroid."""
    square = Polygon([[0, 0], [10, 0], [10, 10], [0, 10]])
    turned = geom.transform_polygon(square, [0.0, 0.0], 180.0)
    minx, miny, maxx, maxy = turned.bounds
    assert (minx, miny, maxx, maxy) == pytest.approx((-10.0, -10.0, 0.0, 0.0), abs=1e-9)


# --------------------------------------------------------------------------
# ring arithmetic
# --------------------------------------------------------------------------


def test_signed_area_sign_and_magnitude():
    ccw = [[0, 0], [10, 0], [10, 10], [0, 10]]
    assert geom.signed_area(ccw) == pytest.approx(100.0)
    assert geom.signed_area(list(reversed(ccw))) == pytest.approx(-100.0)
    assert geom.signed_area([[0, 0], [1, 1]]) == 0.0


def test_ensure_ccw_and_cw_return_new_lists():
    cw = [[0, 0], [0, 10], [10, 10], [10, 0]]
    ccw = geom.ensure_ccw(cw)
    assert geom.signed_area(ccw) > 0
    assert cw == [[0, 0], [0, 10], [10, 10], [10, 0]]  # untouched
    assert geom.ensure_ccw(ccw) == ccw  # idempotent
    back = geom.ensure_cw(ccw)
    assert geom.signed_area(back) < 0
    assert geom.ensure_cw(back) == back


def test_canonical_ring_keeps_orientation_and_vertex_set():
    ring = [[10, 0], [10, 10], [0, 10], [0, 0]]
    canon = geom.canonical_ring(ring)
    assert canon[0] == [0, 0]
    assert geom.signed_area(canon) == pytest.approx(geom.signed_area(ring))
    assert sorted(map(tuple, canon)) == sorted(map(tuple, ring))
    assert geom.canonical_ring(canon) == canon  # idempotent


def test_canonical_ring_breaks_x_ties_on_y():
    ring = [[5, 5], [0, 9], [0, 1], [9, 0]]
    assert geom.canonical_ring(ring)[0] == [0, 1]


def test_bbox():
    assert geom.bbox([[1, 2], [-3, 8], [4, 0]]) == (-3, 0, 4, 8)
    with pytest.raises(ValueError):
        geom.bbox([])


def test_point_set_diameter_of_a_square():
    square = [[0, 0], [100, 0], [100, 100], [0, 100]]
    assert geom.point_set_diameter(square) == pytest.approx(100.0 * math.sqrt(2.0))
    assert geom.point_set_diameter([[3, 4]]) == 0.0
    assert geom.point_set_diameter([]) == 0.0
    assert geom.point_set_diameter([[0, 0], [3, 4]]) == pytest.approx(5.0)


# --------------------------------------------------------------------------
# parts
# --------------------------------------------------------------------------


def test_part_polygon_with_a_hole_subtracts_it():
    part = {
        "id": "p",
        "exterior": [[0, 0], [100, 0], [100, 100], [0, 100]],
        "holes": [[[20, 20], [20, 60], [60, 60], [60, 20]]],
    }
    poly = geom.part_polygon(part)
    assert poly.is_valid
    assert poly.area == pytest.approx(100 * 100 - 40 * 40)
    assert geom.part_area(part) == pytest.approx(100 * 100 - 40 * 40)
    assert geom.part_area(part) == pytest.approx(poly.area)


def test_part_polygon_tolerates_absent_holes_key():
    part = {"id": "p", "exterior": [[0, 0], [10, 0], [0, 10]]}
    assert geom.part_polygon(part).area == pytest.approx(50.0)
    assert geom.part_area(part) == pytest.approx(50.0)


def test_total_area(tiny_instance):
    instance = tiny_instance()
    assert geom.total_area(instance) == pytest.approx(40 * 40 + 0.5 * 30 * 30 + 20 * 20)


def test_placed_polygons(tiny_instance):
    instance = tiny_instance()
    solution = {
        "instance_id": instance["instance_id"],
        "placements": [
            {"part_id": "p001", "translation": [0.0, 0.0], "rotation_deg": 0.0},
            {"part_id": "p002", "translation": [50.0, 0.0], "rotation_deg": 0.0},
            {"part_id": "p003", "translation": [0.0, 50.0], "rotation_deg": 0.0},
        ],
    }
    placed = geom.placed_polygons(instance, solution)
    assert set(placed) == {"p001", "p002", "p003"}
    assert placed["p001"].bounds == pytest.approx((0.0, 0.0, 40.0, 40.0))
    assert placed["p003"].bounds == pytest.approx((0.0, 50.0, 20.0, 70.0))


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda p: p[:-1], "no placement"),
        (lambda p: p + [dict(p[0])], "duplicate"),
        (lambda p: p[:-1] + [{"part_id": "nope", "translation": [0, 0], "rotation_deg": 0}], "unknown"),
    ],
)
def test_placed_polygons_rejects_non_bijections(tiny_instance, mutate, fragment):
    instance = tiny_instance()
    placements = [
        {"part_id": pid, "translation": [0.0, 0.0], "rotation_deg": 0.0}
        for pid in ("p001", "p002", "p003")
    ]
    solution = {"instance_id": instance["instance_id"], "placements": mutate(placements)}
    with pytest.raises(geom.SolutionError) as excinfo:
        geom.placed_polygons(instance, solution)
    assert fragment in str(excinfo.value)


# --------------------------------------------------------------------------
# measures
# --------------------------------------------------------------------------


def test_used_length():
    assert geom.used_length([]) == 0.0
    a = Polygon([[0, 0], [10, 0], [10, 10], [0, 10]])
    b = Polygon([[50, 0], [123.5, 0], [123.5, 10], [50, 10]])
    assert geom.used_length([a, b]) == pytest.approx(123.5)
    assert geom.used_length([a]) == pytest.approx(10.0)


def test_utilization_and_format_pct():
    assert geom.utilization(500_000.0, 1000.0, 1000.0) == pytest.approx(0.5)
    assert geom.utilization(1.0, 1000.0, 0.0) == 0.0
    assert geom.utilization(1.0, 1000.0, -5.0) == 0.0
    assert geom.utilization(0.0, 1000.0, 10.0) == 0.0
    assert geom.utilization(1e9, 1000.0, 1.0) == 1.0  # clamped
    assert 0.0 <= geom.utilization(2.35e6, 1000.0, 4700.0) <= 1.0
    assert geom.format_pct(0.5) == "50.0"
    assert geom.format_pct(0.4567) == "45.7"
    assert geom.format_pct(1.0) == "100.0"
    assert geom.format_pct(0.0) == "0.0"


# --------------------------------------------------------------------------
# rotation constraint
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rot, allowed, expected",
    [
        (-90.0, [270.0], True),
        (360.0000005, [0.0], True),
        (45.0, [0.0, 90.0], False),
        (0.0, "free", True),
        (37.5, "free", True),
        (-1234.5, "free", True),
        (90.0, [0.0, 90.0, 180.0, 270.0], True),
        (270.0, [-90.0], True),
        (0.0, [], False),
        (0.001, [0.0], False),
        (720.0, [0.0], True),
    ],
)
def test_rotation_allowed(rot, allowed, expected):
    assert geom.rotation_allowed(rot, allowed) is expected


# --------------------------------------------------------------------------
# instance ids
# --------------------------------------------------------------------------


def test_instance_ids():
    assert geom.dev_instance_id(1, 1001) == "c001-t1-dev-01"
    assert geom.dev_instance_id(2, 2005) == "c001-t2-dev-05"
    assert geom.dev_instance_id(3, 3003) == "c001-t3-dev-03"
    assert geom.hidden_instance_id(1, 1) == "c001-t1-hidden-01"
    assert geom.hidden_instance_id(3, 12) == "c001-t3-hidden-12"


# --------------------------------------------------------------------------
# load_instance
# --------------------------------------------------------------------------


def test_load_instance_round_trip(tmp_path):
    path = dump(tmp_path / "i.json", valid_instance())
    loaded = geom.load_instance(path)
    assert loaded["instance_id"] == "c001-t1-dev-01"
    assert loaded["strip_width"] == 1000.0
    assert loaded["parts"][0]["exterior"][1] == [10.0, 0.0]
    assert all(isinstance(v, float) for v in loaded["parts"][0]["exterior"][0])


def test_load_instance_accepts_a_rotation_list(tmp_path):
    data = valid_instance()
    data["rotations_allowed"] = [0, 90, 180, 270]
    loaded = geom.load_instance(dump(tmp_path / "i.json", data))
    assert loaded["rotations_allowed"] == [0.0, 90.0, 180.0, 270.0]


def _drop(field):
    def _mutate(data):
        data.pop(field)
    return _mutate


INSTANCE_CASES = [
    ("missing instance_id", _drop("instance_id"), "instance_id"),
    ("missing challenge", _drop("challenge"), "challenge"),
    ("missing tier", _drop("tier"), "tier"),
    ("missing parts", _drop("parts"), "parts"),
    ("bad tier value", lambda d: d.update(tier=4), "tier"),
    ("bad tier type", lambda d: d.update(tier=True), "tier"),
    ("bad tier string", lambda d: d.update(tier="1"), "tier"),
    ("bad seed", lambda d: d.update(seed=1.5), "seed"),
    ("zero strip_width", lambda d: d.update(strip_width=0), "strip_width"),
    ("negative strip_width", lambda d: d.update(strip_width=-1000.0), "strip_width"),
    ("nan strip_width", lambda d: d.update(strip_width=float("nan")), "strip_width"),
    ("bad rotations string", lambda d: d.update(rotations_allowed="any"), "rotations_allowed"),
    ("bad rotations type", lambda d: d.update(rotations_allowed=90), "rotations_allowed"),
    ("nan in rotations", lambda d: d.update(rotations_allowed=[0, float("inf")]), "rotations_allowed[1]"),
    ("empty parts", lambda d: d.update(parts=[]), "parts"),
    ("parts not a list", lambda d: d.update(parts={"id": "p001"}), "parts"),
    ("part not an object", lambda d: d["parts"].__setitem__(1, "p002"), "parts[1]"),
    ("missing part id", lambda d: d["parts"][1].pop("id"), "parts[1].id"),
    ("non-string part id", lambda d: d["parts"][1].update(id=2), "parts[1].id"),
    ("duplicate part ids", lambda d: d["parts"][1].update(id="p001"), "duplicate part id"),
    ("missing exterior", lambda d: d["parts"][0].pop("exterior"), "parts[0].exterior"),
    ("short exterior", lambda d: d["parts"][0].update(exterior=[[0, 0], [1, 1]]), "parts[0].exterior"),
    ("nan coordinate", lambda d: d["parts"][0]["exterior"][2].__setitem__(1, float("nan")), "parts[0].exterior[2][1]"),
    ("triple coordinate", lambda d: d["parts"][0]["exterior"].__setitem__(0, [0, 0, 0]), "parts[0].exterior[0]"),
    ("missing holes", lambda d: d["parts"][0].pop("holes"), "parts[0].holes"),
    ("holes not a list", lambda d: d["parts"][0].update(holes="none"), "parts[0].holes"),
    ("bad hole ring", lambda d: d["parts"][0].update(holes=[[[0, 0], [1, 0]]]), "parts[0].holes[0]"),
]


@pytest.mark.parametrize(
    "mutate, fragment",
    [(m, f) for _, m, f in INSTANCE_CASES],
    ids=[name for name, _, _ in INSTANCE_CASES],
)
def test_load_instance_rejects_malformed_fields(tmp_path, mutate, fragment):
    data = valid_instance()
    mutate(data)
    path = dump(tmp_path / "bad.json", data)
    with pytest.raises(geom.InstanceError) as excinfo:
        geom.load_instance(path)
    assert fragment in str(excinfo.value)


def test_load_instance_rejects_unreadable_and_non_json(tmp_path):
    with pytest.raises(geom.InstanceError):
        geom.load_instance(tmp_path / "absent.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(geom.InstanceError):
        geom.load_instance(broken)
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(geom.InstanceError):
        geom.load_instance(arr)


# --------------------------------------------------------------------------
# load_solution
# --------------------------------------------------------------------------


def test_load_solution_round_trip(tmp_path):
    loaded = geom.load_solution(dump(tmp_path / "s.json", valid_solution()))
    assert loaded["instance_id"] == "c001-t1-dev-01"
    assert loaded["placements"][1]["rotation_deg"] == 90.0
    assert loaded["placements"][0]["translation"] == [0.0, 0.0]


def test_load_solution_solver_block_is_optional(tmp_path):
    data = valid_solution()
    data.pop("solver")
    assert geom.load_solution(dump(tmp_path / "s.json", data))["placements"]


def test_load_solution_allows_empty_placements(tmp_path):
    """A bijection check belongs to validate.py, not to the schema layer."""
    data = valid_solution()
    data["placements"] = []
    assert geom.load_solution(dump(tmp_path / "s.json", data))["placements"] == []


def test_load_solution_does_not_cross_check_an_instance(tmp_path):
    data = valid_solution()
    data["placements"][0]["part_id"] = "not-in-any-instance"
    assert geom.load_solution(dump(tmp_path / "s.json", data))


SOLUTION_CASES = [
    ("missing instance_id", lambda d: d.pop("instance_id"), "instance_id"),
    ("non-string instance_id", lambda d: d.update(instance_id=7), "instance_id"),
    ("missing placements", lambda d: d.pop("placements"), "placements"),
    ("placements not a list", lambda d: d.update(placements={}), "placements"),
    ("placement not an object", lambda d: d["placements"].__setitem__(0, "p001"), "placements[0]"),
    ("missing part_id", lambda d: d["placements"][0].pop("part_id"), "placements[0].part_id"),
    ("non-string part_id", lambda d: d["placements"][1].update(part_id=3), "placements[1].part_id"),
    ("missing translation", lambda d: d["placements"][0].pop("translation"), "placements[0].translation"),
    ("nan translation", lambda d: d["placements"][0].update(translation=[float("nan"), 0.0]), "placements[0].translation[0]"),
    ("inf translation", lambda d: d["placements"][1].update(translation=[0.0, float("inf")]), "placements[1].translation[1]"),
    ("short translation", lambda d: d["placements"][0].update(translation=[1.0]), "placements[0].translation"),
    ("long translation", lambda d: d["placements"][0].update(translation=[1.0, 2.0, 3.0]), "placements[0].translation"),
    ("string translation", lambda d: d["placements"][0].update(translation="0,0"), "placements[0].translation"),
    ("bool translation", lambda d: d["placements"][0].update(translation=[True, 0.0]), "placements[0].translation[0]"),
    ("missing rotation_deg", lambda d: d["placements"][1].pop("rotation_deg"), "placements[1].rotation_deg"),
    ("nan rotation_deg", lambda d: d["placements"][1].update(rotation_deg=float("nan")), "placements[1].rotation_deg"),
    ("string rotation_deg", lambda d: d["placements"][1].update(rotation_deg="90"), "placements[1].rotation_deg"),
    ("bad solver block", lambda d: d.update(solver="baseline"), "solver"),
]


@pytest.mark.parametrize(
    "mutate, fragment",
    [(m, f) for _, m, f in SOLUTION_CASES],
    ids=[name for name, _, _ in SOLUTION_CASES],
)
def test_load_solution_rejects_malformed_fields(tmp_path, mutate, fragment):
    data = valid_solution()
    mutate(data)
    path = dump(tmp_path / "bad.json", data)
    with pytest.raises(geom.SolutionError) as excinfo:
        geom.load_solution(path)
    assert fragment in str(excinfo.value)


def test_load_solution_rejects_unreadable(tmp_path):
    with pytest.raises(geom.SolutionError):
        geom.load_solution(tmp_path / "absent.json")


# --------------------------------------------------------------------------
# write_json
# --------------------------------------------------------------------------


def test_write_json_is_canonical(tmp_path):
    path = tmp_path / "out.json"
    geom.write_json({"b": 1, "a": [1, 2]}, path)
    assert path.read_text(encoding="utf-8") == '{\n  "a": [\n    1,\n    2\n  ],\n  "b": 1\n}\n'


def test_write_json_is_stable_and_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "deeper" / "out.json"
    obj = valid_instance()
    geom.write_json(obj, path)
    first = path.read_bytes()
    geom.write_json(json.loads(path.read_text(encoding="utf-8")), path)
    assert path.read_bytes() == first
    assert first.endswith(b"\n")


def test_write_json_round_trips_through_load_instance(tmp_path):
    path = tmp_path / "instances" / "i.json"
    geom.write_json(valid_instance(), path)
    assert geom.load_instance(path)["parts"][1]["id"] == "p002"


# --------------------------------------------------------------------------
# conftest fixtures (other tool test modules depend on these)
# --------------------------------------------------------------------------


def test_run_tool_fixture_invokes_a_tool_script(run_tool):
    """geom.py has no __main__ block, so running it just proves the plumbing."""
    proc = run_tool("geom")
    assert proc.returncode == 0, proc.stderr
    assert run_tool("geom.py").returncode == 0


def test_tools_and_c001_dirs(tools_dir, c001_dir):
    assert (tools_dir / "geom.py").is_file()
    assert tools_dir.parent == c001_dir
    assert c001_dir.name == "c001"


def test_dev_instances_fixture_is_a_sorted_list(dev_instances):
    assert isinstance(dev_instances, list)
    assert dev_instances == sorted(dev_instances)
    assert all(p.suffix == ".json" for p in dev_instances)


def test_tiny_instance_survives_a_write_load_round_trip(tiny_instance, tmp_path):
    path = geom.write_json(tiny_instance(), tmp_path / "tiny.json")
    loaded = geom.load_instance(path)
    assert loaded["strip_width"] == 100.0
    assert [p["id"] for p in loaded["parts"]] == ["p001", "p002", "p003"]
    assert geom.total_area(loaded) == pytest.approx(40 * 40 + 0.5 * 30 * 30 + 20 * 20)
    for part in loaded["parts"]:
        assert geom.part_polygon(part).is_valid
        assert geom.signed_area(part["exterior"]) > 0  # exteriors are CCW
        assert geom.bbox(part["exterior"])[:2] == (0.0, 0.0)  # bbox-min at origin


def test_tiny_instance_accepts_overrides(tiny_instance):
    assert tiny_instance(tier=3, strip_width=250.0)["tier"] == 3
    assert tiny_instance()["tier"] == 1  # factory is not shared state
