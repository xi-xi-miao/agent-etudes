"""Tests for ``scripts/validate_solutions.py``.

The script is driven as a subprocess throughout: its contract is the exit
status, the human lines it prints and the markdown table it appends to
``--summary``, none of which an in-process import would exercise.

Everything runs against ``tests/fixtures/fake-challenge`` (id ``c999``), whose
validator accepts a solution when its ``value`` equals the instance ``target``.
Because that fixture directory is not named after its id, the tests use the
``--challenge-dir`` escape hatch, plus one copy of the fixture into a
``c999/`` directory for the ``--challenge-root`` / ``--challenge`` / ``--branch``
paths.

Every run is hermetic: the fixture is copied into ``tmp_path`` first (the
module-level ``fake_challenge_dir`` below overrides the session fixture in
``conftest.py``) and the working directory is ``tmp_path`` too. Naming a path
inside this repository would let the script walk up to the repository's own
``session/session.yaml`` and resolve some other challenge -- which is exactly
the accident this isolation exists to rule out.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_solutions.py"
IGNORE = shutil.ignore_patterns("__pycache__")


def run(*args, cwd=None) -> subprocess.CompletedProcess:
    """Run the script with ``args`` and capture everything it produced."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *[str(a) for a in args]],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
    )


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test from ``tmp_path``, never from inside this repository."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def fake_challenge_dir(tmp_path: Path, repo_root: Path) -> Path:
    """A private copy of ``tests/fixtures/fake-challenge`` inside ``tmp_path``.

    Overrides the session-scoped fixture in ``conftest.py`` so that no solution
    path handed to the script lives in the repository under test.
    """
    source = repo_root / "tests" / "fixtures" / "fake-challenge"
    destination = tmp_path / "fake-challenge"
    shutil.copytree(source, destination, ignore=IGNORE)
    return destination


@pytest.fixture
def challenge_root(tmp_path: Path, fake_challenge_dir: Path) -> Path:
    """A ``challenges/``-shaped directory holding the fixture as ``c999``."""
    root = tmp_path / "oracle"
    shutil.copytree(fake_challenge_dir, root / "c999", ignore=IGNORE)
    return root


def example(fake_challenge_dir: Path, name: str) -> Path:
    return fake_challenge_dir / "examples" / name


def table_rows(text: str) -> list[str]:
    """The data rows of the markdown table in ``text``."""
    return [
        line
        for line in text.splitlines()
        if line.startswith("| `") and "| ---" not in line
    ]


# --------------------------------------------------------------------------
# Results per solution
# --------------------------------------------------------------------------


