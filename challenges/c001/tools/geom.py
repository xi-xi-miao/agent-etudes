"""Shared geometry, I/O and schema helpers for challenge c001 (irregular shape nesting).

Everything else under ``challenges/c001/tools/`` codes against this module's public
surface.  Import it after putting the tools directory on ``sys.path``::

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import geom

Geometry conventions (authoritative, see the challenge README):

* The strip stands up: it occupies ``0 <= x <= W`` and ``y >= 0``, unbounded
  in ``+y``.  The width runs along x; material is consumed upward along y.
* A polygon ring is a list of ``[x, y]`` vertices, implicitly closed (the first
  vertex is NOT repeated), simple.  Exterior rings are counter-clockwise, hole
  rings clockwise.
* Parts live in local coordinates with their axis-aligned bounding-box minimum
  at the local origin ``(0, 0)``.
* A placement rotates the part counter-clockwise by ``rotation_deg`` about the
  local origin and *then* translates it by ``[tx, ty]``.  Exactly this order.

Determinism note: emitted coordinates are always built with pure-Python vertex
arithmetic (:func:`transform_ring`, :func:`signed_area`, ...).  Shapely is used
only as an oracle and as a measure (validity, intersection area, bounds) --
never as the source of numbers that get written to a JSON file.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

from shapely.affinity import affine_transform
from shapely.geometry import Polygon

__all__ = [
    "TOL_AREA",
    "CHALLENGE_ID",
    "DEFAULT_STRIP_WIDTH",
    "PALETTE",
    "InstanceError",
    "SolutionError",
    "load_instance",
    "load_solution",
    "write_json",
    "signed_area",
    "ensure_ccw",
    "ensure_cw",
    "canonical_ring",
    "part_polygon",
    "part_area",
    "transform_polygon",
    "transform_ring",
    "placed_polygons",
    "used_height",
    "utilization",
    "format_pct",
    "total_area",
    "point_set_diameter",
    "rotation_allowed",
    "dev_instance_id",
    "hidden_instance_id",
    "bbox",
]

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

#: Area tolerance (square units) for containment and overlap checks.
TOL_AREA = 0.01

#: The challenge id this tooling belongs to.
CHALLENGE_ID = "c001"

#: Strip width used by the generator unless told otherwise.
DEFAULT_STRIP_WIDTH = 1000.0

#: Angular tolerance (degrees) when matching against a rotation list.
ROTATION_TOL_DEG = 1e-6

#: Twelve categorical fill colours, used by render.py and gallery.py.
PALETTE = [
    "#4e79a7",
    "#f28e2b",
    "#e15759",
    "#76b7b2",
    "#59a14f",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
    "#9c755f",
    "#bab0ac",
    "#86bcb6",
    "#d37295",
]


class InstanceError(ValueError):
    """Raised when an instance file is missing, unreadable or malformed."""


class SolutionError(ValueError):
    """Raised when a solution file is missing, unreadable or malformed."""


# --------------------------------------------------------------------------
# Small schema helpers
# --------------------------------------------------------------------------


def _num(value, field, exc):
    """Return ``value`` as a float, or raise ``exc`` naming ``field``.

    Rejects bools explicitly -- ``isinstance(True, int)`` is ``True`` in Python
    and every numeric check below would otherwise silently accept booleans.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise exc("{}: expected a number, got {}".format(field, type(value).__name__))
    out = float(value)
    if not math.isfinite(out):
        raise exc("{}: expected a finite number, got {!r}".format(field, value))
    return out


