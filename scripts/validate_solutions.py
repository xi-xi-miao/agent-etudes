#!/usr/bin/env python3
"""Run a challenge's own validator over a list of solution files.

This script is challenge-agnostic: everything it knows about how to check a
solution comes from ``challenges/<id>/challenge.yaml``::

    validate: "python tools/validate.py {instance} {solution} --json"

The template is split with :func:`shlex.split`, ``{instance}`` and
``{solution}`` are replaced by absolute paths, a leading ``python`` /
``python3`` token becomes the interpreter running this script, and the command
runs with the challenge directory as its working directory.

The validator's contract (see docs/adding-a-challenge.md) is that its last
stdout line is a JSON object ``{"valid": bool, "summary": str,
"errors": [...], "measures": {...}}``, and that it exits 0 for a valid
solution, 1 for an invalid one and 2 when it could not read its input. This
script never formats measures itself -- it prints ``summary`` verbatim -- and
it keeps "the solution is wrong" (invalid) apart from "the harness broke"
(error).

Usage::

    validate_solutions.py [SOLUTION ...] [--changed-from-git BASE]
                          [--challenge cXXX | --branch NAME | --challenge-dir DIR]
                          [--challenge-root DIR] [--repo DIR]
                          [--summary FILE] [--no-summary] [--render-dir DIR]

Which challenge to validate against is resolved in this order, first hit wins:

1. ``--challenge-dir DIR`` -- the oracle directory itself, no lookup at all;
2. ``--challenge cXXX``;
3. ``--branch attempt/<cid>/<participant>/<n>``;
4. ``session/session.yaml``, found by walking *up from the directory of the
   first solution file* and stopping at that solution's own repository root --
   never the current directory, never this script's own checkout;
5. a lookup of the solution's ``instance_id`` across
   ``<challenge-root>/*/instances/*/``.

Steps 4 and 5 are only reached when no flag named a challenge, so an explicit
``--challenge``/``--branch``/``--challenge-dir`` can never be overridden by an
ambient ``session.yaml``.

Exit status: 0 when every solution is valid or skipped, 1 when any solution is
invalid or could not be checked, 2 for a usage/setup problem.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from etudes_lib import (  # noqa: E402  (path shim above must run first)
    CHALLENGE_ID_RE,
    EtudesError,
    load_manifest,
    load_yaml,
    parse_branch,
    repo_root_from,
)

RESULT_VALID = "valid"
RESULT_INVALID = "invalid"
RESULT_SKIPPED = "skipped"
RESULT_ERROR = "error"

#: Exit status a challenge validator uses for "I could not read this input"
#: (docs/adding-a-challenge.md section 3). It is a harness problem, never a
#: verdict on the solution, so it is reported as an error rather than invalid.
EXIT_UNREADABLE = 2

#: Results that must not fail the run.
_BENIGN = (RESULT_VALID, RESULT_SKIPPED)


class Row(NamedTuple):
    """One line of the report: what was checked and how it went."""

    file: str
    instance: str
    result: str
    summary: str


# --------------------------------------------------------------------------
# Collecting solution files
# --------------------------------------------------------------------------


def _looks_like_solution(path: str) -> bool:
    """True for ``.../solutions/**/<name>.json``.

    This is the repository-wide attempt-branch convention, not a manifest
    lookup: which challenge owns a file is only known *after* the file has
    been collected, so ``--changed-from-git`` cannot consult a manifest
    ``solutions_glob`` to decide what to collect. Matched on path components
    rather than with :mod:`fnmatch` because ``**`` is not recursive in
    :meth:`pathlib.PurePath.match`.
    """
    parts = Path(path).parts
    if not parts or not parts[-1].endswith(".json"):
        return False
    return "solutions" in parts[:-1]


def _changed_solution_files(base: str, repo: Path) -> list[Path]:
    """Solution files that changed between ``base`` and ``HEAD``."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=d", base, "HEAD"],
            cwd=str(repo),
            check=True,
            text=True,
            capture_output=True,
        )
    except OSError as exc:
        raise EtudesError(f"could not run git: {exc}") from None
    except subprocess.CalledProcessError as exc:
        detail = " ".join((exc.stderr or "").split())
        raise EtudesError(
            f"git diff {base} HEAD failed in {repo}: {detail or 'unknown error'}. "
            "--changed-from-git takes a single revision (a branch, tag or sha) "
            "that exists in this repository."
        ) from None
    out = []
    for line in proc.stdout.splitlines():
        name = line.strip()
        if name and _looks_like_solution(name):
            out.append(repo / name)
    return out


# --------------------------------------------------------------------------
# Finding the challenge that owns these solutions
# --------------------------------------------------------------------------


