"""Tests for ``scripts/compare_annotations.py``.

The fixture is a small annotations file plus a reviewer's copy of it that
differs in exactly the ways cross-annotation actually differs: one move read
differently, one glyph the reviewer did not award, and lines the reviewer
recorded that the original does not have -- one at a timestamp both files
share (so the two lines have to be paired in order) and one at a timestamp
only the reviewer used.
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
    # phase (with stance), move and glyph each disagree on exactly one pair
    assert re.search(r"phase\s+4 / 5\s+80\.0%", out), out
    assert re.search(r"move\s+4 / 5\s+80\.0%", out), out
    assert re.search(r"glyph\s+4 / 5\s+80\.0%", out), out
    # three of the five pairs differ in at least one field
    assert re.search(r"all three\s+2 / 5\s+40\.0%", out), out


def test_disagreement_lines(pair):
    out = run_compare(*pair).stdout
    assert "+0:20: A=Plan SPEC - | B=Plan SPEC !" in out
    assert "+1:05: A=Build DISPATCH - | B=Build> DISPATCH -" in out
    assert "+1:05: A=Build REDIRECT - | B=Build NUDGE -" in out
    # the pairs that agree are not listed
    assert "SCOUT" not in out.split("Lines present")[0].split("Disagreements")[1]


def test_lines_present_in_only_one_file(pair):
    out = run_compare(*pair).stdout
    tail = out.split("Lines present in only one file")[1]
    # surplus line at a shared timestamp: aligned in order, the third is left over
    assert "only in A: +1:05: Build PROBE -" in tail
    # and a line at a timestamp the other file never uses
    assert "only in A: +3:00: Recover DEFER -" in tail
    assert "only in B" not in tail


def test_json_output(pair):
    proc = run_compare(*pair, "--json")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)

    assert report["moves"] == {"a": 7, "b": 5}
    assert report["aligned"] == 5
    assert report["agreement"]["phase"] == {
        "agree": 4,
        "total": 5,
        "percent": 80.0,
    }
    assert report["agreement"]["all three"]["agree"] == 2
    assert [d["timestamp"] for d in report["disagreements"]] == [
        "+0:20",
        "+1:05",
        "+1:05",
    ]
    assert report["disagreements"][1]["a"]["phase"] == "Build"
    assert report["disagreements"][1]["b"]["phase"] == "Build>"
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
    assert "none: every aligned line has the same phase, move and glyph." in out
    assert "none: every line found a partner at its timestamp." in out


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


def test_align_pairs_in_order_within_one_timestamp(compare_module):
    a = parse(compare_module, ["+0:10  Build  NUDGE", "+0:10  Build  VETO"])
    b = parse(compare_module, ["+0:10  Build  VETO"])
    pairs, only_a, only_b = compare_module.align(a, b)
    assert [(x.move, y.move) for x, y in pairs] == [("NUDGE", "VETO")]
    assert [m.move for m in only_a] == ["VETO"]
    assert only_b == []


def test_summarize_includes_the_stance(compare_module):
    move = parse(compare_module, ['+1:00  Build~  SPIKE  !?  "timing harness"'])[0]
    assert compare_module.summarize(move) == "Build~ SPIKE !?"


def test_agreement_of_no_pairs_has_no_percentage(compare_module):
    data = compare_module.agreement([])
    assert data["move"] == {"agree": 0, "total": 0, "percent": None}
