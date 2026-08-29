#!/usr/bin/env python3
"""SVG renderer for challenge c001 (irregular shape nesting).

Two modes:

* **Instance only** -- a "parts catalog": every part drawn in its own cell of a
  grid, each cell sized to the largest part bounding box, with the part id
  written under it.
* **Instance + solution** -- the strip outline, a dashed vertical line at the
  used length, and every placed part filled from a categorical palette with its
  holes visibly punched out.

Usage::

    render.py <instance.json> [<solution.json>] --out FILE.svg [--labels]

Conventions and deliberate choices:

* The y axis is flipped **in Python** (``y_px = top + (maxy - y) * scale``).
  There is no ``transform="scale(1,-1)"`` group -- a negative scale would also
  mirror every text label.
* World coordinates are converted to pixels in Python as well, so the emitted
  SVG can use literal ``stroke-width="1"`` and ``font-size`` values.  The
  drawing is scaled to roughly 1200 px wide (less when the height cap bites).
* Placed rings come from :func:`geom.transform_ring` -- pure Python vertex
  arithmetic -- never from coordinates read back out of a Shapely geometry.
* Holes are punched out by emitting the exterior and every hole as subpaths of
  one ``<path>`` with ``fill-rule="evenodd"``.
* The header carries the instance id, the utilization and the used length, and
  nothing else: no participant names, no comparison between attempts.
* Rendering is deliberately tolerant so it stays useful as a debugging tool: a
  part with no placement is simply not drawn, and a placement naming an unknown
  part id is ignored.  ``validate.py`` is the thing that objects.  Utilization
  still uses :func:`geom.total_area` over *all* parts of the instance -- the
  same definition the validator uses -- so a partial layout renders with a
  deliberately pessimistic number rather than an invented one.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geom  # noqa: E402  (path shim above must run first)

__all__ = ["svg_string", "write_svg", "layout_measures", "main"]

# ---------------------------------------------------------------------------
# Layout constants (all in output pixels unless noted)
# ---------------------------------------------------------------------------

TARGET_WIDTH = 1200.0
MAX_HEIGHT = 1400.0
#: Floor on the canvas width.  A world box that is much taller than it is long
#: (an early checkpoint layout, a catalog of tall parts) hits the height cap,
#: which shrinks the scale and with it the canvas -- narrow enough to clip the
#: header text at the viewport edge.  The extra width is just background.
MIN_CANVAS_WIDTH = 560.0
MARGIN = 24.0
HEADER_HEIGHT = 52.0

BACKGROUND = "#ffffff"
STRIP_STROKE = "#888888"
PART_STROKE = "#222222"
PART_OPACITY = 0.6
USED_LINE_COLOR = "#c0392b"
TEXT_COLOR = "#111111"
SUBTEXT_COLOR = "#555555"
FONT_FAMILY = "ui-sans-serif, -apple-system, Segoe UI, Helvetica, Arial, sans-serif"

TITLE_SIZE = 16.0
SUBTITLE_SIZE = 12.0
CATALOG_LABEL_SIZE = 11.0
PART_LABEL_SIZE = 9.0

MIN_DRAW_LENGTH = 100.0
LENGTH_HEADROOM = 1.05


# ---------------------------------------------------------------------------
# Small private helpers
# ---------------------------------------------------------------------------


def _f(value):
    """Format a float for SVG output: 3 decimals, no exponent, no trailing zeros."""
    text = "{:.3f}".format(float(value))
    if text.startswith("-") and float(text) == 0.0:
        text = text[1:]
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _attrs(pairs):
    """Render an attribute mapping, escaping every value."""
    return " ".join("{}={}".format(k, quoteattr(str(v))) for k, v in pairs if v is not None)


def _ring_bbox(rings):
    points = [point for ring in rings for point in ring]
    return geom.bbox(points)


def _part_rings(part, translation=(0.0, 0.0), rotation_deg=0.0):
    """Exterior + hole rings of a part, transformed with pure-Python arithmetic."""
    rings = [geom.transform_ring(part["exterior"], translation, rotation_deg)]
    for hole in part.get("holes") or []:
        rings.append(geom.transform_ring(hole, translation, rotation_deg))
    return rings


def _path_data(rings, to_px):
    """One ``d`` attribute holding every ring as a closed subpath."""
    chunks = []
    for ring in rings:
        if len(ring) < 3:
            continue
        pieces = []
        for i, point in enumerate(ring):
            x, y = to_px(point[0], point[1])
            pieces.append("{} {} {}".format("M" if i == 0 else "L", _f(x), _f(y)))
        pieces.append("Z")
        chunks.append(" ".join(pieces))
    return " ".join(chunks)


def _text(x, y, content, size, color=TEXT_COLOR, anchor="start", weight=None):
    attrs = _attrs(
        [
            ("x", _f(x)),
            ("y", _f(y)),
            ("font-family", FONT_FAMILY),
            ("font-size", _f(size)),
            ("font-weight", weight),
            ("fill", color),
            ("text-anchor", anchor),
        ]
    )
    return "  <text {}>{}</text>".format(attrs, escape(str(content)))


def _projector(world_minx, world_maxy, scale, top):
    """Build the world -> pixel projection (y flipped here, not in the SVG)."""

    def to_px(x, y):
        return (MARGIN + (x - world_minx) * scale, top + (world_maxy - y) * scale)

    return to_px


def _fit(world_w, world_h):
    """Scale factor and canvas size for a world box of ``world_w`` x ``world_h``."""
    world_w = max(float(world_w), 1e-9)
    world_h = max(float(world_h), 1e-9)
    scale = (TARGET_WIDTH - 2.0 * MARGIN) / world_w
    height_budget = MAX_HEIGHT - 2.0 * MARGIN - HEADER_HEIGHT
    if world_h * scale > height_budget:
        scale = height_budget / world_h
    canvas_w = max(2.0 * MARGIN + world_w * scale, MIN_CANVAS_WIDTH)
    canvas_h = 2.0 * MARGIN + HEADER_HEIGHT + world_h * scale
    return scale, canvas_w, canvas_h


def _svg_open(canvas_w, canvas_h):
    attrs = _attrs(
        [
            ("xmlns", "http://www.w3.org/2000/svg"),
            ("width", _f(canvas_w)),
            ("height", _f(canvas_h)),
            ("viewBox", "0 0 {} {}".format(_f(canvas_w), _f(canvas_h))),
        ]
    )
    return "<svg {}>".format(attrs)


def _background(canvas_w, canvas_h):
    return "  <rect {} />".format(
        _attrs(
            [
                ("x", "0"),
                ("y", "0"),
                ("width", _f(canvas_w)),
                ("height", _f(canvas_h)),
                ("fill", BACKGROUND),
            ]
        )
    )


def _header(title, subtitle):
    lines = [_text(MARGIN, MARGIN + TITLE_SIZE, title, TITLE_SIZE, TEXT_COLOR, weight="bold")]
    if subtitle:
        lines.append(
            _text(
                MARGIN,
                MARGIN + TITLE_SIZE + SUBTITLE_SIZE + 8.0,
                subtitle,
                SUBTITLE_SIZE,
                SUBTEXT_COLOR,
            )
        )
    return lines


def _part_path(rings, to_px, fill, part_id):
    attrs = _attrs(
        [
            ("d", _path_data(rings, to_px)),
            ("fill", fill),
            ("fill-rule", "evenodd"),
            ("fill-opacity", _f(PART_OPACITY)),
            ("stroke", PART_STROKE),
            ("stroke-width", "1"),
            ("stroke-linejoin", "round"),
            ("data-part-id", part_id),
        ]
    )
    return "  <path {} />".format(attrs)


# ---------------------------------------------------------------------------
# The two modes
# ---------------------------------------------------------------------------


def _catalog_svg(instance, labels=False):
    """Instance-only view: every part in its own grid cell, id written under it."""
    parts = instance["parts"]
    boxes = [_ring_bbox(_part_rings(part)) for part in parts]
    max_w = max(b[2] - b[0] for b in boxes)
    max_h = max(b[3] - b[1] for b in boxes)
    span = max(max_w, max_h, 1e-9)

    pad = 0.14 * span
    label_band = 0.22 * span
    cell_w = max_w + pad
    cell_h = max_h + pad + label_band

    columns = max(1, int(math.ceil(math.sqrt(len(parts)))))
    rows = int(math.ceil(len(parts) / float(columns)))
    world_w = columns * cell_w
    world_h = rows * cell_h

    scale, canvas_w, canvas_h = _fit(world_w, world_h)
    top = MARGIN + HEADER_HEIGHT
    to_px = _projector(0.0, world_h, scale, top)

    body = [_svg_open(canvas_w, canvas_h), _background(canvas_w, canvas_h)]
    body.extend(
        _header(
            "{} - parts catalog".format(instance.get("instance_id", "instance")),
            "{} parts   |   strip width {}   |   total part area {}".format(
                len(parts),
                _f(instance.get("strip_width", geom.DEFAULT_STRIP_WIDTH)),
                _f(geom.total_area(instance)),
            ),
        )
    )

    for index, (part, box) in enumerate(zip(parts, boxes)):
        column = index % columns
        row = index // columns
        cell_x = column * cell_w
        cell_bottom = world_h - (row + 1) * cell_h
        width = box[2] - box[0]
        height = box[3] - box[1]
        tx = cell_x + 0.5 * (cell_w - width) - box[0]
        ty = cell_bottom + label_band + 0.5 * (cell_h - label_band - height) - box[1]
        rings = _part_rings(part, (tx, ty), 0.0)
        body.append(_part_path(rings, to_px, geom.PALETTE[index % len(geom.PALETTE)], part["id"]))
        label_x, label_y = to_px(cell_x + 0.5 * cell_w, cell_bottom + 0.30 * label_band)
        body.append(
            _text(label_x, label_y, part["id"], CATALOG_LABEL_SIZE, SUBTEXT_COLOR, anchor="middle")
        )

    body.append("</svg>")
    return "\n".join(body) + "\n"


def _placements_by_part(instance, solution):
    """``part_id -> placement`` for placements naming a part of this instance."""
    known = {part["id"] for part in instance["parts"]}
    out = {}
    for placement in solution.get("placements", []):
        part_id = placement.get("part_id")
        if part_id in known and part_id not in out:
            out[part_id] = placement
    return out


def _placed_rings(instance, solution):
    """``[(part index, part id, transformed rings), ...]`` in instance part order."""
    by_part = _placements_by_part(instance, solution)
    placed = []
    for index, part in enumerate(instance["parts"]):
        placement = by_part.get(part["id"])
        if placement is None:
            continue
        placed.append(
            (
                index,
                part["id"],
                _part_rings(part, placement["translation"], placement["rotation_deg"]),
            )
        )
    return placed


def _used_length(placed):
    used_len = 0.0
    for _, _, rings in placed:
        for ring in rings:
            for point in ring:
                if point[0] > used_len:
                    used_len = point[0]
    return used_len


def layout_measures(instance, solution):
    """``(used_length, utilization, parts placed)`` for a layout.

    Shared with ``gallery.py`` so both compute the caption number the same way,
    from the two documents and never from a field stored in a file.
    """
    placed = _placed_rings(instance, solution)
    used_len = _used_length(placed)
    strip_width = float(instance.get("strip_width", geom.DEFAULT_STRIP_WIDTH))
    return used_len, geom.utilization(geom.total_area(instance), strip_width, used_len), len(placed)


def _solution_svg(instance, solution, labels=False):
    """Layout view: strip outline, dashed used-length marker, placed parts."""
    strip_width = float(instance.get("strip_width", geom.DEFAULT_STRIP_WIDTH))
    placed = _placed_rings(instance, solution)
    used_len = _used_length(placed)

    draw_len = max(used_len * LENGTH_HEADROOM, MIN_DRAW_LENGTH)
    util = geom.utilization(geom.total_area(instance), strip_width, used_len)

    # The world box is the strip plus whatever sticks out of it, so an INVALID
    # layout (part at negative x, part past y = W) is drawn, not hidden.
    world_minx, world_miny, world_maxx, world_maxy = 0.0, 0.0, draw_len, strip_width
    for _, _, rings in placed:
        for ring in rings:
            for x, y in ring:
                world_minx = min(world_minx, x)
                world_miny = min(world_miny, y)
                world_maxx = max(world_maxx, x)
                world_maxy = max(world_maxy, y)
    scale, canvas_w, canvas_h = _fit(world_maxx - world_minx, world_maxy - world_miny)
    top = MARGIN + HEADER_HEIGHT
    to_px = _projector(world_minx, world_maxy, scale, top)

    body = [_svg_open(canvas_w, canvas_h), _background(canvas_w, canvas_h)]
    body.extend(
        _header(
            str(instance.get("instance_id", "instance")),
            "utilization {}%   |   used length {}   |   strip width {}   |   {} parts placed".format(
                geom.format_pct(util), _f(used_len), _f(strip_width), len(placed)
            ),
        )
    )

    # Strip outline: from x = 0 to the drawn length, full width.
    x0, y0 = to_px(0.0, strip_width)
    x1, y1 = to_px(draw_len, 0.0)
    body.append(
        "  <rect {} />".format(
            _attrs(
                [
                    ("x", _f(x0)),
                    ("y", _f(y0)),
                    ("width", _f(x1 - x0)),
                    ("height", _f(y1 - y0)),
                    ("fill", "none"),
                    ("stroke", STRIP_STROKE),
                    ("stroke-width", "1"),
                ]
            )
        )
    )

    for index, part_id, rings in placed:
        body.append(_part_path(rings, to_px, geom.PALETTE[index % len(geom.PALETTE)], part_id))

    # The one and only <line> in the document: the used-length marker.
    lx, ly_top = to_px(used_len, strip_width)
    _, ly_bottom = to_px(used_len, 0.0)
    body.append(
        "  <line {} />".format(
            _attrs(
                [
                    ("x1", _f(lx)),
                    ("y1", _f(ly_top)),
                    ("x2", _f(lx)),
                    ("y2", _f(ly_bottom)),
                    ("stroke", USED_LINE_COLOR),
                    ("stroke-width", "1"),
                    ("stroke-dasharray", "6 4"),
                ]
            )
        )
    )

    if labels:
        for _, part_id, rings in placed:
            bx = _ring_bbox([rings[0]])
            cx, cy = to_px(0.5 * (bx[0] + bx[2]), 0.5 * (bx[1] + bx[3]))
            body.append(
                _text(cx, cy + 0.35 * PART_LABEL_SIZE, part_id, PART_LABEL_SIZE, TEXT_COLOR, anchor="middle")
            )

    body.append("</svg>")
    return "\n".join(body) + "\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def svg_string(instance, solution=None, labels=False):
    """Render an instance (and optionally a solution) to an SVG document string."""
    if not instance.get("parts"):
        raise geom.InstanceError("parts: expected a non-empty list")
    if solution is None:
        return _catalog_svg(instance, labels=labels)
    return _solution_svg(instance, solution, labels=labels)


def write_svg(instance, solution, out_path, labels=False):
    """Render to ``out_path`` (parent directories are created).  Returns the path."""
    out_path = Path(out_path)
    if str(out_path.parent) not in ("", "."):
        out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg_string(instance, solution, labels=labels), encoding="utf-8")
    return out_path


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="render.py",
        description="Render a c001 instance (parts catalog) or a solution layout as SVG.",
    )
    parser.add_argument("instance", help="instance JSON file")
    parser.add_argument("solution", nargs="?", help="solution JSON file (omit for the parts catalog)")
    parser.add_argument("--out", required=True, help="output SVG file")
    parser.add_argument("--labels", action="store_true", help="draw part ids on the placed parts")
    args = parser.parse_args(argv)

    try:
        instance = geom.load_instance(args.instance)
        solution = geom.load_solution(args.solution) if args.solution else None
    except (geom.InstanceError, geom.SolutionError) as err:
        print("ERROR {}".format(err), file=sys.stderr)
        return 2

    if solution is not None and solution["instance_id"] != instance["instance_id"]:
        print(
            "ERROR instance_id mismatch: solution says {!r}, instance says {!r}".format(
                solution["instance_id"], instance["instance_id"]
            ),
            file=sys.stderr,
        )
        return 2

    try:
        out = write_svg(instance, solution, args.out, labels=args.labels)
    except OSError as err:
        print("ERROR cannot write {}: {}".format(args.out, err), file=sys.stderr)
        return 2
    print("wrote {}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
