from __future__ import annotations

import getpass
import os
import re
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import yaml

from autopapers.config import ConfigError, load_config

Emitter = Callable[[str], None]
InputFunc = Callable[[str], str]
SecretInputFunc = Callable[[str], str]

_SCHEDULE_PATTERN = re.compile(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})$")
_PROVIDER_ALIASES = {
    "minimax": "minimax",
    "openai": "openai",
    "rule_based": "rule_based",
    "rule-based": "rule_based",
    "rulebased": "rule_based",
}
_PROVIDER_DEFAULTS = {
    "minimax": {
        "model": "MiniMax-M2.5",
        "api_key_env": "MINIMAX_API_KEY",
        "base_url": "https://api.minimaxi.com/v1",
    },
    "openai": {
        "model": "gpt-5-mini",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": None,
    },
    "rule_based": {
        "model": "rule_based",
        "api_key_env": "",
        "base_url": None,
    },
}


def run_settings_wizard(
    config_path: Path,
    *,
    input_func: InputFunc = input,
    secret_input_func: SecretInputFunc | None = None,
    emit: Emitter = print,
) -> int:
    config_path = config_path.expanduser().resolve()
    secret_input = secret_input_func or getpass.getpass
    env_path = config_path.parent / ".env"
    env_values = _load_env_map(env_path)
    raw = _load_existing_raw(config_path, emit=emit)

    emit(f"配置向导已启动: {config_path}")
    emit("直接回车表示保留当前值。列表字段使用英文逗号分隔。")
    emit("相对路径会按当前 config.yaml 所在目录解析。")
    emit("当你选择 OpenAI 或 MiniMax 时，向导可以顺手把 API key 写入同目录的 .env。")

    _prompt_general_settings(input_func, raw, emit=emit)
    _prompt_llm_settings(input_func, secret_input, raw.setdefault("llm", {}), env_values, env_path=env_path, emit=emit)
    _prompt_filter_settings(input_func, raw.setdefault("filters", {}), emit=emit)
    _prompt_source_settings(input_func, raw.setdefault("sources", {}), emit=emit)

    while True:
        try:
            _validate_and_write(config_path, raw, env_values=env_values, emit=emit)
            emit(f"配置文件已更新: {config_path}")
            return 0
        except ConfigError as exc:
            message = str(exc)
            emit(f"配置校验失败: {message}")
            _repair_invalid_config(
                input_func,
                secret_input,
                raw,
                env_values,
                env_path=env_path,
                error_message=message,
                emit=emit,
            )


def _load_existing_raw(config_path: Path, *, emit: Emitter) -> dict:
    if not config_path.exists():
        return _default_raw_config()
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        emit(f"现有配置解析失败，将从默认模板开始: {exc}")
        return _default_raw_config()
    if not isinstance(loaded, dict):
        emit("现有配置格式不是字典，将从默认模板开始。")
        return _default_raw_config()
    return _merge_defaults(_default_raw_config(), loaded)


def _default_raw_config() -> dict:
    return {
        "obsidian_root": "/path/to/your/obsidian/Papers",
        "literature_dir": "01 Literature",
        "concepts_dir": "02 Concepts",
        "state_dir": ".autopapers/state",
        "timezone": "Asia/Shanghai",
        "schedule": "08:00",
        "incremental_overlap_hours": 12,
        "llm": {
            "provider": "minimax",
            "model": "MiniMax-M2.5",
            "api_key_env": "MINIMAX_API_KEY",
            "base_url": "https://api.minimaxi.com/v1",
            "timeout_seconds": 60,
        },
        "filters": {
            "include_keywords": [],
            "exclude_keywords": [],
            "concepts_max_per_paper": 5,
        },
        "sources": {
            "arxiv": {
                "enabled": True,
                "queries": [
                    {
                        "name": "test",
                        "search_query": 'all:"vision-language-action"',
                        "max_results": 2,
                    }
                ],
            },
            "openreview": {
                "enabled": False,
                "venues": [
                    {
                        "name": "iclr-2026",
                        "invitation": "ICLR.cc/2026/Conference/-/Submission",
                        "limit": 20,
                    }
                ],
            },
        },
    }


