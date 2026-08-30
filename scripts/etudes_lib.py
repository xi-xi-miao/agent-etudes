"""Shared helpers for the agent-etudes tooling.

This module is the single source of truth for:

* the annotation taxonomy (phases, moves, glyphs, motifs) of TAXONOMY.md v0.2,
* the ``annotations.md`` frontmatter + line grammar and its lint rules,
* the ``session.yaml`` schema checks,
* the challenge manifest (``challenges/<id>/challenge.yaml``) contract,
* small path/git/format utilities used by every script in ``scripts/``.

Dependencies: Python 3.11 standard library + PyYAML. Nothing else, ever --
the shared layer must import cleanly on a machine that has no challenge
specific packages installed.

Error handling contract
-----------------------
``EtudesError`` is the base class for every deliberate, human-facing failure
raised here; ``LintError`` (carries a :class:`LintMessage`) and
``ManifestError`` derive from it. Command line scripts should catch
``EtudesError`` and print ``str(exc)`` -- the messages are written to be read
by a participant, not by a developer.

:func:`parse_annotations_file` deliberately *never* raises for bad content: it
returns the messages it collected so a caller can print all of them at once.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Optional

import yaml

__all__ = [
    "TAXONOMY_VERSION",
    "PHASES",
    "PHASE_LETTERS",
    "FAMILIES",
    "MOVES",
    "GLYPHS",
    "MOTIFS",
    "WILDCARD_RE",
    "NOTE_MOVE",
    "is_named_move",
    "move_family",
    "CHALLENGE_ID_RE",
    "PARTICIPANT_RE",
    "BRANCH_RE",
    "parse_branch",
    "EtudesError",
    "LintError",
    "ManifestError",
    "LintMessage",
    "split_frontmatter",
    "Move",
    "LINE_RE",
    "parse_annotation_line",
    "parse_annotations_file",
    "load_yaml",
    "validate_session_yaml",
    "MANIFEST_REQUIRED_KEYS",
    "MANIFEST_OPTIONAL_KEYS",
    "MANIFEST_STATUSES",
    "load_manifest",
    "find_challenges",
    "Session",
    "walk_results",
    "fmt_elapsed",
    "parse_elapsed",
    "repo_root_from",
    "git",
    "git_ok",
]


# --------------------------------------------------------------------------
# Taxonomy (TAXONOMY.md v0.2)
# --------------------------------------------------------------------------

TAXONOMY_VERSION = "0.2"

PHASES = ("Recon", "Plan", "Build", "Verify", "Recover")

#: Single letter used by the ASCII phase timelines in stats.py.
PHASE_LETTERS = {
    "Recon": "R",
    "Plan": "P",
    "Build": "B",
    "Verify": "V",
    "Recover": "C",
}

FAMILIES = ("Context", "Plan", "Delegate", "Steer", "Epistemic")

#: The 24 named moves -> family. ``X-<name>`` (wildcard) and ``NOTE`` are not
#: in here; see :func:`is_named_move` and :func:`move_family`.
MOVES = {
    # Context
    "SCOUT": "Context",
    "GROUND": "Context",
    "FENCE": "Context",
    "DISTILL": "Context",
    # Plan
    "PLAN": "Plan",
    "SPLIT": "Plan",
    "SPEC": "Plan",
    "SPIKE": "Plan",
    # Delegate
    "DISPATCH": "Delegate",
    "PAIR": "Delegate",
    "FORK": "Delegate",
    "REVIEW": "Delegate",
    # Steer
    "NUDGE": "Steer",
    "REDIRECT": "Steer",
    "VETO": "Steer",
    "TAKEOVER": "Steer",
    "ROLLBACK": "Steer",
    "RESET": "Steer",
    # Epistemic
    "TUTOR": "Epistemic",
    "OPTIONS": "Epistemic",
    "PROBE": "Epistemic",
    "CRITERIA": "Epistemic",
    "CROSSCHECK": "Epistemic",
    "DEFER": "Epistemic",
}

#: Hindsight evaluation marks, in the presentation order of TAXONOMY.md
#: (best to worst). The line grammar matches glyphs with a character class, so
#: nothing here depends on the order; code that needs to build an alternation
#: must sort by descending length itself so ``!`` cannot shadow ``!?``.
GLYPHS = ("!!", "!", "!?", "?!", "?", "??")

MOTIFS = (
    "doom-loop",
    "false-summit",
    "ghost-api",
    "overreach",
    "test-gaming",
    "context-rot",
    "yes-and",
    "rabbit-hole",
    "windfall",
)

WILDCARD_RE = re.compile(r"^X-[a-z][a-z0-9-]*$")

NOTE_MOVE = "NOTE"


def is_named_move(m: str) -> bool:
    """True for one of the 24 named moves (exact, case-sensitive)."""
    return m in MOVES


def move_family(m: str) -> Optional[str]:
    """Family of a move token.

    Returns the family name for a named move, ``"Wildcard"`` for a well
    formed ``X-<name>``, and ``None`` for ``NOTE`` (which is not a move and is
    excluded from every frequency table) as well as for any token that is
    neither -- unknown tokens are simply not counted in family tables.
    """
    if m in MOVES:
        return MOVES[m]
    if WILDCARD_RE.fullmatch(m):
        return "Wildcard"
    return None


# --------------------------------------------------------------------------
# Identifiers: challenge ids, participants, attempt branches
# --------------------------------------------------------------------------

CHALLENGE_ID_RE = re.compile(r"^c[0-9]{3}$")
PARTICIPANT_RE = re.compile(r"^[a-z0-9-]+$")
BRANCH_RE = re.compile(r"^attempt/(c[0-9]{3})/([a-z0-9-]+)/([1-9][0-9]*)$")


def parse_branch(name: str) -> Optional[tuple[str, str, int]]:
    """``attempt/c001/alice/2`` -> ``("c001", "alice", 2)``; else ``None``.

    ``fullmatch`` is used everywhere in this module so that a stray trailing
    newline (very easy to get out of ``git`` or YAML) cannot slip through.
    """
    if not isinstance(name, str):
        return None
    m = BRANCH_RE.fullmatch(name)
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3))


# --------------------------------------------------------------------------
# Errors and lint messages
# --------------------------------------------------------------------------


class EtudesError(Exception):
    """Base class for deliberate, human-facing failures in this toolchain."""


class ManifestError(EtudesError):
    """A ``challenge.yaml`` is missing, unreadable or violates the contract."""


class LintMessage(NamedTuple):
    """One diagnostic tied to a file and a 1-based line number."""

    path: str
    line: int
    level: str  # "error" | "warning"
    text: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.path}:{self.line}: {self.level}: {self.text}"


class LintError(EtudesError):
    """Raised by the single-item parsers; carries one :class:`LintMessage`."""

    def __init__(self, message: LintMessage):
        super().__init__(str(message))
        self.message = message

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.message)


def _err(path: Any, line: int, text: str) -> LintMessage:
    return LintMessage(str(path), line, "error", text)


def _warn(path: Any, line: int, text: str) -> LintMessage:
    return LintMessage(str(path), line, "warning", text)


# --------------------------------------------------------------------------
# Reading text files
# --------------------------------------------------------------------------

#: Every text file this toolchain reads is UTF-8. ``utf-8-sig`` is used rather
#: than ``utf-8`` so that a byte order mark -- which some editors write without
#: telling anyone -- is swallowed instead of turning the first line of a file
#: into something that no longer looks like ``---`` or a YAML key.
_ENCODING = "utf-8-sig"

#: Body of the "bad bytes" message. :class:`LintMessage` prints the path
#: itself, so it is kept separate from the path-prefixed form used by the
#: exceptions.
_NOT_UTF8_BODY = (
    "this file is not valid UTF-8 text. Save it as UTF-8 (annotations.md, "
    "session.yaml and challenge.yaml are always UTF-8)."
)
_NOT_UTF8 = "{path}: " + _NOT_UTF8_BODY


def _read_text(path: Any) -> str:
    """``Path.read_text`` with the toolchain's encoding. Raises as usual."""
    return Path(path).read_text(encoding=_ENCODING)


