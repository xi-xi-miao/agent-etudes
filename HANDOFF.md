# HANDOFF — agent-etudes: repository scaffolding

**Audience:** a coding agent picking up this project cold. Everything you need is in this document.
**Goal of this handoff:** scaffold a GitHub repository that hosts a shared coding challenge, session logging, and an annotation system so that a small group of developers can each solve the same problem with their own AI coding agent, log the process, annotate it with a fixed vocabulary, and learn from comparing approaches.
**Not in scope:** the challenge content itself (placeholder only), any web viewer, any leaderboard or scoring.

---

## 1. Project context

A group of friends wants to learn coding-agent best practices from each other. General descriptions of "how I use my agent" are too vague, so instead: everyone solves the **same ~4-hour challenge** independently, in their own branch, with whatever agent/tool they prefer. What gets compared afterwards is not primarily the resulting code but the **process**: transcripts, git history, and — most importantly — a retrospective annotation of the session written in a small fixed vocabulary of "moves" (inspired by chess annotation: move notation + evaluation glyphs + motif vocabulary + game phases).

Design principles, already decided — treat as constraints:

1. **Async, git-native.** No synchronized event. Branch naming: `attempt/<participant>/<n>`. Retries are simply new attempt branches (`n` increments).
2. **Free tool/model choice.** Tool and model MUST be logged in `session.yaml`; readers judge comparability themselves. Build no tooling that assumes a specific agent.
3. **No leaderboard, no scores, no rankings.** Do not implement any ranking feature, aggregate "winner" output, or competitive framing. The stats tooling reports distributions and timelines only.
4. **Annotation is retrospective.** During the session the only duty is committing often. Annotation (~30 min) happens afterwards from git log + transcript.
5. **No secrets in the repo.** Transcripts are the riskiest artifact. CI runs a secret scanner; contributor docs require self-review before push.
6. **Vocabulary is versioned and conservative.** The taxonomy ships as v0.2 and changes only via PR. A wildcard move exists as escape hatch; wildcard usage is the evidence that drives evolution.

---

## 2. Repository structure to create

```
agent-etudes/
├── README.md                    # what/why + quickstart (see §8)
├── CONTRIBUTING.md              # participant workflow (see §8)
├── TAXONOMY.md                  # the annotation vocabulary v0.2 (full content in §3)
├── challenge/
│   └── README.md                # placeholder + challenge design criteria (see §7)
├── templates/
│   ├── session.yaml             # metadata template (schema in §5)
│   ├── annotations.md           # annotation file template (format in §4)
│   ├── postmortem.md            # half-page structured retrospective
│   └── decision-record.md       # mini-ADR for unfamiliar-domain decisions
├── examples/
│   └── example-session/         # small synthetic fixture demonstrating all artifacts
│       ├── session.yaml
│       ├── annotations.md
│       ├── postmortem.md
│       └── decisions/dr-001.md
├── results/
│   └── .gitkeep                 # populated on main by collect_results
├── scripts/
│   ├── lint_annotations.py      # notation linter (see §6.1)
│   ├── collect_results.py       # gather attempt branches into results/ (see §6.2)
│   └── stats.py                 # frequencies + timelines, CUPS-style (see §6.3)
├── docs/
│   └── references.md            # literature list (content in §9)
└── .github/workflows/ci.yml     # secret scan + annotation lint (see §6.4)
```

Language for scripts: Python 3.11+, stdlib + PyYAML only. Keep everything runnable offline.

---

## 3. TAXONOMY.md — full content (v0.2)

Write the following as `TAXONOMY.md`, formatted nicely, with a frontmatter header `version: 0.2`. This section is the authoritative spec; do not invent additional moves, glyphs, or motifs.

### 3.1 The four layers

Annotation of a session uses four layers, borrowed from chess annotation practice:

1. **Phases** — the game stage a move happens in (like opening/middlegame/endgame).
2. **Moves** — a finite vocabulary of human actions (like Nf3).
3. **Glyphs** — hindsight evaluation marks (like `!`, `?`, `??`).
4. **Motifs** — recurring situational patterns (like fork, pin, zugzwang).

### 3.2 Phases

