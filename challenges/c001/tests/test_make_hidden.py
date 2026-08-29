"""Tests for ``challenges/c001/tools/make_hidden.sh``.

Every test builds a throwaway git repository under ``tmp_path`` that mimics the
challenge directory layout (``<repo>/tools/make_hidden.sh``), so the script's
default paths (``<challenge_dir>/hidden-seeds.txt`` and
``<challenge_dir>/instances/hidden``) land inside the sandbox and the real
repository is never touched.

The generator itself is replaced by a stub via ``GENERATE_CMD``: these tests are
about the seed plumbing and the refusal rules, not about geometry, so they need
neither Shapely nor ``tools/generate.py``.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

C001_DIR = Path(__file__).resolve().parent.parent
SCRIPT = C001_DIR / "tools" / "make_hidden.sh"

STUB = """#!/bin/sh
# Stand-in for tools/generate.py: logs its argv and writes an empty JSON file.
printf '%s\\n' "$*" >> "$STUB_LOG"
out=""
while [ $# -gt 0 ]; do
    if [ "$1" = "--out" ]; then
        out="$2"
        shift 2
    else
        shift
    fi
done
[ -n "$out" ] || exit 9
mkdir -p "$(dirname "$out")"
printf '{}\\n' > "$out"
"""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _commit(repo: Path, message: str) -> None:
    _git(
        repo,
        "-c",
        "user.name=etudes-test",
        "-c",
        "user.email=etudes-test@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        message,
    )


class Sandbox:
    """A throwaway challenge directory with the script installed in tools/."""

    def __init__(self, root: Path, git: bool = True):
        self.root = root
        self.log = root / "generate.log"
        (root / "tools").mkdir(parents=True, exist_ok=True)
        self.script = root / "tools" / "make_hidden.sh"
        shutil.copy2(SCRIPT, self.script)
        self.script.chmod(self.script.stat().st_mode | stat.S_IXUSR)
        self.stub = root / "fake-generate.sh"
        self.stub.write_text(STUB, encoding="utf-8")
        self.stub.chmod(0o755)
        if git:
            _git(root, "init", "-q")

    @property
    def hidden_dir(self) -> Path:
        return self.root / "instances" / "hidden"

    def seeds(self, text: str, name: str = "hidden-seeds.txt") -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def gitignore(self, text: str = "*hidden-seeds*\n") -> Path:
        path = self.root / ".gitignore"
        path.write_text(text, encoding="utf-8")
        return path

    def run(self, *args: str, env=None, cwd=None, stub: bool = True):
        environ = dict(os.environ)
        environ.pop("HIDDEN_SEEDS", None)
        environ.pop("GENERATE_CMD", None)
        environ["STUB_LOG"] = str(self.log)
        if stub:
            environ["GENERATE_CMD"] = str(self.stub)
        if env:
            environ.update(env)
        return subprocess.run(
            ["bash", str(self.script), *args],
            capture_output=True,
            text=True,
            cwd=str(cwd or self.root),
            env=environ,
        )

    def generated(self) -> list[str]:
        if not self.hidden_dir.is_dir():
            return []
        return sorted(p.name for p in self.hidden_dir.glob("*.json"))

    def log_lines(self) -> list[str]:
        if not self.log.is_file():
            return []
        return [ln for ln in self.log.read_text(encoding="utf-8").splitlines() if ln]


@pytest.fixture
def sandbox(tmp_path):
    return Sandbox(tmp_path / "challenge")


def test_script_exists_and_is_bash():
    assert SCRIPT.is_file()
    assert SCRIPT.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")


def test_refuses_a_tracked_seeds_file(sandbox):
    seeds = sandbox.seeds("1 1001\n")
    _git(sandbox.root, "add", "--", seeds.name)
    _commit(sandbox.root, "add seeds")

    result = sandbox.run("--seeds-file", str(seeds))

    assert result.returncode == 3
    assert "tracked" in result.stderr
    assert sandbox.generated() == []


def test_refuses_a_staged_seeds_file(sandbox):
    seeds = sandbox.seeds("1 1001\n")
    _git(sandbox.root, "add", "--", seeds.name)

    result = sandbox.run("--seeds-file", str(seeds))

    assert result.returncode == 3
    assert "tracked" in result.stderr or "staged" in result.stderr
    assert sandbox.generated() == []


def test_refuses_an_untracked_but_unignored_seeds_file(sandbox):
    seeds = sandbox.seeds("1 1001\n")

    result = sandbox.run("--seeds-file", str(seeds))

    assert result.returncode == 3
    assert ".gitignore" in result.stderr
    assert sandbox.generated() == []


def test_refuses_a_seeds_file_outside_any_repository(tmp_path):
    box = Sandbox(tmp_path / "loose", git=False)
    seeds = box.seeds("1 1001\n")

    result = box.run("--seeds-file", str(seeds))

    assert result.returncode == 3
    assert "git repository" in result.stderr
    assert box.generated() == []


def test_generates_instances_from_an_ignored_seeds_file(sandbox):
    sandbox.gitignore()
    seeds = sandbox.seeds(
        "# etude no. 1, hidden set\n"
        "\n"
        "1 1731\n"
        "1 9042\n"
        "2:5510\n"
        "3 8123  # tier three\n",
        name="secret.hidden-seeds.txt",
    )

    result = sandbox.run("--seeds-file", str(seeds))

    assert result.returncode == 0, result.stderr
    assert sandbox.generated() == [
        "c001-t1-hidden-01.json",
        "c001-t1-hidden-02.json",
        "c001-t2-hidden-01.json",
        "c001-t3-hidden-01.json",
    ]
    # every generated path is echoed on stdout
    for name in sandbox.generated():
        assert name in result.stdout
    calls = sandbox.log_lines()
    assert len(calls) == 4
    assert "--tier 1 --seed 1731 --id c001-t1-hidden-01" in calls[0]
    assert "--tier 1 --seed 9042 --id c001-t1-hidden-02" in calls[1]
    assert "--tier 2 --seed 5510 --id c001-t2-hidden-01" in calls[2]
    assert "--tier 3 --seed 8123 --id c001-t3-hidden-01" in calls[3]


def test_uses_the_default_seeds_file_and_runs_from_any_cwd(sandbox, tmp_path):
    sandbox.gitignore()
    sandbox.seeds("2 4242\n")

    result = sandbox.run(cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert sandbox.generated() == ["c001-t2-hidden-01.json"]


def test_out_directory_can_be_redirected(sandbox, tmp_path):
    sandbox.gitignore()
    seeds = sandbox.seeds("3 7001\n")
    out = tmp_path / "elsewhere" / "hidden"

    result = sandbox.run("--seeds-file", str(seeds), "--out", str(out))

    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in out.glob("*.json")) == ["c001-t3-hidden-01.json"]
    assert sandbox.generated() == []


def test_hidden_seeds_env_var_form(sandbox):
    result = sandbox.run(env={"HIDDEN_SEEDS": "1:1731,2:5510,1:9042"})

    assert result.returncode == 0, result.stderr
    assert sandbox.generated() == [
        "c001-t1-hidden-01.json",
        "c001-t1-hidden-02.json",
        "c001-t2-hidden-01.json",
    ]
    calls = sandbox.log_lines()
    assert "--tier 1 --seed 1731 --id c001-t1-hidden-01" in calls[0]
    assert "--tier 2 --seed 5510 --id c001-t2-hidden-01" in calls[1]
    assert "--tier 1 --seed 9042 --id c001-t1-hidden-02" in calls[2]


def test_hidden_seeds_env_var_needs_no_repository(tmp_path):
    box = Sandbox(tmp_path / "loose", git=False)

    result = box.run(env={"HIDDEN_SEEDS": "1:1731"})

    assert result.returncode == 0, result.stderr
    assert box.generated() == ["c001-t1-hidden-01.json"]


def test_an_explicit_seeds_file_wins_over_the_env_var(sandbox):
    sandbox.gitignore()
    seeds = sandbox.seeds("3 8123\n")

    result = sandbox.run(
        "--seeds-file", str(seeds), env={"HIDDEN_SEEDS": "1:1731,1:9042"}
    )

    assert result.returncode == 0, result.stderr
    assert sandbox.generated() == ["c001-t3-hidden-01.json"]


def test_no_seeds_at_all_prints_usage(sandbox):
    result = sandbox.run()

    assert result.returncode != 0
    assert "Usage:" in result.stderr
    assert "HIDDEN_SEEDS" in result.stderr
    assert sandbox.generated() == []


@pytest.mark.parametrize(
    "text, needle",
    [
        ("4 1001\n", "tier"),
        ("1 abc\n", "seed"),
        ("1\n", "seed"),
        ("1 1001 extra\n", "malformed"),
        ("1 1001\n1 1001\n", "duplicate"),
    ],
)
def test_malformed_seed_entries_are_refused(sandbox, text, needle):
    sandbox.gitignore()
    seeds = sandbox.seeds(text)

    result = sandbox.run("--seeds-file", str(seeds))

    assert result.returncode == 2
    assert needle in result.stderr


def test_empty_seeds_file_is_refused(sandbox):
    sandbox.gitignore()
    seeds = sandbox.seeds("# nothing here yet\n\n")

    result = sandbox.run("--seeds-file", str(seeds))

    assert result.returncode == 2
    assert sandbox.generated() == []


def test_missing_seeds_file_is_a_usage_error(sandbox):
    result = sandbox.run("--seeds-file", str(sandbox.root / "nope.txt"))

    assert result.returncode == 2
    assert "not found" in result.stderr


def test_unknown_option_is_a_usage_error(sandbox):
    result = sandbox.run("--nope")

    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_generator_failure_is_reported(sandbox):
    sandbox.gitignore()
    seeds = sandbox.seeds("1 1001\n")

    result = sandbox.run("--seeds-file", str(seeds), env={"GENERATE_CMD": "false"})

    assert result.returncode == 1
    assert "generator failed" in result.stderr
    assert "c001-t1-hidden-01" in result.stderr


def test_help_documents_the_post_round_protocol():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        cwd=str(C001_DIR),
    )

    assert result.returncode == 0
    out = result.stdout
    assert "Usage:" in out
    assert "Post-round protocol" in out
    assert "solutions/hidden/" in out
    assert "status: closed" in out
    assert "instances/hidden/" in out
    # the organizer publishes the seeds under a name .gitignore does not eat
    assert "published-seeds.txt" in out
    assert "*hidden-seeds*" in out
    assert "HIDDEN_SEEDS" in out
    assert "--seeds-file" in out
