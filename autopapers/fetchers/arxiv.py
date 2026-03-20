from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote_plus

from autopapers.config import ArxivQueryConfig
from autopapers.http import HttpClient, HttpError
from autopapers.models import PaperRecord
from autopapers.utils import parse_iso_datetime

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class ArxivFetcher:
    base_urls = ("https://export.arxiv.org/api/query", "http://export.arxiv.org/api/query")

    def __init__(self, http_client: HttpClient | None = None, page_size: int = 100) -> None:
        self.http_client = http_client or HttpClient()
        self.page_size = max(1, page_size)

    def fetch(self, query: ArxivQueryConfig, since: datetime, fetched_at: datetime) -> list[PaperRecord]:
        papers: list[PaperRecord] = []
        seen_keys: set[str] = set()

        for start in range(0, query.max_results, self.page_size):
            batch_size = min(self.page_size, query.max_results - start)
            payload = self._fetch_feed(query, start=start, max_results=batch_size)
            page_papers, entry_count = self._parse_feed_page(
                payload,
                source_name=query.name,
                since=since,
                fetched_at=fetched_at,
            )
            if entry_count == 0:
                break
            for paper in page_papers:
                if paper.source_key in seen_keys:
                    continue
                seen_keys.add(paper.source_key)
                papers.append(paper)
            if entry_count < batch_size or entry_count != len(page_papers):
                break

        papers.sort(key=lambda item: item.published_at, reverse=True)
        return papers

    def _fetch_feed(self, query: ArxivQueryConfig, *, start: int, max_results: int) -> str:
        last_error: HttpError | None = None
        for base_url in self.base_urls:
            url = (
                base_url
                + f"?search_query={quote_plus(query.search_query)}"
                f"&sortBy=submittedDate&sortOrder=descending&start={start}&max_results={max_results}"
            )
            try:
                return self.http_client.get_text(url)
            except HttpError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("arXiv fetch did not attempt any URLs")

    def parse_feed(self, xml_text: str, source_name: str, since: datetime, fetched_at: datetime) -> list[PaperRecord]:
        papers, _entry_count = self._parse_feed_page(
            xml_text,
            source_name=source_name,
            since=since,
            fetched_at=fetched_at,
        )
        return papers

    def _parse_feed_page(
        self,
        xml_text: str,
        source_name: str,
        since: datetime,
        fetched_at: datetime,
    ) -> tuple[list[PaperRecord], int]:
        root = ET.fromstring(xml_text)
        entries = root.findall("atom:entry", ATOM_NS)
        papers: list[PaperRecord] = []
        for entry in entries:
            published = parse_iso_datetime(_entry_text(entry, "atom:published"))
            if published < since:
                continue
            entry_id = _entry_text(entry, "atom:id")
            categories = [node.attrib.get("term", "") for node in entry.findall("atom:category", ATOM_NS)]
            papers.append(
                PaperRecord(
                    source="arxiv",
                    source_key=extract_arxiv_id(entry_id),
                    title=_clean_whitespace(_entry_text(entry, "atom:title")),
                    abstract=_clean_whitespace(_entry_text(entry, "atom:summary")),
                    authors=[
                        _clean_whitespace(author.findtext("atom:name", default="", namespaces=ATOM_NS))
                        for author in entry.findall("atom:author", ATOM_NS)
                    ],
                    url=entry_id.replace("/abs/", "/html/"),
                    published_at=published,
                    fetched_at=fetched_at,
                    categories=[item for item in categories if item],
                    venue=source_name,
                    raw={"entry_id": entry_id},
                )
            )
        return papers, len(entries)


def extract_arxiv_id(entry_id: str) -> str:
    match = re.search(r"/abs/([^/?]+)", entry_id)
    if not match:
        return entry_id
    identifier = match.group(1)
    return identifier.split("v", maxsplit=1)[0]


def _entry_text(entry: ET.Element, path: str) -> str:
    value = entry.findtext(path, default="", namespaces=ATOM_NS)
    return value.strip()


def _clean_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
