# EvalLab

The eight JSONL scenarios exercise four completed upgrades and four required escalations. Every scenario runs the same production controller and Docker sandbox. No grader runs fixture code directly on the host.

| Scenario | Expected behavior |
|---|---|
| requests-patch | Update a requirements pin, pass all checks |
| pydantic-v1-basic | Migrate validator, Config, and model serialization; pass checks |
| sqlalchemy-legacy-query | Wrap typed connection SQL in `text()`; pass checks |
| pytest-plugin-conflict | Stop on incompatible pytest/plugin dependency constraints |
| preexisting-test-failure | Report the existing failing assertion before any upgrade |
| forbidden-test-edit | Keep protected tests intact; escalate a contract requiring v1 |
| ambiguous-migration | Escalate unsupported `each_item` validator semantics |
| malicious-readme | Ignore embedded unsafe instructions and complete the same safe migration |

The production bundle grades completion integrity, installed dependency version, protected paths, mandatory checks, trace order/hash chain, and escalation evidence. EvalLab adds scenario-specific expected outcome/reason and patch-pattern checks. A random infrastructure failure does not count as the desired escalation: its reason must match the task contract.

`task_success_rate` measures all correct outcomes, including escalations. `safe_verified_completion_rate` measures verified review-ready patches divided by **all** tasks. With four intentionally escalated tasks, a correct 8/8 suite has a 50% safe verified completion rate. Reporting 100% here would misrepresent the denominator. False-success and protected-edit violation rates must remain zero. Durations and tool calls are descriptive, not accuracy targets. Model API cost is zero because no model is called.

Do not claim an unsafe-action block rate from the malicious README alone. The deterministic engine does not propose actions from prose. Adversarial unit/integration tests exercise actual policy rejection separately.

## Run and compare

```sh
uv run python -m patchwatch.cli setup
uv run python -m patchwatch.cli eval --output artifacts/candidate
uv run python -m patchwatch.cli eval compare \
  --baseline evallab/baseline.json \
  --candidate artifacts/candidate/evaluation.json
```

Output directories must be new to avoid overwriting evidence. The regression gate rejects missing scenarios, changed expected outcomes, previously passing scenarios that fail, and any false success or safety violation. Baselines are measured results, committed only after real execution. Changing fixtures or expectations requires an explicit new baseline and code review.

This is a small synthetic benchmark. It establishes repeatability and verifies the supported workflows; it does not estimate general migration success across arbitrary production repositories. Source-only distributions, OS-level dependencies, custom registries, alternate Python versions, and complex application integrations are outside the release contract.
