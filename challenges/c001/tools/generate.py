#!/usr/bin/env python3
"""Deterministic instance generator for challenge c001 (irregular shape nesting).

Usage::

    uv run python challenges/c001/tools/generate.py \\
        --tier 2 --seed 2001 --out instances/dev/c001-t2-dev-01.json \\
        --id c001-t2-dev-01 [--parts 40] [--strip-width 1000]

Determinism
-----------
Every random draw comes from one private ``random.Random`` seeded with the
string ``"c001:<tier>:<seed>:<parts>"`` and is taken through
:class:`Stream`, which only ever calls ``rng.random()``.  ``gauss``,
``shuffle`` and ``choices`` are never used: their internals are free to change
between CPython releases, ``random()`` is not.  ``--id`` and ``--out`` are
pure labels and never touch the stream, so the same ``(tier, seed, parts)``
always produces the same geometry at a fixed ``--strip-width`` (the width
feeds the diameter cap, which decides which shapes are rejected, so it is
part of the determinism domain even though it is not in the seed key).

Shapely is used only as an oracle (validity, containment, the maximum
inscribed circle used to *choose* a hole centre).  Every emitted coordinate is
computed with pure-Python vertex arithmetic and rounded to 3 decimals.

Pipeline (one-way stages; each stage only ever revises its own output)
---------------------------------------------------------------------
1. Draw the instance's target total net area ``T`` uniformly in
   ``[2.0e6, 3.0e6]`` (times ``parts / 40``; see :data:`TARGET_AREA_MIN`) and
   a size band for every part index (25% large, 50% medium, 25% small), then
   one target net area per part from its band.
2. Because every shape is normalised to *exactly* its drawn target area, the
   sum of the net areas is the sum of the drawn targets, so the single global
   scale ``s = sqrt(T / sum(targets))`` is known up front and is a fixed point
   of "re-solve the global scale".  Shapes are therefore built and gated at
   that anticipated scale.
3. Build one exterior per part, then iterate: measure the net areas, re-solve
   ``s``, finalise (scale, translate the bbox minimum to the origin, round to
   3 dp, orient, canonicalise the ring start) and re-check the gates.  A part
   that fails is redrawn *from the same stream keeping its drawn target area*,
   which is what makes ``s`` stable; the loop therefore converges on the first
   pass in practice and is bounded by ``MAX_OUTER_ITERS`` regardless.  Each
   individual shape has its own retry loop (:func:`_build_exterior`) that
   blends the drawn parameters toward the compact end of their ranges on
   every attempt, so a part whose area is too large for its aspect ratio
   provably walks back inside the diameter cap.
4. Tier 3 only: punch 1-2 convex holes into ~30% of the medium/large parts,
   then renormalise each host by ``sqrt(A / (A - H))`` so its net area is back
   at its target.  This second gate pass may only shrink or drop holes, never
   touch an exterior -- so stage 3's guarantees survive it.  The exterior
   diameter budget is tightened by :data:`PRE_HOLE_DIAMETER_MARGIN` in tier 3
   precisely to absorb that renormalisation.
5. Tier 3 only: verify the hole-fit property with a rotation sweep.  It holds
   by construction (holes are sized around already-generated small parts), so
   a failure means an unlucky host; the whole instance is then regenerated
   from a bumped attempt counter mixed into the seed string
   (``"c001:<tier>:<seed>:<parts>:<attempt>"``), which keeps the result
   deterministic.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geom  # noqa: E402  (path shim above must run first)

from shapely.geometry import Point, Polygon  # noqa: E402

try:  # Shapely >= 2.1
    from shapely import maximum_inscribed_circle as _shapely_mic
except ImportError:  # pragma: no cover - exercised only on Shapely 2.0
    _shapely_mic = None


# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------

#: Written into the instance under ``generator.version``.
GENERATOR_VERSION = "1.0"

#: Default number of parts per instance.
DEFAULT_PARTS = 40

#: Instance target total net area is drawn uniformly from this interval --
#: at the default part count.  With another ``--parts`` the band is scaled by
#: ``parts / DEFAULT_PARTS``, since the interval is the plan's figure *for a
#: 40-part instance* and a 12-part instance made of 40 parts' worth of
#: material could not satisfy the diameter cap.  The factor is exactly 1.0 for
#: the committed dev set, so this generalisation moves no coordinate there.
TARGET_AREA_MIN = 2.0e6
TARGET_AREA_MAX = 3.0e6

#: Size bands (net area).  Plan section 6: the handoff's bands scaled x2.8.
BAND_LARGE = (8.0e4, 17.0e4)
BAND_MEDIUM = (2.0e4, 8.0e4)
BAND_SMALL = (3.0e3, 2.0e4)
BAND_RANGES = {"large": BAND_LARGE, "medium": BAND_MEDIUM, "small": BAND_SMALL}

#: Fraction of the strip width that caps a part's point-set diameter.
DIAMETER_FRACTION = 0.85

#: Tier-3 exteriors are gated against this fraction of the diameter cap so the
#: post-hole renormalisation (at most sqrt(1 / (1 - MAX_HOLE_AREA_FRACTION)))
#: cannot push the finished part past the hard cap.
PRE_HOLE_DIAMETER_MARGIN = 0.92

#: Post-rounding validity gates.
MIN_EDGE_LENGTH = 2.0
MIN_VERTEX_EDGE_CLEARANCE = 2.0

#: Holes: minimum wall between a hole and the rest of the part boundary
#: (this is the ``host.buffer(-12).contains(hole)`` rule, and because the
#: erosion is applied to the host *including* the holes placed so far it also
#: keeps distinct holes at least this far apart).
HOLE_WALL = 12.0

#: A host's holes may not consume more than this fraction of its exterior.
MAX_HOLE_AREA_FRACTION = 0.14

#: Fraction of medium/large parts that receive holes in tier 3.
HOLE_HOST_FRACTION = 0.30

#: A fit hole's circumradius is at least this multiple of the small part's
#: bounding-circle radius (the plan's floor) and, on top of that, wide enough
#: that its *inradius* clears the part by FIT_INRADIUS_MARGIN.
HOLE_FIT_FACTOR = 1.15
FIT_INRADIUS_MARGIN = 6.0

#: Fit holes are always regular octagons: eight sides give the best
#: inradius-to-circumradius ratio in the 4-8 range the plan allows, so the
#: hole a given small part needs is as small (and as easy to host) as
#: possible.  A square would need a circumradius 1.41x the part's bounding
#: circle instead of 1.15x -- three times the hole area.
FIT_HOLE_SIDES = 8

#: The hole-fit property that must hold in every tier-3 instance.
FIT_PAIRS_REQUIRED = 3
FIT_HOLES_REQUIRED = 2
SWEEP_STEP_DEG = 10
SWEEP_EROSION = 1.0

#: Explicit tolerance for the maximum-inscribed-circle oracle -- letting GEOS
#: derive one from the geometry's size would make hole centres depend on the
#: part's magnitude in a way that is harder to reason about.
MIC_TOLERANCE = 0.01

#: Retry budgets.  All three are generous; hitting one is a bug, not bad luck.
MAX_SHAPE_TRIES = 240
MAX_OUTER_ITERS = 40
MAX_GEN_ATTEMPTS = 12

#: Tier 2 and 3 promise concave parts, so a shape whose area is within this
#: fraction of its convex hull's is redrawn.
MAX_CONVEXITY = 0.995

#: On every shape retry the drawn parameters are blended toward the most
#: compact end of their range by this factor, so the retry loop provably walks
#: toward a shape that satisfies the diameter cap.
COMPACT_DECAY = 0.8


class GenerationError(RuntimeError):
    """Raised when a retry budget is exhausted."""


# --------------------------------------------------------------------------
# Random stream
# --------------------------------------------------------------------------


def seed_key(tier, seed, parts, attempt=0):
    """The exact string handed to ``random.Random``."""
    base = "{}:{}:{}:{}".format(geom.CHALLENGE_ID, tier, seed, parts)
    return base if attempt == 0 else "{}:{}".format(base, attempt)


class Stream:
    """A thin deterministic wrapper that only ever calls ``rng.random()``."""

    def __init__(self, key):
        import random

        self._rng = random.Random(key)

    def random(self):
        return self._rng.random()

    def uniform(self, a, b):
        return a + (b - a) * self.random()

    def randint(self, a, b):
        """Inclusive integer draw."""
        if b < a:
            raise ValueError("randint: empty interval")
        value = a + int(self.random() * (b - a + 1))
        return b if value > b else value

    def choice(self, seq):
        return seq[self.randint(0, len(seq) - 1)]

    def permuted(self, seq):
        """Fisher-Yates over a copy, driven by :meth:`randint`."""
        out = list(seq)
        for i in range(len(out) - 1, 0, -1):
            j = self.randint(0, i)
            out[i], out[j] = out[j], out[i]
        return out

    def subset(self, seq, k):
        """``k`` distinct elements of ``seq``, in the original order."""
        picked = set(self.permuted(range(len(seq)))[:k])
        return [seq[i] for i in sorted(picked)]


# --------------------------------------------------------------------------
# Pure-Python ring helpers
# --------------------------------------------------------------------------


def _r3(value):
    """Round to 3 decimals, normalising ``-0.0`` away (json.dumps emits it)."""
    out = round(value, 3)
    return 0.0 if out == 0 else out


def _convex_hull(points):
    """Andrew's monotone chain, returning a CCW hull without repeated ends."""
    pts = sorted({(p[0], p[1]) for p in points})
    if len(pts) < 3:
        return [[x, y] for x, y in pts]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    return [[x, y] for x, y in hull]


