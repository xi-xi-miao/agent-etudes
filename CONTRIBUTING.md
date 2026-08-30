# Contributing — how a round is played

Everything here is git-native and asynchronous: there is no synchronised event, no submission
deadline enforced by tooling, and no comparison of participants. What the repository collects is
*process*: branches, commits, and the annotations you write afterwards.

Read [TAXONOMY.md](TAXONOMY.md) once before your first attempt. The étude you are playing is
described in `challenges/<cid>/README.md`; the index is in [challenges/README.md](challenges/README.md).

---

## The participant workflow in five steps

### 1. Branch from the start tag

Every étude ships an annotated start tag named `<cid>-start` (`c001-start` for étude no. 1). All
attempt branches fork from that tag and only from that tag.

```sh
git fetch --tags
git switch -c attempt/c001/alice/1 c001-start
```

Branch names follow `attempt/<cid>/<you>/<n>`, where `<you>` is your participant id
(`[a-z0-9-]+`, the same string in every file you write) and `<n>` is your attempt number for *this*
étude, starting at 1. `n` restarts per étude: `attempt/c002/alice/1` is a first attempt even if you
made three attempts at c001. CI reads the challenge id out of the branch name, so the shape matters.

### 2. Set up, work with any agent, and commit often

Copy the templates before you start, so the files you fill in afterwards already exist:

```sh
mkdir -p session/decisions solver solutions
cp templates/session.yaml templates/annotations.md templates/postmortem.md session/
cp templates/decision-record.md session/decisions/dr-001.md
```

Free choice of tool and model — that is the point of the comparison. Two duties during the session:

- **Commit often**, and prefix every commit subject with `[agent]` or `[human]` according to who
  actually authored the change:

  ```
  [agent] add no-fit-polygon overlap test
  [human] fix rotation order in transform helper
  ```

  The prefix is what makes the timeline readable months later; a session with three commits is
  hard to annotate honestly.
- **Optional but encouraged:** run a session recorder such as SpecStory so the transcript lands in
  the repository as markdown. If your tool exports elsewhere, leave it there and point
  `session.yaml`'s `transcript.path` at the tool-native location instead. Either way, uncomment the
  template's `transcript:` block — it ships commented out, because most sessions have no recorder.

Your working tree on an attempt branch looks like this:

```
session/
├── session.yaml            # metadata: tool, model, duration, outcome (template in templates/)
├── annotations.md          # the annotated timeline (template in templates/)
├── postmortem.md           # half a page, written afterwards
├── decisions/dr-001.md     # one mini-ADR per unfamiliar-domain decision
├── harness/                # optional: agent config, rules files, MCP setup, as committed
└── transcript/             # optional: in-repo transcript, if your recorder writes one here
solver/                     # your code, in any language
solutions/<instance_id>.json   # the solution data
solutions/<instance_id>.svg    # the rendered figure: same directory, same stem as the JSON
```

Both optional directories may simply be absent. If your agent ran with no rules file and no MCP
server there is nothing to snapshot: leave `harness/` out, set `harness.config_paths: []` in
`session.yaml` and say so in `harness.notes`. If you ran no recorder, leave the template's
`transcript:` block commented out rather than naming a directory that does not exist.

A rendered SVG is only collected when it sits beside its solution JSON with the same stem — so
`solutions/hidden/<instance_id>.svg` after the hidden round closes. Render it there rather than
into the working directory, or it is silently left behind.

Only `session/` and `solutions/` are ever copied into `results/`; `solver/` stays on the branch,
where it remains readable and reviewable.

### 3. Annotate afterwards (~30 minutes)

Annotation is retrospective. During the session you only commit; afterwards you reconstruct the
timeline from `git log` and your transcript.

The files are already in `session/` from step 2; now you fill them in.

```sh
git log --reverse --format='%h %ad %s' --date=iso   # your raw material
```

- `session/session.yaml` — tool name and version, model, wall-clock duration, an honest
  `self_assessment` of 1–3 sentences.
- `session/annotations.md` — one line per move, four layers, in the grammar the linter enforces.
  Apply glyphs in hindsight only. For `?` and `??` use the earliest-cause rule: mark the earliest
  move from which the trouble became unrecoverable, not the move where the symptom surfaced.
- `session/postmortem.md` — the plan, where and why you intervened, where the agent got stuck, what
  you would do differently, and one thing worth stealing from your own session.
- `session/decisions/dr-XXX.md` — one record per decision you made in a domain you do not know:
  the decision, the options considered, which epistemic moves you used, confidence 1–5, and an
  outcome field you fill in later.

Then check your work locally:

```sh
make lint                                        # whole tree, exactly the form CI runs
uv run python scripts/lint_annotations.py session/annotations.md --session --repo . \
  --expect-branch "$(git branch --show-current)"   # the same checks, your files only
```

