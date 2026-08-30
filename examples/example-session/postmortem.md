# Postmortem — example, c001, attempt 1

*Synthetic fixture. Written the way a real postmortem should read, about a
session that never happened.*

## The plan

Treat the strip as a shelf-packing problem first, get something VALID on disk
inside the first hour, then replace the bounding-box approximation with real
polygon geometry and spend the back half of the session climbing utilization.
I had never touched irregular nesting, so the plan deliberately started with a
`TUTOR` (+0:12, @t118) and an `OPTIONS` (+0:26, @t204) before I committed to an
overlap strategy, and with a `SPEC` (+0:34, @a71b4e0) that pinned the
generate → solve → validate round trip as a failing test.

## Where and why I intervened

Twice, and the second one was the session.

The `TAKEOVER` at +2:05 (@e4d7b13) was reactive: the agent reported the packer
finished while three parts sat past `x = W`, and I rewrote the containment test
by hand rather than explain it a third time. That cost about 35 minutes and it
is not the move I would defend.

The `RESET` at +2:44 is the one I would defend. The context had started
contradicting itself on the transform order — rotate about the local origin,
*then* translate — which I had already corrected twice. Instead of correcting a
third time I wrote a `DISTILL` handoff (+2:46, @9c1f6a8) with the geometry
conventions, the validator's error codes and what the spike had ruled out, and
started a fresh session from it. The difference was immediate; the `PAIR` at
+3:12 went cleanly in one pass.

## Where the agent got stuck

`yes-and` at +0:52, `false-summit` at +2:05, `context-rot` at +2:44 — and they
are the same story told three times. I handed off a shelf packer resting on my
own untested assumption that axis-aligned bounding boxes were a good enough
proxy for these parts. The agent built exactly what I asked for, cheerfully, and
never once said "this will cap you around 50%". Every later fix was a patch on
that foundation, which is why the blunder glyph sits on the `DISPATCH` and not
on the `TAKEOVER` where the symptom finally surfaced.

The `rabbit-hole` at +3:31 was mine, not the agent's: an annealing detour with
no chance of paying off in the time left. The `X-timebox` move is what saved it
— a hard 20-minute cap on a kitchen timer, and I actually stopped when it went.

## What I'd do differently

Put a `PROBE` on the packer before dispatching it: make the agent argue for the
bounding-box approximation and state what it would cost, instead of me assuming
and it agreeing. That is the +0:52 counterfactual under the earliest-cause rule,
and it is a two-minute move that would have changed the whole afternoon.

Second: run the `SPIKE` before the `DISPATCH`, not an hour after it. I had the
timing answer at +1:47 — pairwise intersection over 40 parts is fast enough —
and by then I had already built the thing that assumed it wasn't.

## One thing to steal from my own session

`RESET` + `DISTILL` as a pair, +2:44 and +2:46 (@9c1f6a8). Not the reset alone —
a reset without a handoff doc just throws away two hours of hard-won context.
Writing the handoff first, then starting the fresh session from it, converted a
degrading context into a clean one in four minutes. Go read the handoff doc at
that anchor; it is shorter than you would expect, and the brevity is the point.
