from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from autopapers.config import ArxivQueryConfig
from autopapers.fetchers.arxiv import ArxivFetcher, extract_arxiv_id
from autopapers.fetchers.openreview import OpenReviewFetcher
from autopapers.http import HttpError


FIXTURES = Path(__file__).parent / "fixtures"


class FetcherTests(unittest.TestCase):
    def test_extract_arxiv_id_strips_version(self) -> None:
        self.assertEqual(extract_arxiv_id("http://arxiv.org/abs/2503.12345v3"), "2503.12345")

    def test_parse_arxiv_feed_filters_by_date(self) -> None:
        xml_text = (FIXTURES / "arxiv_sample.xml").read_text(encoding="utf-8")
        fetcher = ArxivFetcher()
        papers = fetcher.parse_feed(
            xml_text,
            source_name="llm-core",
            since=datetime(2026, 3, 15, tzinfo=UTC),
            fetched_at=datetime(2026, 3, 17, tzinfo=UTC),
        )
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].source_key, "2503.12345")
        self.assertEqual(papers[0].authors, ["Alice Zhang", "Bob Li"])

    def test_parse_openreview_response_filters_by_date(self) -> None:
        payload = json.loads((FIXTURES / "openreview_sample.json").read_text(encoding="utf-8"))
        fetcher = OpenReviewFetcher()
        papers = fetcher.parse_response(
            payload,
            venue_name="iclr-2026",
            since=datetime(2026, 3, 14, tzinfo=UTC),
            fetched_at=datetime(2026, 3, 17, tzinfo=UTC),
        )
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].source_key, "abc123")
        self.assertIn("Jane Doe", papers[0].authors)

    def test_arxiv_fetch_falls_back_to_http(self) -> None:
        xml_text = (FIXTURES / "arxiv_sample.xml").read_text(encoding="utf-8")

        class StubHttpClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def get_text(self, url: str, *_args, **_kwargs) -> str:
                self.calls.append(url)
                if url.startswith("https://"):
                    raise HttpError("TLS handshake failed")
                return xml_text

        http_client = StubHttpClient()
        fetcher = ArxivFetcher(http_client=http_client)
        papers = fetcher.fetch(
            ArxivQueryConfig(name="llm-core", search_query="cat:cs.AI", max_results=5),
            since=datetime(2026, 3, 15, tzinfo=UTC),
            fetched_at=datetime(2026, 3, 17, tzinfo=UTC),
        )
        self.assertEqual(len(papers), 1)
        self.assertEqual(len(http_client.calls), 2)
        self.assertTrue(http_client.calls[0].startswith("https://"))
        self.assertTrue(http_client.calls[1].startswith("http://"))
