"""Tests for ``challenges/c001/tools/generate.py`` and the committed dev set.

The byte-identical regeneration test is the drift detector: any change to the
generator that moves a coordinate makes it fail, which is exactly when the 15
committed instances have to be regenerated (and, since instances are the
challenge's fixed input, when that has to be a deliberate decision).

The structural tests import ``generate`` rather than reimplementing its
predicates, so the tool and its guarantees cannot drift apart.
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from pathlib import Path

import pytest

pytest.importorskip("shapely")

import geom  # noqa: E402  (conftest puts tools/ on sys.path)
import generate  # noqa: E402

from shapely.geometry import Polygon  # noqa: E402


DEV_DIR = Path(__file__).resolve().parent.parent / "instances" / "dev"
DEV_FILES = sorted(DEV_DIR.glob("*.json")) if DEV_DIR.is_dir() else []
DEV_IDS = [p.stem for p in DEV_FILES]

EXPECTED_DEV_IDS = [
    geom.dev_instance_id(tier, seed)
    for tier in (1, 2, 3)
    for seed in range(tier * 1000 + 1, tier * 1000 + 6)
]

EXPECTED_DEV_SEEDS = {tier * 1000 + n for tier in (1, 2, 3) for n in range(1, 6)}

STRIP_WIDTH = geom.DEFAULT_STRIP_WIDTH
DIAMETER_CAP = generate.DIAMETER_FRACTION * STRIP_WIDTH


def _loaded(path):
    return geom.load_instance(path)


def _raw(path):
    """The committed file exactly as it sits on disk, with no loader in between."""
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def instances():
    """Every committed dev instance, keyed by instance id."""
    return {p.stem: _loaded(p) for p in DEV_FILES}


# --------------------------------------------------------------------------
# The dev set itself
# --------------------------------------------------------------------------


def test_dev_set_is_complete(dev_instances):
    """15 files, exactly the ids README.md ("Dev set and hidden set") calls for.

    Asserted explicitly so the parametrised tests below cannot pass vacuously
    on an empty directory.
    """
    assert len(dev_instances) == 15
    assert DEV_IDS == EXPECTED_DEV_IDS


def test_hidden_set_is_not_committed(c001_dir):
    """README.md ("Dev set and hidden set"): the hidden instances are generated
    after the round, never committed with the challenge.  Only the placeholder
    may sit in ``hidden/``."""
    hidden = c001_dir / "instances" / "hidden"
    assert hidden.is_dir()
    assert sorted(p.name for p in hidden.iterdir()) == [".gitkeep"]


def test_spec_constants_are_pinned():
    """The numbers README.md ("Size mix and totals") states, asserted as literals.

    Every structural test below derives its thresholds from these constants, so
    without this test a loosened constant would silently take the whole file
    with it -- ``test_parts_are_placeable`` would keep passing at a 950-unit
    cap.  These literals are the specification; the constants are the implementation.
    """
    assert generate.DEFAULT_PARTS == 40
    assert (generate.TARGET_AREA_MIN, generate.TARGET_AREA_MAX) == (2.0e6, 3.0e6)
    # Size bands (README.md, "Size mix and totals"): sized so 40 parts sum to the
    # 2.0e6-3.0e6 total.
    assert generate.BAND_LARGE == (8.0e4, 17.0e4)
    assert generate.BAND_MEDIUM == (2.0e4, 8.0e4)
    assert generate.BAND_SMALL == (3.0e3, 2.0e4)
    # Placeability: point-set diameter capped at 0.85 x strip width = 850.
    assert generate.DIAMETER_FRACTION == 0.85
    assert DIAMETER_CAP == 850.0
    # Post-rounding validity gates.
    assert generate.MIN_EDGE_LENGTH == 2.0
    assert generate.MIN_VERTEX_EDGE_CLEARANCE == 2.0
    # Tier 3: holes on ~30% of the medium/large parts, 12 units of wall.
    assert generate.HOLE_HOST_FRACTION == 0.30
    assert generate.HOLE_WALL == 12.0
    # Tier 3 hole-fit property: >= 3 pairs over >= 2 holes, 10-degree sweep.
    assert generate.FIT_PAIRS_REQUIRED == 3
    assert generate.FIT_HOLES_REQUIRED == 2
    assert generate.SWEEP_STEP_DEG == 10


def test_band_plan_keeps_the_25_50_25_proportions():
    """The size mix is decided in ``_band_plan``, so it is asserted there.

    Checking it on emitted areas instead would need the global scale, which is
    deliberately not recorded in the instance file.
    """
    plan = generate._band_plan(generate.Stream("bands"), generate.DEFAULT_PARTS)
    assert Counter(plan) == {"large": 10, "medium": 20, "small": 10}
    assert len(plan) == generate.DEFAULT_PARTS
    # A permutation, not a sorted run: the bands are spread over the part ids.
    assert plan != sorted(plan)


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", DEV_FILES, ids=DEV_IDS)
def test_regeneration_is_byte_identical(path, run_tool, tmp_path):
    """Regenerating a committed instance reproduces it byte for byte."""
    instance = _loaded(path)
    out = tmp_path / path.name
    result = run_tool(
        "generate",
        "--tier",
        instance["tier"],
        "--seed",
        instance["seed"],
        "--parts",
        instance["generator"]["parts"],
        "--strip-width",
        instance["strip_width"],
        "--id",
        instance["instance_id"],
        "--out",
        out,
    )
    assert result.returncode == 0, result.stderr
    assert out.read_bytes() == path.read_bytes()


def test_summary_line_goes_to_stderr(run_tool, tmp_path):
    """The one-line summary is on stderr, so stdout stays free for piping."""
    out = tmp_path / "one.json"
    result = run_tool(
        "generate", "--tier", 3, "--seed", 3001, "--id", "c001-t3-dev-01", "--out", out
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert "c001-t3-dev-01" in result.stderr
    assert "fitting_pairs=" in result.stderr


def test_id_does_not_influence_geometry(run_tool, tmp_path):
    """``--id`` is a label: same (tier, seed, parts) means the same geometry."""
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    for out, name in ((first, "c001-t2-dev-03"), (second, "totally-different-id")):
        result = run_tool(
            "generate", "--tier", 2, "--seed", 2003, "--id", name, "--out", out
        )
        assert result.returncode == 0, result.stderr

    left, right = _loaded(first), _loaded(second)
    assert left["instance_id"] != right["instance_id"]
    assert left["parts"] == right["parts"]


def test_parts_count_is_honoured_and_changes_the_stream(run_tool, tmp_path):
    out = tmp_path / "small.json"
    result = run_tool(
        "generate", "--tier", 1, "--seed", 1001, "--parts", 12, "--id", "c001-t1-dev-01", "--out", out
    )
    assert result.returncode == 0, result.stderr
    instance = _loaded(out)
    assert len(instance["parts"]) == 12
    assert instance["generator"]["parts"] == 12


def test_generation_is_comfortably_fast():
    started = time.time()
    generate.generate_instance(3, 3001, "c001-t3-dev-01")
    assert time.time() - started < 20.0


def test_seed_key_mixes_in_the_attempt_counter():
    """Stage 5's regeneration must stay deterministic and distinguishable."""
    assert generate.seed_key(3, 3001, 40) == "c001:3:3001:40"
    assert generate.seed_key(3, 3001, 40, 1) == "c001:3:3001:40:1"
    assert generate.seed_key(3, 3001, 40, 0) != generate.seed_key(3, 3001, 40, 2)


