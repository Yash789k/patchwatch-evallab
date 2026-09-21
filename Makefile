.PHONY: setup check test eval demo build viewer
setup:
	uv sync --frozen --python 3.12
	uv run python -m patchwatch.cli setup
check:
	uv run ruff check patchwatch tests
	uv run ruff format --check patchwatch tests
	uv run mypy
	uv run python -m pytest -q -m 'not docker'
test:
	uv run python -m pytest -q
eval:
	uv run python -m patchwatch.cli eval --output artifacts/eval
	uv run python -m patchwatch.cli eval compare --baseline evallab/baseline.json --candidate artifacts/eval/evaluation.json
demo:
	uv run python -m patchwatch.cli demo
build:
	uv build
viewer:
	uv run python -m http.server 8765 --bind 127.0.0.1 --directory site