def _merge_defaults(defaults: dict, loaded: dict) -> dict:
    merged: dict = {}
    for key, default_value in defaults.items():
        if key not in loaded:
            merged[key] = default_value
            continue
        loaded_value = loaded[key]
        if isinstance(default_value, dict) and isinstance(loaded_value, dict):
            merged[key] = _merge_defaults(default_value, loaded_value)
        else:
            merged[key] = loaded_value
    for key, loaded_value in loaded.items():
        if key not in merged:
            merged[key] = loaded_value
    return merged


def _prompt_general_settings(input_func: InputFunc, raw: dict, *, emit: Emitter) -> None:
    _emit_section(
        emit,
        "基础设置",
        [
            "Obsidian 根目录必须指向真实知识库目录。",
            "时区示例: Asia/Shanghai、UTC。",
            "计划执行时间使用 24 小时制 HH:MM，例如 08:00。",
            "增量回看小时数常见值是 6 到 12，用于降低边界漏抓。",
        ],
    )
    raw["obsidian_root"] = _prompt_required_text(input_func, "Obsidian 根目录", raw.get("obsidian_root", ""))
    raw["literature_dir"] = _prompt_required_text(input_func, "Literature 目录", raw.get("literature_dir", "01 Literature"))
    raw["concepts_dir"] = _prompt_required_text(input_func, "Concepts 目录", raw.get("concepts_dir", "02 Concepts"))
    raw["state_dir"] = _prompt_required_text(input_func, "状态目录", raw.get("state_dir", ".autopapers/state"))
    raw["timezone"] = _prompt_timezone(input_func, "时区", raw.get("timezone", "Asia/Shanghai"))
    raw["schedule"] = _prompt_schedule(input_func, "计划执行时间", raw.get("schedule", "08:00"))
    raw["incremental_overlap_hours"] = _prompt_int(
        input_func,
        "增量回看小时数",
        raw.get("incremental_overlap_hours", 12),
        minimum=0,
    )


def _prompt_llm_settings(
    input_func: InputFunc,
    secret_input_func: SecretInputFunc,
    llm: dict,
    env_values: dict[str, str],
    *,
    env_path: Path,
    emit: Emitter,
) -> None:
    _emit_section(
        emit,
        "LLM 设置",
        [
            "provider 支持 minimax、openai、rule_based。",
            "切换 provider 后会自动带出推荐的 model、api_key_env 和 base_url。",
            "API key 会写入 .env，不会写进 config.yaml。",
        ],
    )
    previous_provider = _normalize_provider(str(llm.get("provider", "minimax"))) or "minimax"
    provider = _prompt_choice(
        input_func,
        "LLM provider",
        previous_provider,
        choices=_PROVIDER_ALIASES,
    )
    llm["provider"] = provider

    defaults = _PROVIDER_DEFAULTS[provider]
    provider_changed = provider != previous_provider
    model_default = defaults["model"] if provider_changed else str(llm.get("model", defaults["model"]))
    api_key_env_default = defaults["api_key_env"] if provider_changed else str(llm.get("api_key_env", defaults["api_key_env"]))
    base_url_default = defaults["base_url"] if provider_changed else llm.get("base_url", defaults["base_url"])

    llm["model"] = _prompt_required_text(input_func, "LLM model", model_default)
    llm["timeout_seconds"] = _prompt_int(
        input_func,
        "LLM 超时秒数",
        llm.get("timeout_seconds", 60),
        minimum=1,
    )

    if provider == "rule_based":
        llm["api_key_env"] = ""
        llm["base_url"] = None
        emit("rule_based 不需要 API key，已跳过供应商密钥配置。")
        return

    llm["api_key_env"] = _prompt_required_text(input_func, "API key 环境变量名", api_key_env_default)
    llm["base_url"] = _prompt_optional_text(input_func, "LLM base_url", base_url_default)

    _prompt_api_key_settings(
        input_func,
        secret_input_func,
        env_values,
        llm["api_key_env"],
        env_path=env_path,
        emit=emit,
    )


