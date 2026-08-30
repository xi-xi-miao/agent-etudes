"""The shipped example session must exercise the whole notation.

``examples/example-session/`` is what a participant reads before writing their
first ``annotations.md``, and what every downstream tool (stats, retro,
collect) is developed against. If it stops demonstrating a part of the
vocabulary, that part quietly loses its only worked example -- and its only
integration test.

So the example must demonstrate all four layers of TAXONOMY.md (phases, moves,
glyphs, motifs), a wildcard move, a stance marker, both anchor kinds, at least
one motif -- and the whole thing has to lint clean with ``--session``. That is
what this module holds it to.

It also guards the other pair of shipped artifacts a participant copies,
``templates/annotations.md`` and ``templates/session.yaml``. Discovery skips
``templates/`` on purpose, so no whole-tree lint run ever reaches them; without
these tests a broken template stays green until somebody's first attempt.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import etudes_lib as lib
from conftest import load_tool

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = REPO_ROOT / "examples" / "example-session"
ANNOTATIONS = EXAMPLE_DIR / "annotations.md"
SESSION = EXAMPLE_DIR / "session.yaml"

TEMPLATES_DIR = REPO_ROOT / "templates"
TEMPLATE_ANNOTATIONS = TEMPLATES_DIR / "annotations.md"
TEMPLATE_SESSION = TEMPLATES_DIR / "session.yaml"

lint = load_tool(REPO_ROOT / "scripts" / "lint_annotations.py", "lint_cli_for_example")

HEX_ANCHOR_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
TRANSCRIPT_ANCHOR_RE = re.compile(r"^t[0-9]+$")


@pytest.fixture(scope="module")
def parsed():
    """``(meta, moves, messages)`` for the example annotations."""
    return lib.parse_annotations_file(ANNOTATIONS)


@pytest.fixture(scope="module")
def moves(parsed):
    return parsed[1]


# --------------------------------------------------------------------------
# It parses, and it lints
# --------------------------------------------------------------------------


def test_example_parses_without_messages(parsed):
    _, moves, messages = parsed
    assert messages == [], "\n".join(str(m) for m in messages)
    assert moves, "the example must contain annotation lines"


def test_example_lints_clean_with_session(capsys):
    rc = lint.main([str(ANNOTATIONS), "--session"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "0 error(s), 0 warning(s)" in out


def test_session_yaml_is_valid():
    data = lib.load_yaml(SESSION)
    messages = lib.validate_session_yaml(data, SESSION)
    assert messages == [], "\n".join(str(m) for m in messages)


def test_the_four_artifacts_are_all_present():
    for relative in (
        "session.yaml",
        "annotations.md",
        "postmortem.md",
        "decisions/dr-001.md",
    ):
        assert (EXAMPLE_DIR / relative).is_file(), f"missing {relative}"


# --------------------------------------------------------------------------
# Layer 1: phases (all five) and both stance markers
# --------------------------------------------------------------------------


def test_all_five_phases_are_demonstrated(moves):
    used = {m.phase for m in moves}
    assert used == set(lib.PHASES), f"missing phases: {sorted(set(lib.PHASES) - used)}"


def test_a_stance_suffix_is_demonstrated(moves):
    stances = {m.stance for m in moves if m.stance is not None}
    assert stances, "no line carries a > or ~ stance suffix"
    assert stances == {">", "~"}, f"only {sorted(stances)} demonstrated"


# --------------------------------------------------------------------------
# Layer 2: moves, including the wildcard and NOTE
# --------------------------------------------------------------------------


def test_named_moves_from_several_families_are_used(moves):
    families = {
        lib.move_family(m.move)
        for m in moves
        if lib.is_named_move(m.move)
    }
    assert len(families) >= 3, f"only these families appear: {sorted(families)}"


def test_a_wildcard_move_is_demonstrated(moves):
    wildcards = [m for m in moves if lib.WILDCARD_RE.fullmatch(m.move)]
    assert wildcards, "no X-<name> wildcard move in the example"
    for m in wildcards:
        assert m.comment, f"line {m.line}: a wildcard move must carry a comment"


def test_a_note_line_is_demonstrated(moves):
    notes = [m for m in moves if m.move == lib.NOTE_MOVE]
    assert notes, "no NOTE line in the example"


# --------------------------------------------------------------------------
# Layer 3: glyphs, including the two extremes
# --------------------------------------------------------------------------


def test_a_brilliancy_and_a_blunder_are_demonstrated(moves):
    glyphs = {m.glyph for m in moves if m.glyph is not None}
    assert "!!" in glyphs, "the example never shows a !! glyph"
    assert "??" in glyphs, "the example never shows a ?? glyph"


def test_every_blunder_explains_itself(moves):
    for m in moves:
        if m.glyph == "??":
            assert m.comment, f"line {m.line}: a ?? glyph must carry a comment"


def test_more_than_one_glyph_shape_is_demonstrated(moves):
    glyphs = {m.glyph for m in moves if m.glyph is not None}
    assert len(glyphs) >= 3, f"only {sorted(glyphs)} demonstrated"
    assert glyphs <= set(lib.GLYPHS)


# --------------------------------------------------------------------------
# Layer 4: motifs
# --------------------------------------------------------------------------


def test_at_least_one_motif_is_demonstrated(moves):
    used = {motif for m in moves for motif in m.motifs}
    assert used, "no line carries a motif"
    assert used <= set(lib.MOTIFS), f"unknown motifs: {sorted(used - set(lib.MOTIFS))}"


# --------------------------------------------------------------------------
# Anchors: both kinds
# --------------------------------------------------------------------------


def test_a_commit_anchor_is_demonstrated(moves):
    hexes = [
        m.anchor
        for m in moves
        if m.anchor is not None and HEX_ANCHOR_RE.fullmatch(m.anchor)
    ]
    assert hexes, "no @<hex> commit anchor in the example"


def test_a_transcript_anchor_is_demonstrated(moves):
    transcripts = [
        m.anchor
        for m in moves
        if m.anchor is not None and TRANSCRIPT_ANCHOR_RE.fullmatch(m.anchor)
    ]
    assert transcripts, "no @t<n> transcript anchor in the example"


# --------------------------------------------------------------------------
# Shape of the whole file
# --------------------------------------------------------------------------


def test_frontmatter_labels_match_the_session_file(parsed):
    meta = parsed[0]
    data = lib.load_yaml(SESSION)
    for key in ("participant", "challenge", "attempt"):
        assert meta[key] == data[key], key


def test_the_example_is_marked_as_a_fixture_not_a_real_attempt():
    """Readers must not mistake the synthetic example for someone's attempt."""
    text = ANNOTATIONS.read_text(encoding="utf-8").lower()
    assert "example" in text
    assert "not a real attempt" in text


