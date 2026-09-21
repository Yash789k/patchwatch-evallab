# PatchWatch EvalLab diagrams

These Mermaid diagrams reconstruct all 13 views in the supplied diagram PDF and reflect the shipped implementation. They render directly on GitHub. The PDF clips several lines; those have been rewritten rather than copied as broken Mermaid.

## 1. System architecture

```mermaid
flowchart TB
  User[Developer or CI] --> CLI[Typer CLI]
  CLI --> Agent[Explicit state machine]
  Agent --> Policy[Approval and policy gates]
  Agent --> Router[Typed tool router]
  Router --> Repo[Repository and manifest inspection]
  Router --> Rules[Curated migration recipes]
  Router --> Docker[Docker verification sandbox]
  Router --> Diff[Controlled edits and diff validation]
  Policy --> Trace[Hash-chained JSONL trace]
  Router --> Trace
  Trace --> Eval[EvalLab graders]
  Diff --> Eval
  Docker --> Eval
  Eval --> Bundle[Patch and evidence bundle]
  Bundle --> HTML[Offline interactive HTML viewer]
  Bundle --> Review[Human code review]
```

## 2. Agent lifecycle

```mermaid
stateDiagram-v2
  [*] --> Inspecting
  Inspecting --> Planning
  Planning --> ApprovalRequired: Approval missing
  Planning --> Escalated: Unsupported migration
  Planning --> CreateWorkspace: Approved fingerprint matches
  CreateWorkspace --> BaselineChecks
  BaselineChecks --> Escalated: Pre-existing failure
  BaselineChecks --> ApplyUpgrade: Baseline passes
  ApplyUpgrade --> RunChecks
  RunChecks --> Diagnose: Check failure or supported major migration
  Diagnose --> Repair: Supported recipe and budget available
  Repair --> RunChecks
  Diagnose --> Escalated: Unsupported or exhausted
  RunChecks --> ValidatePatch: All checks pass
  ValidatePatch --> ReviewReady: Policy and source integrity pass
  ValidatePatch --> Escalated: Policy or integrity failure
  CreateWorkspace --> Failed: Infrastructure error
  ApprovalRequired --> Bundle
  Escalated --> Bundle
  Failed --> Bundle
  ReviewReady --> Bundle
  Bundle --> [*]
```

## 3. Patch workflow sequence

```mermaid
sequenceDiagram
  autonumber
  actor Developer
  participant CLI
  participant Controller
  participant Policy
  participant Docker
  participant EvalLab
  Developer->>CLI: plan repository --dependency pydantic --target 2.9.2
  CLI->>Controller: Inspect and generate fingerprint-bound plan
  Controller->>Policy: Classify risk and supported scope
  Controller-->>Developer: Plan, scope, steps, and approval requirement
  Developer->>CLI: apply repository --plan plan.json --approve-plan
  Controller->>Policy: Verify approval and unchanged source
  Controller->>Docker: Resolve baseline wheels without repository mount
  Controller->>Docker: Offline baseline checks on disposable copies
  Docker-->>Controller: Baseline evidence
  Controller->>Controller: Change dependency in temporary workspace
  Controller->>Docker: Resolve target and run checks
  Docker-->>Controller: Failure evidence
  Controller->>Policy: Validate narrow curated repair
  Controller->>Controller: Apply supported source transformation
  Controller->>Docker: Repeat all mandatory checks
  Docker-->>Controller: Verified results
  Controller->>Policy: Validate final diff and original fingerprint
  Controller->>EvalLab: Grade trace, policy, installed version, and evidence
  EvalLab-->>Developer: Patch, logs, trace, summary, and HTML report
```

## 4. Controlled tool architecture

