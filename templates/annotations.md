---
participant: your-handle
challenge: c001
attempt: 1
taxonomy_version: "0.2"
session_date: 2026-09-12
---

# annotations.md

One line per move, written retrospectively (about 30 minutes) from your git log
and your transcript. Vocabulary: TAXONOMY.md (v0.2). Check the file with

    uv run python scripts/lint_annotations.py <path> --session

## Layout

This file is markdown. Everything outside a fenced code block is prose for the
reader and the tooling ignores it; the move lines go inside a fenced code block
(a line of three backticks followed by `text` opens it, a bare line of three
backticks closes it). Once the file has a fence, a move line outside every
fence is an error. A file with no fence at all is read line by line, as before.

## Frontmatter (all five fields required, above)

| Field | Value |
|---|---|
| `participant` | `[a-z0-9-]+`; must match `session.yaml` |
| `challenge` | `c###`; must match `session.yaml` |
| `attempt` | whole number >= 1; must match `session.yaml` |
| `taxonomy_version` | the TAXONOMY.md version you annotated against, quoted |
| `session_date` | ISO date |

## Line grammar

Fields are separated by spaces or tabs, in this fixed order:

    timestamp  phase  move  [glyph]  [(motifs)]  ["comment"]  [@anchor]

| Field | Form |
|---|---|
| timestamp | `+H:MM` elapsed from session start; hours unbounded, minutes 00-59. The origin is when you started the session: your first reading of the challenge, not your first commit (TAXONOMY.md section 8) |
| phase | `Recon`, `Plan`, `Build`, `Verify` or `Recover`, with an optional stance suffix: `>` = acceleration, `~` = exploration |
| move | one of the 24 named moves, or `X-<name>`, or `NOTE` |
| glyph | `!!`, `!`, `!?`, `?!`, `?` or `??` (optional) |
| motifs | `(motif)` or `(motif, motif)` (optional, from the motif table) |
| comment | `"free text in double quotes"` (optional) |
| anchor | `@<7-40 hex>` for a git commit, or `@t<n>` for a transcript line or entry number (optional, last field) |

## Rules

- Timestamps must be non-decreasing (equal is fine).
- `X-<name>` requires a comment. So does every `??`.
- At most one anchor per line, and it comes last.
- Unknown phase / move / motif / glyph is an error.
- Inside the fence, blank lines and lines starting with `#` are ignored.
- Glyphs are hindsight marks. Earliest-cause rule: put a `?` or `??` on the
  earliest move from which the trouble became unrecoverable, not on the move
  where the symptom surfaced; give the symptom a motif instead.

## Moves

The specimen lines below are commented out. Delete them and write your own in
the same block, unindented. A full worked example lives in
`examples/example-session/annotations.md`.

```text
#   +0:00  Recon    SCOUT                      "asked for a repo map before touching anything"  @a1b2c3d
#   +0:31  Plan     SPEC       !               "wrote the failing acceptance test as the contract"
#   +0:40  Build>   DISPATCH                   "handed off module A and walked away"            @t204
#   +1:42  Build    TAKEOVER   ? (false-summit) "agent claimed done; I finished the parser by hand"
#   +2:05  Recover  RESET      !! (context-rot) "fresh context plus a DISTILL handoff; night and day"
#   +3:30  Verify   DEFER      ?!              "accepted its eviction policy unverified"
#   +3:44  Verify   X-timebox  (rabbit-hole)   "capped the detour at 20 minutes on a kitchen timer"
#   +3:52  Verify   NOTE                       "laptop slept for 10 minutes around +2:20"
```
