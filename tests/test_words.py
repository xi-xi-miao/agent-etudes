"""Tests for ``scripts/check_words.sh``.

The repository reports utilizations, distributions and timelines, never
standings, and the shell check is what keeps it that way. The forbidden words
are assembled at run time here so that this test file (and its compiled cache)
never contains one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_words.sh"

#: Assembled from fragments, never written out as a literal.
BAD_WORDS = [
    "".join(parts)
    for parts in (
        ("lea", "der", "board"),
        ("sc", "ores"),
        ("ra", "nkings"),
        ("wi", "nner"),
    )
]


def run(*args, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *[str(a) for a in args]],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
    )


def test_repository_is_clean(tmp_path: Path):
    """Run with no argument, from an unrelated cwd: the script finds its repo."""
    proc = run(cwd=tmp_path)

    assert proc.returncode == 0, (
        "check_words.sh reported forbidden vocabulary in the repository:\n"
        + proc.stdout
        + proc.stderr
    )
    assert "check-words: clean" in proc.stdout


def test_readme_sentence_is_allowed(tmp_path: Path):
    (tmp_path / "README.md").write_text(
        f"It is not a competition: there is no {BAD_WORDS[0]} here.\n",
        encoding="utf-8",
    )

    proc = run(tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "allowed hits" in proc.stdout


@pytest.mark.parametrize("index", range(len(BAD_WORDS)))
def test_each_forbidden_word_outside_the_readme_fails(tmp_path: Path, index: int):
    doc = tmp_path / "docs" / "notes.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(f"a {BAD_WORDS[index]} table\n", encoding="utf-8")

    proc = run(tmp_path)

    assert proc.returncode == 1
    assert "docs/notes.md" in proc.stderr


def test_word_boundaries_are_respected(tmp_path: Path):
    """``underscore`` and ``frankly`` contain no forbidden word."""
    text = "under" + BAD_WORDS[1] + " are fine, and so is " + "fran" + "kly\n"
    (tmp_path / "notes.md").write_text(text, encoding="utf-8")

    proc = run(tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_handoffs_are_excluded(tmp_path: Path):
    doc = tmp_path / "docs" / "handoffs" / "HANDOFF.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(f"the original brief mentions a {BAD_WORDS[0]}\n", encoding="utf-8")

    proc = run(tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_missing_root_is_a_usage_error(tmp_path: Path):
    proc = run(tmp_path / "nowhere")

    assert proc.returncode == 2
    assert "no such directory" in proc.stderr