def _int(value, field, exc):
    """Return ``value`` as an int, or raise ``exc`` naming ``field``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise exc("{}: expected an integer, got {}".format(field, type(value).__name__))
    return value


def _str(value, field, exc, allow_empty=False):
    if not isinstance(value, str):
        raise exc("{}: expected a string, got {}".format(field, type(value).__name__))
    if not allow_empty and not value:
        raise exc("{}: expected a non-empty string".format(field))
    return value


def _require(obj, field, exc, container="object", path=None):
    """Fetch a required field.  ``path`` is the qualified name used in messages."""
    if not isinstance(obj, dict):
        raise exc("{}: expected a JSON object, got {}".format(container, type(obj).__name__))
    if field not in obj:
        raise exc("{}: required field is missing".format(path or field))
    return obj[field]


def _ring(value, field, exc, min_vertices=3):
    """Validate one ring and return it as a list of ``[x, y]`` float pairs."""
    if not isinstance(value, list):
        raise exc("{}: expected a list of [x, y] vertices, got {}".format(field, type(value).__name__))
    if len(value) < min_vertices:
        raise exc("{}: expected at least {} vertices, got {}".format(field, min_vertices, len(value)))
    out = []
    for i, point in enumerate(value):
        where = "{}[{}]".format(field, i)
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise exc("{}: expected an [x, y] pair".format(where))
        out.append([_num(point[0], where + "[0]", exc), _num(point[1], where + "[1]", exc)])
    return out


def _read_json(path, exc):
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        raise exc("{}: cannot read file ({})".format(path, err)) from err
    try:
        return json.loads(text)
    except json.JSONDecodeError as err:
        raise exc("{}: not valid JSON ({})".format(path, err)) from err


# --------------------------------------------------------------------------
# Instance / solution I/O
# --------------------------------------------------------------------------


def load_instance(path):
    """Load and schema-validate an instance JSON file.

    Returns the parsed dict (coordinates normalised to floats).  Raises
    :class:`InstanceError` with a message naming the offending field.
    """
    exc = InstanceError
    data = _read_json(path, exc)
    if not isinstance(data, dict):
        raise exc("instance: expected a JSON object, got {}".format(type(data).__name__))

    _str(_require(data, "instance_id", exc, "instance"), "instance_id", exc)
    _str(_require(data, "challenge", exc, "instance"), "challenge", exc)

    tier = _int(_require(data, "tier", exc, "instance"), "tier", exc)
    if tier not in (1, 2, 3):
        raise exc("tier: expected 1, 2 or 3, got {!r}".format(tier))

    _int(_require(data, "seed", exc, "instance"), "seed", exc)

    strip_width = _num(_require(data, "strip_width", exc, "instance"), "strip_width", exc)
    if strip_width <= 0:
        raise exc("strip_width: expected a positive number, got {!r}".format(strip_width))
    data["strip_width"] = strip_width

    rotations = _require(data, "rotations_allowed", exc, "instance")
    if isinstance(rotations, str):
        if rotations != "free":
            raise exc('rotations_allowed: expected "free" or a list of degrees, got {!r}'.format(rotations))
    elif isinstance(rotations, list):
        data["rotations_allowed"] = [
            _num(a, "rotations_allowed[{}]".format(i), exc) for i, a in enumerate(rotations)
        ]
    else:
        raise exc(
            'rotations_allowed: expected "free" or a list of degrees, got {}'.format(type(rotations).__name__)
        )

    parts = _require(data, "parts", exc, "instance")
    if not isinstance(parts, list):
        raise exc("parts: expected a list, got {}".format(type(parts).__name__))
    if not parts:
        raise exc("parts: expected a non-empty list")

    seen = set()
    for i, part in enumerate(parts):
        where = "parts[{}]".format(i)
        if not isinstance(part, dict):
            raise exc("{}: expected a JSON object, got {}".format(where, type(part).__name__))
        part_id = _str(_require(part, "id", exc, where, where + ".id"), where + ".id", exc)
        if part_id in seen:
            raise exc("{}.id: duplicate part id {!r}".format(where, part_id))
        seen.add(part_id)

        part["exterior"] = _ring(
            _require(part, "exterior", exc, where, where + ".exterior"),
            where + ".exterior",
            exc,
        )

        holes = _require(part, "holes", exc, where, where + ".holes")
        if not isinstance(holes, list):
            raise exc("{}.holes: expected a list of rings, got {}".format(where, type(holes).__name__))
        part["holes"] = [
            _ring(hole, "{}.holes[{}]".format(where, h), exc) for h, hole in enumerate(holes)
        ]

    return data


def load_solution(path):
    """Load and schema-validate a solution JSON file.

    This deliberately does NOT cross-check the solution against an instance --
    ``validate.py`` owns that.  Raises :class:`SolutionError` naming the
    offending field.
    """
    exc = SolutionError
    data = _read_json(path, exc)
    if not isinstance(data, dict):
        raise exc("solution: expected a JSON object, got {}".format(type(data).__name__))

    _str(_require(data, "instance_id", exc, "solution"), "instance_id", exc)

    solver = data.get("solver")
    if solver is not None and not isinstance(solver, dict):
        raise exc("solver: expected a JSON object, got {}".format(type(solver).__name__))

    placements = _require(data, "placements", exc, "solution")
    if not isinstance(placements, list):
        raise exc("placements: expected a list, got {}".format(type(placements).__name__))

    for i, placement in enumerate(placements):
        where = "placements[{}]".format(i)
        if not isinstance(placement, dict):
            raise exc("{}: expected a JSON object, got {}".format(where, type(placement).__name__))
        _str(_require(placement, "part_id", exc, where, where + ".part_id"), where + ".part_id", exc)

        translation = _require(placement, "translation", exc, where, where + ".translation")
        if not isinstance(translation, (list, tuple)) or len(translation) != 2:
            raise exc("{}.translation: expected a [tx, ty] pair".format(where))
        placement["translation"] = [
            _num(translation[0], where + ".translation[0]", exc),
            _num(translation[1], where + ".translation[1]", exc),
        ]

        placement["rotation_deg"] = _num(
            _require(placement, "rotation_deg", exc, where, where + ".rotation_deg"),
            where + ".rotation_deg",
            exc,
        )

    return data


def write_json(obj, path):
    """Write ``obj`` as canonical JSON: sorted keys, indent 2, trailing newline."""
    path = Path(path)
    parent = path.parent
    if str(parent) not in ("", os.curdir):
        parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Pure-Python ring arithmetic
# --------------------------------------------------------------------------


def signed_area(ring):
    """Shoelace signed area of a closed ring (positive when counter-clockwise)."""
    total = 0.0
    n = len(ring)
    if n < 3:
        return 0.0
    for i in range(n):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        total += x0 * y1 - x1 * y0
    return 0.5 * total


def _as_pairs(ring):
    return [[p[0], p[1]] for p in ring]


def ensure_ccw(ring):
    """Return a new ring wound counter-clockwise."""
    out = _as_pairs(ring)
    if signed_area(out) < 0:
        out.reverse()
    return out


def ensure_cw(ring):
    """Return a new ring wound clockwise."""
    out = _as_pairs(ring)
    if signed_area(out) > 0:
        out.reverse()
    return out


def canonical_ring(ring):
    """Rotate a ring so it starts at its lexicographically smallest ``(x, y)``.

    Orientation is preserved; only the starting vertex moves.  On an exact
    coordinate tie the earliest index wins, which keeps the output stable and
    therefore keeps regenerated instance files byte-identical.
    """
    out = _as_pairs(ring)
    if not out:
        return out
    start = min(range(len(out)), key=lambda i: (out[i][0], out[i][1]))
    return out[start:] + out[:start]


def bbox(points):
    """Axis-aligned bounding box of a point sequence: ``(minx, miny, maxx, maxy)``."""
    pts = list(points)
    if not pts:
        raise ValueError("bbox: expected a non-empty point sequence")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def point_set_diameter(points):
    """Maximum pairwise distance in a point set (pure Python, O(n^2))."""
    pts = list(points)
    n = len(pts)
    if n < 2:
        return 0.0
    best = 0.0
    for i in range(n - 1):
        xi, yi = pts[i][0], pts[i][1]
        for j in range(i + 1, n):
            dx = pts[j][0] - xi
            dy = pts[j][1] - yi
            d2 = dx * dx + dy * dy
            if d2 > best:
                best = d2
    return math.sqrt(best)


# --------------------------------------------------------------------------
# Parts and placements
# --------------------------------------------------------------------------


def part_polygon(part):
    """Build the Shapely polygon of a part in local coordinates (holes punched out)."""
    return Polygon(part["exterior"], part.get("holes") or [])


def part_area(part):
    """Area of a part with its holes subtracted (pure Python shoelace)."""
    area = abs(signed_area(part["exterior"]))
    for hole in part.get("holes") or []:
        area -= abs(signed_area(hole))
    return area


def total_area(instance):
    """Sum of :func:`part_area` over every part of an instance."""
    return sum(part_area(part) for part in instance["parts"])


def _cos_sin(rotation_deg):
    theta = math.radians(rotation_deg)
    return math.cos(theta), math.sin(theta)


def transform_polygon(poly, translation, rotation_deg):
    """Rotate ``poly`` CCW about the origin by ``rotation_deg``, then translate.

    Uses a single ``affine_transform`` -- never ``shapely.affinity.rotate``,
    whose default origin is the centroid rather than the local origin.
    """
    c, s = _cos_sin(rotation_deg)
    tx, ty = float(translation[0]), float(translation[1])
    return affine_transform(poly, [c, -s, s, c, tx, ty])


def transform_ring(ring, translation, rotation_deg):
    """Same transform as :func:`transform_polygon`, in pure Python.

    Emitters (generate/baseline/render) must use this rather than reading
    coordinates back out of a Shapely geometry.
    """
    c, s = _cos_sin(rotation_deg)
    tx, ty = float(translation[0]), float(translation[1])
    return [[c * p[0] - s * p[1] + tx, s * p[0] + c * p[1] + ty] for p in ring]


def placed_polygons(instance, solution):
    """Map every part id to its transformed Shapely polygon.

    Assumes the placement set is a bijection onto the instance's part ids and
    raises :class:`SolutionError` otherwise.  ``validate.py`` performs its own
    bijection check first so it can emit distinct error codes.
    """
    parts = {part["id"]: part for part in instance["parts"]}
    out = {}
    for placement in solution["placements"]:
        part_id = placement["part_id"]
        if part_id not in parts:
            raise SolutionError("placements: unknown part id {!r}".format(part_id))
        if part_id in out:
            raise SolutionError("placements: duplicate placement for part id {!r}".format(part_id))
        out[part_id] = transform_polygon(
            part_polygon(parts[part_id]), placement["translation"], placement["rotation_deg"]
        )
    missing = sorted(set(parts) - set(out))
    if missing:
        raise SolutionError("placements: no placement for part id(s) {}".format(", ".join(missing)))
    return out


# --------------------------------------------------------------------------
# Measures
# --------------------------------------------------------------------------


def used_height(polys_iterable):
    """Used height of a layout: the largest y reached by any placed polygon."""
    maxima = [poly.bounds[3] for poly in polys_iterable]
    if not maxima:
        return 0.0
    return max(maxima)


def utilization(total_part_area, strip_width, used_h):
    """Total part area divided by the consumed strip rectangle ``W x H``, clamped to [0, 1]."""
    if used_h <= 0 or strip_width <= 0:
        return 0.0
    value = total_part_area / (strip_width * used_h)
    return min(1.0, max(0.0, value))


def format_pct(u):
    """Format a utilization fraction as a bare one-decimal percentage string.

    No ``%`` sign is appended -- callers add it where they want it.
    """
    return "{:.1f}".format(100.0 * u)


# --------------------------------------------------------------------------
# Rotation constraint and id conventions
# --------------------------------------------------------------------------


def rotation_allowed(rotation_deg, allowed):
    """Is ``rotation_deg`` permitted by an instance's ``rotations_allowed``?"""
    if allowed == "free":
        return True
    if not isinstance(allowed, list):
        return False
    return any(
        abs(((rotation_deg - a + 180.0) % 360.0) - 180.0) <= ROTATION_TOL_DEG for a in allowed
    )


def dev_instance_id(tier, seed):
    """Canonical id of a committed dev instance, e.g. ``c001-t2-dev-03``."""
    return "{}-t{}-dev-{:02d}".format(CHALLENGE_ID, tier, seed % 1000)


def hidden_instance_id(tier, n):
    """Canonical id of a hidden instance, e.g. ``c001-t3-hidden-01``."""
    return "{}-t{}-hidden-{:02d}".format(CHALLENGE_ID, tier, n)
