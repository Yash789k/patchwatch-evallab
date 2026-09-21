"""Explicit state machine. Every mutation is limited to a disposable workspace."""

import json
import tempfile
import time
import uuid
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from patchwatch.errors import PatchwatchError
from patchwatch.migrations import migrate
from patchwatch.models import Check, Plan, PolicyReport, Run, RunStatus, ToolArgs
from patchwatch.planning import make_plan
from patchwatch.policy import diff_snapshots, validate_patch
from patchwatch.repository import (
    fingerprint,
    inspect_repository,
    manifest_requirements,
    protected,
    safe_path,
    snapshot,
    update_manifest,
)
from patchwatch.sandbox import CHECKS, DockerSandbox
from patchwatch.trace import Trace


def execute(plan: Plan, output: Path, approved: bool = False) -> Run:
    started = time.monotonic()
    started_at = datetime.now(UTC).isoformat()
    root = Path(plan.repository.root).resolve()
    output = output.resolve()
    if output.is_relative_to(root):
        raise PatchwatchError(
            "OUTPUT_BOUNDARY", "Evidence output must be outside the source repository."
        )
    output.mkdir(parents=True, exist_ok=False)
    trace = Trace(output / "trace.jsonl", plan.policy)
    checks: list[Check] = []
    before: dict[str, bytes] = {}
    after: dict[str, bytes] = {}
    policy_report = PolicyReport(passed=True, changed_files=[], changed_lines=0, violations=[])
    status: RunStatus = "escalated"
    reason = ""
    repairs = 0
    failures = 0
    original_unchanged = True
    sandbox = DockerSandbox(plan.policy.command_timeout, started + plan.policy.max_seconds)
    resolved: dict[str, str] = {}
    run_id = output.name
    (output / "plan.json").write_text(plan.model_dump_json(indent=2) + "\n")

    def state(name: str) -> None:
        trace.emit("state", state=name)

    def record(check: Check) -> Check:
        nonlocal failures
        checks.append(check)
        failures += int(not check.passed)
        trace.emit(
            "verification",
            name=check.name,
            phase=check.phase,
            passed=check.passed,
            exit_code=check.exit_code,
            sandbox="docker",
        )
        logs = output / "tool-results"
        logs.mkdir(exist_ok=True)
        (logs / f"{check.phase}-{check.name}.log").write_text(check.log)
        if check.exit_code in {124, 125, 126, 127, 137}:
            raise PatchwatchError(
                "SANDBOX_EXECUTION",
                f"Docker {check.phase}/{check.name} failed to execute or exceeded resources. See its log.",
            )
        if failures > plan.policy.max_command_failures:
            raise PatchwatchError("FAILURE_BUDGET", "Command failure budget exhausted.")
        return check

    def check_all(workspace: Path, phase: str) -> bool:
        outcomes = []
        for name in CHECKS:
            result = trace.call(
                "run_check",
                ToolArgs(check=name, phase=phase),
                partial(sandbox.check, workspace, name, phase),
            )
            outcomes.append(record(result).passed)
        return all(outcomes)

    try:
        state("inspecting")
        repo = trace.call(
            "scan_repository", ToolArgs(path=str(root)), lambda: inspect_repository(root)
        )
        if repo.fingerprint != plan.repository.fingerprint:
            raise PatchwatchError(
                "STALE_PLAN", "Repository changed after planning. Generate and approve a new plan."
            )
        if make_plan(repo, plan.dependency, plan.target, plan.policy) != plan:
            raise PatchwatchError(
                "PLAN_TAMPERED",
                "Plan metadata no longer matches a fresh inspection. Generate a new plan.",
            )
        before = snapshot(root)
        after = dict(before)
        trace.call(
            "get_dependency_manifest",
            ToolArgs(path=repo.manifest),
            lambda: [d.model_dump() for d in repo.dependencies],
        )
        state("planning")
        if plan.guide:
            trace.call(
                "get_migration_guide",
                ToolArgs(dependency=plan.dependency),
                lambda: {
                    "url": plan.guide,
                    "source": "bundled-curated-rules",
                    "engine": "curated-rules-v1",
                },
            )
        if not approved:
            status, reason = (
                "approval_required",
                "Approval required. Review plan.json and rerun with --approve-plan.",
            )
            trace.emit("policy", decision="pause", code="APPROVAL_REQUIRED")
        else:
            trace.emit("approval", approved=True, plan_id=plan.id, fingerprint=repo.fingerprint)
            if not plan.supported:
                raise PatchwatchError("UNSUPPORTED_MIGRATION", plan.reason)
            sandbox.available()
            state("create_workspace")
            with tempfile.TemporaryDirectory(prefix="patchwatch-") as tmp:
                workspace = Path(tmp)
                workspace.chmod(
                    0o755
                )  # Non-root Docker UID must traverse the read-only bind on Linux.

                def copy() -> dict[str, int]:
                    for name, data in before.items():
                        destination = safe_path(workspace, name)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(data)
                        destination.chmod(0o644)
                    return {"files": len(before)}

                trace.call("create_workspace_copy", ToolArgs(), copy)
                state("baseline_checks")
                _, requirements, _ = manifest_requirements(before)
                result = trace.call(
                    "run_check",
                    ToolArgs(check="install", phase="before"),
                    lambda: sandbox.install(requirements, "before"),
                )
                if not record(result).passed:
                    raise PatchwatchError(
                        "BASELINE_INSTALL",
                        "Baseline dependencies could not be installed; see before-install.log.",
                    )
                baseline_inventory = dict(sandbox.inventory)
                if not check_all(workspace, "before"):
                    raise PatchwatchError(
                        "PREEXISTING_FAILURE",
                        "Pre-existing verification failure. Fix the baseline before upgrading.",
                    )
                state("apply_upgrade")

                def update() -> dict[str, str]:
                    path = safe_path(workspace, repo.manifest)
                    new = update_manifest(
                        path.read_bytes(), repo.manifest, plan.dependency, plan.target
                    )
                    path.write_bytes(new)
                    return {"manifest": repo.manifest, "target": plan.target}

                trace.call(
                    "update_dependency",
                    ToolArgs(dependency=plan.dependency, target=plan.target),
                    update,
                )
                after = snapshot(workspace)
                _, target_requirements, _ = manifest_requirements(after)
                result = trace.call(
                    "run_check",
                    ToolArgs(check="install", phase="after"),
                    lambda: sandbox.install(target_requirements, "after"),
                )
                if not record(result).passed:
                    raise PatchwatchError(
                        "DEPENDENCY_CONFLICT",
                        "Target dependency installation failed; resolve dependency constraints manually.",
                    )
                resolved = dict(sandbox.inventory)
                if resolved.get(plan.dependency) != plan.target:
                    raise PatchwatchError(
                        "DEPENDENCY_MISMATCH",
                        "Installed target version does not match the approved plan.",
                    )
                (output / "dependency-resolution.json").write_text(
                    json.dumps({"before": baseline_inventory, "after": resolved}, indent=2) + "\n"
                )
                state("run_checks")
                passed = check_all(workspace, "after")
                # Supported major migrations also remove deprecated APIs when tests still pass.
                needs_migration = plan.risk == "high" and plan.dependency in {
                    "pydantic",
                    "sqlalchemy",
                }
                while (not passed or needs_migration) and repairs < plan.policy.max_repairs:
                    state("diagnose_failure")
                    if plan.risk != "high" or plan.dependency not in {"pydantic", "sqlalchemy"}:
                        break
                    needs_migration = False
                    state("repair")

                    def repair(current: dict[str, bytes] = after) -> dict[str, str]:
                        candidates = {}
                        for name in repo.source_files:
                            if protected(name):
                                continue
                            old = safe_path(workspace, name).read_text()
                            new = migrate(old, plan.dependency)
                            if old != new:
                                candidates[name] = new
                        proposed = dict(current)
                        proposed.update({n: t.encode() for n, t in candidates.items()})
                        report = validate_patch(before, proposed, repo.manifest, plan.policy)
                        if not report.passed:
                            raise PatchwatchError("POLICY_VIOLATION", "; ".join(report.violations))
                        for name, new in candidates.items():
                            safe_path(workspace, name).write_text(new)
                        return {name: "curated migration" for name in candidates}

                    changes = trace.call(
                        "repair_source", ToolArgs(dependency=plan.dependency), repair
                    )
                    if not changes:
                        break
                    repairs += 1
                    formatted = trace.call(
                        "format_source",
                        ToolArgs(),
                        partial(sandbox.format_source, workspace, list(changes)),
                    )
                    for name, content in formatted.items():
                        safe_path(workspace, name).write_text(content)
                    after = snapshot(workspace)
                    state("run_checks")
                    passed = check_all(workspace, f"repair-{repairs}")
                after = snapshot(workspace)
                if not passed:
                    raise PatchwatchError(
                        "UNRESOLVED_CHECKS",
                        "Target checks failed; no supported repair remains. Review logs and keep tests unchanged.",
                    )
                baseline_test = next(c for c in checks if c.name == "test" and c.phase == "before")
                final_test = [c for c in checks if c.name == "test"][-1]
                if (final_test.tests_passed or 0) < (baseline_test.tests_passed or 0) or (
                    final_test.tests_skipped or 0
                ) > (baseline_test.tests_skipped or 0):
                    raise PatchwatchError(
                        "TEST_COVERAGE_REDUCED",
                        "The upgrade reduced passing test coverage or introduced skips.",
                    )
                state("validate_patch")
                policy_report = trace.call(
                    "validate_patch",
                    ToolArgs(),
                    lambda: validate_patch(before, after, repo.manifest, plan.policy),
                )
                if not policy_report.passed:
                    raise PatchwatchError("POLICY_VIOLATION", "; ".join(policy_report.violations))
                if fingerprint(snapshot(root)) != repo.fingerprint:
                    raise PatchwatchError(
                        "SOURCE_CHANGED",
                        "Original repository changed during execution; regenerate the plan.",
                    )
                if time.monotonic() - started > plan.policy.max_seconds:
                    raise PatchwatchError("TIME_BUDGET", "Run exceeded its wall-clock budget.")
                status, reason = (
                    "review_ready",
                    "All mandatory checks passed in Docker and the patch passed policy validation. Human code review is still required.",
                )
    except PatchwatchError as exc:
        status, reason = "escalated", f"{exc.code}: {exc}"
        trace.emit(
            "escalation",
            code=exc.code,
            reason=str(exc),
            next_step="Review the evidence, resolve the stated limitation, then generate a new plan.",
        )
    except (OSError, ValueError, RuntimeError) as exc:
        status, reason = "failed", f"INFRASTRUCTURE_ERROR: {type(exc).__name__}: {exc}"
        trace.emit("failure", code="INFRASTRUCTURE_ERROR", reason=reason)
    finally:
        sandbox.close()
    # Validate failed/escalated patches too. No claim of success can bypass this gate.
    policy_report = validate_patch(before, after, plan.repository.manifest, plan.policy)
    trace.emit(
        "policy",
        decision="allow" if policy_report.passed else "block",
        report=policy_report.model_dump(),
    )
    try:
        original_unchanged = fingerprint(snapshot(root)) == plan.repository.fingerprint
    except (OSError, PatchwatchError):
        original_unchanged = False
    if not original_unchanged and status == "review_ready":
        status, reason = "escalated", "SOURCE_CHANGED: Original repository changed during the run."
    diff = diff_snapshots(before, after)
    trace.emit("artifact", name="patch.diff", characters=len(diff))
    (output / "patch.diff").write_text(diff)
    run = Run(
        id=run_id,
        plan=plan,
        status=status,
        reason=reason,
        started_at=started_at,
        duration_seconds=round(time.monotonic() - started, 3),
        repairs=repairs,
        checks=checks,
        policy=policy_report,
        tool_calls=trace.count,
        original_unchanged=original_unchanged,
        resolved_dependencies=resolved,
    )
    state(status)
    from patchwatch.reporting import write_bundle

    write_bundle(output, run)
    return run


def new_run_directory(output_root: Path) -> Path:
    return output_root / (datetime.now(UTC).strftime("run-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
