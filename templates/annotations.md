---
participant: your-handle
challenge: c001
attempt: 1
taxonomy_version: "0.2"
session_date: 2026-09-12
---

# ---------------------------------------------------------------------------
# annotations.md — one line per move, written retrospectively (~30 min) from
# your git log and transcript. Vocabulary: see TAXONOMY.md (v0.2).
# Check it with: uv run python scripts/lint_annotations.py <path> --session
#
# Frontmatter (all five fields required, above):
#   participant       [a-z0-9-]+ ; must match session.yaml
#   challenge         c### ; must match session.yaml
#   attempt           int >= 1 ; must match session.yaml
#   taxonomy_version  the TAXONOMY.md version you annotated against, quoted
#   session_date      ISO date
#
# ---------------------------------------------------------------------------
# LINE GRAMMAR — fields separated by spaces or tabs, in this fixed order:
#
#   timestamp  phase  move  [glyph]  [(motifs)]  ["comment"]  [@anchor]
#
#   timestamp  "+H:MM" elapsed from session start; hours unbounded, minutes 00-59
#   phase      Recon | Plan | Build | Verify | Recover
#              optional stance suffix: ">" = acceleration, "~" = exploration
#   move       one of the 24 named moves, or X-<name>, or NOTE
#   glyph      !! | ! | !? | ?! | ? | ??            (optional)
#   motifs     (motif) or (motif, motif)            (optional, from the motif table)
#   comment    "free text in double quotes"         (optional)
#   anchor     @<7-40 hex>  a git commit             (optional, last field)
#              @t<n>        a transcript line/entry number
#
# RULES
#   - Timestamps must be non-decreasing (equal is fine).
#   - X-<name> requires a comment. So does every ??.
#   - At most one anchor per line, and it comes last.
#   - Unknown phase / move / motif / glyph is an error.
#   - Blank lines and lines starting with # are ignored.
#   - Glyphs are hindsight marks. Earliest-cause rule: put a ? or ?? on the
#     earliest move from which the trouble became unrecoverable, not on the
#     move where the symptom surfaced; give the symptom a motif instead.
#
# ---------------------------------------------------------------------------
# EXAMPLE LINES (delete these comments and write your own, unindented):
#
#   +0:00  Recon    SCOUT                      "asked for a repo map before touching anything"  @a1b2c3d
#   +0:31  Plan     SPEC       !               "wrote the failing acceptance test as the contract"
#   +0:40  Build>   DISPATCH                   "handed off module A and walked away"            @t204
#   +1:42  Build    TAKEOVER   ? (false-summit) "agent claimed done; I finished the parser by hand"
#   +2:05  Recover  RESET      !! (context-rot) "fresh context plus a DISTILL handoff; night and day"
#   +3:30  Verify   DEFER      ?!              "accepted its eviction policy unverified"
#   +3:44  Verify   X-timebox  (rabbit-hole)   "capped the detour at 20 minutes on a kitchen timer"
#   +3:52  Verify   NOTE                       "laptop slept for 10 minutes around +2:20"
#
# A full worked example lives in examples/example-session/annotations.md.
# ---------------------------------------------------------------------------