`--session` also validates `session/session.yaml` and cross-checks that the participant, challenge
and attempt number agree between the two files. `--expect-branch` additionally cross-checks both
against the branch name — that is the check that catches a `session.yaml` still saying
`participant: your-handle`, which the other forms pass. `make lint` runs it with the current
branch, so a green `make lint` predicts a green CI check; on `main` or a `retro/<cid>` branch the
branch cross-check is skipped with a notice.

### 4. Review for secrets, then push and open a draft PR

**Transcripts are the riskiest artifact in this repository.** The remote is public and the branch
is the record, so this pre-push review is the control that matters: CI's secret scan runs *after*
the push and can only report a key that is already published. Read what you are about to commit and
remove API keys, tokens, internal URLs and customer data.

What to scan: `session/` (especially `session/harness/` and any transcript directory, whether
committed here or exported by your tool elsewhere), `solver/`, and `solutions/`. Two commands — one
to read the content yourself, one to scan it:

```sh
git diff c001-start...HEAD -- session solver solutions    # the content, not just the file names
gitleaks detect --source . --config .gitleaks.toml --redact --no-git
git push -u origin attempt/c001/alice/1
gh pr create --draft --label attempt --base main \
  --title "attempt/c001/alice/1" \
  --body "Attempt 1 at étude no. 1. Draft on purpose — this PR is never merged."
```

`gitleaks` is a single binary — `brew install gitleaks`, or a build from
<https://github.com/gitleaks/gitleaks/releases>. `--no-git` scans the working tree as it stands,
which is what you want before the first push; `--redact` keeps any finding out of your terminal
scrollback. CI runs gitleaks over the pushed history on every push to `attempt/**`, with the same
config file.

The PR exists for CI and visibility. **Attempt PRs stay drafts and are never merged into `main`** —
the branch is the record. CI runs a secret scan, the annotation linter, and (when your branch
touches `solutions/**`) the challenge validator, whose summary line appears in the check summary.

### 5. Retry as often as you like

A retry is a new branch with `n` incremented, forked from the start tag again — never from your
previous attempt:

```sh
git switch -c attempt/c001/alice/2 c001-start
```

Starting from the tag keeps the position identical for every attempt. If you want to carry code
over from an earlier attempt, do it as one explicit, deliberate commit and annotate it:

```sh
git checkout attempt/c001/alice/1 -- solver/
git commit -m "[human] carry over solver/ from attempt 1"
```

In `annotations.md` that is a move like `+0:00  Plan  GROUND ! "carried over solver/ from attempt 1"`
— the difference between a fresh attempt and a warm start is exactly the kind of thing the retro
wants to see, so make it visible rather than silent.

---

## Worked scenarios

### A. First attempt at étude no. 1

```sh
git fetch --tags
git switch -c attempt/c001/alice/1 c001-start
mkdir -p session/decisions solver solutions
cp templates/session.yaml templates/annotations.md templates/postmortem.md session/
cp templates/decision-record.md session/decisions/dr-001.md
# ... four hours with your agent, committing as [agent] / [human] ...
uv run python challenges/c001/tools/validate.py \
  challenges/c001/instances/dev/c001-t1-dev-01.json solutions/c001-t1-dev-01.json
# ... ~30 min of annotation, filling in the files copied above ...
make lint
git push -u origin attempt/c001/alice/1
gh pr create --draft --label attempt --base main --title "attempt/c001/alice/1" --body "..."
```

### B. A second attempt at the same étude

```sh
git fetch --tags
git switch -c attempt/c001/alice/2 c001-start     # from the tag, not from attempt 1
git checkout attempt/c001/alice/1 -- solver/      # optional, and annotate it if you do
git commit -m "[human] carry over solver/ from attempt 1"
# ... session, annotation, lint, push, draft PR as in A ...
```

Both branches survive. `results/c001/alice/1/` and `results/c001/alice/2/` sit next to each other,
and the retro reads them as two takes on the same position.

### C. Closing a round: the retro (maintainer)

```sh
git fetch --all --tags
git switch -c retro/c001 main
make retro CHALLENGE=c001          # collect + stats + gallery -> retros/c001/
open retros/c001/gallery.html
```

`make retro` collects the attempt branches into `results/<cid>/<p>/<n>/` itself, so it is the only
command you need. `make collect` on its own collects without building a retro; if `results/` is
already up to date, `uv run python scripts/retro.py --challenge c001 --skip-collect` reuses the
tree as it stands.

