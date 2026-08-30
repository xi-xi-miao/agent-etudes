#!/usr/bin/env python3
"""Distributions, phase timelines and the brilliancies-and-blunders reel.

Reads every ``session.yaml`` + ``annotations.md`` pair under a results tree
(default: ``results/`` in this repository) and prints one plain-text report,
sectioned per challenge and then over everything found:

1. move frequency by family -- one column per session plus a total; the
   ``Wildcard`` family lists each ``X-<name>`` with its count and the number
   of distinct participants who used it (the evidence a wildcard is ready to
   be promoted into the taxonomy). ``NOTE`` is not a move and is never
   counted.
2. glyph distribution,
3. motif counts,
4. ASCII phase timelines -- one row per (challenge, participant, attempt),
   one character per five minutes, each cell sampled at its own minute (so a
   phase that begins and ends between two cells never shows),
5. the brilliancies and blunders reel -- every ``!!`` and ``??`` line with its
   comment, alphabetical by participant and then by attempt.

``--grep TOKEN`` skips the report and prints the annotation lines whose move
or motif is exactly ``TOKEN`` (case-sensitive), one per line, prefixed
``<cid>/<participant>/<n>:<line>:``.

Nothing here orders anybody by anything. Rows follow the fixed vocabulary
order of TAXONOMY.md, wildcard names are alphabetical, and sessions are
grouped challenge -> participant (alphabetical) -> attempt. There is
deliberately no per-participant comparison measure: this is a study group's
notebook, not a contest.

Dependencies: Python 3.11 standard library + PyYAML (through ``etudes_lib``).
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:  # allow `python path/to/stats.py`
    sys.path.insert(0, str(_SCRIPTS_DIR))

from etudes_lib import (  # noqa: E402  (path juggling has to come first)
    CHALLENGE_ID_RE,
    FAMILIES,
    GLYPHS,
    MOTIFS,
    MOVES,
    NOTE_MOVE,
    PHASE_LETTERS,
    EtudesError,
    Move,
    Session,
    move_family,
    repo_root_from,
    walk_results,
)

__all__ = [
    "FAMILY_HEADINGS",
    "WILDCARD_FAMILY",
    "MINUTES_PER_CELL",
    "build_parser",
    "default_results_root",
    "session_label",
    "counted_moves",
    "timeline_cells",
    "phase_timeline",
    "grep_lines",
    "render_report",
    "main",
]

#: The five named families of TAXONOMY.md plus the escape hatch. ``FAMILIES``
#: in etudes_lib holds the named five only.
WILDCARD_FAMILY = "Wildcard"
FAMILY_HEADINGS = tuple(FAMILIES) + (WILDCARD_FAMILY,)

#: One character of an ASCII timeline covers this many minutes (HANDOFF 6.3).
MINUTES_PER_CELL = 5

#: Hard cap on a timeline row (100 hours) so a typo in duration_wall_minutes
#: cannot produce a megabyte-long line.
MAX_TIMELINE_CELLS = 100 * 60 // MINUTES_PER_CELL
_UNKNOWN_CHALLENGE = "(no challenge id)"
_UNKNOWN_PARTICIPANT = "(unknown)"

_LEGEND = "R=Recon  P=Plan  B=Build  V=Verify  C=Recover  . = before the first move"


# --------------------------------------------------------------------------
# Small helpers over a Session
# --------------------------------------------------------------------------


def session_label(session: Session) -> str:
    """``alice/2`` -- the per-session column heading inside a challenge."""
    participant = session.participant or _UNKNOWN_PARTICIPANT
    return f"{participant}/{session.attempt}"


def session_challenge(session: Session) -> str:
    return session.cid or _UNKNOWN_CHALLENGE


def counted_moves(session: Session) -> list[Move]:
    """The annotation lines that count as moves: everything except ``NOTE``."""
    return [m for m in session.moves if m.move != NOTE_MOVE]


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def timeline_cells(session: Session) -> tuple[int, Optional[str]]:
    """How many characters this session's timeline gets, and why.

    Preferred source is ``duration_wall_minutes`` from ``session.yaml``:
    ``ceil(duration / 5)`` characters. When that field is missing or unusable
    the timeline instead stops at the last annotated line (``NOTE`` included,
    since the question here is how long the session ran, not which phase was
    active) and the second element of the return value is a sentence for
    stderr explaining the fallback.
    """
    duration = session.session.get("duration_wall_minutes")
    if _is_number(duration) and duration > 0:
        cells = max(1, math.ceil(duration / MINUTES_PER_CELL))
        if cells > MAX_TIMELINE_CELLS:
            return MAX_TIMELINE_CELLS, (
                f"{session.label}: duration_wall_minutes is {duration!r}; the "
                f"timeline is clipped at {MAX_TIMELINE_CELLS * MINUTES_PER_CELL} "
                "minutes (check the value)."
            )
        return cells, None

    if duration is None:
        why = "session.yaml has no duration_wall_minutes"
    else:
        why = f"session.yaml duration_wall_minutes is {duration!r}"
    if session.moves:
        last = max(m.minutes for m in session.moves)
        cells = last // MINUTES_PER_CELL + 1
        note = (
            f"{session.label}: {why}; the timeline stops at the last annotated "
            f"line (+{last // 60}:{last % 60:02d}) instead."
        )
        return max(1, cells), note
    return 1, f"{session.label}: {why} and the file holds no annotation lines."


def phase_timeline(moves: Iterable[Move], cells: int) -> str:
    """Render one ASCII phase timeline.

    Cell ``i`` covers minute ``5 * i`` and shows the phase letter of the
    latest move at or before it; ``.`` means the session had not started
    annotating yet. ``NOTE`` lines never set a phase and the stance marker
    (``>`` / ``~``) is not shown -- the timeline is about phases only.
    """
    ordered = sorted(
        [m for m in moves if m.move != NOTE_MOVE], key=lambda m: m.minutes
    )
    out: list[str] = []
    index = 0
    current = "."
    for cell in range(cells):
        minute = cell * MINUTES_PER_CELL
        while index < len(ordered) and ordered[index].minutes <= minute:
            current = PHASE_LETTERS.get(ordered[index].phase, "?")
            index += 1
        out.append(current)
    return "".join(out)


def _raw_line(session: Session, line_no: int) -> str:
    """The original text of one line of a session's ``annotations.md``."""
    path = Path(session.dir) / "annotations.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1].rstrip()
    return ""