# --------------------------------------------------------------------------
# Structural guarantees over the committed set
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", DEV_FILES, ids=DEV_IDS)
def test_dev_header_matches_its_filename_and_seed(path, instances):
    """The id encodes the tier and the seed, so the two must agree.

    ``test_regeneration_is_byte_identical`` reads ``--tier``/``--seed`` out of
    the very file it is checking, so on its own it would happily bless a file
    built from the wrong seed.  This is the assertion that ties the committed
    ids to the seeds README.md ("Dev set and hidden set") names.
    """
    instance = instances[path.stem]
    assert instance["instance_id"] == path.stem
    assert instance["seed"] in EXPECTED_DEV_SEEDS
    assert instance["tier"] == instance["seed"] // 1000
    assert geom.dev_instance_id(instance["tier"], instance["seed"]) == path.stem


def test_the_five_seeds_per_tier_are_all_present(instances):
    assert {inst["seed"] for inst in instances.values()} == EXPECTED_DEV_SEEDS


@pytest.mark.parametrize("path", DEV_FILES, ids=DEV_IDS)
def test_committed_file_follows_the_on_disk_conventions(path):
    """Conventions that only exist in the bytes, checked without the loader.

    Every other structural test here goes through ``geom.load_instance``, which
    coerces types and defaults missing keys -- so a file that repeated its
    first vertex, carried unrounded coordinates or omitted ``holes`` would slip
    past all of them.  This test reads the raw JSON instead.
    """
    raw = _raw(path)
    assert raw["challenge"] == geom.CHALLENGE_ID
    assert raw["strip_width"] == STRIP_WIDTH
    assert raw["rotations_allowed"] == "free"
    assert raw["tier"] in (1, 2, 3)
    assert len(raw["parts"]) == generate.DEFAULT_PARTS
    assert raw["generator"]["parts"] == generate.DEFAULT_PARTS

    for part in raw["parts"]:
        assert set(part) == {"id", "exterior", "holes"}, part["id"]
        assert isinstance(part["holes"], list), part["id"]
        for ring in [part["exterior"]] + part["holes"]:
            # Implicitly closed: the first vertex is never repeated at the end.
            assert ring[0] != ring[-1], part["id"]
            assert len(ring) >= 3, part["id"]
            for x, y in ring:
                # Coordinates are rounded to 3 decimals, and no -0.0 survives.
                assert round(x, 3) == x and round(y, 3) == y, part["id"]
                assert math.copysign(1.0, x) > 0 or x != 0.0, part["id"]
                assert math.copysign(1.0, y) > 0 or y != 0.0, part["id"]
            # Canonical ring start: lexicographically smallest vertex first.
            assert ring[0] == min(ring), part["id"]


