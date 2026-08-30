"""Tests for ``scripts/stats.py``.

The tree under test is built in ``tmp_path`` from the repository's own
``examples/example-session`` plus two synthetic sessions, so the expected
timeline strings can be derived by hand from the timestamps in those files.
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import etudes_lib

from conftest import load_tool

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "example-session"

stats = load_tool(REPO_ROOT / "scripts" / "stats.py", "etudes_stats")


# The words this repository refuses to use. They are spelled in fragments
# because this test file is itself covered by the repository word check.
_BANNED = ("leader" + "board", "sc" + "ore", "ra" + "nk", "win" + "ner")
_BANNED_RE = re.compile(r"\b(?:" + "|".join(_BANNED) + r")(?:s|ing|ings)?\b", re.I)


# --------------------------------------------------------------------------
# Fixture tree
# --------------------------------------------------------------------------

BOB_SESSION = """\
participant: bob
challenge: c001
attempt: 1
date: 2026-09-13

tool:
  name: "Another Agent"
  version: "0.9"

model:
  name: "another-model"

duration_wall_minutes: 60

outcome:
  tests_passed: true
  self_assessment: "Synthetic session used by the test suite."
"""

# First line at +0:20, so the timeline starts with '.' cells.
BOB_ANNOTATIONS = """\
---
participant: bob
challenge: c001
attempt: 1
taxonomy_version: "0.2"
session_date: 2026-09-13
---

+0:20  Recon    SCOUT                     "read the instance format end to end"
+0:35  Build>   X-timebox                 "boxed the first solver spike at fifteen minutes"
+0:50  Build    NUDGE       ?             "asked for smaller functions instead of a rewrite"
+0:55  Recover  X-timebox   (doom-loop)   "second timer, this time on the retry loop"
+0:58  Verify   CROSSCHECK  !!            "read every validator error code out loud"
"""

# No duration_wall_minutes: exercises the timeline fallback.
CAROL_SESSION = """\
participant: carol
challenge: c002
attempt: 1
date: 2026-09-14

tool:
  name: "Third Agent"
  version: "2.0"

model:
  name: "third-model"

outcome:
  tests_passed: null
  self_assessment: "Synthetic session used by the test suite."
"""

CAROL_ANNOTATIONS = """\
---
participant: carol
challenge: c002
attempt: 1
taxonomy_version: "0.2"
session_date: 2026-09-14
---

