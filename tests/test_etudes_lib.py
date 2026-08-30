"""Unit tests for scripts/etudes_lib.py -- the shared taxonomy/parsing layer."""

from __future__ import annotations

import datetime
import re
import textwrap
from pathlib import Path

import pytest

import etudes_lib as lib
from conftest import load_tool

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Taxonomy constants
# --------------------------------------------------------------------------


def test_taxonomy_shape():
    assert lib.TAXONOMY_VERSION == "0.2"
    assert lib.PHASES == ("Recon", "Plan", "Build", "Verify", "Recover")
    assert set(lib.PHASE_LETTERS) == set(lib.PHASES)
    assert "".join(lib.PHASE_LETTERS[p] for p in lib.PHASES) == "RPBVC"
    assert len(set(lib.PHASE_LETTERS.values())) == 5
    assert len(lib.MOVES) == 24
    assert len(lib.MOTIFS) == 9
    assert set(lib.GLYPHS) == {"!!", "!", "!?", "?!", "?", "??"}


def test_family_sizes():
    counts = {family: 0 for family in lib.FAMILIES}
    for family in lib.MOVES.values():
        counts[family] += 1
    assert counts == {
        "Context": 4,
        "Plan": 4,
        "Delegate": 4,
        "Steer": 6,
        "Epistemic": 6,
    }


def test_glyphs_are_in_taxonomy_order():
    assert lib.GLYPHS == ("!!", "!", "!?", "?!", "?", "??")


# --------------------------------------------------------------------------
# TAXONOMY.md is the authority; the constants above are a hand copy of it.
# These tests read the markdown tables back and refuse to let the two drift.
# --------------------------------------------------------------------------

TAXONOMY_MD = REPO_ROOT / "TAXONOMY.md"


@pytest.fixture(scope="module")
def taxonomy_text():
    return TAXONOMY_MD.read_text(encoding="utf-8")


def _table_rows(text: str, pattern: str) -> list[tuple[str, ...]]:
    return re.findall(pattern, text, re.M)


def test_taxonomy_md_version_matches_the_constant(taxonomy_text):
    meta, _ = lib.split_frontmatter(taxonomy_text, TAXONOMY_MD)
    assert str(meta.get("version")) == lib.TAXONOMY_VERSION


def test_taxonomy_md_phase_table_matches_phases(taxonomy_text):
    section = taxonomy_text.split("## 2. Phases")[1].split("## 3.")[0]
    documented = tuple(_table_rows(section, r"^\|\s*`([A-Za-z]+)`\s*\|"))
    assert documented == lib.PHASES


def test_taxonomy_md_move_table_matches_moves_and_families(taxonomy_text):
    section = taxonomy_text.split("### 3.1")[1].split("Family sizes")[0]
    documented = dict(
        (move, family)
        for family, move in _table_rows(
            section, r"^\|\s*([A-Za-z]+)\s*\|\s*`([A-Z]+)`\s*\|"
        )
    )
    assert documented == lib.MOVES, (
        "TAXONOMY.md and etudes_lib.MOVES disagree: "
        f"{sorted(set(documented) ^ set(lib.MOVES))}"
    )


def test_taxonomy_md_documents_the_wildcard_and_note_entries(taxonomy_text):
    section = taxonomy_text.split("### 3.2")[1].split("### 3.3")[0]
    assert "`X-<name>`" in section
    assert f"`{lib.NOTE_MOVE}`" in section
    assert lib.WILDCARD_RE.fullmatch("X-bribe")


def test_taxonomy_md_glyph_table_matches_glyphs(taxonomy_text):
    section = taxonomy_text.split("## 4. Glyphs")[1].split("### 4.1")[0]
    documented = tuple(_table_rows(section, r"^\|\s*`([!?]{1,2})`\s*\|"))
    assert documented == lib.GLYPHS


def test_taxonomy_md_motif_table_matches_motifs(taxonomy_text):
    section = taxonomy_text.split("## 5. Motifs")[1].split("## 6.")[0]
    documented = tuple(_table_rows(section, r"^\|\s*`([a-z][a-z-]*)`\s*\|"))
    assert documented == lib.MOTIFS


def test_taxonomy_md_stance_markers_match_the_grammar(taxonomy_text):
    section = taxonomy_text.split("## 6. Optional stance marker")[1].split("## 7.")[0]
    assert "`Build>`" in section and "`Build~`" in section
    for stance in (">", "~"):
        mv = lib.parse_annotation_line(1, f"+0:10 Build{stance} NUDGE", "p")
        assert mv.stance == stance


def test_glyph_alternation_needs_explicit_length_sort():
    # Anyone building a regex alternation from GLYPHS must sort by descending
    # length first, otherwise "!" shadows "!?".
    ordered = sorted(lib.GLYPHS, key=len, reverse=True)
    for i, glyph in enumerate(ordered):
        for longer in ordered[i + 1:]:
            assert not longer.startswith(glyph)


@pytest.mark.parametrize(
    "move, expected",
    [
        ("SCOUT", "Context"),
        ("DISTILL", "Context"),
        ("SPEC", "Plan"),
        ("DISPATCH", "Delegate"),
        ("ROLLBACK", "Steer"),
        ("CROSSCHECK", "Epistemic"),
        ("X-bribe", "Wildcard"),
        ("X-a", "Wildcard"),
        ("NOTE", None),
        ("scout", None),
        ("NOPE", None),
        ("X-Bribe", None),
    ],
)
def test_move_family(move, expected):
    assert lib.move_family(move) == expected


def test_is_named_move():
    assert lib.is_named_move("PROBE")
    assert not lib.is_named_move("NOTE")
    assert not lib.is_named_move("X-bribe")
    assert not lib.is_named_move("probe")


@pytest.mark.parametrize("name", ["X-bribe", "X-a", "X-two-words", "X-a1"])
def test_wildcard_re_accepts(name):
    assert lib.WILDCARD_RE.fullmatch(name)


@pytest.mark.parametrize("name", ["X-", "X-Bribe", "x-bribe", "X-1bad", "XY-bribe"])
def test_wildcard_re_rejects(name):
    assert not lib.WILDCARD_RE.fullmatch(name)


# --------------------------------------------------------------------------
# Identifiers and branches
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "branch, expected",
    [
        ("attempt/c001/alice/1", ("c001", "alice", 1)),
        ("attempt/c999/bob-2/12", ("c999", "bob-2", 12)),
    ],
)
def test_parse_branch_accepts(branch, expected):
    assert lib.parse_branch(branch) == expected


