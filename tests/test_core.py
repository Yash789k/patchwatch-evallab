import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from patchwatch.cli import app
from patchwatch.errors import PatchwatchError
from patchwatch.evaluation import compare
from patchwatch.migrations import pydantic_v2, sqlalchemy_v2
from patchwatch.models import Policy, ToolArgs
from patchwatch.planning import make_plan
from patchwatch.policy import diff_snapshots, validate_patch
from patchwatch.repository import inspect_repository, safe_path, snapshot, update_manifest
from patchwatch.runner import execute
from patchwatch.trace import Trace, verify_trace

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def repo(tmp_path, dependencies='["requests==2.32.2"]'):
    path = tmp_path / "repository"
    path.mkdir()
    (path / "pyproject.toml").write_text(
        '[project]\nname="example"\nversion="1"\ndependencies=' + dependencies + "\n"
    )
    (path / "app.py").write_text("def answer():\n    return 42\n")
    (path / "tests").mkdir()
    (path / "tests/test_app.py").write_text("def test_answer():\n    assert True\n")
    return path


def test_inspection_never_imports_repository(tmp_path):
    path = repo(tmp_path)
    (path / "setup.py").write_text('raise RuntimeError("MUST NOT EXECUTE")')
    summary = inspect_repository(path)
    assert summary.dependencies[0].pinned_version == "2.32.2"
    assert summary.test_files == ["tests/test_app.py"]


@pytest.mark.parametrize("relative", ["../outside", "/tmp/secret", "a/../../outside"])
def test_boundary_blocks_escape(tmp_path, relative):
    with pytest.raises(PatchwatchError, match="outside"):
        safe_path(tmp_path, relative)


def test_symlink_rejected_and_secrets_omitted(tmp_path):
    path = repo(tmp_path)
    (path / ".env").write_text("PRIVATE_KEY=do-not-copy")
    assert ".env" not in snapshot(path)
    (path / "linked.py").symlink_to(tmp_path / "outside")
    with pytest.raises(PatchwatchError):
        snapshot(path)


@pytest.mark.parametrize(
    "dependency", ['"name @ https://example.com/p.whl"', '"git+https://example.com/repo"']
)
def test_dependency_urls_cannot_reach_downloader(tmp_path, dependency):
    with pytest.raises(PatchwatchError):
        inspect_repository(repo(tmp_path, "[" + dependency + "]"))


def test_requirements_includes_blocked(tmp_path):
    (tmp_path / "requirements.txt").write_text("-r /etc/passwd\n")
    with pytest.raises(PatchwatchError, match="Includes"):
        inspect_repository(tmp_path)


def test_manifest_update_preserves_other_dependencies_and_configuration():
    content = b'[project]\ndependencies=["requests[socks]==2.32.2; python_version >= \'3.12\'", "idna==3.10"]\n[tool.pytest.ini_options]\naddopts="--strict-markers"\n'
    updated = update_manifest(content, "pyproject.toml", "requests", "2.32.3").decode()
    assert "requests[socks]==2.32.3" in updated
    assert "idna==3.10" in updated
    assert 'addopts="--strict-markers"' in updated
    assert "python_version" in updated


def test_requirements_update_keeps_comments():
    content = b"# dependencies\nrequests==2.32.2  # pinned\nidna==3.10\n"
    result = update_manifest(content, "requirements.txt", "requests", "2.32.3")
    assert result == b"# dependencies\nrequests==2.32.3  # pinned\nidna==3.10\n"


@pytest.mark.parametrize(
    "path,content",
    [
        ("tests/test_api.py", b"assert True"),
        (".github/workflows/ci.yml", b"on: []"),
        ("app.py", b"x = 1  # type: ignore"),
        ("app.py", b'pytest.mark.skip(reason="migration")'),
    ],
)
def test_policy_blocks_test_ci_and_suppression_changes(path, content):
    report = validate_patch({path: b"original\n"}, {path: content}, "pyproject.toml", Policy())
    assert not report.passed


def test_budget_rejects_large_patch():
    report = validate_patch(
        {"app.py": b"old\n"},
        {"app.py": b"a\nb\nc\n"},
        "pyproject.toml",
        Policy(max_changed_lines=2),
    )
    assert not report.passed
    assert "Changed-line budget exceeded" in report.violations