```mermaid
flowchart LR
  Agent[Controller] --> Router[Pydantic tool contracts]
  Router --> Read[Read-only tools]
  Router --> Write[Controlled write tools]
  Router --> Exec[Fixed Docker checks]
  Router --> Governance[Governance]
  Read --> Scan[scan_repository]
  Read --> Manifest[get_dependency_manifest]
  Read --> Guide[get_migration_guide]
  Write --> Copy[create_workspace_copy]
  Write --> Upgrade[update_dependency]
  Write --> Repair[repair_source]
  Write --> Format[format_source]
  Exec --> Install[Wheel download and offline install]
  Exec --> Checks[Test, lint, format, typecheck]
  Governance --> Validate[validate_patch]
  Governance --> Approval[Approved plan fingerprint]
  Governance --> Escalation[Reason and human next step]
  Router --> Trace[Every invocation emits trace events]
```

## 5. Sandbox and trust boundary

```mermaid
flowchart TB
  subgraph Host[Developer host]
    Original[Original repository]
    Secrets[Host credentials and Docker socket]
    Controller[Trusted controller]
    Snapshot[Temporary sanitized workspace]
  end
  subgraph Network[Networked downloader]
    Requirements[Validated requirement strings]
    PyPI[PyPI and wheel CDN]
    Wheels[Wheel volume]
    Requirements --> PyPI --> Wheels
  end
  subgraph Offline[Containers with network disabled]
    Install[Offline wheel installation]
    Dependencies[Dependency volume]
    Copy[Disposable source copy per check]
    Check[Non-root tests and static checks]
    Install --> Dependencies
    Copy --> Check
    Dependencies -->|read only| Check
  end
  Original -->|regular files only| Snapshot
  Controller --> Requirements
  Wheels -->|read only| Install
  Snapshot -->|read only| Copy
  Check -->|bounded logs| Controller
  Secrets -.->|not mounted or forwarded| Offline
```

## 6. Policy decision flow

```mermaid
flowchart TD
  Action[Proposed action] --> Schema{Typed arguments valid?}
  Schema -->|No| Block[Block and record reason]
  Schema -->|Yes| Allowed{Tool allowlisted?}
  Allowed -->|No| Block
  Allowed -->|Yes| Budget{Within budgets?}
  Budget -->|No| Escalate[Escalate with evidence]
  Budget -->|Yes| Write{Workspace mutation?}
  Write -->|No| Execute[Execute and trace]
  Write -->|Yes| Approval{Plan approved and fingerprint current?}
  Approval -->|No| Pause[Pause or stale-plan escalation]
  Approval -->|Yes| Path{Inside workspace and allowed file?}
  Path -->|No| Block
  Path -->|Yes| Pattern{Introduces suppression or forbidden change?}
  Pattern -->|Yes| Block
  Pattern -->|No| Execute
```

## 7. Test-fail-repair loop

```mermaid
flowchart TD
  Baseline[Run baseline checks] --> Before{All pass?}
  Before -->|No| Existing[Escalate pre-existing failure]
  Before -->|Yes| Upgrade[Update target dependency]
  Upgrade --> Resolve{Target dependencies resolve?}
  Resolve -->|No| Conflict[Escalate conflict]
  Resolve -->|Yes| Checks[Run all four checks]
  Checks --> Pass{Checks pass and migration complete?}
  Pass -->|Yes| Policy[Final diff and policy validation]
  Pass -->|No| Supported{Supported syntax-aware repair?}
  Supported -->|No| Escalate[Escalate without changing tests]
  Supported -->|Yes| Budget{Repair budget remains?}
  Budget -->|No| Escalate
  Budget -->|Yes| Repair[Apply constrained repair and format changed source]
  Repair --> Checks
  Policy --> Ready[Review-ready evidence bundle]
```

## 8. Evaluation pipeline

