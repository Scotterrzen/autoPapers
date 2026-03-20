from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from autopapers.config import AppConfig
from autopapers.fetchers.arxiv import ArxivFetcher
from autopapers.fetchers.openreview import OpenReviewFetcher
from autopapers.llm import PaperEnricher, build_enricher
from autopapers.models import PaperRecord, PipelineResult
from autopapers.obsidian import ObsidianWriter
from autopapers.state import StateStore
from autopapers.utils import contains_any_keywords, normalize_title

logger = logging.getLogger(__name__)


class PaperPipeline:
    def __init__(
        self,
        config: AppConfig,
        *,
        arxiv_fetcher: ArxivFetcher | None = None,
        openreview_fetcher: OpenReviewFetcher | None = None,
        enricher: PaperEnricher | None = None,
        writer: ObsidianWriter | None = None,
        state_store: StateStore | None = None,
    ) -> None:
        self.config = config
        self.arxiv_fetcher = arxiv_fetcher or ArxivFetcher()
        self.openreview_fetcher = openreview_fetcher or OpenReviewFetcher()
        self.enricher = enricher or build_enricher(config.llm, config.filters)
        self.writer = writer or ObsidianWriter(config)
        self.state_store = state_store or StateStore.load(config.state_dir)

    def run_daily(self, now: datetime | None = None) -> PipelineResult:
        now = (now or datetime.now(tz=UTC)).astimezone(UTC)
        last_success = self.state_store.last_success_at()
        if last_success is None:
            since = now - timedelta(days=1)
        else:
            since = last_success - timedelta(hours=self.config.incremental_overlap_hours)
        return self._run_window(since=since, until=now)

    def backfill(self, days: int, now: datetime | None = None) -> PipelineResult:
        now = (now or datetime.now(tz=UTC)).astimezone(UTC)
        since = now - timedelta(days=days)
        return self._run_window(since=since, until=now)

    def _run_window(self, since: datetime, until: datetime) -> PipelineResult:
        logger.info("Fetching papers between %s and %s", since.isoformat(), until.isoformat())
        result = PipelineResult()
        fetched = self._fetch_all(since=since, fetched_at=until)
        result.fetched = len(fetched)
        dedupe_titles: set[str] = set()

        for paper in fetched:
            if self.state_store.has_processed(paper.dedupe_key):
                result.skipped += 1
                continue
            title_key = normalize_title(paper.title)
            if title_key in dedupe_titles:
                result.skipped += 1
                continue
            dedupe_titles.add(title_key)
            if not self._matches_filters(paper):
                result.skipped += 1
                continue
            try:
                enriched = self.enricher.enrich(paper)
                literature_path = self.writer.write_literature(enriched)
                self.writer.write_concepts(enriched, literature_path)
                self.state_store.mark_processed(
                    paper.dedupe_key,
                    {
                        "title": paper.title,
                        "source": paper.source,
                        "published_at": paper.published_at.isoformat(),
                        "written_at": until.isoformat(),
                        "path": str(literature_path),
                    },
                )
                result.written += 1
            except Exception as exc:
                logger.exception("Failed to process paper %s", paper.dedupe_key)
                self.state_store.record_failure(paper.dedupe_key, str(exc))
                result.failed += 1

        if result.failed == 0:
            self.state_store.set_last_success_at(until)
        self.state_store.record_run(
            {
                "started_at": since.isoformat(),
                "finished_at": until.isoformat(),
                "fetched": result.fetched,
                "written": result.written,
                "skipped": result.skipped,
                "failed": result.failed,
            }
        )
        self.state_store.save()
        return result

    def _fetch_all(self, since: datetime, fetched_at: datetime) -> list[PaperRecord]:
        papers: list[PaperRecord] = []
        if self.config.sources.arxiv.enabled:
            for query in self.config.sources.arxiv.queries:
                papers.extend(self.arxiv_fetcher.fetch(query, since=since, fetched_at=fetched_at))
        if self.config.sources.openreview.enabled:
            for venue in self.config.sources.openreview.venues:
                papers.extend(self.openreview_fetcher.fetch(venue, since=since, fetched_at=fetched_at))
        papers.sort(key=lambda item: item.published_at, reverse=True)
        return papers

    def _matches_filters(self, paper: PaperRecord) -> bool:
        merged_text = f"{paper.title}\n{paper.abstract}"
        include_keywords = self.config.filters.include_keywords
        exclude_keywords = self.config.filters.exclude_keywords
        if include_keywords and not contains_any_keywords(merged_text, include_keywords):
            return False
        if exclude_keywords and contains_any_keywords(merged_text, exclude_keywords):
            return False
        return True
