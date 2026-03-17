from __future__ import annotations

from pathlib import Path

from autopapers.config import AppConfig
from autopapers.models import ConceptCard, EnrichedPaper
from autopapers.utils import sanitize_filename


class ObsidianWriter:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def ensure_directories(self) -> None:
        self.config.literature_path.mkdir(parents=True, exist_ok=True)
        self.config.concepts_path.mkdir(parents=True, exist_ok=True)

    def write_literature(self, paper: EnrichedPaper) -> Path:
        self.ensure_directories()
        file_stem = sanitize_filename(f"{paper.paper.published_at.date().isoformat()} {paper.paper.title}")
        path = self.config.literature_path / f"{file_stem}.md"
        link_list = "\n".join(
            f"- [[{sanitize_filename(concept.name)}]]: {concept.definition}" for concept in paper.concepts
        ) or "- 无"
        tags = self._build_tags(paper)
        content = "\n".join(
            [
                f"# {paper.paper.title}",
                "",
                f"- 来源：{paper.paper.source}",
                f"- 发布日期：{paper.paper.published_at.date().isoformat()}",
                f"- 作者：{', '.join(paper.paper.authors) if paper.paper.authors else '未知'}",
                f"- 链接：{paper.paper.url}",
                f"- 标签：{', '.join(tags) if tags else '无'}",
                "",
                "## 摘要",
                paper.paper.abstract or "无摘要",
                "",
                "## 研究问题",
                paper.research_problem,
                "",
                "## 核心方法",
                paper.core_method,
                "",
                "## 主要结果",
                paper.main_results,
                "",
                "## 局限性",
                paper.limitations,
                "",
                "## 一句话判断",
                paper.one_line_judgment,
                "",
                "## 相关概念",
                link_list,
                "",
            ]
        )
        path.write_text(content, encoding="utf-8")
        return path

    def write_concepts(self, paper: EnrichedPaper, literature_path: Path) -> list[Path]:
        self.ensure_directories()
        written_paths: list[Path] = []
        literature_link = f"[[{literature_path.stem}]]"
        for concept in paper.concepts:
            written_paths.append(self._upsert_concept(concept, literature_link))
        return written_paths

    def _upsert_concept(self, concept: ConceptCard, literature_link: str) -> Path:
        path = self.config.concepts_path / f"{sanitize_filename(concept.name)}.md"
        related_line = f"- {literature_link}"
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if related_line not in existing:
                if "## 相关论文" in existing:
                    existing = existing.rstrip() + f"\n{related_line}\n"
                else:
                    existing = existing.rstrip() + f"\n\n## 相关论文\n{related_line}\n"
                path.write_text(existing, encoding="utf-8")
            return path

        content = "\n".join(
            [
                f"# {concept.name}",
                "",
                "## 定义",
                concept.definition,
                "",
                "## 在论文中的作用",
                concept.role_in_paper or "需人工补充",
                "",
                "## 相关论文",
                related_line,
                "",
            ]
        )
        path.write_text(content, encoding="utf-8")
        return path

    @staticmethod
    def _build_tags(paper: EnrichedPaper) -> list[str]:
        tags = [f"source/{paper.paper.source}"]
        if paper.paper.venue:
            tags.append(f"venue/{sanitize_filename(paper.paper.venue).replace(' ', '-')}")
        tags.extend(f"topic/{sanitize_filename(topic).replace(' ', '-')}" for topic in paper.topics)
        tags.extend(f"category/{sanitize_filename(category).replace(' ', '-')}" for category in paper.paper.categories)
        deduped: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            if tag and tag not in seen:
                seen.add(tag)
                deduped.append(tag)
        return deduped

