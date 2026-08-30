#!/usr/bin/env python3
"""Validator for challenge c001 (irregular shape nesting).

Usage::

    validate.py <instance.json> <solution.json> [--svg out.svg] [--json] [--labels]

Checks run in this order, each producing errors with a stable code:

``SCHEMA``
    Either file is unreadable, is not JSON, or does not match the format.  This
    is fatal: the run stops immediately and exits 2.
``INSTANCE_MISMATCH``
    ``solution.instance_id`` differs from ``instance.instance_id``.
``MISSING_PLACEMENT`` / ``DUPLICATE_PLACEMENT`` / ``UNKNOWN_PART``
    The placement set is not a bijection onto the instance's part ids.
``ROTATION_NOT_ALLOWED``
    ``rotations_allowed`` is a list and a placement's angle is not in it.
``INVALID_GEOMETRY``
    A transformed part is not a valid Shapely polygon.
``OUTSIDE_STRIP``
    More than ``TOL_AREA`` of a part lies outside ``[0, inf) x [0, W]``.
``OVERLAP``
    Two parts intersect in more than ``TOL_AREA`` of area.

Every violation is collected -- only ``SCHEMA`` stops the run early.

Exit codes: ``0`` valid, ``1`` invalid, ``2`` unreadable/malformed input.

Note on the ``--json`` contract: the last stdout line is always a JSON object,
including on exit 2.  Its ``summary`` is the human headline, except that on
failure it also carries the violation count and the distinct codes (the printed
headline stays the bare word ``INVALID``) so a consumer that echoes ``summary``
verbatim still says something useful.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geom  # noqa: E402  (must follow the sys.path insertion above)

from shapely.geometry import box  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402
from shapely.validation import explain_validity  # noqa: E402


# --------------------------------------------------------------------------
# Error records
# --------------------------------------------------------------------------


def _err(code, message, **details):
    """Build one violation record: ``code`` and ``message`` plus extra details."""
    record = {"code": code, "message": message}
    record.update(details)
    return record


def _fmt_area(value):
    return "{:.6f}".format(value)


def _schema_error(kind, exc):
    """One ``SCHEMA`` record for a load failure of ``kind`` (instance/solution).

    ``geom``'s own top-level messages already open with ``instance:``/
    ``solution:``; blindly prepending would print ``solution: solution: ...``.
    """
    message = str(exc)
    prefix = kind + ": "
    if not message.startswith(prefix):
        message = prefix + message
    return _err("SCHEMA", message, file=kind)


# --------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------


def check_instance_id(instance, solution):
    """INSTANCE_MISMATCH: the solution names a different instance."""
    want = instance["instance_id"]
    got = solution["instance_id"]
    if got == want:
        return []
    return [
        _err(
            "INSTANCE_MISMATCH",
            "solution instance_id {!r} does not match instance {!r}".format(got, want),
            expected=want,
            actual=got,
        )
    ]


def check_bijection(instance, solution):
    """Bijection between placements and part ids.

    Returns ``(errors, effective)`` where ``effective`` maps a known part id to
    the FIRST placement carrying it, in instance part order.  Later duplicates
    are dropped so the geometry stages never compare a part with itself.
    """
    parts = {part["id"]: part for part in instance["parts"]}
    counts = {}
    first = {}
    unknown = []
    for placement in solution["placements"]:
        part_id = placement["part_id"]
        if part_id not in parts:
            if part_id not in unknown:
                unknown.append(part_id)
            continue
        counts[part_id] = counts.get(part_id, 0) + 1
        first.setdefault(part_id, placement)

    errors = []
    for part in instance["parts"]:
        if part["id"] not in counts:
            errors.append(
                _err(
                    "MISSING_PLACEMENT",
                    "no placement for part {!r}".format(part["id"]),
                    part_id=part["id"],
                )
            )
    for part in instance["parts"]:
        n = counts.get(part["id"], 0)
        if n > 1:
            errors.append(
                _err(
                    "DUPLICATE_PLACEMENT",
                    "part {!r} has {} placements, expected exactly one".format(part["id"], n),
                    part_id=part["id"],
                    count=n,
                )
            )
    for part_id in unknown:
        errors.append(
            _err(
                "UNKNOWN_PART",
                "placement references unknown part {!r}".format(part_id),
                part_id=part_id,
            )
        )

    effective = [(part["id"], first[part["id"]]) for part in instance["parts"] if part["id"] in first]
    return errors, effective


def check_rotations(instance, effective):
    """ROTATION_NOT_ALLOWED: only meaningful when ``rotations_allowed`` is a list."""
    allowed = instance["rotations_allowed"]
    if not isinstance(allowed, list):
        return []
    errors = []
    for part_id, placement in effective:
        rotation = placement["rotation_deg"]
        if not geom.rotation_allowed(rotation, allowed):
            errors.append(
                _err(
                    "ROTATION_NOT_ALLOWED",
                    "part {!r}: rotation {} deg is not in rotations_allowed {}".format(
                        part_id, rotation, allowed
                    ),
                    part_id=part_id,
                    rotation_deg=rotation,
                )
            )
    return errors


def build_polygons(instance, effective):
    """Transform every effectively placed part; report INVALID_GEOMETRY.

    Returns ``(errors, placed)`` with ``placed`` a list of ``(part_id, polygon)``
    holding only the polygons Shapely considers valid -- an invalid polygon is
    excluded before any further GEOS call, which would otherwise be free to
    raise instead of reporting.
    """
    parts = {part["id"]: part for part in instance["parts"]}
    errors = []
    placed = []
    for part_id, placement in effective:
        try:
            poly = geom.transform_polygon(
                geom.part_polygon(parts[part_id]),
                placement["translation"],
                placement["rotation_deg"],
            )
            reason = None if poly.is_valid else explain_validity(poly)
        except Exception as exc:  # pragma: no cover - defensive
            poly = None
            reason = "{}: {}".format(type(exc).__name__, exc)
        if reason is not None:
            errors.append(
                _err(
                    "INVALID_GEOMETRY",
                    "part {!r}: transformed polygon is not valid ({})".format(part_id, reason),
                    part_id=part_id,
                    reason=reason,
                )
            )
            continue
        placed.append((part_id, poly))
    return errors, placed


def check_containment(placed, strip_width, used_len):
    """OUTSIDE_STRIP: area outside ``[0, used_len + 1] x [0, W]``.

    The box is clamped to a positive x extent: a layout whose parts all sit at
    negative x would otherwise produce a reversed rectangle covering exactly the
    region the check is meant to reject.
    """
    if not placed:
        return []
    strip = box(0.0, 0.0, max(used_len, 0.0) + 1.0, strip_width)
    errors = []
    for part_id, poly in placed:
        minx, miny, _maxx, maxy = poly.bounds
        if minx >= 0.0 and miny >= 0.0 and maxy <= strip_width:
            continue
        outside = poly.difference(strip).area
        if outside > geom.TOL_AREA:
            errors.append(
                _err(
                    "OUTSIDE_STRIP",
                    "part {!r}: {} area units lie outside the strip "
                    "[0, inf) x [0, {}]".format(part_id, _fmt_area(outside), strip_width),
                    part_id=part_id,
                    area=outside,
                )
            )
    return errors


def check_overlaps(placed):
    """OVERLAP: pairwise intersection area above ``TOL_AREA``, via an STRtree."""
    if len(placed) < 2:
        return []
    ids = [part_id for part_id, _poly in placed]
    polys = [poly for _part_id, poly in placed]
    tree = STRtree(polys)
    pairs = tree.query(polys, predicate="intersects")
    found = []
    for a, b in zip(pairs[0], pairs[1]):
        i, j = int(a), int(b)
        if i >= j:
            continue
        area = polys[i].intersection(polys[j]).area
        if area > geom.TOL_AREA:
            found.append((ids[i], ids[j], area))
    found.sort(key=lambda item: (item[0], item[1]))
    return [
        _err(
            "OVERLAP",
            "parts {!r} and {!r} overlap by {} area units".format(a, b, _fmt_area(area)),
            part_ids=[a, b],
            area=area,
        )
        for a, b, area in found
    ]


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def validate(instance, solution):
    """Run every check.  Returns ``(errors, used_len, utilization_fraction)``."""
    errors = []
    errors.extend(check_instance_id(instance, solution))

    bijection_errors, effective = check_bijection(instance, solution)
    errors.extend(bijection_errors)
    errors.extend(check_rotations(instance, effective))

    geometry_errors, placed = build_polygons(instance, effective)
    errors.extend(geometry_errors)

    used_len = geom.used_length(poly for _part_id, poly in placed)
    strip_width = instance["strip_width"]
    util = geom.utilization(geom.total_area(instance), strip_width, used_len)

    errors.extend(check_containment(placed, strip_width, used_len))
    errors.extend(check_overlaps(placed))
    return errors, used_len, util


def _headline(valid, used_len, util):
    if valid:
        return "VALID  used_length={:.3f}  utilization={}%".format(used_len, geom.format_pct(util))
    return "INVALID"


def _summary(valid, errors, used_len, util):
    """The one-liner a consumer may echo verbatim."""
    if valid:
        return _headline(True, used_len, util)
    codes = []
    for error in errors:
        if error["code"] not in codes:
            codes.append(error["code"])
    return "INVALID  {} violation(s): {}".format(len(errors), ", ".join(codes))


def _report(valid, instance_id, used_len, util, errors):
    used_len = round(float(used_len), 3)
    util_pct = float(geom.format_pct(util))
    return {
        "valid": valid,
        "instance_id": instance_id,
        "used_length": used_len,
        "utilization_pct": util_pct,
        "summary": _summary(valid, errors, used_len, util),
        "errors": errors,
        "measures": {"utilization_pct": util_pct, "used_length": used_len},
    }


def _peek_instance_id(path):
    """Best-effort ``instance_id`` from a file that failed schema validation."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, dict) and isinstance(data.get("instance_id"), str):
        return data["instance_id"]
    return None


