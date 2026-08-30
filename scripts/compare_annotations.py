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

Moves are aligned by their elapsed timestamp. Two annotators are under no
obligation to list the moves of one minute in the same order, so lines that
share a timestamp are paired by what they say -- same move and glyph first,
then same move, then same glyph -- and whatever is left over is reported as
unpaired rather than guessed at. The output is five agreement rows (phase,
stance, move, glyph, and ``all three`` -- phase, move and glyph together) as
counts and percentages, then the disagreements, then the lines that found no
partner.

``phase`` is the bare phase. The stance marker (``>`` / ``~``) of TAXONOMY §6
is optional, so it gets its own row and is counted only over the pairs where
both files supplied one: an omitted optional marker is not a differing
reading of the minute.

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

#: The fields compared over every aligned pair, in report order.
FIELDS = ("phase", "move", "glyph")

#: Compared only where both files supplied one; reported on its own row.
OPTIONAL_FIELD = "stance"

NO_GLYPH = "-"

#: Printed after an unpaired line whose minute *is* used by the other file.
SAME_MINUTE_NOTE = "   [the other file has that minute, but no line matched]"


def phase_of(move) -> str:
    """``Build`` -- the bare phase, without the optional stance marker."""
    return move.phase


def stance_of(move) -> Optional[str]:
    """``>``, ``~`` or ``None`` -- the optional stance marker of TAXONOMY §6."""
    return move.stance


def glyph_of(move) -> str:
    return move.glyph or NO_GLYPH


def phase_with_stance(move) -> str:
    """``Build>`` -- what the line actually says, for display only."""
    return move.phase + (move.stance or "")


def summarize(move) -> str:
    """``Build> DISPATCH ??`` -- the line as written, in grammar order."""
    return f"{phase_with_stance(move)} {move.move} {glyph_of(move)}"


def _match_group(left: list, right: list) -> tuple[list, list, list]:
    """Pair the lines of one timestamp by what they say.

    Three greedy passes over ``left`` in file order -- same move *and* glyph,
    then same move, then same glyph -- so two annotators who recorded the same
    minute in a different order still line up. Timestamps are minute-granular
    by design, so a minute routinely carries several lines and file order
    inside it carries no meaning.

    "No glyph" counts as a glyph in the third pass, so it is the weakest
    signal of the three; it runs last for that reason.

    Only when exactly one line is left on each side are those two paired: the
    pairing is then unambiguous, which keeps a genuine one-against-one
    disagreement (``Build NUDGE !!`` against ``Build REDIRECT ?``) visible.
    Anything else left over is reported as unpaired rather than guessed at.
    """
    remaining_b = list(right)
    pairs: list = []

    # Pass by pass, each over the lines that are still unpaired.
    pool = list(left)
    for key in (
        lambda m: (m.move, glyph_of(m)),
        lambda m: m.move,
        lambda m: glyph_of(m),
    ):
        still: list = []
        for mv in pool:
            wanted = key(mv)
            index = next(
                (i for i, other in enumerate(remaining_b) if key(other) == wanted),
                None,
            )
            if index is None:
                still.append(mv)
            else:
                pairs.append((mv, remaining_b.pop(index)))
        pool = still

    if len(pool) == 1 and len(remaining_b) == 1:
        pairs.append((pool[0], remaining_b[0]))
        pool, remaining_b = [], []

    pairs.sort(key=lambda pair: pair[0].line)
    return pairs, pool, remaining_b