def _prompt_api_key_settings(
    input_func: InputFunc,
    secret_input_func: SecretInputFunc,
    env_values: dict[str, str],
    env_name: str,
    *,
    env_path: Path,
    emit: Emitter,
) -> None:
    file_value = env_values.get(env_name)
    runtime_value = os.environ.get(env_name)

    emit("API key 输入时不会回显；直接回车会尽量保留现有值。")

    if file_value:
        emit(f".env 中已存在 {env_name}: {_mask_secret(file_value)}")
    elif runtime_value:
        emit(f"当前 shell 中已存在 {env_name}: {_mask_secret(runtime_value)}")

    should_store = _prompt_bool(
        input_func,
        f"写入或更新 {env_name} 到 {env_path.name}",
        default=not bool(file_value),
    )
    if not should_store:
        if not file_value and not runtime_value:
            emit(f"未设置 {env_name}，后续 doctor 可能提示缺失。")
        return

    prompt = f"{env_name} 的 API key [直接回车保留当前值]: " if (file_value or runtime_value) else f"{env_name} 的 API key: "
    value = secret_input_func(prompt).strip()
    if value:
        env_values[env_name] = value
        emit(f"已记录 {env_name}，保存配置时会同步写入 {env_path.name}。")
        return
    if file_value:
        emit(f"保留 {env_path.name} 中现有的 {env_name}。")
        return
    if runtime_value:
        env_values[env_name] = runtime_value
        emit(f"已把当前环境中的 {env_name} 同步到 {env_path.name}。")
        return
    emit(f"未写入 {env_name}，后续 doctor 可能提示缺失。")


def _prompt_filter_settings(input_func: InputFunc, filters: dict, *, emit: Emitter) -> None:
    _emit_section(
        emit,
        "过滤规则",
        [
            "include_keywords 和 exclude_keywords 都是标题/摘要的子串匹配。",
            "建议优先使用稳定短语，例如 gaussian splatting、vision-language-action。",
            "如果 include_keywords 留空，候选论文只受来源范围限制。",
        ],
    )
    filters["include_keywords"] = _prompt_list(
        input_func,
        "include_keywords",
        filters.get("include_keywords", []),
    )
    filters["exclude_keywords"] = _prompt_list(
        input_func,
        "exclude_keywords",
        filters.get("exclude_keywords", []),
    )
    filters["concepts_max_per_paper"] = _prompt_int(
        input_func,
        "每篇论文最多概念卡数",
        filters.get("concepts_max_per_paper", 5),
        minimum=1,
    )


def _prompt_source_settings(input_func: InputFunc, sources: dict, *, emit: Emitter) -> None:
    _emit_section(
        emit,
        "数据源",
        [
            "至少启用一个来源，并配置对应的 query 或 venue。",
            "arXiv search_query 使用官方格式，例如 all:\"vision-language-action\" 或 cat:cs.CV。",
            "每个 arXiv query 的 max_results 是总抓取预算，不是单页上限。",
            "OpenReview invitation 如果不可公开访问，运行时可能返回 403。",
        ],
    )
    arxiv = sources.setdefault("arxiv", {})
    arxiv["enabled"] = _prompt_bool(input_func, "启用 arXiv", bool(arxiv.get("enabled", True)))
    if arxiv["enabled"]:
        arxiv["queries"] = _prompt_arxiv_queries(input_func, arxiv.get("queries", []))
    elif not isinstance(arxiv.get("queries"), list):
        arxiv["queries"] = []

    openreview = sources.setdefault("openreview", {})
    openreview["enabled"] = _prompt_bool(input_func, "启用 OpenReview", bool(openreview.get("enabled", False)))
    if openreview["enabled"]:
        openreview["venues"] = _prompt_openreview_venues(input_func, openreview.get("venues", []))
    elif not isinstance(openreview.get("venues"), list):
        openreview["venues"] = []


