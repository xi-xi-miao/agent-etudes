#!/usr/bin/env python3
"""Baseline solver for challenge c001 -- axis-aligned bounding-box shelf packing.

The point of this tool is not to nest well.  It is to give "less good" a
concrete face on day one, to prove the file formats end to end, and to give
participants a reference floor to climb away from.  It deliberately ignores the
true geometry of every part and packs bounding boxes only.

Algorithm (shelves are **horizontal rows**, because the strip is bounded in x
by its width and unbounded in +y):

1. For every part, pick the better of the two axis-aligned orientations, 0 deg
   and 90 deg: keep the ones whose x-extent fits the strip width, and among
   those take the smallest y-extent (ties broken by the smaller x-extent).
   A part with no fitting orientation is an error -- generated instances cap the
   point-set diameter so that both extents always fit.
2. Sort the parts by decreasing chosen y-extent, i.e. by shelf height.
3. First fit: scan the open shelves bottom to top and drop the part onto the
   first one with enough remaining x-room, packing rightward from x = 0.  If
   none has room, open a new shelf above all of them.

Why that order matters: a shelf's height is fixed by the *first* part put onto
it, and step 2 guarantees every part placed later has a y-extent no larger than
that.  So a shelf never grows upward, shelves stay disjoint in y, parts on one
shelf stay disjoint in x, and the layout cannot overlap.  Choosing orientations
before sorting is load-bearing for that invariant.

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
    """Pick the orientation of ``part`` that makes the lowest shelf.

    Only orientations whose x-extent fits ``strip_width`` are eligible; among
    those the smallest y-extent wins, ties going to the smaller x-extent.
    Raises :class:`BaselineError` when nothing fits.
    """
    options = orientation_options(part, allowed)
    fitting = [opt for opt in options if opt[3] <= strip_width]
    if not fitting:
        extents = ", ".join(
            "{:g}deg x-extent={:.3f}".format(opt[0], opt[3]) for opt in options
        ) or "no orientation permitted by rotations_allowed"
        raise BaselineError(
            "part {!r}: no allowed orientation fits a strip of width {:g} ({})".format(
                part["id"], strip_width, extents
            )
        )
    return min(fitting, key=lambda opt: (opt[4], opt[3]))


def pack(instance):
    """Pack every part of ``instance`` onto horizontal shelves.

    Returns the list of placement dicts, ordered as the parts were placed.
    """
    strip_width = float(instance["strip_width"])
    allowed = instance.get("rotations_allowed", "free")

    # Step 1: orientations first, for every part, before any ordering happens.
    chosen = [
        (part, choose_orientation(part, strip_width, allowed))
        for part in instance["parts"]
    ]

    # Step 2: highest shelf first.  The index keeps the order total, so the
    # packing is reproducible whatever order equal-sized parts arrive in.
    order = sorted(
        range(len(chosen)),
        key=lambda i: (-chosen[i][1][4], -chosen[i][1][3], i),
    )

    # Step 3: first fit over the open shelves.
    shelves = []  # list of [shelf_y, height, x_cursor]
    next_shelf_y = 0.0
    placements = []

    for i in order:
        part, (rotation, minx, miny, x_extent, y_extent) = chosen[i]
        target = None
        for shelf in shelves:
            if shelf[2] + x_extent <= strip_width:
                target = shelf
                break
        if target is None:
            target = [next_shelf_y, y_extent, 0.0]
            shelves.append(target)
            next_shelf_y += y_extent

        shelf_y, _height, x_cursor = target
        placements.append(
            {
                "part_id": part["id"],
                "translation": [x_cursor - minx, shelf_y - miny],
                "rotation_deg": rotation,
            }
        )
        target[2] = x_cursor + x_extent

    return placements


def solve(instance, seed=0):
    """Build the complete solution dict for ``instance``."""
    return {
        "instance_id": instance["instance_id"],
        "solver": {"name": SOLVER_NAME, "version": SOLVER_VERSION, "seed": int(seed)},
        "placements": pack(instance),
    }


def measure(instance, solution):
    """Return ``(used_height, utilization)`` for a finished solution.

    Shapely is used here purely as a measure; nothing it returns is written to
    the solution file.
    """
    polys = geom.placed_polygons(instance, solution)
    used = geom.used_height(polys.values())
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
            "placed {} parts  used_height={:.3f}  utilization={}%".format(
                len(solution["placements"]), used, geom.format_pct(util)
            ),
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