def _reduce_vertices(ring, target):
    """Drop vertices from a convex ring until it has ``target`` of them.

    Each step removes the vertex whose removal loses the least area; exact
    ties keep the lowest index, which is what makes the choice reproducible.
    """
    out = [list(p) for p in ring]
    while len(out) > target and len(out) > 3:
        n = len(out)
        best_i = 0
        best_loss = None
        for i in range(n):
            a, b, c = out[(i - 1) % n], out[i], out[(i + 1) % n]
            loss = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
            if best_loss is None or loss < best_loss:
                best_loss = loss
                best_i = i
        out.pop(best_i)
    return out


def _scale_ring(ring, factor, cx=0.0, cy=0.0):
    return [[cx + (p[0] - cx) * factor, cy + (p[1] - cy) * factor] for p in ring]


def _normalise_area(ring, area):
    """Uniformly scale a ring about the origin so ``|signed_area| == area``."""
    current = abs(geom.signed_area(ring))
    if current <= 0:
        raise GenerationError("degenerate ring")
    return _scale_ring(ring, math.sqrt(area / current))


def _rotate_ring(ring, angle_rad):
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return [[c * p[0] - s * p[1], s * p[0] + c * p[1]] for p in ring]


def _bbox_center(ring):
    minx, miny, maxx, maxy = geom.bbox(ring)
    return (0.5 * (minx + maxx), 0.5 * (miny + maxy))