def test_pydantic_transform_is_targeted_and_preserves_unrelated_code():
    text = (FIXTURES / "pydantic-v1-basic/app.py").read_text()
    text += '\n\nclass Other:\n    def dict(self):\n        return {"name": "é"}\n'
    updated = pydantic_v2(text)
    assert "@field_validator" in updated and "@classmethod" in updated
    assert "model_config = ConfigDict(from_attributes=True)" in updated
    assert "self.model_dump()" in updated
    assert "def dict(self):" in updated and '"é"' in updated
    assert pydantic_v2(updated) == updated


def test_pydantic_unsupported_options_escalate():
    with pytest.raises(PatchwatchError, match="each_item"):
        pydantic_v2((FIXTURES / "ambiguous-migration/app.py").read_text())


def test_config_unknown_semantics_escalate():
    with pytest.raises(PatchwatchError, match="Config option"):
        pydantic_v2(
            "from pydantic import BaseModel\nclass User(BaseModel):\n    class Config:\n        allow_mutation = False\n"
        )


def test_sql_migration_does_not_change_untyped_execute():
    original = 'from sqlalchemy.engine import Connection\n\ndef run(c: Connection):\n    return c.execute("select 1")\n\ndef other(c):\n    return c.execute("arbitrary")\n'
    updated = sqlalchemy_v2(original)
    assert "c.execute(text(" in updated
    assert 'c.execute("arbitrary")' in updated
    assert sqlalchemy_v2(updated) == updated


def test_unpinned_and_existing_lockfiles_escalate(tmp_path):
    path = repo(tmp_path, '["requests>=2"]')
    assert not make_plan(inspect_repository(path), "requests", "2.32.3").supported
    (path / "pyproject.toml").write_text('[project]\ndependencies=["requests==2.32.2"]')
    (path / "uv.lock").write_text("version=1")
    plan = make_plan(inspect_repository(path), "requests", "2.32.3")
    assert not plan.supported and "lockfile" in plan.reason


@pytest.mark.parametrize(
    "target", ["2.32.2", "1.0.0", "2.33.0rc1", "not-a-version", "2.33+private"]
)
def test_invalid_or_non_upgrade_target_is_rejected(tmp_path, target):
    summary = inspect_repository(repo(tmp_path))
    try:
        assert not make_plan(summary, "requests", target).supported
    except PatchwatchError:
        pass


def test_stale_plan_stops_before_docker_or_writes(tmp_path):
    path = repo(tmp_path)
    plan = make_plan(inspect_repository(path), "requests", "2.32.3")
    (path / "app.py").write_text("changed after approval\n")
    run = execute(plan, tmp_path / "evidence", approved=True)
    assert run.status == "escalated" and "STALE_PLAN" in run.reason
    assert not run.checks and not run.policy.changed_files


def test_no_approval_produces_report_without_execution(tmp_path):
    path = repo(tmp_path)
    original = snapshot(path)
    run = execute(make_plan(inspect_repository(path), "requests", "2.32.3"), tmp_path / "evidence")
    assert run.status == "approval_required"
    assert not run.checks and snapshot(path) == original
    assert (tmp_path / "evidence/index.html").is_file()
    result = CliRunner().invoke(app, ["verify", str(tmp_path / "evidence")])
    assert result.exit_code == 0, result.output


def test_trace_detects_editing_and_forbidden_tools(tmp_path):
    path = tmp_path / "trace.jsonl"
    trace = Trace(path, Policy())
    assert trace.call("scan_repository", ToolArgs(), lambda: {"ok": True}) == {"ok": True}
    with pytest.raises(PatchwatchError, match="not allowed"):
        trace.call("unsafe_shell", ToolArgs(), lambda: None)
    assert verify_trace(path)
    path.write_text(path.read_text().replace("scan_repository", "unsafe_shell"))
    assert not verify_trace(path)


def test_tool_arguments_reject_extra_parameters():
    with pytest.raises(ValidationError):
        ToolArgs.model_validate({"shell": "arbitrary command"})


def test_trace_budget_is_enforced(tmp_path):
    trace = Trace(tmp_path / "trace.jsonl", Policy(max_tool_calls=8))
    for _ in range(8):
        trace.call("scan_repository", ToolArgs(), lambda: None)
    with pytest.raises(PatchwatchError, match="budget"):
        trace.call("scan_repository", ToolArgs(), lambda: None)


