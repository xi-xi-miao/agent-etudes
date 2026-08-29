"""Tests for ``scripts/collect_results.py``.

Every test builds a throwaway repository (the ``tmp_git_repo`` fixture) with a
``c001-start`` tag and one or more attempt branches, then runs the collector as
a subprocess -- the way a maintainer runs it -- from an unrelated working
directory, so the "works from any cwd" promise is exercised too.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import load_tool

REPO_ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = REPO_ROOT / "scripts" / "collect_results.py"
EXAMPLE_SESSION = REPO_ROOT / "examples" / "example-session"

T0 = "2026-09-12T09:00:00+00:00"
T7 = "2026-09-12T09:07:00+00:00"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def git(repo: Path, *args: str, at: str | None = None) -> str:
    env = dict(os.environ)
    if at is not None:
        env["GIT_AUTHOR_DATE"] = at
        env["GIT_COMMITTER_DATE"] = at
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def add_attempt(
    repo: Path,
    branch: str,
    *,
    with_solutions: bool = True,
    with_reviews: bool = False,
) -> None:
    """Create ``branch`` off main with a session/ dir and (maybe) solutions."""
    git(repo, "checkout", "-b", branch, "main")

    shutil.copytree(EXAMPLE_SESSION, repo / "session", dirs_exist_ok=True)
    write(repo / "solver" / "solve.py", "# solver code, never collected\n")
    if with_reviews:
        write(
            repo / "reviews" / "bob.annotations.md",
            "---\nparticipant: bob\nchallenge: c001\nattempt: 1\n"
            'taxonomy_version: "0.2"\nsession_date: 2026-09-13\n---\n\n'
            "+0:00  Recon  SCOUT\n",
        )
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "session log", at=T0)

    if with_solutions:
        write(
            repo / "solutions" / "x.json",
            json.dumps({"instance_id": "c001-t1-dev-01", "placements": []}) + "\n",
        )
        write(repo / "solutions" / "x.svg", "<svg xmlns='http://www.w3.org/2000/svg'/>\n")
        write(repo / "solutions" / "notes.txt", "not a solution, not collected\n")
    else:
        write(repo / "solver" / "notes.md", "no solutions committed yet\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "solutions", at=T7)

    git(repo, "checkout", "main")


def collect(repo: Path, *args: str, cwd: Path | None = None):
    """Run the collector as a subprocess; returns the CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(COLLECTOR), "--repo", str(repo), *args],
        cwd=str(cwd if cwd is not None else repo.parent),
        capture_output=True,
        text=True,
    )


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def attempt_repo(tmp_git_repo: Path) -> Path:
    """A repo with tag ``c001-start`` on main and ``attempt/c001/test/1``."""
    git(tmp_git_repo, "tag", "-a", "c001-start", "-m", "étude no. 1 starts here")
    add_attempt(tmp_git_repo, "attempt/c001/test/1")
    return tmp_git_repo


# --------------------------------------------------------------------------
# the happy path
# --------------------------------------------------------------------------


def test_collects_the_expected_files(attempt_repo: Path):
    proc = collect(attempt_repo)
    assert proc.returncode == 0, proc.stderr

    target = attempt_repo / "results" / "c001" / "test" / "1"
    for name in (
        "manifest.yaml",
        "git-timeline.txt",
        "session.yaml",
        "annotations.md",
        "solutions/x.json",
    ):
        assert (target / name).is_file(), f"missing {name}\n{proc.stdout}{proc.stderr}"

    # session/ is flattened onto the target root, sub-directories preserved
    assert (target / "postmortem.md").is_file()
    assert (target / "decisions" / "dr-001.md").is_file()
    assert not (target / "session").exists()

    # sibling renderings ride along; solver code and stray files never do
    assert (target / "solutions" / "x.svg").is_file()
    assert not (target / "solutions" / "notes.txt").exists()
    assert not (target / "solver").exists()


