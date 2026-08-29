"""CI wiring checks (HANDOFF §10.5): the workflow parses and the required jobs exist."""
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CI = REPO / ".github" / "workflows" / "ci.yml"


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
