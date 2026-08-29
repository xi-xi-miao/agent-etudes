#!/usr/bin/env python3
"""Check that a challenge directory honours the challenge contract.

Usage::

    check_challenge.py challenges/c001

Every check prints one ``PASS:`` or ``FAIL:`` line; the script exits 1 as soon
as any of them failed (but it always runs them all, so one run tells you
everything that is wrong). The contract, in order:

1. ``challenge.yaml`` loads and validates (schema_version, required keys, no
   unknown keys, status enum, the ``{instance}``/``{solution}`` placeholders);
2. the directory is named exactly after the manifest ``id``;
3. every tool the ``validate`` template refers to exists;
4. ``README.md`` exists (participants read it first);
5. ``instances/dev/`` holds at least one instance unless the status is draft;
6. every ``instances/*/*.json`` carries ``instance_id`` equal to its filename;
7. ``status: open`` requires the ``start_tag`` to exist in this repository;
8. ``status: closed`` requires ``instances/hidden/`` to be non-empty;
9. a declared ``dependency_group`` exists in ``pyproject.toml``;
10. no forbidden vocabulary (this repository reports distributions, never
    standings) in any text file of the challenge;
11. if ``tools/baseline.py`` exists, a baseline solution for the first dev
    instance passes through the ``validate`` template and the JSON on its last
    stdout line has the ``valid`` / ``summary`` / ``errors`` keys (not run
    while the status is still ``draft`` and no instance has been published).

Exit status: 0 when every check passed, 1 when any failed, 2 for a usage
problem.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from etudes_lib import (  # noqa: E402  (path shim above must run first)
    EtudesError,
    ManifestError,
    git_ok,
    load_manifest,
    repo_root_from,
)

#: The vocabulary this repository does not use. The words are assembled at
#: import time from fragments so that neither this file nor its compiled cache
#: matches the very check it implements (see scripts/check_words.sh).
_WORD_PARTS = (
    ("leader", "board"),
    ("sco", "re"),
    ("sco", "res"),
    ("ra", "nk"),
    ("ra", "nks"),
    ("ra", "nking"),
    ("ra", "nkings"),
    ("win", "ner"),
)
FORBIDDEN_WORDS = tuple(head + tail for head, tail in _WORD_PARTS)
FORBIDDEN_RE = re.compile(r"\b(?:" + "|".join(FORBIDDEN_WORDS) + r")\b", re.IGNORECASE)

SKIP_DIRS = {".git", "__pycache__", ".venv", ".pytest_cache", "node_modules"}
SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".ico"}


class Report:
    """Collects PASS/FAIL lines and remembers whether anything failed."""

    def __init__(self) -> None:
        self.failed = False

    def ok(self, text: str) -> None:
        print(f"PASS: {text}")

    def fail(self, text: str) -> None:
        self.failed = True
        print(f"FAIL: {text}")


# --------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------


def check_directory_name(report: Report, challenge_dir: Path, manifest: dict) -> None:
    cid = manifest["id"]
    if challenge_dir.name == cid:
        report.ok(f"directory name matches the manifest id ({cid})")
    else:
        report.fail(
            f"directory is named {challenge_dir.name!r} but the manifest id is "
            f"{cid!r}; a challenge directory is named exactly after its id"
        )


#: Command names that launch a script rather than being one.
_INTERPRETERS = {"python", "python3", "uv", "uvx", "bash", "sh", "env", "node"}


def _template_paths(template: str) -> list[str]:
    """Relative file paths mentioned by a command template.

    ``argv[0]`` counts too unless it is an interpreter, so a shebang-style
    template such as ``tools/validate.py {instance} {solution}`` is checked as
    well as ``python tools/validate.py ...``.
    """
    try:
        argv = shlex.split(template)
    except ValueError:
        return []
    if argv and argv[0] in _INTERPRETERS:
        argv = argv[1:]
    out = []
    for tok in argv:
        if tok.startswith("-") or tok.startswith("/"):
            continue
        if "{" in tok:
            continue
        if "/" in tok or tok.endswith((".py", ".sh")):
            out.append(tok)
    return out


def check_tools_exist(report: Report, challenge_dir: Path, manifest: dict) -> None:
    referenced = _template_paths(manifest["validate"])
    if not referenced:
        report.ok("the validate command refers to no files inside the challenge")
        return
    for rel in referenced:
        if (challenge_dir / rel).is_file():
            report.ok(f"validate command uses {rel}, which exists")
        else:
            report.fail(
                f"the validate command refers to {rel}, but "
                f"{challenge_dir / rel} does not exist"
            )


def check_readme(report: Report, challenge_dir: Path) -> None:
    if (challenge_dir / "README.md").is_file():
        report.ok("README.md exists")
    else:
        report.fail(
            f"{challenge_dir / 'README.md'} is missing; participants read it first"
        )


def check_instances(report: Report, challenge_dir: Path, manifest: dict) -> None:
    dev = challenge_dir / "instances" / "dev"
    dev_files = sorted(dev.glob("*.json")) if dev.is_dir() else []
    if manifest["status"] == "draft":
        report.ok(
            f"status is draft, so instances/dev may still be empty "
            f"({len(dev_files)} instance file(s) present)"
        )
    elif dev_files:
        report.ok(f"instances/dev holds {len(dev_files)} instance file(s)")
    else:
        report.fail(
            f"status is {manifest['status']} but {dev} holds no instance JSON; "
            "publish at least one development instance"
        )

    instances_root = challenge_dir / "instances"
    all_files = sorted(instances_root.glob("*/*.json")) if instances_root.is_dir() else []
    bad = 0
    for path in all_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            bad += 1
            report.fail(f"{path}: could not be read as JSON ({exc})")
            continue
        if not isinstance(data, dict) or data.get("instance_id") != path.stem:
            bad += 1
            got = data.get("instance_id") if isinstance(data, dict) else None
            report.fail(
                f"{path}: instance_id is {got!r} but the file name says "
                f"{path.stem!r}; the two must be identical"
            )
    if all_files and bad == 0:
        report.ok(f"all {len(all_files)} instance file(s) name themselves correctly")


def check_start_tag(report: Report, challenge_dir: Path, manifest: dict) -> None:
    if manifest["status"] != "open":
        return
    tag = manifest["start_tag"]
    try:
        repo = repo_root_from(challenge_dir)
    except EtudesError as exc:
        report.fail(
            f"status is open, so the start_tag {tag!r} must exist, but the "
            f"repository could not be found: {exc}"
        )
        return
    if git_ok(["rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"], cwd=repo):
        report.ok(f"start_tag {tag} exists in {repo}")
    else:
        report.fail(
            f"status is open but the tag {tag} does not exist in {repo}; create "
            f"it with: git tag -a {tag} -m '{manifest['id']} start'"
        )


def check_hidden(report: Report, challenge_dir: Path, manifest: dict) -> None:
    if manifest["status"] != "closed":
        return
    hidden = challenge_dir / "instances" / "hidden"
    files = sorted(hidden.glob("*.json")) if hidden.is_dir() else []
    if files:
        report.ok(f"status is closed and instances/hidden holds {len(files)} file(s)")
    else:
        report.fail(
            f"status is closed but {hidden} holds no instance JSON; the hidden "
            "instances are published together with their seeds when a round closes"
        )


def _dependency_groups(pyproject: Path) -> Optional[list]:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
        return None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    groups = data.get("dependency-groups")
    return sorted(groups) if isinstance(groups, dict) else None


def check_dependency_group(report: Report, challenge_dir: Path, manifest: dict) -> None:
    group = manifest.get("dependency_group")
    if not group:
        return
    pyproject = None
    for candidate in (challenge_dir.resolve(), *challenge_dir.resolve().parents):
        if (candidate / "pyproject.toml").is_file():
            pyproject = candidate / "pyproject.toml"
            break
    if pyproject is None:
        report.fail(
            f"the manifest declares dependency_group {group!r} but no "
            f"pyproject.toml was found above {challenge_dir}"
        )
        return
    groups = _dependency_groups(pyproject)
    if groups is None:
        report.fail(f"{pyproject}: could not be read as TOML with [dependency-groups]")
    elif group in groups:
        report.ok(f"dependency group {group!r} is declared in {pyproject}")
    else:
        report.fail(
            f"{pyproject} has no [dependency-groups] entry {group!r} "
            f"(declared groups: {', '.join(groups) or 'none'})"
        )


def _text_files(challenge_dir: Path):
    for path in sorted(challenge_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        yield path


def check_vocabulary(report: Report, challenge_dir: Path) -> None:
    """No competitive vocabulary anywhere in the challenge."""
    hits = []
    for path in _text_files(challenge_dir):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if FORBIDDEN_RE.search(line):
                hits.append(f"{path}:{number}: {line.strip()}")
    if not hits:
        report.ok("no competitive vocabulary in the challenge files")
        return
    report.fail(
        "competitive vocabulary found; this repository reports utilizations and "
        "distributions, never standings:"
    )
    for hit in hits:
        print(f"    {hit}")


def _expand_validate(template: str, instance: Path, solution: Path) -> list[str]:
    """Manifest template -> argv (same rules as scripts/validate_solutions.py)."""
    argv = shlex.split(template)
    argv = [
        tok.replace("{instance}", str(instance)).replace("{solution}", str(solution))
        for tok in argv
    ]
    if argv and argv[0] in ("python", "python3"):
        argv[0] = sys.executable
    return argv


def check_baseline_round_trip(
    report: Report, challenge_dir: Path, manifest: dict
) -> None:
    baseline = challenge_dir / "tools" / "baseline.py"
    if not baseline.is_file():
        return
    dev = challenge_dir / "instances" / "dev"
    instances = sorted(dev.glob("*.json")) if dev.is_dir() else []
    if not instances:
        if manifest["status"] == "draft":
            report.ok(
                "status is draft and there is no development instance yet, so "
                "the baseline round trip was not run"
            )
        else:
            report.fail(
                f"{baseline} exists but there is no development instance to run it on"
            )
        return
    instance = instances[0].resolve()

    with tempfile.TemporaryDirectory() as tmp:
        solution = Path(tmp) / instance.name
        try:
            # Absolute paths throughout: the command runs with the challenge
            # directory as its cwd, so a relative challenge_dir (which is what
            # `make check-challenge` and CI pass) would otherwise be resolved
            # twice.
            proc = subprocess.run(
                [
                    sys.executable,
                    str(baseline.resolve()),
                    str(instance),
                    "--out",
                    str(solution),
                ],
                cwd=str(challenge_dir),
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            report.fail(f"could not run {baseline}: {exc}")
            return
        if proc.returncode != 0 or not solution.is_file():
            report.fail(
                f"{baseline.name} failed on {instance.name} (exit "
                f"{proc.returncode}): {_tail(proc.stderr or proc.stdout)}"
            )
            return
        report.ok(f"baseline.py produced a solution for {instance.name}")

        argv = _expand_validate(manifest["validate"], instance, solution.resolve())
        try:
            proc = subprocess.run(
                argv, cwd=str(challenge_dir), capture_output=True, text=True
            )
        except OSError as exc:
            report.fail(f"could not run the validate command: {exc}")
            return

        payload = None
        for line in reversed(proc.stdout.splitlines()):
            if line.strip():
                try:
                    payload = json.loads(line.strip())
                except ValueError:
                    payload = None
                break
        if not isinstance(payload, dict):
            report.fail(
                "the validate command must print a JSON object as its last "
                f"stdout line (exit {proc.returncode}): "
                f"{_tail(proc.stderr or proc.stdout)}"
            )
            return
        missing = [key for key in ("valid", "summary", "errors") if key not in payload]
        if missing:
            report.fail(
                "the JSON printed by the validate command is missing the key(s) "
                f"{', '.join(missing)}; it must hold valid, summary and errors"
            )
        else:
            report.ok(
                "the validate command's JSON has the valid/summary/errors keys"
            )


def _tail(text: str, limit: int = 200) -> str:
    flat = " ".join((text or "").split())
    return flat[-limit:] if len(flat) > limit else flat


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_challenge.py",
        description="Check a challenge directory against the challenge contract.",
    )
    parser.add_argument(
        "challenge_dir", help="the challenge directory, e.g. challenges/c001"
    )
    return parser


def check_challenge(challenge_dir: Path) -> int:
    report = Report()
    print(f"Checking {challenge_dir}")
    try:
        manifest = load_manifest(challenge_dir)
    except ManifestError as exc:
        report.fail(str(exc))
        return 1
    report.ok(
        f"challenge.yaml is valid (id {manifest['id']}, status {manifest['status']})"
    )

    check_directory_name(report, challenge_dir, manifest)
    check_tools_exist(report, challenge_dir, manifest)
    check_readme(report, challenge_dir)
    check_instances(report, challenge_dir, manifest)
    check_start_tag(report, challenge_dir, manifest)
    check_hidden(report, challenge_dir, manifest)
    check_dependency_group(report, challenge_dir, manifest)
    check_vocabulary(report, challenge_dir)
    check_baseline_round_trip(report, challenge_dir, manifest)

    if report.failed:
        print(f"{challenge_dir}: contract check failed")
        return 1
    print(f"{challenge_dir}: contract check passed")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    challenge_dir = Path(args.challenge_dir).expanduser()
    if not challenge_dir.is_dir():
        print(
            f"error: {challenge_dir}: no such directory. Pass a challenge "
            "directory, for example challenges/c001.",
            file=sys.stderr,
        )
        return 2
    try:
        return check_challenge(challenge_dir)
    except EtudesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
