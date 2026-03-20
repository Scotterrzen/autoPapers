from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from autopapers.config import LLMConfig
from autopapers.http import HttpClient, HttpError

_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)
_LOW_SIGNAL_KEYWORDS = {
    "ai",
    "artificial intelligence",
    "machine learning",
    "deep learning",
    "multimodal",
    "alignment",
    "reasoning",
    "vision",
    "language",
    "model",
    "models",
    "research",
    "paper",
}
_MIN_INCLUDE_KEYWORDS = 3
_MAX_INCLUDE_KEYWORDS = 20
_MAX_EXCLUDE_KEYWORDS = 8
_MAX_QUERY_COUNT = 3


class ConfigPlannerError(RuntimeError):
    """Raised when automatic settings generation cannot complete safely."""


@dataclass(slots=True)
class PlannerRequest:
    interest_directions: str
    mode: str
    target_papers_per_day: int
    must_track_phrases: list[str]
    avoid_phrases: list[str]


@dataclass(slots=True)
class PlannerArxivQuery:
    name: str
    search_query: str
    max_results: int


@dataclass(slots=True)
class PlannerResult:
    summary: str
    mode: str
    reasoning: str
    include_keywords: list[str]
    exclude_keywords: list[str]
    queries: list[PlannerArxivQuery]


class ConfigPlanner:
    def probe(self, *, api_key_override: str | None = None) -> None:
        raise NotImplementedError

    def plan(self, request: PlannerRequest, *, api_key_override: str | None = None) -> PlannerResult:
        raise NotImplementedError


@dataclass(slots=True)
class OpenAIConfigPlanner(ConfigPlanner):
    config: LLMConfig
    http_client: HttpClient

    def probe(self, *, api_key_override: str | None = None) -> None:
        response = self.http_client.post_json(
            "https://api.openai.com/v1/responses",
            payload={
                "model": self.config.model,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": 'Return {"ok": true} as JSON only.',
                            }
                        ],
                    }
                ],
                "text": {"format": {"type": "json_object"}},
            },
            headers={"Authorization": f"Bearer {self._api_key(api_key_override)}"},
        )
        data = _load_json_content(_extract_openai_text(response))
        if data.get("ok") is not True:
            raise ConfigPlannerError("Provider probe did not return ok=true")

    def plan(self, request: PlannerRequest, *, api_key_override: str | None = None) -> PlannerResult:
        response = self.http_client.post_json(
            "https://api.openai.com/v1/responses",
            payload={
                "model": self.config.model,
                "input": [
                    {
                        "role": "system",
                        "content": [
                            {
                                "type": "input_text",
                                "text": _planner_system_prompt(),
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": _planner_user_prompt(request),
                            }
                        ],
                    },
                ],
                "text": {"format": {"type": "json_object"}},
            },
            headers={"Authorization": f"Bearer {self._api_key(api_key_override)}"},
        )
        return _coerce_planner_result(_load_json_content(_extract_openai_text(response)))

    def _api_key(self, api_key_override: str | None) -> str:
        api_key = api_key_override or os.environ.get(self.config.api_key_env)
        if not api_key:
            raise ConfigPlannerError(f"Missing API key in environment variable {self.config.api_key_env}")
        return api_key