def _repair_invalid_config(
    input_func: InputFunc,
    secret_input_func: SecretInputFunc,
    raw: dict,
    env_values: dict[str, str],
    *,
    env_path: Path,
    error_message: str,
    emit: Emitter,
) -> None:
    if error_message.startswith("Invalid timezone:"):
        raw["timezone"] = _prompt_timezone(input_func, "时区", raw.get("timezone", "Asia/Shanghai"))
        return
    if error_message.startswith("Invalid schedule:"):
        raw["schedule"] = _prompt_schedule(input_func, "计划执行时间", raw.get("schedule", "08:00"))
        return
    if error_message == "obsidian_root is required":
        raw["obsidian_root"] = _prompt_required_text(input_func, "Obsidian 根目录", raw.get("obsidian_root", ""))
        return
    if error_message == "literature_dir is required":
        raw["literature_dir"] = _prompt_required_text(input_func, "Literature 目录", raw.get("literature_dir", "01 Literature"))
        return
    if error_message == "concepts_dir is required":
        raw["concepts_dir"] = _prompt_required_text(input_func, "Concepts 目录", raw.get("concepts_dir", "02 Concepts"))
        return
    if error_message == "state_dir is required":
        raw["state_dir"] = _prompt_required_text(input_func, "状态目录", raw.get("state_dir", ".autopapers/state"))
        return
    if error_message.startswith("incremental_overlap_hours"):
        raw["incremental_overlap_hours"] = _prompt_int(
            input_func,
            "增量回看小时数",
            raw.get("incremental_overlap_hours", 12),
            minimum=0,
        )
        return
    if error_message.startswith("filters.concepts_max_per_paper"):
        filters = raw.setdefault("filters", {})
        filters["concepts_max_per_paper"] = _prompt_int(
            input_func,
            "每篇论文最多概念卡数",
            filters.get("concepts_max_per_paper", 5),
            minimum=1,
        )
        return
    if (
        error_message.startswith("Unsupported llm.provider:")
        or error_message.startswith("Missing API environment variable name")
        or error_message.startswith("llm.timeout_seconds")
    ):
        _prompt_llm_settings(
            input_func,
            secret_input_func,
            raw.setdefault("llm", {}),
            env_values,
            env_path=env_path,
            emit=emit,
        )
        return
    if (
        error_message == "At least one source query or venue must be configured"
        or error_message.startswith("At least one arXiv query")
        or error_message.startswith("At least one OpenReview venue")
        or error_message.startswith("arxiv query ")
        or error_message.startswith("openreview venue ")
    ):
        emit("将重新询问数据源设置。")
        _prompt_source_settings(input_func, raw.setdefault("sources", {}), emit=emit)
        return

    emit("无法自动定位错误字段，将重新进入完整配置向导。")
    _prompt_general_settings(input_func, raw, emit=emit)
    _prompt_llm_settings(
        input_func,
        secret_input_func,
        raw.setdefault("llm", {}),
        env_values,
        env_path=env_path,
        emit=emit,
    )
    _prompt_filter_settings(input_func, raw.setdefault("filters", {}), emit=emit)
    _prompt_source_settings(input_func, raw.setdefault("sources", {}), emit=emit)


def _prompt_required_text(input_func: InputFunc, label: str, default: object) -> str:
    while True:
        value = _prompt_text(input_func, label, default).strip()
        if value:
            return value
        print(f"{label} 不能为空。")


def _prompt_text(input_func: InputFunc, label: str, default: object) -> str:
    prompt = f"{label} [{default}]: " if str(default) else f"{label}: "
    value = input_func(prompt).strip()
    return value or str(default)


