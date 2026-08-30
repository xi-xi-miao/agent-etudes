# AGENTS.md — orientation for coding agents

A coding agent was pointed at this repository; this file is its map. It says what is where, which
rules must not be broken, which commands prove a change, and the conventions the prose follows.
Every rule names the file that owns it in square brackets: when this file and the owner disagree,
the owner is right and this file has a defect. Nothing here says how to solve an étude — the
comparison this repository exists for depends on every participant starting from the same position.

## What this repository is

agent-etudes is a git-native lab. A small group each solve the same ~4-hour challenge (an "étude")
on their own branch with their own coding agent, then spend ~30 minutes annotating the *process* in
a chess-like vocabulary. The record is the branches, the commits and the annotations; nothing in the
tree compares one participant with another. [`README.md`]

Two situations you are likely in:

- **On an attempt branch** (`attempt/<cid>/<participant>/<n>`), helping a participant play. The
  position is `challenges/<cid>/README.md`; the workflow is `CONTRIBUTING.md`. Your commits are part
  of the record — invariants 2 and 5 below.
- **On a branch off `main`**, changing tooling, documents or a challenge. Read "House rules for
  every PR" in `CONTRIBUTING.md`, and `docs/adding-a-challenge.md` when a challenge is involved.

## Map

| Path | What it is, and the rules it owns |
|---|---|
| `README.md` | purpose, the four annotation layers, quickstart, repository map; carries the one sentence allowed to name what this is not |
| `AGENTS.md` | this file: it owns nothing and cites everything |
| `CONTRIBUTING.md` | the participant workflow and the maintainer section; owns branch names, commit prefixes, the attempt working tree, the secrets review, the PR and label rules |
| `TAXONOMY.md` | the vocabulary v0.2 — phases, moves, glyphs, motifs, stance; owns the earliest-cause rule, the versioning rules (section 7), the fence rule and the timestamp origin (section 8) |
| `templates/` | `templates/session.yaml`, `templates/annotations.md`, `templates/postmortem.md` and `templates/decision-record.md` for an attempt, `templates/retro.md` for a round; owns their shape |
| `examples/example-session/` | one complete synthetic session; `tests/test_example_completeness.py` holds it to the whole notation |
| `challenges/` | one directory per étude; `challenges/README.md` is the index, `challenges/<cid>/README.md` the position — the statement followed by the tool contracts |
| `challenges/<cid>/challenge.yaml` | the manifest every shared script reads: id, number, title, status, start tag, dependency group, solutions glob, validate command |
| `challenges/<cid>/tools/` | generator, validator, renderer, baseline, gallery — the organizer's side; the validator is the oracle |
| `scripts/` | shared, challenge-agnostic tooling; `scripts/lint_annotations.py` owns the line grammar and `scripts/check_words.sh` the vocabulary check |
| `tests/` | tests of the shared layer; a challenge's own tests live in `challenges/<cid>/tests/` |
| `results/` | collected attempts, `results/<cid>/<participant>/<n>/` — see `results/README.md` |
| `retros/` | the stored record of each closed round — see `retros/README.md` |
| `docs/adding-a-challenge.md` | the contract a new étude must satisfy: manifest, tool CLIs, demo, opening and closing a round |
| `docs/references.md` | the research this design borrows from |
| `Makefile` | every command worth running; `make help` lists the targets |
| `pyproject.toml`, `uv.lock`, `.python-version` | Python 3.11+, the `dev` group plus one group per challenge, the pytest paths |
| `.github/workflows/ci.yml`, `.github/PULL_REQUEST_TEMPLATE.md` | which checks run where, and the PR checklist |
| `.gitleaks.toml`, `.gitignore` | the secret-scan config; the ignore list covers the generated build directory, hidden-set seeds and nested agent worktrees |

## Invariants

1. Attempt branches are named `attempt/<cid>/<participant>/<n>` and fork from the annotated tag
   `<cid>-start`, never from another attempt. CI reads the challenge id out of the branch name.
   [`CONTRIBUTING.md` steps 1 and 5]
2. Every commit subject on an attempt branch starts with `[agent]` or `[human]`, by who actually
   authored the change, and commits are frequent enough to annotate. [`CONTRIBUTING.md` step 2]
3. Attempt pull requests are drafts labelled `attempt` and are never merged; the branch is the
   record. The one pull request of a round that merges is the retro, from `retro/<cid>` to `main`.
   [`CONTRIBUTING.md` step 4 and scenario C; `.github/PULL_REQUEST_TEMPLATE.md`]