def _read_instance_id(path: Path) -> Optional[str]:
    """``instance_id`` of a solution file, or ``None`` if it cannot be read."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("instance_id"), str):
        return data["instance_id"].strip() or None
    return None


def _challenge_in_dir(directory: Path) -> Optional[str]:
    """The ``challenge:`` field of a ``session.yaml`` directly under ``directory``."""
    for candidate in (directory / "session" / "session.yaml", directory / "session.yaml"):
        if not candidate.is_file():
            continue
        try:
            data = load_yaml(candidate)
        except EtudesError:
            return None
        cid = data.get("challenge")
        if isinstance(cid, str) and CHALLENGE_ID_RE.fullmatch(cid):
            return cid
    return None


def _challenge_from_session(solutions: list[Path]) -> Optional[str]:
    """``challenge:`` from the ``session/session.yaml`` that owns these solutions.

    The search walks *upwards from each solution file's own directory* and
    stops at the first repository root it meets, so a run only ever reads the
    session.yaml of the attempt the solutions belong to. Deliberately not the
    current directory or the directory this script lives in: validating an
    exported oracle from inside another checkout used to pick up that
    checkout's ``session/session.yaml`` and select a challenge nobody asked
    for.
    """
    seen: set[Path] = set()
    for solution in solutions:
        start = solution.expanduser().resolve().parent
        for directory in (start, *start.parents):
            if directory in seen:
                break  # already walked from an earlier solution
            seen.add(directory)
            cid = _challenge_in_dir(directory)
            if cid is not None:
                return cid
            if (directory / ".git").exists():
                break  # a repository root: never look outside it
    return None


def _challenge_from_instance_ids(root: Path, solutions: list[Path]) -> Optional[Path]:
    """Locate the challenge directory that publishes a solution's instance."""
    if not root.is_dir():
        return None
    for solution in solutions:
        instance_id = _read_instance_id(solution)
        if not instance_id:
            continue
        matches = sorted(root.glob(f"*/instances/*/{instance_id}.json"))
        owners = sorted({m.parents[2] for m in matches})
        if len(owners) == 1:
            return owners[0]
    return None


def _resolve_challenge_dir(args, solutions: list[Path], repo: Path) -> Path:
    """Work out which challenge directory is the oracle for this run."""
    if args.challenge_dir:
        d = Path(args.challenge_dir).expanduser()
        if not d.is_dir():
            raise EtudesError(f"--challenge-dir {d}: no such directory")
        return d.resolve()

    root = (
        Path(args.challenge_root).expanduser().resolve()
        if args.challenge_root
        else repo / "challenges"
    )

    cid = None
    if args.challenge:
        cid = args.challenge
        if not CHALLENGE_ID_RE.fullmatch(cid):
            raise EtudesError(
                f"--challenge {cid!r} is not a challenge id; it must look like c001"
            )
    elif args.branch:
        parsed = parse_branch(args.branch.strip())
        if parsed is None:
            raise EtudesError(
                f"--branch {args.branch!r} is not an attempt branch; expected "
                "attempt/<cid>/<participant>/<n>, for example "
                "attempt/c001/alice/1. Pass --challenge cXXX instead."
            )
        cid = parsed[0]
    else:
        cid = _challenge_from_session(solutions)

    if cid is not None:
        d = root / cid
        if not d.is_dir():
            raise EtudesError(
                f"challenge {cid} was selected but {d} does not exist. "
                "Point --challenge-root at the directory that holds the "
                "challenge directories (default: <repo>/challenges)."
            )
        return d.resolve()

    found = _challenge_from_instance_ids(root, solutions)
    if found is not None:
        return found.resolve()

    raise EtudesError(
        "could not work out which challenge these solutions belong to. Pass "
        "--challenge cXXX (or --challenge-dir DIR), or validate solution files "
        "that live in an attempt checkout with a session/session.yaml."
    )


# --------------------------------------------------------------------------
# Running the validator
# --------------------------------------------------------------------------


def _expand_command(template: str, instance: Path, solution: Path) -> list[str]:
    """Turn the manifest ``validate`` template into an argv list."""
    try:
        argv = shlex.split(template)
    except ValueError as exc:
        raise EtudesError(
            f"the validate command in challenge.yaml cannot be parsed as a "
            f"shell command ({exc}): {template!r}"
        ) from None
    if not argv:
        raise EtudesError("the validate command in challenge.yaml is empty")
    argv = [
        tok.replace("{instance}", str(instance)).replace("{solution}", str(solution))
        for tok in argv
    ]
    if argv[0] in ("python", "python3"):
        argv[0] = sys.executable
    return argv


def _last_json_object(stdout: str) -> Optional[dict]:
    """Parse the last non-empty stdout line as a JSON object."""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None
    return None


def _tail(text: str, limit: int = 200) -> str:
    """A short, single-line excerpt of a command's output."""
    flat = " ".join((text or "").split())
    return flat[-limit:] if len(flat) > limit else flat


