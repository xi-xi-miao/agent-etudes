#!/usr/bin/env python3
"""Reference solver for the fixture challenge c999 (standard library only).

Follows the participant-facing solver CLI contract:

    python tools/baseline.py <instance.json> --out <solution.json>
                             [--time-budget 60] [--seed N]

It writes the trivially valid solution ``{"instance_id": ..., "value": target}``.
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("instance", help="path to the instance JSON")
    parser.add_argument("--out", required=True, help="path of the solution to write")
    parser.add_argument(
        "--time-budget",
        type=float,
        default=60.0,
        help="wall-clock seconds the solver may use (ignored: this one is instant)",
    )
    parser.add_argument(
        "--seed", type=int, default=0, help="random seed (ignored: fully deterministic)"
    )
    args = parser.parse_args(argv)

    try:
        with open(args.instance, "r", encoding="utf-8") as fh:
            instance = json.load(fh)
    except OSError as exc:
        print(f"could not read instance: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"could not parse instance JSON: {exc}", file=sys.stderr)
        return 2

    solution = {"instance_id": instance["instance_id"], "value": instance["target"]}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(solution, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
