# agent-etudes

**Études for the age of coding agents: same position, different games, annotated.**

An étude is a piece composed for practicing technique — a study, not a tournament; challenges here
are numbered "étude no. 1", "étude no. 2", … and each one is played by everybody.

## Purpose

A small group of people each solve the *same* ~4-hour challenge independently, each with whatever
AI coding agent they prefer, in their own branch. Afterwards each participant spends ~30 minutes
annotating what happened — a retrospective, chess-style transcript of the *process*, not the code —
and the group reads those annotations side by side. The point is to learn best practices for the
human guidance of coding agents from concrete, comparable sessions: where somebody planned instead
of prompting, where an agent went in circles, where a human took over too early, what is worth
stealing.

It is not a benchmark, not a competition: there is no leaderboard, no scores, no rankings.

## The four layers

Annotation borrows its structure from chess notation. Every session becomes a list of timestamped
lines with four layers:

1. **Phases** — `Recon` `Plan` `Build` `Verify` `Recover`: which stage of the game a move happens in.
2. **Moves** — a fixed vocabulary of 26 entries: 24 named human actions (`SCOUT`, `GROUND`, `PLAN`,
   `SPEC`, `DISPATCH`, `REVIEW`, `NUDGE`, `TAKEOVER`, `TUTOR`, `CROSSCHECK`, `DEFER`, …), the
   wildcard `X-<name>` for whatever the vocabulary cannot express, and `NOTE` for plain remarks.
3. **Glyphs** — hindsight marks: `!!` turning point, `!` good, `!?` interesting, `?!` dubious,
   `?` mistake, `??` blunder. Most moves carry none.
4. **Motifs** — recurring situations rather than actions: `doom-loop`, `false-summit`, `ghost-api`,
   `context-rot`, `yes-and`, `rabbit-hole`, `windfall`, …

One annotation line, all four layers at once:

```
+2:05  Recover RESET !!  (context-rot) "fresh context + DISTILL doc; night-and-day difference"
```

The full vocabulary, the earliest-cause rule for `?`/`??`, the optional stance marker, the fence
rule that keeps an `annotations.md` readable as ordinary markdown, and the governance rules for
growing the vocabulary live in [TAXONOMY.md](TAXONOMY.md).

## Quickstart

```sh
uv sync --all-groups                                       # install everything (Python 3.11+)
uv run python scripts/lint_annotations.py examples/example-session/annotations.md --session
uv run pytest                                              # shared + challenge tests
make demo CHALLENGE=c001                                   # étude no. 1 round trip
make lint                                                  # every annotations.md in the tree, as CI does
```

Run `make help` for the full list of targets.

## Repository map

Placeholders used throughout: `<cid>` is a challenge id such as `c001`, `<participant>` is your
handle (`[a-z0-9-]+`, the same string in every file), `<n>` is your attempt number for that étude,
from 1, and `<instance_id>` is the stem of an instance file, equal to its `instance_id` field.

```
AGENTS.md            orientation for coding agents: map, invariants, commands, conventions
CONTRIBUTING.md      the participant workflow in five steps; maintainer section at the end
TAXONOMY.md          annotation vocabulary v0.2 — authoritative for the vocabulary itself; the
                     line grammar that combines it is enforced by scripts/lint_annotations.py
templates/           session.yaml, annotations.md, postmortem.md, decision-record.md (attempt);
                     retro.md (maintainer, for retros/)
examples/            example-session/ — a complete synthetic session, all four layers
challenges/          one directory per étude (challenges/c001/ = étude no. 1); README.md is the
                     index and the design criteria, each étude's README.md is the statement
                     followed by the tool contracts
scripts/             shared, challenge-agnostic tooling (linter, collector, stats, validation)
tests/               tests for the shared layer (a challenge's tests: challenges/<cid>/tests/)
results/             collected session artifacts, results/<cid>/<participant>/<n>/ (README.md inside)
retros/              the stored record of each round: retro.md, stats.txt, gallery.html (README.md inside)
docs/                adding-a-challenge.md (the challenge contract), references.md
Makefile             every command; make help
pyproject.toml       Python 3.11+, uv dependency groups (dev + one per challenge), pytest config
.github/             workflows/ci.yml and PULL_REQUEST_TEMPLATE.md
```

## Where to go next

- [CONTRIBUTING.md](CONTRIBUTING.md) — **participants start here**: the participant workflow, step
  by step, with worked scenarios.
- [AGENTS.md](AGENTS.md) — **coding agents start here**: a map of the repository and its invariants,
  with the file that owns each rule. It says nothing about how to solve an étude.
- [TAXONOMY.md](TAXONOMY.md) — the vocabulary: phases, moves, glyphs, motifs, versioning rules.
- [templates/](templates/) — `session.yaml`, `annotations.md` and `postmortem.md` are copied into
  your `session/` directory when you set the attempt up; `decision-record.md` becomes
  `session/decisions/dr-00X.md`, one file per decision; `retro.md` is a maintainer artifact for
  `retros/<cid>/`, not part of an attempt. The exact commands are in CONTRIBUTING step 2.
- [challenges/README.md](challenges/README.md) — the étude index and the challenge design criteria.
- [docs/adding-a-challenge.md](docs/adding-a-challenge.md) — the contract a new étude must satisfy.
- [docs/references.md](docs/references.md) — the research this design is built on.

## Open items

- [ ] The hidden test set and the round schedule: hidden instances are generated from seeds that are
      published only after a round closes, and no publication date is fixed yet.
- [ ] A lightweight HTML session viewer — explicitly deferred; the retro gallery is the only HTML
      artifact for now.
- [ ] Taxonomy v0.3 — to be driven by wildcard (`X-*`) evidence collected in round one, per the
      promotion rules in TAXONOMY.md.
