from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

from autopapers.config import FilterConfig, LLMConfig
from autopapers.http import HttpClient, HttpError
from autopapers.models import ConceptCard, EnrichedPaper, PaperRecord

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when the LLM output cannot be generated or parsed."""


class PaperEnricher:
    def enrich(self, paper: PaperRecord) -> EnrichedPaper:
        raise NotImplementedError


@dataclass(slots=True)
class OpenAIEnricher(PaperEnricher):
    config: LLMConfig
    filters: FilterConfig
    http_client: HttpClient

    def enrich(self, paper: PaperRecord) -> EnrichedPaper:
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise LLMError(f"Missing API key in environment variable {self.config.api_key_env}")

        fallback = RuleBasedEnricher(filters=self.filters)
        try:
            response = self.http_client.post_json(
                "https://api.openai.com/v1/responses",
                payload=self._build_payload(paper),
                headers={"Authorization": f"Bearer {api_key}"},
            )
            content = _extract_text_response(response)
            data = json.loads(content)
            return _coerce_enriched_paper(paper, data, self.filters.concepts_max_per_paper)
        except HttpError as exc:
            logger.warning("OpenAI enrich failed for %s, falling back to rule-based notes: %s", paper.dedupe_key, exc)
            return fallback.enrich(paper)
        except json.JSONDecodeError as exc:
            logger.warning("OpenAI returned invalid JSON for %s, falling back to rule-based notes", paper.dedupe_key)
            return fallback.enrich(paper)
        except LLMError as exc:
            logger.warning("OpenAI response parsing failed for %s, falling back to rule-based notes: %s", paper.dedupe_key, exc)
            return fallback.enrich(paper)

    def _build_payload(self, paper: PaperRecord) -> dict:
        return {
            "model": self.config.model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You generate concise Chinese research notes for academic papers. "
                                "Return valid JSON only."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": self._build_prompt(paper),
                        }
                    ],
                },
            ],
            "text": {"format": {"type": "json_object"}},
        }

    def _build_prompt(self, paper: PaperRecord) -> str:
        authors = ", ".join(paper.authors) if paper.authors else "未知作者"
        return (
            "请根据以下论文信息生成结构化研究笔记。"
            "输出 JSON 对象，字段必须包含："
            "research_problem, core_method, main_results, limitations, one_line_judgment, "
            "topics, concepts。"
            "其中 topics 是字符串数组，concepts 是对象数组，每个对象包含 "
            "name, definition, role_in_paper。"
            "回答必须用简体中文，内容简洁、明确，不要编造论文中没有的信息。\n\n"
            f"标题: {paper.title}\n"
            f"作者: {authors}\n"
            f"来源: {paper.source}\n"
            f"发布日期: {paper.published_at.date().isoformat()}\n"
            f"链接: {paper.url}\n"
            f"摘要: {paper.abstract}\n"
        )


@dataclass(slots=True)
class MiniMaxEnricher(PaperEnricher):
    config: LLMConfig
    filters: FilterConfig
    http_client: HttpClient

    def enrich(self, paper: PaperRecord) -> EnrichedPaper:
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise LLMError(f"Missing API key in environment variable {self.config.api_key_env}")

        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You generate concise Chinese research notes for academic papers. Return valid JSON only.",
                },
                {
                    "role": "user",
                    "content": self._build_prompt(paper),
                },
            ],
            "temperature": 0.2,
        }
        response = self.http_client.post_json(
            f"{self._base_url()}/chat/completions",
            payload=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        content = _extract_chat_completion_text(response)
        data = _load_json_content(content)
        return _coerce_enriched_paper(paper, data, self.filters.concepts_max_per_paper)

    def _base_url(self) -> str:
        return (self.config.base_url or "https://api.minimaxi.com/v1").rstrip("/")

    def _build_prompt(self, paper: PaperRecord) -> str:
        authors = ", ".join(paper.authors) if paper.authors else "未知作者"
        return (
            "请根据以下论文信息生成结构化研究笔记。"
            "你必须只输出一个 JSON 对象，不要输出 Markdown，不要输出解释。"
            "字段必须包含：research_problem, core_method, main_results, limitations, "
            "one_line_judgment, topics, concepts。"
            "其中 topics 是字符串数组，concepts 是对象数组，每个对象包含 "
            "name, definition, role_in_paper。"
            "回答必须用简体中文，内容简洁、明确，不要编造论文中没有的信息。\n\n"
            f"标题: {paper.title}\n"
            f"作者: {authors}\n"
            f"来源: {paper.source}\n"
            f"发布日期: {paper.published_at.date().isoformat()}\n"
            f"链接: {paper.url}\n"
            f"摘要: {paper.abstract}\n"
        )


@dataclass(slots=True)
class RuleBasedEnricher(PaperEnricher):
    filters: FilterConfig

    def enrich(self, paper: PaperRecord) -> EnrichedPaper:
        leading_sentence = paper.abstract.split(". ")[0].split("。")[0].strip()
        summary = leading_sentence or paper.abstract[:140].strip() or paper.title
        return EnrichedPaper(
            paper=paper,
            research_problem=summary,
            core_method=paper.abstract[:200].strip() or "需人工补充",
            main_results="需人工补充",
            limitations="需人工补充",
            one_line_judgment=summary,
            topics=list(dict.fromkeys(paper.categories))[:3],
            concepts=[],
        )


def build_enricher(config: LLMConfig, filters: FilterConfig) -> PaperEnricher:
    if config.provider == "openai":
        return OpenAIEnricher(config=config, filters=filters, http_client=HttpClient(timeout_seconds=config.timeout_seconds))
    if config.provider == "minimax":
        return MiniMaxEnricher(config=config, filters=filters, http_client=HttpClient(timeout_seconds=config.timeout_seconds))
    if config.provider == "rule_based":
        return RuleBasedEnricher(filters=filters)
    raise LLMError(f"Unsupported LLM provider: {config.provider}")


def _extract_text_response(response: dict) -> str:
    if isinstance(response.get("output_text"), str) and response["output_text"].strip():
        return response["output_text"]
    chunks: list[str] = []
    for item in response.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text") or content.get("output_text")
            if isinstance(text, str) and text.strip():
                chunks.append(text)
    if not chunks:
        raise LLMError("LLM response did not contain output text")
    return "\n".join(chunks)


def _extract_chat_completion_text(response: dict) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMError("Chat completion response did not contain choices")
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
    raise LLMError("Chat completion response did not contain text content")


def _load_json_content(content: str) -> dict:
    cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Failed to decode LLM JSON output: {cleaned}") from exc


def _coerce_enriched_paper(paper: PaperRecord, data: dict, max_concepts: int) -> EnrichedPaper:
    concepts: list[ConceptCard] = []
    for item in data.get("concepts", [])[:max_concepts]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        definition = str(item.get("definition", "")).strip()
        role = str(item.get("role_in_paper", "")).strip()
        if name and definition:
            concepts.append(ConceptCard(name=name, definition=definition, role_in_paper=role or "需人工补充"))

    topics = [str(item).strip() for item in data.get("topics", []) if str(item).strip()]
    return EnrichedPaper(
        paper=paper,
        research_problem=str(data.get("research_problem", "")).strip() or "需人工补充",
        core_method=str(data.get("core_method", "")).strip() or "需人工补充",
        main_results=str(data.get("main_results", "")).strip() or "需人工补充",
        limitations=str(data.get("limitations", "")).strip() or "需人工补充",
        one_line_judgment=str(data.get("one_line_judgment", "")).strip() or "需人工补充",
        topics=topics,
        concepts=concepts,
    )
