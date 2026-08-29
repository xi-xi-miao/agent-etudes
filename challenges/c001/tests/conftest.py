"""Shared pytest fixtures for the c001 tool tests.

Importing this module puts ``challenges/c001/tools`` on ``sys.path`` so the test
modules can ``import geom`` (and the other tools) directly -- the tools are
scripts, not an installed package.

Shapely is deliberately NOT guarded here: a module-level ``importorskip`` in a
conftest would skip nothing and just break collection.  Each test module that
needs Shapely puts ``pytest.importorskip("shapely")`` at its own top, above the
first ``import geom``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

C001_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = C001_DIR / "tools"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


@pytest.fixture(scope="session")
def c001_dir():
    """Absolute path of ``challenges/c001``."""
    return C001_DIR


@pytest.fixture(scope="session")
def tools_dir():
    """Absolute path of ``challenges/c001/tools``."""
    return TOOLS_DIR


@pytest.fixture(scope="session")
def dev_instances():
    """Sorted list of committed dev instance paths (empty if none exist yet)."""
    dev = C001_DIR / "instances" / "dev"
    return sorted(dev.glob("*.json")) if dev.is_dir() else []


@pytest.fixture
def run_tool():
    """Run ``python tools/<name>.py <args>`` with cwd = the challenge directory.

    Returns the :class:`subprocess.CompletedProcess` (text mode, output
    captured); the caller asserts on ``returncode``/``stdout``/``stderr``.
    """

    def _run(name, *args):
        script = name if name.endswith(".py") else name + ".py"
        cmd = [sys.executable, str(Path("tools") / script)] + [str(a) for a in args]
        return subprocess.run(
            cmd,
            cwd=str(C001_DIR),
            capture_output=True,
            text=True,
        )

    return _run


@pytest.fixture
def tiny_instance():
    """Factory for a small in-memory instance: W=100, a 40x40 square, a right
    triangle and a 20x20 square.  Keyword arguments override top-level fields.
    """

    def _make(**overrides):
        instance = {
            "instance_id": "c001-t1-dev-99",
            "challenge": "c001",
            "tier": 1,
            "seed": 99,
            "strip_width": 100.0,
            "rotations_allowed": "free",
            "parts": [
                {
                    "id": "p001",
                    "exterior": [[0.0, 0.0], [40.0, 0.0], [40.0, 40.0], [0.0, 40.0]],
                    "holes": [],
                },
                {
                    "id": "p002",
                    "exterior": [[0.0, 0.0], [30.0, 0.0], [0.0, 30.0]],
                    "holes": [],
                },
                {
                    "id": "p003",
                    "exterior": [[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]],
                    "holes": [],
                },
            ],
        }
        instance.update(overrides)
        return instance

    return _make
