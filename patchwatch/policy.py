import difflib
import re
import tomllib

from patchwatch.errors import PatchwatchError
from patchwatch.models import Policy, PolicyReport
from patchwatch.repository import manifest_requirements, parse_requirement, protected

FORBIDDEN = re.compile(
    r"#\s*(?:noqa|type:\s*ignore)|pytest\.mark\.(?:skip|xfail)|pytest\.skip\(|unittest\.skip|pragma:\s*no\s*cover|BEGIN [A-Z ]*PRIVATE KEY|(?:AKIA|ASIA)[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{30,}"
)


def diff_snapshots(before: dict[str, bytes], after: dict[str, bytes]) -> str:
    parts = []
    for name in sorted(before.keys() | after.keys()):
        a, b = before.get(name, b""), after.get(name, b"")
        if a == b:
            continue
        try:
            left, right = a.decode().splitlines(keepends=True), b.decode().splitlines(keepends=True)
        except UnicodeError:
            parts.append(f"Binary files a/{name} and b/{name} differ\n")
            continue
        parts.append(f"diff --git a/{name} b/{name}\n")
        lines = difflib.unified_diff(
            left,
            right,
            fromfile=f"a/{name}" if name in before else "/dev/null",
            tofile=f"b/{name}" if name in after else "/dev/null",
        )
        for line in lines:
            if not line.endswith("\n"):
                parts.append(line + "\n\\ No newline at end of file\n")
            else:
                parts.append(line)
    return "".join(parts)


def validate_patch(
    before: dict[str, bytes], after: dict[str, bytes], manifest: str, policy: Policy
) -> PolicyReport:
    changed = [n for n in sorted(before.keys() | after.keys()) if before.get(n) != after.get(n)]
    violations = []
    count = 0
    for name in changed:
        if protected(name) or name != manifest and not name.endswith(".py"):
            violations.append(f"Protected or disallowed file: {name}")
        if name not in after:
            violations.append(f"File deletion is prohibited: {name}")
        try:
            a, b = before.get(name, b"").decode(), after.get(name, b"").decode()
        except UnicodeError:
            violations.append(f"Binary edits are prohibited: {name}")
            continue
        for line in difflib.ndiff(a.splitlines(), b.splitlines()):
            if line.startswith(("+ ", "- ")):
                count += 1
            if line.startswith("+ ") and FORBIDDEN.search(line):
                violations.append(f"Suppression or secret-like text introduced: {name}")
    if manifest in changed and manifest in before and manifest in after:
        try:
            _, old_values, _ = manifest_requirements({manifest: before[manifest]})
            _, new_values, _ = manifest_requirements({manifest: after[manifest]})
            old_requirements = {r.name.lower(): r for r in map(parse_requirement, old_values)}
            new_requirements = {r.name.lower(): r for r in map(parse_requirement, new_values)}
            if old_requirements.keys() != new_requirements.keys():
                violations.append("Dependency additions/removals are prohibited")
            changed_dependencies = [
                name
                for name in old_requirements.keys() & new_requirements.keys()
                if str(old_requirements[name]) != str(new_requirements[name])
            ]
            if len(changed_dependencies) != 1:
                violations.append("Exactly one direct dependency may change")
            for name in changed_dependencies:
                old_r, new_r = old_requirements[name], new_requirements[name]
                if old_r.extras != new_r.extras or old_r.marker != new_r.marker:
                    violations.append("Dependency extras/markers may not change")
            if manifest == "pyproject.toml":
                old_doc = tomllib.loads(before[manifest].decode())
                new_doc = tomllib.loads(after[manifest].decode())
                old_doc["project"].pop("dependencies", None)
                new_doc["project"].pop("dependencies", None)
                if old_doc != new_doc:
                    violations.append("Non-dependency manifest settings are protected")
        except (ValueError, KeyError, TypeError, PatchwatchError):
            violations.append("Manifest cannot be independently validated")
    if len(changed) > policy.max_changed_files:
        violations.append("Changed-file budget exceeded")
    if count > policy.max_changed_lines:
        violations.append("Changed-line budget exceeded")
    return PolicyReport(
        passed=not violations, changed_files=changed, changed_lines=count, violations=violations
    )
