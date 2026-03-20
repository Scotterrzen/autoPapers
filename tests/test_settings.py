from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import autopapers.settings as settings_module
from autopapers.cli import main
from autopapers.config import load_config
from autopapers.settings import run_settings_wizard


class SettingsWizardTests(unittest.TestCase):
    def test_run_settings_wizard_writes_valid_config_and_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            (root / "vault").mkdir()
            answers = iter(
                [
                    "vault",
                    "",
                    "",
                    "",
                    "",
                    "8:05",
                    "",
                    "openai",
                    "",
                    "",
                    "",
                    "",
                    "y",
                    "vision-language-action，gaussian splatting",
                    "survey",
                    "7",
                    "y",
                    "1",
                    "vision",
                    'all:"vision-language-action"',
                    "15",
                    "n",
                ]
            )
            secrets = iter(["test-openai-key"])
            emitted: list[str] = []

            exit_code = run_settings_wizard(
                config_path,
                input_func=lambda _prompt: next(answers),
                secret_input_func=lambda _prompt: next(secrets),
                emit=emitted.append,
            )

            config = load_config(config_path)
            self.assertEqual(exit_code, 0)
            self.assertEqual(config.obsidian_root, (root / "vault").resolve())
            self.assertEqual(config.schedule, "08:05")
            self.assertEqual(config.llm.provider, "openai")
            self.assertEqual(config.llm.api_key_env, "OPENAI_API_KEY")
            self.assertEqual(config.filters.include_keywords, ["vision-language-action", "gaussian splatting"])
            self.assertEqual(config.filters.exclude_keywords, ["survey"])
            self.assertEqual(config.filters.concepts_max_per_paper, 7)
            self.assertEqual(len(config.sources.arxiv.queries), 1)
            self.assertEqual(config.sources.arxiv.queries[0].max_results, 15)
            self.assertFalse(config.sources.openreview.enabled)
            self.assertIn("OPENAI_API_KEY", (root / ".env").read_text(encoding="utf-8"))
            self.assertIn("配置校验通过。", emitted)
            self.assertIn("--- 基础设置 ---", emitted)
            self.assertIn("--- LLM 设置 ---", emitted)
            self.assertIn("--- 过滤规则 ---", emitted)
            self.assertIn("--- 数据源 ---", emitted)

    def test_run_settings_wizard_repairs_invalid_sources_after_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            (root / "vault").mkdir()
            answers = iter(
                [
                    "vault",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "rule_based",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "n",
                    "n",
                    "y",
                    "1",
                    "vision",
                    'all:"vision-language-action"',
                    "5",
                    "n",
                ]
            )
            emitted: list[str] = []

            exit_code = run_settings_wizard(
                config_path,
                input_func=lambda _prompt: next(answers),
                secret_input_func=lambda _prompt: "",
                emit=emitted.append,
            )

            config = load_config(config_path)
            self.assertEqual(exit_code, 0)
            self.assertTrue(config.sources.arxiv.enabled)
            self.assertEqual(len(config.sources.arxiv.queries), 1)
            self.assertTrue(any("配置校验失败: At least one source query or venue must be configured" in line for line in emitted))

    def test_cli_routes_settings_flag_without_command(self) -> None:
        with mock.patch("autopapers.cli.run_settings_wizard", return_value=0) as wizard:
            exit_code = main(["--settings", "--config", "custom.yaml"])

        self.assertEqual(exit_code, 0)
        wizard.assert_called_once_with(Path("custom.yaml"))

    def test_validate_and_write_rolls_back_both_files_when_commit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "vault").mkdir()
            config_path = root / "config.yaml"
            env_path = root / ".env"
            old_config = "\n".join(
                [
                    "obsidian_root: vault",
                    "state_dir: .autopapers/state",
                    "llm:",
                    "  provider: rule_based",
                    "sources:",
                    "  arxiv:",
                    "    enabled: true",
                    "    queries:",
                    "      - name: old",
                    "        search_query: cat:cs.AI",
                ]
            )
            old_env = 'OPENAI_API_KEY="old-key"\n'
            config_path.write_text(old_config, encoding="utf-8")
            env_path.write_text(old_env, encoding="utf-8")

            raw = {
                "obsidian_root": "vault",
                "literature_dir": "01 Literature",
                "concepts_dir": "02 Concepts",
                "state_dir": ".autopapers/state",
                "timezone": "Asia/Shanghai",
                "schedule": "08:00",
                "incremental_overlap_hours": 12,
                "llm": {
                    "provider": "openai",
                    "model": "gpt-5-mini",
                    "api_key_env": "OPENAI_API_KEY",
                    "timeout_seconds": 60,
                },
                "filters": {
                    "include_keywords": ["vision-language-action"],
                    "exclude_keywords": [],
                    "concepts_max_per_paper": 5,
                },
                "sources": {
                    "arxiv": {
                        "enabled": True,
                        "queries": [
                            {
                                "name": "vision",
                                "search_query": 'all:"vision-language-action"',
                                "max_results": 5,
                            }
                        ],
                    },
                    "openreview": {
                        "enabled": False,
                        "venues": [],
                    },
                },
            }

            original_replace = settings_module._replace_path

            def flaky_replace(source: Path, target: Path) -> None:
                if source == config_path.with_name("config.yaml.txn.tmp") and target == config_path:
                    raise OSError("commit failed")
                original_replace(source, target)

            with mock.patch("autopapers.settings._replace_path", side_effect=flaky_replace):
                with self.assertRaisesRegex(OSError, "commit failed"):
                    settings_module._validate_and_write(
                        config_path,
                        raw,
                        env_values={"OPENAI_API_KEY": "new-key"},
                        emit=lambda _message: None,
                    )

            self.assertEqual(config_path.read_text(encoding="utf-8"), old_config)
            self.assertEqual(env_path.read_text(encoding="utf-8"), old_env)
            self.assertFalse(config_path.with_name("config.yaml.txn.tmp").exists())
            self.assertFalse(config_path.with_name("config.yaml.txn.bak").exists())
            self.assertFalse(env_path.with_name(".env.txn.tmp").exists())
            self.assertFalse(env_path.with_name(".env.txn.bak").exists())