| Phase | Meaning |
|---|---|
| `Recon` | Understanding the problem/codebase before planning |
| `Plan` | Deciding approach, decomposition, contracts |
| `Build` | Producing the solution |
| `Verify` | Checking the solution against intent |
| `Recover` | Reacting to things having gone wrong |

Sessions oscillate between phases; the oscillation pattern is itself a comparison signal.

### 3.3 Moves (26)

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
| — | `X-<name>` | **Wildcard/escape hatch.** Anything the vocabulary can't express. `<name>` is a short lowercase identifier chosen by the annotator, e.g. `X-bribe`. A comment is mandatory. |
| — | `NOTE` | Not a move: free-form timeline remark (environment issues, breaks, observations) |

The Epistemic family exists specifically to capture how people handle **decisions in domains they don't know** — the project's central research interest. `DEFER` is a legitimate, explicit move; what matters is that it is logged.

**Wildcard governance (CUPS-inspired):** wildcards are legal and lint-clean. At each retro, all `X-*` moves used since the last version are reviewed; a wildcard used independently by ≥2 participants (or ≥3 times by one) is a candidate for promotion into the vocabulary via PR. This is the only intended growth path.

### 3.4 Glyphs

Applied in hindsight during annotation, never during the session. Same semantics as chess:

| Glyph | Meaning |
|---|---|
| `!!` | Turning point; steal this |
| `!` | Good move |
| `!?` | Interesting, unproven |
| `?!` | Dubious |
| `?` | Mistake |
| `??` | Blunder |

Glyphs are optional; most moves carry none. Costs (minutes, tokens) belong in the comment, not in new symbols.

**Earliest-cause rule** (adopted from failure-localization research): when marking a `?` or `??`, place it on the **earliest move from which the trouble became unrecoverable**, not on the downstream move where the symptom surfaced. The symptom location may get a motif annotation instead.

### 3.5 Motifs

Motifs annotate the *situation*, not the human's action — the forks and pins of agent work:

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

### 3.6 Optional stance marker

