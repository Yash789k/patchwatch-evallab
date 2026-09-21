# Threat model

## Assets and trust boundaries

The original repository, host credentials, Git state, and controller code are trusted assets. Repository text, tests, dependency code, test output, downloaded metadata, and report imports are untrusted. The operator explicitly selects a repository and approves a plan. A task never gains authority from a README, source comment, generated log, or migration page.

Docker executes third-party code; the controller never imports a target project or runs its build scripts on the host. The Docker socket is not exposed to containers. Host environment variables, SSH agents, cloud credentials, browser state, home directories, and source Git metadata are not mounted. Common secret-file names are excluded from the copy, but this is not a general secret-discovery scanner.

## Controls

- Read-only container root filesystem; non-root UID/GID 65534; all Linux capabilities dropped; no-new-privileges.
- One CPU, 768 MiB memory, 128 processes, capped file descriptors, bounded tmpfs directories and command timeouts.
- Only the wheel downloader gets network access. That container sees requirements strings and its wheel volume, not repository files. It uses the public PyPI index with isolated pip configuration and binary distributions only.
- Offline installation and checks use `--network none`. Each check copies a read-only source snapshot into a new disposable directory. Writes performed by tests cannot modify the controller's patch.
- No raw shell input, arbitrary command strings, model tool shell, host Git hooks, package publishing, or autonomous GitHub mutation.
- Test/CI/security/config files are protected. Source-only edits and the selected manifest are allowed; new suppressions and test skips are blocked.
- Before/after verification is mandatory, and failed or unavailable checks cannot be presented as a completed upgrade.
- Plans include a source fingerprint; changes after approval force re-planning.
- HTML safely embeds JSON and inserts repository-derived strings using `textContent`.

## Limits

Docker shares a kernel with its host/VM and is not a guarantee against kernel vulnerabilities or deliberately hostile code. Use disposable Linux VMs for strongly adversarial repositories. Rootless Docker/Colima can reduce host exposure. Docker Desktop has separate license terms; Docker Engine on Linux is a free alternative.

The dependency-download phase intentionally has outbound access to PyPI and its distribution CDN; it is not a domain-filtering firewall. The controller does not execute downloaded packages in that phase. Installed packages may execute when tests run, but those containers have no network and no secrets mounted.

A malicious test suite can lie about its own behavior. Passing checks establish evidence for the selected tests, not mathematical correctness or an independently trustworthy oracle. Hash chains/checksums detect accidental or partial evidence changes; they are not authenticated signatures and do not prevent an attacker rewriting an entire bundle.

Default checks intentionally ignore repository-provided Ruff/mypy configuration and pytest addopts, and disable pytest plugin autoload. Project-specific build steps, test plugins, OS packages, and Python versions need a separately reviewed integration. No paid or cloud fallback silently runs if Docker fails.

## Security reporting

Do not put credentials or exploit details in public issues. See [SECURITY.md](../SECURITY.md). Tests exercise path traversal, symlinks, unsupported dependency sources, stale plans, trace tampering, HTML injection, policy budgets, protected edits, and scope-sensitive migrations.
