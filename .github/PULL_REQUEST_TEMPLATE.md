<!-- Delete the sections that do not apply. -->

## What this is

<!-- One or two sentences. For an attempt PR: challenge id, participant, attempt number. -->

## Checklist

- [ ] **I reviewed my transcript and session files for secrets** (API keys, tokens, internal URLs,
      customer data) before pushing.
- [ ] `uv run python scripts/lint_annotations.py session/annotations.md --session` passes locally,
      or this PR touches no annotations.
- [ ] `uv run pytest` and `bash scripts/check_words.sh` are green, or this PR touches no code.

---

### Attempt PR (`attempt/<cid>/<you>/<n>` → `main`)

Open it as a **draft**, label it `attempt`. It exists for CI and visibility only and **is never
merged** — the branch itself is the record. Leave it open for the round.

- Attempt number: <!-- n --> · Challenge: <!-- cXXX --> · Forked from: <!-- cXXX-start -->
- Anything you want readers to look at first (a `!!` line, a decision record, a dead end):

### Retro PR (`retro/<cid>` → `main`)

The stored record of a round; this one **does** get merged. It should contain `retros/<cid>/`
(`retro.md`, `stats.txt`, `gallery.html`) and the `results/<cid>/…` directories produced by
`make retro CHALLENGE=<cid>`.

- [ ] `retro.md` is filled in: steal list, recurring traps, wildcard review, decisions for next round.
- [ ] The GitHub Discussion for the round is open and linked here.
- [ ] Taxonomy proposals, if any, are split out into their own `taxonomy-change` PR.