def _emit(report, as_json, stream=None):
    """Print the human lines, then (with ``--json``) the JSON object last."""
    out = stream or sys.stdout
    print(_headline(report["valid"], report["used_length"], report["utilization_pct"] / 100.0), file=out)
    for error in report["errors"]:
        print("{}: {}".format(error["code"], error["message"]), file=out)
    if as_json:
        print(json.dumps(report, sort_keys=True), file=out)


def _render(instance, solution, svg_path, labels):
    """Delegate to ``render.py``; a missing or failing renderer is a warning."""
    try:
        import render  # noqa: F401  (lazy: render.py is optional at validate time)

        render.write_svg(instance, solution, svg_path, labels=labels)
    except Exception as exc:
        print(
            "warning: could not write SVG {}: {}: {}".format(svg_path, type(exc).__name__, exc),
            file=sys.stderr,
        )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="validate.py",
        description="Validate a c001 nesting solution against its instance.",
    )
    parser.add_argument("instance", help="path to the instance JSON file")
    parser.add_argument("solution", help="path to the solution JSON file")
    parser.add_argument("--svg", metavar="FILE", help="also render the layout to this SVG file")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print a machine-readable JSON object as the last stdout line",
    )
    parser.add_argument(
        "--labels",
        action="store_true",
        help="label parts with their ids in the rendered SVG (ignored unless --svg is given)",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    schema_errors = []
    instance = None
    solution = None
    try:
        instance = geom.load_instance(args.instance)
    except geom.InstanceError as exc:
        schema_errors.append(_schema_error("instance", exc))
    try:
        solution = geom.load_solution(args.solution)
    except geom.SolutionError as exc:
        schema_errors.append(_schema_error("solution", exc))

    if schema_errors:
        instance_id = (
            (instance or {}).get("instance_id")
            or (solution or {}).get("instance_id")
            or _peek_instance_id(args.instance)
            or _peek_instance_id(args.solution)
            or ""
        )
        _emit(_report(False, instance_id, 0.0, 0.0, schema_errors), args.as_json)
        return 2

    errors, used_len, util = validate(instance, solution)

    # Render before printing so the JSON object stays the last stdout line even
    # if the renderer writes to stdout itself.
    if args.svg:
        _render(instance, solution, args.svg, args.labels)

    valid = not errors
    _emit(_report(valid, instance["instance_id"], used_len, util, errors), args.as_json)
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