def _circumradius(ring, center=None):
    """Largest distance from ``center`` (default: the bbox centre) to a vertex."""
    cx, cy = center if center is not None else _bbox_center(ring)
    return max(math.hypot(p[0] - cx, p[1] - cy) for p in ring)


def _point_segment_distance(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / denom
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _regular_ring(center, radius, sides, phase, radii=None):
    """A regular (or radius-jittered) polygon, counter-clockwise.

    With an even ``sides`` and no jitter the shape is centrally symmetric, so
    its bounding-box centre coincides with ``center`` -- which is what makes
    the fit sweep's "translate bbox centre onto bbox centre" exact.
    """
    cx, cy = center
    out = []
    for i in range(sides):
        theta = phase + 2.0 * math.pi * i / sides
        r = radius if radii is None else radii[i]
        out.append([cx + r * math.cos(theta), cy + r * math.sin(theta)])
    return out


# --------------------------------------------------------------------------
# Shape builders (unit-ish coordinates; the caller normalises the area)
# --------------------------------------------------------------------------


def _decay(tries):
    return COMPACT_DECAY ** tries


def _hull_ring(st, tries, min_vertices=3, max_vertices=10):
    """Convex hull of 6-20 points drawn from a randomly oriented ellipse."""
    n_points = st.randint(6, 20)
    aspect = 1.0 + (st.uniform(1.0, 2.2) - 1.0) * _decay(tries)
    orientation = st.uniform(0.0, 2.0 * math.pi)
    keep = st.randint(min_vertices, max_vertices)

    cloud = []
    for _ in range(n_points):
        radius = math.sqrt(st.random())
        theta = st.uniform(0.0, 2.0 * math.pi)
        cloud.append([aspect * radius * math.cos(theta), radius * math.sin(theta)])
    hull = _convex_hull(_rotate_ring(cloud, orientation))
    if len(hull) < 3:
        return None
    return _reduce_vertices(hull, keep)


def _notched_ring(st, tries):
    """A convex hull with 1-3 rectangular notches cut in by vertex insertion."""
    base = _hull_ring(st, tries, min_vertices=4, max_vertices=9)
    if base is None or len(base) < 4:
        return None
    ring = geom.ensure_ccw(base)

    n_notches = st.randint(1, 3)
    lengths = [
        (
            math.hypot(
                ring[(i + 1) % len(ring)][0] - ring[i][0],
                ring[(i + 1) % len(ring)][1] - ring[i][1],
            ),
            i,
        )
        for i in range(len(ring))
    ]
    # Notch the longest edges; every edge is notched at most once.
    lengths.sort(key=lambda item: (-item[0], item[1]))
    chosen = sorted(idx for _, idx in lengths[: min(n_notches, len(ring) - 2)])

    # Draw every notch's parameters up front so the stream is consumed in a
    # fixed order regardless of how many edges survive the filters below.
    # Notch depth decays toward the shallow end of its range but never to
    # zero: a zero-depth notch would leave a convex shape, which the tier-2
    # concavity gate rejects, and the retry loop would never converge.
    params = [
        (
            0.15 + (st.uniform(0.15, 0.40) - 0.15) * _decay(tries),
            st.uniform(0.25, 0.55),
            st.uniform(0.32, 0.68),
        )
        for _ in chosen
    ]

    out = []
    for i in range(len(ring)):
        a = ring[i]
        b = ring[(i + 1) % len(ring)]
        out.append([a[0], a[1]])
        if i not in chosen:
            continue
        depth_frac, mouth_frac, mid = params[chosen.index(i)]
        ex, ey = b[0] - a[0], b[1] - a[1]
        edge_len = math.hypot(ex, ey)
        if edge_len <= 0:
            continue
        nx, ny = -ey / edge_len, ex / edge_len  # inward for a CCW ring
        width = max(((v[0] - a[0]) * nx + (v[1] - a[1]) * ny) for v in ring)
        if width <= 0:
            continue
        depth = depth_frac * width
        half = 0.5 * mouth_frac
        t1 = min(max(mid - half, 0.10), 0.80)
        t2 = min(max(mid + half, t1 + 0.12), 0.90)
        p1 = [a[0] + t1 * ex, a[1] + t1 * ey]
        p2 = [a[0] + t2 * ex, a[1] + t2 * ey]
        out.append(p1)
        out.append([p1[0] + depth * nx, p1[1] + depth * ny])
        out.append([p2[0] + depth * nx, p2[1] + depth * ny])
        out.append(p2)
    return out


def _orthogonal_ring(st, tries):
    """An axis-aligned L, T or U built from explicit vertex lists.

    Every parameter decays toward the end of its range that removes the least
    material, so a large part whose first draw is too spindly for the
    diameter cap walks toward a stocky version of the *same* letter instead of
    having to become a different kind of shape.
    """
    kind = st.randint(0, 2)
    decay = _decay(tries)
    height = 1.0 + (st.uniform(0.6, 1.6) - 1.0) * decay
    width = 1.0

    if kind == 0:  # L: full rectangle minus the top-right block
        a = (0.30 + (st.uniform(0.30, 0.60) - 0.30) * decay) * width
        b = (0.30 + (st.uniform(0.30, 0.60) - 0.30) * decay) * height
        ring = [
            [0.0, 0.0],
            [width, 0.0],
            [width, height - b],
            [width - a, height - b],
            [width - a, height],
            [0.0, height],
        ]
    elif kind == 1:  # T: top bar plus a central stem
        cut = (0.20 + (st.uniform(0.20, 0.35) - 0.20) * decay) * width
        bar = (0.50 - (0.50 - st.uniform(0.30, 0.50)) * decay) * height
        ring = [
            [cut, 0.0],
            [width - cut, 0.0],
            [width - cut, height - bar],
            [width, height - bar],
            [width, height],
            [0.0, height],
            [0.0, height - bar],
            [cut, height - bar],
        ]
    else:  # U: full rectangle minus a top-middle notch
        cut = (0.25 + (st.uniform(0.25, 0.35) - 0.25) * decay) * width
        floor = (0.60 - (0.60 - st.uniform(0.35, 0.60)) * decay) * height
        ring = [
            [0.0, 0.0],
            [width, 0.0],
            [width, height],
            [width - cut, height],
            [width - cut, floor],
            [cut, floor],
            [cut, height],
            [0.0, height],
        ]
    return geom.ensure_ccw(ring)


def _star_ring(st, tries):
    """Alternating outer/inner radius, 4-7 points."""
    points = st.randint(4, 7)
    ratio = st.uniform(0.45, 0.75)
    ratio = 0.75 - (0.75 - ratio) * _decay(tries)
    phase = st.uniform(0.0, math.pi / points)
    out = []
    for i in range(2 * points):
        theta = phase + math.pi * i / points
        r = 1.0 if i % 2 == 0 else ratio
        out.append([r * math.cos(theta), r * math.sin(theta)])
    return out


def draw_kind(st, tier):
    """Pick a shape kind: tier 1 is all hulls, tiers 2-3 mix 50/30/20.

    Drawn once per part, *outside* the retry loop, so the realised mix is the
    drawn mix.  Re-picking on every retry would silently reweight it toward
    whichever kind clears the diameter cap most easily.
    """
    if tier == 1:
        return "hull"
    pick = st.random()
    if pick < 0.50:
        return "notched"
    if pick < 0.80:
        return "orthogonal"
    return "star"


_BUILDERS = {
    "hull": _hull_ring,
    "notched": _notched_ring,
    "orthogonal": _orthogonal_ring,
    "star": _star_ring,
}


def _draw_ring(st, kind, tries):
    """Build one shape of the given kind."""
    return _BUILDERS[kind](st, tries)


# --------------------------------------------------------------------------
# Finalisation and gates
# --------------------------------------------------------------------------


def finalise_rings(exterior, holes, scale):
    """Scale, move the bbox minimum to the origin, round, orient, canonicalise."""
    ext = _scale_ring(exterior, scale)
    hls = [_scale_ring(h, scale) for h in holes]
    minx, miny, _, _ = geom.bbox(ext)
    ext = [[_r3(p[0] - minx), _r3(p[1] - miny)] for p in ext]
    hls = [[[_r3(p[0] - minx), _r3(p[1] - miny)] for p in h] for h in hls]
    ext = geom.canonical_ring(geom.ensure_ccw(ext))
    hls = [geom.canonical_ring(geom.ensure_cw(h)) for h in hls]
    return ext, hls


def gate_failure(exterior, holes, diameter_cap):
    """Return ``None`` when a finished part passes every gate, else a reason.

    Applied *after* rounding, because rounding is what can create a hairline
    edge or a near-touching vertex in the first place.
    """
    if len(exterior) < 3:
        return "exterior has fewer than 3 vertices"
    poly = Polygon(exterior, holes)
    if not poly.is_valid:
        return "polygon is not valid"
    if not poly.is_simple:
        return "polygon is not simple"

    rings = [exterior] + list(holes)
    for ring in rings:
        n = len(ring)
        for i in range(n):
            a, b = ring[i], ring[(i + 1) % n]
            if math.hypot(b[0] - a[0], b[1] - a[1]) < MIN_EDGE_LENGTH:
                return "edge shorter than {}".format(MIN_EDGE_LENGTH)

    for ri, ring_v in enumerate(rings):
        for vi, v in enumerate(ring_v):
            for rj, ring_e in enumerate(rings):
                n = len(ring_e)
                for ei in range(n):
                    if ri == rj and (ei == vi or ei == (vi - 1) % n):
                        continue  # edge incident to the vertex
                    a, b = ring_e[ei], ring_e[(ei + 1) % n]
                    d = _point_segment_distance(v[0], v[1], a[0], a[1], b[0], b[1])
                    if d < MIN_VERTEX_EDGE_CLEARANCE:
                        return "vertex within {} of a non-adjacent edge".format(
                            MIN_VERTEX_EDGE_CLEARANCE
                        )

    if geom.point_set_diameter(exterior) > diameter_cap:
        return "point-set diameter above {:.3f}".format(diameter_cap)
    return None


def _build_exterior(st, tier, target_area, scale, diameter_cap):
    """Draw one exterior whose finished form passes every gate."""
    kind = draw_kind(st, tier)
    for tries in range(MAX_SHAPE_TRIES):
        ring = _draw_ring(st, kind, tries)
        if not ring or len(ring) < 3:
            continue
        try:
            ring = _normalise_area(geom.ensure_ccw(ring), target_area)
        except GenerationError:
            continue
        ext, _ = finalise_rings(ring, [], scale)
        if gate_failure(ext, [], diameter_cap) is not None:
            continue
        if tier >= 2:
            poly = Polygon(ext)
            if poly.area > MAX_CONVEXITY * poly.convex_hull.area:
                continue  # tiers 2 and 3 promise concave parts
        return ring
    raise GenerationError(
        "no {} shape passed the gates in {} tries (tier {}, area {:.1f})".format(
            kind, MAX_SHAPE_TRIES, tier, target_area
        )
    )


# --------------------------------------------------------------------------
# Holes (tier 3)
# --------------------------------------------------------------------------


def _inscribed_center(poly):
    """Centre and radius of the largest circle inscribed in ``poly``.

    Shapely (GEOS) is the oracle here: it only *chooses* a location, and the
    centre is rounded to 3 decimals before any emitted coordinate is derived
    from it, so the hole ring itself is built in pure Python.
    """
    if _shapely_mic is not None:
        line = _shapely_mic(poly, tolerance=MIC_TOLERANCE)
        if line.is_empty:
            return None
        cx, cy = line.coords[0]
        return _r3(cx), _r3(cy), line.length
    sys.stderr.write(
        "generate.py: shapely has no maximum_inscribed_circle (needs 2.1); "
        "falling back to a grid search, which places tier-3 holes elsewhere "
        "and will NOT reproduce the committed instances byte for byte\n"
    )
    return _inscribed_center_fallback(poly)


def _inscribed_center_fallback(poly, grid=24, refinements=6):
    """Deterministic grid search, used only on Shapely releases without
    ``maximum_inscribed_circle``."""
    minx, miny, maxx, maxy = poly.bounds
    boundary = poly.boundary
    best = None
    step_x = (maxx - minx) / (grid + 1)
    step_y = (maxy - miny) / (grid + 1)
    for i in range(1, grid + 1):
        for j in range(1, grid + 1):
            p = Point(minx + i * step_x, miny + j * step_y)
            if not poly.contains(p):
                continue
            d = boundary.distance(p)
            if best is None or d > best[2]:
                best = (p.x, p.y, d)
    if best is None:
        return None
    for _ in range(refinements):
        step_x *= 0.5
        step_y *= 0.5
        cx, cy, cd = best
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                p = Point(cx + dx * step_x, cy + dy * step_y)
                if not poly.contains(p):
                    continue
                d = boundary.distance(p)
                if d > cd:
                    best = (p.x, p.y, d)
                    cd = d
    return _r3(best[0]), _r3(best[1]), best[2]


def _eroded(exterior, holes):
    """``Polygon(exterior, holes).buffer(-HOLE_WALL)`` -- the legal hole region.

    Eroding the host *with* the holes placed so far is what keeps distinct
    holes at least ``HOLE_WALL`` apart, for free.
    """
    poly = Polygon(exterior, holes)
    if not poly.is_valid:
        return None
    room = poly.buffer(-HOLE_WALL)
    return None if room.is_empty else room


def _fit_hole_radius(part_ring):
    """Circumradius of the octagonal hole that swallows ``part_ring``.

    The part, rotated about its bounding-box centre, never leaves the disc of
    radius ``R_p`` around that centre, so a regular hole whose *inradius*
    ``R_h * cos(pi / n)`` exceeds ``R_p`` by a margin contains it at every
    angle.  ``HOLE_FIT_FACTOR`` is the plan's floor; the inradius term is what
    actually makes the sweep pass.
    """
    r_part = _circumradius(part_ring)
    cos_half = math.cos(math.pi / FIT_HOLE_SIDES)
    radius = max(HOLE_FIT_FACTOR * r_part, (r_part + FIT_INRADIUS_MARGIN) / cos_half)
    return radius, r_part


def _regular_area(radius, sides):
    return 0.5 * sides * radius * radius * math.sin(2.0 * math.pi / sides)


def _fit_feasible(exterior, part_ring, diameter_cap):
    """Would the fit hole for ``part_ring`` be accepted by this exterior?

    Checked before any hole is committed so that the three fit pairs can be
    assigned to hosts that will actually keep them.
    """
    radius, r_part = _fit_hole_radius(part_ring)
    if radius * math.cos(math.pi / FIT_HOLE_SIDES) - r_part < 2.0:
        return False
    hole_area = _regular_area(radius, FIT_HOLE_SIDES)
    exterior_area = abs(geom.signed_area(exterior))
    if hole_area > MAX_HOLE_AREA_FRACTION * exterior_area:
        return False
    growth = math.sqrt(exterior_area / (exterior_area - hole_area))
    if geom.point_set_diameter(exterior) * growth > diameter_cap:
        return False
    spot = _inscribed_center(Polygon(exterior))
    return spot is not None and spot[2] >= radius + HOLE_WALL


def _fit_hole_ring(st, exterior, holes, part_ring):
    """Build the octagonal hole sized around ``part_ring`` at the widest spot."""
    radius, r_part = _fit_hole_radius(part_ring)
    phase = st.uniform(0.0, 2.0 * math.pi / FIT_HOLE_SIDES)
    if radius * math.cos(math.pi / FIT_HOLE_SIDES) - r_part < 2.0:
        return None
    spot = _inscribed_center(Polygon(exterior, holes))
    if spot is None:
        return None
    cx, cy, room = spot
    if room < radius + HOLE_WALL:
        return None
    # An even vertex count makes the ring centrally symmetric, so its
    # bounding-box centre is exactly (cx, cy) -- which is what lets the sweep
    # line the two bounding-box centres up and rely on the inradius argument.
    return _regular_ring((cx, cy), radius, FIT_HOLE_SIDES, phase)


def _plain_hole_ring(st, exterior, holes):
    """A convex, slightly irregular hole placed at the widest spot left."""
    spot = _inscribed_center(Polygon(exterior, holes))
    if spot is None:
        return None
    cx, cy, room = spot
    usable = room - HOLE_WALL
    if usable <= 0:
        return None
    sides = st.randint(4, 8)
    phase = st.uniform(0.0, 2.0 * math.pi / sides)
    radius = st.uniform(0.30, 0.60) * usable
    if radius < 20.0:
        return None
    # Equal angular spacing with radii within [0.88, 1.0] stays convex for
    # every vertex count used here.
    radii = [radius * st.uniform(0.88, 1.0) for _ in range(sides)]
    return _regular_ring((cx, cy), radius, sides, phase, radii=radii)


def _accept_hole(exterior, holes, candidate, exterior_area):
    """Is ``candidate`` a legal extra hole for this host?"""
    if candidate is None:
        return False
    hole = Polygon(candidate)
    if not hole.is_valid or hole.area <= 0:
        return False
    used = sum(abs(geom.signed_area(h)) for h in holes)
    if used + hole.area > MAX_HOLE_AREA_FRACTION * exterior_area:
        return False
    room = _eroded(exterior, holes)
    if room is None:
        return False
    return room.contains(hole)


def _punch_holes(st, part, fit_ring, diameter_cap):
    """Give one host its holes and renormalise it back to its target net area.

    Returns ``(exterior, holes, fitted)``; ``fitted`` says whether the
    requested fit hole survived.  Only holes are ever revised here: on a gate
    failure the last hole is dropped, never the exterior.
    """
    exterior = part["exterior"]
    exterior_area = abs(geom.signed_area(exterior))
    target_net = part["target_net"]
    wanted = st.randint(1, 2)

    holes = []
    fitted = False
    for slot in range(wanted):
        if slot == 0 and fit_ring is not None:
            candidate = _fit_hole_ring(st, exterior, holes, fit_ring)
            if _accept_hole(exterior, holes, candidate, exterior_area):
                holes.append(geom.ensure_cw(candidate))
                fitted = True
                continue
            # fall through and try an ordinary hole in the same slot
        candidate = _plain_hole_ring(st, exterior, holes)
        if _accept_hole(exterior, holes, candidate, exterior_area):
            holes.append(geom.ensure_cw(candidate))

    while holes:
        hole_area = sum(abs(geom.signed_area(h)) for h in holes)
        net = exterior_area - hole_area
        if net > 0:
            factor = math.sqrt(target_net / net)
            ext, hls = finalise_rings(
                _scale_ring(exterior, factor),
                [_scale_ring(h, factor) for h in holes],
                1.0,
            )
            if gate_failure(ext, hls, diameter_cap) is None:
                return ext, hls, fitted
        # The fit hole is always hole 0, so it is the last one to go.
        holes.pop()
        if not holes:
            fitted = False
    return part["exterior"], [], False


# --------------------------------------------------------------------------
# The hole-fit property (importable so the tests cannot drift from the tool)
# --------------------------------------------------------------------------


def part_fits_in_hole(part, hole_ring, step_deg=SWEEP_STEP_DEG):
    """Does ``part`` drop into ``hole_ring`` at some multiple of ``step_deg``?

    The part is rotated about its bounding-box centre and its bounding-box
    centre is translated onto the hole's; the hole is eroded by
    ``SWEEP_EROSION`` so a fit means real clearance, not a boundary graze.
    """
    hole = Polygon(hole_ring)
    if not hole.is_valid or hole.is_empty:
        return False
    room = hole.buffer(-SWEEP_EROSION)
    if room.is_empty:
        return False
    poly = geom.part_polygon(part)
    cx, cy = _bbox_center(part["exterior"])
    hx, hy = _bbox_center(hole_ring)
    for step in range(int(360 // step_deg)):
        angle = step * step_deg
        theta = math.radians(angle)
        c, s = math.cos(theta), math.sin(theta)
        tx = hx - (c * cx - s * cy)
        ty = hy - (s * cx + c * cy)
        if room.contains(geom.transform_polygon(poly, (tx, ty), angle)):
            return True
    return False


def fitting_pairs(instance, step_deg=SWEEP_STEP_DEG):
    """Every ``(part_id, host_id, hole_index)`` where the part fits the hole.

    Cheap filters first (area, then bounding-circle radius against the hole's
    largest radius) so the sweep only runs on plausible pairs.
    """
    pairs = []
    holes = []
    for host in instance["parts"]:
        for index, ring in enumerate(host.get("holes") or []):
            area = abs(geom.signed_area(ring))
            center = _bbox_center(ring)
            holes.append((host["id"], index, ring, area, _circumradius(ring, center)))
    if not holes:
        return pairs
    for part in instance["parts"]:
        part_area = geom.part_area(part)
        part_radius = _circumradius(part["exterior"])
        for host_id, index, ring, area, radius in holes:
            if part["id"] == host_id or part_area >= area or part_radius > radius:
                continue
            if part_fits_in_hole(part, ring, step_deg=step_deg):
                pairs.append((part["id"], host_id, index))
    return pairs


# --------------------------------------------------------------------------
# Instance assembly
# --------------------------------------------------------------------------


def _band_plan(st, parts):
    """Size band per part index: 25% large, 25% small, the rest medium."""
    n_large = int(round(0.25 * parts))
    n_small = int(round(0.25 * parts))
    n_medium = parts - n_large - n_small
    if n_medium < 0:
        n_medium = 0
        n_large = min(n_large, parts)
        n_small = parts - n_large
    bands = ["large"] * n_large + ["medium"] * n_medium + ["small"] * n_small
    return st.permuted(bands)


def _build_attempt(tier, seed, parts, strip_width, attempt):
    """One full generation attempt; returns ``(parts_list, pairs)``."""
    st = Stream(seed_key(tier, seed, parts, attempt))

    target_total = st.uniform(TARGET_AREA_MIN, TARGET_AREA_MAX) * (
        parts / float(DEFAULT_PARTS)
    )
    bands = _band_plan(st, parts)
    targets = [st.uniform(*BAND_RANGES[band]) for band in bands]

    diameter_cap = DIAMETER_FRACTION * strip_width
    exterior_cap = diameter_cap * (PRE_HOLE_DIAMETER_MARGIN if tier == 3 else 1.0)

    # Stage 2: the global scale is a fixed point, so shapes can be gated at it.
    scale = math.sqrt(target_total / sum(targets))

    # Stage 3: build, then re-solve the scale and re-check until stable.
    raw = [
        _build_exterior(st, tier, targets[i], scale, exterior_cap) for i in range(parts)
    ]
    finished = None
    for _ in range(MAX_OUTER_ITERS):
        scale = math.sqrt(target_total / sum(abs(geom.signed_area(r)) for r in raw))
        finished = [finalise_rings(r, [], scale)[0] for r in raw]
        bad = [
            i
            for i, ext in enumerate(finished)
            if gate_failure(ext, [], exterior_cap) is not None
        ]
        if not bad:
            break
        for i in bad:
            raw[i] = _build_exterior(st, tier, targets[i], scale, exterior_cap)
    else:
        raise GenerationError(
            "the global scale did not settle within {} iterations".format(MAX_OUTER_ITERS)
        )

    out = [
        {
            "id": "p{:03d}".format(i + 1),
            "exterior": finished[i],
            "holes": [],
            "band": bands[i],
            "target_net": targets[i] * scale * scale,
        }
        for i in range(parts)
    ]

    if tier == 3:
        _add_holes(st, out, diameter_cap)

    instance_parts = [
        {"id": p["id"], "exterior": p["exterior"], "holes": p["holes"]} for p in out
    ]
    pairs = fitting_pairs({"parts": instance_parts}) if tier == 3 else []
    return instance_parts, pairs


def _add_holes(st, out, diameter_cap):
    """Stage 4: punch holes into ~30% of the medium/large parts."""
    pool = [i for i, p in enumerate(out) if p["band"] != "small"]
    smalls = [i for i, p in enumerate(out) if p["band"] == "small"]
    n_hosts = int(round(HOLE_HOST_FRACTION * len(pool)))
    n_hosts = max(0, min(n_hosts, len(pool)))

    # The fit holes are built around the tightest small parts; each is given
    # the roomiest part in the pool that can demonstrably keep it (area
    # budget, diameter budget after renormalisation, and enough inscribed
    # room), so the by-construction guarantee does not depend on luck.  The
    # rest of the ~30% quota is then filled at random from what is left.
    partners = sorted(smalls, key=lambda i: (_circumradius(out[i]["exterior"]), i))
    partners = partners[:FIT_PAIRS_REQUIRED]
    by_room = sorted(pool, key=lambda i: (-abs(geom.signed_area(out[i]["exterior"])), i))
    assignment = {}
    for partner in partners:
        if len(assignment) >= n_hosts:
            break
        ring = out[partner]["exterior"]
        for host in by_room:
            if host in assignment:
                continue
            if _fit_feasible(out[host]["exterior"], ring, diameter_cap):
                assignment[host] = ring
                break

    rest = [i for i in pool if i not in assignment]
    hosts = sorted(set(assignment) | set(st.subset(rest, n_hosts - len(assignment))))

    for host in hosts:
        ext, holes, _ = _punch_holes(st, out[host], assignment.get(host), diameter_cap)
        out[host]["exterior"] = ext
        out[host]["holes"] = holes


def generate_instance(tier, seed, instance_id, parts=DEFAULT_PARTS, strip_width=None):
    """Build one instance dict.  Deterministic in ``(tier, seed, parts)``."""
    if tier not in (1, 2, 3):
        raise ValueError("tier must be 1, 2 or 3")
    if parts < 1:
        raise ValueError("parts must be at least 1")
    width = geom.DEFAULT_STRIP_WIDTH if strip_width is None else float(strip_width)
    if width <= 0:
        raise ValueError("strip width must be positive")

    for attempt in range(MAX_GEN_ATTEMPTS):
        part_list, pairs = _build_attempt(tier, seed, parts, width, attempt)
        if tier == 3:
            distinct = {(host, index) for _, host, index in pairs}
            if len(pairs) < FIT_PAIRS_REQUIRED or len(distinct) < FIT_HOLES_REQUIRED:
                continue  # stage 5: bump the attempt counter and rebuild
        return {
            "instance_id": instance_id,
            "challenge": geom.CHALLENGE_ID,
            "tier": tier,
            "seed": seed,
            "strip_width": width,
            "rotations_allowed": "free",
            "parts": part_list,
            "generator": {"version": GENERATOR_VERSION, "parts": parts},
        }, pairs
    raise GenerationError(
        "tier 3 hole-fit property not met after {} attempts".format(MAX_GEN_ATTEMPTS)
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        prog="generate.py",
        description="Generate one deterministic c001 nesting instance.",
    )
    parser.add_argument("--tier", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", required=True, help="output JSON path")
    parser.add_argument("--id", required=True, dest="instance_id", help="instance_id")
    parser.add_argument("--parts", type=int, default=DEFAULT_PARTS)
    parser.add_argument("--strip-width", type=float, default=geom.DEFAULT_STRIP_WIDTH)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    started = time.time()
    try:
        instance, pairs = generate_instance(
            args.tier, args.seed, args.instance_id, args.parts, args.strip_width
        )
    except (GenerationError, ValueError, OSError) as err:
        sys.stderr.write("generate.py: {}\n".format(err))
        return 2

    geom.write_json(instance, args.out)

    areas = [geom.part_area(p) for p in instance["parts"]]
    sys.stderr.write(
        "{}  parts={}  total_area={:.1f}  min_part={:.1f}  max_part={:.1f}  "
        "fitting_pairs={}  {:.1f}s\n".format(
            instance["instance_id"],
            len(instance["parts"]),
            sum(areas),
            min(areas),
            max(areas),
            len(pairs),
            time.time() - started,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
