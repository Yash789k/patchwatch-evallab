import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from patchwatch.errors import PatchwatchError
from patchwatch.models import Policy, ToolArgs, ToolResult

T = TypeVar("T")
ALLOWLIST = {
    "scan_repository",
    "get_dependency_manifest",
    "get_migration_guide",
    "create_workspace_copy",
    "update_dependency",
    "run_check",
    "repair_source",
    "format_source",
    "validate_patch",
    "get_git_diff",
}


class Trace:
    def __init__(self, path: Path, policy: Policy):
        self.path = path
        self.policy = policy
        self.count = 0
        self.sequence = 0
        self.previous = "0" * 64
        path.touch(exist_ok=False)

    def emit(self, kind: str, **data: object) -> None:
        self.sequence += 1
        event = {
            "seq": self.sequence,
            "time": datetime.now(UTC).isoformat(),
            "type": kind,
            "previous_hash": self.previous,
            **data,
        }
        raw = json.dumps(event, sort_keys=True, ensure_ascii=True)
        self.previous = hashlib.sha256(raw.encode()).hexdigest()
        event["hash"] = self.previous
        with self.path.open("a") as file:
            file.write(json.dumps(event, sort_keys=True) + "\n")

    def call(self, name: str, args: ToolArgs, operation: Callable[[], T]) -> T:
        if name not in ALLOWLIST:
            self.emit("policy", decision="block", code="TOOL_NOT_ALLOWED", tool=name)
            raise PatchwatchError("TOOL_NOT_ALLOWED", f"Tool {name} is not allowed.")
        if self.count >= self.policy.max_tool_calls:
            self.emit("policy", decision="block", code="TOOL_BUDGET")
            raise PatchwatchError("TOOL_BUDGET", "Tool-call budget exceeded.")
        self.count += 1
        started = time.monotonic()
        self.emit("tool_call", tool=name, arguments=args.model_dump(exclude_none=True))
        try:
            value = operation()
            data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
            # Do not duplicate potentially large command logs in the trace.
            if isinstance(data, dict) and "log" in data:
                data = {k: v for k, v in data.items() if k != "log"}
            if isinstance(data, dict) and any(isinstance(v, bytes) for v in data.values()):
                data = {"file_count": len(data)}
            if isinstance(data, str) and len(data) > 2000:
                data = {
                    "characters": len(data),
                    "sha256": hashlib.sha256(data.encode()).hexdigest(),
                }
            result = ToolResult(ok=True, data=data)
        except PatchwatchError as exc:
            self.emit(
                "tool_result",
                tool=name,
                result=ToolResult(ok=False, code=exc.code, data=str(exc)).model_dump(),
                duration_seconds=round(time.monotonic() - started, 3),
            )
            raise
        self.emit(
            "tool_result",
            tool=name,
            result=result.model_dump(mode="json"),
            duration_seconds=round(time.monotonic() - started, 3),
        )
        return value


def verify_trace(path: Path) -> bool:
    previous = "0" * 64
    try:
        lines = path.read_text().splitlines()
        if not lines:
            return False
        for seq, line in enumerate(lines, 1):
            event = json.loads(line)
            digest = event.pop("hash")
            if event["seq"] != seq or event["previous_hash"] != previous:
                return False
            if (
                hashlib.sha256(
                    json.dumps(event, sort_keys=True, ensure_ascii=True).encode()
                ).hexdigest()
                != digest
            ):
                return False
            previous = digest
    except (ValueError, KeyError, OSError):
        return False
    return True