@dataclass(slots=True)
class MiniMaxConfigPlanner(ConfigPlanner):
    config: LLMConfig
    http_client: HttpClient

    def probe(self, *, api_key_override: str | None = None) -> None:
        response = self.http_client.post_json(
            f"{self._base_url()}/chat/completions",
            payload={
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": "Return JSON only."},
                    {"role": "user", "content": 'Return {"ok": true} as JSON only.'},
                ],
                "temperature": 0.0,
            },
            headers={"Authorization": f"Bearer {self._api_key(api_key_override)}"},
        )
        data = _load_json_content(_extract_chat_completion_text(response))
        if data.get("ok") is not True:
            raise ConfigPlannerError("Provider probe did not return ok=true")

    def plan(self, request: PlannerRequest, *, api_key_override: str | None = None) -> PlannerResult:
        response = self.http_client.post_json(
            f"{self._base_url()}/chat/completions",
            payload={
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": _planner_system_prompt()},
                    {"role": "user", "content": _planner_user_prompt(request)},
                ],
                "temperature": 0.2,
            },
            headers={"Authorization": f"Bearer {self._api_key(api_key_override)}"},
        )
        return _coerce_planner_result(_load_json_content(_extract_chat_completion_text(response)))

    def _api_key(self, api_key_override: str | None) -> str:
        api_key = api_key_override or os.environ.get(self.config.api_key_env)
        if not api_key:
            raise ConfigPlannerError(f"Missing API key in environment variable {self.config.api_key_env}")
        return api_key

    def _base_url(self) -> str:
        return (self.config.base_url or "https://api.minimaxi.com/v1").rstrip("/")


def build_config_planner(config: LLMConfig) -> ConfigPlanner:
    if config.provider == "openai":
        return OpenAIConfigPlanner(config=config, http_client=HttpClient(timeout_seconds=config.timeout_seconds))
    if config.provider == "minimax":
        return MiniMaxConfigPlanner(config=config, http_client=HttpClient(timeout_seconds=config.timeout_seconds))
    raise ConfigPlannerError(f"Automatic planning is not available for llm.provider={config.provider}")


def _planner_system_prompt() -> str:
    return (
        "You are generating conservative retrieval configuration for an academic paper ingestion pipeline.\n"
        "Your job is NOT to summarize papers. Your job is to produce executable config.\n"
        "Pipeline behavior:\n"
        "1. arXiv queries retrieve a broad candidate set.\n"
        "2. include_keywords/exclude_keywords then filter title + abstract using case-insensitive substring matching.\n"
        "3. Therefore keywords must be literal phrases likely to appear verbatim in titles or abstracts.\n"
        "Hard requirements:\n"
        "- Return valid JSON only.\n"
        "- Prefer literal technical phrases over abstract themes.\n"
        "- Avoid vague keywords such as ai, multimodal, alignment, reasoning, model, models.\n"
        "- exclude_keywords must be conservative and only remove obvious noise.\n"
        "- Do not generate OpenReview invitations.\n"
        "- Generate at most 3 arXiv queries.\n"
        "- Each arXiv query must use simple syntax with cat: and/or all: terms.\n"
        "- Each query max_results must be between 10 and 40.\n"
        "- include_keywords should contain 8 to 20 items when possible.\n"
        "- exclude_keywords should contain 0 to 8 items.\n"
        "- If the user goal is ambiguous, bias toward precision.\n"
        "Output schema:\n"
        "{"
        '"summary":"...",'
        '"strategy":{"mode":"precision|balanced|recall","reasoning":"..."},'
        '"filters":{"include_keywords":["..."],"exclude_keywords":["..."]},'
        '"sources":{"arxiv":{"queries":[{"name":"short-slug","search_query":"...","max_results":20}]}}'
        "}"
    )


def _planner_user_prompt(request: PlannerRequest) -> str:
    must_track = ", ".join(request.must_track_phrases) if request.must_track_phrases else "无"
    avoid = ", ".join(request.avoid_phrases) if request.avoid_phrases else "无"
    return (
        "请为下面的用户目标生成配置。\n"
        f"- Interested directions: {request.interest_directions}\n"
        f"- Precision preference: {request.mode}\n"
        f"- Target papers per day: {request.target_papers_per_day}\n"
        f"- Known must-track phrases: {must_track}\n"
        f"- Known noise to avoid: {avoid}\n"
        "请记住：include_keywords/exclude_keywords 是标题+摘要的子串匹配；"
        "arXiv queries 应该比 include_keywords 更宽；exclude_keywords 必须保守；"
        "只输出 JSON。"
    )


