"""Docker is mandatory. Networked downloads cannot see repository contents."""

import json
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from patchwatch.errors import PatchwatchError
from patchwatch.models import Check, CheckName

IMAGE = "patchwatch-sandbox:1.0"
CHECKS: tuple[CheckName, ...] = ("test", "lint", "format", "typecheck")


def bounded_process(args: list[str], timeout: float) -> tuple[int, str]:
    try:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except FileNotFoundError as exc:
        raise PatchwatchError(
            "DOCKER_MISSING",
            "Docker CLI is required. Install Docker Engine, Docker Desktop, or Colima.",
        ) from exc
    output = bytearray()
    truncated = False

    def drain() -> None:
        nonlocal truncated
        assert process.stdout
        while block := process.stdout.read(8192):
            output.extend(block)
            if len(output) > 524288:
                del output[:-524288]
                truncated = True

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    try:
        code = process.wait(timeout=max(1, timeout))
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        code = 124
    thread.join(timeout=5)
    text = output.decode(errors="replace")
    if truncated:
        text = "[Output truncated to final 512 KiB]\n" + text
    if code == 124:
        text += "\n[Command exceeded time budget]\n"
    return code, text


class DockerSandbox:
    def __init__(self, timeout: int = 120, deadline: float | None = None):
        self.timeout = timeout
        self.deadline = deadline or time.monotonic() + 900
        self.volumes: list[str] = []
        self.deps: str | None = None
        self.inventory: dict[str, str] = {}
        self.image = IMAGE

    def available(self) -> None:
        code, _ = bounded_process(["docker", "info", "--format", "{{.ServerVersion}}"], 15)
        if code:
            raise PatchwatchError("DOCKER_UNAVAILABLE", "Start Docker, then run patchwatch setup.")
        code, out = bounded_process(
            ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"], 15
        )
        if code:
            raise PatchwatchError(
                "SANDBOX_IMAGE_MISSING", "Run patchwatch setup to build the sandbox image."
            )
        self.image = out.strip()  # Pin this run to the image content, even if its tag moves.

    def _run(
        self,
        action: str,
        args: list[str] | None = None,
        mounts: list[str] | None = None,
        network: bool = False,
    ) -> tuple[int, str, float]:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise PatchwatchError("TIME_BUDGET", "Run exceeded its wall-clock budget.")
        name = "pw-" + uuid.uuid4().hex
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--pull=never",
            "--network",
            "bridge" if network else "none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            "--user",
            "65534:65534",
            "--pids-limit",
            "128",
            "--memory",
            "768m",
            "--cpus",
            "1",
            "--ulimit",
            "nofile=1024:1024",
            "--tmpfs",
            "/tmp:rw,nosuid,size=256m,mode=1777",
            "--tmpfs",
            "/workspace:rw,nosuid,size=64m,mode=1777",
        ]
        for mount in mounts or []:
            command.extend(["--mount", mount])
        command.extend([self.image, action, *(args or [])])
        started = time.monotonic()
        try:
            code, output = bounded_process(command, min(self.timeout, remaining))
        finally:
            bounded_process(["docker", "rm", "-f", name], 10)
        return code, output, round(time.monotonic() - started, 3)

    def _volume(self) -> str:
        name = "pw-" + uuid.uuid4().hex
        code, _ = bounded_process(
            ["docker", "volume", "create", "--label", "app=patchwatch", name], 10
        )
        if code:
            raise PatchwatchError(
                "SANDBOX_VOLUME", "Could not allocate an isolated dependency volume."
            )
        self.volumes.append(name)
        return name

    def install(self, requirements: list[str], phase: str) -> Check:
        wheels, deps = self._volume(), self._volume()
        code, log, duration = self._run(
            "download",
            [json.dumps(requirements)],
            [f"type=volume,src={wheels},dst=/wheels"],
            network=True,
        )
        if not code:
            code, install_log, elapsed = self._run(
                "install",
                mounts=[
                    f"type=volume,src={wheels},dst=/wheels,readonly",
                    f"type=volume,src={deps},dst=/deps",
                ],
            )
            log += "\n--- Offline installation ---\n" + install_log
            duration += elapsed
        if not code:
            self.deps = deps
            inv_code, inv, _ = self._run(
                "inventory", mounts=[f"type=volume,src={deps},dst=/deps,readonly"]
            )
            if inv_code:
                code, log = inv_code, log + "\nUnable to verify installed dependencies."
            else:
                self.inventory = json.loads(inv)
        return Check(
            name="install",
            phase=phase,
            passed=code == 0,
            exit_code=code,
            duration_seconds=duration,
            log=log,
        )

    def _mounts(self, workspace: Path) -> list[str]:
        if not self.deps:
            raise PatchwatchError(
                "DEPENDENCIES_MISSING", "No verified dependency environment exists."
            )
        if "," in str(workspace):
            raise PatchwatchError(
                "PATH_UNSUPPORTED",
                "Workspace paths containing commas are unsupported by Docker mounts.",
            )
        return [
            f"type=bind,src={workspace.resolve()},dst=/input,readonly",
            f"type=volume,src={self.deps},dst=/deps,readonly",
        ]

    def check(self, workspace: Path, name: str, phase: str) -> Check:
        if name not in CHECKS:
            raise PatchwatchError("TOOL_NOT_ALLOWED", "Unknown verification check.")
        code, log, elapsed = self._run(name, mounts=self._mounts(workspace))
        summary: dict[str, int] = {}
        if name == "test":
            match = re.search(r"^PATCHWATCH_TEST_SUMMARY=(\{[^\n]+\})$", log, re.MULTILINE)
            if match:
                summary = json.loads(match.group(1))
            if summary.get("passed", 0) == 0:
                code = code or 1
                log += "\n[Verification requires at least one passing test.]\n"
        return Check(
            tests_passed=summary.get("passed"),
            tests_skipped=summary.get("skipped"),
            tests_total=summary.get("total"),
            name=name,
            phase=phase,
            passed=code == 0,
            exit_code=code,
            duration_seconds=elapsed,
            log=log,
        )

    def format_source(self, workspace: Path, paths: list[str]) -> dict[str, str]:
        code, output, _ = self._run("format_source", [json.dumps(paths)], self._mounts(workspace))
        if code:
            raise PatchwatchError("FORMAT_FAILED", output[-1000:])
        value: Any = json.loads(output)
        if (
            not isinstance(value, dict)
            or set(value) != set(paths)
            or not all(isinstance(v, str) for v in value.values())
        ):
            raise PatchwatchError("FORMAT_CONTRACT", "Formatter returned unexpected files.")
        return value

    def close(self) -> None:
        for name in self.volumes:
            bounded_process(["docker", "volume", "rm", "-f", name], 15)
        self.volumes.clear()