def _prompt_optional_text(input_func: InputFunc, label: str, default: object | None) -> str | None:
    shown_default = "" if default is None else str(default)
    prompt = f"{label} [{shown_default}]: " if shown_default else f"{label} [留空表示不设置]: "
    value = input_func(prompt).strip()
    if value:
        return value
    return None if default in (None, "") else str(default)


def _prompt_timezone(input_func: InputFunc, label: str, default: object) -> str:
    while True:
        value = _prompt_required_text(input_func, label, default)
        try:
            ZoneInfo(value)
        except Exception:
            print("时区无效，例如 Asia/Shanghai 或 UTC。")
            continue
        return value


def _prompt_schedule(input_func: InputFunc, label: str, default: object) -> str:
    while True:
        value = _prompt_required_text(input_func, label, default)
        match = _SCHEDULE_PATTERN.match(value)
        if not match:
            print("计划执行时间格式必须是 HH:MM，例如 08:00。")
            continue
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        if hour > 23 or minute > 59:
            print("计划执行时间格式必须是 HH:MM，例如 08:00。")
            continue
        return f"{hour:02d}:{minute:02d}"


def _prompt_int(input_func: InputFunc, label: str, default: object, *, minimum: int) -> int:
    while True:
        raw = _prompt_text(input_func, label, default)
        try:
            value = int(raw)
        except ValueError:
            print(f"{label} 必须是整数。")
            continue
        if value < minimum:
            print(f"{label} 必须 >= {minimum}。")
            continue
        return value