# --------------------------------------------------------------------------
# Table rendering
# --------------------------------------------------------------------------


class _Row(NamedTuple):
    """One table line. ``values is None`` makes it a heading inside the table."""

    text: str
    values: Optional[list[int]] = None
    suffix: str = ""


def _render_table(columns: list[str], rows: list[_Row], indent: str = "  ") -> list[str]:
    """Format a label column, one integer column per name, and free suffixes."""
    label_width = max([len(r.text) for r in rows] + [0])
    widths = []
    for i, name in enumerate(columns):
        cells = [len(str(r.values[i])) for r in rows if r.values is not None]
        widths.append(max([len(name)] + cells))

    header = " " * label_width + "".join(
        "  " + name.rjust(widths[i]) for i, name in enumerate(columns)
    )
    out = [indent + header.rstrip()]
    for row in rows:
        if row.values is None:
            out.append(indent + row.text)
            continue
        line = row.text.ljust(label_width) + "".join(
            "  " + str(row.values[i]).rjust(widths[i]) for i in range(len(columns))
        )
        if row.suffix:
            line = line + "   " + row.suffix
        out.append(indent + line.rstrip())
    return out


def _totalled(counts: list[int]) -> list[int]:
    return counts + [sum(counts)]


# --------------------------------------------------------------------------
# The four count tables
# --------------------------------------------------------------------------


def _move_rows(groups: list[list[Session]]) -> list[_Row]:
    """Rows for the move-frequency table, in TAXONOMY.md vocabulary order."""
    rows: list[_Row] = []
    per_group_moves = [
        [m for s in group for m in counted_moves(s)] for group in groups
    ]

    for family in FAMILY_HEADINGS:
        rows.append(_Row(family))
        if family == WILDCARD_FAMILY:
            # Wildcard names are whatever participants invented; alphabetical
            # order, never by count -- the numbers are evidence, not a contest.
            names = sorted(
                {
                    m.move
                    for moves in per_group_moves
                    for m in moves
                    if move_family(m.move) == WILDCARD_FAMILY
                }
            )
            if not names:
                rows.append(_Row("  (none used)"))
                continue
            for name in names:
                counts = [
                    sum(1 for m in moves if m.move == name) for moves in per_group_moves
                ]
                users = sorted(
                    {
                        s.participant or _UNKNOWN_PARTICIPANT
                        for group in groups
                        for s in group
                        if any(m.move == name for m in counted_moves(s))
                    }
                )
                plural = "participant" if len(users) == 1 else "participants"
                rows.append(
                    _Row(
                        "  " + name,
                        _totalled(counts),
                        f"{len(users)} {plural}",
                    )
                )
            continue

        # Named moves keep the declaration order of TAXONOMY.md; only moves
        # that actually occurred get a row, so the table stays readable.
        family_moves = [m for m, fam in MOVES.items() if fam == family]
        shown = False
        for name in family_moves:
            counts = [
                sum(1 for m in moves if m.move == name) for moves in per_group_moves
            ]
            if sum(counts) == 0:
                continue
            shown = True
            rows.append(_Row("  " + name, _totalled(counts)))
        if not shown:
            rows.append(_Row("  (none used)"))
    return rows


