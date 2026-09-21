# Running without a service bill

Reviewed on 2026-09-22. The shipped default requires no paid model, cloud account, hosted database, or persistent web server. Local compute, electricity, disk, and internet access are still your responsibility.

| Option | Fit for this product | Cost control / decision |
|---|---|---|
| Local Docker + CLI + HTML | Full product, including migrations and benchmarks | Default. No recurring application service charge. Use Docker Engine on Linux or a free local container runtime compatible with the Docker CLI. |
| Public GitHub repository + standard Ubuntu Actions runner | Reproducible CI and benchmark execution | Recommended shipping path. Standard runner minutes are free for public repositories. Artifacts still share an account storage allowance. |
| GitHub Pages | Public static evidence viewer and documentation | Optional; no server backend. Pages cannot run the maintenance agent itself. |
| Private GitHub repository | Private code and CI | Free account quotas apply; included private-repo minutes/storage are finite. Leave paid overages disabled and avoid automatic schedules. |
| Codespaces | Convenient dev environment | Finite included compute/storage; not used by default. |
| Vercel/Netlify/Cloudflare static hosting | Viewer hosting | Unnecessary extra account. Their serverless functions do not provide the required Docker execution boundary. |
| Small cloud VM / hosted container job | Remote worker | Often billable or free credits expire; not provisioned. |
| Hosted LLM APIs | Broader speculative repair capability | Optional future adapter, deliberately absent from the required path. |
| Local Ollama/model | Zero API bill, but substantial local compute and weaker reproducibility | Consider only after adding evaluation and policy coverage; not required for v1. |
| Streamlit + hosted database | Multi-user dashboard | Adds operational services without improving patch safety. Static viewer ships instead. |

## GitHub controls in this repository

- Use standard `ubuntu-latest`, no paid larger runners.
- CI runs on push/PR and manual dispatch; no scheduled benchmark loop.
- Jobs have timeouts and concurrency cancellation.
- Artifact uploads retain evidence for one day, and only verification artifacts are uploaded.
- Cache storage is not used by the workflows.
- Workflow permissions default to read-only. PR jobs receive no application secrets.
- Actions are pinned to immutable commit SHAs.

Account-wide storage and other repositories may consume the same allowance. A repository cannot enforce an account spending cap. In GitHub billing settings, keep Actions budgets configured to stop usage rather than allow paid overages. This build does not change your billing settings or attach a payment method.

Official references:

- [GitHub Actions billing and included quotas](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
- [Docker Engine security](https://docs.docker.com/engine/security/)
- [Docker Desktop license terms](https://docs.docker.com/subscription/desktop-license/)

## Dependency metadata and supply chain

A cold build downloads the pinned container base and verification tools. Each run resolves before/after wheels from PyPI. Versions in fixtures intentionally reproduce historical migrations. They are not recommendations to install those old versions in a new production application. `patchwatch scan --online` retrieves current non-yanked stable releases for supported packages; `plan` still checks the support boundary before any execution.
