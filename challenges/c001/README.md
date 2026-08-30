# Étude no. 1 — Irregular Shape Nesting (c001)

The étude's status is the `status:` field of [`challenge.yaml`](challenge.yaml) (`draft`, `open` or
`closed`; [`challenges/README.md`](../README.md) explains the three). The annotated tag
`c001-start` is frozen on `main` and every attempt branch forks from it.

The workflow around the étude — branch names, `session/`, annotating afterwards — is in
[CONTRIBUTING.md](../../CONTRIBUTING.md). This file is the position itself — and, after the
horizontal rule, the contracts of its tools.

## Start here

Fork your attempt branch from the start tag:

```sh
git fetch --tags
git switch -c attempt/c001/<participant>/1 c001-start
```

Run `uv sync --all-groups` once — the `c001` dependency group is where Shapely lives. Commands are
written from the repository root; every tool also runs from any other directory, since each
resolves its own imports.

The whole round trip — generate → baseline → validate → render, plus the dev-set table and a
gallery — doubles as the install check:

```sh
make demo CHALLENGE=c001            # or: bash challenges/c001/demo.sh [OUT_DIR]
```

Everything above the horizontal rule is what you need during the four hours; below it come the
tools' contracts.

## The challenge

You are given a strip of material of fixed width and unbounded length, and a set of irregular
polygonal parts. Write a solver that places **every** part on the strip — translated and rotated,
no overlaps, nothing outside the strip — while **minimizing the length of material used**. Quality
is measured as **utilization**: how much of the used strip is covered by parts, defined under
Geometry conventions. A valid layout is instantly visible as an SVG: a better layout has visibly
less whitespace and a higher utilization number. Naive bounding-box packing gets you to somewhere
around 45–50% in the first hour — that is what the baseline shipped here measures on the dev set
(its numbers are the table under The reference floor) — and the interesting work is climbing from
there toward 80%+ through real computational geometry and optimization, a domain most participants
will not know. That is the point of the étude.

## What good looks like

Six parts, a 200-wide strip, two layouts of the same instance:

| baseline — `tools/baseline.py` | hand-nested — `demo/demo-6.improved.json` |
|---|---|
| ![baseline layout of the 6-part demo instance](demo/baseline.svg) | ![hand-nested layout of the same six parts](demo/improved.svg) |
| used length 190.0 · utilization **59.5%** | used length 150.0 · utilization **75.3%** |

Same six parts, +15.8 percentage points, and you can see it without reading the number: the two
L-shapes interlock so their notches coincide, the square drops into the shared notch, and the
triangle is rotated to nest in the leftover column. That is the whole étude in one picture.

The hand-written inputs are `demo/demo-6.json` and `demo/demo-6.improved.json`; the two SVGs and
`demo/demo-6.baseline.json` are derived from them by `bash challenges/c001/demo.sh` and committed
so the figure renders here. Re-run the script after changing the inputs, the baseline or the
renderer; see [`demo/README.md`](demo/README.md).

## Rules

1. **Objective:** maximize utilization. Utilization is the only measure this étude produces;
   nothing here compares one participant against another.
2. **Tiers, not standings.** Tier 1: convex parts. Tier 2: concave (simple) parts. Tier 3: parts
   may contain holes, and placing parts inside other parts' holes is legal and profitable. Tiers
   are personal rungs — climb as far as you get to in your four hours.
3. **Runtime:** ≤ 60 seconds wall-clock per instance, on your own machine, single process, honour
   system: no distributed or multi-machine solving, and interpreter start-up does not count;
   threads inside that one process are fine, a multiprocessing pool across cores is not. Your
   solver must accept `--time-budget SECONDS` and respect it.
4. **Allowed:** any language; any general-purpose library, including geometry libraries (Shapely,
   Clipper, CGAL bindings, …) and generic optimization libraries (SciPy, OR-Tools CP-SAT, SAT/ILP
   solvers). Web research is allowed and encouraged.
5. **Banned:** purpose-built irregular-nesting software or ports of it (SVGnest, Deepnest,
   libnest2d / nest2D, commercial nesting tools). The line: primitives and generic solvers yes,
   ready-made nesting pipelines no. Importing or copying `challenges/c001/tools/` into your solver
   — the `geom.py` helpers, `baseline.py` — is allowed: they are primitives and a naive reference,
   not a nesting pipeline, and the ban is on purpose-built nesting software.
