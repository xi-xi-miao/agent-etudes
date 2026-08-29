# HANDOFF — Challenge c001: Irregular Shape Nesting

**Audience:** a coding agent building the challenge infrastructure inside the `agent-etudes` repository (see the main handoff, `HANDOFF.md`, for repo context).
**Goal:** implement everything under `challenge/` — instance generator, validator, renderer, gallery, baseline solver, and the participant-facing challenge statement — for étude no. 1, the first round of the lab.
**Not in scope:** any participant solver, any leaderboard/ranking output, any web viewer.

---

## 1. The challenge in one paragraph (participant-facing summary)

You are given a strip of material of fixed width and unbounded length, and a set of irregular polygonal parts. Write a solver that places **every** part on the strip — translated and rotated, no overlaps, nothing outside the strip — while **minimizing the length of material used**. Quality is measured as **utilization**: total part area ÷ (strip width × used length). A valid layout is instantly visible as an SVG; a better layout has visibly less whitespace and a higher utilization number. Naive bounding-box packing reaches roughly 45–55% within the first hour; the interesting work is climbing from there toward 80%+ through real computational geometry and optimization — a domain most participants won't know, which is the point.

## 2. Fixed design decisions (constraints — do not change)

1. **Objective:** maximize utilization; report to one decimal place. No other score exists.
2. **Tiers, not ranks.** Tier 1: convex parts. Tier 2: concave (simple) parts. Tier 3: parts may contain holes, and placing parts inside other parts' holes is allowed and profitable. Tiers are personal rungs; tooling never compares participants.
3. **Runtime rule:** ≤ 60 seconds wall-clock per instance on the participant's own machine, single process, honor system. The solver CLI must accept `--time-budget SECONDS` and respect it.
4. **Allowed:** any language; any general-purpose libraries, including geometry libraries (Shapely, Clipper, CGAL bindings, …) and generic optimization libraries (SciPy, OR-Tools CP-SAT, SAT/ILP solvers). Web research allowed and encouraged.
5. **Banned:** purpose-built irregular-nesting software or ports of it (e.g. SVGnest, Deepnest, libnest2d/nest2D, commercial nesting tools). The line: primitives and generic solvers yes, ready-made nesting pipelines no.
6. **No flips/mirroring** of parts (material has a face side). Rotations are free (any real angle) in all tiers.
7. **Contamination control:** instances come from a seeded generator. Dev instances are committed; hidden instances use secret seeds published only after the round closes, then every participant runs their own solver on them locally and commits the solutions.
8. Everything must run offline on a laptop; Python 3.11+, stdlib + PyYAML + Shapely for organizer tooling.

## 3. Geometry conventions (authoritative — used by all formats and tools)

- 2D Cartesian, floating point. Units are abstract.
- The strip occupies `0 ≤ y ≤ W` (width `W`) and `x ≥ 0`, extending unboundedly in +x.
- **Used length** `L` = the maximum x-coordinate over all vertices of all placed parts. **Utilization** = Σ(part areas) / (W × L). Part area includes holes subtracted.
- A polygon is a list of `[x, y]` vertices, implicitly closed (first vertex NOT repeated at the end), simple (no self-intersection). Exterior rings are counter-clockwise; hole rings are clockwise.
- Parts are defined in local coordinates with their axis-aligned bounding-box minimum at the local origin `(0, 0)`.
- **Placement transform:** rotate the part counter-clockwise by `rotation_deg` about the local origin `(0,0)`, **then** translate by `[tx, ty]`. Exactly this order.

## 4. File formats

### 4.1 Instance (`challenge/instances/dev/<instance_id>.json`)

```json
{
  "instance_id": "c001-t1-dev-01",
  "challenge": "c001",
  "tier": 1,
  "seed": 424242,
  "strip_width": 1000.0,
  "rotations_allowed": "free",
  "parts": [
    {
      "id": "p001",
      "exterior": [[0.0, 0.0], [120.4, 3.2], [95.1, 88.7]],
      "holes": []
    }
  ]
}
```

- `rotations_allowed` is `"free"` for c001; the field exists for future rounds (a list of allowed degrees). The validator must enforce it when it is a list.
- Every part has a unique `id`; duplicated shapes appear as separate entries with distinct ids. No quantity field.
- `holes` is always present; empty except in tier 3.

### 4.2 Solution (`solutions/<instance_id>.json` on the participant's branch)