def test_regression_gate_rejects_missing_tasks_and_false_success():
    baseline = {
        "tasks": [{"id": "a", "passed": True, "expected_status": "review_ready"}],
        "metrics": {"false_success_rate": 0, "test_edit_violation_rate": 0},
    }
    missing = {"tasks": [], "metrics": {"false_success_rate": 0, "test_edit_violation_rate": 0}}
    assert compare(baseline, missing)
    candidate = json.loads(json.dumps(baseline))
    candidate["metrics"]["false_success_rate"] = 0.1
    assert compare(baseline, candidate)
    assert not compare(baseline, baseline)


def test_regression_cli_accepts_documented_options(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "tasks": [{"id": "a", "passed": True, "expected_status": "review_ready"}],
                "metrics": {"false_success_rate": 0, "test_edit_violation_rate": 0},
            }
        )
    )
    result = CliRunner().invoke(
        app, ["eval", "compare", "--baseline", str(baseline), "--candidate", str(baseline)]
    )
    assert result.exit_code == 0, result.output
    assert "No evaluation regression" in result.output


def test_unified_diff_handles_no_final_newline():
    diff = diff_snapshots({"app.py": b"a"}, {"app.py": b"b"})
    assert "\\ No newline at end of file" in diff
    assert "-a\n" in diff and "+b\n" in diff


def test_report_escapes_script_in_untrusted_content(tmp_path):
    path = repo(tmp_path)
    run = execute(make_plan(inspect_repository(path), "requests", "2.32.3"), tmp_path / "evidence")
    report = tmp_path / "evidence/run.json"
    run.reason = '</script><script>alert("unsafe")</script>'
    report.write_text(run.model_dump_json())
    from patchwatch.reporting import build_dashboard

    build_dashboard(report.parent, report.parent / "index.html")
    html = (report.parent / "index.html").read_text()
    assert "</script><script>alert" not in html
    assert "\\u003c/script" in html


def test_cli_machine_readable_inspection():
    result = CliRunner().invoke(app, ["inspect", str(FIXTURES / "requests-patch"), "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["manifest"] == "requirements.txt"


def test_report_regeneration_preserves_other_integrity_evidence(tmp_path):
    path = repo(tmp_path)
    evidence = tmp_path / "evidence"
    execute(make_plan(inspect_repository(path), "requests", "2.32.3"), evidence)
    (evidence / "index.html").write_text("old viewer")
    runner = CliRunner()
    assert runner.invoke(app, ["report", str(evidence)]).exit_code == 0
    assert runner.invoke(app, ["verify", str(evidence)]).exit_code == 0
    (evidence / "patch.diff").write_text("tampered evidence")
    assert runner.invoke(app, ["report", str(evidence)]).exit_code == 0
    assert runner.invoke(app, ["verify", str(evidence)]).exit_code == 1


def test_manifest_cannot_weaken_checks_or_upgrade_two_dependencies():
    before = {
        "pyproject.toml": b'[project]\ndependencies=["requests==2.32.2", "idna==3.9"]\n[tool.pytest.ini_options]\naddopts="--strict-markers"\n'
    }
    after = {
        "pyproject.toml": before["pyproject.toml"]
        .replace(b"--strict-markers", b"--ignore=tests")
        .replace(b"2.32.2", b"2.32.3")
    }
    assert not validate_patch(before, after, "pyproject.toml", Policy()).passed
    after = {
        "pyproject.toml": before["pyproject.toml"]
        .replace(b"2.32.2", b"2.32.3")
        .replace(b"3.9", b"3.10")
    }
    assert not validate_patch(before, after, "pyproject.toml", Policy()).passed


def test_python_version_outside_sandbox_escalates(tmp_path):
    path = repo(tmp_path)
    with (path / "pyproject.toml").open("a") as f:
        f.write('requires-python=">=3.13"\n')
    result = make_plan(inspect_repository(path), "requests", "2.32.3")
    assert not result.supported and "Python" in result.reason


def test_tampered_plan_cannot_bypass_runtime_eligibility(tmp_path):
    path = repo(tmp_path)
    plan = make_plan(inspect_repository(path), "requests", "2.32.3")
    plan.repository.dependencies[0].pinned_version = "2.32.1"
    run = execute(plan, tmp_path / "evidence", approved=True)
    assert run.status == "escalated"
    assert "PLAN_TAMPERED" in run.reason
    assert not run.checks
