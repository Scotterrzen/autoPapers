from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff ]+", "", normalized)
    return normalized.strip()


def sanitize_filename(value: str, max_length: int = 120) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned[:max_length].strip() or "untitled"


def parse_iso_datetime(value: str) -> datetime:
    clean = value.replace("Z", "+00:00")
    return datetime.fromisoformat(clean).astimezone(UTC)


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def contains_any_keywords(text: str, keywords: list[str]) -> bool:
    haystack = text.lower()
    return any(keyword.lower() in haystack for keyword in keywords)

