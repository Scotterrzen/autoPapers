from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autopapers.config import load_config


class ConfigTests(unittest.TestCase):
    def test_load_config_reads_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "vault").mkdir()
            (root / "config.yaml").write_text(
                "\n".join(
                    [
                        "obsidian_root: vault",
                        "state_dir: .autopapers/state",
                        "llm:",
                        "  provider: openai",
                        "  model: gpt-5-mini",
                        "  api_key_env: OPENAI_API_KEY",
                        "sources:",
                        "  arxiv:",
                        "    enabled: true",
                        "    queries:",
                        "      - name: test",
                        "        search_query: cat:cs.AI",
                    ]
                ),
                encoding="utf-8",
            )
            (root / ".env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")

            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("OPENAI_API_KEY", None)
                config = load_config(root / "config.yaml")
                self.assertEqual(os.environ.get("OPENAI_API_KEY"), "test-key")

            self.assertEqual(config.llm.provider, "openai")

    def test_load_config_does_not_override_existing_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "vault").mkdir()
            (root / "config.yaml").write_text(
                "\n".join(
                    [
                        "obsidian_root: vault",
                        "state_dir: .autopapers/state",
                        "llm:",
                        "  provider: openai",
                        "  model: gpt-5-mini",
                        "  api_key_env: OPENAI_API_KEY",
                        "sources:",
                        "  arxiv:",
                        "    enabled: true",
                        "    queries:",
                        "      - name: test",
                        "        search_query: cat:cs.AI",
                    ]
                ),
                encoding="utf-8",
            )
            (root / ".env").write_text("OPENAI_API_KEY=file-key\n", encoding="utf-8")

            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "existing-key"}, clear=False):
                load_config(root / "config.yaml")
                self.assertEqual(os.environ.get("OPENAI_API_KEY"), "existing-key")

    def test_load_config_reads_incremental_overlap_hours(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "vault").mkdir()
            (root / "config.yaml").write_text(
                "\n".join(
                    [
                        "obsidian_root: vault",
                        "state_dir: .autopapers/state",
                        "incremental_overlap_hours: 6",
                        "llm:",
                        "  provider: rule_based",
                        "sources:",
                        "  arxiv:",
                        "    enabled: true",
                        "    queries:",
                        "      - name: test",
                        "        search_query: cat:cs.AI",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(root / "config.yaml")

            self.assertEqual(config.incremental_overlap_hours, 6)