def align(a_moves: list, b_moves: list) -> tuple[list, list, list]:
    """Pair moves by timestamp, then by content within the timestamp.

    Returns ``(pairs, only_a, only_b)`` where ``pairs`` is a list of
    ``(a_move, b_move)`` and the two others hold the moves that found no
    partner. See ``_match_group`` for how one timestamp is resolved.
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
        matched, left_over_a, left_over_b = _match_group(
            by_minute_a.get(minute, []), by_minute_b.get(minute, [])
        )
        pairs.extend(matched)
        only_a.extend(left_over_a)
        only_b.extend(left_over_b)
    return pairs, only_a, only_b


def _agrees_on_the_three(a, b) -> bool:
    return (
        phase_of(a) == phase_of(b)
        and a.move == b.move
        and glyph_of(a) == glyph_of(b)
    )


def _stance_differs(a, b) -> bool:
    """True only when both sides marked a stance and the two marks differ.

    A bare phase against a marked one is an omitted optional field, not a
    differing reading; see TAXONOMY §6.
    """
    return (
        stance_of(a) is not None
        and stance_of(b) is not None
        and stance_of(a) != stance_of(b)
    )


def _row(agree: int, total: int) -> dict:
    return {
        "agree": agree,
        "total": total,
        "percent": (100.0 * agree / total) if total else None,
    }


def agreement(pairs: list) -> dict:
    """Per-field agreement counts and percentages over the aligned pairs."""
    total = len(pairs)
    out: dict[str, dict] = {}
    getters = {"phase": phase_of, "move": lambda m: m.move, "glyph": glyph_of}
    for fieldname in FIELDS:
        getter = getters[fieldname]
        out[fieldname] = _row(
            sum(1 for a, b in pairs if getter(a) == getter(b)), total
        )
        if fieldname == "phase":
            # The stance marker is optional, so its row is counted only over
            # the pairs where both files supplied one.
            both_marked = [
                (a, b)
                for a, b in pairs
                if stance_of(a) is not None and stance_of(b) is not None
            ]
            out[OPTIONAL_FIELD] = _row(
                sum(1 for a, b in both_marked if stance_of(a) == stance_of(b)),
                len(both_marked),
            )
    out["all three"] = _row(
        sum(1 for a, b in pairs if _agrees_on_the_three(a, b)), total
    )
    return out


def _sides(move) -> dict:
    return {
        "line": move.line,
        "phase": phase_of(move),
        "stance": stance_of(move),
        "move": move.move,
        "glyph": glyph_of(move),
    }


def disagreements(pairs: list) -> list[dict]:
    """Every pair where a compared field differs.

    That is phase, move or glyph -- plus stance where both files marked one.
    """
    out = []
    for a, b in pairs:
        if _agrees_on_the_three(a, b) and not _stance_differs(a, b):
            continue
        out.append(
            {
                "timestamp": a.timestamp,
                "a": _sides(a),
                "b": _sides(b),
                "text": f"{a.timestamp}: A={summarize(a)} | B={summarize(b)}",
            }
        )
    return out


def _unmatched(moves: list, other_minutes: set) -> list[dict]:
    """The lines that found no partner, each flagged with why.

    ``shared_timestamp`` is true when the other file does have lines at that
    minute: none of them matched, and the matcher declined to guess. Such a
    line is not "at a timestamp the other file never used", so a reader must
    be able to tell the two cases apart.
    """
    return [
        {
            "timestamp": mv.timestamp,
            "shared_timestamp": mv.minutes in other_minutes,
            **_sides(mv),
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
        "only_in_a": _unmatched(only_a, {mv.minutes for mv in moves_b}),
        "only_in_b": _unmatched(only_b, {mv.minutes for mv in moves_a}),
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
        lines.append(
            "  phase is the bare phase; the optional stance marker (> / ~) has"
        )
        lines.append(
            "  its own row, counted only over the pairs where both files gave"
        )
        lines.append(
            "  one. 'all three' is phase, move and glyph."
        )
    lines.append("")

    lines.append("Disagreements")
    lines.append("-------------")
    if not report["disagreements"]:
        lines.append(
            "  none: every aligned line has the same phase, move and glyph "
            "(and the same stance where both files gave one)."
        )
    else:
        for item in report["disagreements"]:
            lines.append("  " + item["text"])
    lines.append("")

    lines.append("Lines that found no partner")
    lines.append("---------------------------")
    if not report["only_in_a"] and not report["only_in_b"]:
        lines.append("  none: every line was paired with one in the other file.")
    else:
        for side, key in (("A", "only_in_a"), ("B", "only_in_b")):
            for item in report[key]:
                suffix = SAME_MINUTE_NOTE if item["shared_timestamp"] else ""
                lines.append(f"  only in {side}: " + item["text"] + suffix)

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