@pytest.mark.parametrize(
    "branch",
    [
        "attempt/c001/alice/0",
        "attempt/c001/alice/01",
        "attempt/c001/Alice/1",
        "attempt/c1/alice/1",
        "attempt/alice/1",
        "main",
        "attempt/c001/alice/1/extra",
        "attempt/c001/alice/1\n",  # fullmatch, not $, so a stray newline fails
        "",
        None,
    ],
)
def test_parse_branch_rejects(branch):
    assert lib.parse_branch(branch) is None


def test_id_regexes_reject_trailing_newline():
    assert not lib.CHALLENGE_ID_RE.fullmatch("c001\n")
    assert not lib.PARTICIPANT_RE.fullmatch("alice\n")


# --------------------------------------------------------------------------
# LintMessage
# --------------------------------------------------------------------------


def test_lint_message_str():
    msg = lib.LintMessage("a/b.md", 12, "error", "bad thing")
    assert str(msg) == "a/b.md:12: error: bad thing"
    assert msg.path == "a/b.md" and msg.line == 12


def test_lint_error_carries_message():
    msg = lib.LintMessage("x.md", 3, "error", "boom")
    exc = lib.LintError(msg)
    assert exc.message == msg
    assert str(exc) == "x.md:3: error: boom"
    assert isinstance(exc, lib.EtudesError)


# --------------------------------------------------------------------------
# Frontmatter
# --------------------------------------------------------------------------

GOOD_FRONTMATTER = textwrap.dedent(
    """\
    ---
    participant: alice
    challenge: c001
    attempt: 2
    taxonomy_version: "0.2"
    session_date: 2026-09-12
    ---

    +0:00  Recon  SCOUT  "looked around"
    """
)


def test_split_frontmatter_ok():
    meta, body = lib.split_frontmatter(GOOD_FRONTMATTER, "a.md")
    assert meta["participant"] == "alice"
    assert meta["attempt"] == 2
    assert isinstance(meta["session_date"], datetime.date)
    # Absolute 1-based line numbers: the blank line after --- is line 8.
    assert body[0] == (8, "")
    assert body[1][0] == 9
    assert body[1][1].startswith("+0:00")


def test_split_frontmatter_missing():
    with pytest.raises(lib.LintError) as excinfo:
        lib.split_frontmatter("+0:00 Recon SCOUT\n", "a.md")
    assert excinfo.value.message.line == 1
    assert "missing YAML frontmatter" in excinfo.value.message.text


def test_split_frontmatter_unterminated():
    with pytest.raises(lib.LintError) as excinfo:
        lib.split_frontmatter("---\nparticipant: alice\n", "a.md")
    assert "unterminated" in excinfo.value.message.text


def test_split_frontmatter_not_a_mapping():
    with pytest.raises(lib.LintError) as excinfo:
        lib.split_frontmatter("---\n- a\n- b\n---\n", "a.md")
    assert "mapping" in excinfo.value.message.text


def test_split_frontmatter_bad_yaml():
    with pytest.raises(lib.LintError) as excinfo:
        lib.split_frontmatter("---\na: [1,\n---\n", "a.md")
    assert "not valid YAML" in excinfo.value.message.text


def test_split_frontmatter_empty_block():
    meta, body = lib.split_frontmatter("---\n---\nrest\n", "a.md")
    assert meta == {}
    assert body == [(3, "rest")]


# --------------------------------------------------------------------------
# The line grammar: positives
# --------------------------------------------------------------------------


def parse(text, line_no=1):
    return lib.parse_annotation_line(line_no, text, "a.md")


@pytest.mark.parametrize("text", ["", "   ", "\t", "# a comment", "   # indented"])
def test_ignored_lines(text):
    assert parse(text) is None


def test_minimal_line():
    mv = parse("+0:00 Recon SCOUT")
    assert mv == lib.Move(
        line=1,
        minutes=0,
        timestamp="+0:00",
        phase="Recon",
        stance=None,
        move="SCOUT",
        glyph=None,
        motifs=(),
        comment=None,
        anchor=None,
    )


def test_full_line():
    mv = parse(
        '+1:42\tBuild>  TAKEOVER ?  (false-summit, context-rot) '
        '"rewrote parser by hand" @c3d4e5f',
        line_no=9,
    )
    assert mv.line == 9
    assert mv.minutes == 102
    assert mv.timestamp == "+1:42"
    assert mv.phase == "Build"
    assert mv.stance == ">"
    assert mv.move == "TAKEOVER"
    assert mv.glyph == "?"
    assert mv.motifs == ("false-summit", "context-rot")
    assert mv.comment == "rewrote parser by hand"
    assert mv.anchor == "c3d4e5f"


@pytest.mark.parametrize("stance, expected", [("", None), (">", ">"), ("~", "~")])
def test_stance_suffixes(stance, expected):
    assert parse(f"+0:10 Build{stance} NUDGE").stance == expected


@pytest.mark.parametrize("phase", lib.PHASES)
def test_every_phase(phase):
    assert parse(f"+0:10 {phase} NUDGE").phase == phase


@pytest.mark.parametrize("move", sorted(lib.MOVES))
def test_every_named_move(move):
    assert parse(f"+0:10 Build {move}").move == move


def test_note_move():
    mv = parse('+0:10 Build NOTE "coffee"')
    assert mv.move == "NOTE"
    assert lib.move_family(mv.move) is None


def test_wildcard_move():
    mv = parse('+0:10 Build X-bribe "promised it a cookie"')
    assert mv.move == "X-bribe"
    assert lib.move_family(mv.move) == "Wildcard"


@pytest.mark.parametrize("glyph", lib.GLYPHS)
def test_every_glyph(glyph):
    # "??" needs a comment at file level, but the line parser accepts it alone.
    assert parse(f"+0:10 Build NUDGE {glyph}").glyph == glyph


def test_glyph_two_char_not_shadowed_by_one_char():
    assert parse("+0:10 Build NUDGE !?").glyph == "!?"
    assert parse("+0:10 Build NUDGE ?!").glyph == "?!"
    assert parse("+0:10 Build NUDGE !").glyph == "!"


@pytest.mark.parametrize(
    "listing, expected",
    [
        ("(doom-loop)", ("doom-loop",)),
        ("(doom-loop,windfall)", ("doom-loop", "windfall")),
        ("(doom-loop, windfall)", ("doom-loop", "windfall")),
        ("( doom-loop ,  windfall )", ("doom-loop", "windfall")),
        ("(yes-and, rabbit-hole, ghost-api)", ("yes-and", "rabbit-hole", "ghost-api")),
    ],
)
def test_motif_lists(listing, expected):
    assert parse(f"+0:10 Build NUDGE {listing}").motifs == expected


