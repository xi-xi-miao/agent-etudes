#!/usr/bin/env python3
"""Validator for the fixture challenge c999 (standard library only).

Contract (identical to the real challenges, see docs/adding-a-challenge.md):

    python tools/validate.py <instance.json> <solution.json> [--json]

A solution is a JSON object ``{"instance_id": str, "value": number}`` and it is
valid exactly when ``value == target`` from the instance.

Output: one human-readable line ("VALID value=10" / "INVALID ...") and, with
``--json``, a final stdout line holding

    {"valid": bool, "summary": str,
     "errors": [{"code": str, "message": str}],
     "measures": {"value": number}}

Error codes: SCHEMA, INSTANCE_MISMATCH, WRONG_VALUE.
Exit status: 0 valid, 1 invalid, 2 unreadable input.
"""

from __future__ import annotations

import argparse
import json
import sys


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("instance", help="path to the instance JSON")
    parser.add_argument("solution", help="path to the solution JSON")
    parser.add_argument(
        "--json",
        action="store_true",
        help="print a machine-readable JSON object as the last stdout line",
    )
    args = parser.parse_args(argv)

    try:
        instance = _read_json(args.instance)
        solution = _read_json(args.solution)
    except OSError as exc:
        print(f"could not read input: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"could not parse JSON: {exc}", file=sys.stderr)
        return 2

    errors: list[dict] = []
    value = solution.get("value")

    if not isinstance(instance, dict) or "target" not in instance:
        print("instance JSON has no 'target'", file=sys.stderr)
        return 2

    if not isinstance(solution, dict) or "instance_id" not in solution:
        errors.append(
            {"code": "SCHEMA", "message": "solution must be an object with instance_id and value"}
        )
    elif solution["instance_id"] != instance.get("instance_id"):
        errors.append(
            {
                "code": "INSTANCE_MISMATCH",
                "message": (
                    f"solution is for instance {solution['instance_id']!r}, "
                    f"instance file is {instance.get('instance_id')!r}"
                ),
            }
        )

    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.append({"code": "SCHEMA", "message": "value must be a number"})
        value = None
    elif value != instance["target"]:
        errors.append(
            {
                "code": "WRONG_VALUE",
                "message": f"value {value} does not equal target {instance['target']}",
            }
        )

    valid = not errors
    if valid:
        summary = f"VALID value={value}"
    else:
        summary = "INVALID " + "; ".join(e["message"] for e in errors)
    print(summary)

    if args.json:
        print(
            json.dumps(
                {
                    "valid": valid,
                    "summary": summary,
                    "errors": errors,
                    "measures": {"value": value},
                },
                sort_keys=True,
            )
        )
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