# --------------------------------------------------------------------------
# YAML helpers
# --------------------------------------------------------------------------


def load_yaml(path: Any) -> dict:
    """``yaml.safe_load`` a file into a dict. Empty file -> ``{}``.

    Raises :class:`EtudesError` with a readable message when the file cannot
    be read, is not UTF-8, is not valid YAML, or does not hold a mapping at
    the top level.
    """
    p = Path(path)
    try:
        text = _read_text(p)
    except FileNotFoundError:
        raise EtudesError(f"{p}: file not found") from None
    except UnicodeDecodeError:
        raise EtudesError(_NOT_UTF8.format(path=p)) from None
    except OSError as exc:
        raise EtudesError(f"{p}: could not read file ({exc.strerror or exc})") from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise EtudesError(f"{p}: not valid YAML: {_one_line(exc)}") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise EtudesError(
            f"{p}: expected a YAML mapping (key: value) at the top level, "
            f"found {type(data).__name__}"
        )
    return data


def _one_line(exc: Exception) -> str:
    return " ".join(str(exc).split())


# --------------------------------------------------------------------------
# Frontmatter
# --------------------------------------------------------------------------


def split_frontmatter(text: str, path: Any) -> tuple[dict, list[tuple[int, str]]]:
    """Split ``---`` YAML frontmatter from the body of an annotations file.

    Returns ``(meta, body_lines)`` where ``body_lines`` is a list of
    ``(absolute_1_based_line_number, raw_line_text)`` pairs for everything
    after the closing ``---``.

    Raises :class:`LintError` when the frontmatter is missing or malformed.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise LintError(
            _err(
                path,
                1,
                "missing YAML frontmatter: the file must start with a line "
                "containing only ---",
            )
        )
    close = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close = i
            break
    if close is None:
        raise LintError(
            _err(
                path,
                1,
                "unterminated YAML frontmatter: no closing --- line was found",
            )
        )
    raw = "\n".join(lines[1:close])
    try:
        meta = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise LintError(
            _err(path, 2, f"frontmatter is not valid YAML: {_one_line(exc)}")
        ) from None
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise LintError(
            _err(
                path,
                2,
                "frontmatter must be a YAML mapping (key: value), found "
                f"{type(meta).__name__}",
            )
        )
    body = [(i + 1, lines[i]) for i in range(close + 1, len(lines))]
    return meta, body


def _frontmatter_key_lines(text: str) -> dict[str, int]:
    """Map top-level frontmatter keys to their absolute line numbers."""
    out: dict[str, int] = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            break
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:", lines[i])
        if m and m.group(1) not in out:
            out[m.group(1)] = i + 1
    return out


# --------------------------------------------------------------------------
# The annotation line grammar
# --------------------------------------------------------------------------


class Move(NamedTuple):
    """One parsed annotation line."""

    line: int
    minutes: int
    timestamp: str
    phase: str
    stance: Optional[str]  # None | ">" | "~"
    move: str
    glyph: Optional[str]
    motifs: tuple
    comment: Optional[str]
    anchor: Optional[str]


#: One anchored regex for the whole grammar of TAXONOMY.md. Each field is
#: captured by *shape* only; the concrete vocabularies are checked afterwards
#: so that a bad token yields a precise message instead of "does not match".
LINE_RE = re.compile(
    r"""
    [ \t]*
    \+(?P<hours>[0-9]+):(?P<minutes>[0-9]{2})
    [ \t]+
    (?P<phase>[A-Za-z]+)(?P<stance>[>~])?
    [ \t]+
    (?P<move>[A-Za-z][A-Za-z0-9_-]*)
    (?:[ \t]+(?P<glyph>[!?]+))?
    (?:[ \t]+\((?P<motifs>[^)]*)\))?
    (?:[ \t]+"(?P<comment>(?:[^"\\]|\\.)*)")?
    (?:[ \t]+@(?P<anchor>[^ \t]+))?
    [ \t]*
    """,
    re.VERBOSE,
)

_TIMESTAMP_LOOSE_RE = re.compile(r"[ \t]*\+(?P<hours>[0-9]+):(?P<minutes>[0-9]+)")
_ANCHOR_RE = re.compile(r"^(?:t[0-9]+|[0-9a-fA-F]{7,40})$")
#: A line ending in two or more ``@token`` fields. The grammar allows exactly
#: one anchor, and writing both a commit and a transcript position is the
#: mistake people actually make, so it earns its own message.
_TWO_ANCHORS_RE = re.compile(r"[ \t]+@[^ \t]+(?:[ \t]+@[^ \t]+)+[ \t]*$")

_FIELD_ORDER_HINT = (
    'fields must appear in the order: +H:MM  Phase[>|~]  MOVE  [glyph]  '
    '[(motifs)]  ["comment"]  [@anchor]'
)


def parse_annotation_line(line_no: int, text: str, path: Any = "") -> Optional[Move]:
    """Parse one annotation line.

    Returns ``None`` for a blank line or a line whose first non-whitespace
    character is ``#`` (both are ignored by the linter). Raises
    :class:`LintError` with a precise message for anything malformed.
    """
    raw = text.rstrip("\r\n")
    stripped = raw.strip()
    if not stripped or stripped.startswith("#"):
        return None

    m = LINE_RE.fullmatch(raw.rstrip())
    if m is None:
        ts = _TIMESTAMP_LOOSE_RE.match(raw)
        if ts is None:
            raise LintError(
                _err(
                    path,
                    line_no,
                    "line does not start with a +H:MM elapsed timestamp "
                    "(blank lines and lines starting with # are ignored); "
                    + _FIELD_ORDER_HINT,
                )
            )
        if len(ts.group("minutes")) != 2:
            raise LintError(
                _err(
                    path,
                    line_no,
                    "timestamp minutes must be exactly two digits, "
                    f"e.g. +0:05 (found +{ts.group('hours')}:{ts.group('minutes')})",
                )
            )
        if _TWO_ANCHORS_RE.search(raw):
            raise LintError(
                _err(
                    path,
                    line_no,
                    "at most one anchor per line, and it comes last; keep "
                    "either the @<hex> commit or the @t<number> transcript "
                    "position and move the other into the comment",
                )
            )
        raise LintError(
            _err(path, line_no, "unrecognized or trailing text; " + _FIELD_ORDER_HINT)
        )

    hours = int(m.group("hours"))
    minutes = int(m.group("minutes"))
    if minutes > 59:
        raise LintError(
            _err(
                path,
                line_no,
                f"timestamp minutes must be 00-59 (found {m.group('minutes')})",
            )
        )
    timestamp = f"+{hours}:{minutes:02d}"

    phase = m.group("phase")
    if phase not in PHASES:
        raise LintError(
            _err(
                path,
                line_no,
                f"unknown phase {phase!r}; expected one of: " + ", ".join(PHASES),
            )
        )
    stance = m.group("stance")

    move = m.group("move")
    if move[:2].lower() == "x-":
        if not WILDCARD_RE.fullmatch(move):
            raise LintError(
                _err(
                    path,
                    line_no,
                    f"malformed wildcard move {move!r}; it must look like "
                    "X-<name> with a lowercase name, e.g. X-bribe",
                )
            )
    elif move != NOTE_MOVE and not is_named_move(move):
        raise LintError(
            _err(
                path,
                line_no,
                f"unknown move {move!r}; expected one of the 24 named moves, "
                "NOTE, or a wildcard X-<name>",
            )
        )

    glyph = m.group("glyph")
    if glyph is not None and glyph not in GLYPHS:
        raise LintError(
            _err(
                path,
                line_no,
                f"unknown glyph {glyph!r}; expected one of: " + " ".join(GLYPHS),
            )
        )

    motifs: tuple = ()
    raw_motifs = m.group("motifs")
    if raw_motifs is not None:
        parts = [p.strip() for p in raw_motifs.split(",")]
        if any(p == "" for p in parts):
            raise LintError(
                _err(
                    path,
                    line_no,
                    "empty motif list; write (motif) or (motif, motif) using "
                    "the motifs from TAXONOMY.md",
                )
            )
        for p in parts:
            if p not in MOTIFS:
                raise LintError(
                    _err(
                        path,
                        line_no,
                        f"unknown motif {p!r}; expected one of: "
                        + ", ".join(MOTIFS),
                    )
                )
        motifs = tuple(parts)

    comment = m.group("comment")
    if comment is not None:
        comment = re.sub(r"\\(.)", r"\1", comment)

    anchor = m.group("anchor")
    if anchor is not None and not _ANCHOR_RE.match(anchor):
        raise LintError(
            _err(
                path,
                line_no,
                f"malformed anchor '@{anchor}'; expected @<7-40 hex digits> "
                "for a commit or @t<number> for a transcript position",
            )
        )

    return Move(
        line=line_no,
        minutes=hours * 60 + minutes,
        timestamp=timestamp,
        phase=phase,
        stance=stance,
        move=move,
        glyph=glyph,
        motifs=motifs,
        comment=comment,
        anchor=anchor,
    )


# --------------------------------------------------------------------------
# Whole-file annotation lint
# --------------------------------------------------------------------------

_ANNOTATION_REQUIRED_META = (
    "participant",
    "challenge",
    "attempt",
    "taxonomy_version",
    "session_date",
)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _iso_date_ok(value: Any) -> bool:
    if isinstance(value, (_dt.date, _dt.datetime)):
        return True
    if isinstance(value, str):
        try:
            _dt.date.fromisoformat(value.strip()[:10])
        except ValueError:
            return False
        return True
    return False


def _check_annotation_meta(
    meta: dict, path: Any, key_lines: dict[str, int]
) -> list[LintMessage]:
    out: list[LintMessage] = []

    def ln(key: str) -> int:
        return key_lines.get(key, 1)

    for key in _ANNOTATION_REQUIRED_META:
        if key not in meta:
            out.append(_err(path, 1, f"frontmatter is missing required key {key!r}"))

    if "participant" in meta:
        v = meta["participant"]
        if not isinstance(v, str) or not PARTICIPANT_RE.fullmatch(v):
            out.append(
                _err(
                    path,
                    ln("participant"),
                    f"participant must be lowercase letters, digits and hyphens "
                    f"(pattern [a-z0-9-]+), found {v!r}",
                )
            )

    if "challenge" in meta:
        v = meta["challenge"]
        if not isinstance(v, str) or not CHALLENGE_ID_RE.fullmatch(v):
            out.append(
                _err(
                    path,
                    ln("challenge"),
                    f"challenge must be a challenge id like c001, found {v!r}",
                )
            )

    if "attempt" in meta:
        v = meta["attempt"]
        if not _is_int(v):
            out.append(
                _err(
                    path,
                    ln("attempt"),
                    f"attempt must be a whole number (1, 2, 3...), found "
                    f"{v!r} of type {type(v).__name__}",
                )
            )
        elif v < 1:
            out.append(
                _err(path, ln("attempt"), f"attempt must be >= 1, found {v}")
            )

    if "taxonomy_version" in meta:
        v = meta["taxonomy_version"]
        if not isinstance(v, str):
            out.append(
                _warn(
                    path,
                    ln("taxonomy_version"),
                    f"taxonomy_version should be quoted so YAML keeps it a "
                    f'string, e.g. taxonomy_version: "{TAXONOMY_VERSION}"',
                )
            )
        if str(v) != TAXONOMY_VERSION:
            out.append(
                _warn(
                    path,
                    ln("taxonomy_version"),
                    f"annotations were written against taxonomy version "
                    f"{str(v)!r}; this repository is at {TAXONOMY_VERSION!r}",
                )
            )

    if "session_date" in meta and not _iso_date_ok(meta["session_date"]):
        out.append(
            _err(
                path,
                ln("session_date"),
                f"session_date must be a date such as 2026-09-12, found "
                f"{meta['session_date']!r}",
            )
        )

    return out


def parse_annotations_file(path: Any) -> tuple[dict, list[Move], list[LintMessage]]:
    """Parse and lint one ``annotations.md``.

    Returns ``(meta, moves, messages)``. This function never raises for bad
    content -- every problem becomes a :class:`LintMessage` so a caller can
    report all of them in one pass. Callers decide what is fatal; by
    convention only ``level == "error"`` fails a build.

    Rules applied here (the annotation grammar of TAXONOMY.md): required
    frontmatter keys and their
    types, the line grammar, non-decreasing timestamps (equal is fine), a
    mandatory comment on every ``X-*`` move and every ``??`` glyph, and a
    warning when ``taxonomy_version`` is unquoted or does not match.

    Not applied here (they belong to ``lint_annotations.py``): ``--repo``
    commit-anchor resolution, ``--session`` cross-checks and
    ``--expect-branch``.
    """
    p = Path(path)
    messages: list[LintMessage] = []
    try:
        text = _read_text(p)
    except FileNotFoundError:
        return {}, [], [_err(p, 1, "file not found")]
    except UnicodeDecodeError:
        return {}, [], [_err(p, 1, _NOT_UTF8_BODY)]
    except OSError as exc:
        return {}, [], [_err(p, 1, f"could not read file ({exc.strerror or exc})")]

    try:
        meta, body = split_frontmatter(text, p)
    except LintError as exc:
        return {}, [], [exc.message]

    messages.extend(_check_annotation_meta(meta, p, _frontmatter_key_lines(text)))

    moves: list[Move] = []
    previous: Optional[Move] = None
    for line_no, line_text in body:
        try:
            mv = parse_annotation_line(line_no, line_text, p)
        except LintError as exc:
            messages.append(exc.message)
            continue
        if mv is None:
            continue

        if previous is not None and mv.minutes < previous.minutes:
            messages.append(
                _err(
                    p,
                    mv.line,
                    f"timestamp {mv.timestamp} goes backwards; timestamps must "
                    f"be non-decreasing (previous was {previous.timestamp} on "
                    f"line {previous.line})",
                )
            )
        if mv.comment is None:
            if mv.move[:2].lower() == "x-":
                messages.append(
                    _err(
                        p,
                        mv.line,
                        f"wildcard move {mv.move} requires a \"comment\" "
                        "explaining what it means",
                    )
                )
            if mv.glyph == "??":
                messages.append(
                    _err(
                        p,
                        mv.line,
                        'a ?? glyph requires a "comment" saying what went wrong',
                    )
                )
        moves.append(mv)
        previous = mv

    return meta, moves, messages


# --------------------------------------------------------------------------
# session.yaml
# --------------------------------------------------------------------------


def validate_session_yaml(data: Any, path: Any) -> list[LintMessage]:
    """Check a loaded ``session.yaml`` against the schema in ``templates/session.yaml``.

    That template is the schema: its comments name every required key and the
    shape expected of it, and it is the file a participant copies (CONTRIBUTING
    step 2).

    Unknown extra keys are accepted on purpose -- participants are encouraged
    to record more, not less. All messages carry line 1: YAML loading loses
    the line information, and the file is short enough to read.
    """
    out: list[LintMessage] = []
    if not isinstance(data, dict):
        return [
            _err(
                path,
                1,
                "session.yaml must contain a YAML mapping (key: value) at the "
                f"top level, found {type(data).__name__}",
            )
        ]

    def missing(key: str) -> bool:
        if key not in data:
            out.append(_err(path, 1, f"missing required key {key!r}"))
            return True
        return False

    if not missing("participant"):
        v = data["participant"]
        if not isinstance(v, str) or not PARTICIPANT_RE.fullmatch(v):
            out.append(
                _err(
                    path,
                    1,
                    "participant must be lowercase letters, digits and hyphens "
                    f"(pattern [a-z0-9-]+), found {v!r}",
                )
            )

    if not missing("challenge"):
        v = data["challenge"]
        if not isinstance(v, str) or not CHALLENGE_ID_RE.fullmatch(v):
            out.append(
                _err(path, 1, f"challenge must be an id like c001, found {v!r}")
            )

    if not missing("attempt"):
        v = data["attempt"]
        if not _is_int(v):
            out.append(
                _err(
                    path,
                    1,
                    f"attempt must be a whole number (1, 2, 3...), found {v!r} "
                    f"of type {type(v).__name__}",
                )
            )
        elif v < 1:
            out.append(_err(path, 1, f"attempt must be >= 1, found {v}"))

    if not missing("date") and not _iso_date_ok(data["date"]):
        out.append(
            _err(
                path,
                1,
                f"date must be a date such as 2026-09-12, found {data['date']!r}",
            )
        )

    if not missing("tool"):
        v = data["tool"]
        if not isinstance(v, dict):
            out.append(_err(path, 1, "tool must be a mapping with name and version"))
        else:
            for sub in ("name", "version"):
                if sub not in v:
                    out.append(_err(path, 1, f"tool is missing required key {sub!r}"))
                elif not isinstance(v[sub], str):
                    out.append(
                        _err(
                            path,
                            1,
                            f"tool.{sub} must be a string, found {v[sub]!r}; quote "
                            "it if it looks like a number",
                        )
                    )

    if not missing("model"):
        v = data["model"]
        if not isinstance(v, dict):
            out.append(_err(path, 1, "model must be a mapping with a name"))
        elif "name" not in v:
            out.append(_err(path, 1, "model is missing required key 'name'"))
        elif not isinstance(v["name"], str):
            out.append(
                _err(path, 1, f"model.name must be a string, found {v['name']!r}")
            )

    if not missing("duration_wall_minutes"):
        v = data["duration_wall_minutes"]
        if not _is_number(v):
            out.append(
                _err(
                    path,
                    1,
                    f"duration_wall_minutes must be a number of minutes, found "
                    f"{v!r} of type {type(v).__name__}",
                )
            )
        elif v < 0:
            out.append(
                _err(path, 1, f"duration_wall_minutes must be >= 0, found {v}")
            )

    if not missing("outcome"):
        v = data["outcome"]
        if not isinstance(v, dict):
            out.append(
                _err(
                    path,
                    1,
                    "outcome must be a mapping with tests_passed and "
                    "self_assessment",
                )
            )
        else:
            if "tests_passed" not in v:
                out.append(
                    _err(path, 1, "outcome is missing required key 'tests_passed'")
                )
            else:
                tp = v["tests_passed"]
                if not (tp is None or isinstance(tp, bool)):
                    out.append(
                        _err(
                            path,
                            1,
                            f"outcome.tests_passed must be true, false or null, "
                            f"found {tp!r}",
                        )
                    )
            if "self_assessment" not in v:
                out.append(
                    _err(path, 1, "outcome is missing required key 'self_assessment'")
                )
            elif not isinstance(v["self_assessment"], str):
                out.append(
                    _err(
                        path,
                        1,
                        "outcome.self_assessment must be a string of 1-3 honest "
                        f"sentences, found {v['self_assessment']!r}",
                    )
                )

    return out


# --------------------------------------------------------------------------
# Challenge manifests
# --------------------------------------------------------------------------

MANIFEST_REQUIRED_KEYS = (
    "schema_version",
    "id",
    "number",
    "title",
    "status",
    "start_tag",
    "solutions_glob",
    "validate",
)
MANIFEST_OPTIONAL_KEYS = ("dependency_group",)
MANIFEST_STATUSES = ("draft", "open", "closed")
MANIFEST_SCHEMA_VERSION = 1


def load_manifest(challenge_dir: Any) -> dict:
    """Load and validate ``<challenge_dir>/challenge.yaml``.

    Raises :class:`ManifestError` with a message a human can act on when the
    file is missing, has an unknown ``schema_version``, is missing a required
    key, carries an unknown key, or has a bad ``status``.

    Directory-name rule: the repository convention is that a challenge lives
    in a directory named exactly after its id, so ``id`` is compared against
    the directory name *only when that name itself looks like a challenge id*
    (``^c[0-9]{3}$``). Test fixtures therefore live happily in a directory
    such as ``fake-challenge`` while declaring ``id: c999``.
    ``scripts/check_challenge.py`` enforces the naming rule strictly for real
    challenges under ``challenges/``.
    """
    d = Path(challenge_dir)
    manifest_path = d / "challenge.yaml"
    if not manifest_path.is_file():
        raise ManifestError(
            f"{manifest_path}: no challenge manifest here. A challenge "
            "directory must contain a challenge.yaml (see "
            "docs/adding-a-challenge.md)."
        )
    try:
        data = load_yaml(manifest_path)
    except EtudesError as exc:
        raise ManifestError(str(exc)) from None

    sv = data.get("schema_version")
    if sv != MANIFEST_SCHEMA_VERSION:
        raise ManifestError(
            f"{manifest_path}: schema_version must be "
            f"{MANIFEST_SCHEMA_VERSION}, found {sv!r}"
        )

    for key in MANIFEST_REQUIRED_KEYS:
        if key not in data:
            raise ManifestError(
                f"{manifest_path}: missing required key {key!r} "
                f"(required keys: {', '.join(MANIFEST_REQUIRED_KEYS)})"
            )

    allowed = set(MANIFEST_REQUIRED_KEYS) | set(MANIFEST_OPTIONAL_KEYS)
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ManifestError(
            f"{manifest_path}: unknown key(s) {', '.join(repr(k) for k in unknown)}; "
            f"allowed keys are {', '.join(sorted(allowed))}"
        )

    cid = data["id"]
    if not isinstance(cid, str) or not CHALLENGE_ID_RE.fullmatch(cid):
        raise ManifestError(
            f"{manifest_path}: id must look like c001 (pattern ^c[0-9]{{3}}$), "
            f"found {cid!r}"
        )
    if CHALLENGE_ID_RE.fullmatch(d.name) and d.name != cid:
        raise ManifestError(
            f"{manifest_path}: id {cid!r} does not match the directory name "
            f"{d.name!r}; a challenge directory is named after its id"
        )

    if not _is_int(data["number"]) or data["number"] < 1:
        raise ManifestError(
            f"{manifest_path}: number must be a whole number >= 1, found "
            f"{data['number']!r}"
        )

    for key in ("title", "start_tag", "solutions_glob", "validate"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ManifestError(
                f"{manifest_path}: {key} must be a non-empty string, found "
                f"{data[key]!r}"
            )

    if data["status"] not in MANIFEST_STATUSES:
        raise ManifestError(
            f"{manifest_path}: status must be one of "
            f"{', '.join(MANIFEST_STATUSES)}, found {data['status']!r}"
        )

    for placeholder in ("{instance}", "{solution}"):
        if placeholder not in data["validate"]:
            raise ManifestError(
                f"{manifest_path}: the validate command template must contain "
                f"{placeholder}, found {data['validate']!r}"
            )

    dg = data.get("dependency_group")
    if dg is not None and (not isinstance(dg, str) or not dg.strip()):
        raise ManifestError(
            f"{manifest_path}: dependency_group must be a non-empty string "
            f"naming a uv dependency group, found {dg!r}"
        )

    return data


def find_challenges(repo_root: Any) -> list[Path]:
    """All ``challenges/c???/`` directories that carry a ``challenge.yaml``."""
    base = Path(repo_root) / "challenges"
    if not base.is_dir():
        return []
    out = [
        child
        for child in base.iterdir()
        if child.is_dir()
        and CHALLENGE_ID_RE.fullmatch(child.name)
        and (child / "challenge.yaml").is_file()
    ]
    return sorted(out, key=lambda p: p.name)


# --------------------------------------------------------------------------
# Results tree
# --------------------------------------------------------------------------


@dataclass
class Session:
    """One collected attempt: a ``session.yaml`` + ``annotations.md`` pair."""

    dir: Path
    cid: str
    participant: str
    attempt: int
    session: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    moves: list = field(default_factory=list)
    lint: list = field(default_factory=list)

    @property
    def label(self) -> str:
        """``c001/alice/2`` -- the identity used in every report heading."""
        return f"{self.cid}/{self.participant}/{self.attempt}"


def walk_results(results_root: Any) -> list[Session]:
    """Find every ``session.yaml`` + ``annotations.md`` pair under a tree.

    Labels (challenge, participant, attempt) come from the *file contents*,
    never from the path, so a mis-filed directory still reports honestly.
    Anything unreadable becomes a lint message on the returned record; this
    function does not raise. The result is sorted by
    ``(cid, participant, attempt)`` so reports are stable.
    """
    root = Path(results_root)
    sessions: list[Session] = []
    if not root.is_dir():
        return sessions

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        if "session.yaml" not in filenames or "annotations.md" not in filenames:
            continue
        d = Path(dirpath)
        lint: list[LintMessage] = []
        session_path = d / "session.yaml"
        try:
            data = load_yaml(session_path)
        except EtudesError as exc:
            data = {}
            lint.append(_err(session_path, 1, _one_line(exc)))
        else:
            lint.extend(validate_session_yaml(data, session_path))

        meta, moves, ann_lint = parse_annotations_file(d / "annotations.md")
        lint.extend(ann_lint)

        cid = data.get("challenge") or meta.get("challenge") or ""
        participant = data.get("participant") or meta.get("participant") or ""
        attempt_raw = data.get("attempt", meta.get("attempt", 0))
        attempt = attempt_raw if _is_int(attempt_raw) else 0

        sessions.append(
            Session(
                dir=d,
                cid=str(cid),
                participant=str(participant),
                attempt=attempt,
                session=data,
                meta=meta,
                moves=moves,
                lint=lint,
            )
        )

    sessions.sort(key=lambda s: (s.cid, s.participant, s.attempt, str(s.dir)))
    return sessions


# --------------------------------------------------------------------------
# Elapsed-time formatting
# --------------------------------------------------------------------------


def fmt_elapsed(minutes: int) -> str:
    """``95`` -> ``"+1:35"``. Hours are unbounded."""
    if not _is_number(minutes):
        raise ValueError(f"elapsed minutes must be a number, got {minutes!r}")
    total = int(minutes)
    if total < 0:
        raise ValueError(f"elapsed minutes must be >= 0, got {minutes!r}")
    return f"+{total // 60}:{total % 60:02d}"


def parse_elapsed(text: str) -> int:
    """``"+1:35"`` -> ``95``. Raises ``ValueError`` on anything else."""
    if not isinstance(text, str):
        raise ValueError(f"elapsed time must be a string like +1:35, got {text!r}")
    m = re.fullmatch(r"[ \t]*\+([0-9]+):([0-9]{2})[ \t]*", text)
    if not m:
        raise ValueError(f"elapsed time must look like +H:MM, got {text!r}")
    mm = int(m.group(2))
    if mm > 59:
        raise ValueError(f"elapsed minutes must be 00-59, got {text!r}")
    return int(m.group(1)) * 60 + mm


# --------------------------------------------------------------------------
# Paths and git
# --------------------------------------------------------------------------


def repo_root_from(path: Any) -> Path:
    """Walk up from ``path`` to the enclosing git repository root.

    ``.git`` may be a directory or (in a worktree) a file, so existence is
    what is tested. Raises :class:`EtudesError` when there is no repository
    above ``path``.
    """
    p = Path(path).resolve()
    if p.is_file():
        p = p.parent
    for candidate in (p, *p.parents):
        if (candidate / ".git").exists():
            return candidate
    raise EtudesError(
        f"{path}: not inside a git repository (looked for a .git in {p} and "
        "every parent directory)"
    )


def git(args: Iterable[str], cwd: Any = None) -> str:
    """Run ``git`` and return stdout. Raises on a non-zero exit."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd is not None else None,
        check=True,
        text=True,
        capture_output=True,
    )
    return proc.stdout


def git_ok(args: Iterable[str], cwd: Any = None) -> bool:
    """True when ``git <args>`` exits 0; False on failure or missing git."""
    try:
        subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd is not None else None,
            check=True,
            text=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return False
    return True
