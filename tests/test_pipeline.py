from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from autopapers.config import (
    AppConfig,
    ArxivQueryConfig,
    ArxivSourceConfig,
    FilterConfig,
    LLMConfig,
    OpenReviewSourceConfig,
    OpenReviewVenueConfig,
    SourceConfig,
)
from autopapers.models import ConceptCard, EnrichedPaper, PaperRecord
from autopapers.obsidian import ObsidianWriter
from autopapers.pipeline import PaperPipeline
from autopapers.state import StateStore


class StubFetcher:
    def __init__(self, papers: list[PaperRecord]) -> None:
        self.papers = papers

    def fetch(self, *_args, **_kwargs) -> list[PaperRecord]:
        return list(self.papers)


class CapturingFetcher(StubFetcher):
    def __init__(self, papers: list[PaperRecord]) -> None:
        super().__init__(papers)
        self.since_calls: list[datetime] = []

    def fetch(self, _query, since: datetime, **_kwargs) -> list[PaperRecord]:
        self.since_calls.append(since)
        return list(self.papers)


class StubEnricher:
    def enrich(self, paper: PaperRecord) -> EnrichedPaper:
        return EnrichedPaper(
            paper=paper,
            research_problem="problem",
            core_method="method",
            main_results="results",
            limitations="limits",
            one_line_judgment="judgment",
            topics=["nlp"],
            concepts=[ConceptCard(name="Concept A", definition="Definition A", role_in_paper="Role A")],
        )


class PipelineTests(unittest.TestCase):
    def _config(self, root: Path) -> AppConfig:
        return AppConfig(
            config_path=root / "config.yaml",
            obsidian_root=root,
            literature_dir=Path("01 Literature"),
            concepts_dir=Path("02 Concepts"),
            state_dir=root / ".autopapers" / "state",
            incremental_overlap_hours=12,
            llm=LLMConfig(provider="rule_based"),
            filters=FilterConfig(include_keywords=["retrieval"], exclude_keywords=[]),
            sources=SourceConfig(
                arxiv=ArxivSourceConfig(
                    enabled=True,
                    queries=[ArxivQueryConfig(name="test-query", search_query="all:retrieval")],
                ),
                openreview=OpenReviewSourceConfig(
                    enabled=True,
                    venues=[OpenReviewVenueConfig(name="test-venue", invitation="Test.cc/-/Submission")],
                ),
            ),
        )

    def _paper(self, source: str, source_key: str, title: str) -> PaperRecord:
        return PaperRecord(
            source=source,
            source_key=source_key,
            title=title,
            abstract="This paper studies retrieval under time drift.",
            authors=["Alice Zhang"],
            url=f"https://example.com/{source_key}",
            published_at=datetime(2026, 3, 16, tzinfo=UTC),
            fetched_at=datetime(2026, 3, 17, tzinfo=UTC),
            categories=["cs.CL"],
            venue="test-venue",
        )

    def test_pipeline_deduplicates_by_title_and_marks_processed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._config(root)
            papers = [
                self._paper("arxiv", "1", "Unified Retrieval Benchmark"),
                self._paper("openreview", "2", "Unified Retrieval Benchmark"),
            ]
            pipeline = PaperPipeline(
                config,
                arxiv_fetcher=StubFetcher(papers[:1]),
                openreview_fetcher=StubFetcher(papers[1:]),
                enricher=StubEnricher(),
                writer=ObsidianWriter(config),
                state_store=StateStore.load(config.state_dir),
            )
            result = pipeline.backfill(days=2, now=datetime(2026, 3, 17, tzinfo=UTC))
            self.assertEqual(result.fetched, 2)
            self.assertEqual(result.written, 1)
            self.assertEqual(result.skipped, 1)
            state = StateStore.load(config.state_dir)
            self.assertTrue(state.has_processed("arxiv:1") or state.has_processed("openreview:2"))

    def test_pipeline_filters_by_include_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._config(root)
            paper = self._paper("arxiv", "3", "Graph Compression Study")
            paper.abstract = "This paper studies graph compression only."
            pipeline = PaperPipeline(
                config,
                arxiv_fetcher=StubFetcher([paper]),
                openreview_fetcher=StubFetcher([]),
                enricher=StubEnricher(),
                writer=ObsidianWriter(config),
                state_store=StateStore.load(config.state_dir),
            )
            result = pipeline.backfill(days=2, now=datetime(2026, 3, 17, tzinfo=UTC))
            self.assertEqual(result.written, 0)
            self.assertEqual(result.skipped, 1)

    def test_run_daily_reuses_overlap_hours_from_last_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._config(root)
            state = StateStore.load(config.state_dir)
            state.set_last_success_at(datetime(2026, 3, 20, 8, 0, tzinfo=UTC))
            state.save()
            fetcher = CapturingFetcher([])
            pipeline = PaperPipeline(
                config,
                arxiv_fetcher=fetcher,
                openreview_fetcher=StubFetcher([]),
                enricher=StubEnricher(),
                writer=ObsidianWriter(config),
                state_store=StateStore.load(config.state_dir),
            )

            pipeline.run_daily(now=datetime(2026, 3, 20, 20, 0, tzinfo=UTC))

            self.assertEqual(fetcher.since_calls[0], datetime(2026, 3, 19, 20, 0, tzinfo=UTC))
