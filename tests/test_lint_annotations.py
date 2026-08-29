"""Tests for ``scripts/lint_annotations.py``.

Every behaviour is checked twice where it matters: once through the real
command line (a subprocess, so exit codes and stdout/stderr routing are the
ones a participant and CI actually see) and once by calling ``main()``
in-process (fast, and it keeps the tracebacks readable while developing).

HANDOFF section 10 acceptance criteria 1 and 2 are covered by
:func:`test_example_lints_clean_via_cli` and the ``CORRUPTIONS`` table.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import load_tool

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "lint_annotations.py"
EXAMPLE_DIR = REPO_ROOT / "examples" / "example-session"
EXAMPLE_ANNOTATIONS = (EXAMPLE_DIR / "annotations.md").read_text(encoding="utf-8")
EXAMPLE_SESSION = (EXAMPLE_DIR / "session.yaml").read_text(encoding="utf-8")

lint = load_tool(SCRIPT, "lint_annotations_cli")

_UV = shutil.which("uv")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def run_cli(*args: str, cwd=None) -> subprocess.CompletedProcess:
    """Run the linter as a real subprocess.

    ``uv run --no-sync`` is used when uv is on PATH (that is the documented way
    to run everything in this repository); ``--no-sync`` keeps the test suite
    from touching the lockfile, and ``--project`` lets the child run from any
    working directory. Without uv the current interpreter is used, which under
    ``uv run pytest`` is the very same virtualenv.
    """
    if _UV:
        cmd = [_UV, "run", "--no-sync", "--project", str(REPO_ROOT), "python"]
    else:  # pragma: no cover - only on a machine without uv
        cmd = [sys.executable]
    cmd += [str(SCRIPT), *args]
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True
    )


def write_session_dir(
    base: Path,
    *,
    annotations: str = EXAMPLE_ANNOTATIONS,
    session: str | None = EXAMPLE_SESSION,
    name: str = "session",
) -> Path:
    """Create ``<base>/<name>/`` holding a copy of the example attempt."""
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "annotations.md").write_text(annotations, encoding="utf-8")
    if session is not None:
        (d / "session.yaml").write_text(session, encoding="utf-8")
    return d


def replace_line(text: str, needle: str, new_line: str) -> str:
    """Swap the single line containing ``needle`` for ``new_line``."""
    lines = text.splitlines()
    hits = [i for i, line in enumerate(lines) if needle in line]
    assert len(hits) == 1, f"{needle!r} matched {len(hits)} lines, expected exactly 1"
    lines[hits[0]] = new_line
    return "\n".join(lines) + "\n"


def line_number_of(text: str, needle: str) -> int:
    """1-based line number of the single line containing ``needle``."""
    hits = [i for i, line in enumerate(text.splitlines(), 1) if needle in line]
    assert len(hits) == 1, f"{needle!r} matched {len(hits)} lines, expected exactly 1"
    return hits[0]


def errors_in(output: str) -> list[str]:
    return [ln for ln in output.splitlines() if ": error: " in ln]


def warnings_in(output: str) -> list[str]:
    return [ln for ln in output.splitlines() if ": warning: " in ln]


# --------------------------------------------------------------------------
# Acceptance criterion 1: the shipped example lints clean
# --------------------------------------------------------------------------


def test_example_lints_clean_via_cli():
    proc = run_cli("examples/example-session/annotations.md", "--session", cwd=REPO_ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert errors_in(proc.stdout) == []
    assert "1 file(s), 0 error(s), 0 warning(s)" in proc.stdout


def test_example_lints_clean_via_main(capsys):
    rc = lint.main([str(EXAMPLE_DIR / "annotations.md"), "--session"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert errors_in(out) == []


def test_runs_from_any_cwd_with_absolute_paths(tmp_path):
    """The scripts must not depend on being started from the repository root."""
    proc = run_cli(
        str(EXAMPLE_DIR / "annotations.md"), "--session", cwd=tmp_path
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 error(s)" in proc.stdout


def test_help_is_available():
    proc = run_cli("--help")
    assert proc.returncode == 0
    assert "--expect-branch" in proc.stdout


# --------------------------------------------------------------------------
# Acceptance criterion 2: the four corruptions
# --------------------------------------------------------------------------

#: ``(id, needle, replacement line, fragment expected in the message)``
CORRUPTIONS = [
    pytest.param(
        "SCOUT",
        '+0:00  Recon    SCOOT   "asked for a map of the challenge"  @3f9a1c2',
        "unknown move",
        id="unknown-move",
    ),
    pytest.param(
        "PAIR",
        '+0:05  Build    PAIR    "stepped through the rotation sweep together"',
        "goes backwards",
        id="out-of-order-timestamp",
    ),
    pytest.param(
        "X-timebox",
        "+3:31  Verify   X-timebox      (rabbit-hole)",
        "requires a",
        id="wildcard-without-comment",
    ),
    pytest.param(
        "DISPATCH",
        "+0:52  Build>   DISPATCH   ??  (yes-and)",
        "requires a",
        id="double-question-without-comment",
    ),
]


def _corrupted(tmp_path: Path, needle: str, new_line: str) -> tuple[Path, int]:
    text = replace_line(EXAMPLE_ANNOTATIONS, needle, new_line)
    d = write_session_dir(tmp_path, annotations=text)
    return d / "annotations.md", line_number_of(text, new_line.split()[2])


@pytest.mark.parametrize("needle,new_line,fragment", CORRUPTIONS)
def test_corruption_reported_via_cli(tmp_path, needle, new_line, fragment):
    path, expected_line = _corrupted(tmp_path, needle, new_line)
    proc = run_cli(str(path), "--session")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    reported = errors_in(proc.stdout)
    assert reported, proc.stdout
    assert any(
        line.startswith(f"{path}:{expected_line}: error: ") and fragment in line
        for line in reported
    ), reported


@pytest.mark.parametrize("needle,new_line,fragment", CORRUPTIONS)
def test_corruption_reported_via_main(tmp_path, capsys, needle, new_line, fragment):
    path, expected_line = _corrupted(tmp_path, needle, new_line)
    rc = lint.main([str(path), "--session"])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert any(
        line.startswith(f"{path}:{expected_line}: error: ") and fragment in line
        for line in errors_in(out)
    ), out


def test_corruption_message_names_the_line_and_the_file(tmp_path, capsys):
    """A participant must be able to jump straight to the offending line."""
    path, expected_line = _corrupted(tmp_path, "SCOUT", CORRUPTIONS[0].values[1])
    lint.main([str(path)])
    out = capsys.readouterr().out
    assert f"{path}:{expected_line}: error: " in out
    assert "SCOOT" in out


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def test_empty_directory_is_not_a_failure(tmp_path, capsys):
    rc = lint.main(["--root", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert "nothing to lint" in captured.err


def test_empty_directory_is_not_a_failure_via_cli(tmp_path):
    proc = run_cli("--root", str(tmp_path))
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert "nothing to lint" in proc.stderr


def test_discovery_finds_nested_sessions(tmp_path, capsys):
    write_session_dir(tmp_path, name="results/c001/alice/1")
    write_session_dir(tmp_path, name="results/c001/bob/1")
    rc = lint.main(["--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "2 file(s), 0 error(s), 0 warning(s)" in out


def test_templates_directory_is_skipped(tmp_path, capsys):
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "annotations.md").write_text(
        "not even frontmatter\n", encoding="utf-8"
    )
    write_session_dir(tmp_path)
    rc = lint.main(["--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "1 file(s), 0 error(s), 0 warning(s)" in out
    assert "templates" not in out


def test_git_directory_is_skipped(tmp_path, capsys):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "annotations.md").write_text("garbage\n", encoding="utf-8")
    rc = lint.main(["--root", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "nothing to lint" in captured.err


def test_directory_argument_is_searched(tmp_path, capsys):
    write_session_dir(tmp_path, name="a/deep/place")
    rc = lint.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "1 file(s)" in out


def test_repeated_paths_are_linted_once(tmp_path, capsys):
    d = write_session_dir(tmp_path)
    rc = lint.main([str(d / "annotations.md"), str(d), str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "1 file(s)" in out


def test_missing_path_is_a_usage_error(tmp_path, capsys):
    rc = lint.main([str(tmp_path / "nowhere" / "annotations.md")])
    captured = capsys.readouterr()
    assert rc == 2
    assert "no such file or directory" in captured.err


def test_missing_root_is_a_usage_error(tmp_path, capsys):
    rc = lint.main(["--root", str(tmp_path / "nowhere")])
    captured = capsys.readouterr()
    assert rc == 2
    assert "--root" in captured.err


# --------------------------------------------------------------------------
# --session
# --------------------------------------------------------------------------


def test_session_requires_a_sibling_file(tmp_path, capsys):
    d = write_session_dir(tmp_path, session=None)
    rc = lint.main([str(d / "annotations.md"), "--session"])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert str(d / "session.yaml") in out
    assert "no session.yaml" in out


def test_without_session_the_missing_sibling_is_ignored(tmp_path, capsys):
    d = write_session_dir(tmp_path, session=None)
    rc = lint.main([str(d / "annotations.md")])
    out = capsys.readouterr().out
    assert rc == 0, out


def test_participant_mismatch_between_the_two_files(tmp_path, capsys):
    session = EXAMPLE_SESSION.replace("participant: example", "participant: someone")
    d = write_session_dir(tmp_path, session=session)
    rc = lint.main([str(d / "annotations.md"), "--session"])
    out = capsys.readouterr().out
    assert rc == 1, out
    mismatches = [ln for ln in errors_in(out) if "participant" in ln]
    assert mismatches, out
    assert "'example'" in mismatches[0] and "'someone'" in mismatches[0]
    # the message points at the frontmatter line, not at line 1
    assert f"{d / 'annotations.md'}:2:" in mismatches[0]


def test_attempt_mismatch_between_the_two_files(tmp_path, capsys):
    session = EXAMPLE_SESSION.replace("attempt: 1", "attempt: 3")
    d = write_session_dir(tmp_path, session=session)
    rc = lint.main([str(d / "annotations.md"), "--session"])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert any("attempt is 1" in ln for ln in errors_in(out)), out


def test_session_schema_problems_are_reported(tmp_path, capsys):
    session = EXAMPLE_SESSION.replace("duration_wall_minutes: 235", "")
    d = write_session_dir(tmp_path, session=session)
    rc = lint.main([str(d / "annotations.md"), "--session"])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "duration_wall_minutes" in out


def test_unparseable_session_yaml_is_an_error(tmp_path, capsys):
    d = write_session_dir(tmp_path, session="participant: [unclosed\n")
    rc = lint.main([str(d / "annotations.md"), "--session"])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert str(d / "session.yaml") in out


# --------------------------------------------------------------------------
# --expect-branch
# --------------------------------------------------------------------------


def test_expect_branch_agrees(tmp_path, capsys):
    d = write_session_dir(tmp_path)
    rc = lint.main(
        [str(d / "annotations.md"), "--session", "--expect-branch", "attempt/c001/example/1"]
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "0 error(s)" in out


def test_expect_branch_mismatch_is_an_error(tmp_path, capsys):
    d = write_session_dir(tmp_path)
    rc = lint.main(
        [str(d / "annotations.md"), "--session", "--expect-branch", "attempt/c002/bob/4"]
    )
    captured = capsys.readouterr()
    assert rc == 1, captured.out
    reported = errors_in(captured.out)
    assert any("participant" in ln and "'bob'" in ln for ln in reported), reported
    assert any("challenge" in ln and "'c002'" in ln for ln in reported), reported
    assert any("attempt" in ln and "4" in ln for ln in reported), reported
    # both files are checked against the branch
    assert any(str(d / "session.yaml") in ln for ln in reported), reported


def test_non_attempt_branch_is_skipped_with_a_notice(tmp_path, capsys):
    d = write_session_dir(tmp_path)
    rc = lint.main([str(d / "annotations.md"), "--session", "--expect-branch", "main"])
    captured = capsys.readouterr()
    assert rc == 0, captured.out
    assert "skipping the branch cross-check" in captured.err
    assert errors_in(captured.out) == []


def test_non_attempt_branch_notice_via_cli(tmp_path):
    d = write_session_dir(tmp_path)
    proc = run_cli(str(d / "annotations.md"), "--expect-branch", "retro/c001")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "skipping the branch cross-check" in proc.stderr


# --------------------------------------------------------------------------
# --repo
# --------------------------------------------------------------------------


def test_unresolvable_anchors_are_warnings_only(tmp_path, capsys, tmp_git_repo):
    d = write_session_dir(tmp_path)
    rc = lint.main([str(d / "annotations.md"), "--session", "--repo", str(tmp_git_repo)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert errors_in(out) == []
    reported = warnings_in(out)
    # the example carries six @hex anchors, none of which exist anywhere
    assert len(reported) == 6, out
    assert all("does not resolve to a commit" in ln for ln in reported)
    assert "0 error(s), 6 warning(s)" in out


def test_transcript_anchors_are_never_resolved(tmp_path, capsys, tmp_git_repo):
    text = "\n".join(
        [
            "---",
            "participant: example",
            "challenge: c001",
            "attempt: 1",
            'taxonomy_version: "0.2"',
            "session_date: 2026-09-12",
            "---",
            "",
            "+0:00  Recon  SCOUT  @t42",
            "",
        ]
    )
    d = write_session_dir(tmp_path, annotations=text)
    rc = lint.main([str(d / "annotations.md"), "--repo", str(tmp_git_repo)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert warnings_in(out) == []


def test_resolvable_anchor_produces_no_warning(tmp_path, capsys, tmp_git_repo):
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_git_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()[:8]
    text = "\n".join(
        [
            "---",
            "participant: example",
            "challenge: c001",
            "attempt: 1",
            'taxonomy_version: "0.2"',
            "session_date: 2026-09-12",
            "---",
            "",
            f"+0:00  Recon  SCOUT  @{sha}",
            "+0:04  Recon  GROUND  @0000000",
            "",
        ]
    )
    d = write_session_dir(tmp_path, annotations=text)
    rc = lint.main([str(d / "annotations.md"), "--repo", str(tmp_git_repo)])
    out = capsys.readouterr().out
    assert rc == 0, out
    reported = warnings_in(out)
    assert len(reported) == 1, out
    assert "@0000000" in reported[0]


def test_repo_that_is_not_a_repository_is_a_usage_error(tmp_path, capsys):
    d = write_session_dir(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    rc = lint.main([str(d / "annotations.md"), "--repo", str(plain)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "not a git repository" in captured.err


def test_repo_that_does_not_exist_is_a_usage_error(tmp_path, capsys):
    d = write_session_dir(tmp_path)
    rc = lint.main([str(d / "annotations.md"), "--repo", str(tmp_path / "nope")])
    captured = capsys.readouterr()
    assert rc == 2
    assert "not a directory" in captured.err


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def test_quiet_hides_the_summary_but_keeps_diagnostics(tmp_path, capsys):
    text = replace_line(
        EXAMPLE_ANNOTATIONS, "SCOUT", CORRUPTIONS[0].values[1]
    )
    d = write_session_dir(tmp_path, annotations=text)
    rc = lint.main([str(d / "annotations.md"), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "file(s)" not in captured.out
    assert errors_in(captured.out)


def test_quiet_hides_the_nothing_to_lint_notice(tmp_path, capsys):
    rc = lint.main(["--root", str(tmp_path), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert captured.err == ""


def test_summary_counts_files_errors_and_warnings(tmp_path, capsys):
    write_session_dir(tmp_path, name="good")
    bad = replace_line(EXAMPLE_ANNOTATIONS, "SCOUT", CORRUPTIONS[0].values[1])
    write_session_dir(tmp_path, annotations=bad, name="bad")
    bad_version = EXAMPLE_ANNOTATIONS.replace(
        'taxonomy_version: "0.2"', 'taxonomy_version: "0.1"'
    )
    write_session_dir(tmp_path, annotations=bad_version, name="old")
    rc = lint.main(["--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "3 file(s), 1 error(s), 1 warning(s)" in out


def test_taxonomy_version_mismatch_does_not_fail_the_run(tmp_path, capsys):
    text = EXAMPLE_ANNOTATIONS.replace(
        'taxonomy_version: "0.2"', 'taxonomy_version: "0.1"'
    )
    d = write_session_dir(tmp_path, annotations=text)
    rc = lint.main([str(d / "annotations.md"), "--session"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert warnings_in(out), out


def test_every_message_is_path_line_level_text(tmp_path, capsys):
    bad = replace_line(EXAMPLE_ANNOTATIONS, "SCOUT", CORRUPTIONS[0].values[1])
    d = write_session_dir(tmp_path, annotations=bad)
    lint.main([str(d / "annotations.md"), "--session"])
    out = capsys.readouterr().out
    for line in out.splitlines():
        if "file(s)" in line:
            continue
        head, _, _ = line.partition(": ")
        path, _, number = head.rpartition(":")
        assert path, line
        assert number.isdigit(), line


def test_missing_frontmatter_is_a_single_clear_error(tmp_path, capsys):
    d = write_session_dir(tmp_path, annotations="+0:00 Recon SCOUT\n")
    rc = lint.main([str(d / "annotations.md")])
    out = capsys.readouterr().out
    assert rc == 1
    assert "frontmatter" in out
    assert len(errors_in(out)) == 1


# --------------------------------------------------------------------------
# File encoding: a badly saved file must produce a sentence, not a traceback
# --------------------------------------------------------------------------


def test_non_utf8_annotations_file_is_a_clean_error(tmp_path, capsys):
    d = write_session_dir(tmp_path)
    (d / "annotations.md").write_bytes(b"\xff\xfe---\nparticipant: alice\n---\n")
    rc = lint.main([str(d / "annotations.md")])
    out = capsys.readouterr().out
    assert rc == 1
    assert len(errors_in(out)) == 1
    assert "UTF-8" in out


def test_non_utf8_annotations_file_does_not_traceback_via_cli(tmp_path):
    d = write_session_dir(tmp_path)
    (d / "annotations.md").write_bytes(b"\xff\xfe---\nparticipant: alice\n---\n")
    proc = run_cli(str(d / "annotations.md"))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr
    assert "UTF-8" in proc.stdout


def test_non_utf8_session_file_is_a_clean_error(tmp_path, capsys):
    d = write_session_dir(tmp_path)
    (d / "session.yaml").write_bytes(b"participant: \xff\xfe\n")
    rc = lint.main([str(d / "annotations.md"), "--session"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "UTF-8" in out


def test_byte_order_marked_files_still_lint_clean(tmp_path, capsys):
    d = write_session_dir(tmp_path)
    bom = b"\xef\xbb\xbf"
    (d / "annotations.md").write_bytes(bom + EXAMPLE_ANNOTATIONS.encode("utf-8"))
    (d / "session.yaml").write_bytes(bom + EXAMPLE_SESSION.encode("utf-8"))
    rc = lint.main([str(d / "annotations.md"), "--session"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "0 error(s), 0 warning(s)" in out


# --------------------------------------------------------------------------
# --expect-branch scoping: a whole-tree CI run must not judge other people's
# annotations (or the shipped example) by the pusher's branch name.
# --------------------------------------------------------------------------


def _attempt_tree(tmp_path: Path) -> Path:
    """A tree shaped like an attempt branch checkout: session/ + examples/ + results/."""
    write_session_dir(tmp_path, name="session")
    write_session_dir(tmp_path, name="examples/example-session")
    other = EXAMPLE_ANNOTATIONS.replace("participant: example", "participant: bob")
    other_session = EXAMPLE_SESSION.replace("participant: example", "participant: bob")
    write_session_dir(
        tmp_path,
        annotations=other,
        session=other_session,
        name="results/c001/bob/1",
    )
    return tmp_path


def test_expect_branch_ignores_the_example_and_collected_attempts(tmp_path, capsys):
    """The CI invocation from plan section 5 must not fail on unrelated files."""
    _attempt_tree(tmp_path)
    rc = lint.main(
        ["--root", str(tmp_path), "--session", "--expect-branch", "attempt/c001/example/1"]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.out + captured.err
    assert errors_in(captured.out) == []
    assert "3 file(s), 0 error(s), 0 warning(s)" in captured.out


def test_expect_branch_still_bites_on_the_attempts_own_session(tmp_path, capsys):
    _attempt_tree(tmp_path)
    rc = lint.main(
        ["--root", str(tmp_path), "--session", "--expect-branch", "attempt/c001/alice/1"]
    )
    captured = capsys.readouterr()
    assert rc == 1, captured.out
    reported = errors_in(captured.out)
    # exactly the session/ pair, never examples/ or results/
    assert len(reported) == 2, reported
    assert {ln.split(":")[0] for ln in reported} == {
        str(tmp_path / "session" / "annotations.md"),
        str(tmp_path / "session" / "session.yaml"),
    }, reported


def test_expect_branch_via_cli_on_a_whole_tree(tmp_path):
    _attempt_tree(tmp_path)
    proc = run_cli(
        "--root",
        str(tmp_path),
        "--session",
        "--expect-branch",
        "attempt/c001/example/1",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert errors_in(proc.stdout) == []


def test_notice_when_the_branch_check_matched_nothing(tmp_path, capsys):
    write_session_dir(tmp_path, name="examples/example-session")
    rc = lint.main(
        ["--root", str(tmp_path), "--expect-branch", "attempt/c001/alice/1"]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.out
    assert "nothing was cross-checked against the branch name" in captured.err


def test_an_explicitly_named_file_is_always_branch_checked(tmp_path, capsys):
    """Point the linter at a file and it does what you asked, wherever it lives."""
    d = write_session_dir(tmp_path, name="somewhere/else")
    rc = lint.main(
        [str(d / "annotations.md"), "--expect-branch", "attempt/c001/alice/1"]
    )
    out = capsys.readouterr().out
    assert rc == 1, out
    assert any("participant" in ln for ln in errors_in(out)), out


def test_reviewer_copies_are_discovered_and_share_the_parent_session(tmp_path):
    """Cross-annotations live in results/<cid>/<p>/<n>/reviews/<who>.annotations.md
    and share the attempt's session.yaml one directory up."""
    attempt = tmp_path / "results" / "c001" / "example" / "1"
    (attempt / "reviews").mkdir(parents=True)
    (attempt / "annotations.md").write_text(EXAMPLE_ANNOTATIONS, encoding="utf-8")
    (attempt / "session.yaml").write_text(EXAMPLE_SESSION, encoding="utf-8")
    (attempt / "reviews" / "bob.annotations.md").write_text(EXAMPLE_ANNOTATIONS, encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--session", "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "2 file(s)" in proc.stdout + proc.stderr
