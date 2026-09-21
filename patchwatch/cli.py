"""CLI entrypoints: execution failures are machine-readable and never hidden."""

import json
import subprocess
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from patchwatch.errors import PatchwatchError
from patchwatch.models import Plan
from patchwatch.planning import make_plan
from patchwatch.repository import inspect_repository
from patchwatch.runner import execute, new_run_directory

app = typer.Typer(
    help="Verified dependency upgrades. No paid API. No automatic merge.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
eval_app = typer.Typer(
    help="Execute and compare the EvalLab benchmark.", invoke_without_command=True
)
app.add_typer(eval_app, name="eval")
console = Console()


def fail(exc: Exception) -> None:
    console.print(f"[red]{getattr(exc, 'code', 'ERROR')}[/red]: {exc}", markup=False)
    raise typer.Exit(1)


def display_run(run: Any, directory: Path) -> None:
    console.print(f"{run.status.upper()}: {run.reason}", markup=False)
    console.print(f"Evidence: {directory.resolve()}", markup=False)
    console.print(f"Review viewer: {(directory / 'index.html').resolve()}", markup=False)


@app.command()
def inspect(repo: Path, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Read manifest, source inventory, test inventory, and repository fingerprint."""
    try:
        result = inspect_repository(repo)
    except (PatchwatchError, OSError, ValueError) as exc:
        fail(exc)
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return
    console.print(f"PatchWatch · {result.name}", markup=False)
    table = Table("Dependency", "Declared constraint", "Pinned version")
    for dep in result.dependencies:
        table.add_row(dep.name, dep.requirement, dep.pinned_version or "unresolved")
    console.print(table)
    console.print(
        f"{len(result.source_files)} source files · {len(result.test_files)} test files · {result.manifest}",
        markup=False,
    )
    for warning in result.warnings:
        console.print(warning, markup=False)


@app.command()
def scan(repo: Path, online: bool = False) -> None:
    """Inspect locally; optionally query PyPI for stable versions of curated packages."""
    try:
        summary = inspect_repository(repo)
        if not online:
            inspect(repo)
            return
        from patchwatch.monitor import scan_updates

        typer.echo(json.dumps(scan_updates(summary), indent=2))
    except (PatchwatchError, OSError, ValueError) as exc:
        fail(exc)


@app.command()
def plan(repo: Path, dependency: str, target: str, output: Path | None = None) -> None:
    """Generate a fingerprint-bound approval plan without modifying the repository."""
    try:
        result = make_plan(inspect_repository(repo), dependency, target)
        if output:
            if output.resolve().is_relative_to(repo.resolve()):
                raise PatchwatchError(
                    "OUTPUT_BOUNDARY",
                    "Save the plan outside the repository to preserve its fingerprint.",
                )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(result.model_dump_json(indent=2) + "\n")
        typer.echo(result.model_dump_json(indent=2))
    except (PatchwatchError, OSError, ValueError) as exc:
        fail(exc)


@app.command()
def apply(
    repo: Path,
    dependency: str | None = None,
    target: str | None = None,
    plan_file: Annotated[Path | None, typer.Option("--plan")] = None,
    approve_plan: bool = False,
    output: Path = Path("runs"),
) -> None:
    """Execute an approved plan in Docker and emit a review bundle (source stays unchanged)."""
    try:
        if plan_file:
            requested = Plan.model_validate_json(plan_file.read_text())
            if Path(requested.repository.root).resolve() != repo.resolve():
                raise PatchwatchError("PLAN_REPOSITORY", "Plan belongs to a different repository.")
            if (
                dependency
                and dependency != requested.dependency
                or target
                and target != requested.target
            ):
                raise PatchwatchError(
                    "PLAN_MISMATCH", "CLI target/dependency differs from approved plan."
                )
            # Never trust edited plan claims: recompute eligibility from its captured repository.
            recomputed = make_plan(
                requested.repository, requested.dependency, requested.target, requested.policy
            )
            if recomputed != requested:
                raise PatchwatchError(
                    "PLAN_TAMPERED", "Plan fields were modified. Generate a new plan."
                )
        else:
            if not dependency or not target:
                raise PatchwatchError(
                    "TARGET_REQUIRED", "Supply --dependency and --target, or --plan."
                )
            requested = make_plan(inspect_repository(repo), dependency, target)
        directory = new_run_directory(output)
        run = execute(requested, directory, approve_plan)
        display_run(run, directory)
        raise typer.Exit(
            0
            if run.status == "review_ready"
            else 2
            if run.status == "escalated"
            else 3
            if run.status == "approval_required"
            else 1
        )
    except (PatchwatchError, OSError, ValueError) as exc:
        fail(exc)


@app.command()
def setup() -> None:
    """Build the pinned Docker verification image from bundled trusted sources."""
    context = files("patchwatch").joinpath("assets")
    try:
        result = subprocess.run(
            ["docker", "build", "--load", "-t", "patchwatch-sandbox:1.0", str(context)], check=False
        )
        if result.returncode:
            raise typer.Exit(result.returncode)
        console.print("Sandbox ready. Run patchwatch demo.")
    except FileNotFoundError:
        fail(PatchwatchError("DOCKER_MISSING", "Install and start Docker first."))


@app.command()
def doctor() -> None:
    """Verify that Docker and the sandbox image are ready."""
    from patchwatch.sandbox import DockerSandbox

    try:
        DockerSandbox().available()
        console.print("Ready · Docker available · sandbox image found · no API key required")
    except PatchwatchError as exc:
        fail(exc)


@app.command()
def demo(output: Path = Path("runs")) -> None:
    """Run the Pydantic migration and prompt-injection-resistance demonstration."""
    root = Path(str(files("patchwatch")))
    fixture = root / "fixtures" / "malicious-readme"
    if not fixture.exists():
        fixture = root.parent / "fixtures" / "malicious-readme"
    apply(fixture, dependency="pydantic", target="2.9.2", approve_plan=True, output=output)


@app.command()
def show(run: Path) -> None:
    """Read a completed run's summary."""
    try:
        typer.echo((run / "run-summary.md").read_text())
    except OSError as exc:
        fail(exc)


@app.command()
def report(run: Path, output: Path | None = None) -> None:
    """Generate a portable interactive HTML evidence viewer."""
    from patchwatch.reporting import build_dashboard

    try:
        destination = output or run / "index.html"
        build_dashboard(run, destination)
        manifest = run / "checksums.json"
        if destination.resolve() == (run / "index.html").resolve() and manifest.is_file():
            import hashlib

            checksums = json.loads(manifest.read_text())
            # Update only the regenerated file; preserve evidence of other tampering.
            checksums["index.html"] = hashlib.sha256(destination.read_bytes()).hexdigest()
            manifest.write_text(json.dumps(checksums, indent=2) + "\n")
        console.print(str(destination.resolve()), markup=False)
    except (ValueError, OSError) as exc:
        fail(exc)


@app.command()
def verify(run: Path) -> None:
    """Verify evidence checksums and the trace hash chain."""
    import hashlib

    from patchwatch.trace import verify_trace

    try:
        expected = json.loads((run / "checksums.json").read_text())
        valid = bool(expected) and verify_trace(run / "trace.jsonl")
        for name, digest in expected.items():
            from patchwatch.repository import safe_path

            path = safe_path(run, name)
            valid = (
                valid and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
            )
        console.print(
            "Evidence integrity verified." if valid else "Evidence integrity check failed."
        )
        raise typer.Exit(0 if valid else 1)
    except (OSError, ValueError, PatchwatchError) as exc:
        fail(exc)


@eval_app.callback()
def eval_main(
    ctx: typer.Context,
    dataset: Path = Path("evallab/datasets/mvp_tasks.jsonl"),
    output: Path = Path("artifacts/eval"),
) -> None:
    if ctx.invoked_subcommand:
        return
    from patchwatch.evaluation import evaluate

    try:
        result = evaluate(dataset, output)
        typer.echo(json.dumps(result["metrics"], indent=2))
        raise typer.Exit(0 if all(t["passed"] for t in result["tasks"]) else 1)
    except (PatchwatchError, OSError, ValueError) as exc:
        fail(exc)


@eval_app.command("compare")
def compare_cmd(
    baseline: Annotated[Path, typer.Option(help="Previously measured evaluation JSON.")],
    candidate: Annotated[Path, typer.Option(help="New evaluation JSON to check.")],
) -> None:
    """Fail CI when scenarios disappear or regress, or unsafe success appears."""
    from patchwatch.evaluation import compare

    try:
        failures = compare(json.loads(baseline.read_text()), json.loads(candidate.read_text()))
        typer.echo("\n".join(failures) if failures else "No evaluation regression.")
        raise typer.Exit(1 if failures else 0)
    except (OSError, ValueError, KeyError) as exc:
        fail(exc)


if __name__ == "__main__":
    app()
