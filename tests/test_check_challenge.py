"""Tests for ``scripts/check_challenge.py``.

The fixture challenge is copied into a ``c999/`` directory (the contract wants
the directory named after the manifest id) and then broken one way at a time,
so every test pins one specific FAIL message.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_challenge.py"
IGNORE = shutil.ignore_patterns("__pycache__")


def run(challenge_dir: Path, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(challenge_dir)],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def challenge(tmp_path: Path, fake_challenge_dir: Path) -> Path:
    """A private, complete copy of the fixture challenge named ``c999``."""
    target = tmp_path / "c999"
    shutil.copytree(fake_challenge_dir, target, ignore=IGNORE)
    return target


def read_manifest(challenge: Path) -> str:
    return (challenge / "challenge.yaml").read_text(encoding="utf-8")


def write_manifest(challenge: Path, text: str) -> None:
    (challenge / "challenge.yaml").write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------


def test_intact_challenge_passes(challenge: Path):
    proc = run(challenge)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "FAIL:" not in proc.stdout
    assert "contract check passed" in proc.stdout
    # the checks that matter are actually reported, not silently skipped
    assert "challenge.yaml is valid" in proc.stdout
    assert "tools/validate.py" in proc.stdout
    assert "README.md exists" in proc.stdout
    assert "valid/summary/errors" in proc.stdout


def test_a_relative_challenge_directory_works(tmp_path: Path, challenge: Path):
    """``make check-challenge`` and CI both pass a path relative to the cwd.

    The baseline round trip runs with the challenge directory as its cwd, so a
    relative directory must not end up resolved twice.
    """
    proc = run(Path(challenge.name), cwd=tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "FAIL:" not in proc.stdout
    assert "baseline.py produced a solution" in proc.stdout


def test_missing_directory_is_a_usage_error(tmp_path: Path):
    proc = run(tmp_path / "nowhere")

    assert proc.returncode == 2
    assert "no such directory" in proc.stderr


# --------------------------------------------------------------------------
# One break at a time
# --------------------------------------------------------------------------


def test_instance_file_name_must_match_instance_id(challenge: Path):
    instance = challenge / "instances" / "dev" / "c999-dev-01.json"
    instance.rename(instance.with_name("c999-dev-02.json"))

    proc = run(challenge)

    assert proc.returncode == 1
    assert "instance_id" in proc.stdout
    assert "c999-dev-02" in proc.stdout


def test_unknown_manifest_key_fails(challenge: Path):
    write_manifest(challenge, read_manifest(challenge) + "extra_key: nope\n")

    proc = run(challenge)

    assert proc.returncode == 1
    assert "unknown key" in proc.stdout
    assert "extra_key" in proc.stdout
    # a manifest that will not load stops the run rather than cascading
    assert "PASS:" not in proc.stdout


def test_forbidden_vocabulary_in_the_readme_fails(challenge: Path):
    # assembled at run time so this test file never contains the word itself
    word = "".join(("lea", "der", "board"))
    readme = challenge / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + f"\nThe {word} lives here.\n",
        encoding="utf-8",
    )

    proc = run(challenge)

    assert proc.returncode == 1
    assert "competitive vocabulary" in proc.stdout
    assert "README.md" in proc.stdout


def test_directory_named_after_another_id_fails(
    tmp_path: Path, fake_challenge_dir: Path
):
    target = tmp_path / "c998"
    shutil.copytree(fake_challenge_dir, target, ignore=IGNORE)

    proc = run(target)

    assert proc.returncode == 1
    assert "does not match the directory name 'c998'" in proc.stdout


def test_directory_not_named_after_its_id_fails(
    tmp_path: Path, fake_challenge_dir: Path
):
    """The library is lenient for fixture directories; this script is not."""
    target = tmp_path / "fake-challenge"
    shutil.copytree(fake_challenge_dir, target, ignore=IGNORE)

    proc = run(target)

    assert proc.returncode == 1
    assert "directory is named 'fake-challenge'" in proc.stdout
    assert "the manifest id is 'c999'" in proc.stdout


def test_missing_readme_fails(challenge: Path):
    (challenge / "README.md").unlink()

    proc = run(challenge)

    assert proc.returncode == 1
    assert "README.md" in proc.stdout
    assert "is missing" in proc.stdout


def test_missing_validator_fails(challenge: Path):
    (challenge / "tools" / "validate.py").unlink()

    proc = run(challenge)

    assert proc.returncode == 1
    assert "the validate command refers to tools/validate.py" in proc.stdout


def test_open_status_without_dev_instances_fails(challenge: Path):
    (challenge / "instances" / "dev" / "c999-dev-01.json").unlink()
    write_manifest(challenge, read_manifest(challenge).replace("status: draft", "status: open"))

    proc = run(challenge)

    assert proc.returncode == 1
    assert "no instance JSON" in proc.stdout


def test_draft_without_instances_does_not_fail_on_the_baseline(challenge: Path):
    """A draft may have tools before it has instances; the two checks agree."""
    (challenge / "instances" / "dev" / "c999-dev-01.json").unlink()

    proc = run(challenge)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "FAIL:" not in proc.stdout
    assert "status is draft" in proc.stdout


def test_closed_status_needs_hidden_instances(challenge: Path):
    write_manifest(
        challenge, read_manifest(challenge).replace("status: draft", "status: closed")
    )

    proc = run(challenge)

    assert proc.returncode == 1
    assert "instances/hidden" in proc.stdout


def test_declared_dependency_group_must_exist(challenge: Path, tmp_path: Path):
    write_manifest(challenge, read_manifest(challenge) + "dependency_group: c999\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.1.0"\n\n'
        "[dependency-groups]\ndev = []\n",
        encoding="utf-8",
    )

    proc = run(challenge)

    assert proc.returncode == 1
    assert "dependency-groups" in proc.stdout
    assert "c999" in proc.stdout


# --------------------------------------------------------------------------
# The git-dependent check
# --------------------------------------------------------------------------


def test_open_status_requires_the_start_tag(tmp_git_repo: Path, fake_challenge_dir: Path):
    challenge = tmp_git_repo / "challenges" / "c999"
    shutil.copytree(fake_challenge_dir, challenge, ignore=IGNORE)
    manifest = challenge / "challenge.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("status: draft", "status: open"),
        encoding="utf-8",
    )

    proc = run(challenge)
    assert proc.returncode == 1
    assert "c999-start" in proc.stdout

    subprocess.run(
        ["git", "tag", "-a", "c999-start", "-m", "c999 start"],
        cwd=tmp_git_repo,
        check=True,
        capture_output=True,
        text=True,
    )

    proc = run(challenge)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "start_tag c999-start exists" in proc.stdout


def test_shebang_style_validate_template_is_checked_too(challenge: Path):
    """argv[0] is a path when the template does not start with an interpreter."""
    write_manifest(
        challenge,
        read_manifest(challenge).replace(
            'validate: "python tools/validate.py', 'validate: "tools/validate.py'
        ),
    )
    (challenge / "tools" / "validate.py").unlink()

    proc = run(challenge)

    assert proc.returncode == 1
    assert "the validate command refers to tools/validate.py" in proc.stdout
