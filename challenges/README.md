# Études

One directory per étude, named after its challenge id (`^c[0-9]{3}$`). The directory holds the
participant-facing statement, the organizer's tooling, the committed dev instances and the tests;
the human-readable title, the number and the current status live in `challenges/<id>/challenge.yaml`.

## Index

| id | no. | title | status | start tag |
|---|---|---|---|---|
| [c001](c001/) | 1 | Irregular Shape Nesting | open | `c001-start` |

The status column mirrors `status:` in `challenges/<id>/challenge.yaml` — keep the two in step when
you flip one:

- **draft** — under construction; do not start an attempt yet, the position can still move.
- **open** — the start tag exists and is frozen; fork `attempt/<cid>/<you>/<n>` from it and play.
- **closed** — the round is over; the hidden seeds have been published and `instances/hidden/` is
  committed, so late attempts can still be validated against the full set.

Start an attempt by following [CONTRIBUTING.md](../CONTRIBUTING.md); read
`challenges/<id>/README.md` for the rules of that particular étude.

## Design criteria for an étude

Every challenge in this repository is expected to satisfy all six. They exist so that the sessions
they produce are worth comparing — a challenge that fails any one of them tends to yield
annotations that all look the same.

1. **About four hours** of balanced effort, and explicitly **not one-shot-able** by a current agent.
   If a single well-written prompt finishes it, there is no process to annotate.
2. **Multi-file**, with at least one **early design decision**, so that planning style becomes
   visible in the timeline rather than hidden inside one function.
3. **Deliberately includes decisions in a domain most participants will not know.** This is what
   exercises the Epistemic family of moves (`TUTOR`, `OPTIONS`, `PROBE`, `CRITERIA`, `CROSSCHECK`,
   `DEFER`) — the central research interest of the lab.
4. **An objective check exists** — a hidden set released after the round closes — **alongside
   qualitative dimensions** such as maintainability and clarity that no tool can settle.
5. **Not a well-known problem** likely to sit in training data in finished form.
6. **Ships with a pinned starting tag** (`<cid>-start`, annotated, on `main`) that every attempt
   branch forks from, so everybody plays the same position.

## Adding an étude

The full contract — directory layout, `challenge.yaml` fields, the validator's `--json` output,
the participant solver CLI, dependency groups, tests, `demo.sh`, tagging — is a checklist in
[docs/adding-a-challenge.md](../docs/adding-a-challenge.md). Conformance is machine-checked:

```sh
uv run python scripts/check_challenge.py challenges/cXXX
```
