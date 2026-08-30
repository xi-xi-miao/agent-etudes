---
version: "0.2"
---

# TAXONOMY — the annotation vocabulary (v0.2)

This file is the authoritative vocabulary for annotating a session. It changes only
by pull request (see §7). Annotation files record the version they were written
against in their `taxonomy_version` frontmatter field.

---

## 1. The four layers

Annotation of a session uses four layers, borrowed from chess annotation practice:

1. **Phases** — the game stage a move happens in (like opening/middlegame/endgame).
2. **Moves** — a finite vocabulary of human actions (like Nf3).
3. **Glyphs** — hindsight evaluation marks (like `!`, `?`, `??`).
4. **Motifs** — recurring situational patterns (like fork, pin, zugzwang).

---

## 2. Phases

| Phase | Meaning |
|---|---|
| `Recon` | Understanding the problem/codebase before planning |
| `Plan` | Deciding approach, decomposition, contracts |
| `Build` | Producing the solution |
| `Verify` | Checking the solution against intent |
| `Recover` | Reacting to things having gone wrong |

Sessions oscillate between phases; the oscillation pattern is itself a comparison
signal.

---

## 3. Moves (26)

The vocabulary has **26 entries: 24 named moves + `X-<name>` + `NOTE`.**

`NOTE` is not a move — it is a free-form timeline remark — and it is **excluded
from move-frequency tables** produced by the stats tooling. `X-<name>` is the
wildcard escape hatch and forms its own "Wildcard" family in those tables.

### 3.1 The 24 named moves

| Family | Move | Meaning |
|---|---|---|
| Context | `SCOUT` | Send the agent to explore/report, read-only, before acting |
| Context | `GROUND` | Inject authoritative material (docs, spec, reference code) |
| Context | `FENCE` | Set constraints/rules (agent config file, "don't touch X", permissions) |
| Context | `DISTILL` | Compress session state into a handoff doc for a fresh context |
| Plan | `PLAN` | Demand an explicit plan before any code |
| Plan | `SPLIT` | Decompose into subtasks |
| Plan | `SPEC` | Write acceptance criteria / tests as the contract first |
| Plan | `SPIKE` | Throwaway experiment to learn before committing to an approach |
| Delegate | `DISPATCH` | Hand off a chunk and walk away |
| Delegate | `PAIR` | Tight interactive loop, step-by-step supervision |
| Delegate | `FORK` | Parallel attempts (worktrees, multiple agents) |
| Delegate | `REVIEW` | Fresh context / second agent reviews the work |
| Steer | `NUDGE` | Small in-flight correction |
| Steer | `REDIRECT` | Change of approach mid-task |
| Steer | `VETO` | Reject output, re-request |
| Steer | `TAKEOVER` | Human edits the code directly |
| Steer | `ROLLBACK` | Revert to a checkpoint |
| Steer | `RESET` | Abandon context, start a fresh session |
| Epistemic | `TUTOR` | Have the agent teach the domain concept before deciding |
| Epistemic | `OPTIONS` | Request alternatives with tradeoffs before choosing |
| Epistemic | `PROBE` | Make the agent justify a choice it already made |
| Epistemic | `CRITERIA` | Establish how to judge what you can't judge directly (benchmark, invariant, oracle) |
| Epistemic | `CROSSCHECK` | Independent verification: web search, second model, primary docs |
| Epistemic | `DEFER` | Consciously accept the agent's judgment unverified |

Family sizes: Context 4 · Plan 4 · Delegate 4 · Steer 6 · Epistemic 6 = **24**.

### 3.2 The two non-named entries

| Entry | Meaning |
|---|---|
| `X-<name>` | **Wildcard/escape hatch.** Anything the vocabulary can't express. `<name>` is a short lowercase identifier chosen by the annotator, e.g. `X-bribe`. A comment is mandatory. |
| `NOTE` | Not a move: free-form timeline remark (environment issues, breaks, observations) |

So: **26 = 24 named moves + `X-<name>` + `NOTE`.**

### 3.3 Why the Epistemic family exists

The Epistemic family exists specifically to capture how people handle **decisions
in domains they don't know** — the project's central research interest. `DEFER` is
a legitimate, explicit move; what matters is that it is logged.

### 3.4 Wildcard governance (CUPS-inspired)