@pytest.mark.parametrize("motif", lib.MOTIFS)
def test_every_motif(motif):
    assert parse(f"+0:10 Build NUDGE ({motif})").motifs == (motif,)


def test_escaped_quotes_in_comment():
    mv = parse(r'+0:10 Build NUDGE "it said \"done\" but it was not"')
    assert mv.comment == 'it said "done" but it was not'


def test_backslash_in_comment():
    mv = parse(r'+0:10 Build NUDGE "path C:\\tmp"')
    assert mv.comment == r"path C:\tmp"


def test_comment_may_contain_parentheses_and_at():
    mv = parse('+0:10 Build NUDGE "see (the) plan @ noon"')
    assert mv.comment == "see (the) plan @ noon"
    assert mv.anchor is None


@pytest.mark.parametrize(
    "anchor", ["@a1b2c3d", "@" + "a" * 40, "@ABCDEF1", "@t1", "@t12345"]
)
def test_anchor_forms(anchor):
    mv = parse(f"+0:10 Build NUDGE {anchor}")
    assert mv.anchor == anchor[1:]


def test_hours_unbounded():
    mv = parse("+13:07 Verify DEFER")
    assert mv.minutes == 13 * 60 + 7
    assert mv.timestamp == "+13:07"


def test_leading_and_trailing_whitespace_tolerated():
    assert parse("   +0:10 Build NUDGE   ").move == "NUDGE"


def test_crlf_line_ending_tolerated():
    assert parse("+0:10 Build NUDGE\r\n").move == "NUDGE"


# --------------------------------------------------------------------------
# The line grammar: negatives
# --------------------------------------------------------------------------


def expect_error(text, needle):
    with pytest.raises(lib.LintError) as excinfo:
        parse(text, line_no=7)
    msg = excinfo.value.message
    assert msg.line == 7
    assert msg.level == "error"
    assert needle in msg.text, msg.text
    return msg


def test_minute_75_rejected():
    expect_error("+0:75 Build NUDGE", "00-59")


def test_minute_60_rejected():
    expect_error("+0:60 Build NUDGE", "00-59")


def test_one_digit_minutes_rejected():
    expect_error("+0:5 Build NUDGE", "two digits")


def test_no_timestamp():
    expect_error("Recon SCOUT", "+H:MM")


def test_missing_plus():
    expect_error("0:10 Build NUDGE", "+H:MM")


def test_unknown_phase():
    expect_error("+0:10 Building NUDGE", "unknown phase")


def test_lowercase_phase_is_unknown():
    expect_error("+0:10 build NUDGE", "unknown phase")


def test_unknown_move():
    expect_error("+0:10 Build FROTZ", "unknown move")


def test_lowercase_named_move_is_unknown():
    expect_error("+0:10 Build nudge", "unknown move")


@pytest.mark.parametrize("bad", ["X-", "X-Bribe", "X-1x"])
def test_malformed_wildcard(bad):
    expect_error(f'+0:10 Build {bad} "why"', "wildcard")


def test_unknown_glyph():
    expect_error("+0:10 Build NUDGE !!!", "unknown glyph")


def test_unknown_motif():
    expect_error("+0:10 Build NUDGE (doom-scroll)", "unknown motif")


def test_empty_motif_list():
    expect_error("+0:10 Build NUDGE ()", "empty motif list")


def test_trailing_comma_in_motifs():
    expect_error("+0:10 Build NUDGE (windfall,)", "empty motif list")


@pytest.mark.parametrize("bad", ["@abc", "@zzzzzzz", "@t", "@" + "a" * 41])
def test_malformed_anchor(bad):
    expect_error(f"+0:10 Build NUDGE {bad}", "anchor")


def test_trailing_junk():
    expect_error("+0:10 Build NUDGE what is this", "unrecognized")


def test_two_anchors_named_as_such():
    # The grammar allows exactly one anchor. Pointing at both a commit and a
    # transcript position is the mistake people actually make, so the message
    # has to say so rather than "unrecognized text".
    expect_error("+0:10 Build NUDGE @a1b2c3d @b2c3d4e", "at most one anchor")
    expect_error('+0:10 Build NUDGE "c" @t204 @a1b2c3d', "at most one anchor")


def test_an_at_sign_inside_a_comment_is_not_an_anchor():
    mv = lib.parse_annotation_line(1, '+0:10 Build NUDGE "ask @someone"', "p")
    assert mv.anchor is None
    assert mv.comment == "ask @someone"


def test_field_order_enforced():
    expect_error('+0:10 Build NUDGE "comment" (windfall)', "unrecognized")


def test_unterminated_comment():
    expect_error('+0:10 Build NUDGE "no closing quote', "unrecognized")


def test_missing_move():
    expect_error("+0:10 Build", "unrecognized")


# --------------------------------------------------------------------------
# Whole-file lint
# --------------------------------------------------------------------------


def write_annotations(tmp_path, frontmatter: str, body: str):
    path = tmp_path / "annotations.md"
    path.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return path


FM_OK = 'participant: alice\nchallenge: c001\nattempt: 2\ntaxonomy_version: "0.2"\nsession_date: 2026-09-12\n'


def errors(messages):
    return [m for m in messages if m.level == "error"]


def warnings(messages):
    return [m for m in messages if m.level == "warning"]


def test_clean_file(tmp_path):
    path = write_annotations(
        tmp_path,
        FM_OK,
        textwrap.dedent(
            """\

            # a comment line
            +0:00  Recon   SCOUT      "repo map"                 @a1b2c3d
            +0:14  Recon~  TUTOR      "explain CRDTs"
            +0:31  Plan    SPEC !     "tests first"              @t42
            +2:05  Recover RESET !!   (context-rot) "night and day"
            """
        ),
    )
    meta, moves, messages = lib.parse_annotations_file(path)
    assert messages == []
    assert meta["participant"] == "alice"
    assert [m.move for m in moves] == ["SCOUT", "TUTOR", "SPEC", "RESET"]
    assert [m.line for m in moves] == [10, 11, 12, 13]


def test_equal_timestamps_ok(tmp_path):
    path = write_annotations(
        tmp_path, FM_OK, "+0:10 Build NUDGE\n+0:10 Build VETO\n"
    )
    _, moves, messages = lib.parse_annotations_file(path)
    assert messages == []
    assert len(moves) == 2


