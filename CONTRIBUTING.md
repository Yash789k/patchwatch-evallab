# Contributing

Use Python 3.12+, uv, and Docker. Run `make setup`, then `make check`. Run `make eval` for the real container benchmark.

A new migration recipe needs a source/target fixture, baseline verification, tests for ambiguous syntax and protected files, an official reference, and evidence that the final patch passes checks. Keep recipes narrow; unsupported behavior must escalate with a useful reason. Never change tests merely to make an upgrade appear successful.

Changes to the policy engine or sandbox need adversarial regression coverage. Do not introduce shell tools, credential forwarding, networked test execution, unapproved source writes, or automatic external actions. Document any support-boundary changes and compare the benchmark to the committed baseline.

Reports, fixtures, and documentation must distinguish measured outcomes from targets. Do not commit private run bundles or credentials. All new contributions are under the GPL-3.0 license.
