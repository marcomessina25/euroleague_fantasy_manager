"""Tests for authoritative ruleset (Phase P1)."""

from __future__ import annotations

import json
from pathlib import Path

from euroleague_fantasy_manager.storage import SnapshotStore


def test_save_snapshot_stores_game_rules(tmp_path: Path):
    """P1.1 / RULE-1: Saving official config fixture stores max_num_same_team_players = 6."""
    db_file = tmp_path / "rules_test.sqlite3"
    store = SnapshotStore(db_file)

    fixture_path = Path(__file__).resolve().parent / "fixtures" / "official_config_el.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    summary = store.save_snapshot(payload)
    assert summary is not None

    rules = store.load_game_rules(snapshot_id=summary.snapshot_id)
    assert rules is not None
    assert rules.game_mode_id == 1
    assert rules.num_players_per_team == 11
    assert rules.num_starter_players == 5
    assert rules.num_bench_players == 5
    assert rules.num_coach_players == 1
    assert rules.max_num_same_team_players == 6
    assert rules.captain_multiplier == 2.0


def test_backfill_snapshot_game_rules_is_idempotent(tmp_path: Path):
    """P1.1: Backfill of snapshot_game_rules from raw_archive_path is idempotent."""
    db_file = tmp_path / "backfill_test.sqlite3"
    raw_dir = tmp_path / "raw"
    store = SnapshotStore(db_file)

    fixture_path = Path(__file__).resolve().parent / "fixtures" / "official_config_el.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    summary = store.save_snapshot(payload, raw_directory=raw_dir)
    assert summary is not None

    # Verify initial rules exist
    rules1 = store.load_game_rules(snapshot_id=summary.snapshot_id)
    assert rules1 is not None
    assert rules1.max_num_same_team_players == 6

    # Re-run migration backfill explicitly on same connection
    with store._connect() as conn:
        store._migrate_to_v4_add_snapshot_game_rules(conn)
        store._migrate_to_v4_add_snapshot_game_rules(conn)

    # Verify rules are still exactly the same
    rules2 = store.load_game_rules(snapshot_id=summary.snapshot_id)
    assert rules2 is not None
    assert rules2.max_num_same_team_players == 6
    assert rules2.raw_json == rules1.raw_json


def test_resolve_ruleset_official_vs_fallback(tmp_path: Path):
    """P1.2 / RULE-1: With official config 6 -> 6; without config -> fallback 6."""
    from euroleague_fantasy_manager.competition.ruleset import League, resolve_ruleset

    # Without db_path -> returns fallback
    base_el = resolve_ruleset(League.EUROLEAGUE)
    assert base_el.max_court_players_per_club == 6
    assert base_el.source == "fallback"

    # With DB containing snapshot fixture (quota 6)
    db_file = tmp_path / "rules_official.sqlite3"
    store = SnapshotStore(db_file)
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "official_config_el.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    summary = store.save_snapshot(payload)
    assert summary is not None

    resolved = resolve_ruleset(League.EUROLEAGUE, db_path=db_file)
    assert resolved.max_court_players_per_club == 6
    assert resolved.source == "official_config"


def test_resolve_ruleset_override_logs_warning(tmp_path: Path, caplog):
    """P1.2: Changing config to 4 -> 4 and logs warning."""
    import logging
    from euroleague_fantasy_manager.competition.ruleset import League, resolve_ruleset

    db_file = tmp_path / "rules_warn.sqlite3"
    store = SnapshotStore(db_file)
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "official_config_el.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    payload["config"]["game_modes_configs"][0]["max_num_same_team_players"] = 4

    summary = store.save_snapshot(payload)
    assert summary is not None

    with caplog.at_level(logging.WARNING):
        resolved = resolve_ruleset(League.EUROLEAGUE, db_path=db_file)
        assert resolved.max_court_players_per_club == 4
        assert resolved.source == "official_config"
        assert "Official config overrides fallback ruleset" in caplog.text
        assert "max_court_players_per_club: 6 -> 4" in caplog.text


def test_eurocup_ruleset_and_unlimited_trade_rounds():
    """P1.2 / DATA-15: EuroCup window lookup uses EuroCup ruleset."""
    from euroleague_fantasy_manager.competition.ruleset import (
        League,
        is_unlimited_trade_round,
        resolve_ruleset,
    )

    ec_rules = resolve_ruleset(League.EUROCUP)
    assert ec_rules.league == League.EUROCUP
    assert ec_rules.max_court_players_per_club == 6
    assert is_unlimited_trade_round(7, ec_rules) is True
    assert is_unlimited_trade_round(14, ec_rules) is True
    assert is_unlimited_trade_round(19, ec_rules) is False  # EL has 19, EC does not

    el_rules = resolve_ruleset(League.EUROLEAGUE)
    assert is_unlimited_trade_round(19, el_rules) is True