def test_decreasing_timestamps_rejected(tmp_path):
    path = write_annotations(
        tmp_path, FM_OK, "+1:00 Build NUDGE\n+0:59 Build VETO\n"
    )
    _, _, messages = lib.parse_annotations_file(path)
    errs = errors(messages)
    assert len(errs) == 1
    assert "backwards" in errs[0].text
    assert errs[0].line == 9


def test_wildcard_without_comment(tmp_path):
    path = write_annotations(tmp_path, FM_OK, "+0:10 Build X-bribe\n")
    _, _, messages = lib.parse_annotations_file(path)
    assert len(errors(messages)) == 1
    assert "requires a" in errors(messages)[0].text


def test_wildcard_with_comment_ok(tmp_path):
    path = write_annotations(tmp_path, FM_OK, '+0:10 Build X-bribe "offered a cookie"\n')
    _, moves, messages = lib.parse_annotations_file(path)
    assert messages == []
    assert moves[0].move == "X-bribe"


def test_double_question_without_comment(tmp_path):
    path = write_annotations(tmp_path, FM_OK, "+0:10 Build TAKEOVER ??\n")
    _, _, messages = lib.parse_annotations_file(path)
    assert len(errors(messages)) == 1
    assert "?? glyph requires" in errors(messages)[0].text


def test_double_question_with_comment_ok(tmp_path):
    path = write_annotations(tmp_path, FM_OK, '+0:10 Build TAKEOVER ?? "lost an hour"\n')
    _, _, messages = lib.parse_annotations_file(path)
    assert messages == []


def test_single_question_needs_no_comment(tmp_path):
    path = write_annotations(tmp_path, FM_OK, "+0:10 Build TAKEOVER ?\n")
    _, _, messages = lib.parse_annotations_file(path)
    assert messages == []


def test_errors_are_collected_not_raised(tmp_path):
    path = write_annotations(
        tmp_path, FM_OK, "+0:10 Build FROTZ\n+0:20 Nowhere NUDGE\n+0:30 Build VETO\n"
    )
    _, moves, messages = lib.parse_annotations_file(path)
    assert len(errors(messages)) == 2
    assert [m.line for m in errors(messages)] == [8, 9]
    assert [m.move for m in moves] == ["VETO"]


def test_missing_frontmatter_returns_message(tmp_path):
    path = tmp_path / "annotations.md"
    path.write_text("+0:10 Build NUDGE\n", encoding="utf-8")
    meta, moves, messages = lib.parse_annotations_file(path)
    assert meta == {} and moves == []
    assert len(errors(messages)) == 1


def test_missing_file_returns_message(tmp_path):
    meta, moves, messages = lib.parse_annotations_file(tmp_path / "nope.md")
    assert (meta, moves) == ({}, [])
    assert "not found" in messages[0].text


def test_non_utf8_file_returns_a_message_instead_of_crashing(tmp_path):
    # parse_annotations_file promises never to raise for bad content, and a
    # traceback is not a human-friendly error. UnicodeDecodeError is a
    # ValueError, so it slips past an "except OSError".
    path = tmp_path / "annotations.md"
    path.write_bytes(b"\xff\xfe---\nparticipant: alice\n---\n")
    meta, moves, messages = lib.parse_annotations_file(path)
    assert (meta, moves) == ({}, [])
    assert len(messages) == 1
    assert messages[0].level == "error"
    assert messages[0].line == 1
    assert "UTF-8" in messages[0].text


def test_byte_order_mark_does_not_hide_the_frontmatter(tmp_path):
    # Some editors write a BOM without saying so; the first line still reads
    # as "---" to a human, so it must read that way to the linter too.
    path = tmp_path / "annotations.md"
    path.write_bytes(
        b"\xef\xbb\xbf" + f"---\n{FM_OK}---\n+0:10 Build NUDGE\n".encode("utf-8")
    )
    meta, moves, messages = lib.parse_annotations_file(path)
    assert messages == [], "\n".join(str(m) for m in messages)
    assert meta["participant"] == "alice"
    assert [m.move for m in moves] == ["NUDGE"]


@pytest.mark.parametrize(
    "key", ["participant", "challenge", "attempt", "taxonomy_version", "session_date"]
)
def test_required_frontmatter_keys(tmp_path, key):
    fm = "".join(line + "\n" for line in FM_OK.splitlines() if not line.startswith(key + ":"))
    path = write_annotations(tmp_path, fm, "+0:10 Build NUDGE\n")
    _, _, messages = lib.parse_annotations_file(path)
    assert any(key in m.text and "missing" in m.text for m in errors(messages))


def test_session_date_as_iso_string(tmp_path):
    fm = FM_OK.replace("session_date: 2026-09-12", 'session_date: "2026-09-12"')
    path = write_annotations(tmp_path, fm, "+0:10 Build NUDGE\n")
    _, _, messages = lib.parse_annotations_file(path)
    assert messages == []


def test_session_date_garbage(tmp_path):
    fm = FM_OK.replace("session_date: 2026-09-12", "session_date: someday")
    path = write_annotations(tmp_path, fm, "+0:10 Build NUDGE\n")
    _, _, messages = lib.parse_annotations_file(path)
    errs = errors(messages)
    assert len(errs) == 1 and "session_date" in errs[0].text
    assert errs[0].line == 6  # points at the offending frontmatter line


def test_attempt_true_rejected(tmp_path):
    fm = FM_OK.replace("attempt: 2", "attempt: true")
    path = write_annotations(tmp_path, fm, "+0:10 Build NUDGE\n")
    _, _, messages = lib.parse_annotations_file(path)
    errs = errors(messages)
    assert len(errs) == 1 and "attempt" in errs[0].text
    assert errs[0].line == 4


def test_attempt_zero_rejected(tmp_path):
    fm = FM_OK.replace("attempt: 2", "attempt: 0")
    path = write_annotations(tmp_path, fm, "+0:10 Build NUDGE\n")
    assert any(">= 1" in m.text for m in errors(lib.parse_annotations_file(path)[2]))


def test_bad_participant_rejected(tmp_path):
    fm = FM_OK.replace("participant: alice", "participant: Alice Smith")
    path = write_annotations(tmp_path, fm, "+0:10 Build NUDGE\n")
    assert any("participant" in m.text for m in errors(lib.parse_annotations_file(path)[2]))