def test_the_last_move_fits_inside_the_recorded_wall_time(moves):
    """stats.py sizes the ASCII timeline from ``duration_wall_minutes``.

    A last annotation past the recorded duration would be silently clipped off
    the end of the example's timeline, which is the one timeline every reader
    sees first.
    """
    duration = lib.load_yaml(SESSION)["duration_wall_minutes"]
    assert moves[-1].minutes <= duration, (
        f"the last line is at {moves[-1].timestamp} but session.yaml records "
        f"only {duration} minutes of wall time"
    )


# --------------------------------------------------------------------------
# The templates: what a participant actually copies
# --------------------------------------------------------------------------


def test_template_annotations_lints_clean_with_session(capsys):
    """The template's own header tells participants to run exactly this."""
    rc = lint.main([str(TEMPLATE_ANNOTATIONS), "--session"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "0 error(s), 0 warning(s)" in out


def test_template_session_yaml_satisfies_the_schema():
    data = lib.load_yaml(TEMPLATE_SESSION)
    messages = lib.validate_session_yaml(data, TEMPLATE_SESSION)
    assert messages == [], "\n".join(str(m) for m in messages)


def fenced_lines(text: str) -> list[tuple[int, str]]:
    """``(1-based line number, text)`` for every line inside a ``` fence."""
    out: list[tuple[int, str]] = []
    inside = False
    for number, line in enumerate(text.splitlines(), start=1):
        if lib.FENCE_RE.match(line):
            inside = not inside
            continue
        if inside:
            out.append((number, line))
    return out


def test_template_example_lines_all_parse():
    """The commented-out specimen lines must be copy-pasteable, not decorative.

    They live inside the template's fenced block, which is where a participant
    writes their own -- so that is where this test looks for them.
    """
    specimens = [
        (number, line.strip().lstrip("#").strip())
        for number, line in fenced_lines(
            TEMPLATE_ANNOTATIONS.read_text(encoding="utf-8")
        )
        if line.strip().startswith("#")
    ]
    specimens = [(n, s) for n, s in specimens if s.startswith("+")]
    assert len(specimens) >= 5, "the template should show several specimen lines"
    for number, text in specimens:
        assert lib.parse_annotation_line(number, text, TEMPLATE_ANNOTATIONS) is not None


def test_template_parses_to_no_moves_and_no_messages():
    """A freshly copied template is a legal, empty annotations file.

    Everything a participant reads is prose outside the fence, and every
    specimen inside it is commented out, so the linter must find nothing at
    all -- no move to count and nothing to complain about.
    """
    _, moves, messages = lib.parse_annotations_file(TEMPLATE_ANNOTATIONS)
    assert messages == [], "\n".join(str(m) for m in messages)
    assert moves == []


def test_example_keeps_its_moves_inside_one_fence(moves):
    """One block, and every move line in it (TAXONOMY.md section 8).

    A move that drifted out of the fence would stop being read at all, so the
    example would silently shrink instead of failing.
    """
    lines = ANNOTATIONS.read_text(encoding="utf-8").splitlines()
    fences = [i for i, line in enumerate(lines, start=1) if lib.FENCE_RE.match(line)]
    assert len(fences) == 2, f"expected exactly one fenced block, found {fences}"
    opening, closing = fences
    for m in moves:
        assert opening < m.line < closing, (
            f"line {m.line} ({m.move}) is outside the block at {opening}-{closing}"
        )


def test_template_documents_every_phase_glyph_and_motif_source():
    text = TEMPLATE_ANNOTATIONS.read_text(encoding="utf-8")
    for phase in lib.PHASES:
        assert phase in text, f"the template never names the {phase} phase"
    for glyph in lib.GLYPHS:
        assert glyph in text, f"the template never shows the {glyph} glyph"
    assert str(len(lib.MOVES)) in text, "the template should name the move count"


def test_timestamps_span_a_realistic_session(moves):
    assert moves[0].minutes == 0, "the first line should be +0:00"
    assert moves[-1].minutes >= 120, "the example should cover a multi-hour session"
    assert all(
        a.minutes <= b.minutes for a, b in zip(moves, moves[1:])
    ), "timestamps must be non-decreasing"