def _glyph_rows(groups: list[list[Session]]) -> list[_Row]:
    per_group_moves = [
        [m for s in group for m in counted_moves(s)] for group in groups
    ]
    rows: list[_Row] = []
    for glyph in GLYPHS:  # TAXONOMY.md presentation order, never by count
        counts = [
            sum(1 for m in moves if m.glyph == glyph) for moves in per_group_moves
        ]
        rows.append(_Row(glyph, _totalled(counts)))
    counts = [sum(1 for m in moves if m.glyph is None) for moves in per_group_moves]
    rows.append(_Row("(none)", _totalled(counts)))
    return rows


def _motif_rows(groups: list[list[Session]]) -> list[_Row]:
    per_group_moves = [
        [m for s in group for m in counted_moves(s)] for group in groups
    ]
    rows: list[_Row] = []
    for motif in MOTIFS:  # TAXONOMY.md order, never by count
        counts = [
            sum(1 for m in moves if motif in m.motifs) for moves in per_group_moves
        ]
        rows.append(_Row(motif, _totalled(counts)))
    return rows


# --------------------------------------------------------------------------
# Report assembly
# --------------------------------------------------------------------------


def _count_tables(
    column_names: list[str], groups: list[list[Session]]
) -> list[str]:
    columns = column_names + ["total"]
    out: list[str] = []
    out.append("Move frequency by family")
    out.append("  NOTE lines are not moves and are not counted.")
    out.append(
        "  Wildcard rows also show how many distinct participants used the "
        "name (promotion evidence)."
    )
    out.append("")
    out.extend(_render_table(columns, _move_rows(groups)))
    out.append("")
    out.append("Glyph distribution")
    out.append("")
    out.extend(_render_table(columns, _glyph_rows(groups)))
    out.append("")
    out.append("Motif counts")
    out.append("")
    out.extend(_render_table(columns, _motif_rows(groups)))
    return out


def _timelines(sessions: list[Session], notes: list[str]) -> list[str]:
    # The legend is printed once, in the report preamble.
    out = [
        "Phase timelines",
        f"  one character per {MINUTES_PER_CELL} minutes: cell i is sampled at "
        f"minute {MINUTES_PER_CELL} * i and shows the",
        "  phase of the latest move at or before that mark. A phase that begins "
        "and ends",
        "  between two marks is invisible here, and a phase carries across cells "
        "with no move.",
        "",
    ]
    width = max(len(s.label) for s in sessions)
    for session in sessions:
        cells, note = timeline_cells(session)
        if note:
            notes.append(note)
        out.append(
            "  " + session.label.ljust(width) + "  " + phase_timeline(session.moves, cells)
        )
    return out


def _reel(sessions: list[Session]) -> list[str]:
    out = [
        "Brilliancies and blunders reel",
        "  every !! and ?? line, alphabetical by participant then attempt;",
        "  no ordering by any measure is implied or intended",
        "",
    ]
    any_line = False
    for session in sorted(sessions, key=lambda s: (s.participant, s.attempt)):
        picked = [m for m in session.moves if m.glyph in ("!!", "??")]
        if not picked:
            continue
        any_line = True
        out.append("  " + session.label)
        for mv in picked:
            comment = f'"{mv.comment}"' if mv.comment else "(no comment)"
            anchor = f"  @{mv.anchor}" if mv.anchor else ""
            motifs = f"  ({', '.join(mv.motifs)})" if mv.motifs else ""
            out.append(
                f"    {mv.timestamp:>6}  {mv.glyph:<2}  {mv.phase:<7} "
                f"{mv.move}{motifs}  {comment}{anchor}"
            )
        out.append("")
    if not any_line:
        out.append("  (no !! or ?? lines in this selection)")
        out.append("")
    return out