def test_bad_challenge_rejected(tmp_path):
    fm = FM_OK.replace("challenge: c001", "challenge: nesting")
    path = write_annotations(tmp_path, fm, "+0:10 Build NUDGE\n")
    assert any("challenge" in m.text for m in errors(lib.parse_annotations_file(path)[2]))


def test_unquoted_taxonomy_version_is_a_warning_not_an_error(tmp_path):
    fm = FM_OK.replace('taxonomy_version: "0.2"', "taxonomy_version: 0.2")
    path = write_annotations(tmp_path, fm, "+0:10 Build NUDGE\n")
    _, _, messages = lib.parse_annotations_file(path)
    assert errors(messages) == []
    warns = warnings(messages)
    assert len(warns) == 1
    assert "quoted" in warns[0].text
    assert warns[0].line == 5


def test_mismatched_taxonomy_version_is_a_warning(tmp_path):
    fm = FM_OK.replace('taxonomy_version: "0.2"', 'taxonomy_version: "0.1"')
    path = write_annotations(tmp_path, fm, "+0:10 Build NUDGE\n")
    _, _, messages = lib.parse_annotations_file(path)
    assert errors(messages) == []
    assert any("0.1" in m.text for m in warnings(messages))


def test_unknown_frontmatter_keys_accepted(tmp_path):
    path = write_annotations(tmp_path, FM_OK + "mood: cheerful\n", "+0:10 Build NUDGE\n")
    _, _, messages = lib.parse_annotations_file(path)
    assert messages == []


# --------------------------------------------------------------------------
# Fences (TAXONOMY.md section 8)
#
# A file whose body holds a ``` fence is read in fenced mode: only the lines
# inside fences are moves, the prose around them is ignored. A file with no
# fence keeps the plain line-by-line reading -- every test above is that
# guarantee. ``write_annotations`` puts the body at file line 8.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,matches",
    [
        ("```", True),
        ("```text", True),
        ("  ```", True),
        ("\t```text", True),
        ("````", True),
        ("a ``` b", False),
        ("``", False),
        ('+0:10 Build NUDGE "``` inside a comment"', False),
        ("", False),
    ],
)
def test_fence_re_matches_only_fence_lines(text, matches):
    assert bool(lib.FENCE_RE.match(text)) is matches


FENCED_BODY = textwrap.dedent(
    """\
    # Alice, attempt 2

    Prose that mentions Recon and a map but has no timestamp.

    ```text
    +0:00  Recon  SCOUT  "map"

    # a comment inside the fence
    +0:14  Plan   SPEC   !
    ```

    Closing remarks.
    """
)


def test_fenced_file_reads_only_the_lines_inside_the_fence(tmp_path):
    path = write_annotations(tmp_path, FM_OK, FENCED_BODY)
    _, moves, messages = lib.parse_annotations_file(path)
    assert messages == []
    assert [m.move for m in moves] == ["SCOUT", "SPEC"]
    # absolute file lines, fence lines counted
    assert [m.line for m in moves] == [13, 16]


def test_move_line_outside_a_fence_is_an_error(tmp_path):
    path = write_annotations(tmp_path, FM_OK, FENCED_BODY + "+0:20  Build  NUDGE\n")
    _, moves, messages = lib.parse_annotations_file(path)
    errs = errors(messages)
    assert len(errs) == 1, [str(m) for m in messages]
    assert errs[0].line == 20
    assert "outside a ``` fence" in errs[0].text
    assert [m.move for m in moves] == ["SCOUT", "SPEC"]


def test_an_indented_move_line_outside_a_fence_is_still_an_error(tmp_path):
    """Indentation is exactly how a move gets lost to the prose."""
    path = write_annotations(tmp_path, FM_OK, FENCED_BODY + "    +0:20  Build  NUDGE\n")
    _, _, messages = lib.parse_annotations_file(path)
    errs = errors(messages)
    assert len(errs) == 1, [str(m) for m in messages]
    assert errs[0].line == 20
    assert "outside a ``` fence" in errs[0].text


def test_prose_outside_a_fence_is_never_parsed_as_a_move(tmp_path):
    body = textwrap.dedent(
        """\
        | Field | Form |
        |---|---|
        | move | one of the 24 named moves |

        ```text
        +0:10  Build  NUDGE
        ```
        """
    )
    path = write_annotations(tmp_path, FM_OK, body)
    _, moves, messages = lib.parse_annotations_file(path)
    assert messages == []
    assert [m.move for m in moves] == ["NUDGE"]


def test_move_lines_in_two_fences_are_one_timeline(tmp_path):
    body = textwrap.dedent(
        """\
        ```text
        +0:30  Build  NUDGE
        ```

        A paragraph between the two blocks.

        ```text
        +0:10  Build  VETO
        ```
        """
    )
    path = write_annotations(tmp_path, FM_OK, body)
    _, moves, messages = lib.parse_annotations_file(path)
    errs = errors(messages)
    assert len(errs) == 1, [str(m) for m in messages]
    assert "goes backwards" in errs[0].text
    # the message names the earlier line, which sits in the first fence
    assert "line 9" in errs[0].text
    assert errs[0].line == 15
    assert [m.move for m in moves] == ["NUDGE", "VETO"]


def test_unclosed_fence_runs_to_the_end_of_the_file(tmp_path):
    path = write_annotations(
        tmp_path, FM_OK, "```text\n+0:10  Build  NUDGE\n+0:20  Build  VETO\n"
    )
    _, moves, messages = lib.parse_annotations_file(path)
    assert messages == []
    assert [m.move for m in moves] == ["NUDGE", "VETO"]


def test_backticks_inside_a_comment_do_not_open_a_fence(tmp_path):
    path = write_annotations(
        tmp_path,
        FM_OK,
        '+0:10 Build NUDGE "wrapped the diff in ``` for the PR"\n+0:20 Build VETO\n',
    )
    _, moves, messages = lib.parse_annotations_file(path)
    assert messages == []
    assert [m.move for m in moves] == ["NUDGE", "VETO"]


def test_plain_file_without_a_fence_still_reports_the_old_message(tmp_path):
    path = write_annotations(
        tmp_path, FM_OK, "Recon SCOUT with no timestamp\n+0:10 Build NUDGE\n"
    )
    _, moves, messages = lib.parse_annotations_file(path)
    errs = errors(messages)
    assert len(errs) == 1
    assert errs[0].line == 8
    assert "+H:MM" in errs[0].text
    assert [m.move for m in moves] == ["NUDGE"]


