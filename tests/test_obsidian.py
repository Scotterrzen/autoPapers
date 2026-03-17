from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from autopapers.config import AppConfig, FilterConfig, LLMConfig, SourceConfig
from autopapers.models import ConceptCard, EnrichedPaper, PaperRecord
from autopapers.obsidian import ObsidianWriter


class ObsidianWriterTests(unittest.TestCase):
    def _config(self, root: Path) -> AppConfig:
        return AppConfig(
            config_path=root / "config.yaml",
            obsidian_root=root,
            literature_dir=Path("01 Literature"),
            concepts_dir=Path("02 Concepts"),
            state_dir=root / ".autopapers" / "state",
            llm=LLMConfig(),
            filters=FilterConfig(),
            sources=SourceConfig(),
        )

    def _paper(self) -> EnrichedPaper:
        paper = PaperRecord(
            source="arxiv",
            source_key="2503.12345",
            title="Time Retrieval via Diffusion",
            abstract="A retrieval paper abstract.",
            authors=["Alice Zhang", "Bob Li"],
            url="https://arxiv.org/abs/2503.12345",
            published_at=datetime(2026, 3, 16, tzinfo=UTC),
            fetched_at=datetime(2026, 3, 17, tzinfo=UTC),
            categories=["cs.CL"],
            venue="llm-core",
        )
        return EnrichedPaper(
            paper=paper,
            research_problem="研究时间感知检索问题。",
            core_method="提出扩散式检索框架。",
            main_results="在多个基准上优于基线。",
            limitations="依赖较大计算资源。",
            one_line_judgment="值得关注的检索方向。",
            topics=["retrieval", "diffusion"],
            concepts=[
                ConceptCard(
                    name="Time-aware Retrieval",
                    definition="面向时间变化语料的检索方法。",
                    role_in_paper="作为核心任务设定。",
                )
            ],
        )

    def test_write_literature_and_concepts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            writer = ObsidianWriter(self._config(root))
            paper = self._paper()
            literature_path = writer.write_literature(paper)
            concept_paths = writer.write_concepts(paper, literature_path)
            self.assertTrue(literature_path.exists())
            self.assertEqual(len(concept_paths), 1)
            content = literature_path.read_text(encoding="utf-8")
            self.assertIn("## 研究问题", content)
            self.assertIn("[[Time-aware Retrieval]]", content)
            concept_content = concept_paths[0].read_text(encoding="utf-8")
            self.assertIn("## 相关论文", concept_content)

    def test_existing_concept_file_is_appended_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            writer = ObsidianWriter(self._config(root))
            paper = self._paper()
            literature_path = writer.write_literature(paper)
            concept_dir = root / "02 Concepts"
            concept_dir.mkdir(parents=True, exist_ok=True)
            concept_path = concept_dir / "Time-aware Retrieval.md"
            concept_path.write_text("# Time-aware Retrieval\n\n## 定义\n已有定义\n", encoding="utf-8")
            writer.write_concepts(paper, literature_path)
            content = concept_path.read_text(encoding="utf-8")
            self.assertIn("已有定义", content)
            self.assertIn("[[2026-03-16 Time Retrieval via Diffusion]]", content)