def test_never_switches_the_working_tree(attempt_repo: Path):
    before = git(attempt_repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    collect(attempt_repo)
    after = git(attempt_repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    assert before == after == "main"
    assert git(attempt_repo, "status", "--porcelain", "--untracked-files=no") == ""


def test_manifest_fields(attempt_repo: Path):
    collect(attempt_repo)
    manifest = yaml.safe_load(
        (attempt_repo / "results/c001/test/1/manifest.yaml").read_text(encoding="utf-8")
    )

    head = git(attempt_repo, "rev-parse", "attempt/c001/test/1^{commit}").strip()
    base = git(attempt_repo, "rev-parse", "main^{commit}").strip()

    assert manifest["branch"] == "attempt/c001/test/1"
    assert manifest["head_sha"] == head
    assert manifest["base_sha"] == base
    assert manifest["start_tag"] == "c001-start"
    assert manifest["cid"] == "c001"
    assert manifest["participant"] == "test"
    assert manifest["attempt"] == 1
    assert manifest["taxonomy_version"] == "0.2"
    assert manifest["collected_at"].endswith("Z")
    assert "session/annotations.md" in manifest["copied_paths"]
    assert "solutions/x.json" in manifest["copied_paths"]
    assert "solver/solve.py" not in manifest["copied_paths"]
    # provenance only: no measures are stored here
    assert set(manifest) == {
        "branch",
        "head_sha",
        "base_sha",
        "start_tag",
        "cid",
        "participant",
        "attempt",
        "collected_at",
        "taxonomy_version",
        "copied_paths",
    }


def test_timeline_uses_elapsed_time(attempt_repo: Path):
    collect(attempt_repo)
    lines = (
        (attempt_repo / "results/c001/test/1/git-timeline.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(lines) == 2
    assert lines[0].split()[1] == "+0:00"
    assert lines[1].split()[1] == "+0:07"
    assert lines[0].endswith("session log")
    assert lines[1].endswith("solutions")


def test_report_line_and_secret_reminder(attempt_repo: Path):
    proc = collect(attempt_repo)
    assert "c001/test/1" in proc.stdout
    assert "files" in proc.stdout
    assert "secrets" in proc.stdout.lower()


def test_reviews_are_preserved(tmp_git_repo: Path):
    git(tmp_git_repo, "tag", "-a", "c001-start", "-m", "start")
    add_attempt(tmp_git_repo, "attempt/c001/test/1", with_reviews=True)
    collect(tmp_git_repo)
    assert (
        tmp_git_repo / "results/c001/test/1/reviews/bob.annotations.md"
    ).is_file()


# --------------------------------------------------------------------------
# idempotency
# --------------------------------------------------------------------------


def test_rerunning_is_idempotent(attempt_repo: Path):
    collect(attempt_repo)
    target = attempt_repo / "results" / "c001" / "test" / "1"
    first = tree_bytes(target)

    proc = collect(attempt_repo)
    assert proc.returncode == 0, proc.stderr
    assert tree_bytes(target) == first  # byte for byte, collected_at included


def test_hand_committed_reviews_survive_a_recollection(attempt_repo: Path):
    """Cross-annotations live in results/, not on the attempt branch.

    CONTRIBUTING has a reviewer commit
    ``results/c001/alice/1/reviews/bob.annotations.md`` straight to main, so
    rebuilding the attempt directory must not delete it.
    """
    collect(attempt_repo)
    target = attempt_repo / "results" / "c001" / "test" / "1"
    review = target / "reviews" / "bob.annotations.md"
    write(
        review,
        "---\nparticipant: bob\nchallenge: c001\nattempt: 1\n"
        'taxonomy_version: "0.2"\nsession_date: 2026-09-13\n---\n\n'
        "+0:00  Recon  SCOUT\n",
    )
    before = tree_bytes(target)

    proc = collect(attempt_repo)
    assert proc.returncode == 0, proc.stderr
    assert review.is_file()
    # the carried-over file must not churn collected_at either
    assert tree_bytes(target) == before


def test_a_review_on_the_branch_wins_over_the_collected_copy(tmp_git_repo: Path):
    git(tmp_git_repo, "tag", "-a", "c001-start", "-m", "start")
    add_attempt(tmp_git_repo, "attempt/c001/test/1", with_reviews=True)
    collect(tmp_git_repo)
    review = (
        tmp_git_repo / "results/c001/test/1/reviews/bob.annotations.md"
    )
    review.write_text("edited by hand\n", encoding="utf-8")

    collect(tmp_git_repo)
    assert review.read_text(encoding="utf-8").startswith("---\n")


def test_stale_files_are_removed(attempt_repo: Path):
    collect(attempt_repo)
    target = attempt_repo / "results" / "c001" / "test" / "1"
    stale = target / "solutions" / "gone.json"
    stale.write_text("{}\n", encoding="utf-8")
    collect(attempt_repo)
    assert not stale.exists()
    assert (target / "solutions" / "x.json").is_file()


# --------------------------------------------------------------------------
# refs the collector should not choke on
# --------------------------------------------------------------------------


def test_malformed_attempt_branch_is_skipped_with_a_warning(attempt_repo: Path):
    git(attempt_repo, "branch", "attempt/bad", "main")
    proc = collect(attempt_repo)
    assert proc.returncode == 0, proc.stderr
    assert "attempt/bad" in proc.stderr
    assert "warning" in proc.stderr
    # the well-formed attempt is still collected
    assert (attempt_repo / "results/c001/test/1/annotations.md").is_file()
    assert not (attempt_repo / "results" / "bad").exists()


def test_branch_without_solutions_still_collects(tmp_git_repo: Path):
    git(tmp_git_repo, "tag", "-a", "c001-start", "-m", "start")
    add_attempt(tmp_git_repo, "attempt/c001/nosol/1", with_solutions=False)
    proc = collect(tmp_git_repo)
    assert proc.returncode == 0, proc.stderr

    target = tmp_git_repo / "results" / "c001" / "nosol" / "1"
    assert (target / "annotations.md").is_file()
    assert (target / "manifest.yaml").is_file()
    assert (target / "git-timeline.txt").read_text(encoding="utf-8").count("\n") == 2
    assert not (target / "solutions").exists()


def test_missing_start_tag_falls_back_to_main(tmp_git_repo: Path):
    add_attempt(tmp_git_repo, "attempt/c002/test/1")
    proc = collect(tmp_git_repo)
    assert proc.returncode == 0, proc.stderr
    assert "c002-start" in proc.stderr

    manifest = yaml.safe_load(
        (tmp_git_repo / "results/c002/test/1/manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["start_tag"] is None
    assert manifest["base_sha"] == git(tmp_git_repo, "rev-parse", "main^{commit}").strip()


def test_explicit_ref_argument(attempt_repo: Path):
    git(attempt_repo, "branch", "attempt/c001/other/2", "attempt/c001/test/1")
    proc = collect(attempt_repo, "attempt/c001/other/2")
    assert proc.returncode == 0, proc.stderr
    assert (attempt_repo / "results/c001/other/2/annotations.md").is_file()
    assert not (attempt_repo / "results" / "c001" / "test").exists()


def test_unknown_explicit_ref_is_a_friendly_error(attempt_repo: Path):
    proc = collect(attempt_repo, "attempt/c001/nobody/9")
    assert proc.returncode == 1
    assert "no such branch" in proc.stderr


def test_no_attempt_branches_at_all(tmp_git_repo: Path):
    proc = collect(tmp_git_repo)
    assert proc.returncode == 0, proc.stderr
    assert "No attempt branches" in proc.stdout


def test_not_a_repository_is_a_friendly_error(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    proc = subprocess.run(
        [sys.executable, str(COLLECTOR), "--repo", str(plain)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "not a git repository" in proc.stderr


def test_results_directory_can_be_redirected(attempt_repo: Path, tmp_path: Path):
    elsewhere = tmp_path / "elsewhere"
    proc = collect(attempt_repo, "--results", str(elsewhere))
    assert proc.returncode == 0, proc.stderr
    assert (elsewhere / "c001" / "test" / "1" / "annotations.md").is_file()
    assert not (attempt_repo / "results").exists()


def test_relative_paths_from_an_unrelated_directory(attempt_repo: Path, tmp_path: Path):
    """--repo and --results may be relative to whatever cwd the run has."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    relative_repo = os.path.relpath(attempt_repo, workdir)
    proc = subprocess.run(
        [
            sys.executable,
            str(COLLECTOR),
            "--repo",
            relative_repo,
            "--results",
            "collected",
        ],
        cwd=str(workdir),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (workdir / "collected/c001/test/1/annotations.md").is_file()


# --------------------------------------------------------------------------
# the challenge manifest decides which solution files travel
# --------------------------------------------------------------------------


def add_manifest(repo: Path, cid: str, body: str) -> None:
    """Commit a ``challenges/<cid>/challenge.yaml`` on main."""
    write(repo / "challenges" / cid / "challenge.yaml", body)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", f"add the {cid} manifest")


MANIFEST_BODY = """\
schema_version: 1
id: c001
number: 1
title: "Fixture Challenge"
status: draft
start_tag: c001-start
solutions_glob: "out/*.json"
validate: "python tools/validate.py {instance} {solution} --json"
"""


def test_solutions_glob_comes_from_the_challenge_manifest(tmp_git_repo: Path):
    add_manifest(tmp_git_repo, "c001", MANIFEST_BODY)
    git(tmp_git_repo, "tag", "-a", "c001-start", "-m", "start")

    git(tmp_git_repo, "checkout", "-b", "attempt/c001/test/1", "main")
    shutil.copytree(EXAMPLE_SESSION, tmp_git_repo / "session", dirs_exist_ok=True)
    write(tmp_git_repo / "out" / "a.json", "{}\n")
    write(tmp_git_repo / "out" / "a.svg", "<svg/>\n")
    write(tmp_git_repo / "solutions" / "x.json", "{}\n")
    git(tmp_git_repo, "add", "-A")
    git(tmp_git_repo, "commit", "-m", "attempt", at=T0)
    git(tmp_git_repo, "checkout", "main")

    proc = collect(tmp_git_repo)
    assert proc.returncode == 0, proc.stderr

    target = tmp_git_repo / "results" / "c001" / "test" / "1"
    assert (target / "out" / "a.json").is_file()
    assert (target / "out" / "a.svg").is_file()
    assert not (target / "solutions").exists()


def test_broken_manifest_warns_and_uses_the_default_glob(attempt_repo: Path):
    add_manifest(
        attempt_repo,
        "c001",
        MANIFEST_BODY.replace(
            'solutions_glob: "out/*.json"',
            'solutions_glob: "out/*.json"\nnonsense: true',
        ),
    )
    proc = collect(attempt_repo)
    assert proc.returncode == 0, proc.stderr
    assert "warning" in proc.stderr
    assert "nonsense" in proc.stderr
    assert (attempt_repo / "results/c001/test/1/solutions/x.json").is_file()


# --------------------------------------------------------------------------
# what the rest of the toolchain expects to find
# --------------------------------------------------------------------------


def test_collected_tree_is_readable_by_walk_results(attempt_repo: Path):
    """The downstream contract: stats.py walks results/ with this function."""
    import etudes_lib

    collect(attempt_repo)
    sessions = etudes_lib.walk_results(attempt_repo / "results")
    assert len(sessions) == 1
    session = sessions[0]
    assert session.cid == "c001"
    assert session.moves, "annotations.md did not parse into moves"
    errors = [m for m in session.lint if m.level == "error"]
    assert errors == []


def test_remote_tracking_branch_is_collected(
    tmp_git_repo: Path, tmp_path: Path
):
    """A fetched ``origin/attempt/...`` branch is collected like a local one."""
    git(tmp_git_repo, "tag", "-a", "c001-start", "-m", "start")
    add_attempt(tmp_git_repo, "attempt/c001/test/1")

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "--quiet", str(tmp_git_repo), str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(clone, "config", "user.name", "Etudes Test")
    git(clone, "config", "user.email", "etudes-test@example.invalid")

    proc = collect(clone)
    assert proc.returncode == 0, proc.stderr
    manifest = yaml.safe_load(
        (clone / "results/c001/test/1/manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["branch"] == "attempt/c001/test/1"
    assert manifest["taxonomy_version"] == "0.2"

    # once the same attempt exists locally, the local ref is the one collected
    git(clone, "checkout", "-b", "attempt/c001/test/1", "origin/attempt/c001/test/1")
    write(clone / "session" / "postmortem.md", "local edit\n")
    git(clone, "add", "-A")
    git(clone, "commit", "-m", "later thinking", at=T7)
    git(clone, "checkout", "main")

    proc = collect(clone)
    assert proc.returncode == 0, proc.stderr
    manifest = yaml.safe_load(
        (clone / "results/c001/test/1/manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["head_sha"] == git(
        clone, "rev-parse", "refs/heads/attempt/c001/test/1"
    ).strip()
    assert (clone / "results/c001/test/1/postmortem.md").read_text(
        encoding="utf-8"
    ) == "local edit\n"


# --------------------------------------------------------------------------
# unit level: the private glob translator and the path chooser
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def collector():
    return load_tool(COLLECTOR, "scripts_collect_results")


@pytest.mark.parametrize(
    "path, expected",
    [
        ("solutions/a.json", True),
        ("solutions/hidden/b.json", True),
        ("solutions/deep/deeper/c.json", True),
        ("solutions/a.svg", False),
        ("solver/a.json", False),
        ("a.json", False),
    ],
)
def test_glob_translation(collector, path: str, expected: bool):
    matcher = collector._glob_to_re("solutions/**/*.json")
    assert bool(matcher.match(path)) is expected


def test_choose_paths_picks_sessions_solutions_and_siblings(collector):
    tree = [
        "session/annotations.md",
        "session/decisions/dr-001.md",
        "reviews/bob.annotations.md",
        "solutions/x.json",
        "solutions/x.svg",
        "solutions/README.md",
        "solver/main.py",
        "README.md",
    ]
    chosen = collector.choose_paths(tree, "solutions/**/*.json")
    assert chosen == [
        "reviews/bob.annotations.md",
        "session/annotations.md",
        "session/decisions/dr-001.md",
        "solutions/x.json",
        "solutions/x.svg",
    ]


def test_solver_code_is_never_copied_however_loose_the_glob(collector):
    """A challenge manifest cannot talk the collector into copying solver/."""
    tree = [
        "session/annotations.md",
        "solver/candidate.json",
        "solver/deep/other.json",
        "out/a.json",
    ]
    assert collector.choose_paths(tree, "**/*.json") == [
        "out/a.json",
        "session/annotations.md",
    ]


def test_strip_ref_prefix(collector):
    assert (
        collector._strip_ref_prefix("refs/heads/attempt/c001/a/1", "origin")
        == "attempt/c001/a/1"
    )
    assert (
        collector._strip_ref_prefix("refs/remotes/origin/attempt/c001/a/1", "origin")
        == "attempt/c001/a/1"
    )
    assert (
        collector._strip_ref_prefix("refs/remotes/upstream/attempt/c001/a/1", "origin")
        == "attempt/c001/a/1"
    )
