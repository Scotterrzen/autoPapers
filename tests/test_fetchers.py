from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from autopapers.config import ArxivQueryConfig, OpenReviewVenueConfig
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

    def test_arxiv_fetch_paginates_across_multiple_pages(self) -> None:
        page_1 = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2603.20001v1</id>
    <updated>2026-03-18T12:00:00Z</updated>
    <published>2026-03-18T12:00:00Z</published>
    <title>Page One Paper</title>
    <summary>Fresh result from page one.</summary>
    <author><name>Alice Zhang</name></author>
    <category term="cs.CV" />
  </entry>
</feed>
"""
        page_2 = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2603.20000v1</id>
    <updated>2026-03-17T12:00:00Z</updated>
    <published>2026-03-17T12:00:00Z</published>
    <title>Page Two Paper</title>
    <summary>Fresh result from page two.</summary>
    <author><name>Bob Li</name></author>
    <category term="cs.RO" />
  </entry>
</feed>
"""

        class StubHttpClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def get_text(self, url: str, *_args, **_kwargs) -> str:
                self.calls.append(url)
                start = int(parse_qs(urlparse(url).query).get("start", ["0"])[0])
                if start == 0:
                    return page_1
                if start == 1:
                    return page_2
                return "<?xml version='1.0' encoding='UTF-8'?><feed xmlns='http://www.w3.org/2005/Atom'></feed>"

        http_client = StubHttpClient()
        fetcher = ArxivFetcher(http_client=http_client, page_size=1)
        papers = fetcher.fetch(
            ArxivQueryConfig(name="vision", search_query="cat:cs.CV", max_results=2),
            since=datetime(2026, 3, 17, tzinfo=UTC),
            fetched_at=datetime(2026, 3, 19, tzinfo=UTC),
        )

        self.assertEqual([paper.source_key for paper in papers], ["2603.20001", "2603.20000"])
        self.assertEqual(len(http_client.calls), 2)

    def test_openreview_fetch_paginates_across_multiple_pages(self) -> None:
        page_1 = {
            "notes": [
                {
                    "id": "note-1",
                    "forum": "forum-1",
                    "tcdate": int(datetime(2026, 3, 18, 12, 0, tzinfo=UTC).timestamp() * 1000),
                    "content": {
                        "title": {"value": "Page One Review Paper"},
                        "abstract": {"value": "Fresh result from page one."},
                        "authors": {"value": ["Jane Doe"]},
                    },
                }
            ]
        }
        page_2 = {
            "notes": [
                {
                    "id": "note-2",
                    "forum": "forum-2",
                    "tcdate": int(datetime(2026, 3, 17, 12, 0, tzinfo=UTC).timestamp() * 1000),
                    "content": {
                        "title": {"value": "Page Two Review Paper"},
                        "abstract": {"value": "Fresh result from page two."},
                        "authors": {"value": ["John Roe"]},
                    },
                }
            ]
        }

        class StubHttpClient:
            def __init__(self) -> None:
                self.offsets: list[int] = []

            def get_json(self, _url: str, params: dict | None = None, *_args, **_kwargs) -> dict:
                offset = int((params or {}).get("offset", 0))
                self.offsets.append(offset)
                if offset == 0:
                    return page_1
                if offset == 1:
                    return page_2
                return {"notes": []}

        http_client = StubHttpClient()
        fetcher = OpenReviewFetcher(http_client=http_client, page_size=1)
        papers = fetcher.fetch(
            OpenReviewVenueConfig(name="iclr-2026", invitation="ICLR.cc/2026/Conference/-/Submission", limit=2),
            since=datetime(2026, 3, 17, tzinfo=UTC),
            fetched_at=datetime(2026, 3, 19, tzinfo=UTC),
        )

        self.assertEqual([paper.source_key for paper in papers], ["forum-1", "forum-2"])
        self.assertEqual(http_client.offsets, [0, 1])
