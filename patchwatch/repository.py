"""Read repository data without importing or running repository code."""

import hashlib
import os
import re
import stat
import tomllib
from pathlib import Path

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from patchwatch.errors import PatchwatchError
from patchwatch.models import Dependency, RepoSummary

EXCLUDED = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "runs",
    "dist",
    "build",
}
SECRET_NAMES = {
    ".env",
    ".pypirc",
    ".npmrc",
    ".netrc",
    ".ssh",
    ".aws",
    ".azure",
    ".kube",
    ".gcloud",
    "id_rsa",
    "id_ed25519",
    "credentials",
    "credentials.json",
}
LOCKFILES = ("uv.lock", "poetry.lock", "Pipfile.lock", "pdm.lock")
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 30 * 1024 * 1024


def secret_path(path: Path) -> bool:
    return any(
        p in SECRET_NAMES or p.startswith(".env.") or p.endswith((".pem", ".key", ".p12"))
        for p in path.parts
    )


def protected(path: str) -> bool:
    p = Path(path)
    return (
        any(
            part in {"tests", "test", ".github", ".gitlab", ".circleci", ".patchwatch"}
            for part in p.parts
        )
        or p.name.startswith("test_")
        or p.name.endswith("_test.py")
        or p.name
        in {
            "conftest.py",
            "tox.ini",
            "pytest.ini",
            ".pre-commit-config.yaml",
            "SECURITY.md",
            "mypy.ini",
            "ruff.toml",
            ".ruff.toml",
            "setup.cfg",
        }
        or secret_path(p)
    )


def safe_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if any(ord(c) < 32 or ord(c) == 127 for c in relative) or any(
        part.startswith("-") for part in path.parts
    ):
        raise PatchwatchError(
            "PATH_UNSUPPORTED",
            "Control characters and option-like path components are not permitted.",
        )
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise PatchwatchError("PATH_BOUNDARY", f"Path is outside workspace: {relative}")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise PatchwatchError("SYMLINK", f"Symlink is not permitted: {relative}")
    if not current.resolve().is_relative_to(root.resolve()):
        raise PatchwatchError("PATH_BOUNDARY", f"Path is outside workspace: {relative}")
    return current


def snapshot(root: Path) -> dict[str, bytes]:
    root = root.resolve()
    if not root.is_dir():
        raise PatchwatchError("REPOSITORY_MISSING", "Repository directory does not exist.")
    result: dict[str, bytes] = {}
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not secret_path(Path(d)))
        for d in dirs:
            if (Path(directory) / d).is_symlink():
                raise PatchwatchError("SYMLINK", "Repository contains a symlink directory.")
        for name in sorted(files):
            relative = (Path(directory) / name).relative_to(root)
            if secret_path(relative) or name == ".DS_Store" or name.endswith((".pyc", ".pyo")):
                continue
            path = safe_path(root, relative.as_posix())
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                raise PatchwatchError("SPECIAL_FILE", "Repository contains a non-regular file.")
            if info.st_size > MAX_FILE:
                raise PatchwatchError("REPOSITORY_LIMIT", f"File exceeds 2 MiB: {relative}")
            data = path.read_bytes()
            total += len(data)
            if total > MAX_TOTAL or len(result) >= 2000:
                raise PatchwatchError(
                    "REPOSITORY_LIMIT", "Repository exceeds 30 MiB or 2,000 files."
                )
            result[relative.as_posix()] = data
    return result