def render_report(sessions: list[Session], root: Path, notes: list[str]) -> str:
    """Build the whole plain-text report for the given sessions."""
    lines: list[str] = []
    lines.append("agent-etudes -- annotation statistics")
    lines.append(f"results root: {root}")
    plural = "session" if len(sessions) == 1 else "sessions"
    lines.append(f"{len(sessions)} {plural}")
    lines.append(f"phase timeline legend: {_LEGEND}")
    lines.append("")

    challenges: list[str] = []
    for session in sessions:
        cid = session_challenge(session)
        if cid not in challenges:
            challenges.append(cid)
    challenges.sort()

    for cid in challenges:
        group = [s for s in sessions if session_challenge(s) == cid]
        plural = "session" if len(group) == 1 else "sessions"
        lines.append("=" * 72)
        lines.append(f"etude {cid} -- {len(group)} {plural}")
        lines.append("=" * 72)
        lines.append("")
        lines.extend(
            _count_tables([session_label(s) for s in group], [[s] for s in group])
        )
        lines.append("")
        lines.extend(_timelines(group, notes))
        lines.append("")
        lines.extend(_reel(group))

    lines.append("=" * 72)
    lines.append("all challenges")
    lines.append("=" * 72)
    lines.append("  timelines and the reel are printed per challenge, above.")
    lines.append("")
    lines.extend(
        _count_tables(
            challenges,
            [[s for s in sessions if session_challenge(s) == cid] for cid in challenges],
        )
    )
    lines.append("")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# --grep
# --------------------------------------------------------------------------


def grep_lines(sessions: list[Session], token: str) -> list[str]:
    """``<cid>/<participant>/<n>:<line>: <original line>`` for each match.

    A line matches when its move token or one of its motifs is exactly
    ``token`` (case-sensitive, no substrings): the vocabulary is small and
    fixed, so an exact match is what makes the output trustworthy.

    ``NOTE`` lines are searchable here even though they are excluded from
    every count table -- this is a lookup, not a measure.
    """
    out: list[str] = []
    for session in sessions:
        for mv in session.moves:
            if mv.move == token or token in mv.motifs:
                out.append(f"{session.label}:{mv.line}: {_raw_line(session, mv.line)}")
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def default_results_root() -> Path:
    """``results/`` of the repository this script lives in."""
    try:
        return repo_root_from(Path(__file__)) / "results"
    except EtudesError:
        return _SCRIPTS_DIR.parent / "results"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stats.py",
        description=(
            "Move frequencies, glyph and motif distributions, ASCII phase "
            "timelines and the brilliancies and blunders reel, read from a "
            "results tree of session.yaml + annotations.md pairs."
        ),
        epilog=(
            "This tool reports distributions only. It never orders "
            "participants and never computes a comparison measure."
        ),
    )
    parser.add_argument(
        "results_root",
        nargs="?",
        default=None,
        help="directory to read (default: results/ of this repository)",
    )
    parser.add_argument(
        "--challenge",
        metavar="cXXX",
        default=None,
        help="only report sessions of this challenge, e.g. --challenge c001",
    )
    parser.add_argument(
        "--grep",
        metavar="TOKEN",
        default=None,
        help=(
            "print the annotation lines whose move or motif is exactly TOKEN "
            "(case-sensitive) and stop"
        ),
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    root = Path(args.results_root) if args.results_root else default_results_root()
    if not root.exists():
        print(
            f"stats.py: no such directory: {root}\n"
            "Pass the results directory as an argument, for example:\n"
            "  uv run python scripts/stats.py results/",
            file=sys.stderr,
        )
        return 2
    if not root.is_dir():
        print(
            f"stats.py: {root} is a file; this tool wants the directory that "
            "holds the collected sessions.",
            file=sys.stderr,
        )
        return 2

    challenge = args.challenge
    if challenge is not None and not CHALLENGE_ID_RE.fullmatch(challenge):
        print(
            f"stats.py: --challenge wants a challenge id like c001, got "
            f"{challenge!r}.",
            file=sys.stderr,
        )
        return 2

    try:
        sessions = walk_results(root)
    except EtudesError as exc:  # pragma: no cover - walk_results is forgiving
        print(f"stats.py: {exc}", file=sys.stderr)
        return 2

    if challenge is not None:
        sessions = [s for s in sessions if s.cid == challenge]

    if not sessions:
        where = f"{root}"
        if challenge is not None:
            print(
                f"stats.py: no sessions for challenge {challenge} under {where}.",
                file=sys.stderr,
            )
        else:
            print(
                f"stats.py: no sessions under {where}.\n"
                "A session is a directory holding both session.yaml and "
                "annotations.md; run scripts/collect_results.py to populate "
                "the tree.",
                file=sys.stderr,
            )
        return 0

    if args.grep is not None:
        matches = grep_lines(sessions, args.grep)
        for line in matches:
            print(line)
        if not matches:
            print(
                f"stats.py: no annotation line uses the move or motif "
                f"{args.grep!r}.",
                file=sys.stderr,
            )
            return 1
        return 0

    notes: list[str] = []
    report = render_report(sessions, root, notes)
    sys.stdout.write(report)

    for session in sessions:
        for message in session.lint:
            print(f"stats.py: note: {message}", file=sys.stderr)
    for note in notes:
        print(f"stats.py: note: {note}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