# --------------------------------------------------------------------------
# session.yaml
# --------------------------------------------------------------------------

SESSION_OK = {
    "participant": "alice",
    "challenge": "c001",
    "attempt": 2,
    "date": datetime.date(2026, 9, 12),
    "tool": {"name": "Some Agent", "version": "1.2.3"},
    "model": {"name": "some-model"},
    "duration_wall_minutes": 235,
    "outcome": {"tests_passed": None, "self_assessment": "It went fine."},
}


def session(**overrides):
    data = {k: (dict(v) if isinstance(v, dict) else v) for k, v in SESSION_OK.items()}
    for key, value in overrides.items():
        if value is _DELETE:
            data.pop(key, None)
        else:
            data[key] = value
    return data


class _Delete:
    pass


_DELETE = _Delete()


def test_session_yaml_clean():
    assert lib.validate_session_yaml(session(), "session.yaml") == []


def test_session_yaml_iso_date_string():
    assert lib.validate_session_yaml(session(date="2026-09-12"), "s.yaml") == []


def test_session_yaml_datetime_ok():
    data = session(date=datetime.datetime(2026, 9, 12, 10, 0))
    assert lib.validate_session_yaml(data, "s.yaml") == []


@pytest.mark.parametrize(
    "key",
    [
        "participant",
        "challenge",
        "attempt",
        "date",
        "tool",
        "model",
        "duration_wall_minutes",
        "outcome",
    ],
)
def test_session_yaml_required_keys(key):
    messages = lib.validate_session_yaml(session(**{key: _DELETE}), "s.yaml")
    assert any(key in m.text and "missing" in m.text for m in messages)


def test_session_yaml_not_a_mapping():
    messages = lib.validate_session_yaml(["a"], "s.yaml")
    assert len(messages) == 1 and "mapping" in messages[0].text


def test_session_yaml_attempt_true_rejected():
    messages = lib.validate_session_yaml(session(attempt=True), "s.yaml")
    assert any("attempt" in m.text for m in messages)


def test_session_yaml_attempt_zero_rejected():
    assert lib.validate_session_yaml(session(attempt=0), "s.yaml")


def test_session_yaml_participant_pattern():
    assert lib.validate_session_yaml(session(participant="Alice"), "s.yaml")


def test_session_yaml_challenge_pattern():
    assert lib.validate_session_yaml(session(challenge="c1"), "s.yaml")


def test_session_yaml_tool_version_must_be_string():
    messages = lib.validate_session_yaml(
        session(tool={"name": "Agent", "version": 1.2}), "s.yaml"
    )
    assert any("tool.version" in m.text for m in messages)


def test_session_yaml_tool_missing_subkey():
    messages = lib.validate_session_yaml(session(tool={"name": "Agent"}), "s.yaml")
    assert any("version" in m.text for m in messages)


def test_session_yaml_model_must_be_mapping():
    assert lib.validate_session_yaml(session(model="some-model"), "s.yaml")


def test_session_yaml_duration_must_be_number():
    assert lib.validate_session_yaml(session(duration_wall_minutes="235"), "s.yaml")


def test_session_yaml_duration_bool_rejected():
    assert lib.validate_session_yaml(session(duration_wall_minutes=True), "s.yaml")


def test_session_yaml_duration_negative_rejected():
    assert lib.validate_session_yaml(session(duration_wall_minutes=-1), "s.yaml")


def test_session_yaml_duration_float_ok():
    assert lib.validate_session_yaml(session(duration_wall_minutes=12.5), "s.yaml") == []


@pytest.mark.parametrize("value", [True, False, None])
def test_session_yaml_tests_passed_tristate(value):
    data = session(outcome={"tests_passed": value, "self_assessment": "ok"})
    assert lib.validate_session_yaml(data, "s.yaml") == []


@pytest.mark.parametrize("value", [1, 0, "true", "yes"])
def test_session_yaml_tests_passed_rejects_lookalikes(value):
    data = session(outcome={"tests_passed": value, "self_assessment": "ok"})
    messages = lib.validate_session_yaml(data, "s.yaml")
    assert any("tests_passed" in m.text for m in messages)


def test_session_yaml_self_assessment_must_be_string():
    data = session(outcome={"tests_passed": None, "self_assessment": 5})
    assert any(
        "self_assessment" in m.text for m in lib.validate_session_yaml(data, "s.yaml")
    )


def test_session_yaml_extra_keys_accepted():
    data = session(notes="hello", cost={"tokens_in": 10}, harness={"notes": ""})
    assert lib.validate_session_yaml(data, "s.yaml") == []


# --------------------------------------------------------------------------
# load_yaml
# --------------------------------------------------------------------------


def test_load_yaml_ok(tmp_path):
    p = tmp_path / "x.yaml"
    p.write_text("a: 1\nb: two\n", encoding="utf-8")
    assert lib.load_yaml(p) == {"a": 1, "b": "two"}


def test_load_yaml_empty(tmp_path):
    p = tmp_path / "x.yaml"
    p.write_text("", encoding="utf-8")
    assert lib.load_yaml(p) == {}


def test_load_yaml_comments_only(tmp_path):
    p = tmp_path / "x.yaml"
    p.write_text("# nothing here\n", encoding="utf-8")
    assert lib.load_yaml(p) == {}


def test_load_yaml_missing(tmp_path):
    with pytest.raises(lib.EtudesError, match="not found"):
        lib.load_yaml(tmp_path / "nope.yaml")


def test_load_yaml_not_a_mapping(tmp_path):
    p = tmp_path / "x.yaml"
    p.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(lib.EtudesError, match="mapping"):
        lib.load_yaml(p)


def test_load_yaml_bad_syntax(tmp_path):
    p = tmp_path / "x.yaml"
    p.write_text("a: [1,\n", encoding="utf-8")
    with pytest.raises(lib.EtudesError, match="not valid YAML"):
        lib.load_yaml(p)


def test_load_yaml_non_utf8_is_an_etudes_error(tmp_path):
    # Every caller of load_yaml catches EtudesError and prints it; a raw
    # UnicodeDecodeError would escape as a traceback instead.
    p = tmp_path / "session.yaml"
    p.write_bytes(b"participant: \xff\xfe\n")
    with pytest.raises(lib.EtudesError, match="UTF-8"):
        lib.load_yaml(p)


def test_load_yaml_tolerates_a_byte_order_mark(tmp_path):
    p = tmp_path / "x.yaml"
    p.write_bytes(b"\xef\xbb\xbfa: 1\n")
    assert lib.load_yaml(p) == {"a": 1}