def _prompt_bool(input_func: InputFunc, label: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input_func(f"{label} [{suffix}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes", "1", "true", "on", "是", "开启"}:
            return True
        if raw in {"n", "no", "0", "false", "off", "否", "关闭"}:
            return False
        print("请输入 y 或 n。")


def _prompt_choice(input_func: InputFunc, label: str, default: str, choices: dict[str, str]) -> str:
    shown_choices = "/".join(sorted(set(choices.values())))
    normalized_default = choices.get(default.strip().lower(), default)
    while True:
        value = _prompt_text(input_func, f"{label} ({shown_choices})", normalized_default).strip().lower()
        normalized = choices.get(value)
        if normalized:
            return normalized
        print(f"{label} 必须是以下之一: {shown_choices}")


def _prompt_list(input_func: InputFunc, label: str, default: object) -> list[str]:
    default_items = default if isinstance(default, list) else []
    shown_default = ", ".join(str(item) for item in default_items)
    raw = input_func(f"{label}（英文逗号分隔） [{shown_default}]: ").strip()
    if not raw:
        return [str(item).strip() for item in default_items if str(item).strip()]
    normalized = raw.replace("，", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _prompt_arxiv_queries(input_func: InputFunc, existing: object) -> list[dict]:
    existing_queries = existing if isinstance(existing, list) else []
    count = _prompt_int(input_func, "arXiv query 数量", len(existing_queries) or 1, minimum=1)
    queries: list[dict] = []
    for index in range(count):
        current = existing_queries[index] if index < len(existing_queries) and isinstance(existing_queries[index], dict) else {}
        queries.append(
            {
                "name": _prompt_required_text(
                    input_func,
                    f"arXiv query {index + 1} 名称",
                    current.get("name", f"query-{index + 1}"),
                ),
                "search_query": _prompt_required_text(
                    input_func,
                    f"arXiv query {index + 1} search_query",
                    current.get("search_query", 'all:"vision-language-action"'),
                ),
                "max_results": _prompt_int(
                    input_func,
                    f"arXiv query {index + 1} max_results",
                    current.get("max_results", 20),
                    minimum=1,
                ),
            }
        )
    return queries


def _prompt_openreview_venues(input_func: InputFunc, existing: object) -> list[dict]:
    existing_venues = existing if isinstance(existing, list) else []
    count = _prompt_int(input_func, "OpenReview venue 数量", len(existing_venues) or 1, minimum=1)
    venues: list[dict] = []
    for index in range(count):
        current = existing_venues[index] if index < len(existing_venues) and isinstance(existing_venues[index], dict) else {}
        venues.append(
            {
                "name": _prompt_required_text(
                    input_func,
                    f"OpenReview venue {index + 1} 名称",
                    current.get("name", f"venue-{index + 1}"),
                ),
                "invitation": _prompt_required_text(
                    input_func,
                    f"OpenReview venue {index + 1} invitation",
                    current.get("invitation", "ICLR.cc/2026/Conference/-/Submission"),
                ),
                "limit": _prompt_int(
                    input_func,
                    f"OpenReview venue {index + 1} limit",
                    current.get("limit", 20),
                    minimum=1,
                ),
            }
        )
    return venues


def _validate_and_write(config_path: Path, raw: dict, *, env_values: dict[str, str], emit: Emitter) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_temp_path = _transaction_path(config_path, "tmp")
    with config_temp_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(raw, handle, allow_unicode=True, sort_keys=False)
    try:
        load_config(config_temp_path)
        staged_files: list[tuple[Path, Path]] = []
        if env_values:
            env_path = config_path.parent / ".env"
            env_temp_path = _transaction_path(env_path, "tmp")
            env_temp_path.write_text(_render_env_map(env_values), encoding="utf-8")
            staged_files.append((env_path, env_temp_path))
        staged_files.append((config_path, config_temp_path))
        _commit_transaction(staged_files)
    except Exception:
        config_temp_path.unlink(missing_ok=True)
        _transaction_path(config_path.parent / ".env", "tmp").unlink(missing_ok=True)
        raise
    emit("配置校验通过。")


def _load_env_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
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
        if key:
            values[key] = _strip_env_quotes(value)
    return values


def _render_env_map(env_values: dict[str, str]) -> str:
    lines = [f"{key}={_quote_env_value(value)}" for key, value in env_values.items()]
    return "\n".join(lines) + "\n"


def _quote_env_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _mask_secret(value: str) -> str:
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}...{value[-3:]}"


def _normalize_provider(value: str) -> str | None:
    return _PROVIDER_ALIASES.get(value.strip().lower())


def _emit_section(emit: Emitter, title: str, hints: list[str]) -> None:
    emit(f"--- {title} ---")
    for hint in hints:
        emit(f"- {hint}")


def _commit_transaction(staged_files: list[tuple[Path, Path]]) -> None:
    backups: list[tuple[Path, Path | None, bool]] = []
    committed_targets: set[Path] = set()
    try:
        for target, _staged in staged_files:
            existed = target.exists()
            backup = _transaction_path(target, "bak")
            backup.unlink(missing_ok=True)
            if existed:
                _replace_path(target, backup)
                backups.append((target, backup, True))
            else:
                backups.append((target, None, False))

        for target, staged in staged_files:
            _replace_path(staged, target)
            committed_targets.add(target)
    except Exception:
        _rollback_transaction(staged_files, backups, committed_targets)
        raise
    else:
        for _target, backup, _existed in backups:
            if backup is not None:
                backup.unlink(missing_ok=True)


def _rollback_transaction(
    staged_files: list[tuple[Path, Path]],
    backups: list[tuple[Path, Path | None, bool]],
    committed_targets: set[Path],
) -> None:
    staged_lookup = {target: staged for target, staged in staged_files}
    for target, backup, existed in reversed(backups):
        staged = staged_lookup[target]
        if staged.exists():
            staged.unlink(missing_ok=True)
        if backup is not None:
            target.unlink(missing_ok=True)
            _replace_path(backup, target)
            continue
        if not existed and target in committed_targets:
            target.unlink(missing_ok=True)


def _transaction_path(target: Path, suffix: str) -> Path:
    return target.with_name(f"{target.name}.txn.{suffix}")


def _replace_path(source: Path, target: Path) -> None:
    source.replace(target)
