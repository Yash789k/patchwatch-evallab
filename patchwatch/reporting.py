import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from patchwatch.models import Run


def write_bundle(directory: Path, run: Run) -> None:
    from patchwatch.evaluation import grade_run

    (directory / "task.json").write_text(
        json.dumps(
            {
                "dependency": run.plan.dependency,
                "from": run.plan.from_version,
                "target": run.plan.target,
                "plan_id": run.plan.id,
            },
            indent=2,
        )
        + "\n"
    )
    (directory / "run.json").write_text(run.model_dump_json(indent=2) + "\n")
    (directory / "policy-report.json").write_text(run.policy.model_dump_json(indent=2) + "\n")
    (directory / "risk-report.json").write_text(
        json.dumps(
            {
                "level": run.plan.risk,
                "reason": run.reason,
                "guide": run.plan.guide,
                "limitations": [
                    "Only curated syntax patterns are repaired.",
                    "Passing tests are evidence, not proof of semantic equivalence.",
                    "Dependency download needs PyPI access; execution checks have no network.",
                    "Review and apply the patch manually; no automatic merge or publishing.",
                ],
            },
            indent=2,
        )
        + "\n"
    )
    grades = grade_run(run, directory)
    (directory / "eval-results.json").write_text(
        json.dumps(
            {
                "passed": all(g.passed for g in grades),
                "score": sum(g.passed for g in grades) / len(grades),
                "grades": [g.model_dump() for g in grades],
            },
            indent=2,
        )
        + "\n"
    )
    summary = [
        f"# PatchWatch review: {run.plan.repository.name}",
        "",
        f"**Status: {run.status.upper()}**",
        "",
        run.reason,
        "",
        f"Upgrade: `{run.plan.dependency}` `{run.plan.from_version}` → `{run.plan.target}`",
        f"Risk: {run.plan.risk}. Engine: {run.engine}. Model cost: $0.",
        f"Original repository unchanged: {run.original_unchanged}.",
        "",
        "## Changed files",
        "",
    ]
    summary += [f"- `{name}`" for name in run.policy.changed_files] or ["No files changed."]
    summary += [
        "",
        "## Verification",
        "",
        "| Phase | Check | Result | Seconds |",
        "|---|---|---|---|",
    ]
    summary += [
        f"| {c.phase} | {c.name} | {'PASS' if c.passed else 'FAIL'} | {c.duration_seconds:.1f} |"
        for c in run.checks
    ]
    summary += [
        "",
        "## Reviewer checklist",
        "",
        "- Read patch.diff and the before/after logs.",
        "- Check behavior that the repository's tests do not cover.",
        "- Review transitive dependency changes in dependency-resolution.json.",
        "- Confirm the target version and deployment compatibility.",
        "- Apply manually to the matching source revision; run your own full CI.",
        "",
        "## Limits",
        "",
        "This run uses curated deterministic recipes, not a general-purpose LLM. Existing lockfiles, unsupported major migrations, source distributions, custom package indexes, and ambiguous APIs escalate. Tests and repository text are untrusted. Docker reduces risk but is not a virtual-machine boundary for actively hostile code.",
    ]
    (directory / "run-summary.md").write_text("\n".join(summary) + "\n")
    build_dashboard(directory, directory / "index.html")
    refresh_checksums(directory)


def refresh_checksums(directory: Path) -> None:
    checksums = {
        p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file() and p.name != "checksums.json"
    }
    (directory / "checksums.json").write_text(json.dumps(checksums, indent=2) + "\n")


def dashboard_data(directory: Path) -> dict[str, Any]:
    run_files = (
        [directory / "run.json"]
        if (directory / "run.json").exists()
        else sorted(directory.glob("*/run.json"))
    )
    runs = []
    for path in run_files:
        run = json.loads(path.read_text())
        # Portable reports omit host paths.
        run["plan"]["repository"]["root"] = run["plan"]["repository"]["name"]
        run["patch"] = (path.parent / "patch.diff").read_text()
        events = [
            json.loads(line) for line in (path.parent / "trace.jsonl").read_text().splitlines()
        ]
        for event in events:
            if isinstance(event.get("arguments"), dict) and "path" in event["arguments"]:
                event["arguments"]["path"] = Path(event["arguments"]["path"]).name
            result = event.get("result", {}).get("data")
            if isinstance(result, dict) and "root" in result:
                result["root"] = Path(result["root"]).name
        run["trace"] = events
        run["evaluation"] = json.loads((path.parent / "eval-results.json").read_text())
        runs.append(run)
    metrics = (
        json.loads((directory / "evaluation.json").read_text()).get("metrics")
        if (directory / "evaluation.json").exists()
        else None
    )
    return {"schema_version": 1, "runs": runs, "metrics": metrics}


def build_dashboard(directory: Path, destination: Path) -> None:
    template = files("patchwatch").joinpath("assets/viewer.html").read_text()
    payload = (
        json.dumps(dashboard_data(directory), ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(template.replace("__PATCHWATCH_DATA__", payload))