# --------------------------------------------------------------------------
# Challenge manifests
# --------------------------------------------------------------------------


def test_load_manifest_fake_challenge(fake_challenge_dir):
    data = lib.load_manifest(fake_challenge_dir)
    assert data["id"] == "c999"
    assert data["number"] == 99
    assert data["status"] == "draft"
    assert data["start_tag"] == "c999-start"
    assert "{instance}" in data["validate"] and "{solution}" in data["validate"]
    assert "dependency_group" not in data


def test_load_manifest_directory_name_check_skipped_for_non_id_dirs(fake_challenge_dir):
    # The fixture lives in "fake-challenge" but declares id c999.
    assert fake_challenge_dir.name == "fake-challenge"
    assert lib.load_manifest(fake_challenge_dir)["id"] == "c999"


def write_manifest(tmp_path, dirname="c123", **overrides):
    import yaml as _yaml

    data = {
        "schema_version": 1,
        "id": "c123",
        "number": 123,
        "title": "Example",
        "status": "draft",
        "start_tag": "c123-start",
        "solutions_glob": "solutions/**/*.json",
        "validate": "python tools/validate.py {instance} {solution} --json",
    }
    for key, value in overrides.items():
        if value is _DELETE:
            data.pop(key, None)
        else:
            data[key] = value
    d = tmp_path / dirname
    d.mkdir(parents=True, exist_ok=True)
    (d / "challenge.yaml").write_text(_yaml.safe_dump(data), encoding="utf-8")
    return d


def test_load_manifest_roundtrip(tmp_path):
    assert lib.load_manifest(write_manifest(tmp_path))["id"] == "c123"


def test_load_manifest_optional_dependency_group(tmp_path):
    d = write_manifest(tmp_path, dependency_group="c123")
    assert lib.load_manifest(d)["dependency_group"] == "c123"


def test_load_manifest_missing_file(tmp_path):
    with pytest.raises(lib.ManifestError, match="challenge.yaml"):
        lib.load_manifest(tmp_path)


def test_load_manifest_unknown_key(tmp_path):
    d = write_manifest(tmp_path, extra_thing=1)
    with pytest.raises(lib.ManifestError, match="unknown key"):
        lib.load_manifest(d)


def test_load_manifest_bad_status(tmp_path):
    d = write_manifest(tmp_path, status="published")
    with pytest.raises(lib.ManifestError, match="status"):
        lib.load_manifest(d)


@pytest.mark.parametrize("status", ["draft", "open", "closed"])
def test_load_manifest_all_statuses(tmp_path, status):
    d = write_manifest(tmp_path / status, status=status)
    assert lib.load_manifest(d)["status"] == status


def test_load_manifest_wrong_schema_version(tmp_path):
    d = write_manifest(tmp_path, schema_version=2)
    with pytest.raises(lib.ManifestError, match="schema_version"):
        lib.load_manifest(d)


@pytest.mark.parametrize(
    "key",
    [
        "schema_version",
        "id",
        "number",
        "title",
        "status",
        "start_tag",
        "solutions_glob",
        "validate",
    ],
)
def test_load_manifest_required_keys(tmp_path, key):
    d = write_manifest(tmp_path, **{key: _DELETE})
    with pytest.raises(lib.ManifestError):
        lib.load_manifest(d)


def test_load_manifest_dir_name_mismatch(tmp_path):
    d = write_manifest(tmp_path, dirname="c999", id="c123")
    with pytest.raises(lib.ManifestError, match="directory name"):
        lib.load_manifest(d)


def test_load_manifest_bad_id(tmp_path):
    d = write_manifest(tmp_path, dirname="whatever", id="nesting")
    with pytest.raises(lib.ManifestError, match="id must look like"):
        lib.load_manifest(d)


def test_load_manifest_validate_needs_placeholders(tmp_path):
    d = write_manifest(tmp_path, validate="python tools/validate.py --json")
    with pytest.raises(lib.ManifestError, match=r"\{instance\}"):
        lib.load_manifest(d)


def test_load_manifest_number_must_be_int(tmp_path):
    d = write_manifest(tmp_path, number="123")
    with pytest.raises(lib.ManifestError, match="number"):
        lib.load_manifest(d)


def test_find_challenges(tmp_path):
    (tmp_path / "challenges").mkdir()
    write_manifest(tmp_path / "challenges", dirname="c002", id="c002", number=2)
    write_manifest(tmp_path / "challenges", dirname="c001", id="c001", number=1)
    (tmp_path / "challenges" / "notes").mkdir()
    (tmp_path / "challenges" / "c003").mkdir()  # no manifest -> not a challenge
    found = lib.find_challenges(tmp_path)
    assert [p.name for p in found] == ["c001", "c002"]


def test_find_challenges_no_directory(tmp_path):
    assert lib.find_challenges(tmp_path) == []


def test_repo_has_a_challenges_directory(repo_root):
    assert (repo_root / "challenges").is_dir()


# --------------------------------------------------------------------------
# The fake challenge actually runs
# --------------------------------------------------------------------------


def test_fake_challenge_validator_accepts_and_rejects(fake_challenge_dir):
    validate = load_tool(fake_challenge_dir / "tools" / "validate.py", "fake_validate")
    instance = str(fake_challenge_dir / "instances" / "dev" / "c999-dev-01.json")
    good = str(fake_challenge_dir / "examples" / "valid.json")
    bad = str(fake_challenge_dir / "examples" / "invalid.json")
    assert validate.main([instance, good, "--json"]) == 0
    assert validate.main([instance, bad, "--json"]) == 1


def test_fake_challenge_baseline_writes_a_valid_solution(fake_challenge_dir, tmp_path):
    baseline = load_tool(fake_challenge_dir / "tools" / "baseline.py", "fake_baseline")
    validate = load_tool(fake_challenge_dir / "tools" / "validate.py", "fake_validate2")
    instance = str(fake_challenge_dir / "instances" / "dev" / "c999-dev-01.json")
    out = tmp_path / "solution.json"
    assert baseline.main([instance, "--out", str(out), "--time-budget", "5"]) == 0
    assert validate.main([instance, str(out)]) == 0


