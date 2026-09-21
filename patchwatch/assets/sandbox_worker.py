"""Fixed container entrypoint. It never runs a user-provided command string."""

import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

COMMANDS = {
    "test": [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--junitxml=/tmp/patchwatch-junit.xml",
        "-o",
        "addopts=",
        "-o",
        "cache_dir=/tmp/pytest-cache",
    ],
    "lint": ["ruff", "check", "--isolated", "--select", "E4,E7,E9,F", "."],
    "format": ["ruff", "format", "--isolated", "--check", "."],
    "typecheck": [
        "mypy",
        "--config-file",
        "/dev/null",
        "--cache-dir",
        "/tmp/mypy",
        "--follow-imports",
        "silent",
        "--ignore-missing-imports",
        ".",
    ],
    "format_source": ["ruff", "format", "--isolated"],
}


def main() -> int:
    action = sys.argv[1]
    if action == "download":
        # No repository or host directories are mounted in this networked phase.
        requirements = json.loads(sys.argv[2])
        if not isinstance(requirements, list) or not all(
            isinstance(x, str) and len(x) < 1000 and not x.startswith("-") for x in requirements
        ):
            raise ValueError("Invalid requirements")
        return subprocess.call(
            [
                sys.executable,
                "-I",
                "-m",
                "pip",
                "--isolated",
                "download",
                "--only-binary=:all:",
                "--index-url",
                "https://pypi.org/simple",
                "--dest",
                "/wheels",
                *requirements,
            ]
        )
    if action == "install":
        wheels = sorted(str(p) for p in Path("/wheels").glob("*.whl"))
        if not wheels:
            print("No wheels were resolved")
            return 1
        return subprocess.call(
            [
                sys.executable,
                "-I",
                "-m",
                "pip",
                "--isolated",
                "install",
                "--no-index",
                "--no-deps",
                "--no-compile",
                "--target",
                "/deps",
                *wheels,
            ]
        )
    if action == "inventory":
        from importlib.metadata import distributions

        print(
            json.dumps(
                {
                    d.metadata["Name"].lower().replace("_", "-"): d.version
                    for d in distributions(path=["/deps"])
                }
            )
        )
        return 0
    if action not in COMMANDS:
        raise ValueError("Unknown check")
    shutil.copytree("/input", "/workspace/repo")
    os.chdir("/workspace/repo")
    environment = dict(
        os.environ,
        PYTHONPATH="/deps:/workspace/repo:/workspace/repo/src",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        HOME="/tmp",
        PYTHONDONTWRITEBYTECODE="1",
    )
    command = COMMANDS[action]
    if action == "format_source":
        files = json.loads(sys.argv[2])
        if not files:
            return 0
        for f in files:
            p = Path(f)
            if p.is_absolute() or ".." in p.parts or not str(p).endswith(".py"):
                raise ValueError("Invalid source path")
        result = subprocess.run([*command, *files], env=environment, capture_output=True, text=True)
        if result.returncode:
            print(result.stderr)
            return result.returncode
        print(json.dumps({f: Path(f).read_text() for f in files}))
        return 0
    code = subprocess.call(command, env=environment)
    if action == "test":
        try:
            root = ET.parse("/tmp/patchwatch-junit.xml").getroot()
            cases = list(root.iter("testcase"))
            skipped = sum(c.find("skipped") is not None for c in cases)
            failed = sum(
                c.find("failure") is not None or c.find("error") is not None for c in cases
            )
            summary = {
                "total": len(cases),
                "passed": len(cases) - skipped - failed,
                "skipped": skipped,
            }
            print("PATCHWATCH_TEST_SUMMARY=" + json.dumps(summary), flush=True)
        except (OSError, ET.ParseError):
            return 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
