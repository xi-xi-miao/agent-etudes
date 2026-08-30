# Adding an étude

The contract every challenge directory must satisfy, as a checklist. The shared tooling in
`scripts/` is challenge-agnostic: it learns everything it needs from `challenges/<id>/challenge.yaml`
and from the CLI contracts below. Anything not in this contract is yours to design.

Machine-check your work at any point with:

```sh
uv run python scripts/check_challenge.py challenges/cXXX
```

Before that, read [challenges/README.md](../challenges/README.md) § *Design criteria for an étude* —
the contract makes a challenge *runnable*, the criteria make it *worth playing*.

---

## 1. Pick an id and create the directory

- [ ] The **challenge id** matches `^c[0-9]{3}$` and is the next free number. The directory name is
      the id and nothing else — no slug. The human-readable title lives in the manifest.
- [ ] Create the layout:

```
challenges/c002/
├── challenge.yaml           # the manifest (§2)
├── README.md                # participant-facing statement: rules, formats, how to run the tools
├── instances/
│   ├── dev/                 # committed instances, filename stem == instance_id
│   └── hidden/.gitkeep      # empty until the round closes (§8)
├── tools/                   # generator, validator, renderer, baseline, … organizer-side
├── tests/                   # pytest files for this challenge (§6)
├── demo/                    # tiny hand-made instance + figures used by demo.sh
└── demo.sh                  # end-to-end round trip (§7)
```

## 2. Write `challenge.yaml`

Every field is consumed by a script, and `check_challenge.py` **rejects unknown keys** — do not add
fields "for later".

```yaml
schema_version: 1
id: c002
number: 2
title: Some Memorable Title
status: draft
start_tag: c002-start
dependency_group: c002
solutions_glob: "solutions/**/*.json"
validate: "python tools/validate.py {instance} {solution} --json"
```

- [ ] `schema_version` — `1`. Bumped only when this contract changes.
- [ ] `id` — equals the directory name.
- [ ] `number` — the étude number, used verbatim in headings ("étude no. 2").
- [ ] `title` — the human-readable title, used in `challenges/README.md` and in tool output.
- [ ] `status` — `draft` | `open` | `closed`. `open` requires the start tag to exist; `closed`
      requires `instances/hidden/` to be non-empty. Start at `draft`.
- [ ] `start_tag` — the annotated tag every attempt branch forks from, conventionally `<id>-start`.
- [ ] `dependency_group` — *optional*; the uv dependency group carrying this challenge's extra
      libraries (§5). Omit it if stdlib and PyYAML are enough.
- [ ] `solutions_glob` — where solutions live **on the attempt branch**, relative to the repository
      root. CI uses it to decide whether a push needs validating, and `collect_results.py` uses it
      to find what to copy.
- [ ] `validate` — the command template below.

## 3. The validator contract

- [ ] `validate` is a command template run with **cwd = the challenge directory**, taken from
      `main` (never from the attempt branch — a participant cannot weaken their own validator).
- [ ] It contains the two placeholders `{instance}` and `{solution}`, which are substituted with
      paths before the command runs. Every tool the template names must exist under the challenge
      directory; `check_challenge.py` verifies this.
- [ ] **Instance resolution.** The runner reads `instance_id` from the solution JSON and looks for
      the unique `challenges/<id>/instances/*/<instance_id>.json`:
      - exactly one match → that file is `{instance}`;
      - zero matches → the solution is reported as a **skipped** row, never a failure. The usual
        reason is that the hidden set has not been published yet, and the runner cannot tell that
        apart from a typo in the id, so it refuses to fail the round over either; the tally line
        (`3 solutions: 2 valid, 1 skipped`) is what a human reads;
      - more than one match → an error, because nothing downstream is trustworthy.
      So every instance file's **filename stem must equal its `instance_id`**, and instance ids must
      be unique across `instances/dev/` and `instances/hidden/`.
- [ ] **The `--json` line contract.** The **last line of stdout** is a single JSON object:

  ```json
  {"valid": true, "summary": "VALID  used_length=2841.0  utilization=52.7%", "errors": [], "measures": {"utilization_pct": 52.7, "used_length": 2841.0}}
  ```

  - `valid` (bool, required) — did the solution pass every check.
  - `summary` (str, required) — one line, **posted verbatim** by CI. The shared tooling never
    formats or reformats measures itself, so put whatever a human should read right here.
  - `errors` (list, required, empty when valid) — objects with at least `code` and `message`;
    add whatever extra fields help (`part_id`, `area`, …). Use stable, greppable codes.
  - `measures` (object, optional) — `{name: number}` only. These are quantities, never a
    comparison between participants; the tooling stores and prints them, and nothing else.
  - Anything the validator wants to print for humans goes on **earlier** lines.
- [ ] **Exit codes:** `0` valid · `1` invalid · `2` input unreadable (missing file, bad JSON,
      unknown instance). CI distinguishes "your solution is wrong" from "the harness broke":
      `validate_solutions.py` reports exit `2` as an **error** row, never as `invalid`, whatever
      the JSON line says.

## 3b. The optional renderer

Not required, but the shared tooling uses it when it is there, so it has a fixed shape:

```
python tools/render.py <instance> <solution> --out <file.svg>
```

