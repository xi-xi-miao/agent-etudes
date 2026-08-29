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

The full vocabulary, the earliest-cause rule for `?`/`??`, the optional stance marker and the
governance rules for growing the vocabulary live in [TAXONOMY.md](TAXONOMY.md).

## Quickstart

```sh
uv sync --all-groups                                       # install everything (Python 3.11+)
uv run python scripts/lint_annotations.py examples/example-session/annotations.md --session
uv run pytest                                              # shared + challenge tests
make demo CHALLENGE=c001                                   # étude no. 1 round trip
```

`make help` lists the rest (`lint`, `test`, `stats`, `collect`, `retro`, `check-words`,
`check-challenge`).

## Repository map

```
TAXONOMY.md          annotation vocabulary v0.2 — the authoritative spec
templates/           session.yaml, annotations.md, postmortem.md, decision-record.md, retro.md
examples/            example-session/ — a complete synthetic session, all four layers
challenges/          one directory per étude (challenges/c001/ = étude no. 1) + the index
scripts/             shared, challenge-agnostic tooling (linter, collector, stats, validation)
tests/               tests for the shared layer
results/             collected session artifacts, results/<cid>/<participant>/<n>/
retros/              the stored record of each round: retro.md, stats.txt, gallery.html
docs/                adding-a-challenge.md, references.md, handoffs/ (original specs)
```

## Where to go next

- [TAXONOMY.md](TAXONOMY.md) — the vocabulary: phases, moves, glyphs, motifs, versioning rules.
- [templates/](templates/) — copy these into your `session/` directory at the start of an attempt.
- [challenges/README.md](challenges/README.md) — the étude index and the challenge design criteria.
- [CONTRIBUTING.md](CONTRIBUTING.md) — the participant workflow, step by step, with worked scenarios.
- [docs/adding-a-challenge.md](docs/adding-a-challenge.md) — the contract a new étude must satisfy.
- [docs/references.md](docs/references.md) — the research this design is built on.

## Open items

- [ ] The hidden test set and the round schedule: hidden instances are generated from seeds that are
      published only after a round closes, and no publication date is fixed yet.
- [ ] A lightweight HTML session viewer — explicitly deferred; the retro gallery is the only HTML
      artifact for now.
- [ ] Taxonomy v0.3 — to be driven by wildcard (`X-*`) evidence collected in round one, per the
      promotion rules in TAXONOMY.md.
