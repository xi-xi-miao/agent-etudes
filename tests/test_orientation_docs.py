"""The orientation documents must keep pointing at things that exist.

``AGENTS.md`` is a map: it owns no rule, it cites the file that owns each one.
A citation that no longer resolves is worse than no citation, and nothing else
in the suite reads it. ``README.md``'s repository map has the same job for a
human arriving at the root, and ``retros/README.md`` explains a directory that
stays empty until the first round closes -- the one place where "run this
command" is the whole explanation.

Path checking is deliberately mechanical: every inline ``code span`` in
``AGENTS.md`` that looks like a repository path must resolve from the
repository root. Spans carrying a placeholder (``<cid>`` and friends), a glob,
or a space are skipped, because they name a family of files rather than one.
Fenced blocks are stripped first: they hold command lines, not citations.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

AGENTS = REPO_ROOT / "AGENTS.md"
README = REPO_ROOT / "README.md"
RETROS_README = REPO_ROOT / "retros" / "README.md"

#: An inline code span: backtick, at least one non-backtick character, backtick.
CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")

#: A fenced block, opened and closed by a line of three backticks.
FENCE_RE = re.compile(r"^[ \t]*```")

#: Suffixes that make a token a path even without a directory separator.
PATH_SUFFIXES = (".md", ".toml", ".yml", ".yaml", ".sh", ".py", ".lock", ".gitignore")

#: AGENTS.md is a map, not a manual; past this it stops being readable in one go.
MAX_AGENTS_LINES = 130


def strip_fenced_blocks(text: str) -> list[str]:
    """The lines of ``text`` that are outside every fenced code block."""
    outside: list[str] = []
    inside = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            inside = not inside
            continue
        if not inside:
            outside.append(line)
    return outside


def looks_like_a_repository_path(token: str) -> bool:
    if any(ch in token for ch in "<*") or " " in token:
        return False
    if token.startswith("/"):
        return False
    return "/" in token or token.endswith(PATH_SUFFIXES)


def test_agents_md_cites_paths_that_exist():
    text = AGENTS.read_text(encoding="utf-8")

    line_count = len(text.splitlines())
    assert line_count <= MAX_AGENTS_LINES, (
        f"AGENTS.md is {line_count} lines; it is a map an agent reads in one go and the "
        f"cap is {MAX_AGENTS_LINES}. Move detail into the file that owns the rule."
    )

    missing = []
    for line in strip_fenced_blocks(text):
        for token in CODE_SPAN_RE.findall(line):
            if looks_like_a_repository_path(token) and not (REPO_ROOT / token).exists():
                missing.append(token)

    assert not missing, (
        "AGENTS.md cites paths that do not exist: "
        + ", ".join(sorted(set(missing)))
        + ". Fix the citation, or write the path with a placeholder when it only "
        "exists on an attempt branch."
    )


def test_readme_map_names_every_top_level_entry():
    lines = README.read_text(encoding="utf-8").splitlines()

    heading = next(
        (i for i, line in enumerate(lines) if line.strip() == "## Repository map"),
        None,
    )
    assert heading is not None, "README.md has no '## Repository map' heading"

    opening = next(
        (i for i in range(heading + 1, len(lines)) if FENCE_RE.match(lines[i])),
        None,
    )
    assert opening is not None, "the repository map heading is not followed by a code block"
    closing = next(
        (i for i in range(opening + 1, len(lines)) if FENCE_RE.match(lines[i])),
        None,
    )
    assert closing is not None, "the repository map code block is never closed"

    block = "\n".join(lines[opening + 1 : closing])
    for entry in ("AGENTS.md", "CONTRIBUTING.md", "Makefile", "pyproject.toml", ".github/"):
        assert entry in block, (
            f"the repository map does not name {entry}; a newcomer reading only this "
            "block would not know it is there"
        )


def test_retros_readme_explains_make_retro():
    text = RETROS_README.read_text(encoding="utf-8")
    for needle in ("make retro", "scripts/retro.py"):
        assert needle in text, (
            f"retros/README.md does not mention {needle}; the directory is empty until a "
            "round closes, so the command that fills it is the explanation"
        )
