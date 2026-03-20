from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from autopapers.config import ConfigError, load_config
from autopapers.pipeline import PaperPipeline
from autopapers.state import StateStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Daily paper ingestion for Obsidian")
    parser.add_argument("--log-level", default="INFO")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_daily = subparsers.add_parser(
        "run-daily",
        help="Fetch new papers since the last successful run, with overlap protection",
    )
    run_daily.add_argument("--config", default="config.yaml")
    run_daily.add_argument("--now", help="Override current time in ISO-8601")

    backfill = subparsers.add_parser("backfill", help="Fetch papers from the last N days")
    backfill.add_argument("--config", default="config.yaml")
    backfill.add_argument("--days", type=int, required=True)
    backfill.add_argument("--now", help="Override current time in ISO-8601")

    doctor = subparsers.add_parser("doctor", help="Validate configuration and local environment")
    doctor.add_argument("--config", default="config.yaml")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO))
    try:
        if args.command == "doctor":
            return _run_doctor(Path(args.config))
        config = load_config(args.config)
        pipeline = PaperPipeline(config)
        now = _parse_now(getattr(args, "now", None))
        if args.command == "run-daily":
            result = pipeline.run_daily(now=now)
        elif args.command == "backfill":
            result = pipeline.backfill(days=args.days, now=now)
        else:  # pragma: no cover - argparse prevents this
            parser.error(f"Unsupported command: {args.command}")
            return 2
        print(
            f"fetched={result.fetched} written={result.written} "
            f"skipped={result.skipped} failed={result.failed}"
        )
        return 0 if result.failed == 0 else 1
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 2
    except Exception as exc:  # pragma: no cover - integration path
        print(f"Fatal error: {exc}")
        return 1


def _run_doctor(config_path: Path) -> int:
    config = load_config(config_path)
    issues: list[str] = []

    for target in (config.obsidian_root, config.literature_path, config.concepts_path, config.state_dir):
        if target.exists():
            continue
        if target in (config.literature_path, config.concepts_path, config.state_dir):
            issues.append(f"Missing directory, will be created on first run: {target}")
        else:
            issues.append(f"Missing obsidian_root: {target}")

    if config.llm.provider in {"openai", "minimax"}:
        if not os.environ.get(config.llm.api_key_env):
            issues.append(f"Missing environment variable: {config.llm.api_key_env}")

    state = StateStore.load(config.state_dir)
    last_success = state.last_success_at()
    print(f"Config: {config.config_path}")
    print(f"Obsidian root: {config.obsidian_root}")
    print(f"Literature dir: {config.literature_path}")
    print(f"Concepts dir: {config.concepts_path}")
    print(f"State dir: {config.state_dir}")
    print(f"Incremental overlap: {config.incremental_overlap_hours}h")
    print(f"Last success: {last_success.isoformat() if last_success else 'never'}")
    if issues:
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("Environment looks ready.")
    return 0


def _parse_now(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