- [ ] `challenges/<id>/tools/render.py`, run with **cwd = the challenge directory**, writes one
      picture of one solution to `--out`. Anything else it accepts is yours to design.
- [ ] With that file present, `validate_solutions.py --render-dir DIR` renders every solution it
      checked, and CI uploads the result as a workflow artifact. Rendering is best-effort: a
      renderer that fails never changes the exit status.
- [ ] A gallery tool is optional too. `scripts/retro.py` runs
      `python tools/gallery.py <results glob> --out <file.html>` from the challenge directory when
      `tools/gallery.py` exists, so match that shape (and expand the glob yourself — it arrives
      quoted) if you want `make retro` to build a gallery.

## 4. The participant solver CLI

Document this in `challenges/<id>/README.md`; the shared tooling never invokes a participant's
solver, but everyone needs one common shape so a session is comparable to another.

```
solve <instance> --out <solution> --time-budget 60 [--seed N]
```

- [ ] Any language. The participant documents the actual invocation in their `solver/README.md`.
- [ ] `--time-budget SECONDS` must be honoured — it is the runtime rule of the round.
- [ ] `--seed N` exists so a run can be reproduced.
- [ ] Your own reference solver, `tools/baseline.py`, follows the same shape — and this one *is*
      invoked: `check_challenge.py` runs `python tools/baseline.py <instance> --out <solution>`
      from the challenge directory to prove the round trip still works. Every flag beyond
      `<instance>` and `--out` must therefore have a usable default.

## 5. Dependencies

- [ ] Extra libraries go in a **uv dependency group named after the challenge id** in
      `pyproject.toml`:

  ```toml
  [dependency-groups]
  c002 = ["some-library>=1.0"]
  ```

  There is no per-challenge `requirements.txt`. Name the group in the manifest's
  `dependency_group`. CI does not install groups one at a time: its validate-solutions job runs
  `uv sync --frozen --all-groups`, and so do the tests. Contributors get the same with
  `uv sync --all-groups`. Per-challenge isolation is therefore the rule below, kept by the author
  and by review — nothing checks it for you.
- [ ] The **shared layer stays stdlib + PyYAML**: nothing under `scripts/` or `tests/` may import a
      challenge's libraries. Challenge tooling may import whatever its group provides.

## 6. Tests

- [ ] Challenge tests live in `challenges/<id>/tests/` and are added to `testpaths` in
      `pyproject.toml`.
- [ ] Each test module starts with `pytest.importorskip("<library>")` for anything outside the
      shared layer, so `uv run pytest` still passes for someone who synced only the dev group.
- [ ] Cover at least: deterministic instance generation (same inputs → byte-identical file), the
      structural guarantees your README promises, one negative test per validator error code, and
      the interesting positive edge cases.

## 7. `demo.sh`

- [ ] `challenges/<id>/demo.sh` runs the whole round trip on a tiny hand-made instance from
      `demo/` — generate (or read) → baseline → validate → render — and is what `make demo
      CHALLENGE=<id>` invokes. It must work from any working directory (resolve paths relative to
      the script) and write only into the challenge directory.
- [ ] Numbers quoted in `challenges/<id>/README.md` are produced by the tools, not typed by hand.

## 8. Opening and closing the round

- [ ] Land the challenge on `main`, get `check_challenge.py` and `uv run pytest` green.
- [ ] Create the annotated start tag on that `main` commit, then flip the manifest to
      `status: open` and update the row in `challenges/README.md`:

  ```sh
  git tag -a c002-start -m "étude no. 2 — <title> — start position"
  git push origin c002-start
  ```

  The tag **never moves once the status is `open`**. Tooling fixes land on `main` afterwards; CI
  validates with `main`'s copy of the challenge directory, so participants never rebase.
- [ ] **Hidden-set protocol.** Hidden instances are generated from secret seeds and are *not*
      committed while the round is open — keep the seeds in an untracked file or an environment
      variable, and have your generator script refuse to run if the seeds file is tracked or staged.
      When the round closes, the organizer publishes the seeds, commits the generated
      `instances/hidden/`, and flips the manifest to `status: closed` in one PR. Participants then
      regenerate the identical instances locally, run their own solver, and commit
      `solutions/hidden/` on their attempt branch, where CI can validate them.
      See `challenges/c001/tools/make_hidden.sh` for the worked example.

## 9. Final pass

- [ ] `uv run python scripts/check_challenge.py challenges/c002` — one `PASS:`/`FAIL:` line per
      rule, exit 1 if any of them failed: manifest schema and unknown keys, directory name == id,
      the tools named by `validate`, `README.md`, dev instances unless the status is `draft`,
      instance id == filename stem, tag/status agreement, hidden-set state, the declared
      `dependency_group` really existing in `pyproject.toml`, the vocabulary grep over the whole
      challenge directory, and — once `tools/baseline.py` and one dev instance exist — a live
      baseline → `validate` round trip whose last stdout line is checked for the `valid`,
      `summary` and `errors` keys.
- [ ] `bash scripts/check_words.sh` — the repository's vocabulary rules apply inside your challenge
      too: a quality number is a **measure**, difficulty levels are personal rungs rather than
      standings, and no tool ever compares one participant with another.
- [ ] `uv run pytest` and `make demo CHALLENGE=c002`.
- [ ] Open the PR. The étude is a normal change to `main`, reviewed like any other.