6. **No flips or mirroring** — the material has a face side. Rotation is free (any real angle) in
   all three tiers, subject to `rotations_allowed` (File formats → Instance).
7. **Contamination control:** instances come from a seeded generator. Dev instances are committed;
   hidden instances use secret seeds published only after the round closes (the protocol is under
   Dev instances, hidden instances, checkpoints).
8. Everything runs offline on a laptop. The organizer tooling is Python 3.11+, stdlib + PyYAML +
   Shapely.

## Geometry conventions

These conventions are shared by every format and every tool.

- 2D Cartesian, floating point. Units are abstract.
- The strip is the region `x ≥ 0`, `0 ≤ y ≤ W`, unbounded in `+x`. `W` is the instance's
  `strip_width` (1000.0 throughout the dev set).
- A **ring** is a list of `[x, y]` vertices, implicitly closed — the first vertex is not repeated —
  and simple. Exterior rings are counter-clockwise, hole rings clockwise.
- A **part** is one exterior ring plus zero or more hole rings, in local coordinates, with the
  axis-aligned bounding-box minimum of the exterior at the local origin `(0, 0)`.
- **Part area** is the exterior's absolute shoelace area minus each hole's.
- **Placement transform:** rotate the part counter-clockwise by `rotation_deg` about the local
  origin `(0, 0)`, **then** translate by `[tx, ty]`. Exactly that order. In Shapely this is one
  `affine_transform([cos, -sin, sin, cos, tx, ty])`; `shapely.affinity.rotate` defaults to the
  centroid and is not this transform.
- **Used length** `L` is the largest x-coordinate reached by any placed part.
- **Utilization** is `Σ part_area / (W × L)`, over **all** parts of the instance, clamped to
  `[0, 1]`, and `0.0` when `L ≤ 0`. It is formatted as a percentage with one decimal place.

## File formats

Files written by the tooling are canonical JSON: keys sorted, indent 2, one trailing newline.

### Instance

`instances/dev/<instance_id>.json`, read-only input, and after the round
`instances/hidden/<instance_id>.json`. The file stem is always the `instance_id`.

```json
{
  "challenge": "c001",
  "generator": {"parts": 40, "version": "1.0"},
  "instance_id": "c001-t1-dev-01",
  "parts": [
    {"exterior": [[0.0, 0.0], [120.4, 3.2], [95.1, 88.7]], "holes": [], "id": "p001"}
  ],
  "rotations_allowed": "free",
  "seed": 1001,
  "strip_width": 1000.0,
  "tier": 1
}
```

Loading (`geom.load_instance`) rejects a file that violates any of: `instance_id` and `challenge`
are non-empty strings; `tier` is 1, 2 or 3; `seed` is an integer; `strip_width` is a positive
finite number; `rotations_allowed` is either the string `"free"` or a list of finite numbers
(degrees); `parts` is a non-empty list; every part has a unique `id`, an `exterior` of at least
three `[x, y]` pairs, and a `holes` list (possibly empty) of such rings. Booleans and non-finite
numbers are rejected wherever a number is expected. Ring orientation, simplicity and the
local-origin normalisation of Geometry conventions are Generator guarantees, not load-time checks.

`rotations_allowed` is `"free"` for this étude; the field exists for future rounds, and the
validator enforces the list form when it is a list. `holes` is always present and empty outside
tier 3. Duplicate shapes appear as separate parts with distinct ids; there is no quantity field.
The `generator` block is informational, as is `solver` below.

### Solution

`solutions/<instance_id>.json` on your attempt branch — what you write — and
`solutions/hidden/<instance_id>.json` after the hidden round.

```json
{
  "instance_id": "c001-t1-dev-01",
  "placements": [
    {"part_id": "p001", "rotation_deg": 37.5, "translation": [412.0, 96.5]}
  ],
  "solver": {"name": "alice-nester", "seed": 7, "version": "0.3"}
}
```

Loading (`geom.load_solution`) requires a non-empty `instance_id`, a `placements` list, and in each
placement a non-empty `part_id`, a `translation` of exactly two finite numbers, and a finite
`rotation_deg`. `solver` is optional and must be an object when present. Cross-checking against an
instance is the validator's job, not the loader's.

