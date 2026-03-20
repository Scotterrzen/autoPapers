from __future__ import annotations

import os
import unittest
from unittest import mock

from autopapers.config import LLMConfig
from autopapers.config_planner import (
    MiniMaxConfigPlanner,
    PlannerRequest,
    _coerce_planner_result,
)


class StubHttpClient:
    def __init__(self, response: dict) -> None:
        self.response = response

    def post_json(self, *_args, **_kwargs) -> dict:
        return self.response


class ConfigPlannerTests(unittest.TestCase):
    def test_minimax_config_planner_parses_chat_completion_json(self) -> None:
        planner = MiniMaxConfigPlanner(
            config=LLMConfig(provider="minimax", model="MiniMax-M2.5", api_key_env="MINIMAX_API_KEY"),
            http_client=StubHttpClient(
                {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '<think>internal</think>{'
                                    '"summary":"关注 VLA",'
                                    '"strategy":{"mode":"balanced","reasoning":"宽抓取后收敛"},'
                                    '"filters":{"include_keywords":["vision-language-action","robot manipulation","policy finetuning"],'
                                    '"exclude_keywords":["survey"]},'
                                    '"sources":{"arxiv":{"queries":[{"name":"vla","search_query":"all:\\"vision-language-action\\"","max_results":18}]}}'
                                    "}"
                                )
                            }
                        }
                    ]
                }
            ),
        )

        with mock.patch.dict(os.environ, {"MINIMAX_API_KEY": "test-key"}, clear=False):
            result = planner.plan(
                PlannerRequest(
                    interest_directions="vision-language-action",
                    mode="balanced",
                    target_papers_per_day=5,
                    must_track_phrases=[],
                    avoid_phrases=[],
                )
            )

        self.assertEqual(result.summary, "关注 VLA")
        self.assertEqual(result.mode, "balanced")
        self.assertEqual(result.include_keywords[0], "vision-language-action")
        self.assertEqual(result.queries[0].name, "vla")

    def test_coerce_planner_result_filters_low_signal_keywords_and_invalid_queries(self) -> None:
        result = _coerce_planner_result(
            {
                "summary": "test",
                "strategy": {"mode": "precision", "reasoning": "test"},
                "filters": {
                    "include_keywords": [
                        "AI",
                        "alignment",
                        "vision-language-action",
                        "gaussian splatting",
                        "robot manipulation",
                    ],
                    "exclude_keywords": ["survey", "benchmark", "AI"],
                },
                "sources": {
                    "arxiv": {
                        "queries": [
                            {"name": "bad", "search_query": "vision language action", "max_results": 100},
                            {"name": "good", "search_query": 'all:"vision-language-action"', "max_results": 100},
                        ]
                    }
                },
            }
        )

        self.assertEqual(
            result.include_keywords,
            ["vision-language-action", "gaussian splatting", "robot manipulation"],
        )
        self.assertEqual(result.exclude_keywords, ["survey", "benchmark"])
        self.assertEqual(len(result.queries), 1)
        self.assertEqual(result.queries[0].max_results, 40)
