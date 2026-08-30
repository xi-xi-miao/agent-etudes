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


def test_no_subdirectory_of_docs_is_exempt(tmp_path: Path):
    """Nothing under ``docs/`` is exempt -- every document is held to the rule.

    An earlier revision excluded ``docs/handoffs/`` by directory name, so that
    a set of external briefs could be kept verbatim. That exclusion is gone,
    and the fixture below reuses the exact name it keyed on: reinstating the
    carve-out -- for that name or any other under ``docs/`` -- fails here.
    """
    doc = tmp_path / "docs" / "handoffs" / "BRIEF.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(f"this brief mentions a {BAD_WORDS[0]}\n", encoding="utf-8")

    proc = run(tmp_path)

    assert proc.returncode == 1
    assert "docs/handoffs/BRIEF.md" in proc.stderr


def test_missing_root_is_a_usage_error(tmp_path: Path):
    proc = run(tmp_path / "nowhere")

    assert proc.returncode == 2
    assert "no such directory" in proc.stderr


def _nested_checkout(root: Path, name: str, *, git_entry: str) -> Path:
    """A second checkout inside ``root``: a clone (.git dir) or a worktree (.git file)."""
    nested = root / name
    nested.mkdir(parents=True)
    if git_entry == "dir":
        (nested / ".git").mkdir()
    else:
        (nested / ".git").write_text(
            "gitdir: /elsewhere/.git/worktrees/x\n", encoding="utf-8"
        )
    return nested


@pytest.mark.parametrize("git_entry", ["dir", "file"], ids=["clone", "worktree"])
def test_a_nested_checkouts_readme_copy_is_not_a_violation(tmp_path: Path, git_entry):
    """The allowed sentence, copied verbatim into a second checkout, is not a hit.

    The allowlist is anchored to the top-level README.md, so before this the
    identical sentence one directory down failed the check that permits it.
    """
    sentence = f"It is not a competition: there is no {BAD_WORDS[0]} here.\n"
    (tmp_path / "README.md").write_text(sentence, encoding="utf-8")
    nested = _nested_checkout(tmp_path, "worktrees/playtest", git_entry=git_entry)
    (nested / "README.md").write_text(sentence, encoding="utf-8")

    proc = run(tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "clean (only the README.md sentence)" in proc.stdout
    assert "playtest" not in proc.stdout + proc.stderr
    assert "exactly ONE sentence" not in proc.stderr


def test_a_nested_checkouts_own_vocabulary_is_not_this_trees_problem(tmp_path: Path):
    doc = _nested_checkout(tmp_path, "vendor/other-clone", git_entry="dir") / "notes.md"
    doc.write_text(f"a {BAD_WORDS[1]} table\n", encoding="utf-8")

    proc = run(tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_claude_directory_is_excluded(tmp_path: Path):
    """.claude/ holds agent scratch, including worktrees of this repository."""
    doc = tmp_path / ".claude" / "worktrees" / "playtest" / "docs" / "notes.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(f"a {BAD_WORDS[2]} table\n", encoding="utf-8")

    proc = run(tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_a_real_violation_still_fails_when_a_nested_checkout_exists(tmp_path: Path):
    """Pruning the neighbours must not prune the tree the check is about."""
    _nested_checkout(tmp_path, "worktrees/playtest", git_entry="file")
    doc = tmp_path / "docs" / "notes.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(f"a {BAD_WORDS[3]} table\n", encoding="utf-8")

    proc = run(tmp_path)

    assert proc.returncode == 1
    assert "docs/notes.md" in proc.stderr


def test_the_advice_names_only_measures_this_repository_reports(tmp_path: Path):
    """The suggestion list must not recommend the ordering word the docs disclaim."""
    doc = tmp_path / "docs" / "notes.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(f"a {BAD_WORDS[0]} table\n", encoding="utf-8")

    proc = run(tmp_path)

    assert proc.returncode == 1
    assert "Use utilization / measure / distribution / count instead." in proc.stderr
    assert "stan" + "dings" not in proc.stderr
