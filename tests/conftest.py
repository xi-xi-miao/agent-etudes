"""Shared pytest configuration for the challenge-agnostic test suite.

Two jobs:

1. put ``scripts/`` on ``sys.path`` so ``import etudes_lib`` works;
2. offer :func:`load_tool`, which imports a script *by file path* under a
   unique module name. Challenge directories each have their own
   ``tools/validate.py``, ``tools/render.py`` and so on, so importing by name
   would collide; ``importlib.util.spec_from_file_location`` sidesteps that.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def load_tool(path, name: str):
    """Import the Python file at ``path`` as a module called ``name``.

    ``name`` must be unique within a test session; prefix it with the owning
    directory (``fake_validate``, ``c001_validate``) rather than reusing the
    bare file stem.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no such script: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"could not build an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path of the repository checkout the tests belong to."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def fake_challenge_dir() -> Path:
    """``tests/fixtures/fake-challenge`` -- a complete, dependency-free challenge."""
    return REPO_ROOT / "tests" / "fixtures" / "fake-challenge"


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """A fresh git repository in ``tmp_path`` with one commit on ``main``.

    Identity and signing are configured locally so the suite never blocks on a
    developer's global git settings.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True
        )

    run("init", "-b", "main")
    run("config", "user.name", "Etudes Test")
    run("config", "user.email", "etudes-test@example.invalid")
    run("config", "commit.gpgsign", "false")
    run("config", "tag.gpgsign", "false")
    (repo / "README.md").write_text("fixture repository\n", encoding="utf-8")
    run("add", "README.md")
    run("commit", "-m", "initial commit")
    return repo
