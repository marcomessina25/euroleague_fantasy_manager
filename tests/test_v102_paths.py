"""Tests for central path resolution (v102 P0.1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def test_elf_home_set_redirects_all_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_home = tmp_path / "custom_elf_home"
    monkeypatch.setenv("ELF_HOME", str(custom_home))

    from euroleague_fantasy_manager import paths

    assert paths.elf_home() == custom_home.resolve()
    assert paths.database_path() == custom_home.resolve() / "data" / "euroleague.sqlite3"
    assert paths.raw_archive_dir() == custom_home.resolve() / "data" / "raw"
    assert paths.squad_config_path() == custom_home.resolve() / "config" / "current_squad.json"
    assert paths.players_txt_path() == custom_home.resolve() / "players.txt"
    assert paths.eval_reports_dir() == custom_home.resolve() / "reports" / "evaluation"


def test_site_packages_layout_falls_back_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELF_HOME", raising=False)
    monkeypatch.chdir(tmp_path)

    from euroleague_fantasy_manager import paths

    with patch.object(Path, "is_file", return_value=False):
        assert paths.elf_home() == tmp_path.resolve()


def test_raw_archive_dir_with_explicit_db(tmp_path: Path) -> None:
    from euroleague_fantasy_manager import paths

    custom_db = tmp_path / "somewhere" / "custom.sqlite3"
    assert paths.raw_archive_dir(custom_db) == (tmp_path / "somewhere" / "raw").resolve()


def test_cli_update_writes_raw_archives_next_to_db(tmp_path: Path) -> None:
    from euroleague_fantasy_manager import cli

    custom_db = tmp_path / "my_project" / "custom.sqlite3"
    custom_db.parent.mkdir(parents=True, exist_ok=True)
    fake_payload = {
        "league_id": 10,
        "competition_code": "E",
        "season_code": "E2026",
        "config": {
            "current_matchday": {"id": 1, "number": 1, "num_rounds": 2},
            "teams": [],
        },
        "schedules": [],
        "match_lineups": [],
    }

    with patch("euroleague_fantasy_manager.cli.fetch_current_data", return_value=fake_payload):
        code = cli.main(["--db", str(custom_db), "update"])
        assert code == 0

    expected_raw_dir = tmp_path / "my_project" / "raw"
    assert expected_raw_dir.is_dir()
    raw_files = list(expected_raw_dir.glob("snapshot_*.json"))
    assert len(raw_files) == 1


def test_historical_stats_store_uses_paths_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_home = tmp_path / "custom_home"
    monkeypatch.setenv("ELF_HOME", str(custom_home))

    from euroleague_fantasy_manager.ingestion.historical_feeds import HistoricalStatsStore

    store = HistoricalStatsStore()
    assert store.database_path == (custom_home / "data" / "euroleague.sqlite3").resolve()