+0:00  Recon  SCOUT  "skimmed the manifest"
+0:10  Plan   PLAN   "one page of steps"
"""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A results tree: c001/example/1, c001/bob/1 and c002/carol/1."""
    root = tmp_path / "results"

    example = root / "c001" / "example" / "1"
    example.mkdir(parents=True)
    for name in ("session.yaml", "annotations.md"):
        shutil.copy(EXAMPLE / name, example / name)

    bob = root / "c001" / "bob" / "1"
    bob.mkdir(parents=True)
    (bob / "session.yaml").write_text(BOB_SESSION, encoding="utf-8")
    (bob / "annotations.md").write_text(BOB_ANNOTATIONS, encoding="utf-8")

    carol = root / "c002" / "carol" / "1"
    carol.mkdir(parents=True)
    (carol / "session.yaml").write_text(CAROL_SESSION, encoding="utf-8")
    (carol / "annotations.md").write_text(CAROL_ANNOTATIONS, encoding="utf-8")

    return root


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = stats.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def timeline_for(text: str, label: str) -> str:
    """The timeline characters printed on the row for ``label``."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == label and set(parts[1]) <= set("RPBVC."):
            return parts[1]
    raise AssertionError(f"no timeline row for {label} in:\n{text}")


def rows_containing(text: str, needle: str) -> list[str]:
    return [line for line in text.splitlines() if needle in line]


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------


def test_report_runs_and_names_every_session(tree, capsys):
    code, out, _ = run(capsys, str(tree))
    assert code == 0
    assert "c001" in out and "c002" in out
    assert "example/1" in out
    assert "bob/1" in out
    assert "carol/1" in out


def test_all_family_headings_present(tree, capsys):
    _, out, _ = run(capsys, str(tree))
    for family in ("Context", "Plan", "Delegate", "Steer", "Epistemic", "Wildcard"):
        assert re.search(rf"^\s+{family}$", out, re.M), f"missing family {family}"


def test_move_frequency_counts_moves_and_excludes_note(tree, capsys):
    _, out, _ = run(capsys, str(tree))
    assert "Move frequency by family" in out
    scout = rows_containing(out, "SCOUT")
    assert scout, "no SCOUT row"
    # example uses SCOUT once, bob once: total 2 in the c001 section.
    assert scout[0].split()[1:] == ["1", "1", "2"]

    # The example has 14 annotation lines, one of them a NOTE (+3:52), and bob
    # has 5: 13 + 5 = 18 counted moves in the c001 section. Counting the NOTE
    # line would make this 19.
    section = out.split("etude c001", 1)[1].split("Glyph distribution", 1)[0]
    total = 0
    for line in section.splitlines():
        parts = line.split()
        if not parts or not (parts[0] in etudes_lib.MOVES or parts[0].startswith("X-")):
            continue
        numbers = [p for p in parts[1:] if p.isdigit()]
        total += int(numbers[2])  # columns: bob/1, example/1, total
    assert total == 18, section


def test_wildcard_row_shows_count_and_distinct_participants(tree, capsys):
    _, out, _ = run(capsys, str(tree))
    rows = rows_containing(out, "X-timebox")
    assert rows, "the wildcard move is missing from the report"
    first = rows[0]
    # bob used it twice, example once -> three uses by two participants.
    assert first.split()[1:4] == ["2", "1", "3"]
    assert "2 participants" in first


def test_glyph_distribution(tree, capsys):
    _, out, _ = run(capsys, str(tree))
    assert "Glyph distribution" in out
    section = out.split("Glyph distribution", 1)[1]
    bang_bang = [
        line for line in section.splitlines() if line.split()[:1] == ["!!"]
    ]
    assert bang_bang and bang_bang[0].split()[-1] == "2"  # example + bob
    query = [line for line in section.splitlines() if line.split()[:1] == ["??"]]
    assert query and query[0].split()[-1] == "1"


def test_motif_counts(tree, capsys):
    _, out, _ = run(capsys, str(tree))
    assert "Motif counts" in out
    section = out.split("Motif counts", 1)[1]
    for motif, total in (("context-rot", "1"), ("yes-and", "1"), ("doom-loop", "1")):
        rows = [line for line in section.splitlines() if line.split()[:1] == [motif]]
        assert rows, f"no row for motif {motif}"
        assert rows[0].split()[-1] == total


def test_example_timeline_length_and_letters(tree, capsys):
    _, out, _ = run(capsys, str(tree))
    timeline = timeline_for(out, "c001/example/1")

    # duration_wall_minutes: 235 in examples/example-session/session.yaml.
    assert len(timeline) == math.ceil(235 / 5) == 47

    # Derived from the example's timestamps; cell i shows the phase of the
    # latest non-NOTE move at or before minute 5*i:
    #   +0:00 Recon .. +0:26 Plan .. +0:52 Build .. +2:44 Recover ..
    #   +3:12 Build .. +3:24 Verify (the +3:52 NOTE never sets a phase)
    expected = "R" * 6 + "P" * 5 + "B" * 22 + "C" * 6 + "B" * 2 + "V" * 6
    assert timeline == expected
    assert timeline[0] == "R"
    assert timeline[6] == "P"
    assert timeline[11] == "B"
    assert timeline[33] == "C"
    assert timeline[39] == "B"
    assert timeline[46] == "V"


def test_timeline_uses_dots_before_the_first_move(tree, capsys):
    _, out, _ = run(capsys, str(tree))
    timeline = timeline_for(out, "c001/bob/1")
    # duration 60 -> 12 cells; first move at +0:20 -> cells 0..3 are empty.
    assert len(timeline) == math.ceil(60 / 5) == 12
    assert timeline == "....RRRBBBBC"


def test_timeline_legend_printed_once(tree, capsys):
    _, out, _ = run(capsys, str(tree))
    assert out.count("R=Recon") == 1
    assert "C=Recover" in out
    assert out.count("Phase timelines") == 2  # one section per challenge


def test_timeline_header_states_the_sampling_rule(tree, capsys):
    """A reader must not mistake a missing letter for a missing phase."""
    _, out, _ = run(capsys, str(tree))
    header = out.split("Phase timelines", 1)[1].split("\n\n", 1)[0]
    assert "cell i is sampled at minute 5 * i" in header
    assert "latest move at or before that mark" in header
    # the consequence, spelled out: a short phase inside one cell is invisible
    assert "begins and ends" in header and "invisible" in header
    assert "carries across cells with no move" in header


def test_timeline_falls_back_to_the_last_timestamp_with_a_warning(tree, capsys):
    _, out, err = run(capsys, str(tree))
    timeline = timeline_for(out, "c002/carol/1")
    # No duration_wall_minutes: last line is +0:10 -> 10 // 5 + 1 = 3 cells.
    assert len(timeline) == 10 // 5 + 1
    assert timeline == "RRP"
    assert "the timeline stops at the last annotated line" in err


def test_reel_holds_the_brilliancies_and_the_blunders(tree, capsys):
    _, out, _ = run(capsys, str(tree))
    assert "Brilliancies and blunders reel" in out
    reel = out.split("Brilliancies and blunders reel", 1)[1]
    assert "fresh session seeded with a handoff doc" in reel  # !!
    assert "handed off a shelf packer" in reel  # ??
    assert "read every validator error code out loud" in reel  # bob's !!
    # Alphabetical by participant: bob before example.
    assert reel.index("c001/bob/1") < reel.index("c001/example/1")
    # A ?! line is not part of the reel.
    assert "TOL_AREA" not in reel


def test_aggregate_section_follows_the_challenge_sections(tree, capsys):
    _, out, _ = run(capsys, str(tree))
    assert "all challenges" in out
    assert out.index("etude c001") < out.index("all challenges")
    aggregate = out.split("all challenges", 1)[1]
    # Aggregate columns are challenge ids, and X-timebox is still three uses.
    rows = rows_containing(aggregate, "X-timebox")
    assert rows and rows[0].split()[1:4] == ["3", "0", "3"]


# --------------------------------------------------------------------------
# --grep
# --------------------------------------------------------------------------


def test_grep_finds_a_move(tree, capsys):
    code, out, _ = run(capsys, str(tree), "--grep", "RESET")
    assert code == 0
    lines = out.strip().splitlines()
    assert len(lines) == 1
    source = (EXAMPLE / "annotations.md").read_text(encoding="utf-8").splitlines()
    line_no = next(i + 1 for i, t in enumerate(source) if " RESET " in t)
    assert lines[0].startswith(f"c001/example/1:{line_no}: ")
    assert "fresh session seeded with a handoff doc" in lines[0]


def test_grep_finds_a_motif_across_sessions(tree, capsys):
    code, out, _ = run(capsys, str(tree), "--grep", "doom-loop")
    assert code == 0
    lines = out.strip().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("c001/bob/1:")
    assert "X-timebox" in lines[0]


def test_grep_is_case_sensitive_and_exact(tree, capsys):
    code, out, err = run(capsys, str(tree), "--grep", "reset")
    assert code == 1
    assert out == ""
    assert "no annotation line uses the move or motif" in err

    code, _, _ = run(capsys, str(tree), "--grep", "SET")
    assert code == 1


def test_grep_honours_the_challenge_filter(tree, capsys):
    code, out, _ = run(capsys, str(tree), "--grep", "SCOUT", "--challenge", "c002")
    assert code == 0
    lines = out.strip().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("c002/carol/1:")
    # Without the filter the same token matches in all three sessions.
    _, wide, _ = run(capsys, str(tree), "--grep", "SCOUT")
    assert len(wide.strip().splitlines()) == 3


def test_grep_finds_note_lines_even_though_they_are_never_counted(tree, capsys):
    code, out, _ = run(capsys, str(tree), "--grep", "NOTE")
    assert code == 0
    lines = out.strip().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("c001/example/1:")
    assert "laptop slept" in lines[0]


def test_grep_prints_no_tables(tree, capsys):
    _, out, _ = run(capsys, str(tree), "--grep", "SCOUT")
    assert "Move frequency by family" not in out


DAVE_ANNOTATIONS = """\
---
participant: dave
challenge: c001
attempt: 1
taxonomy_version: "0.2"
session_date: 2026-09-13
---

