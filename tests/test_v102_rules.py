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