def _validate_one(
    display: str,
    solution: Path,
    challenge_dir: Path,
    manifest: dict,
) -> tuple[Row, Optional[Path]]:
    """Check one solution. Returns its row plus the instance file it used."""
    try:
        raw = solution.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Row(display, "", RESULT_ERROR, "no such file"), None
    except UnicodeDecodeError as exc:
        return Row(display, "", RESULT_ERROR, f"file is not valid UTF-8: {exc}"), None
    except OSError as exc:
        return Row(display, "", RESULT_ERROR, f"could not read file: {exc}"), None

    try:
        data = json.loads(raw)
    except ValueError as exc:
        return Row(display, "", RESULT_ERROR, f"not valid JSON: {exc}"), None
    if not isinstance(data, dict):
        return Row(display, "", RESULT_ERROR, "solution must be a JSON object"), None

    instance_id = data.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id.strip():
        return (
            Row(
                display,
                "",
                RESULT_ERROR,
                'solution has no "instance_id" string, so the instance it '
                "belongs to cannot be found",
            ),
            None,
        )
    instance_id = instance_id.strip()

    matches = sorted((challenge_dir / "instances").glob(f"*/{instance_id}.json"))
    if not matches:
        return (
            Row(
                display,
                instance_id,
                RESULT_SKIPPED,
                "instance not published",
            ),
            None,
        )
    if len(matches) > 1:
        names = ", ".join(str(m.relative_to(challenge_dir)) for m in matches)
        return (
            Row(
                display,
                instance_id,
                RESULT_ERROR,
                f"instance {instance_id} is published more than once: {names}",
            ),
            None,
        )
    instance = matches[0].resolve()

    argv = _expand_command(manifest["validate"], instance, solution.resolve())
    try:
        proc = subprocess.run(
            argv, cwd=str(challenge_dir), capture_output=True, text=True
        )
    except OSError as exc:
        return (
            Row(
                display,
                instance_id,
                RESULT_ERROR,
                f"could not run the validate command ({shlex.join(argv)}): {exc}",
            ),
            instance,
        )

    report = _last_json_object(proc.stdout)

    if proc.returncode == EXIT_UNREADABLE:
        # Contract (docs/adding-a-challenge.md section 3): exit 2 means the
        # validator could not read its input -- not that the solution is
        # wrong. Reporting that as "invalid" would blame a participant for a
        # broken harness, so it stays an error even when a JSON line was
        # printed alongside it.
        detail = report.get("summary") if isinstance(report, dict) else None
        if not isinstance(detail, str) or not detail.strip():
            detail = _tail(proc.stderr or proc.stdout) or "nothing was printed"
        return (
            Row(
                display,
                instance_id,
                RESULT_ERROR,
                f"the validate command exited {EXIT_UNREADABLE}, meaning it "
                f"could not read its input: {' '.join(detail.split())}",
            ),
            instance,
        )

    if report is None:
        return (
            Row(
                display,
                instance_id,
                RESULT_ERROR,
                f"the validate command exited {proc.returncode} without a JSON "
                f"object on its last stdout line: {_tail(proc.stderr or proc.stdout)}",
            ),
            instance,
        )

    valid = report.get("valid")
    if not isinstance(valid, bool):
        return (
            Row(
                display,
                instance_id,
                RESULT_ERROR,
                f"the validate command's JSON has no boolean \"valid\" field: "
                f"{_tail(json.dumps(report))}",
            ),
            instance,
        )

    summary = report.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        summary = "valid" if valid else "invalid"
    return (
        Row(
            display,
            instance_id,
            RESULT_VALID if valid else RESULT_INVALID,
            " ".join(summary.split()),
        ),
        instance,
    )


def _render(
    challenge_dir: Path, instance: Path, solution: Path, render_dir: Path
) -> None:
    """Best-effort SVG render; never affects the exit status."""
    renderer = challenge_dir / "tools" / "render.py"
    if not renderer.is_file():
        return
    render_dir.mkdir(parents=True, exist_ok=True)
    out = render_dir / (solution.stem + ".svg")
    try:
        subprocess.run(
            [
                sys.executable,
                str(renderer),
                str(instance),
                str(solution.resolve()),
                "--out",
                str(out),
            ],
            cwd=str(challenge_dir),
            capture_output=True,
            text=True,
        )
    except OSError as exc:  # pragma: no cover - defensive
        print(f"note: could not render {solution}: {exc}")


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _cell(text: str) -> str:
    """Make a string safe for one markdown table cell."""
    return " ".join(str(text).split()).replace("|", r"\|") or "-"