# Dave, attempt 1

Two lines of prose the tooling ignores, sitting where a reader wants them and
where a line-counting tool would trip over them.

```text
+0:20  Recon    SCOUT       "read the format"
+0:40  Recover  RESET  !!   "clean slate"
```
"""


def test_grep_reports_the_on_disk_line_number_through_a_fence(tmp_path, capsys):
    """``--grep`` prints where to look, so the number must survive the prose.

    ``stats.py`` re-reads the file by ``Move.line``; with a fenced layout that
    number counts the heading, the paragraphs and the opening fence too, or the
    printed text would be some other line entirely.
    """
    root = tmp_path / "results"
    dave = root / "c001" / "dave" / "1"
    dave.mkdir(parents=True)
    (dave / "session.yaml").write_text(
        BOB_SESSION.replace("participant: bob", "participant: dave"), encoding="utf-8"
    )
    (dave / "annotations.md").write_text(DAVE_ANNOTATIONS, encoding="utf-8")

    lines = DAVE_ANNOTATIONS.splitlines()
    expected = next(i + 1 for i, t in enumerate(lines) if " RESET " in t)

    code, out, err = run(capsys, str(root), "--grep", "RESET")

    assert code == 0, err
    printed = out.strip().splitlines()
    assert len(printed) == 1, printed
    assert printed[0].startswith(f"c001/dave/1:{expected}: "), printed
    assert printed[0].endswith('"clean slate"'), printed


# --------------------------------------------------------------------------
# Filters, roots and error handling
# --------------------------------------------------------------------------


def test_challenge_filter_selects_one_challenge(tree, capsys):
    code, out, _ = run(capsys, str(tree), "--challenge", "c001")
    assert code == 0
    assert "bob/1" in out and "example/1" in out
    assert "carol" not in out
    assert "c002" not in out


def test_challenge_filter_rejects_a_bad_id(tree, capsys):
    code, out, err = run(capsys, str(tree), "--challenge", "nope")
    assert code == 2
    assert "challenge id like c001" in err


def test_challenge_filter_with_no_sessions_is_not_a_failure(tree, capsys):
    code, out, err = run(capsys, str(tree), "--challenge", "c003")
    assert code == 0
    assert "no sessions for challenge c003" in err


def test_empty_tree_is_not_a_failure(tmp_path, capsys):
    empty = tmp_path / "results"
    empty.mkdir()
    code, out, err = run(capsys, str(empty))
    assert code == 0
    assert "no sessions" in err


def test_missing_root_is_a_friendly_error(tmp_path, capsys):
    code, out, err = run(capsys, str(tmp_path / "nope"))
    assert code == 2
    assert "no such directory" in err


def test_runs_from_any_cwd_with_a_relative_path(tree):
    script = REPO_ROOT / "scripts" / "stats.py"
    proc = subprocess.run(
        [sys.executable, str(script), "results", "--challenge", "c001"],
        cwd=tree.parent,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Move frequency by family" in proc.stdout
    assert "c001/example/1" in proc.stdout


def test_default_root_is_the_repository_results_directory():
    assert stats.default_results_root() == REPO_ROOT / "results"


# --------------------------------------------------------------------------
# House rules
# --------------------------------------------------------------------------


def test_report_uses_no_forbidden_word(tree, capsys):
    _, out, err = run(capsys, str(tree))
    assert not _BANNED_RE.search(out), _BANNED_RE.search(out)
    assert not _BANNED_RE.search(err), _BANNED_RE.search(err)


@pytest.mark.parametrize(
    "relative", ["scripts/stats.py", "tests/test_stats.py"]
)
def test_sources_use_no_forbidden_word(relative):
    text = (REPO_ROOT / relative).read_text(encoding="utf-8")
    hit = _BANNED_RE.search(text)
    assert hit is None, f"{relative} says {hit.group(0)!r}"


def test_absurd_duration_is_clamped_with_a_note(tmp_path):
    """A typo in duration_wall_minutes must not produce a megabyte-long row."""
    stats = load_tool(REPO_ROOT / "scripts" / "stats.py", "stats_clamp")
    target = tmp_path / "results" / "c001" / "example" / "1"
    shutil.copytree(EXAMPLE, target)
    session_path = target / "session.yaml"
    text = session_path.read_text(encoding="utf-8")
    assert "duration_wall_minutes: 235" in text
    session_path.write_text(text.replace("duration_wall_minutes: 235", "duration_wall_minutes: 100000000"), encoding="utf-8")
    sessions = etudes_lib.walk_results(tmp_path / "results")
    assert len(sessions) == 1
    cells, note = stats.timeline_cells(sessions[0])
    assert cells == stats.MAX_TIMELINE_CELLS
    assert note and "clipped" in note
