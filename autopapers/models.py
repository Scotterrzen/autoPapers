from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class PaperRecord:
    source: str
    source_key: str
    title: str
    abstract: str
    authors: list[str]
    url: str
    published_at: datetime
    fetched_at: datetime
    categories: list[str] = field(default_factory=list)
    venue: str | None = None
    raw: dict | None = None

    @property
    def dedupe_key(self) -> str:
        return f"{self.source}:{self.source_key}"


@dataclass(slots=True)
class ConceptCard:
    name: str
    definition: str
    role_in_paper: str


@dataclass(slots=True)
class EnrichedPaper:
    paper: PaperRecord
    research_problem: str
    core_method: str
    main_results: str
    limitations: str
    one_line_judgment: str
    topics: list[str] = field(default_factory=list)
    concepts: list[ConceptCard] = field(default_factory=list)


@dataclass(slots=True)
class PipelineResult:
    fetched: int = 0
    written: int = 0
    skipped: int = 0
    failed: int = 0