## Running the tools

**Validate a layout** (the exit codes are under Validator contract → Exit codes and performance):

```sh
uv run python challenges/c001/tools/validate.py \
    challenges/c001/instances/dev/c001-t1-dev-01.json \
    solutions/c001-t1-dev-01.json --json --svg solutions/c001-t1-dev-01.svg
```

It prints one human line, `VALID  used_length=4800.621  utilization=44.6%`. `--json` appends a
machine-readable object as the last stdout line — this is what CI echoes; its keys and their
semantics are under Validator contract → Output.

`--svg FILE` renders the layout while validating, and `--labels` puts part ids on that SVG
(without `--svg` it is ignored).

**Render** — omit the solution for a parts-catalog view of the instance:

```sh
uv run python challenges/c001/tools/render.py <instance.json> [<solution.json>] --out FILE.svg [--labels]
```

**Baseline solver** — the reference floor, and a working example of the solver CLI:

```sh
uv run python challenges/c001/tools/baseline.py <instance.json> --out FILE.json \
    [--time-budget 60] [--seed 0] [--quiet]
```

**Gallery** — one self-contained HTML page, grouped by instance, alphabetical inside a group.
Accepts files, directories or globs:

```sh
uv run python challenges/c001/tools/gallery.py build/c001-demo/dev --out gallery.html \
    [--instances-dir challenges/c001/instances/dev]
```

**Generator** — you rarely need it during a session; it is how the hidden instances get reproduced
from published seeds:

```sh
uv run python challenges/c001/tools/generate.py --tier 1 --seed 4242 --id c001-t1-demo-01 \
    --out /tmp/c001-t1-demo-01.json [--parts 40] [--strip-width 1000]
```

## Your solver

```
solve <instance.json> --out <solution.json> --time-budget 60 [--seed N]
```

Any language. Document the actual invocation (build step, interpreter, entry point) in
`solver/README.md` on your attempt branch — the shared tooling never runs your solver, but the
common shape is what makes two sessions comparable. `--time-budget SECONDS` is the runtime rule of
the round and must be honoured; `--seed N` exists so that one run can be reproduced.
`tools/baseline.py` implements this contract and is worth reading once.

## Dev instances, hidden instances, checkpoints

- **`instances/dev/`** — what you solve during the session; write each layout to
  `solutions/<instance_id>.json` on your branch. The seeds and the id pattern are under Dev set and
  hidden set.
- **`instances/hidden/`** — empty while the round is open. The organizer picks the seeds before the
  round and keeps them secret; when the round closes, one pull request commits the seed list as
  `published-seeds.txt` and the generated instances under `instances/hidden/`, and flips
  `challenge.yaml` to `status: closed`. Everybody then regenerates the identical instances locally,
  checks them byte for byte against the committed ones, runs their own unchanged solver under the
  same 60-second rule, and commits `solutions/hidden/`. No solver ever runs on anybody else's
  machine. `bash challenges/c001/tools/make_hidden.sh --help` spells out the protocol.
- **Checkpoints.** Commit `solutions/` **and the rendered SVGs** at milestones during the session —
  first valid layout, first refinement pass, the last thing that worked. Render each SVG beside its
  solution JSON with the same stem (`solutions/<instance_id>.svg`, `solutions/hidden/<instance_id>.svg`
  after the hidden round) — the collector keeps only those;
  [CONTRIBUTING.md](../../CONTRIBUTING.md) step 2 shows the tree. Those intermediate results are
  the material this lab exists to study: the git timeline should show layout quality evolving, not
  a single drop at the end.

## Decision records worth writing

Copy [`templates/decision-record.md`](../../templates/decision-record.md) into
`session/decisions/dr-00X.md`. This étude reliably produces at least these six decisions, all of
them in a domain most participants do not know:

- **Geometry representation** — exact polygons vs. rasterization.
- **Overlap machinery** — no-fit polygon vs. pairwise intersection vs. raster masks.
- **Rotation handling** — free angles vs. a discrete set, and at what granularity.
- **Placement heuristic** — the bottom-left family vs. best-fit vs. something else.
- **Refinement strategy** — none vs. local search vs. simulated annealing vs. genetic.
- **Time-budget allocation** — how the 60 seconds split between placement and refinement.

