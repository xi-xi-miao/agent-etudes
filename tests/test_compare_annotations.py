"""Tests for ``scripts/compare_annotations.py``.

The fixture is a small annotations file plus a reviewer's copy of it that
differs in exactly the ways cross-annotation actually differs: one move read
differently, one glyph the reviewer did not award, one optional stance marker
the reviewer left off, and lines the reviewer recorded that the original does
not have -- one at a timestamp both files share (so it has to find its partner
by content) and one at a timestamp only the reviewer used.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import load_tool

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_annotations.py"

FRONTMATTER = """\
---
participant: alice
challenge: c001
attempt: 1
taxonomy_version: "0.2"
session_date: 2026-09-12
---

"""

ORIGINAL = FRONTMATTER + """\
# alice's own annotations
+0:00  Recon    SCOUT                   "read the challenge README end to end"
+0:20  Plan     SPEC        !           "wrote the round trip test before any solver code"
+1:05  Build>   DISPATCH                "handed the packer over with the fit rule spelled out"
+1:05  Build    NUDGE                   "asked for smaller steps"
+2:30  Verify   CROSSCHECK  ??          "took the agent's summary on trust and shipped it"
"""

REVIEW = FRONTMATTER + """\
# bob re-annotating alice's session from the same git log
+0:00  Recon    SCOUT                   "read the challenge README end to end"
+0:20  Plan     SPEC                    "wrote the round trip test before any solver code"
+1:05  Build    DISPATCH                "handed the packer over with the fit rule spelled out"
+1:05  Build    REDIRECT                "this reads as a course correction, not a nudge"
+1:05  Build    PROBE                   "an extra line the original does not have"
+2:30  Verify   CROSSCHECK  ??          "took the agent's summary on trust and shipped it"
+3:00  Recover  DEFER                   "a line at a timestamp only this file uses"
"""


@pytest.fixture(scope="module")
def compare_module():
    return load_tool(SCRIPT, "compare_annotations_script")


@pytest.fixture
def pair(tmp_path: Path) -> tuple[Path, Path]:
    review = tmp_path / "bob.annotations.md"
    original = tmp_path / "annotations.md"
    review.write_text(REVIEW, encoding="utf-8")
    original.write_text(ORIGINAL, encoding="utf-8")
    return review, original


def run_compare(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *[str(a) for a in args]],
        capture_output=True,
        text=True,
    )


def test_agreement_counts_and_percentages(pair):
    proc = run_compare(*pair)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout

    assert "7 annotated line(s) in A, 5 in B; 5 aligned by timestamp." in out
    # the two files never disagree about the bare phase: the one difference
    # is the optional stance marker, which is its own row
    assert re.search(r"phase\s+5 / 5\s+100\.0%", out), out
    # no pair has a stance on both sides, so there is nothing to count
    assert re.search(r"stance\s+0 / 0\s+n/a", out), out
    # move and glyph each disagree on exactly one pair
    assert re.search(r"move\s+4 / 5\s+80\.0%", out), out
    assert re.search(r"glyph\s+4 / 5\s+80\.0%", out), out
    # two of the five pairs differ in at least one of the three
    assert re.search(r"all three\s+3 / 5\s+60\.0%", out), out
    assert "counted only over the pairs where both files gave" in out


def test_disagreement_lines(pair):
    out = run_compare(*pair).stdout
    assert "+0:20: A=Plan SPEC - | B=Plan SPEC !" in out
    assert "+1:05: A=Build REDIRECT - | B=Build NUDGE -" in out
    # a bare phase against a stance-marked one is an omitted optional field,
    # not a differing reading of the minute
    assert "A=Build DISPATCH - | B=Build> DISPATCH -" not in out
    # the pairs that agree are not listed
    assert (
        "SCOUT"
        not in out.split("Lines that found no partner")[0].split("Disagreements")[1]
    )


def test_lines_that_found_no_partner(pair):
    out = run_compare(*pair).stdout
    tail = out.split("Lines that found no partner")[1]
    # surplus line at a shared timestamp: the other two found partners by
    # content, so the third is what is left over -- and B does use that minute
    assert "only in A: +1:05: Build PROBE -" in tail
    probe_line = [ln for ln in tail.splitlines() if "PROBE" in ln][0]
    assert "the other file has that minute" in probe_line
    # and a line at a timestamp the other file never uses carries no such note
    defer_line = [ln for ln in tail.splitlines() if "DEFER" in ln][0]
    assert defer_line.strip() == "only in A: +3:00: Recover DEFER -"
    assert "only in B" not in tail


def test_json_output(pair):
    proc = run_compare(*pair, "--json")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)

    assert report["moves"] == {"a": 7, "b": 5}
    assert report["aligned"] == 5
    assert report["agreement"]["phase"] == {
        "agree": 5,
        "total": 5,
        "percent": 100.0,
    }
    assert report["agreement"]["stance"] == {
        "agree": 0,
        "total": 0,
        "percent": None,
    }
    assert report["agreement"]["all three"]["agree"] == 3
    assert [d["timestamp"] for d in report["disagreements"]] == ["+0:20", "+1:05"]
    assert report["disagreements"][1]["a"]["move"] == "REDIRECT"
    assert report["disagreements"][1]["b"]["move"] == "NUDGE"
    # phase and stance are separate keys on both sides
    assert report["disagreements"][1]["a"]["phase"] == "Build"
    assert report["disagreements"][1]["a"]["stance"] is None
    assert [d["move"] for d in report["only_in_a"]] == ["PROBE", "DEFER"]
    assert report["only_in_b"] == []
    assert report["notes"] == []


def test_identical_files_agree_completely(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text(ORIGINAL, encoding="utf-8")
    b.write_text(ORIGINAL, encoding="utf-8")
    out = run_compare(a, b).stdout
    assert re.search(r"all three\s+5 / 5\s+100\.0%", out), out
    assert "none: every aligned line has the same phase, move and glyph" in out
    assert "none: every line was paired with one in the other file." in out


def test_no_shared_timestamps(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text(FRONTMATTER + "+0:05  Recon  SCOUT\n", encoding="utf-8")
    b.write_text(FRONTMATTER + "+0:06  Recon  SCOUT\n", encoding="utf-8")
    proc = run_compare(a, b)
    assert proc.returncode == 0
    assert "nothing to compare" in proc.stdout
    assert "only in A: +0:05" in proc.stdout
    assert "only in B: +0:06" in proc.stdout


def test_missing_file_is_informational(tmp_path):
    a = tmp_path / "a.md"
    a.write_text(ORIGINAL, encoding="utf-8")
    proc = run_compare(a, tmp_path / "nowhere.md")
    assert proc.returncode == 0, "the tool is informational and always exits 0"
    assert "nowhere.md" in proc.stderr
    assert "file not found" in proc.stdout


def test_files_from_different_sessions_get_a_note(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text(ORIGINAL, encoding="utf-8")
    b.write_text(
        ORIGINAL.replace("participant: alice", "participant: carol"), encoding="utf-8"
    )
    out = run_compare(a, b).stdout
    assert "disagree about participant" in out


def test_broken_grammar_is_reported_but_does_not_stop_the_comparison(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text(ORIGINAL + "+9:99  Recon  SCOUT\n", encoding="utf-8")
    b.write_text(ORIGINAL, encoding="utf-8")
    proc = run_compare(a, b)
    assert proc.returncode == 0
    assert "minutes must be 00-59" in proc.stdout
    assert re.search(r"all three\s+5 / 5", proc.stdout), proc.stdout


# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------


def parse(compare_module, lines):
    import etudes_lib as lib

    return [
        lib.parse_annotation_line(i + 1, text) for i, text in enumerate(lines)
    ]


def test_align_pairs_by_content_within_one_timestamp(compare_module):
    a = parse(compare_module, ["+0:10  Build  NUDGE", "+0:10  Build  VETO"])
    b = parse(compare_module, ["+0:10  Build  VETO"])
    pairs, only_a, only_b = compare_module.align(a, b)
    # VETO finds VETO whatever position it sits in; NUDGE is the surplus
    assert [(x.move, y.move) for x, y in pairs] == [("VETO", "VETO")]
    assert [m.move for m in only_a] == ["NUDGE"]
    assert only_b == []


def test_align_survives_a_reordered_minute(compare_module):
    """Two annotators are not obliged to order one minute the same way."""
    lines = [
        '+0:04  Plan  CRITERIA  !!  "named the fit rule"',
        '+0:04  Plan  SPEC          "wrote the round trip test"',
    ]
    a = parse(compare_module, lines)
    b = parse(compare_module, list(reversed(lines)))
    pairs, only_a, only_b = compare_module.align(a, b)
    assert [(x.move, y.move) for x, y in pairs] == [
        ("CRITERIA", "CRITERIA"),
        ("SPEC", "SPEC"),
    ]
    assert (only_a, only_b) == ([], [])
    data = compare_module.agreement(pairs)
    assert data["move"]["percent"] == 100.0
    assert data["all three"]["percent"] == 100.0
    assert compare_module.disagreements(pairs) == []


def test_align_prefers_the_same_move_over_file_order(compare_module):
    a = parse(compare_module, ["+0:08  Build  SPIKE  !", "+0:08  Verify  CROSSCHECK"])
    b = parse(compare_module, ["+0:08  Verify  CROSSCHECK", "+0:08  Build  SPIKE"])
    pairs, only_a, only_b = compare_module.align(a, b)
    assert [(x.move, y.move) for x, y in pairs] == [
        ("SPIKE", "SPIKE"),
        ("CROSSCHECK", "CROSSCHECK"),
    ]
    assert (only_a, only_b) == ([], [])


def test_align_still_pairs_a_single_line_on_each_side(compare_module):
    """One line against one line is unambiguous even when nothing matches."""
    a = parse(compare_module, ["+0:10  Build  NUDGE  !!"])
    b = parse(compare_module, ["+0:10  Build  REDIRECT  ?"])
    pairs, only_a, only_b = compare_module.align(a, b)
    assert [(x.move, y.move) for x, y in pairs] == [("NUDGE", "REDIRECT")]
    assert (only_a, only_b) == ([], [])


def test_align_reports_an_ambiguous_leftover_instead_of_guessing(compare_module):
    a = parse(compare_module, ["+0:10  Build  NUDGE  !!", "+0:10  Build  SPIKE  ??"])
    b = parse(compare_module, ["+0:10  Build  REDIRECT  ?"])
    pairs, only_a, only_b = compare_module.align(a, b)
    assert pairs == []
    assert [m.move for m in only_a] == ["NUDGE", "SPIKE"]
    assert [m.move for m in only_b] == ["REDIRECT"]
    # and the report says so: these are not lines at a minute the other file
    # never used, they are lines the matcher refused to guess a partner for
    unmatched = compare_module._unmatched(only_a, {m.minutes for m in b})
    assert all(item["shared_timestamp"] for item in unmatched)


def test_stance_is_counted_only_where_both_files_marked_one(compare_module):
    a = parse(
        compare_module,
        [
            "+0:01  Build>  DISPATCH",
            "+0:02  Build>  SPIKE",
            "+0:03  Build   NUDGE",
        ],
    )
    b = parse(
        compare_module,
        [
            "+0:01  Build>  DISPATCH",
            "+0:02  Build~  SPIKE",
            "+0:03  Build>  NUDGE",
        ],
    )
    pairs, _, _ = compare_module.align(a, b)
    data = compare_module.agreement(pairs)
    # the bare phase is Build everywhere
    assert data["phase"] == {"agree": 3, "total": 3, "percent": 100.0}
    # only the first two pairs carry a stance on both sides, and they differ
    # on one of them; the third pair is not counted at all
    assert data["stance"] == {"agree": 1, "total": 2, "percent": 50.0}
    # a stance-only difference never moves the "all three" row ...
    assert data["all three"] == {"agree": 3, "total": 3, "percent": 100.0}
    # ... but a real > against ~ is still worth showing
    assert [d["timestamp"] for d in compare_module.disagreements(pairs)] == ["+0:02"]


def test_phase_of_drops_the_stance(compare_module):
    move = parse(compare_module, ["+1:00  Build~  SPIKE"])[0]
    assert compare_module.phase_of(move) == "Build"
    assert compare_module.stance_of(move) == "~"


def test_summarize_includes_the_stance(compare_module):
    move = parse(compare_module, ['+1:00  Build~  SPIKE  !?  "timing harness"'])[0]
    assert compare_module.summarize(move) == "Build~ SPIKE !?"


def test_agreement_of_no_pairs_has_no_percentage(compare_module):
    data = compare_module.agreement([])
    assert data["move"] == {"agree": 0, "total": 0, "percent": None}
