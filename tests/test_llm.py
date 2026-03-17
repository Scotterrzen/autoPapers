from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from unittest import mock

from autopapers.config import FilterConfig, LLMConfig
from autopapers.http import HttpError
from autopapers.llm import MiniMaxEnricher, OpenAIEnricher
from autopapers.models import PaperRecord


class StubFailingHttpClient:
    def post_json(self, *_args, **_kwargs) -> dict:
        raise HttpError("POST https://api.openai.com/v1/responses failed: HTTP Error 429: Too Many Requests")


class StubMiniMaxHttpClient:
    def __init__(self, response: dict) -> None:
        self.response = response

    def post_json(self, *_args, **_kwargs) -> dict:
        return self.response


class LLMTests(unittest.TestCase):
    def test_openai_enricher_falls_back_to_rule_based_when_api_fails(self) -> None:
        paper = PaperRecord(
            source="arxiv",
            source_key="2603.15619",
            title="Test Paper",
            abstract="This paper studies retrieval under time drift. It adds evaluation details.",
            authors=["Alice Zhang"],
            url="https://example.com/paper",
            published_at=datetime(2026, 3, 17, tzinfo=UTC),
            fetched_at=datetime(2026, 3, 17, tzinfo=UTC),
            categories=["cs.CL"],
            venue="llm-core",
        )
        enricher = OpenAIEnricher(
            config=LLMConfig(provider="openai", model="gpt-5-mini"),
            filters=FilterConfig(),
            http_client=StubFailingHttpClient(),
        )

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            enriched = enricher.enrich(paper)

        self.assertEqual(enriched.research_problem, "This paper studies retrieval under time drift")
        self.assertEqual(enriched.topics, ["cs.CL"])
        self.assertEqual(enriched.concepts, [])

    def test_minimax_enricher_parses_chat_completion_json(self) -> None:
        paper = PaperRecord(
            source="arxiv",
            source_key="2603.15620",
            title="Test Paper",
            abstract="This paper studies retrieval under time drift.",
            authors=["Alice Zhang"],
            url="https://example.com/paper",
            published_at=datetime(2026, 3, 17, tzinfo=UTC),
            fetched_at=datetime(2026, 3, 17, tzinfo=UTC),
            categories=["cs.CL"],
            venue="llm-core",
        )
        response = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '<think>internal</think>{"research_problem":"问题","core_method":"方法",'
                            '"main_results":"结果","limitations":"局限","one_line_judgment":"判断",'
                            '"topics":["检索"],"concepts":[{"name":"RAG","definition":"定义","role_in_paper":"作用"}]}'
                        )
                    }
                }
            ]
        }
        enricher = MiniMaxEnricher(
            config=LLMConfig(provider="minimax", model="MiniMax-M2.5", api_key_env="MINIMAX_API_KEY"),
            filters=FilterConfig(),
            http_client=StubMiniMaxHttpClient(response),
        )

        with mock.patch.dict(os.environ, {"MINIMAX_API_KEY": "test-key"}, clear=False):
            enriched = enricher.enrich(paper)

        self.assertEqual(enriched.research_problem, "问题")
        self.assertEqual(enriched.topics, ["检索"])
        self.assertEqual(enriched.concepts[0].name, "RAG")
