# Architecture and operating decisions

PatchWatch is a local controller with an explicit state machine. It plans and executes one dependency upgrade at a time. EvalLab independently evaluates the outcome and ordered evidence. The default engine is deterministic: no model API, API key, token charges, external database, or background service.

## Execution flow

1. Parse PEP 621 `project.dependencies` or a plain `requirements.txt` without importing repository code.
2. Normalize package names, reject URL/VCS/local dependencies, identify source/tests, and hash the sanitized repository.
3. Build a versioned Pydantic plan bound to that fingerprint. Require an explicit approval flag.
4. Copy only regular, bounded files into a temporary controller workspace. Exclude VCS state, virtual environments, and common secret files; reject symlinks and special files.
5. Resolve wheels in a networked Docker container **without a repository mount**. Install them offline into a new named volume. Record the installed inventory.
6. Run baseline test, lint, formatting, and type checks in separate containers. Every check gets its own disposable copy. The controller's workspace and dependency volume are read-only mounts.
7. Change one requested direct dependency. Resolve its environment and run the same checks. Pydantic and SQLAlchemy major migrations may apply narrow syntax-aware repairs, followed by all checks again.
8. Enforce file/line/tool/time/failure budgets and protected paths. Recheck the original repository fingerprint. Emit a review bundle and grade it.
9. The human reviews and applies `patch.diff`. PatchWatch does not push, open PRs, merge, deploy, or publish packages.

## Why this stack

| Decision | Reason | Tradeoff |
|---|---|---|
| Python + Typer + Pydantic | Matches the target ecosystem; strict CLI and data contracts | Python repositories only |
| Explicit state machine | Tool order and approval gates remain observable | Limited supported workflows |
| Curated AST recipes | Zero inference cost, reproducible behavior, repository prompt injection has no instruction channel | Unsupported APIs escalate |
| Docker Engine API through fixed CLI arguments | Same isolation model locally and on Linux CI | A running Docker daemon is mandatory |
| Wheel-only pip resolution | No build hooks run while network is available | Source-only packages cannot be upgraded |
| JSONL + JSON + static HTML | Portable evidence, easy CI artifacts, no hosting bill | No multi-user backend or live job scheduler |
| Committed `uv.lock` for PatchWatch itself | Reproducible developer and CI environment | Target repositories with existing lockfiles currently escalate |

The source PDFs describe the intended product. They are not runtime instructions. Their truncated Mermaid code has been reconstructed as valid diagrams in [diagrams.md](diagrams.md). All numerical benchmark claims come from executed fixtures, not from the PDFs' example results or aspirational targets.

## Supported scope

- Python 3.12 execution environment; target `requires-python` must include Python 3.12.
- Exact direct-dependency pins in PEP 621 or plain requirements files.
- Requests and FastAPI same-major manifest upgrades.
- Pydantic 1 → 2: simple `@validator`, literal supported `Config` options, and `self.dict/json/copy` in directly declared BaseModel classes.
- SQLAlchemy 1 → 2: typed Connection/Session string execution, typed Session query/get, and the declarative-base import move.
- Pytest 8 → 9: dependency resolution and verification only; plugin conflicts escalate.
- Other supported-package same-major upgrades use manifest changes and verification, with no speculative source repair.

Aliased/dynamic APIs, unsupported validator options, custom indexes, editable/VCS/URL dependencies, dynamic dependencies, existing target lockfiles, missing tests, and pre-existing check failures require human intervention. A passing curated benchmark is not a claim to handle arbitrary Python applications.

## Storage

Source repositories stay unchanged. Runs contain `plan.json`, `task.json`, `run.json`, `patch.diff`, check logs, dependency resolution, risk/policy/evaluation reports, `trace.jsonl`, a Markdown summary, `index.html`, and checksums. Reports can be opened directly or hosted on any static server. Imported JSON is rendered as text, never executable markup.