@pytest.mark.parametrize("path", DEV_FILES, ids=DEV_IDS)
def test_part_ids_are_unique_and_sequential(path, instances):
    instance = instances[path.stem]
    ids = [part["id"] for part in instance["parts"]]
    assert ids == ["p{:03d}".format(i + 1) for i in range(len(ids))]
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("path", DEV_FILES, ids=DEV_IDS)
def test_every_polygon_is_valid_and_simple(path, instances):
    for part in instances[path.stem]["parts"]:
        poly = geom.part_polygon(part)
        assert poly.is_valid, part["id"]
        assert poly.is_simple, part["id"]
        assert poly.area > 0, part["id"]


@pytest.mark.parametrize("path", DEV_FILES, ids=DEV_IDS)
def test_ring_orientation(path, instances):
    """Exteriors counter-clockwise, holes clockwise -- by signed area."""
    for part in instances[path.stem]["parts"]:
        assert geom.signed_area(part["exterior"]) > 0, part["id"]
        for index, hole in enumerate(part["holes"]):
            assert geom.signed_area(hole) < 0, (part["id"], index)


@pytest.mark.parametrize("path", DEV_FILES, ids=DEV_IDS)
def test_local_bbox_minimum_sits_at_the_origin(path, instances):
    for part in instances[path.stem]["parts"]:
        minx, miny, _, _ = geom.bbox(part["exterior"])
        assert minx == 0.0, part["id"]
        assert miny == 0.0, part["id"]


@pytest.mark.parametrize("path", DEV_FILES, ids=DEV_IDS)
def test_parts_are_placeable(path, instances):
    """Diameter cap, plus both axis-aligned extents at 0 and 90 degrees."""
    for part in instances[path.stem]["parts"]:
        assert geom.point_set_diameter(part["exterior"]) <= DIAMETER_CAP, part["id"]
        for angle in (0.0, 90.0):
            ring = geom.transform_ring(part["exterior"], (0.0, 0.0), angle)
            minx, miny, maxx, maxy = geom.bbox(ring)
            assert maxx - minx < STRIP_WIDTH, (part["id"], angle)
            assert maxy - miny < STRIP_WIDTH, (part["id"], angle)


@pytest.mark.parametrize("path", DEV_FILES, ids=DEV_IDS)
def test_parts_pass_the_generator_gates(path, instances):
    """Minimum edge length and vertex-to-non-adjacent-edge clearance."""
    for part in instances[path.stem]["parts"]:
        reason = generate.gate_failure(part["exterior"], part["holes"], DIAMETER_CAP)
        assert reason is None, (part["id"], reason)