def _extract_openai_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    chunks: list[str] = []
    for item in response.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text") or content.get("output_text")
            if isinstance(text, str) and text.strip():
                chunks.append(text)
    if not chunks:
        raise ConfigPlannerError("Planner response did not contain text output")
    return "\n".join(chunks)


def _extract_chat_completion_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ConfigPlannerError("Planner response did not contain choices")
    message = choices[0].get("message", {}) or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                chunks.append(item["text"])
        if chunks:
            return "\n".join(chunks)
    raise ConfigPlannerError("Planner response did not contain text content")


def _load_json_content(content: str) -> dict[str, Any]:
    cleaned = _THINK_PATTERN.sub("", content).strip()
    try:
        loaded = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ConfigPlannerError(f"Failed to decode planner JSON output: {cleaned}") from exc
    if not isinstance(loaded, dict):
        raise ConfigPlannerError("Planner output must be a JSON object")
    return loaded


def _coerce_planner_result(data: dict[str, Any]) -> PlannerResult:
    strategy = data.get("strategy", {}) if isinstance(data.get("strategy"), dict) else {}
    filters = data.get("filters", {}) if isinstance(data.get("filters"), dict) else {}
    sources = data.get("sources", {}) if isinstance(data.get("sources"), dict) else {}
    arxiv = sources.get("arxiv", {}) if isinstance(sources.get("arxiv"), dict) else {}

    include_keywords = _sanitize_keywords(filters.get("include_keywords", []), allow_empty=False, maximum=_MAX_INCLUDE_KEYWORDS)
    exclude_keywords = _sanitize_keywords(filters.get("exclude_keywords", []), allow_empty=True, maximum=_MAX_EXCLUDE_KEYWORDS)
    queries = _sanitize_queries(arxiv.get("queries", []))

    summary = str(data.get("summary", "")).strip() or "未提供摘要"
    mode = str(strategy.get("mode", "")).strip().lower()
    if mode not in {"precision", "balanced", "recall"}:
        raise ConfigPlannerError(f"Unsupported planner mode: {mode or '<empty>'}")
    reasoning = str(strategy.get("reasoning", "")).strip() or "未提供理由"
    return PlannerResult(
        summary=summary,
        mode=mode,
        reasoning=reasoning,
        include_keywords=include_keywords,
        exclude_keywords=exclude_keywords,
        queries=queries,
    )


def _sanitize_keywords(raw_keywords: Any, *, allow_empty: bool, maximum: int) -> list[str]:
    if not isinstance(raw_keywords, list):
        raise ConfigPlannerError("Planner keywords must be arrays")
    seen: set[str] = set()
    result: list[str] = []
    for item in raw_keywords:
        keyword = str(item).strip()
        if not keyword:
            continue
        folded = keyword.casefold()
        if folded in _LOW_SIGNAL_KEYWORDS:
            continue
        if len(keyword) < 3:
            continue
        if folded in seen:
            continue
        seen.add(folded)
        result.append(keyword)
        if len(result) >= maximum:
            break
    if not allow_empty and len(result) < _MIN_INCLUDE_KEYWORDS:
        raise ConfigPlannerError("Planner did not produce enough include_keywords")
    return result


def _sanitize_queries(raw_queries: Any) -> list[PlannerArxivQuery]:
    if not isinstance(raw_queries, list) or not raw_queries:
        raise ConfigPlannerError("Planner did not produce arXiv queries")
    queries: list[PlannerArxivQuery] = []
    for item in raw_queries[:_MAX_QUERY_COUNT]:
        if not isinstance(item, dict):
            continue
        search_query = str(item.get("search_query", "")).strip()
        if not search_query or not any(token in search_query for token in ("all:", "cat:")):
            continue
        queries.append(
            PlannerArxivQuery(
                name=_slugify(str(item.get("name", "")).strip() or search_query),
                search_query=search_query,
                max_results=min(max(int(item.get("max_results", 20)), 10), 40),
            )
        )
    if not queries:
        raise ConfigPlannerError("Planner did not produce valid arXiv queries")
    return queries


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:40] or "auto-query"