4. Nothing in tooling or prose compares participants, and the vocabulary `scripts/check_words.sh`
   greps for appears nowhere except one sentence of `README.md`. CI runs the check in its tests job.
   [`scripts/check_words.sh`; `CONTRIBUTING.md` "House rules for every PR"]
5. Everything about to be pushed is read for secrets first — transcripts above all, then the agent
   harness, the solver code and the solutions. CI's gitleaks job runs after the push and can only
   report what is already published. [`CONTRIBUTING.md` step 4; `.gitleaks.toml`]
6. `TAXONOMY.md` changes only through a pull request labelled `taxonomy-change`, motivated by
   wildcard evidence or by a session that demonstrably could not be described.
   [`TAXONOMY.md` section 7]
7. The annotated timeline follows the grammar `scripts/lint_annotations.py` enforces, and its
   `participant`, `challenge` and `attempt` agree with the session metadata beside it and with the
   branch name. `+0:00` is the start of the session, not the first commit.
   [`TAXONOMY.md` section 8; `templates/annotations.md`; `CONTRIBUTING.md` step 3]
8. A solution is written to `solutions/<instance_id>.json` on the attempt branch, with its rendered
   SVG beside it under the same stem. Only the session and solution artifacts are collected, into
   `results/<cid>/<participant>/<n>/`; the solver code stays on the branch and says how to build and
   run it in a README of its own. [`CONTRIBUTING.md` step 2; `challenges/<cid>/README.md`]
9. The shared layer (`scripts/`, `tests/`) imports only the standard library and PyYAML; a
   challenge's own libraries live in a uv dependency group named after its id.
   [`docs/adding-a-challenge.md` section 5; `pyproject.toml`]
10. `challenges/<cid>/challenge.yaml` rejects unknown keys; the start tag never moves once the
    status is `open`; CI validates solutions with `main`'s copy of the challenge directory, so
    participants never rebase.
    [`docs/adding-a-challenge.md` sections 2, 3 and 8; `.github/workflows/ci.yml`]
11. Hidden-set seeds are never committed while a round is open; seeds and instances are published
    together when it closes. [`docs/adding-a-challenge.md` section 8;
    `challenges/<cid>/tools/make_hidden.sh`]
12. A rule is stated in full in one file; every other file gives the path and a link. When a rule
    changes, change the owner and fix the links. [`CONTRIBUTING.md` "House rules for every PR"]

## Commands

Run them from the repository root; Python runs through `uv`. [`Makefile`]

```sh
uv sync --all-groups                      # once per clone (Python 3.11+ and uv); also: make sync
make help                                 # every target
make lint                                 # annotations and session files, in the form CI runs
uv run pytest                             # shared layer plus challenge tests; also: make test
make check-words                          # the vocabulary check
make check-challenge CHALLENGE=<cid>      # the challenge contract, rule by rule
make demo CHALLENGE=<cid>                 # a challenge's round trip, written into build/
uv run python challenges/<cid>/tools/validate.py <instance> <solution> --json   # one layout
make retro CHALLENGE=<cid>                # maintainer: collect, stats and gallery into retros/<cid>
```

A green `make lint`, `uv run pytest` and `make check-words` are the bar before asking for review.
[`CONTRIBUTING.md` "House rules for every PR"]

## Conventions

- Placeholders: `<cid>` is a challenge id (`^c[0-9]{3}$`, e.g. `c001`); `<participant>` a handle
  (`[a-z0-9-]+`, the same string in every file); `<n>` an attempt number for that étude, from 1;
  `<instance_id>` the stem of an instance file, equal to its `instance_id` field.
- Prose says "étude no. N"; paths say `cNNN`; the title lives in the challenge manifest.
- Branch names, `results/` and `retros/` are all keyed by `<cid>`, so several études coexist.
- Numbers quoted in a document come out of the tools, never from typing.
  [`docs/adding-a-challenge.md` section 7]
- A test or script that must not contain a checked word assembles it from fragments at run time.
  [`tests/test_words.py`; `scripts/check_challenge.py`]
- Markdown is wrapped at about 100 columns, plain and unadorned; commit subjects are imperative.
- `docs/adding-a-challenge.md` is the checklist and `scripts/check_challenge.py` its machine form;
  when the contract changes, both change.