@pytest.mark.parametrize("path", DEV_FILES, ids=DEV_IDS)
def test_total_area_is_in_the_target_band(path, instances):
    total = geom.total_area(instances[path.stem])
    # One square unit of slack absorbs the 3-decimal coordinate rounding.
    assert generate.TARGET_AREA_MIN - 1.0 <= total <= generate.TARGET_AREA_MAX + 1.0


@pytest.mark.parametrize("path", DEV_FILES, ids=DEV_IDS)
def test_size_mix(path, instances):
    """The three size bands are still separated after the global scale.

    The scale multiplies every area by the same factor and is not recorded in
    the file, so the assertion has to be a ratio.  The band edges are 8e4 and
    2e4, a factor of 4; 3.9 leaves room for the rounding of coordinates.
    """
    parts = instances[path.stem]["parts"]
    count = len(parts)
    n_large = int(round(0.25 * count))
    n_small = int(round(0.25 * count))
    areas = sorted(geom.part_area(part) for part in parts)
    assert min(areas[-n_large:]) >= 3.9 * max(areas[:n_small])
    assert n_large + n_small < count  # the medium band is not empty


@pytest.mark.parametrize("path", DEV_FILES, ids=DEV_IDS)
def test_holes_only_appear_in_tier_three(path, instances):
    instance = instances[path.stem]
    holes = sum(len(part["holes"]) for part in instance["parts"])
    if instance["tier"] < 3:
        assert holes == 0
        assert all(part["holes"] == [] for part in instance["parts"])
    else:
        assert holes > 0


@pytest.mark.parametrize("path", DEV_FILES, ids=DEV_IDS)
def test_tier_one_is_convex_and_higher_tiers_are_not(path, instances):
    instance = instances[path.stem]
    for part in instance["parts"]:
        poly = Polygon(part["exterior"])
        convex = poly.area > generate.MAX_CONVEXITY * poly.convex_hull.area
        if instance["tier"] == 1:
            assert convex, part["id"]
            assert 3 <= len(part["exterior"]) <= 10, part["id"]
        else:
            assert not convex, part["id"]


@pytest.mark.parametrize("path", [p for p in DEV_FILES if "-t3-" in p.stem], ids=[p.stem for p in DEV_FILES if "-t3-" in p.stem])
def test_tier_three_holes_are_well_separated(path, instances):
    """Holes are convex, 1-2 per host, and keep the promised wall."""
    instance = instances[path.stem]
    hosts = 0
    for part in instance["parts"]:
        if not part["holes"]:
            continue
        hosts += 1
        assert len(part["holes"]) <= 2, part["id"]
        room = Polygon(part["exterior"]).buffer(-generate.HOLE_WALL)
        for index, hole in enumerate(part["holes"]):
            poly = Polygon(hole)
            assert room.contains(poly), (part["id"], index)
            assert poly.area >= (1 - 1e-9) * poly.convex_hull.area, (part["id"], index)
        for i in range(len(part["holes"])):
            for j in range(i + 1, len(part["holes"])):
                gap = Polygon(part["holes"][i]).distance(Polygon(part["holes"][j]))
                assert gap >= generate.HOLE_WALL - 1e-6, (part["id"], i, j)

    # "~30% of medium/large parts get holes"; small parts never do.
    n_small = int(round(0.25 * len(instance["parts"])))
    pool = len(instance["parts"]) - n_small
    assert 0.20 <= hosts / pool <= 0.40, hosts


@pytest.mark.parametrize("path", [p for p in DEV_FILES if "-t3-" in p.stem], ids=[p.stem for p in DEV_FILES if "-t3-" in p.stem])
def test_tier_three_hole_fit_property(path, instances):
    """At least 3 (hole, part) pairs over at least 2 distinct holes.

    Uses the generator's own rotation sweep, so the property the tool
    guarantees and the property the test checks are the same code.
    """
    pairs = generate.fitting_pairs(instances[path.stem])
    assert len(pairs) >= generate.FIT_PAIRS_REQUIRED
    distinct = {(host_id, index) for _, host_id, index in pairs}
    assert len(distinct) >= generate.FIT_HOLES_REQUIRED
    # Every reported pair really is a small part in someone else's hole.
    for part_id, host_id, _ in pairs:
        assert part_id != host_id