## Background reading

- **The no-fit polygon (NFP).** For an ordered pair of polygons, the set of translations of the
  second that make it touch the first without overlapping — its boundary. Precompute one per pair
  and per rotation, and "may I place B here?" collapses from a polygon intersection into a
  point-in-polygon test. It is the central data structure of the field and worth twenty minutes of
  searching before you write your own overlap test.
- **Bottom-left / bottom-left-fill placement.** Place parts one at a time, each pushed as far down
  and then as far left as it will go, in some order. Almost every published nesting heuristic is a
  variation on the ordering and the tie-breaks.
- **[ESICUP](https://www.euro-online.org/websites/esicup/)** — the EURO Special Interest Group on
  Cutting and Packing, the academic home of this problem family; its "Data sets" section holds the
  standard benchmark instances.
- Context, if the problem family is new to you:
  [cutting-stock problem](https://en.wikipedia.org/wiki/Cutting_stock_problem) and
  [packing problems](https://en.wikipedia.org/wiki/Packing_problems).

Reading the literature is explicitly fair game. Deciding **how deep to go** — and when to stop
reading and start building — is itself an annotatable move, and a good candidate for a
`TUTOR` / `OPTIONS` / `DEFER` trail with an honest confidence number at the end of it.

## The reference floor

`tools/baseline.py` packs bounding boxes into columns, deliberately blind to the parts' outlines —
the algorithm is under Baseline — and exists to give "less good" a concrete face on day one.
Measured by `make demo CHALLENGE=c001` over the 15 committed dev instances (`W = 1000`, 40 parts
each):

| instance | utilization % | used length |
| --- | ---: | ---: |
| c001-t1-dev-01 | 44.6 | 4800.621 |
| c001-t1-dev-02 | 50.9 | 4042.012 |
| c001-t1-dev-03 | 49.4 | 5306.030 |
| c001-t1-dev-04 | 46.8 | 6094.946 |
| c001-t1-dev-05 | 46.1 | 5770.301 |
| c001-t2-dev-01 | 45.2 | 5736.394 |
| c001-t2-dev-02 | 45.9 | 6398.147 |
| c001-t2-dev-03 | 51.0 | 5683.311 |
| c001-t2-dev-04 | 45.5 | 5371.729 |
| c001-t2-dev-05 | 47.6 | 4844.388 |
| c001-t3-dev-01 | 48.4 | 5324.295 |
| c001-t3-dev-02 | 48.7 | 6045.049 |
| c001-t3-dev-03 | 48.6 | 4948.623 |
| c001-t3-dev-04 | 48.4 | 4320.200 |
| c001-t3-dev-05 | 47.8 | 4229.758 |

Range 44.6–51.0%, mean 47.7%. Beating it is not the achievement — a solver that reasons about the
actual outlines should clear it comfortably in the first hour. The numbers come out of the demo
run; regenerate them there rather than editing this table by hand.

---

Everything below is the normative contract of the tools in [`tools/`](tools/), all built on
`geom.py`; you do not need it on day one. Where this text and a tool disagree, one of them has a
defect. Paths are relative to `challenges/c001/` unless they start with `challenges/`;
`solutions/`, `solver/` and `session/` sit at the root of your attempt branch.

## Validator contract

[`tools/validate.py`](tools/validate.py) — the invocation and its flags are under Running the
tools.

### Checks, in order

Every violation is collected and reported; only `SCHEMA` stops the run.

| # | Code | Condition |
|---|---|---|
| 1 | `SCHEMA` | Either file is unreadable, is not JSON, or fails File formats. **Fatal**: no further check runs, exit 2. |
| 2 | `INSTANCE_MISMATCH` | `solution.instance_id` differs from `instance.instance_id`. |
| 3 | `MISSING_PLACEMENT` | An instance part id has no placement. |
| 3 | `DUPLICATE_PLACEMENT` | An instance part id carries more than one placement. |
| 3 | `UNKNOWN_PART` | A placement names a part id the instance does not define. |
| 4 | `ROTATION_NOT_ALLOWED` | `rotations_allowed` is a list and a placement's angle is not in it, modulo 360° with a tolerance of 1e-6°. |
| 5 | `INVALID_GEOMETRY` | A transformed part is not a valid Shapely polygon. |
| 6 | `OUTSIDE_STRIP` | More than `TOL_AREA` of a transformed part lies outside `x ≥ 0`, `0 ≤ y ≤ W`. |
| 7 | `OVERLAP` | Two transformed parts intersect in more than `TOL_AREA` of area. |

The placement set must be a bijection onto the instance's part ids. When it is not, the geometry
stages (5–7) still run on what can be salvaged: for each known part id the **first** placement
carrying it, in instance part order, is the one transformed. A part reported as `INVALID_GEOMETRY`
is excluded from stages 6 and 7 and from `used_length`.

Because a part's interior excludes its holes, one part placed fully inside another part's hole
produces no `OVERLAP`, and two parts sharing an edge exactly produce none either: holes are real
holes, not decoration.

### Tolerance

`TOL_AREA = 0.01` square units (`geom.TOL_AREA`), applied **inclusively and per check** — not as a
budget spendable across a layout. Exactly 0.01 passes; only a strictly greater area is a violation.
`OUTSIDE_STRIP` is per part, `OVERLAP` is per pair. With `W = 1000` and part areas of 10³–10⁵ this
admits hairline boundary-contact effects and nothing else.

### Output

The human output is one headline — the `VALID …` line shown under Running the tools — then one
`CODE: message` line per violation. On failure the headline is the bare word `INVALID`, and each
violation follows, e.g. `OVERLAP: parts 'p003' and 'p017' overlap by 12.402011 area units`.

With `--json`, the last stdout line is exactly this object — seven keys, printed with keys sorted:

```json
{"errors": [], "instance_id": "c001-t1-dev-01",
 "measures": {"used_length": 4800.621, "utilization_pct": 44.6},
 "summary": "VALID  used_length=4800.621  utilization=44.6%",
 "used_length": 4800.621, "utilization_pct": 44.6, "valid": true}
```

`used_length` is rounded to three decimals, `utilization_pct` to one; the two top-level measures
repeat the two `measures` entries. `summary` is the line a consumer may echo verbatim, and on
failure it carries more than the printed headline does:
`"INVALID  2 violation(s): OUTSIDE_STRIP, OVERLAP"`. Each entry of `errors` is an object with
`code` and `message` plus code-specific detail: `file` (`SCHEMA`), `expected`/`actual`
(`INSTANCE_MISMATCH`), `part_id` (placement, rotation and geometry codes), `count`
(`DUPLICATE_PLACEMENT`), `rotation_deg`, `reason` (`INVALID_GEOMETRY`), `area` (`OUTSIDE_STRIP`),
`part_ids` and `area` (`OVERLAP`). The object is printed on exit 2 as well, with a best-effort
`instance_id` recovered from whichever file could be read.

Violation order is deterministic: grouped by check in the order above, instance part order within a
check, and `OVERLAP` sorted by the pair's ids. `UNKNOWN_PART` is the one exception to "instance part
order" — its ids are not instance parts, so they are reported in order of first appearance among the
solution's placements, each id once however many placements name it.

The two measures are only meaningful when `valid` is `true`. `used_length` spans just the parts
that were actually transformed, while utilization always divides by the total area of *every*
instance part, so an incomplete layout reports a shorter length and a flatteringly high
utilization. A consumer must gate on `valid` before reading either number.

### Exit codes and performance

`0` valid · `1` invalid · `2` unreadable or malformed input. The pairwise stage is indexed with a
Shapely `STRtree`; a 60-part instance validates in under 5 seconds, asserted by
`tests/test_validate.py`.

## Generator guarantees

In [`tools/generate.py`](tools/generate.py), `--id` is required and is written verbatim into
`instance_id`.

### Determinism

Every random draw comes from one `random.Random` seeded with the string
`"c001:<tier>:<seed>:<parts>"` (with `:<attempt>` appended once a regeneration attempt is needed,
see Tier-3 holes and the hole-fit property), and only `rng.random()` is ever called — never
`gauss`, `shuffle` or `choices`, whose internals may change between CPython releases. `--id` and
`--out` are labels and never touch the stream, so the same `(tier, seed, parts)` at the same
`--strip-width` always produces the same geometry, byte for byte. `--strip-width` is in the
determinism domain though not in the seed key: it sets the diameter cap, which decides which
candidate shapes are rejected. Hole centres (tier 3) are chosen by a pure-Python inscribed-circle
grid search rather than GEOS's `maximum_inscribed_circle`, so the output does not depend on the
Shapely/GEOS build either: the same command reproduces every tier on macOS, Linux and Windows.

Emitted coordinates are always computed with pure-Python vertex arithmetic. Shapely is used as an
oracle and as a measure — validity, intersection area, bounds — never as the source of a number
written into a file.

### Size mix and totals

At the default `K = 40` parts, each part is assigned a size band — 25% large, 50% medium, 25%
small — and a target net area drawn uniformly from that band. The bands are sized so that 40 parts
drawn that way sum to the instance total below:

| band | net area | share |
|---|---|---|
| large | 8–17·10⁴ | 25% |
| medium | 2–8·10⁴ | 50% |
| small | 0.3–2·10⁴ | 25% |

The instance's total net part area is drawn uniformly from `[2.0·10⁶, 3.0·10⁶]`, scaled by
`parts / 40` at other part counts, and is realised exactly by a single global scale factor. At
`W = 1000` a perfect layout would therefore use a length of 2000–3000.

**Placeability.** Every part's exterior has a point-set diameter of at most
`0.85 × strip_width` (850 in the dev set), measured after rounding to three decimals. The diameter
bounds every rotated extent, so every part provably fits the strip at some angle — and, since it
bounds both axis-aligned extents too, at 0° and 90° as well. In tier 3 the exterior is gated at
`0.92 ×` that cap before holes are punched, so the renormalisation under Tier-3 holes and the
hole-fit property cannot breach it.

**Post-rounding gates.** Every finished part is a valid, simple Shapely polygon; no edge is shorter
than 2.0 units; no vertex lies within 2.0 units of a non-adjacent edge. Rings are oriented per
Geometry conventions and rotated to start at their lexicographically smallest vertex, which is what
keeps regenerated files byte-identical.

### Tier families

- **Tier 1** — convex hulls of random point clouds drawn from a randomly oriented ellipse, reduced
  to 3–10 vertices.
- **Tier 2** — concave and simple, mixed 50% notched hulls (a convex base with 1–3 rectangular
  notches cut into its longest edges), 30% axis-aligned L/T/U pieces, 20% stars with 4–7 points.
- **Tier 3** — the tier-2 mix, plus holes (below).

Tiers 2 and 3 additionally gate on concavity: a part whose area exceeds 0.995 × its convex hull's
area is redrawn.

### Tier-3 holes and the hole-fit property

About 30% of the medium and large parts become hosts and receive 1–2 convex holes, each separated
from the rest of the boundary — and from any other hole — by at least 12 units of wall, and
consuming at most 14% of the host's exterior area. A host is then renormalised back to its target
net area, which may only shrink or drop holes, never alter an exterior.

The **hole-fit property** every tier-3 instance satisfies: at least **3** `(part, host, hole)`
triples exist in which the part drops fully inside the hole, spread over at least **2** distinct
holes. "Fits" means that, with bounding-box centres aligned, the part is contained in the hole
eroded by 1.0 unit at some multiple of 10°. It holds by construction — the fit holes are regular
octagons sized around the smallest small parts and assigned to hosts that can demonstrably keep
them — and is verified after generation by the importable `generate.fitting_pairs()`; a failure
regenerates the whole instance from a bumped attempt counter, up to 12 attempts, which keeps the
result deterministic.

### Dev set and hidden set

The dev set is 15 committed instances, tiers 1–3 × 5 seeds each: seeds `1001`–`1005`,
`2001`–`2005`, `3001`–`3005`, ids `c001-t<T>-dev-<NN>` where `<NN>` is the last two digits of the
seed. Every file is reproducible byte for byte; `tests/test_generate.py` asserts it.

Hidden instances are ids `c001-t<T>-hidden-<NN>`, `<NN>` counting from 01 within each tier in the
order the seeds are listed. They are built by [`tools/make_hidden.sh`](tools/make_hidden.sh), a loop
around `generate.py` that takes seeds from `--seeds-file FILE`, from `$HIDDEN_SEEDS`
(`"tier:seed,tier:seed,…"`), or from an untracked `hidden-seeds.txt`. The script refuses (exit 3) a
seeds file that git can see — tracked, staged, or not matched by an ignore rule — and equally one it
cannot check, i.e. a file that lies outside any git repository. Other exits are `0` ok, `1` generator
failure, `2` usage or malformed seeds (a bad tier, a non-numeric seed, a duplicate `tier:seed`, or no
entries at all). `$HIDDEN_SEEDS` is exempt from the file check, never having touched the disk.

The post-round protocol is under Dev instances, hidden instances, checkpoints; the command that
regenerates one committed dev file in place is in [`instances/README.md`](instances/README.md).

## Renderer and gallery contracts

[`tools/render.py`](tools/render.py). Without a solution it draws a parts catalog — every part in
its own grid cell, id underneath. With one it draws the strip outline, a dashed vertical line at
`used_length`, and every placed part filled from a 12-colour categorical palette at 60% opacity
with a thin dark stroke, holes punched out via `fill-rule="evenodd"`; `--labels` writes part ids
onto them. The header carries the instance id, the utilization and the used length, and nothing
else — no participant names, no comparison between attempts. Rendering is deliberately tolerant so
it stays useful for debugging: an unplaced part is not drawn and a placement naming an unknown part
id is ignored — `validate.py` is the tool that objects — but utilization is still computed over all
instance parts, so a partial layout renders with the same flatteringly high number the validator
would report, not an invented one.
Exit `0`, or `2` on unreadable input, an instance-id mismatch, or an unwritable output.

[`tools/gallery.py`](tools/gallery.py). Each path is a solution file, a directory (its `*.json`,
non-recursive), or a glob. The instance behind a solution is located by `instance_id`, searching
`--instances-dir` first, then `instances/dev`, then `instances/hidden`; a solution whose instance
cannot be found is skipped with a warning.

The page is one self-contained HTML file: one section per instance id in sorted order, one card per
solution inside a section — so two attempts at the same instance sit side by side. Cards are
alphabetical by label (`<participant> / attempt <n>` when the path lies under
`results/<cid>/<participant>/<n>/`, otherwise the file stem); the label is the sort key, so card
order never depends on utilization. Every utilization shown is recomputed from the instance and the
solution, never read out of a file, and there is no aggregate table and no medals. Provenance paths
are written relative to the working directory so the same tree yields the same page on every
machine. Exit `0` — including when nothing matched, which is only a warning — or `2` when the
output cannot be written.

## Baseline

[`tools/baseline.py`](tools/baseline.py) proves the formats end to end. It packs bounding boxes
into **vertical columns** and ignores the parts' true outlines:

1. For each part, keep the orientations among 0° and 90° whose y-extent fits `W`, and take the one
   with the smallest x-extent, ties going to the smaller y-extent. A part with no fitting
   orientation is an error — the diameter cap under Size mix and totals guarantees there always is
   one.
2. Sort by decreasing chosen x-extent, i.e. by column thickness.
3. First fit: drop each part into the leftmost open column with enough remaining y-room, stacking
   upward from `y = 0`; open a new column to the right of all of them when none has room. A
   column's thickness is fixed by its first part and step 2 guarantees no later part is thicker,
   so the layout cannot overlap.

`--time-budget` is accepted for CLI compatibility and never consulted — the algorithm is
deterministic and instant; `--seed` only travels into the solution's `solver` block; without
`--quiet` a summary line goes to stderr. Exit `0`, or `2` when the instance cannot be loaded or
packed. The baseline validates on all 15 dev instances, and its measured utilizations are the table
under [The reference floor](#the-reference-floor).

## Open items

- [ ] Round scheduling and the hidden-seed publication date — a human decision, not yet fixed.
- [ ] Whether the tier 2 and tier 3 dev instances need difficulty calibration — to be reviewed at
      the first retro; the position is frozen and playable now.
- [ ] A possible round-two variant: restricted rotation lists (`rotations_allowed` as a list of
      degrees — the validator already enforces that form), or the metro-map layout challenge that
      is being kept in the drawer.
