---
participant: example
challenge: c001
attempt: 1
taxonomy_version: "0.2"
session_date: 2026-09-12
---

# Example session (étude no. 1, tier 1)

Synthetic, and not a real attempt: this file exists so the linter, the stats
tooling and the templates have something complete to chew on. It demonstrates
all four layers, both stance markers, a wildcard move, both anchor kinds, and
the earliest-cause rule.

The moves sit inside the fenced block below. Everything outside the block is
prose for the reader, which the tooling ignores (TAXONOMY.md section 8).

```text
+0:00  Recon    SCOUT                       "asked for a map of challenges/c001 and a list of the validator error codes"   @t001
+0:12  Recon    TUTOR                       "had it explain no-fit polygons and bottom-left placement before I chose anything"  @t118
+0:26  Plan     OPTIONS                     "three overlap strategies with tradeoffs: no-fit polygon, pairwise intersection, raster masks"  @t204
+0:34  Plan     SPEC       !                "wrote the generate-solve-validate round trip as a failing test before any solver code"  @a71b4e0
+0:52  Build>   DISPATCH   ??  (yes-and)    "handed off a shelf packer built on my assumption that bounding boxes were good enough; it never pushed back and every later fix inherited the gap"  @c02d5a9
+1:47  Build~   SPIKE                       "throwaway timing harness: pairwise intersection over 40 parts, 5 degree rotation sweep"  @t512
+2:05  Build    TAKEOVER       (false-summit)  "agent reported the packer done with three parts hanging past y=W; I rewrote the fit test by hand, about 35 minutes"  @e4d7b13
+2:44  Recover  RESET      !!  (context-rot)   "fresh session seeded with a handoff doc after the old context started forgetting the transform order"
+2:46  Recover  DISTILL                     "handoff doc: geometry conventions, error codes, what the spike ruled out"      @9c1f6a8
+3:12  Build    PAIR                        "stepped through the rotation sweep together at 5 degree granularity"
+3:24  Verify   CROSSCHECK                  "ran validate.py --json over all five tier-1 dev instances and read the summaries"  @b8e02f4
+3:31  Verify   X-timebox      (rabbit-hole)   "capped the annealing detour at 20 minutes on a kitchen timer and dropped it when the timer went"
+3:44  Verify   DEFER      ?!               "accepted the agent's handling of TOL_AREA on touching edges without reading the pair test"
+3:52  Verify   NOTE                        "laptop slept for about 10 minutes around +2:20; the elapsed stamps already account for it"
```
