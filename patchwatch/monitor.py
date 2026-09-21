"""Opt-in, read-only PyPI metadata lookup. Never downloads or runs packages."""

import json
import urllib.error
import urllib.request
from typing import Any

from packaging.version import InvalidVersion, Version

from patchwatch.migrations import GUIDES
from patchwatch.models import RepoSummary


def scan_updates(repo: RepoSummary) -> dict[str, Any]:
    rows = []
    for dependency in repo.dependencies:
        if dependency.name not in GUIDES:
            continue
        row: dict[str, Any] = {"dependency": dependency.name, "current": dependency.pinned_version}
        request = urllib.request.Request(
            f"https://pypi.org/pypi/{dependency.name}/json",
            headers={"User-Agent": "PatchWatch/1.0 (+read-only dependency scan)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = response.read(5 * 1024 * 1024 + 1)
            if len(data) > 5 * 1024 * 1024:
                raise ValueError("PyPI response exceeds limit")
            metadata = json.loads(data)
            versions = []
            for version, distributions in metadata["releases"].items():
                try:
                    parsed = Version(version)
                except InvalidVersion:
                    continue
                if (
                    not parsed.is_prerelease
                    and not parsed.is_devrelease
                    and distributions
                    and any(not d.get("yanked") for d in distributions)
                ):
                    versions.append(parsed)
            latest = str(max(versions)) if versions else None
            row.update(
                latest=latest,
                upgrade_available=bool(
                    latest
                    and dependency.pinned_version
                    and Version(latest) > Version(dependency.pinned_version)
                ),
                guide=GUIDES[dependency.name],
            )
        except (urllib.error.URLError, ValueError, KeyError, TimeoutError) as exc:
            row["error"] = str(exc)
        rows.append(row)
    return {
        "repository": repo.name,
        "source": "PyPI metadata",
        "updates": rows,
        "note": "Latest release is informational; compatibility and support are checked during planning.",
    }
