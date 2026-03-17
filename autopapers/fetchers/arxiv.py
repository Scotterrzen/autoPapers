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

    def __init__(self, http_client: HttpClient | None = None) -> None:
        self.http_client = http_client or HttpClient()

    def fetch(self, query: ArxivQueryConfig, since: datetime, fetched_at: datetime) -> list[PaperRecord]:
        payload = self._fetch_feed(query)
        return self.parse_feed(payload, source_name=query.name, since=since, fetched_at=fetched_at)

    def _fetch_feed(self, query: ArxivQueryConfig) -> str:
        last_error: HttpError | None = None
        for base_url in self.base_urls:
            url = (
                base_url
                + f"?search_query={quote_plus(query.search_query)}"
                f"&sortBy=submittedDate&sortOrder=descending&start=0&max_results={query.max_results}"
            )
            try:
                return self.http_client.get_text(url)
            except HttpError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("arXiv fetch did not attempt any URLs")

    def parse_feed(self, xml_text: str, source_name: str, since: datetime, fetched_at: datetime) -> list[PaperRecord]:
        root = ET.fromstring(xml_text)
        papers: list[PaperRecord] = []
        for entry in root.findall("atom:entry", ATOM_NS):
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
        return papers


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