# --------------------------------------------------------------------------
# Unit checks on the pieces the guarantees rest on
# --------------------------------------------------------------------------


def test_rounding_helper_kills_negative_zero():
    assert generate._r3(-0.0001) == 0.0
    assert not math.copysign(1.0, generate._r3(-0.0001)) < 0
    assert generate._r3(1.23456) == 1.235


def test_stream_only_uses_random():
    """The draw helpers must be pure functions of ``random()``.

    Two streams on the same key agree; ``randint`` stays inside its bounds and
    ``permuted`` is a permutation.
    """
    left = generate.Stream("c001:1:1:1")
    right = generate.Stream("c001:1:1:1")
    assert [left.random() for _ in range(5)] == [right.random() for _ in range(5)]

    stream = generate.Stream("bounds")
    draws = [stream.randint(3, 7) for _ in range(500)]
    assert set(draws) <= {3, 4, 5, 6, 7}
    assert set(draws) == {3, 4, 5, 6, 7}
    assert sorted(generate.Stream("perm").permuted(range(20))) == list(range(20))
    subset = generate.Stream("sub").subset(list(range(20)), 5)
    assert len(subset) == len(set(subset)) == 5
    assert subset == sorted(subset)
    assert generate.Stream("pick").choice(["a"]) == "a"
    assert generate.Stream("pick").choice(list("abcdef")) in list("abcdef")
    assert -3.0 <= generate.Stream("u").uniform(-3.0, 3.0) <= 3.0


def test_shape_kind_mix_is_50_30_20():
    stream = generate.Stream("mix")
    draws = 20000
    tally = Counter(generate.draw_kind(stream, 2) for _ in range(draws))
    assert abs(tally["notched"] / draws - 0.50) < 0.02
    assert abs(tally["orthogonal"] / draws - 0.30) < 0.02
    assert abs(tally["star"] / draws - 0.20) < 0.02
    assert generate.draw_kind(generate.Stream("t1"), 1) == "hull"


def test_tier_one_spends_no_draw_on_the_shape_kind():
    """Tier 1 must not consume a draw it does not need."""
    left, right = generate.Stream("same"), generate.Stream("same")
    assert generate.draw_kind(left, 1) == "hull"
    assert left.random() == right.random()


def test_retries_do_not_reweight_the_shape_kind_mix(monkeypatch):
    """The kind is drawn once per part, so the realised mix is the drawn mix.

    Re-picking inside the retry loop would quietly shift mass toward whichever
    kind clears the diameter cap most easily, which is a plan deviation no
    other test would notice.
    """
    tally = Counter()
    pending = {}
    real_draw_kind = generate.draw_kind
    real_build = generate._build_exterior

    def spy(stream, tier):
        pending["kind"] = real_draw_kind(stream, tier)
        return pending["kind"]

    def build(*args, **kwargs):
        ring = real_build(*args, **kwargs)
        tally[pending["kind"]] += 1
        return ring

    monkeypatch.setattr(generate, "draw_kind", spy)
    monkeypatch.setattr(generate, "_build_exterior", build)
    for seed in range(2001, 2021):
        generate.generate_instance(2, seed, "unused")

    total = sum(tally.values())
    assert total == 20 * generate.DEFAULT_PARTS
    assert 0.44 <= tally["notched"] / total <= 0.56
    assert 0.24 <= tally["orthogonal"] / total <= 0.36
    assert 0.14 <= tally["star"] / total <= 0.26


def test_fit_sweep_accepts_a_part_that_fits_and_rejects_one_that_does_not():
    square = {"id": "p001", "exterior": [[0, 0], [40, 0], [40, 40], [0, 40]], "holes": []}
    radius = generate._circumradius(square["exterior"])
    big = geom.ensure_cw(generate._regular_ring((0.0, 0.0), radius * 1.3, 8, 0.0))
    tight = geom.ensure_cw(generate._regular_ring((0.0, 0.0), radius * 0.9, 8, 0.0))
    assert generate.part_fits_in_hole(square, big)
    assert not generate.part_fits_in_hole(square, tight)