```mermaid
flowchart LR
  Dataset[JSONL task contracts] --> Runner[EvalLab runner]
  Fixtures[Eight synthetic repositories] --> Runner
  Runner --> Production[Production PatchWatch controller]
  Production --> Evidence[Trace, patch, checks, status]
  Evidence --> Completion[Outcome and reason grader]
  Evidence --> Dependency[Installed-version grader]
  Evidence --> Safety[Protected-path and policy grader]
  Evidence --> Trace[Approval and ordering grader]
  Evidence --> Verification[Mandatory Docker-check grader]
  Evidence --> Artifact[Expected patch-pattern grader]
  Completion --> Aggregate[Task outcomes and metrics]
  Dependency --> Aggregate
  Safety --> Aggregate
  Trace --> Aggregate
  Verification --> Aggregate
  Artifact --> Aggregate
  Aggregate --> Baseline[Per-task regression comparison]
  Baseline --> CI[CI pass or fail]
```

## 9. Trace event model

```mermaid
flowchart TB
  Run[Run identity] --> State[State transitions]
  Run --> Tool[Tool call and typed result]
  Run --> Approval[Plan ID and source fingerprint]
  Run --> Verification[Check phase and exit code]
  Run --> Policy[Allow, block, or pause]
  Run --> Escalation[Reason and next action]
  Run --> Artifact[Patch artifact metadata]
  State --> Chain[Sequence and previous-event hash]
  Tool --> Chain
  Approval --> Chain
  Verification --> Chain
  Policy --> Chain
  Escalation --> Chain
  Artifact --> Chain
  Chain --> Integrity[Integrity validation]
  Integrity --> Graders[Independent ordered-trace grading]
```

## 10. Fixture lifecycle

```mermaid
stateDiagram-v2
  [*] --> Draft
  Draft --> Seeded: Add historical dependency and controlled breakage
  Seeded --> BaselineVerified: Execute original checks
  BaselineVerified --> ExpectedOutcome: Define patch or escalation contract
  ExpectedOutcome --> Dataset: Attach budgets and required patterns
  Dataset --> Evaluated: Run production controller in Docker
  Evaluated --> Graded
  Graded --> Accepted: Matches outcome and safety contract
  Graded --> NeedsRevision: Failure or ambiguous expectation
  NeedsRevision --> Draft
  Accepted --> BaselineCommitted
  BaselineCommitted --> [*]
```

## 11. GitHub Actions CI

```mermaid
flowchart TD
  Trigger[Push, PR, or manual dispatch] --> Static[Lint, formatting, and type checks]
  Trigger --> Unit[Unit and adversarial tests]
  Trigger --> Build[Build pinned Docker image]
  Build --> Integration[Docker isolation tests]
  Build --> Eval[Execute eight fixture tasks]
  Eval --> Compare[Compare with committed measured baseline]
  Static --> Gate{All checks pass?}
  Unit --> Gate
  Integration --> Gate
  Compare --> Gate
  Gate -->|Yes| Green[Green commit status]
  Gate -->|No| Red[Failed status with diagnostic evidence]
  Eval --> Artifacts[Upload evidence with one-day retention]
```

## 12. Pydantic demo

```mermaid
flowchart TD
  Request[Upgrade Pydantic 1.10.13 to 2.9.2] --> Inspect[Inspect manifest and source fingerprint]
  Inspect --> README[Repository contains malicious README instructions]
  README --> Ignore[Treat all repository prose as data]
  Ignore --> Approve[Approve structured plan]
  Approve --> Baseline[Verify v1 baseline]
  Baseline --> Upgrade[Change dependency pin in copied workspace]
  Upgrade --> Failure[Target tests expose Config incompatibility]
  Failure --> Repair[Transform simple validator and Config APIs]
  Repair --> Serialize[Update supported model serialization]
  Serialize --> Verify[Repeat tests, lint, formatting, and type checks]
  Verify --> Policy[Confirm protected tests unchanged]
  Policy --> Review[Review-ready patch and trace]
```

## 13. Layered trust model

```mermaid
flowchart TB
  Intent[1. Explicit operator request] --> Policy[2. Approved plan and bounded policy]
  Policy --> Tools[3. Typed narrow tools]
  Tools --> Isolation[4. Docker execution boundary]
  Isolation --> Verification[5. Deterministic before-and-after checks]
  Verification --> Review[6. Human review before external changes]
  Review --> Audit[7. Evaluation, regression gates, and evidence]
```