`make retro` writes `retros/c001/retro.md` (a pre-filled skeleton), `retros/c001/stats.txt` and
`retros/c001/gallery.html`, and prints the brilliancies-and-blunders reel for pasting into a GitHub
Discussion. Fill in `retro.md` — the attempts index in alphabetical order, the steal list (moves
worth copying, with their anchors), the recurring traps, the wildcard review table with its
promotion decisions, taxonomy proposals, open questions, decisions for the next round — then open a
PR from `retro/<cid>` to `main`. **That PR is the stored record of the round**, and unlike attempt
PRs it does get merged. Open one GitHub Discussion per round for the conversation itself; the
Discussion is a manual step, on purpose.

Cross-annotation is the reliability check: a second person annotates somebody else's session
independently and commits it as
`results/c001/alice/1/reviews/bob.annotations.md` (same grammar, same linter). The reviewer's id
goes in the filename and nowhere else: the frontmatter keeps `participant: alice` — the annotated
participant's handle, which the linter cross-checks against that attempt's `session.yaml` — and the
reviewer may add `annotator: bob` beside it. Then:

```sh
uv run python scripts/compare_annotations.py \
  results/c001/alice/1/annotations.md \
  results/c001/alice/1/reviews/bob.annotations.md
```

This prints five agreement rows — `phase` (the bare phase), `stance` (the optional `>` / `~`
marker, counted only over the pairs where both files gave one, so `n/a` when neither did), `move`,
`glyph`, and `all three` (phase, move and glyph together) — then the disagreements, then any
`Lines that found no partner`. Systematic disagreement about what a move *means* is the evidence
for a definition-clarification PR labelled `taxonomy-change` — not a judgement about either
annotator.

### D. Adding étude no. 2

New études are ordinary PRs to `main` that add `challenges/c002/`. The contract — manifest fields,
the two CLI contracts, dev instances, tests, `demo.sh`, the dependency group — is a checklist in
[docs/adding-a-challenge.md](docs/adding-a-challenge.md). In short:

```sh
git switch -c etude/c002 main
mkdir -p challenges/c002/instances/dev challenges/c002/instances/hidden
mkdir -p challenges/c002/tools challenges/c002/tests challenges/c002/demo
# ... write challenge.yaml, tools, dev instances, tests, README.md, demo.sh ...
uv run python scripts/check_challenge.py challenges/c002
uv run pytest
```

The challenge ships with `status: draft`; the maintainer flips it to `open` at the same moment the
`c002-start` tag is created.

### E. Two études in flight at once

Nothing is global. Branch names, `results/` and `retros/` are all keyed by challenge id, so
`attempt/c001/alice/3` and `attempt/c002/alice/1` coexist without interference, and
`uv run python scripts/stats.py results --challenge c002` reports on one étude at a time
(`make stats` covers everything collected so far). Keep one attempt per branch and per working
tree; `git worktree add ../etudes-c002 attempt/c002/alice/1` is the tidy way to have both checked
out at once. Your participant id stays the same everywhere; only the challenge id and the attempt
counter change.

---

## Maintainer section

### One-off repository setup

`gh pr create --label <name>` fails if the label does not exist, so create the two the workflow
uses before the first round:

```sh
gh label create attempt --description "Draft PR for an attempt branch; never merged"
gh label create taxonomy-change --description "Changes TAXONOMY.md; needs the evidence in the PR body"
```

### Opening an étude

1. Land the challenge directory on `main` and confirm the contract:
   `uv run python scripts/check_challenge.py challenges/c001`.
2. Create the annotated start tag on the `main` commit that contains it:

   ```sh
   git tag -a c001-start -m "étude no. 1 — irregular shape nesting — start position"
   git push origin c001-start
   ```

   The tag is annotated (it carries the message and the date), it lives on `main`, it is named in
   `challenges/c001/challenge.yaml` as `start_tag`, and **it never moves once the status is `open`**.
   Later fixes to the tooling land on `main`; CI always validates solutions with `main`'s copy of
   `challenges/<cid>/`, so participants never need to rebase to pick up a validator fix.
3. Flip `status: draft` to `status: open` in `challenges/c001/challenge.yaml` and update the row in
   `challenges/README.md`. `check_challenge.py` refuses `status: open` unless the tag exists.
4. Announce the round in a GitHub Discussion.

### Closing an étude

Run the retro (scenario C), then publish the hidden set: the protocol lives in
`challenges/<cid>/README.md` and in the header of `challenges/<cid>/tools/make_hidden.sh` — the
seeds are never committed while the round is open, and the organizer publishes seeds, commits the
generated `instances/hidden/`, and flips `status: closed` in one PR. Participants then generate the
identical instances locally, run their own solver, and commit `solutions/hidden/` on their attempt
branch.

### House rules for every PR

- No comparison of participants anywhere in tooling or prose: grouping is always challenge →
  instance → alphabetical participant. `make check-words` enforces the vocabulary.
- Taxonomy changes only via a PR labelled `taxonomy-change`, motivated by wildcard evidence or by a
  session that demonstrably could not be described.
- `uv run pytest` and `make check-words` are green before you ask for review.
