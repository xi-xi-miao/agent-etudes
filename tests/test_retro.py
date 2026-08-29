"""End-to-end and unit tests for ``scripts/retro.py``.

The end-to-end tests build a small ``results/`` tree in ``tmp_path`` from
``examples/example-session`` and run the script as a subprocess, exactly the
way ``make retro`` does. ``--skip-collect`` keeps git out of the picture, and
``--gallery-cmd`` keeps the challenge-specific tooling out of it as well, so
this file stays inside the shared layer's stdlib + PyYAML budget.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import load_tool

import etudes_lib as lib

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "retro.py"

MANIFEST = """\
branch: attempt/c001/example/1
head_sha: 3f9a1c2b0d1e2f3a4b5c6d7e8f90a1b2c3d4e5f6
base_sha: 00112233445566778899aabbccddeeff00112233
start_tag: c001-start
cid: c001
participant: example
attempt: 1
collected_at: 2026-09-13T09:00:00Z
taxonomy_version: "0.2"
"""


@pytest.fixture(scope="module")
def retro():
    """``scripts/retro.py`` imported as a module for the unit tests."""
    return load_tool(SCRIPT, "retro_script")


@pytest.fixture
def results_tree(tmp_path: Path, repo_root: Path) -> Path:
    """``<tmp>/results/c001/example/1`` holding the example session."""
    session_dir = tmp_path / "results" / "c001" / "example" / "1"
    session_dir.mkdir(parents=True)
    example = repo_root / "examples" / "example-session"
    for name in ("session.yaml", "annotations.md"):
        (session_dir / name).write_text(
            (example / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (session_dir / "manifest.yaml").write_text(MANIFEST, encoding="utf-8")
    return tmp_path / "results"


def run_retro(repo_root: Path, results: Path, out: Path, *extra: str):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--challenge",
            "c001",
            "--skip-collect",
            "--repo",
            str(repo_root),
            "--results",
            str(results),
            "--out",
            str(out),
            *extra,
        ],
        capture_output=True,
        text=True,
    )


def block(text: str, block_id: str) -> str:
    """The content between one pair of generated markers."""
    match = re.search(
        rf"<!-- generated:start {block_id} -->\n(.*?)\n<!-- generated:end {block_id} -->",
        text,
        re.DOTALL,
    )
    assert match is not None, f"no {block_id!r} block in:\n{text}"
    return match.group(1)


def gallery_stub() -> str:
    """A portable ``--gallery-cmd`` that just writes a file we can recognise."""
    return (
        f"{sys.executable} -c "
        "\"import sys,pathlib;"
        "pathlib.Path(sys.argv[-1]).write_text('stub gallery')\" {out}"
    )


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------



def add_challenge_stub(repo: Path, cid: str = "c001") -> None:
    """retro.py refuses unknown challenges; give a bare repo a minimal manifest."""
    d = repo / "challenges" / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "challenge.yaml").write_text(
        "schema_version: 1\n"
        f"id: {cid}\n"
        "number: 1\n"
        "title: Stub\n"
        "status: draft\n"
        f"start_tag: {cid}-start\n"
        'solutions_glob: "solutions/**/*.json"\n'
        'validate: "python tools/validate.py {instance} {solution} --json"\n'
    )

def test_retro_writes_the_package(tmp_path, repo_root, results_tree):
    out = tmp_path / "retros" / "c001"
    proc = run_retro(repo_root, results_tree, out, "--gallery-cmd", gallery_stub())
    assert proc.returncode == 0, proc.stderr

    retro_md = out / "retro.md"
    assert retro_md.is_file()
    text = retro_md.read_text(encoding="utf-8")

    # 1. the attempts index row, from session.yaml + manifest.yaml
    index = block(text, "attempts")
    assert "| example | 1 |" in index
    assert "attempt/c001/example/1" in index
    assert "3f9a1c2" in index  # short head sha
    assert "3f9a1c2b0d1e" not in index  # not the whole 40 characters
    assert "+3:55" in index  # duration_wall_minutes: 235

    # 2. the reel: every !!/?? line of the example, and nothing else
    reel = block(text, "reel")
    _, moves, _ = lib.parse_annotations_file(
        results_tree / "c001" / "example" / "1" / "annotations.md"
    )
    marked = [m for m in moves if m.glyph in ("!!", "??")]
    assert marked, "the example session should carry at least one !! and one ??"
    for move in marked:
        assert move.timestamp in reel
        assert move.move in reel
    for move in moves:
        if move.glyph not in ("!!", "??") and move.move not in {
            m.move for m in marked
        }:
            assert f" {move.move} " not in reel

    # 3. the wildcard table with its promotion evidence
    wildcards = block(text, "wildcards")
    assert "X-timebox" in wildcards
    assert "| 1 | 1 (example) | no |" in wildcards

    # 4. narrative sections survive as headings with TODO markers
    assert "## 2. Steal list" in text
    assert "TODO" in text

    # 5. the reel is printed for pasting into the discussion thread
    assert "brilliancies and blunders reel" in proc.stdout
    for move in marked:
        assert move.timestamp in proc.stdout

    # 6. companion files
    assert (out / "gallery.html").read_text(encoding="utf-8") == "stub gallery"
    if (repo_root / "scripts" / "stats.py").is_file():
        assert (out / "stats.txt").is_file()
        assert (out / "stats.txt").read_text(encoding="utf-8").strip()
    else:  # pragma: no cover - only while stats.py is still being written
        pytest.skip("scripts/stats.py does not exist yet")


def test_rerun_keeps_the_narrative_and_refreshes_the_blocks(
    tmp_path, repo_root, results_tree
):
    out = tmp_path / "retros" / "c001"
    assert run_retro(
        repo_root, results_tree, out, "--gallery-cmd", gallery_stub()
    ).returncode == 0

    retro_md = out / "retro.md"
    first = retro_md.read_text(encoding="utf-8")
    assert "bob" not in block(first, "attempts")
    retro_md.write_text(
        first + "\n## 8. My hand-written section\n\nWe agreed to keep pairing.\n",
        encoding="utf-8",
    )

    # a second attempt appears in results/ before the re-run
    second_dir = results_tree / "c001" / "bob" / "1"
    second_dir.mkdir(parents=True)
    example = results_tree / "c001" / "example" / "1"
    for name in ("session.yaml", "annotations.md"):
        (second_dir / name).write_text(
            example.joinpath(name)
            .read_text(encoding="utf-8")
            .replace("participant: example", "participant: bob"),
            encoding="utf-8",
        )
    (second_dir / "manifest.yaml").write_text(
        "branch: attempt/c001/bob/1\nhead_sha: 9f8e7d6c5b4a39281706\n", encoding="utf-8"
    )

    assert run_retro(
        repo_root, results_tree, out, "--gallery-cmd", gallery_stub()
    ).returncode == 0
    second = retro_md.read_text(encoding="utf-8")

    # the narrative outside the markers is untouched
    assert "## 8. My hand-written section" in second
    assert "We agreed to keep pairing." in second

    # and the generated block really was replaced, not appended to
    index = block(second, "attempts")
    assert "| bob | 1 |" in index
    assert "| example | 1 |" in index
    assert index.count("| example | 1 |") == 1
    assert second.count("<!-- generated:start attempts -->") == 1
    # alphabetical by participant
    assert index.index("| bob |") < index.index("| example |")

    # the other two blocks are refreshed too, and the three marker pairs stay
    # distinct (a greedy match would swallow the middle one)
    assert "c001/bob/1" in block(second, "reel")
    assert "generated:start" not in block(second, "reel")
    assert "2 (bob, example)" in block(second, "wildcards")
    for block_id in ("attempts", "reel", "wildcards"):
        assert second.count(f"<!-- generated:start {block_id} -->") == 1


def test_other_challenges_are_left_out(tmp_path, repo_root, results_tree):
    other = results_tree / "c002" / "zoe" / "1"
    other.mkdir(parents=True)
    source = results_tree / "c001" / "example" / "1"
    for name in ("session.yaml", "annotations.md"):
        (other / name).write_text(
            source.joinpath(name)
            .read_text(encoding="utf-8")
            .replace("challenge: c001", "challenge: c002")
            .replace("participant: example", "participant: zoe"),
            encoding="utf-8",
        )

    out = tmp_path / "out"
    assert (
        run_retro(
            repo_root, results_tree, out, "--gallery-cmd", gallery_stub()
        ).returncode
        == 0
    )
    text = (out / "retro.md").read_text(encoding="utf-8")
    assert "zoe" not in block(text, "attempts")
    assert "| example | 1 |" in block(text, "attempts")
    assert "c002" not in block(text, "reel")
    assert "1 (example)" in block(text, "wildcards")


def test_missing_block_is_appended_with_a_notice(tmp_path, repo_root, results_tree):
    out = tmp_path / "retros" / "c001"
    assert run_retro(
        repo_root, results_tree, out, "--gallery-cmd", gallery_stub()
    ).returncode == 0

    retro_md = out / "retro.md"
    text = retro_md.read_text(encoding="utf-8")
    stripped = re.sub(
        r"<!-- generated:start wildcards -->.*?<!-- generated:end wildcards -->",
        "someone deleted the wildcard block",
        text,
        flags=re.DOTALL,
    )
    retro_md.write_text(stripped, encoding="utf-8")

    proc = run_retro(repo_root, results_tree, out, "--gallery-cmd", gallery_stub())
    assert proc.returncode == 0
    refreshed = retro_md.read_text(encoding="utf-8")
    assert "someone deleted the wildcard block" in refreshed
    assert "X-timebox" in block(refreshed, "wildcards")
    assert "wildcards" in proc.stderr


def test_no_gallery_tool_is_a_notice_not_a_failure(tmp_path, results_tree):
    fake_repo = tmp_path / "fake-repo"
    (fake_repo / "templates").mkdir(parents=True)
    add_challenge_stub(fake_repo)
    out = tmp_path / "out"
    proc = run_retro(fake_repo, results_tree, out)
    assert proc.returncode == 0
    assert "gallery" in proc.stderr
    assert not (out / "gallery.html").exists()
    # no templates/retro.md either: the built-in skeleton takes over
    text = (out / "retro.md").read_text(encoding="utf-8")
    assert "| example | 1 |" in block(text, "attempts")


def test_collect_step_runs_when_it_is_not_skipped(tmp_path, tmp_git_repo):
    """Without --skip-collect the script drives collect_results.py itself."""
    add_challenge_stub(tmp_git_repo)
    out = tmp_path / "out"
    results = tmp_path / "results"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--challenge",
            "c001",
            "--repo",
            str(tmp_git_repo),
            "--results",
            str(results),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "collecting attempt branches" in proc.stdout
    # the repository has no attempt branches, so the document comes out empty
    assert "no attempts collected yet" in block(
        (out / "retro.md").read_text(encoding="utf-8"), "attempts"
    )


def test_collect_failure_points_at_skip_collect(tmp_path):
    not_a_repo = tmp_path / "elsewhere"
    not_a_repo.mkdir()
    add_challenge_stub(not_a_repo)
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--challenge",
            "c001",
            "--repo",
            str(not_a_repo),
            "--out",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "--skip-collect" in proc.stderr


def test_unknown_challenge_id_is_a_friendly_error(tmp_path, repo_root, results_tree):
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--challenge",
            "nope",
            "--skip-collect",
            "--repo",
            str(repo_root),
            "--results",
            str(results_tree),
            "--out",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "c001" in proc.stderr and "nope" in proc.stderr


def test_empty_results_tree_still_writes_a_document(tmp_path, repo_root):
    empty = tmp_path / "results"
    empty.mkdir()
    out = tmp_path / "out"
    proc = run_retro(repo_root, empty, out, "--gallery-cmd", gallery_stub())
    assert proc.returncode == 0
    text = (out / "retro.md").read_text(encoding="utf-8")
    assert "no attempts collected yet" in block(text, "attempts")
    assert "no !! or ?? lines" in block(text, "reel")
    assert "no wildcard moves" in block(text, "wildcards")


def test_missing_results_tree_is_a_notice_not_a_failure(tmp_path, repo_root):
    out = tmp_path / "out"
    proc = run_retro(repo_root, tmp_path / "nowhere", out)
    assert proc.returncode == 0
    assert "nowhere" in proc.stderr
    assert "no attempts collected yet" in block(
        (out / "retro.md").read_text(encoding="utf-8"), "attempts"
    )


# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------


def make_session(participant: str, lines: list[str], attempt: int = 1):
    moves = [
        lib.parse_annotation_line(i + 1, text) for i, text in enumerate(lines)
    ]
    return lib.Session(
        dir=Path("results") / "c001" / participant / str(attempt),
        cid="c001",
        participant=participant,
        attempt=attempt,
        session={},
        meta={},
        moves=[m for m in moves if m is not None],
        lint=[],
    )


def test_wildcard_threshold_two_participants(retro):
    sessions = [
        make_session("alice", ['+0:10  Build  X-bribe  "one"']),
        make_session("bob", ['+0:20  Build  X-bribe  "two"']),
    ]
    table = retro.build_wildcard_table(sessions)
    assert "| `X-bribe` | 2 | 2 (alice, bob) | yes |" in table


def test_wildcard_threshold_three_uses_by_one_participant(retro):
    sessions = [
        make_session(
            "alice",
            [
                '+0:10  Build  X-bribe  "one"',
                '+0:20  Build  X-bribe  "two"',
                '+0:30  Build  X-bribe  "three"',
                '+0:40  Build  X-timebox  "only once"',
            ],
        )
    ]
    table = retro.build_wildcard_table(sessions)
    assert "| `X-bribe` | 3 | 1 (alice) | yes |" in table
    assert "| `X-timebox` | 1 | 1 (alice) | no |" in table


def test_reel_holds_only_the_marked_lines(retro):
    session = make_session(
        "alice",
        [
            '+0:10  Build   NUDGE  !',
            '+0:20  Build>  RESET  !!  "clean slate"  @abc1234',
            '+0:30  Verify  DEFER  ??  "did not read the test"',
        ],
    )
    reel = retro.build_reel([session])
    assert "NUDGE" not in reel
    assert "RESET" in reel and "@abc1234" in reel
    assert "Build>" in reel
    assert "DEFER" in reel and "did not read the test" in reel
    assert len(reel.splitlines()) == 2


def test_index_row_survives_a_missing_manifest(retro, tmp_path):
    session = make_session("alice", ['+0:10  Build  NUDGE'])
    session.dir = tmp_path  # no manifest.yaml in here
    table = retro.build_attempts_table([session])
    assert "| alice | 1 |" in table
    assert "(unknown)" in table


def test_refresh_document_replaces_only_the_block(retro):
    original = (
        "# Retro\n\nkeep me\n\n"
        + retro.render_block("attempts", "| old |")
        + "\n\nkeep me too\n"
    )
    text, missing = retro.refresh_document(original, {"attempts": "| new |"})
    assert "keep me" in text and "keep me too" in text
    assert "| new |" in text and "| old |" not in text
    assert missing == []


def test_refresh_document_appends_unknown_blocks(retro):
    original = "# Retro\n\n" + retro.render_block("attempts", "| old |") + "\n"
    text, missing = retro.refresh_document(
        original, {"attempts": "| new |", "reel": "a reel"}
    )
    assert missing == ["reel"]
    assert "a reel" in text
    assert text.count("<!-- generated:start reel -->") == 1


def test_build_document_fills_the_template_sections(retro, repo_root):
    template = (repo_root / "templates" / "retro.md").read_text(encoding="utf-8")
    blocks = {"attempts": "| a |", "reel": "```\nr\n```", "wildcards": "| w |"}
    text = retro.build_document(template, blocks, "c001", 1)
    assert "étude no. 1 (`c001`)" in text
    for block_id, content in blocks.items():
        assert content in block(text, block_id)
    # the narrative sections keep their prose
    assert "Moves worth copying" in text
    assert "TODO" in text


def test_gallery_placeholders(retro, tmp_path, monkeypatch):
    """A custom --gallery-cmd receives absolute, shell-quoted paths."""
    out_file = tmp_path / "gallery.html"
    ok = retro.run_gallery(
        tmp_path,
        tmp_path / "results",
        "c001",
        out_file,
        f"{sys.executable} -c \"import sys,pathlib;"
        "pathlib.Path(sys.argv[-1]).write_text(sys.argv[-3])\" {results_glob} --out {out}",
    )
    assert ok is True
    written = out_file.read_text(encoding="utf-8")
    assert written.endswith("solutions/*.json")
    assert str(tmp_path) in written


def test_unknown_challenge_is_refused(tmp_path, tmp_git_repo):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--challenge", "c777", "--repo", str(tmp_git_repo),
         "--skip-collect", "--out", str(tmp_path / "out")],
        capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "no such challenge" in proc.stderr
    assert not (tmp_path / "out").exists()