def markdown_table(rows: list[Row], challenge_id: str) -> str:
    """The markdown report appended to ``--summary`` (and printed by default)."""
    lines = [f"#### Solution validation - {challenge_id}", ""]
    lines.append("| file | instance | result | summary |")
    lines.append("| --- | --- | --- | --- |")
    for row in rows:
        lines.append(
            f"| `{_cell(row.file)}` | {_cell(row.instance)} | {_cell(row.result)} "
            f"| {_cell(row.summary)} |"
        )
    lines.append("")
    return "\n".join(lines)


def _tally(rows: list[Row]) -> str:
    counts = {name: 0 for name in (RESULT_VALID, RESULT_INVALID, RESULT_SKIPPED, RESULT_ERROR)}
    for row in rows:
        counts[row.result] = counts.get(row.result, 0) + 1
    parts = [f"{counts[name]} {name}" for name in counts if counts[name]]
    n = len(rows)
    return f"{n} solution{'' if n == 1 else 's'}: " + (", ".join(parts) or "nothing to do")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate_solutions.py",
        description=(
            "Validate solution files with the validator of the challenge they "
            "belong to."
        ),
        epilog=(
            "Which challenge is used, first hit wins: --challenge-dir, then "
            "--challenge, then --branch, then the session/session.yaml found by "
            "walking up from the first solution file's own directory (stopping "
            "at that solution's repository root -- never the current directory "
            "or this script's checkout), then a lookup of the solution's "
            "instance_id under --challenge-root. An explicit flag is never "
            "overridden by an ambient session.yaml."
        ),
    )
    parser.add_argument("solutions", nargs="*", help="solution JSON files to check")
    parser.add_argument(
        "--changed-from-git",
        metavar="BASE",
        help=(
            "also check every solutions/**/*.json that changed between BASE (a "
            "single revision) and HEAD"
        ),
    )
    parser.add_argument(
        "--challenge", metavar="cXXX", help="challenge id to validate against"
    )
    parser.add_argument(
        "--branch",
        metavar="NAME",
        help="attempt branch name to read the challenge id from",
    )
    parser.add_argument(
        "--challenge-dir",
        metavar="DIR",
        help=(
            "use this directory as the challenge oracle directly, skipping the "
            "challenge-root/id lookup"
        ),
    )
    parser.add_argument(
        "--challenge-root",
        metavar="DIR",
        help="directory holding the challenge directories (default: <repo>/challenges)",
    )
    parser.add_argument(
        "--repo", metavar="DIR", help="repository root (default: found from the cwd)"
    )
    parser.add_argument(
        "--summary",
        metavar="FILE",
        help="append the markdown report to this file (e.g. $GITHUB_STEP_SUMMARY)",
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="do not print the markdown table on stdout",
    )
    parser.add_argument(
        "--render-dir",
        metavar="DIR",
        help="if the challenge ships tools/render.py, write an SVG per solution here",
    )
    return parser


def _find_repo(args, solutions: list[Path]) -> Path:
    """Repository root: --repo, else the cwd's repo, else a solution's repo."""
    if args.repo:
        d = Path(args.repo).expanduser()
        if not d.is_dir():
            raise EtudesError(f"--repo {d}: no such directory")
        return d.resolve()
    for hint in (Path.cwd(), *[p.parent for p in solutions]):
        try:
            return repo_root_from(hint)
        except EtudesError:
            continue
    return Path.cwd().resolve()


def run(args) -> int:
    solutions = [Path(p).expanduser() for p in args.solutions]
    repo = _find_repo(args, solutions)
    if args.changed_from_git:
        known = {p.resolve() for p in solutions if p.exists()}
        for extra in _changed_solution_files(args.changed_from_git, repo):
            if extra.resolve() not in known:
                solutions.append(extra)
                known.add(extra.resolve())

    if not solutions:
        print("No solution files to validate.")
        return 0

    challenge_dir = _resolve_challenge_dir(args, solutions, repo)
    manifest = load_manifest(challenge_dir)
    print(f"Validating {len(solutions)} solution file(s) with {challenge_dir}")

    render_dir = Path(args.render_dir).expanduser() if args.render_dir else None

    rows: list[Row] = []
    for solution in solutions:
        display = _display_path(solution, repo)
        row, instance = _validate_one(display, solution, challenge_dir, manifest)
        rows.append(row)
        print(f"  [{row.result}] {display}: {row.summary}")
        if render_dir is not None and instance is not None:
            _render(challenge_dir, instance, solution, render_dir)

    table = markdown_table(rows, str(manifest["id"]))
    if not args.no_summary:
        print()
        print(table)
    if args.summary:
        summary_path = Path(args.summary).expanduser()
        parent = summary_path.parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(table + "\n")

    print(_tally(rows))
    return 0 if all(row.result in _BENIGN for row in rows) else 1


def _display_path(path: Path, repo: Path) -> str:
    """Repo-relative path when possible, so reports read the same everywhere."""
    try:
        return str(path.resolve().relative_to(repo))
    except ValueError:
        return str(path)


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except EtudesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("interrupted", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
