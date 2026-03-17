from __future__ import annotations

from datetime import UTC, datetime

from autopapers.config import OpenReviewVenueConfig
from autopapers.http import HttpClient
from autopapers.models import PaperRecord


class OpenReviewFetcher:
    base_url = "https://api2.openreview.net/notes"

    def __init__(self, http_client: HttpClient | None = None) -> None:
        self.http_client = http_client or HttpClient()

    def fetch(self, venue: OpenReviewVenueConfig, since: datetime, fetched_at: datetime) -> list[PaperRecord]:
        payload = self.http_client.get_json(
            self.base_url,
            params={
                "invitation": venue.invitation,
                "source": "forum",
                "sort": "tcdate:desc",
                "limit": venue.limit,
                "mintcdate": int(since.timestamp() * 1000),
            },
        )
        return self.parse_response(payload, venue_name=venue.name, since=since, fetched_at=fetched_at)

    def parse_response(
        self,
        payload: dict,
        venue_name: str,
        since: datetime,
        fetched_at: datetime,
    ) -> list[PaperRecord]:
        notes = payload.get("notes", [])
        papers: list[PaperRecord] = []
        for note in notes:
            published = _extract_note_datetime(note)
            if published < since:
                continue
            content = note.get("content", {}) or {}
            paper_id = str(note.get("forum") or note.get("id") or "")
            papers.append(
                PaperRecord(
                    source="openreview",
                    source_key=paper_id,
                    title=_unwrap_content(content.get("title")),
                    abstract=_unwrap_content(content.get("abstract")),
                    authors=_unwrap_authors(content.get("authors")),
                    url=f"https://openreview.net/forum?id={paper_id}",
                    published_at=published,
                    fetched_at=fetched_at,
                    categories=[venue_name],
                    venue=venue_name,
                    raw=note,
                )
            )
        return [paper for paper in papers if paper.source_key and paper.title]


def _extract_note_datetime(note: dict) -> datetime:
    for key in ("odate", "pdate", "tcdate", "tmdate", "cdate"):
        value = note.get(key)
        if value:
            return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    raise ValueError("OpenReview note is missing a timestamp")


def _unwrap_content(value: object) -> str:
    if isinstance(value, dict):
        inner = value.get("value")
        if inner is None:
            return ""
        if isinstance(inner, list):
            return ", ".join(str(item) for item in inner)
        return str(inner).strip()
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value).strip() if value is not None else ""


def _unwrap_authors(value: object) -> list[str]:
    if isinstance(value, dict):
        inner = value.get("value")
        if isinstance(inner, list):
            return [str(item).strip() for item in inner if str(item).strip()]
        if isinstance(inner, str) and inner.strip():
            return [inner.strip()]
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []
