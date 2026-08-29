#!/usr/bin/env python3
"""Compare two annotation files of the *same* session.

Cross-annotation is the evidence-gathering step behind definition
clarifications: a reviewer re-annotates somebody else's session from the same
git log and transcript, and the two files are held side by side. Where two
careful readers label the same minute differently, the taxonomy definition is
ambiguous and wants a ``taxonomy-change`` PR.

    python scripts/compare_annotations.py \\
        results/c001/alice/1/reviews/bob.annotations.md \\
        results/c001/alice/1/annotations.md

Moves are aligned by their elapsed timestamp. When a timestamp carries a
different number of lines in the two files, the lines are paired in order and
the surplus is reported as present in only one file. The output is per-field
agreement (phase including its stance marker, move, glyph) as counts and
percentages, then the disagreements, then the unmatched lines.

This tool judges nobody: it reports where two readings differ, not which one
is right. It is informational and always exits 0.

Dependencies: Python 3.11 standard library + PyYAML (via ``etudes_lib``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import etudes_lib as lib  # noqa: E402  (needs the sys.path line above)

#: The fields that are compared, in report order.
FIELDS = ("phase", "move", "glyph")

NO_GLYPH = "-"


def phase_of(move) -> str:
    """``Build>`` -- the phase together with its stance marker."""
    return move.phase + (move.stance or "")


def glyph_of(move) -> str:
    return move.glyph or NO_GLYPH


def summarize(move) -> str:
    """``Build> DISPATCH ??`` -- the three compared fields, in grammar order."""
    return f"{phase_of(move)} {move.move} {glyph_of(move)}"


def align(a_moves: list, b_moves: list) -> tuple[list, list, list]:
    """Pair moves by timestamp.

    Returns ``(pairs, only_a, only_b)`` where ``pairs`` is a list of
    ``(a_move, b_move)`` and the two others hold the moves whose timestamp had
    no partner left. Within one timestamp the lines are paired in file order,
    which is the only alignment available once the minute is the same.
    """
    by_minute_a: dict[int, list] = {}
    by_minute_b: dict[int, list] = {}
    for mv in a_moves:
        by_minute_a.setdefault(mv.minutes, []).append(mv)
    for mv in b_moves:
        by_minute_b.setdefault(mv.minutes, []).append(mv)

    pairs: list = []
    only_a: list = []
    only_b: list = []
    for minute in sorted(set(by_minute_a) | set(by_minute_b)):
        left = by_minute_a.get(minute, [])
        right = by_minute_b.get(minute, [])
        common = min(len(left), len(right))
        pairs.extend(zip(left[:common], right[:common]))
        only_a.extend(left[common:])
        only_b.extend(right[common:])
    return pairs, only_a, only_b


def agreement(pairs: list) -> dict:
    """Per-field agreement counts and percentages over the aligned pairs."""
    total = len(pairs)
    out: dict[str, dict] = {}
    for fieldname in FIELDS:
        getter = {"phase": phase_of, "move": lambda m: m.move, "glyph": glyph_of}[
            fieldname
        ]
        agree = sum(1 for a, b in pairs if getter(a) == getter(b))
        out[fieldname] = {
            "agree": agree,
            "total": total,
            "percent": (100.0 * agree / total) if total else None,
        }
    both = sum(
        1
        for a, b in pairs
        if phase_of(a) == phase_of(b)
        and a.move == b.move
        and glyph_of(a) == glyph_of(b)
    )
    out["all three"] = {
        "agree": both,
        "total": total,
        "percent": (100.0 * both / total) if total else None,
    }
    return out


def disagreements(pairs: list) -> list[dict]:
    """Every pair where at least one of the three fields differs."""
    out = []
    for a, b in pairs:
        if phase_of(a) == phase_of(b) and a.move == b.move and glyph_of(a) == glyph_of(b):
            continue
        out.append(
            {
                "timestamp": a.timestamp,
                "a": {
                    "line": a.line,
                    "phase": phase_of(a),
                    "move": a.move,
                    "glyph": glyph_of(a),
                },
                "b": {
                    "line": b.line,
                    "phase": phase_of(b),
                    "move": b.move,
                    "glyph": glyph_of(b),
                },
                "text": f"{a.timestamp}: A={summarize(a)} | B={summarize(b)}",
            }
        )
    return out


def _unmatched(moves: list) -> list[dict]:
    return [
        {
            "timestamp": mv.timestamp,
            "line": mv.line,
            "phase": phase_of(mv),
            "move": mv.move,
            "glyph": glyph_of(mv),
            "text": f"{mv.timestamp}: {summarize(mv)}",
        }
        for mv in moves
    ]


def _fmt_percent(value: Optional[float]) -> str:
    return "  n/a" if value is None else f"{value:5.1f}%"


def compare(path_a: Path, path_b: Path) -> dict:
    """Parse both files and build the whole comparison as plain data."""
    meta_a, moves_a, lint_a = lib.parse_annotations_file(path_a)
    meta_b, moves_b, lint_b = lib.parse_annotations_file(path_b)

    notes: list[str] = [str(m) for m in lint_a] + [str(m) for m in lint_b]
    for key in ("participant", "challenge", "attempt"):
        va, vb = meta_a.get(key), meta_b.get(key)
        if va is not None and vb is not None and va != vb:
            notes.append(
                f"the two files disagree about {key} ({va!r} vs {vb!r}); they "
                "should be two readings of one session"
            )

    pairs, only_a, only_b = align(moves_a, moves_b)
    return {
        "a": str(path_a),
        "b": str(path_b),
        "moves": {"a": len(moves_a), "b": len(moves_b)},
        "aligned": len(pairs),
        "agreement": agreement(pairs),
        "disagreements": disagreements(pairs),
        "only_in_a": _unmatched(only_a),
        "only_in_b": _unmatched(only_b),
        "notes": notes,
    }


def render(report: dict) -> str:
    """The human-readable report."""
    lines: list[str] = []
    lines.append(f"A = {report['a']}")
    lines.append(f"B = {report['b']}")
    lines.append(
        f"{report['moves']['a']} annotated line(s) in A, "
        f"{report['moves']['b']} in B; {report['aligned']} aligned by timestamp."
    )
    lines.append("")

    lines.append("Agreement")
    lines.append("---------")
    if report["aligned"] == 0:
        lines.append("  no lines shared a timestamp, so there is nothing to compare.")
    else:
        for name, data in report["agreement"].items():
            lines.append(
                f"  {name:<10} {data['agree']:>4} / {data['total']:<4} "
                f"{_fmt_percent(data['percent'])}"
            )
    lines.append("")

    lines.append("Disagreements")
    lines.append("-------------")
    if not report["disagreements"]:
        lines.append("  none: every aligned line has the same phase, move and glyph.")
    else:
        for item in report["disagreements"]:
            lines.append("  " + item["text"])
    lines.append("")

    lines.append("Lines present in only one file")
    lines.append("------------------------------")
    if not report["only_in_a"] and not report["only_in_b"]:
        lines.append("  none: every line found a partner at its timestamp.")
    else:
        for item in report["only_in_a"]:
            lines.append("  only in A: " + item["text"])
        for item in report["only_in_b"]:
            lines.append("  only in B: " + item["text"])

    if report["notes"]:
        lines.append("")
        lines.append("Notes")
        lines.append("-----")
        for note in report["notes"]:
            lines.append("  " + note)

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compare_annotations.py",
        description=(
            "Compare two annotation files of the same session (for example a "
            "reviewer's copy against the original) and report where the two "
            "readings differ."
        ),
        epilog="Informational only: this command always exits 0.",
    )
    parser.add_argument("a", metavar="A", help="first annotations.md")
    parser.add_argument("b", metavar="B", help="second annotations.md")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print the comparison as one JSON object instead of text",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    path_a = Path(args.a)
    path_b = Path(args.b)

    for path in (path_a, path_b):
        if not path.is_file():
            # A notice, not an error: this command is informational and always
            # exits 0, and the report below still says "file not found" on the
            # side that is missing.
            print(
                f"notice: {path}: no such annotations file. Pass two "
                "annotations.md paths, for example the reviewer copy under "
                "reviews/ and the original next to session.yaml.",
                file=sys.stderr,
            )

    report = compare(path_a, path_b)
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except lib.EtudesError as exc:  # pragma: no cover - defensive
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(0)
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(130)
