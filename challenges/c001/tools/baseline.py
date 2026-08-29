#!/usr/bin/env python3
"""Baseline solver for challenge c001 -- axis-aligned bounding-box shelf packing.

The point of this tool is not to nest well.  It is to give "less good" a
concrete face on day one, to prove the file formats end to end, and to give
participants a reference floor to climb away from.  It deliberately ignores the
true geometry of every part and packs bounding boxes only.

Algorithm (shelves are **vertical columns**, because the strip is unbounded in
+x and bounded in y):

1. For every part, pick the better of the two axis-aligned orientations, 0 deg
   and 90 deg: keep the ones whose y-extent fits the strip width, and among
   those take the smallest x-extent (ties broken by the smaller y-extent).
   A part with no fitting orientation is an error -- generated instances cap the
   point-set diameter so that both extents always fit.
2. Sort the parts by decreasing chosen x-extent, i.e. by column thickness.
3. First fit: scan the open columns left to right and drop the part into the
   first one with enough remaining y-room, stacking upward from y = 0.  If none
   has room, open a new column to the right of all of them.

Why that order matters: a column's thickness is fixed by the *first* part put
into it, and step 2 guarantees every part placed later has an x-extent no larger
than that.  So a column never grows sideways, columns stay disjoint in x, parts
within a column stay disjoint in y, and the layout cannot overlap.  Choosing
orientations before sorting is load-bearing for that invariant.

CLI (the same shape participants must implement for their own solver)::

    baseline.py <instance.json> --out <solution.json> [--time-budget 60]
                [--seed 0] [--quiet]

``--time-budget`` and ``--seed`` are accepted for CLI compatibility; the
algorithm is deterministic and finishes instantly, so the budget is never
consulted and the seed only travels into the solution's ``solver`` block.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geom  # noqa: E402  (needs the sys.path line above)

#: Orientations this baseline considers, in degrees CCW about the local origin.
ORIENTATIONS = (0.0, 90.0)

SOLVER_NAME = "baseline-shelf"
SOLVER_VERSION = "1.0"


class BaselineError(ValueError):
    """Raised when an instance cannot be packed by this baseline."""


def _part_points(part):
    """Every vertex of a part in local coordinates (holes lie inside the shell,
    so the exterior alone already fixes the bounding box -- holes are included
    anyway so the helper stays honest for hand-authored parts)."""
    points = list(part["exterior"])
    for hole in part.get("holes") or []:
        points.extend(hole)
    return points


def orientation_options(part, allowed="free"):
    """Bounding boxes of ``part`` under each permitted orientation.

    Returns a list of ``(rotation_deg, minx, miny, x_extent, y_extent)`` tuples.
    The bounds come from :func:`geom.transform_ring` -- pure-Python vertex
    arithmetic -- because ``minx``/``miny`` feed straight into the emitted
    translation and emitted coordinates must never be read back out of a
    Shapely geometry.
    """
    options = []
    for rotation in ORIENTATIONS:
        if not geom.rotation_allowed(rotation, allowed):
            continue
        rotated = geom.transform_ring(_part_points(part), (0.0, 0.0), rotation)
        minx, miny, maxx, maxy = geom.bbox(rotated)
        options.append((rotation, minx, miny, maxx - minx, maxy - miny))
    return options


def choose_orientation(part, strip_width, allowed="free"):
    """Pick the orientation of ``part`` that makes the thinnest column.

    Only orientations whose y-extent fits ``strip_width`` are eligible; among
    those the smallest x-extent wins, ties going to the smaller y-extent.
    Raises :class:`BaselineError` when nothing fits.
    """
    options = orientation_options(part, allowed)
    fitting = [opt for opt in options if opt[4] <= strip_width]
    if not fitting:
        extents = ", ".join(
            "{:g}deg y-extent={:.3f}".format(opt[0], opt[4]) for opt in options
        ) or "no orientation permitted by rotations_allowed"
        raise BaselineError(
            "part {!r}: no allowed orientation fits a strip of width {:g} ({})".format(
                part["id"], strip_width, extents
            )
        )
    return min(fitting, key=lambda opt: (opt[3], opt[4]))


def pack(instance):
    """Pack every part of ``instance`` into vertical columns.

    Returns the list of placement dicts, ordered as the parts were placed.
    """
    strip_width = float(instance["strip_width"])
    allowed = instance.get("rotations_allowed", "free")

    # Step 1: orientations first, for every part, before any ordering happens.
    chosen = [
        (part, choose_orientation(part, strip_width, allowed))
        for part in instance["parts"]
    ]

    # Step 2: thickest column first.  The index keeps the order total, so the
    # packing is reproducible whatever order equal-sized parts arrive in.
    order = sorted(
        range(len(chosen)),
        key=lambda i: (-chosen[i][1][3], -chosen[i][1][4], i),
    )

    # Step 3: first fit over the open columns.
    columns = []  # list of [column_x, thickness, y_cursor]
    next_column_x = 0.0
    placements = []

    for i in order:
        part, (rotation, minx, miny, x_extent, y_extent) = chosen[i]
        target = None
        for column in columns:
            if column[2] + y_extent <= strip_width:
                target = column
                break
        if target is None:
            target = [next_column_x, x_extent, 0.0]
            columns.append(target)
            next_column_x += x_extent

        column_x, _thickness, y_cursor = target
        placements.append(
            {
                "part_id": part["id"],
                "translation": [column_x - minx, y_cursor - miny],
                "rotation_deg": rotation,
            }
        )
        target[2] = y_cursor + y_extent

    return placements


def solve(instance, seed=0):
    """Build the complete solution dict for ``instance``."""
    return {
        "instance_id": instance["instance_id"],
        "solver": {"name": SOLVER_NAME, "version": SOLVER_VERSION, "seed": int(seed)},
        "placements": pack(instance),
    }


def measure(instance, solution):
    """Return ``(used_length, utilization)`` for a finished solution.

    Shapely is used here purely as a measure; nothing it returns is written to
    the solution file.
    """
    polys = geom.placed_polygons(instance, solution)
    used = geom.used_length(polys.values())
    return used, geom.utilization(geom.total_area(instance), instance["strip_width"], used)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="baseline.py",
        description="Bounding-box shelf-packing baseline solver for challenge c001.",
    )
    parser.add_argument("instance", help="path to the instance JSON file")
    parser.add_argument("--out", required=True, help="path of the solution JSON to write")
    parser.add_argument(
        "--time-budget",
        type=float,
        default=60.0,
        metavar="SECONDS",
        help="accepted for CLI compatibility; this solver is instant (default: 60)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="recorded in the solver block; the algorithm is deterministic (default: 0)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="do not print the summary line to stderr",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        instance = geom.load_instance(args.instance)
        solution = solve(instance, seed=args.seed)
        used, util = measure(instance, solution)
    except (geom.InstanceError, geom.SolutionError, BaselineError) as err:
        print("baseline.py: {}".format(err), file=sys.stderr)
        return 2

    geom.write_json(solution, args.out)

    if not args.quiet:
        print(
            "placed {} parts  used_length={:.3f}  utilization={}%".format(
                len(solution["placements"]), used, geom.format_pct(util)
            ),
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