Wildcards are legal and lint-clean. At each retro, all `X-*` moves used since the
last version are reviewed; a wildcard used independently by **≥ 2 participants**
(or **≥ 3 times by one**) is a candidate for promotion into the vocabulary via PR.
This is the only intended growth path.

The stats tooling reports the Wildcard family with per-`X-<name>` counts and the
number of distinct participants who used each — that table is the promotion
evidence, and the retro records the promotion decisions.

---

## 4. Glyphs

Applied in hindsight during annotation, never during the session. Same semantics
as chess:

| Glyph | Meaning |
|---|---|
| `!!` | Turning point; steal this |
| `!` | Good move |
| `!?` | Interesting, unproven |
| `?!` | Dubious |
| `?` | Mistake |
| `??` | Blunder |

Glyphs are optional; most moves carry none. Costs (minutes, tokens) belong in the
comment, not in new symbols.

### 4.1 Earliest-cause rule

Adopted from failure-localization research: when marking a `?` or `??`, place it
on the **earliest move from which the trouble became unrecoverable**, not on the
downstream move where the symptom surfaced. The symptom location may get a motif
annotation instead.

---

## 5. Motifs

Motifs annotate the *situation*, not the human's action — the forks and pins of
agent work:

| Motif | Meaning |
|---|---|
| `doom-loop` | Agent cycling on the same failing fix |
| `false-summit` | Agent claims done; it isn't |
| `ghost-api` | Hallucinated function/library/flag |
| `overreach` | Agent did more than asked |
| `test-gaming` | Satisfies the check, defeats the intent |
| `context-rot` | Quality decaying as the context window fills |
| `yes-and` | Agent uncritically builds on the human's wrong assumption |
| `rabbit-hole` | Human-directed detour that consumed time without payoff |
| `windfall` | Agent surfaced something valuable that wasn't asked for |

---

## 6. Optional stance marker

To keep annotations mappable to the research literature (Grounded Copilot's
acceleration/exploration bimodality), a move line MAY carry a stance suffix on
the phase:

- `Build>` = **acceleration** (I knew what I wanted)
- `Build~` = **exploration** (I was searching)

The suffix is available on every phase (`Recon~`, `Plan>`, `Verify~`, …).
It is entirely optional; the linter accepts both bare and suffixed phases.

---

## 7. Versioning & evolution rules

- `TAXONOMY.md` carries `version:` frontmatter; annotation files record which
  version they were written against (`taxonomy_version`).
- Changes only via PR labeled `taxonomy-change`, motivated by wildcard evidence
  or a session that demonstrably couldn't be described.
- Removal is preferred over addition when usage data shows a move is never used.
  Target size stays ≤ ~26 moves.
- **Reliability check:** occasionally two participants annotate the *same* session
  independently and diff the results; systematic disagreement on a move's meaning
  triggers a definition clarification PR. (Standard practice from dialogue-act
  annotation research.)
- **Where a cross-annotation lives.** The second reading of an attempt is committed as
  `results/<cid>/<participant>/<n>/reviews/<reviewer>.annotations.md` — the reviewer's
  handle is the filename stem and appears nowhere else. Its frontmatter keeps the
  *annotated* attempt's `participant`, `challenge` and `attempt`, which
  `scripts/lint_annotations.py` cross-checks against that attempt's `session.yaml`; a
  reviewer who wants to be named in the file may add an optional `annotator:` key
  beside them. Diff the pair with `scripts/compare_annotations.py`.

---

## 8. Where the grammar lives

The line grammar that combines these four layers into one annotation line is
enforced by `scripts/lint_annotations.py`; the shape is:

```
timestamp  phase  move  [glyph]  [(motifs)]  ["comment"]  [@anchor]
```

**The timestamp origin.** `+0:00` is the moment the participant starts the
session — the first reading of the challenge, before any code or commit exists.
Every later `+H:MM` is elapsed time from that moment, and it is the only zero
point the annotation grammar has. The collected
`results/<cid>/<participant>/<n>/git-timeline.txt` uses a *different* zero: its
`+0:00` is the attempt's first commit, which normally falls some minutes into
the session. So a line anchored `@<commit>` and that commit's row in the
timeline carry different offsets by design; read the two side by side, not as
one clock.

See `templates/annotations.md` for the annotated template and
`examples/example-session/annotations.md` for a complete worked example.
