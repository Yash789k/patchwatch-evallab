# Installation, CI, and optional publishing

## Local installation

`make setup && make demo` is the source-checkout path. `uv build` produces a wheel and source distribution. The wheel bundles the sandbox Dockerfile, worker, HTML viewer, and demo fixture repositories. A fresh environment can install it without checking out the source.

```sh
uv tool install ./dist/patchwatch_evallab-1.0.0-py3-none-any.whl
patchwatch setup
patchwatch demo
```

Only `setup` builds trusted bundled code. Source repositories are never installed on the host. Docker must be running before execution; `patchwatch doctor` checks the prerequisites. A wheel installation does not automatically publish to PyPI or a package registry.

## GitHub delivery

The repository includes quality/package CI and a separate Docker evaluation regression job. Both use standard Ubuntu runners and immutable action references, read-only checkout tokens, fixed timeouts, cancellation on newer pushes, and no workflow cache. No PAT, cloud secret, model key, or database is needed to run the product.

After both main-branch checks pass, a matching version tag (for example `v1.0.0`) triggers the release workflow. It verifies the package version, reruns quality checks, builds the wheel and source distribution, and publishes them with SHA-256 checksums as GitHub Release assets. Only this tag-triggered job receives permission to write release assets.

## Optional GitHub Pages

The committed `site/index.html` is a portable public sample of real synthetic benchmark evidence. To publish it, enable Pages for the repository and choose an appropriate static deployment workflow or a publishing branch containing that file at its root. Pages is an optional viewer deployment; it cannot run the Docker controller.

Do not upload private-repository evidence to a public Pages site. The shipped sample uses only synthetic fixtures. The viewer's JSON import/export and diff download work offline, with no network or analytics service.

## Updating verification dependencies

The Docker base is pinned to an immutable digest and verification tools have explicit versions. The application environment is committed in `uv.lock`. Update these in a reviewed change, rebuild the sandbox, run the full evaluation suite, and compare with the previous baseline. Do not rebuild or delete an image while evaluations using it are still running.

## Troubleshooting

| Symptom | Action |
|---|---|
| Docker unavailable | Start Docker or your compatible runtime and run `patchwatch doctor` |
| Sandbox image missing | Run `patchwatch setup` |
| Baseline checks fail | Read `tool-results/before-*.log`; fix the project before migrating |
| Missing third-party type stubs | Declare the required stub package in the target's dependency set |
| Source-only package cannot resolve | Use a published wheel or review a dedicated build integration |
| Stale plan | Regenerate the plan after repository changes |
| Existing output directory | Choose a fresh run/evaluation output directory |
| Command unavailable in a macOS editable checkout | Use `uv run python -m patchwatch.cli ...`, or install the built wheel |
| Benchmark infrastructure error | Check Docker resource availability and PyPI connectivity; do not count it as a correct scenario escalation |

A killed controller can leave `pw-`-prefixed Docker resources. Inspect resources labeled `app=patchwatch` and remove only those from abandoned runs. Normal completion and command timeouts clean up their own containers and dependency volumes.