```json
{
  "instance_id": "c001-t1-dev-01",
  "solver": {"name": "alice-nester", "version": "0.3", "seed": 7},
  "placements": [
    {"part_id": "p001", "translation": [412.0, 96.5], "rotation_deg": 37.5}
  ]
}
```

- Exactly one placement per part id in the instance; missing, duplicate, or unknown ids are validation errors.
- `solver` block is informational and optional.

## 5. Validator — `challenge/tools/validate.py`

CLI: `validate.py <instance.json> <solution.json> [--svg out.svg] [--json]`

Checks, in order, each producing a specific error message:

1. **Schema:** files parse; required fields present; placement set matches part ids exactly (bijection).
2. **Rotation constraint:** if `rotations_allowed` is a list, each `rotation_deg` ∈ list (mod 360, tolerance 1e-6°).
3. **Containment:** for each transformed part, the area lying outside the strip region `[0, ∞) × [0, W]` must be ≤ `TOL_AREA`.
4. **Non-overlap:** for each pair of transformed parts, `area(intersection)` ≤ `TOL_AREA`. Part interiors count; one part fully inside another's *hole* is legal (implement parts as Shapely polygons with holes, so this falls out naturally).
5. **Simplicity:** each transformed polygon must remain valid per Shapely (`.is_valid`); instance polygons are guaranteed valid by the generator.

- `TOL_AREA = 0.01` square units (constant, documented in the participant README; strip width is 1000, typical part areas are 10³–10⁵, so this permits only hairline boundary contact effects, not real overlap).
- Output on success: `VALID  used_length=<L>  utilization=<pp.p>%` plus a per-instance one-line JSON with `--json`. On failure: `INVALID` with every violation listed (pair ids, overlap area, out-of-strip area). Exit code 0 only when valid.
- Performance target: ≤ 5 s for 60 parts (use STRtree for the pairwise stage).

## 6. Generator — `challenge/tools/generate.py`

CLI: `generate.py --tier {1,2,3} --seed N --out FILE [--parts K]`

Deterministic given `(tier, seed, parts)`. Requirements:

- Default `K = 40` parts per instance, all tiers.
- **Tier 1 (convex):** random convex polygons (convex hull of random point clouds), 3–10 vertices, mixed size distribution: ~25% large (area 3–6·10⁴), ~50% medium (0.8–3·10⁴), ~25% small (0.1–0.8·10⁴). Small parts make gap-filling rewarding.
- **Tier 2 (concave):** simple concave polygons — generate via convex base then carve 1–3 notches, plus L/T/U-style orthogonal pieces and star-like shapes; guarantee simplicity (validate with Shapely, regenerate on failure).
- **Tier 3 (holes):** tier-2 shapes where ~30% of medium/large parts get 1–2 convex holes, sized so that at least a few small parts genuinely fit inside some holes (verify this property during generation: for ≥ 3 (hole, small-part) pairs, the small part fits in the hole at some rotation — a coarse rotation sweep is fine).
- Every part's minimum-width over rotations must be ≤ `0.85 × strip_width` (guaranteed placeable). Enforce by capping the bounding-circle diameter at 850.
- Total part area per instance ≈ 2.0–3.0 ·10⁶ (so a perfect layout would use length 2000–3000).
- Write instances for the dev set: tiers 1–3 × 5 seeds each = 15 files under `challenge/instances/dev/`, seeds `1001–1005`, `2001–2005`, `3001–3005`, ids `c001-t<T>-dev-<NN>`.
- **Hidden set:** do NOT generate or commit. Provide `challenge/tools/make_hidden.sh` that reads seeds from an env var / untracked file and documents the post-round protocol (organizer publishes seeds → everyone generates identical instances locally → runs own solver → commits `solutions/hidden/`).

## 7. Renderer & gallery

### 7.1 `challenge/tools/render.py`
CLI: `render.py <instance.json> [<solution.json>] --out FILE.svg`

- Instance-only mode: parts laid out in a grid (a "parts catalog" view).
- Solution mode: strip outline, a vertical line at `used_length`, parts filled (categorical palette, 60% opacity, thin dark stroke), holes visibly punched out, part ids as tiny labels toggleable via `--labels`.
- Header text in the SVG: instance id, utilization %, used length. Nothing else — no participant comparison.

### 7.2 `challenge/tools/gallery.py`
CLI: `gallery.py <solution_dir_or_results_glob> --out gallery.html`

- One self-contained HTML page embedding the SVGs side by side, grouped **by instance** (so different attempts at the same instance sit next to each other), captioned with participant/attempt/utilization, ordered alphabetically. This is the retro's centerpiece. No sorting by utilization, no medals, no aggregate table.

