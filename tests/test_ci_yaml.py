"""CI wiring checks: ``.github/workflows/ci.yml`` parses and its required jobs exist.

It also pins the one place a contributor is told they can reproduce CI locally:
``make lint`` must invoke the linter with the same flags as the lint-annotations
job, or a green local run stops predicting a green check (D-012).
"""
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CI = REPO / ".github" / "workflows" / "ci.yml"
MAKEFILE = REPO / "Makefile"


def lint_flags(command: str) -> set[str]:
    """The ``--flags`` a lint_annotations.py invocation passes.

    Command substitutions are stripped first, so the ``--show-current`` inside
    ``$(git branch --show-current)`` is not mistaken for a linter flag.
    """
    assert "scripts/lint_annotations.py" in command, command
    return set(re.findall(r"--[a-z-]+", re.sub(r"\$+\([^)]*\)", "", command)))


def makefile_recipe(target: str) -> str:
    """The tab-indented recipe lines of one Makefile target, joined."""
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"{target}:") + 1
    body = []
    for line in lines[start:]:
        if not line.startswith("\t"):
            break
        body.append(line.strip())
    assert body, f"no recipe for the {target} target"
    return "\n".join(body)


def ci_lint_command() -> str:
    data = yaml.safe_load(CI.read_text())
    steps = data["jobs"]["lint-annotations"]["steps"]
    runs = [s.get("run", "") for s in steps if "scripts/lint_annotations.py" in s.get("run", "")]
    assert len(runs) == 1, runs
    return runs[0]


def load():
    data = yaml.safe_load(CI.read_text())
    # PyYAML parses the bare key `on` as boolean True.
    triggers = data.get("on", data.get(True))
    return data, triggers


def test_ci_parses_and_has_required_jobs():
    data, _ = load()
    jobs = data["jobs"]
    for name in ("secret-scan", "lint-annotations", "validate-solutions", "tests"):
        assert name in jobs, name


def test_ci_triggers():
    _, triggers = load()
    assert triggers["pull_request"]["branches"] == ["main"]
    push = triggers["push"]["branches"]
    assert "main" in push
    assert "attempt/**" in push


def test_ci_checkouts_use_full_history():
    data, _ = load()
    for name, job in data["jobs"].items():
        for step in job["steps"]:
            if str(step.get("uses", "")).startswith("actions/checkout"):
                assert step["with"]["fetch-depth"] == 0, f"{name}: checkout needs fetch-depth 0"


def test_ci_secret_scan_uses_gitleaks():
    data, _ = load()
    uses = [s.get("uses", "") for s in data["jobs"]["secret-scan"]["steps"]]
    assert any(u.startswith("gitleaks/gitleaks-action") for u in uses)


def test_ci_lint_runs_session_validation_with_branch_crosscheck():
    data, _ = load()
    runs = "\n".join(s.get("run", "") for s in data["jobs"]["lint-annotations"]["steps"])
    assert "scripts/lint_annotations.py" in runs
    assert "--session" in runs
    assert "--expect-branch" in runs


def test_ci_validate_solutions_takes_oracle_from_main():
    data, _ = load()
    job = data["jobs"]["validate-solutions"]
    assert "attempt/" in str(job["if"])
    runs = "\n".join(s.get("run", "") for s in job["steps"])
    assert "git archive origin/main challenges" in runs
    assert "scripts/validate_solutions.py" in runs
    assert "--challenge-root" in runs
    assert "GITHUB_STEP_SUMMARY" in runs


def test_ci_tests_job_runs_pytest_contract_and_words():
    data, _ = load()
    runs = "\n".join(s.get("run", "") for s in data["jobs"]["tests"]["steps"])
    assert "uv run pytest" in runs
    assert "scripts/check_challenge.py" in runs
    assert "scripts/check_words.sh" in runs


def test_ci_uses_uv_everywhere_python_runs():
    data, _ = load()
    for name in ("lint-annotations", "validate-solutions", "tests"):
        uses = [s.get("uses", "") for s in data["jobs"][name]["steps"]]
        assert any(u.startswith("astral-sh/setup-uv") for u in uses), name


def test_ci_validate_solutions_step_is_portable():
    """`xargs -a FILE` is a GNU extension: a maintainer on macOS must be able to
    reproduce the validate step by hand (D15)."""
    data, _ = load()
    runs = "\n".join(s.get("run", "") for s in data["jobs"]["validate-solutions"]["steps"])
    assert "xargs -a" not in runs
    assert "xargs " in runs
    assert "solution-files.txt" in runs


def test_make_lint_runs_the_same_flags_as_the_ci_lint_job():
    """CONTRIBUTING §3 tells participants a green ``make lint`` predicts a green CI
    check. That only holds while the two invocations carry the same flags -- the
    branch cross-check is what catches a session.yaml still saying
    ``participant: your-handle``, and the weaker forms pass it (D-012)."""
    recipe = makefile_recipe("lint")
    assert lint_flags(recipe) == lint_flags(ci_lint_command())


def test_make_lint_supplies_the_current_branch_to_expect_branch():
    """CI reads the branch from the environment; locally it has to come from git."""
    recipe = makefile_recipe("lint")
    assert "--expect-branch" in recipe
    # "$$" is how a Makefile recipe escapes a shell "$".
    assert "$$(git branch --show-current)" in recipe, recipe


def test_ci_header_describes_the_checks_that_can_be_required():
    """The header comment is the only statement of the branch-protection setup, and
    validate-solutions cannot be one of the required checks: it runs on attempt/**
    branches only, and those PRs are never merged (D5)."""
    header = "\n".join(
        line for line in CI.read_text().splitlines() if line.startswith("#")
    )
    assert "Branch protection" in header
    protection = header.split("Branch protection", 1)[1]
    # the required list is the sentence that starts at "require"
    assert "require " in protection, protection
    required = protection.split("require ", 1)[1].split(".")[0]
    assert "secret-scan" in required, required
    assert "lint-annotations" in required, required
    assert "validate-solutions" not in required, required
    # and it is named afterwards, to say where it does run instead
    assert "validate-solutions" in protection
    assert "attempt/**" in protection