def test_valid_solution_exits_zero_and_reports_a_row(
    tmp_path: Path, fake_challenge_dir: Path
):
    summary = tmp_path / "summary.md"
    proc = run(
        example(fake_challenge_dir, "valid.json"),
        "--challenge-dir",
        fake_challenge_dir,
        "--summary",
        summary,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "[valid]" in proc.stdout
    assert "VALID value=10" in proc.stdout

    written = summary.read_text(encoding="utf-8")
    rows = table_rows(written)
    assert len(rows) == 1
    assert "valid.json" in rows[0]
    assert "c999-dev-01" in rows[0]
    assert "| valid |" in rows[0]
    assert "VALID value=10" in rows[0]


def test_invalid_solution_exits_one(tmp_path: Path, fake_challenge_dir: Path):
    summary = tmp_path / "summary.md"
    proc = run(
        example(fake_challenge_dir, "invalid.json"),
        "--challenge-dir",
        fake_challenge_dir,
        "--summary",
        summary,
    )

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "[invalid]" in proc.stdout
    assert "does not equal target" in proc.stdout
    assert "| invalid |" in summary.read_text(encoding="utf-8")


def test_unpublished_instance_is_skipped_not_failed(
    tmp_path: Path, fake_challenge_dir: Path
):
    summary = tmp_path / "summary.md"
    proc = run(
        example(fake_challenge_dir, "unknown-instance.json"),
        "--challenge-dir",
        fake_challenge_dir,
        "--summary",
        summary,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "[skipped]" in proc.stdout
    row = table_rows(summary.read_text(encoding="utf-8"))[0]
    assert "| skipped |" in row
    assert "instance not published" in row
    assert "c999-dev-99" in row


def test_mixed_run_reports_every_file_and_fails(
    tmp_path: Path, fake_challenge_dir: Path
):
    summary = tmp_path / "summary.md"
    proc = run(
        example(fake_challenge_dir, "valid.json"),
        example(fake_challenge_dir, "invalid.json"),
        example(fake_challenge_dir, "unknown-instance.json"),
        "--challenge-dir",
        fake_challenge_dir,
        "--summary",
        summary,
    )

    assert proc.returncode == 1, proc.stdout + proc.stderr
    rows = table_rows(summary.read_text(encoding="utf-8"))
    assert len(rows) == 3
    assert sum("| valid |" in r for r in rows) == 1
    assert sum("| invalid |" in r for r in rows) == 1
    assert sum("| skipped |" in r for r in rows) == 1
    assert "3 solutions:" in proc.stdout


def test_unreadable_solution_is_an_error(tmp_path: Path, fake_challenge_dir: Path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    proc = run(broken, "--challenge-dir", fake_challenge_dir)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "[error]" in proc.stdout
    assert "not valid JSON" in proc.stdout


def test_solution_without_instance_id_is_an_error(
    tmp_path: Path, fake_challenge_dir: Path
):
    orphan = tmp_path / "orphan.json"
    orphan.write_text(json.dumps({"value": 10}), encoding="utf-8")

    proc = run(orphan, "--challenge-dir", fake_challenge_dir)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "instance_id" in proc.stdout


def test_instance_published_twice_is_an_error(
    tmp_path: Path, challenge_root: Path, fake_challenge_dir: Path
):
    """An instance id must resolve to exactly one file, or nothing is trustworthy."""
    dev = challenge_root / "c999" / "instances" / "dev" / "c999-dev-01.json"
    hidden = challenge_root / "c999" / "instances" / "hidden"
    hidden.mkdir(parents=True, exist_ok=True)
    shutil.copy(dev, hidden / "c999-dev-01.json")

    proc = run(
        example(fake_challenge_dir, "valid.json"),
        "--challenge-root",
        challenge_root,
        "--challenge",
        "c999",
        cwd=tmp_path,
    )

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "[error]" in proc.stdout
    assert "published more than once" in proc.stdout
    assert "instances/dev/c999-dev-01.json" in proc.stdout
    assert "instances/hidden/c999-dev-01.json" in proc.stdout


def test_validator_exit_two_is_an_error_not_an_invalid_verdict(
    tmp_path: Path, challenge_root: Path, fake_challenge_dir: Path
):
    """Exit 2 means the harness broke, never "this participant is wrong"."""
    challenge = challenge_root / "c999"
    (challenge / "tools" / "broken.py").write_text(
        "import json, sys\n"
        'print(json.dumps({"valid": False, "summary": "could not read the '
        'instance", "errors": []}))\n'
        "sys.exit(2)\n",
        encoding="utf-8",
    )
    manifest = challenge / "challenge.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "tools/validate.py {instance} {solution} --json",
            "tools/broken.py {instance} {solution}",
        ),
        encoding="utf-8",
    )

    summary = tmp_path / "summary.md"
    proc = run(
        example(fake_challenge_dir, "valid.json"),
        "--challenge-dir",
        challenge,
        "--summary",
        summary,
    )

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "[error]" in proc.stdout
    assert "[invalid]" not in proc.stdout
    assert "could not read its input" in proc.stdout
    assert "could not read the instance" in proc.stdout
    assert "| error |" in summary.read_text(encoding="utf-8")


def test_missing_file_is_an_error(tmp_path: Path, fake_challenge_dir: Path):
    proc = run(tmp_path / "nope.json", "--challenge-dir", fake_challenge_dir)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "no such file" in proc.stdout


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def test_summary_file_is_appended_not_overwritten(
    tmp_path: Path, fake_challenge_dir: Path
):
    summary = tmp_path / "summary.md"
    summary.write_text("earlier content\n", encoding="utf-8")

    for _ in range(2):
        proc = run(
            example(fake_challenge_dir, "valid.json"),
            "--challenge-dir",
            fake_challenge_dir,
            "--summary",
            summary,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

    written = summary.read_text(encoding="utf-8")
    assert written.startswith("earlier content")
    assert written.count("#### Solution validation") == 2
    assert len(table_rows(written)) == 2


def test_no_summary_suppresses_the_table_on_stdout(fake_challenge_dir: Path):
    proc = run(
        example(fake_challenge_dir, "valid.json"),
        "--challenge-dir",
        fake_challenge_dir,
        "--no-summary",
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "#### Solution validation" not in proc.stdout
    assert "[valid]" in proc.stdout


def test_no_solution_files_is_not_a_failure(tmp_path: Path, fake_challenge_dir: Path):
    proc = run("--challenge-dir", fake_challenge_dir, cwd=tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "No solution files" in proc.stdout


# --------------------------------------------------------------------------
# Resolving the challenge
# --------------------------------------------------------------------------


def test_challenge_root_and_id(tmp_path: Path, challenge_root: Path, fake_challenge_dir: Path):
    proc = run(
        example(fake_challenge_dir, "valid.json"),
        "--challenge-root",
        challenge_root,
        "--challenge",
        "c999",
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "[valid]" in proc.stdout


def test_branch_name_selects_the_challenge(
    tmp_path: Path, challenge_root: Path, fake_challenge_dir: Path
):
    proc = run(
        example(fake_challenge_dir, "valid.json"),
        "--challenge-root",
        challenge_root,
        "--branch",
        "attempt/c999/alice/2",
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "c999" in proc.stdout


def test_bad_branch_name_is_a_friendly_usage_error(
    tmp_path: Path, challenge_root: Path, fake_challenge_dir: Path
):
    proc = run(
        example(fake_challenge_dir, "valid.json"),
        "--challenge-root",
        challenge_root,
        "--branch",
        "main",
        cwd=tmp_path,
    )

    assert proc.returncode == 2
    assert "attempt/<cid>/<participant>/<n>" in proc.stderr


def test_instance_id_lookup_finds_the_challenge(
    tmp_path: Path, challenge_root: Path, fake_challenge_dir: Path
):
    proc = run(
        example(fake_challenge_dir, "valid.json"),
        "--challenge-root",
        challenge_root,
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "c999" in proc.stdout


def test_unknown_challenge_id_explains_itself(
    tmp_path: Path, challenge_root: Path, fake_challenge_dir: Path
):
    proc = run(
        example(fake_challenge_dir, "valid.json"),
        "--challenge-root",
        challenge_root,
        "--challenge",
        "c123",
        cwd=tmp_path,
    )

    assert proc.returncode == 2
    assert "c123" in proc.stderr


def test_session_yaml_selects_the_challenge(
    tmp_git_repo: Path, fake_challenge_dir: Path
):
    """The attempt-branch layout: session/session.yaml names the challenge."""
    shutil.copytree(
        fake_challenge_dir, tmp_git_repo / "challenges" / "c999", ignore=IGNORE
    )
    session = tmp_git_repo / "session"
    session.mkdir()
    (session / "session.yaml").write_text(
        "participant: alice\nchallenge: c999\nattempt: 1\n", encoding="utf-8"
    )
    solutions = tmp_git_repo / "solutions"
    solutions.mkdir()
    shutil.copy(
        example(fake_challenge_dir, "valid.json"), solutions / "c999-dev-01.json"
    )

    proc = run("solutions/c999-dev-01.json", cwd=tmp_git_repo)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "[valid]" in proc.stdout
    # the report shows repository-relative paths
    assert "solutions/c999-dev-01.json" in proc.stdout


def test_an_unrelated_repositorys_session_yaml_is_never_read(
    tmp_git_repo: Path, challenge_root: Path, fake_challenge_dir: Path
):
    """The session.yaml fallback follows the *solution*, not the working directory.

    Running the tool from inside some other checkout -- an attempt branch, say,
    while validating an exported oracle -- used to pick up that checkout's
    ``session/session.yaml`` and select a challenge the caller never named.
    """
    session = tmp_git_repo / "session"
    session.mkdir()
    (session / "session.yaml").write_text(
        "participant: alice\nchallenge: c001\nattempt: 1\n", encoding="utf-8"
    )

    proc = run(
        example(fake_challenge_dir, "valid.json"),
        "--challenge-root",
        challenge_root,
        cwd=tmp_git_repo,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "c999" in proc.stdout
    assert "c001" not in proc.stdout + proc.stderr


def test_help_documents_the_resolution_order():
    proc = run("--help")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    for fragment in (
        "--challenge-dir",
        "--challenge",
        "--branch",
        "session/session.yaml",
        "instance_id",
    ):
        assert fragment in proc.stdout, fragment
    assert "walking up from the first solution file" in " ".join(proc.stdout.split())


def test_changed_from_git_lists_solution_files(
    tmp_git_repo: Path, fake_challenge_dir: Path
):
    shutil.copytree(
        fake_challenge_dir, tmp_git_repo / "challenges" / "c999", ignore=IGNORE
    )

    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=tmp_git_repo, check=True, capture_output=True, text=True
        )

    git("add", "challenges")
    git("commit", "-m", "add the challenge")

    solutions = tmp_git_repo / "solutions"
    solutions.mkdir()
    shutil.copy(
        example(fake_challenge_dir, "valid.json"), solutions / "c999-dev-01.json"
    )
    (tmp_git_repo / "notes.md").write_text("not a solution\n", encoding="utf-8")
    git("add", "solutions", "notes.md")
    git("commit", "-m", "add a solution")

    proc = run("--changed-from-git", "HEAD~1", "--challenge", "c999", cwd=tmp_git_repo)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "solutions/c999-dev-01.json" in proc.stdout
    assert "notes.md" not in proc.stdout
    assert "1 solution:" in proc.stdout


def test_changed_from_git_with_a_bad_revision_is_friendly(tmp_git_repo: Path):
    proc = run("--changed-from-git", "no-such-revision", cwd=tmp_git_repo)

    assert proc.returncode == 2
    assert "--changed-from-git" in proc.stderr