## 8. Baseline solver — `challenge/tools/baseline.py`

Purpose: give "less good" a concrete face on day one, and prove the formats end-to-end.

- Algorithm: axis-aligned bounding-box **shelf packing**, first-fit decreasing by bounding-box height, choosing per part the better of 0°/90°. Deliberately ignores true part geometry.
- CLI: `baseline.py <instance.json> --out <solution.json> [--time-budget 60] [--seed 0]` — same CLI shape participants must implement.
- Must produce VALID solutions on all 15 dev instances. Expected utilization: roughly 40–55%; document the actual numbers it achieves in `challenge/README.md` as the reference floor.

## 9. Participant-facing `challenge/README.md`

Rewrite the current placeholder with: the one-paragraph statement (§1), rules (§2), geometry conventions and formats (§3–4, abridged with a link to this handoff for the full spec), how to run validator/renderer/baseline, the dev/hidden protocol, and:

- **Solver CLI contract:** `solve <instance.json> --out <solution.json> --time-budget 60 [--seed N]`, any language, invocation documented in the participant's `solver/README.md`.
- **Checkpoint convention:** participants are encouraged to commit `solutions/` + rendered SVGs at milestones during the session, so the git timeline shows layout quality evolving — these are the "intermediate results" the lab exists to study.
- **Suggested decision-record triggers** (ties into `templates/decision-record.md`): geometry representation (exact polygons vs. rasterization); overlap machinery (no-fit polygon vs. pairwise intersection vs. raster masks); rotation handling (free vs. discretized, and at what granularity); placement heuristic (bottom-left family vs. best-fit vs. other); refinement strategy (none vs. local search vs. annealing vs. genetic); time-budget allocation across placement vs. refinement.
- **Background reading pointers** (agent: include as links, participants may read or not): the concept of the no-fit polygon; bottom-left placement heuristics; the ESICUP (EURO Special Interest Group on Cutting and Packing) community and datasets as the academic home of this problem family. Note explicitly that reading the literature is fair game — deciding *how deep to go* is itself an annotatable move.
- A short "what good looks like" section: two thumbnail SVGs, the baseline's layout vs. a visibly tighter hand-improved toy layout (agent: construct a tiny 6-part demo instance for this figure).

## 10. Repository additions

```
challenge/
├── README.md                    # participant-facing (rewritten per §9)
├── instances/
│   └── dev/                     # 15 committed instances
├── tools/
│   ├── generate.py
│   ├── validate.py
│   ├── render.py
│   ├── gallery.py
│   ├── baseline.py
│   └── make_hidden.sh
└── demo/                        # 6-part demo instance + the two figure SVGs
```

CI addition (extend `.github/workflows/ci.yml`): when a PR touches `solutions/**`, run the validator on each changed solution against its instance and post the utilization line as a check summary. Validation failures fail the check; utilization itself is informational only.

## 11. Acceptance criteria (verify before finishing)

1. `generate.py` is deterministic: same `(tier, seed)` twice → byte-identical instance JSON.
2. All 15 dev instances satisfy the structural guarantees of §6 (placeability cap, area range; tier-3 hole-fit property).
3. `baseline.py` produces solutions for all 15 dev instances; `validate.py` returns VALID on every one; utilizations are recorded in `challenge/README.md`.
4. Validator negative tests (as pytest fixtures): overlapping pair, part protruding past `y = W`, part at negative x, missing placement, duplicate placement, unknown part id, disallowed rotation when `rotations_allowed` is a list — each rejected with the specific error.
5. Validator positive edge test: two parts sharing an edge exactly (touching, not overlapping) → VALID; a small part placed fully inside a tier-3 hole → VALID.
6. `render.py` output opens as valid SVG; `gallery.py` on two solutions of the same instance produces one HTML with both, grouped by instance.
7. Round-trip: generate → baseline → validate → render works via a single documented `make demo` (or `demo.sh`).
8. Grep check: "leaderboard", "rank", "winner", "score" appear nowhere under `challenge/` (utilization is a "measure", not a "score").
9. `make_hidden.sh` refuses to run if the seeds file is tracked by git.

## 12. Open items (leave as TODOs in challenge/README.md)

- Round scheduling and the hidden-seed publication date (human decision).
- Whether tier 2/3 dev instances need difficulty calibration after first playtest — organizer should self-playtest one dev instance end-to-end (and annotate that session per `TAXONOMY.md`).
- Possible round-two variant: restricted rotation lists, or the metro-map layout challenge (kept in the drawer).
