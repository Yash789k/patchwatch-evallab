"""Versioned, strict contracts shared by tools, CLI, reports, and graders."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CheckName = Literal["install", "test", "lint", "format", "typecheck"]
RunStatus = Literal["review_ready", "escalated", "failed", "approval_required"]
Risk = Literal["low", "medium", "high", "unknown"]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Policy(Schema):
    max_tool_calls: int = Field(default=60, ge=8, le=200)
    max_repairs: int = Field(default=3, ge=0, le=3)
    max_changed_files: int = Field(default=10, ge=1, le=30)
    max_changed_lines: int = Field(default=300, ge=1, le=1000)
    max_seconds: int = Field(default=900, ge=30, le=1800)
    command_timeout: int = Field(default=120, ge=5, le=300)
    max_command_failures: int = Field(default=5, ge=1, le=10)


class Dependency(Schema):
    name: str
    requirement: str
    pinned_version: str | None = None


class RepoSummary(Schema):
    name: str
    root: str
    manifest: str
    dependencies: list[Dependency]
    python_requires: str | None
    source_files: list[str]
    test_files: list[str]
    lockfiles: list[str]
    fingerprint: str
    warnings: list[str] = Field(default_factory=list)


class Plan(Schema):
    schema_version: int = 1
    id: str
    repository: RepoSummary
    dependency: str
    from_version: str | None
    target: str
    risk: Risk
    supported: bool
    reason: str
    guide: str | None
    steps: list[str]
    requires_approval: bool = True
    policy: Policy = Field(default_factory=Policy)


class ToolArgs(Schema):
    path: str | None = None
    dependency: str | None = None
    target: str | None = None
    check: CheckName | None = None
    phase: str | None = None


class ToolResult(Schema):
    ok: bool
    code: str = "OK"
    data: Any = None


class Check(Schema):
    name: str
    phase: str
    passed: bool
    exit_code: int
    duration_seconds: float
    log: str
    sandbox: str = "docker"
    tests_passed: int | None = None
    tests_skipped: int | None = None
    tests_total: int | None = None


class PolicyReport(Schema):
    passed: bool
    changed_files: list[str]
    changed_lines: int
    violations: list[str]


class Run(Schema):
    schema_version: int = 1
    id: str
    plan: Plan
    status: RunStatus
    reason: str
    started_at: str
    duration_seconds: float
    repairs: int
    checks: list[Check]
    policy: PolicyReport
    tool_calls: int
    cost_usd: float = 0
    model_calls: int = 0
    engine: str = "curated-rules-v1"
    original_unchanged: bool
    resolved_dependencies: dict[str, str] = Field(default_factory=dict)


class Expected(Schema):
    status: Literal["review_ready", "escalated"]
    tests_pass: bool
    reason_contains: str | None = None
    required_patterns_present: list[str] = Field(default_factory=list)
    required_patterns_absent: list[str] = Field(default_factory=list)


class EvalTask(Schema):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    repo: str
    dependency: str
    target: str
    expected: Expected
    policy: Policy = Field(default_factory=Policy)


class Grade(Schema):
    name: str
    passed: bool
    reason: str