def test_fake_challenge_instance_ids_match_filenames(fake_challenge_dir):
    import json

    for path in (fake_challenge_dir / "instances").rglob("*.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["instance_id"] == path.stem


# --------------------------------------------------------------------------
# Results walking
# --------------------------------------------------------------------------


def make_result(root, cid, participant, attempt, *, extra_body=""):
    import yaml as _yaml

    d = root / cid / participant / str(attempt)
    d.mkdir(parents=True)
    (d / "session.yaml").write_text(
        _yaml.safe_dump(
            {
                "participant": participant,
                "challenge": cid,
                "attempt": attempt,
                "date": "2026-09-12",
                "tool": {"name": "Agent", "version": "1.0"},
                "model": {"name": "model-x"},
                "duration_wall_minutes": 60,
                "outcome": {"tests_passed": True, "self_assessment": "fine"},
            }
        ),
        encoding="utf-8",
    )
    (d / "annotations.md").write_text(
        "---\n"
        f"participant: {participant}\n"
        f"challenge: {cid}\n"
        f"attempt: {attempt}\n"
        'taxonomy_version: "0.2"\n'
        "session_date: 2026-09-12\n"
        "---\n"
        "+0:00 Recon SCOUT\n" + extra_body,
        encoding="utf-8",
    )
    return d


def test_walk_results(tmp_path):
    root = tmp_path / "results"
    make_result(root, "c001", "bob", 1)
    make_result(root, "c001", "alice", 2)
    make_result(root, "c001", "alice", 1)
    make_result(root, "c999", "alice", 1)
    (root / "c001" / "stray").mkdir()
    (root / "c001" / "stray" / "session.yaml").write_text("x: 1\n", encoding="utf-8")

    sessions = lib.walk_results(root)
    assert [s.label for s in sessions] == [
        "c001/alice/1",
        "c001/alice/2",
        "c001/bob/1",
        "c999/alice/1",
    ]
    assert all(s.lint == [] for s in sessions)
    assert all(len(s.moves) == 1 for s in sessions)
    assert sessions[0].session["tool"]["name"] == "Agent"
    assert sessions[0].meta["taxonomy_version"] == "0.2"
    assert sessions[0].dir.is_dir()


def test_walk_results_labels_come_from_files_not_paths(tmp_path):
    root = tmp_path / "results"
    d = make_result(root, "c001", "alice", 1)
    moved = root / "misfiled"
    d.rename(moved)
    sessions = lib.walk_results(root)
    assert len(sessions) == 1
    assert sessions[0].label == "c001/alice/1"
    assert sessions[0].dir == moved


def test_walk_results_reports_lint_without_raising(tmp_path):
    root = tmp_path / "results"
    d = make_result(root, "c001", "alice", 1, extra_body="+0:10 Build FROTZ\n")
    (d / "session.yaml").write_text("participant: alice\n", encoding="utf-8")
    sessions = lib.walk_results(root)
    assert len(sessions) == 1
    assert any("unknown move" in m.text for m in sessions[0].lint)
    assert any("missing required key" in m.text for m in sessions[0].lint)
    # Labels still recovered from annotations.md when session.yaml is thin.
    assert sessions[0].cid == "c001"


def test_walk_results_needs_both_files(tmp_path):
    root = tmp_path / "results"
    d = make_result(root, "c001", "alice", 1)
    (d / "annotations.md").unlink()
    assert lib.walk_results(root) == []


def test_walk_results_missing_root(tmp_path):
    assert lib.walk_results(tmp_path / "nope") == []


def test_walk_results_skips_git_directory(tmp_path):
    root = tmp_path / "results"
    make_result(root / ".git", "c001", "alice", 1)
    assert lib.walk_results(root) == []


# --------------------------------------------------------------------------
# Elapsed time
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "minutes, text",
    [(0, "+0:00"), (5, "+0:05"), (59, "+0:59"), (60, "+1:00"), (95, "+1:35"), (787, "+13:07"), (6000, "+100:00")],
)
def test_fmt_and_parse_elapsed_roundtrip(minutes, text):
    assert lib.fmt_elapsed(minutes) == text
    assert lib.parse_elapsed(text) == minutes


def test_fmt_elapsed_rejects_negative():
    with pytest.raises(ValueError):
        lib.fmt_elapsed(-1)


@pytest.mark.parametrize("bad", ["1:00", "+1:0", "+1:60", "+:00", "", "+1:00extra", None, 60])
def test_parse_elapsed_rejects(bad):
    with pytest.raises(ValueError):
        lib.parse_elapsed(bad)


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------


def test_repo_root_from_file_and_dir(tmp_git_repo):
    nested = tmp_git_repo / "a" / "b"
    nested.mkdir(parents=True)
    f = nested / "c.txt"
    f.write_text("hi\n", encoding="utf-8")
    assert lib.repo_root_from(nested) == tmp_git_repo.resolve()
    assert lib.repo_root_from(f) == tmp_git_repo.resolve()


def test_repo_root_from_detects_dot_git_file(tmp_path):
    fake = tmp_path / "worktree"
    fake.mkdir()
    (fake / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
    assert lib.repo_root_from(fake) == fake.resolve()


def test_repo_root_from_this_repo(repo_root):
    assert lib.repo_root_from(__file__) == repo_root


def test_repo_root_from_raises_outside_a_repo(tmp_path):
    p = tmp_path / "elsewhere"
    p.mkdir()
    if any((c / ".git").exists() for c in (p, *p.parents)):
        pytest.skip("the temporary directory happens to sit inside a git checkout")
    with pytest.raises(lib.EtudesError, match="git repository"):
        lib.repo_root_from(p)


def test_git_returns_stdout(tmp_git_repo):
    assert lib.git(["rev-parse", "--abbrev-ref", "HEAD"], tmp_git_repo).strip() == "main"


def test_git_raises_on_failure(tmp_git_repo):
    import subprocess as sp

    with pytest.raises(sp.CalledProcessError):
        lib.git(["rev-parse", "--verify", "does-not-exist"], tmp_git_repo)


def test_git_ok(tmp_git_repo):
    assert lib.git_ok(["rev-parse", "--verify", "HEAD"], tmp_git_repo)
    assert not lib.git_ok(["rev-parse", "--verify", "nope"], tmp_git_repo)


def test_git_ok_survives_a_missing_directory(tmp_path):
    assert not lib.git_ok(["status"], tmp_path / "does-not-exist")


# --------------------------------------------------------------------------
# conftest helper
# --------------------------------------------------------------------------


def test_load_tool_rejects_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_tool(tmp_path / "nope.py", "nope_module")


def test_scripts_dir_is_importable(repo_root):
    assert lib.__file__.startswith(str(repo_root / "scripts"))
