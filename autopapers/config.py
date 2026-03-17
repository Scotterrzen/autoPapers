from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml


class ConfigError(ValueError):
    """Raised when the user config is missing required values."""


@dataclass(slots=True)
class ArxivQueryConfig:
    name: str
    search_query: str
    max_results: int = 50


@dataclass(slots=True)
class OpenReviewVenueConfig:
    name: str
    invitation: str
    limit: int = 50


@dataclass(slots=True)
class ArxivSourceConfig:
    enabled: bool = True
    queries: list[ArxivQueryConfig] = field(default_factory=list)


@dataclass(slots=True)
class OpenReviewSourceConfig:
    enabled: bool = True
    venues: list[OpenReviewVenueConfig] = field(default_factory=list)


@dataclass(slots=True)
class SourceConfig:
    arxiv: ArxivSourceConfig = field(default_factory=ArxivSourceConfig)
    openreview: OpenReviewSourceConfig = field(default_factory=OpenReviewSourceConfig)


@dataclass(slots=True)
class LLMConfig:
    provider: str = "openai"
    model: str = "gpt-5-mini"
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None
    timeout_seconds: int = 60


@dataclass(slots=True)
class FilterConfig:
    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    concepts_max_per_paper: int = 5


@dataclass(slots=True)
class AppConfig:
    config_path: Path
    obsidian_root: Path
    literature_dir: Path
    concepts_dir: Path
    state_dir: Path
    timezone: str = "Asia/Shanghai"
    schedule: str = "08:00"
    llm: LLMConfig = field(default_factory=LLMConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    sources: SourceConfig = field(default_factory=SourceConfig)

    @property
    def literature_path(self) -> Path:
        return self.obsidian_root / self.literature_dir

    @property
    def concepts_path(self) -> Path:
        return self.obsidian_root / self.concepts_dir

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(f"Config file does not exist: {config_path}")

    _load_env_file(config_path.parent / ".env")

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    base_dir = config_path.parent

    obsidian_root = _resolve_path(raw.get("obsidian_root"), base_dir, required=True)
    literature_dir = Path(raw.get("literature_dir", "01 Literature"))
    concepts_dir = Path(raw.get("concepts_dir", "02 Concepts"))
    state_dir = _resolve_path(raw.get("state_dir", ".autopapers/state"), base_dir, required=True)

    llm_raw = raw.get("llm", {}) or {}
    llm = LLMConfig(
        provider=str(llm_raw.get("provider", "openai")),
        model=str(llm_raw.get("model", "gpt-5-mini")),
        api_key_env=str(llm_raw.get("api_key_env", "OPENAI_API_KEY")),
        base_url=str(llm_raw["base_url"]) if llm_raw.get("base_url") else None,
        timeout_seconds=int(llm_raw.get("timeout_seconds", 60)),
    )

    filter_raw = raw.get("filters", {}) or {}
    filters = FilterConfig(
        include_keywords=[str(item) for item in filter_raw.get("include_keywords", [])],
        exclude_keywords=[str(item) for item in filter_raw.get("exclude_keywords", [])],
        concepts_max_per_paper=int(filter_raw.get("concepts_max_per_paper", 5)),
    )

    sources_raw = raw.get("sources", {}) or {}
    arxiv_raw = sources_raw.get("arxiv", {}) or {}
    openreview_raw = sources_raw.get("openreview", {}) or {}

    arxiv = ArxivSourceConfig(
        enabled=bool(arxiv_raw.get("enabled", True)),
        queries=[
            ArxivQueryConfig(
                name=str(item["name"]),
                search_query=str(item["search_query"]),
                max_results=int(item.get("max_results", 50)),
            )
            for item in arxiv_raw.get("queries", [])
        ],
    )

    openreview = OpenReviewSourceConfig(
        enabled=bool(openreview_raw.get("enabled", True)),
        venues=[
            OpenReviewVenueConfig(
                name=str(item["name"]),
                invitation=str(item["invitation"]),
                limit=int(item.get("limit", 50)),
            )
            for item in openreview_raw.get("venues", [])
        ],
    )

    config = AppConfig(
        config_path=config_path,
        obsidian_root=obsidian_root,
        literature_dir=literature_dir,
        concepts_dir=concepts_dir,
        state_dir=state_dir,
        timezone=str(raw.get("timezone", "Asia/Shanghai")),
        schedule=str(raw.get("schedule", "08:00")),
        llm=llm,
        filters=filters,
        sources=SourceConfig(arxiv=arxiv, openreview=openreview),
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    if not config.obsidian_root:
        raise ConfigError("obsidian_root is required")
    if config.filters.concepts_max_per_paper < 1:
        raise ConfigError("filters.concepts_max_per_paper must be >= 1")
    if config.llm.provider not in {"openai", "rule_based", "minimax"}:
        raise ConfigError(f"Unsupported llm.provider: {config.llm.provider}")
    has_arxiv = config.sources.arxiv.enabled and bool(config.sources.arxiv.queries)
    has_openreview = config.sources.openreview.enabled and bool(config.sources.openreview.venues)
    if not has_arxiv and not has_openreview:
        raise ConfigError("At least one source query or venue must be configured")


def _resolve_path(value: str | None, base_dir: Path, *, required: bool) -> Path:
    if value is None:
        if required:
            raise ConfigError("Missing required path value")
        return base_dir
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        os.environ.setdefault(key, _strip_env_quotes(value))


def _strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