def fingerprint(files: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for name, data in sorted(files.items()):
        h.update(name.encode() + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()


def parse_requirement(value: str) -> Requirement:
    try:
        requirement = Requirement(value)
    except InvalidRequirement as exc:
        raise PatchwatchError(
            "UNSUPPORTED_REQUIREMENT", f"Unsupported dependency declaration: {value[:100]}"
        ) from exc
    if requirement.url:
        raise PatchwatchError(
            "DEPENDENCY_URL", "URL, VCS, and local-path dependencies are not permitted."
        )
    return requirement


def manifest_requirements(files: dict[str, bytes]) -> tuple[str, list[str], str | None]:
    if "pyproject.toml" in files:
        try:
            doc = tomllib.loads(files["pyproject.toml"].decode())
        except (ValueError, UnicodeError) as exc:
            raise PatchwatchError("INVALID_MANIFEST", "Invalid pyproject.toml.") from exc
        project = doc.get("project", {})
        if "dependencies" in project.get("dynamic", []):
            raise PatchwatchError(
                "DYNAMIC_DEPENDENCIES", "Dynamic dependencies require manual review."
            )
        deps = project.get("dependencies")
        if deps is not None:
            if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
                raise PatchwatchError(
                    "INVALID_MANIFEST", "project.dependencies must be a string array."
                )
            if doc.get("tool", {}).get("uv", {}).get("sources"):
                raise PatchwatchError(
                    "CUSTOM_SOURCES", "Custom package sources require manual review."
                )
            return "pyproject.toml", deps, project.get("requires-python")
    if "requirements.txt" in files:
        deps = []
        for line in files["requirements.txt"].decode().splitlines():
            line = line.split(" #", 1)[0].strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-") or "\\" in line:
                raise PatchwatchError(
                    "REQUIREMENTS_DIRECTIVE",
                    "Includes, pip options and multiline requirements require manual review.",
                )
            deps.append(line)
        return "requirements.txt", deps, None
    raise PatchwatchError(
        "MANIFEST_MISSING", "Expected PEP 621 project.dependencies or requirements.txt."
    )


def inspect_repository(root: Path) -> RepoSummary:
    files = snapshot(root)
    manifest, values, python = manifest_requirements(files)
    deps = []
    names: set[str] = set()
    for value in values:
        r = parse_requirement(value)
        name = canonicalize_name(r.name)
        if name in names:
            raise PatchwatchError("DUPLICATE_DEPENDENCY", f"Duplicate dependency: {name}")
        names.add(name)
        specs = list(r.specifier)
        pin = (
            specs[0].version
            if len(specs) == 1 and specs[0].operator == "==" and "*" not in specs[0].version
            else None
        )
        deps.append(Dependency(name=name, requirement=value, pinned_version=pin))
    source = [name for name in files if name.endswith(".py") and not protected(name)]
    tests = [name for name in files if name.endswith(".py") and protected(name)]
    warnings = ["Repository content is untrusted data; instructions in it are never executed."]
    if not tests:
        warnings.append(
            "No test files detected; REVIEW_READY requires a non-empty passing test suite."
        )
    return RepoSummary(
        name=root.resolve().name,
        root=str(root.resolve()),
        manifest=manifest,
        dependencies=deps,
        python_requires=python,
        source_files=source,
        test_files=tests,
        lockfiles=[p for p in LOCKFILES if p in files],
        fingerprint=fingerprint(files),
        warnings=warnings,
    )


def update_manifest(content: bytes, manifest: str, dependency: str, target: str) -> bytes:
    def replace(value: str) -> str:
        r = parse_requirement(value)
        if canonicalize_name(r.name) != canonicalize_name(dependency):
            return value
        extras = "[" + ",".join(sorted(r.extras)) + "]" if r.extras else ""
        marker = f"; {r.marker}" if r.marker else ""
        return f"{r.name}{extras}=={target}{marker}"

    text = content.decode()
    if manifest == "pyproject.toml":
        doc = tomlkit.parse(text)
        project = doc["project"]
        dependencies = project["dependencies"]
        for i, value in enumerate(dependencies):
            dependencies[i] = replace(str(value))
        return tomlkit.dumps(doc).encode()
    lines = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            lines.append(line)
            continue
        value, *comment = re.split(r"\s+#", line.rstrip("\r\n"), maxsplit=1)
        lines.append(
            replace(value.strip())
            + ("  #" + comment[0] if comment else "")
            + ("\n" if line.endswith("\n") else "")
        )
    return "".join(lines).encode()