To keep annotations mappable to the research literature (Grounded Copilot's acceleration/exploration bimodality), a move line MAY carry a stance suffix on the phase: `Build>` = acceleration (I knew what I wanted), `Build~` = exploration (I was searching). Entirely optional; linter accepts both bare and suffixed phases.

### 3.7 Versioning & evolution rules

- `TAXONOMY.md` carries `version:` frontmatter; annotation files record which version they were written against.
- Changes only via PR labeled `taxonomy-change`, motivated by wildcard evidence or a session that demonstrably couldn't be described.
- Removal is preferred over addition when usage data shows a move is never used. Target size stays ≤ ~26 moves.
- **Reliability check:** occasionally two participants annotate the *same* session independently and diff the results; systematic disagreement on a move's meaning triggers a definition clarification PR. (Standard practice from dialogue-act annotation research.)

---

## 4. Annotation file format (`annotations.md`)

YAML frontmatter + one line per move. This is the format `lint_annotations.py` must enforce.

```markdown
---
participant: alice
challenge: c001
attempt: 2
taxonomy_version: "0.2"
session_date: 2026-09-12
---

+0:00  Recon   SCOUT           "asked for repo map and dependency overview"        @a1b2c3d
+0:14  Recon   TUTOR           "had it explain CRDTs before touching sync code"
+0:31  Plan    SPEC !          "wrote failing tests as contract first"             @b2c3d4e
+0:40  Build>  DISPATCH        "handed off module A, went for coffee"
+1:12  Build   NUDGE           "keep the public API, change internals only"
+1:42  Build   TAKEOVER ?  (false-summit) "rewrote parser by hand; agent's version was salvageable, cost ~30min" @c3d4e5f
+2:05  Recover RESET !!  (context-rot) "fresh context + DISTILL doc; night-and-day difference"
+2:06  Recover DISTILL !       "handoff doc: decisions so far, open items, constraints"
+3:10  Verify  CROSSCHECK      "second model reviewed diff; found off-by-one"      @d4e5f6a
+3:30  Verify  DEFER ?!        "accepted its choice of eviction policy unverified"
```

### 4.1 Line grammar (implement exactly)

```
line      := timestamp WS phase WS move [WS glyph] [WS motifs] [WS comment] [WS anchor]
timestamp := "+" digit+ ":" digit digit               # elapsed h:mm from session start
phase     := ("Recon"|"Plan"|"Build"|"Verify"|"Recover") ["<stance>"]
stance    := ">" | "~"                                 # optional, appended to phase
move      := <one of the 24 named moves> | "X-" [a-z][a-z0-9-]* | "NOTE"
glyph     := "!!" | "!" | "!?" | "?!" | "?" | "??"
motifs    := "(" motif {"," WS? motif} ")"             # motif from the motif table only
comment   := '"' <no unescaped quotes> '"'
anchor    := "@" hex{7,40}                             # git commit
           | "@t" digit+                               # transcript anchor (line/entry no.)
```

Lint rules: timestamps monotonically non-decreasing; `X-*` and every `??` require a comment; unknown moves/phases/motifs/glyphs are errors; blank lines and `#`-comment lines are ignored; frontmatter fields above are all required. With `--repo <path>`, verify `@<hex>` anchors resolve to commits (warning, not error, if repo unavailable).

---

## 5. `session.yaml` schema

```yaml
participant: alice            # required, [a-z0-9-]+
challenge: c001               # required
attempt: 2                    # required, int ≥ 1
date: 2026-09-12              # required
tool:                         # required
  name: "<agent product>"
  version: "<version string>"
model:                        # required
  name: "<model id>"
harness:                      # optional but encouraged
  config_paths: ["harness/"]  # snapshot of agent config, rules files, MCP setup
  notes: ""
duration_wall_minutes: 235    # required
cost:                         # optional (e.g. from usage tooling)
  tokens_in: 0
  tokens_out: 0
  usd_estimate: 0.0
transcript:                   # optional
  path: ".specstory/history/" # or tool-native export location
  tool: "specstory|native|manual"
outcome:                      # required
  tests_passed: null          # true/false/null until challenge defines a suite
  self_assessment: ""         # 1–3 sentences, honest
notes: ""
```

Validate presence/types of required fields in the linter (a `--session` flag or separate check invoked by CI).

---

## 6. Scripts & CI

### 6.1 `scripts/lint_annotations.py`
- Input: one or more `annotations.md` paths (default: discover recursively).
- Implements §4 exactly. Human-friendly error messages with line numbers. Exit non-zero on any error.
- `--session` flag additionally validates sibling `session.yaml` against §5.

### 6.2 `scripts/collect_results.py`
- Enumerates branches matching `attempt/*/*` (or takes explicit refs).
- For each, copies the session artifacts — `session.yaml`, `annotations.md`, `postmortem.md`, `decisions/`, `harness/`, transcript directory if present — into `results/<participant>/<attempt>/` in the working tree, plus a generated `git-timeline.txt` (`git log --reverse --format='%h %ad %s' --date=format:'+%H:%M'` relative to first commit of the attempt).
- Never copies code (code stays reviewable on the branch); writes a `manifest.yaml` per attempt with branch name and head SHA.
- Idempotent; intended to be run by a maintainer and committed via normal PR.

### 6.3 `scripts/stats.py`
- Reads everything under `results/`.
- Outputs, per participant and aggregate: move-frequency table by family, glyph distribution, motif counts, phase timeline per session rendered as ASCII (CUPS-style timeline: one row per session, one char per 5 minutes, letter = phase), and a plain-text index of all `!!` and `??` lines with comments (the "brilliancies and blunders reel" — unranked, alphabetical by participant).
- `--grep MOVE|MOTIF` prints matching lines across all sessions.
- **Must not** compute rankings, scores, or any per-participant comparison metric framed as better/worse.

### 6.4 `.github/workflows/ci.yml`
- Job 1: secret scan with gitleaks (action `gitleaks/gitleaks-action`) over the full diff.
- Job 2: run `lint_annotations.py` (with `--session`) on any changed `annotations.md` / `session.yaml`.
- Both jobs required on PRs to `main` and pushes to `attempt/**`.

---

## 7. `challenge/README.md` placeholder

State that the first challenge is TBD and list the agreed design criteria so future challenge authors comply:

- ~4 hours for a balanced effort; explicitly **not one-shot-able** by a current agent.
- Multi-file; at least one early design decision so planning style becomes visible.
- Deliberately includes **decisions in a domain most participants won't know**, so Epistemic moves get exercised.
- Objective check exists (hidden test suite released after the round) plus qualitative dimensions (maintainability, clarity).
- Not a well-known problem likely to be in training data.
- Ships with a pinned starting commit/tag that all attempt branches must fork from.

## 8. README.md and CONTRIBUTING.md content requirements

README: open with the tagline *"Études for the age of coding agents: same position, different games, annotated."* and one line on the name (an étude is a piece composed for practicing technique — a study, not a tournament; challenges are numbered "étude no. 1", "étude no. 2", …). Then: one-paragraph purpose (learning best practices for human guidance of coding agents by comparing annotated sessions; explicitly *not* a benchmark, *not* a competition), the four-layer annotation idea in ~10 lines with one example line, quickstart, links to TAXONOMY.md and templates.

CONTRIBUTING — the participant workflow:
1. Branch `attempt/<you>/<n>` from the challenge tag.
2. Work with any agent. Commit often; prefix commit subjects `[agent]` or `[human]` by who authored the change. Optional: run a session recorder (e.g. SpecStory) so transcripts land in-repo as markdown.
3. Afterwards (~30 min): fill `session.yaml`, write `annotations.md` from git log + transcript, write `postmortem.md` (template: plan, where/why I intervened, where the agent got stuck, what I'd do differently, one thing to steal from my own session), and one `decisions/dr-XXX.md` per unfamiliar-domain decision (template fields: decision, options considered, epistemic moves used, confidence 1–5, outcome-filled-in-later).
4. **Review your transcript for secrets before pushing.** Push; open a PR to trigger CI (PRs are for CI + visibility; attempt branches are not merged into main).
5. Retries welcome: new branch, increment `n`.

## 9. `docs/references.md`

Include these with URLs and one-line relevance notes:

- Mozannar et al., *Reading Between the Lines: Modeling User Behavior and Costs in AI-Assisted Programming* (CHI 2024) — CUPS taxonomy; retrospective self-labeling of sessions; timeline/state-machine visualizations. Methodological template for our annotation workflow. https://dl.acm.org/doi/10.1145/3613904.3641936
- Barke, James, Polikarpova, *Grounded Copilot* (OOPSLA 2023) — acceleration vs. exploration bimodality; source of our optional stance marker. https://dl.acm.org/doi/10.1145/3586030
- *Model or Harness? An Interaction-Centric Taxonomy for Localizing Agent Failures* (arXiv 2607.28802) — source of the earliest-cause labeling rule. https://arxiv.org/html/2607.28802
- *Code with Me or for Me? How Increasing AI Automation Transforms Developer Workflows* (CHI 2026) — controlled study of developer–agent interaction. https://dl.acm.org/doi/10.1145/3772318.3790850
- *Are We All Using Agents the Same Way?* (arXiv 2601.20106) — evidence that interaction patterns vary by developer experience; motivates cross-person comparison. https://arxiv.org/html/2601.20106
- SpecStory docs — git-friendly markdown session capture across agent tools, with secret redaction. https://docs.specstory.com/
- PGN standard, Numeric Annotation Glyphs — precedent for standardized, machine-readable evaluation glyphs.
- Chess annotation practice generally (phases, glyphs, motifs) — the structural model for the four layers.

## 10. Acceptance criteria (verify before finishing)

1. Fresh clone: `python scripts/lint_annotations.py examples/example-session/annotations.md --session` exits 0.
2. Corrupting the example (unknown move, out-of-order timestamp, `X-` without comment, `??` without comment) produces a clear, line-numbered error and non-zero exit.
3. `stats.py` on a `results/` tree containing the example produces the frequency table and an ASCII phase timeline.
4. `collect_results.py` run against a dummy `attempt/test/1` branch populates `results/test/1/` with manifest and git-timeline.
5. CI config is syntactically valid and wires both jobs.
6. The example session demonstrates: all four layers, a wildcard move, a stance marker, both anchor types, and at least one motif.
7. Grep check: the words "leaderboard", "score", "rank" appear nowhere except (optionally) in a "what this is not" sentence in the README.

## 11. Known open items (leave as TODOs in README)

- First challenge content and hidden test suite.
- Whether to add a lightweight HTML session viewer (explicitly deferred).
- Taxonomy v0.3: to be driven by wildcard evidence after round one.
