#!/usr/bin/env python3
"""Lint ``annotations.md`` files against the taxonomy grammar (TAXONOMY.md v0.2).

Usage examples::

    uv run python scripts/lint_annotations.py                     # everything below cwd
    uv run python scripts/lint_annotations.py session/annotations.md --session
    uv run python scripts/lint_annotations.py --root results --quiet
    uv run python scripts/lint_annotations.py --session --expect-branch "$BRANCH"

With no positional argument the linter discovers every ``annotations.md``
underneath ``--root`` (default: the current directory), skipping ``.git/``,
``.claude/``, ``templates/`` and any nested checkout (a directory with its own
``.git``). Positional arguments may be files *or* directories; a directory is
discovered the same way.

Every problem is reported as ``path:line: error: text`` or
``path:line: warning: text`` followed by a one line summary. Warnings never fail
the run.

Exit status
-----------
``0``  no errors (warnings are fine, and so is finding nothing to lint)
``1``  at least one error
``2``  the command line itself was wrong (unreadable path, bad ``--repo``)

The grammar and the frontmatter rules live in :mod:`etudes_lib`; this script
only adds the checks that need more than a single file: ``--session``
(the sibling ``session.yaml``, the three labels shared by both files, and --
as warnings -- the session day and a ``duration_wall_minutes`` that fits the
annotated timeline),
``--repo`` (do the ``@<hex>`` anchors name real commits?) and
``--expect-branch`` (do the labels agree with the branch being pushed?).

``--expect-branch`` is deliberately narrow: it applies to files named on the
command line and to discovered ``session/annotations.md`` files -- the layout an
attempt branch uses -- so that a whole-tree run in CI does not check the shipped
example, or somebody else's collected attempt under ``results/``, against the
branch name of whoever happens to be pushing.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys
from pathlib import Path
from typing import Optional

# Runnable from any working directory: make sure the sibling etudes_lib.py is
# importable even when this file is executed by absolute path or loaded by a
# test harness.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from etudes_lib import (  # noqa: E402  (path shim above must run first)
    EtudesError,
    LintMessage,
    load_yaml,
    parse_annotations_file,
    parse_branch,
    validate_session_yaml,
    git_ok,
)

__all__ = ["main", "discover", "check_file"]

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_USAGE = 2

ANNOTATIONS_NAME = "annotations.md"
SESSION_NAME = "session.yaml"

#: Directory names never descended into during discovery. ``templates/`` holds
#: the blank annotation template, which is documentation rather than a session;
#: ``.claude/`` is agent scratch (local settings, and worktrees of this very
#: repository).
SKIP_DIRS = frozenset({".git", ".claude", "templates"})

#: Directory holding an attempt's session artifacts on an attempt branch.
#: ``--expect-branch`` only applies to annotations found inside one.
ATTEMPT_SESSION_DIR = "session"

#: The three labels that ``annotations.md``, ``session.yaml`` and the attempt
#: branch all carry and must agree on.
SHARED_LABELS = ("participant", "challenge", "attempt")

_TRANSCRIPT_ANCHOR_RE = re.compile(r"^t[0-9]+$")
_FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:")

BRANCH_SHAPE = "attempt/<challenge>/<participant>/<n>"


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _error(path, line: int, text: str) -> LintMessage:
    return LintMessage(str(path), line, "error", text)


def _warning(path, line: int, text: str) -> LintMessage:
    return LintMessage(str(path), line, "warning", text)


def _frontmatter_key_lines(path: Path) -> dict[str, int]:
    """Map top-level frontmatter keys of ``path`` to 1-based line numbers.

    A private twin of the same helper inside :mod:`etudes_lib` (which does not
    export it): the cross-file checks below want to point at the offending
    frontmatter line rather than at line 1 of the file. Anything unreadable
    (missing, unreadable, or not UTF-8) simply yields an empty map and the
    callers fall back to line 1 -- the real diagnosis comes from
    :func:`etudes_lib.parse_annotations_file`.
    """
    out: dict[str, int] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return out
    if not lines or lines[0].strip() != "---":
        return out
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            break
        m = _FRONTMATTER_KEY_RE.match(lines[i])
        if m and m.group(1) not in out:
            out[m.group(1)] = i + 1
    return out


def _show(value) -> str:
    """Render a label for a message: quoted for strings, plain for numbers."""
    return repr(value) if isinstance(value, str) else str(value)


def _iso_day(value) -> Optional[str]:
    """``value`` as an ISO ``YYYY-MM-DD`` string, or ``None`` if it is not one.

    YAML turns an unquoted ``2026-09-12`` into a :class:`datetime.date` and a
    quoted one into a string, so the two files can hold the same day in two
    types; both sides are normalised before they are compared.
    """
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value.strip()[:10]).isoformat()
        except ValueError:
            return None
    return None


def _clock(minutes: int) -> str:
    """``232`` -> ``+3:52``, the way an annotation timestamp is written."""
    return f"+{minutes // 60}:{minutes % 60:02d}"


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def discover(root) -> list[Path]:
    """Every ``annotations.md`` under ``root``, skipping :data:`SKIP_DIRS`.

    Nested checkouts are skipped too: any directory below ``root`` that carries
    its own ``.git`` entry (a directory for a second clone, a file for a git
    worktree) belongs to another checkout, and linting it would judge somebody
    else's session -- under ``--expect-branch``, against the branch name of
    whoever happens to be running the check. ``root`` itself is never tested,
    so a run from a repository root still finds everything in it.

    The list is sorted so that output is identical from run to run and from
    machine to machine.
    """
    root = Path(root)
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in SKIP_DIRS and not (here / d / ".git").exists()
        )
        for name in filenames:
            # ``annotations.md`` plus reviewer copies named
            # ``<reviewer>.annotations.md`` (cross-annotation, TAXONOMY.md §7).
            if name == ANNOTATIONS_NAME or name.endswith("." + ANNOTATIONS_NAME):
                found.append(Path(dirpath) / name)
    return sorted(found, key=lambda p: str(p))


def _collect(paths: list[str], root: str) -> tuple[list[Path], list[str], set[str]]:
    """Resolve the positional arguments (or ``--root``) into a file list.

    Returns ``(files, problems, explicit)``. ``problems`` are usage errors such
    as a path that does not exist and make the run exit 2 without linting
    anything; ``explicit`` holds the resolved paths that were named on the
    command line as files (as opposed to found by searching a directory), which
    is what decides whether ``--expect-branch`` applies -- see
    :func:`branch_check_applies`.
    """
    files: list[Path] = []
    problems: list[str] = []
    explicit: set[str] = set()

    if paths:
        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                files.extend(discover(p))
            elif p.is_file():
                files.append(p)
                explicit.add(str(p.resolve()))
            elif p.exists():
                problems.append(f"{raw}: not a regular file or directory")
            else:
                problems.append(f"{raw}: no such file or directory")
    else:
        r = Path(root)
        if not r.is_dir():
            problems.append(
                f"{root}: --root must be an existing directory to search for "
                f"{ANNOTATIONS_NAME} files"
            )
        else:
            files = discover(r)

    seen: set[str] = set()
    unique: list[Path] = []
    for f in files:
        key = str(f.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique, problems, explicit


def branch_check_applies(path: Path, explicit: set[str]) -> bool:
    """Should ``--expect-branch`` be applied to this file?

    Only to annotations that belong to the branch being pushed. On an attempt
    branch those live in ``session/annotations.md`` (the attempt-branch layout in
    CONTRIBUTING.md), so that is
    the rule for files found by searching -- otherwise CI, which lints the whole
    tree, would check ``examples/example-session/`` and every already collected
    attempt under ``results/`` against the pusher's branch name and fail on all
    of them. A file named explicitly on the command line is always checked: the
    caller asked for it.
    """
    return str(path.resolve()) in explicit or path.parent.name == ATTEMPT_SESSION_DIR


# --------------------------------------------------------------------------
# Cross-file checks
# --------------------------------------------------------------------------


def _check_timeline(
    ann_path: Path,
    meta: dict,
    moves: list,
    data: dict,
    session_path: Path,
    key_lines: dict[str, int],
) -> list[LintMessage]:
    """Warn when the two files disagree about *when* the session happened.

    Warnings, never errors: both numbers are the participant's own honest
    report and a wide gap can be genuine (a session paused overnight, say).
    But ``duration_wall_minutes`` sizes the ASCII phase timeline in
    ``scripts/stats.py``, so a duration that cannot hold the annotated moves --
    or that dwarfs them -- is worth a second look while the session is still
    fresh.
    """
    messages: list[LintMessage] = []

    ann_day = _iso_day(meta.get("session_date"))
    session_day = _iso_day(data.get("date"))
    if ann_day is not None and session_day is not None and ann_day != session_day:
        messages.append(
            _warning(
                ann_path,
                key_lines.get("session_date", 1),
                f"session_date is {ann_day} here but date is {session_day} in "
                f"{session_path}; the two files describe one session",
            )
        )

    duration = data.get("duration_wall_minutes")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        return messages  # already an error from validate_session_yaml
    if not moves:
        return messages
    last = max(mv.minutes for mv in moves)
    if duration < last:
        messages.append(
            _warning(
                session_path,
                1,
                f"duration_wall_minutes is {duration} but the annotations run to "
                f"{_clock(last)} ({last} minutes); the session cannot be shorter "
                "than the moves it records",
            )
        )
    elif last > 0 and duration > 3 * last:
        messages.append(
            _warning(
                session_path,
                1,
                f"duration_wall_minutes is {duration}, more than three times the "
                f"annotated span of {_clock(last)} ({last} minutes); check the "
                "duration, or say in notes what the untracked time was",
            )
        )
    return messages


def _check_session(
    ann_path: Path, meta: dict, moves: list, key_lines: dict[str, int]
) -> tuple[list[LintMessage], dict]:
    """Validate the sibling ``session.yaml`` and cross-check the shared labels."""
    session_path = ann_path.parent / SESSION_NAME
    if not session_path.is_file() and ann_path.parent.name == "reviews":
        # A reviewer copy under results/<cid>/<p>/<n>/reviews/ shares the
        # session.yaml of the attempt it annotates, one directory up -- so its
        # participant/challenge/attempt name that attempt, not the reviewer.
        # The reviewer's own handle lives in the filename, and optionally in an
        # extra `annotator:` frontmatter key: unknown frontmatter keys are
        # accepted everywhere, so that costs nothing here.
        session_path = ann_path.parent.parent / SESSION_NAME
    if not session_path.is_file():
        return (
            [
                _error(
                    session_path,
                    1,
                    f"--session was requested but there is no {SESSION_NAME} next "
                    f"to {ann_path.name}; copy templates/{SESSION_NAME} and fill "
                    "it in",
                )
            ],
            {},
        )

    try:
        data = load_yaml(session_path)
    except EtudesError as exc:
        # load_yaml prefixes its message with the path; the LintMessage adds
        # the path (and a line number) itself, so drop the duplicate.
        text = str(exc)
        prefix = f"{session_path}: "
        if text.startswith(prefix):
            text = text[len(prefix) :]
        return [_error(session_path, 1, text)], {}

    messages = list(validate_session_yaml(data, session_path))

    for key in SHARED_LABELS:
        if key not in meta or key not in data:
            continue
        if meta[key] != data[key]:
            messages.append(
                _error(
                    ann_path,
                    key_lines.get(key, 1),
                    f"{key} is {_show(meta[key])} here but {_show(data[key])} in "
                    f"{session_path}; the two files describe one attempt and must "
                    "agree",
                )
            )

    messages.extend(
        _check_timeline(ann_path, meta, moves, data, session_path, key_lines)
    )
    return messages, data


def _check_branch(
    branch: str,
    ann_path: Path,
    meta: dict,
    key_lines: dict[str, int],
    session_data: dict,
    session_path: Path,
) -> list[LintMessage]:
    """Cross-check the labels in both files against the attempt branch name."""
    parsed = parse_branch(branch)
    if parsed is None:  # caller already reported the notice
        return []
    cid, participant, attempt = parsed
    expected = {"participant": participant, "challenge": cid, "attempt": attempt}

    messages: list[LintMessage] = []
    for key in SHARED_LABELS:
        if key in meta and meta[key] != expected[key]:
            messages.append(
                _error(
                    ann_path,
                    key_lines.get(key, 1),
                    f"{key} is {_show(meta[key])} but branch {branch!r} says "
                    f"{_show(expected[key])}",
                )
            )
        if key in session_data and session_data[key] != expected[key]:
            messages.append(
                _error(
                    session_path,
                    1,
                    f"{key} is {_show(session_data[key])} but branch {branch!r} "
                    f"says {_show(expected[key])}",
                )
            )
    return messages


def _check_anchors(
    ann_path: Path, moves: list, repo: Path, cache: dict[str, bool]
) -> list[LintMessage]:
    """Warn about ``@<hex>`` anchors that name no commit in ``repo``.

    Warnings only, never errors: an attempt branch is often linted before its
    commits are pushed, and the example session anchors deliberately point at
    commits that do not exist.
    """
    messages: list[LintMessage] = []
    for mv in moves:
        anchor = mv.anchor
        if anchor is None or _TRANSCRIPT_ANCHOR_RE.match(anchor):
            continue
        key = anchor.lower()
        if key not in cache:
            cache[key] = git_ok(["cat-file", "-e", f"{anchor}^{{commit}}"], cwd=repo)
        if not cache[key]:
            messages.append(
                _warning(
                    ann_path,
                    mv.line,
                    f"anchor @{anchor} does not resolve to a commit in {repo}; "
                    "it may be unpushed, rewritten, or a typo",
                )
            )
    return messages


# --------------------------------------------------------------------------
# One file
# --------------------------------------------------------------------------


def check_file(
    path,
    *,
    session: bool = False,
    repo: Optional[Path] = None,
    expect_branch: Optional[str] = None,
    anchor_cache: Optional[dict[str, bool]] = None,
) -> list[LintMessage]:
    """Run every enabled check over one ``annotations.md`` and return messages.

    Never raises for bad content; problems come back as :class:`LintMessage`
    values in reporting order (frontmatter, then body lines, then the
    cross-file checks).
    """
    ann_path = Path(path)
    meta, moves, messages = parse_annotations_file(ann_path)
    messages = list(messages)

    key_lines = _frontmatter_key_lines(ann_path)
    session_data: dict = {}
    session_path = ann_path.parent / SESSION_NAME

    if session:
        session_messages, session_data = _check_session(
            ann_path, meta, moves, key_lines
        )
        messages.extend(session_messages)

    if expect_branch:
        messages.extend(
            _check_branch(
                expect_branch, ann_path, meta, key_lines, session_data, session_path
            )
        )

    if repo is not None:
        messages.extend(
            _check_anchors(
                ann_path, moves, repo, anchor_cache if anchor_cache is not None else {}
            )
        )

    return messages


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lint_annotations.py",
        description=(
            "Check annotations.md files against the annotation grammar in "
            "TAXONOMY.md (v0.2)."
        ),
        epilog=(
            "Exit status: 0 = no errors (warnings are fine, and so is finding "
            "nothing to lint), 1 = at least one error, 2 = bad command line."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help=(
            "annotations.md files, or directories to search. Default: search "
            "--root."
        ),
    )
    parser.add_argument(
        "--root",
        default=".",
        metavar="DIR",
        help=(
            "directory to search when no PATH is given (default: the current "
            "directory)"
        ),
    )
    parser.add_argument(
        "--session",
        action="store_true",
        help=(
            "also require and validate the session.yaml next to each "
            "annotations.md, and check that both files agree on participant, "
            "challenge and attempt (errors), on the session day and on a "
            "duration that fits the annotated timeline (warnings)"
        ),
    )
    parser.add_argument(
        "--repo",
        metavar="PATH",
        help=(
            "git repository used to resolve @<hex> commit anchors; anchors that "
            "resolve to nothing are reported as warnings"
        ),
    )
    parser.add_argument(
        "--expect-branch",
        metavar="NAME",
        help=(
            f"check participant/challenge/attempt against a {BRANCH_SHAPE} branch "
            "name; any other name is skipped with a notice. Applies to files "
            f"named on the command line and to discovered "
            f"{ATTEMPT_SESSION_DIR}/{ANNOTATIONS_NAME} files -- never to the "
            "example or to already collected attempts"
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print errors and warnings only: no summary line, no notices",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point. Returns the process exit status; never raises for bad input."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    def notice(text: str) -> None:
        if not args.quiet:
            print(text, file=sys.stderr)

    repo: Optional[Path] = None
    if args.repo is not None:
        repo = Path(args.repo)
        if not repo.is_dir():
            print(
                f"lint_annotations.py: --repo {args.repo}: not a directory",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if not git_ok(["rev-parse", "--git-dir"], cwd=repo):
            print(
                f"lint_annotations.py: --repo {args.repo}: not a git repository "
                "(anchors can only be resolved inside one)",
                file=sys.stderr,
            )
            return EXIT_USAGE

    if args.expect_branch and parse_branch(args.expect_branch) is None:
        notice(
            f"note: --expect-branch {args.expect_branch!r} is not an attempt "
            f"branch ({BRANCH_SHAPE}); skipping the branch cross-check"
        )
        args.expect_branch = None

    files, problems, explicit = _collect(args.paths, args.root)
    if problems:
        for problem in problems:
            print(f"lint_annotations.py: {problem}", file=sys.stderr)
        return EXIT_USAGE

    if not files:
        where = " ".join(args.paths) if args.paths else args.root
        notice(
            f"note: no {ANNOTATIONS_NAME} found under {where}; nothing to lint"
        )
        return EXIT_OK

    anchor_cache: dict[str, bool] = {}
    errors = 0
    warnings = 0
    branch_checked = 0
    for f in files:
        branch: Optional[str] = None
        if args.expect_branch and branch_check_applies(f, explicit):
            branch = args.expect_branch
            branch_checked += 1
        for message in check_file(
            f,
            session=args.session,
            repo=repo,
            expect_branch=branch,
            anchor_cache=anchor_cache,
        ):
            print(str(message))
            if message.level == "error":
                errors += 1
            else:
                warnings += 1

    if args.expect_branch and branch_checked == 0:
        notice(
            f"note: --expect-branch {args.expect_branch!r} matched no "
            f"{ATTEMPT_SESSION_DIR}/{ANNOTATIONS_NAME}; nothing was cross-checked "
            "against the branch name"
        )

    if not args.quiet:
        print(
            f"{len(files)} file(s), {errors} error(s), {warnings} warning(s)"
        )
    return EXIT_ERRORS if errors else EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    sys.exit(main())
