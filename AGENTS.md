# Repository Guidelines

## Project Structure & Module Organization
Source code lives in `autopapers/`. The CLI entrypoint is `autopapers/cli.py`, the ingestion workflow is in `autopapers/pipeline.py`, and integrations are split by concern: fetchers in `autopapers/fetchers/`, Obsidian writers in `autopapers/obsidian.py`, LLM enrichment in `autopapers/llm.py`, and persisted run state in `autopapers/state.py`. Shared models and helpers live in `autopapers/models.py`, `autopapers/config.py`, `autopapers/http.py`, and `autopapers/utils.py`.

Tests live in `tests/`, with sample API payloads under `tests/fixtures/`. Use `config.example.yaml` as the starting point for local configuration.

## Build, Test, and Development Commands
- `python3 -m pip install -e .` installs the package locally and exposes the `autopapers` console script.
- `python3 -m unittest discover -s tests -v` runs the full test suite.
- `python3 -m compileall autopapers` performs a quick syntax check across the package.
- `python3 -m autopapers.cli --settings --config config.yaml` launches the interactive settings wizard for writing `config.yaml`.
- `python3 -m autopapers.cli doctor --config config.example.yaml` validates config structure and local prerequisites.
- `python3 -m autopapers.cli run-daily --config config.yaml` runs the daily fetch pipeline against your real config.
- `python3 -m autopapers.cli backfill --config config.yaml --days 3` replays a recent history window with the same filtering and write path.

## Coding Style & Naming Conventions
Target Python is `>=3.12`. Follow PEP 8 with 4-space indentation, explicit type hints, and small focused functions. Prefer `snake_case` for functions, variables, and modules; `PascalCase` for dataclasses and other classes. Keep modules single-purpose and push source-specific logic into `autopapers/fetchers/` instead of branching centrally. No formatter or linter is configured yet, so keep changes consistent with the existing standard-library-first style.

## Testing Guidelines
This repository uses `unittest`. Add tests next to the relevant area as `tests/test_<feature>.py`, and keep fixtures small and deterministic in `tests/fixtures/`. Cover parser edge cases, filter behavior, deduplication, and Obsidian write semantics when changing ingestion logic. Run the full suite before opening a PR.

## Commit & Pull Request Guidelines
Use short imperative commit subjects such as `Improve incremental fetch coverage`. Keep commits scoped to one logical change. PRs should include a brief summary, config or environment impacts, and the exact verification commands you ran. If a change affects note output, include a short Markdown example or sample file path.

## Security & Configuration Tips
Do not commit secrets, real Obsidian vault paths, or API keys. Use environment variables such as `MINIMAX_API_KEY` or `OPENAI_API_KEY`, and keep personal settings in an untracked `config.yaml` derived from `config.example.yaml`.
