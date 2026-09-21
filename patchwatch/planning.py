import hashlib

from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from patchwatch.errors import PatchwatchError
from patchwatch.migrations import GUIDES
from patchwatch.models import Plan, Policy, RepoSummary, Risk


def make_plan(
    repo: RepoSummary, dependency: str, target: str, policy: Policy | None = None
) -> Plan:
    name = canonicalize_name(dependency)
    match = next((d for d in repo.dependencies if d.name == name), None)
    if not match:
        raise PatchwatchError("DEPENDENCY_MISSING", f"{name} is not a declared direct dependency.")
    try:
        version = Version(target)
    except InvalidVersion as exc:
        raise PatchwatchError(
            "INVALID_VERSION", "Target must be an exact release version."
        ) from exc
    if str(version) != target or version.is_prerelease or version.is_devrelease or version.local:
        raise PatchwatchError(
            "INVALID_VERSION", "Use a canonical stable release version, without a local suffix."
        )
    old = Version(match.pinned_version) if match.pinned_version else None
    risk: Risk = (
        "unknown"
        if old is None
        else "high"
        if old.major != version.major
        else "medium"
        if old.minor != version.minor
        else "low"
    )
    supported = True
    reason = "Pinned upgrade with mandatory before/after checks."
    if old is None:
        supported, reason = (
            False,
            "Unpinned source version: pin the existing dependency before migration.",
        )
    elif version <= old:
        supported, reason = False, "Target must be newer than the current pinned version."
    elif repo.python_requires and not SpecifierSet(repo.python_requires).contains("3.12.14"):
        supported, reason = (
            False,
            "The repository requires a Python version outside the pinned Python 3.12.14 sandbox.",
        )
    elif repo.lockfiles:
        supported, reason = (
            False,
            "Existing lockfile requires a package-manager-specific migration; refusing manifest/lock drift.",
        )
    elif name not in GUIDES:
        supported, reason = False, "No curated migration guide exists for this dependency."
    elif risk == "high" and not (
        (name in {"pydantic", "sqlalchemy"} and old.major == 1 and version.major == 2)
        or (name == "pytest" and old.major == 8 and version.major == 9)
    ):
        supported, reason = False, "Unsupported major migration: manual API review required."
    elif not repo.test_files:
        supported, reason = (
            False,
            "No test files found; add a test suite before requesting a verified patch.",
        )
    policy = policy or Policy()
    payload = f"{repo.fingerprint}:{name}:{target}:{policy.model_dump_json()}"
    return Plan(
        id=hashlib.sha256(payload.encode()).hexdigest()[:20],
        repository=repo,
        dependency=name,
        from_version=match.pinned_version,
        target=target,
        risk=risk,
        supported=supported,
        reason=reason,
        guide=GUIDES.get(name),
        policy=policy,
        steps=[
            "Verify the approved repository fingerprint",
            "Copy sanitized repository into a temporary workspace",
            "Resolve wheel-only dependencies and run baseline checks in Docker",
            "Update only the requested direct dependency",
            "Run target checks; apply bounded curated repairs when needed",
            "Validate the diff, protected paths, and original repository",
            "Write patch, logs, trace, evaluation, and a review checklist",
        ],
    )
