"""Hermetic tests for V1.0.2 Phase P2: Team state transactions, replay, and concurrency."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import threading
from typing import Any
import pytest
from fastapi.testclient import TestClient

from euroleague_fantasy_manager.multi_team.models import (
    Team,
    TeamRosterUnit,
    TeamSettings,
)
from euroleague_fantasy_manager.multi_team.store import (
    ConcurrentModificationError,
    MAX_TEAMS,
    TeamStore,
)
from euroleague_fantasy_manager.tracking.logger import DecisionLogger
from euroleague_fantasy_manager.tracking.store import DecisionStore
from euroleague_fantasy_manager.web.app import create_app


def _make_dummy_unit(pid: int, pos: str = "G", team_code: str = "EFS") -> TeamRosterUnit:
    return TeamRosterUnit(
        player_id=pid,
        position=pos,
        name=f"Player {pid}",
        team_code=team_code,
        purchase_price_tenths=100,
        current_price_tenths=100,
        is_starter=True,
    )


def _table_snapshot(db_path: Path, table_name: str) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(f"SELECT * FROM {table_name}")
        cols = [d[0] for d in cur.description]
        order_by = cols[0]
        rows = conn.execute(f"SELECT * FROM {table_name} ORDER BY {order_by}").fetchall()
        return rows
    finally:
        conn.close()


def test_p2_1_transaction_rollback_byte_identical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rollback test: Injected exception inside transaction leaves all 5 tables byte-identical."""
    db_file = tmp_path / "rollback_test.sqlite3"
    team_store = TeamStore(db_path=db_file)
    dec_store = DecisionStore(database_path=db_file)
    logger = DecisionLogger(store=dec_store)

    # 1. Establish baseline state
    squad_units = [_make_dummy_unit(100 + i) for i in range(11)]
    initial_team = Team(
        team_id="team_base",
        name="Baseline Team",
        league="euroleague",
        mode="classic",
        season="2026/27",
        round_number=1,
        turn_number=1,
        bank_tenths=50,
        transfers_remaining=4,
        squad=squad_units,
        settings=TeamSettings(),
    )
    team_store.create_team(initial_team)
    team_store.save_round_checkpoint(
        team_id="team_base",
        round_number=1,
        season="2026/27",
        bank_tenths=50,
        transfers_remaining=4,
        squad=squad_units,
    )
    team_store.record_transfers(
        team_id="team_base",
        round_number=1,
        season="2026/27",
        moves=[{"player_out_id": 100, "player_in_id": 200, "price_out_tenths": 100, "price_in_tenths": 100}],
    )
    logger.log_transfer_decision(
        round_number=1,
        season="2026/27",
        team_id="team_base",
        actual_out_ids=[100],
        actual_in_ids=[200],
    )

    # Capture baseline table snapshots across all 5 tables
    tables = [
        "managed_teams",
        "managed_team_squads",
        "team_round_checkpoints",
        "team_transfers",
        "decision_logs",
    ]
    baseline_snapshots = {table: _table_snapshot(db_file, table) for table in tables}

    # Monkeypatch log_transfer_decision to fail after executing some writes
    def _exploding_audit(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Injected audit failure after writes")

    monkeypatch.setattr(logger, "log_transfer_decision", _exploding_audit)

    # 2. Attempt atomic transaction that mutates data and calls the exploding logger
    with pytest.raises(RuntimeError, match="Injected audit failure after writes"):
        with team_store.transaction() as conn:
            # Modify managed_teams
            conn.execute("UPDATE managed_teams SET bank_tenths = 9999 WHERE team_id = 'team_base';")
            # Modify squad
            conn.execute("DELETE FROM managed_team_squads WHERE team_id = 'team_base';")
            # Record transfer
            team_store.record_transfers(
                team_id="team_base",
                round_number=1,
                season="2026/27",
                moves=[{"player_out_id": 101, "player_in_id": 201}],
                conn=conn,
            )
            # Call exploding audit
            logger.log_transfer_decision(
                round_number=1,
                season="2026/27",
                team_id="team_base",
                conn=conn,
            )

    # 3. Assert all 5 tables remain 100% identical to baseline
    for table in tables:
        current_rows = _table_snapshot(db_file, table)
        assert current_rows == baseline_snapshots[table], f"Table {table} differed after transaction rollback!"


def test_p2_1_concurrency_create_team_max_and_single_active(tmp_path: Path) -> None:
    """Concurrency test: 8 threads x 30 trials create teams concurrently -> <= 6 teams, <= 1 active team."""
    num_threads = 8
    num_trials = 30

    for trial in range(num_trials):
        db_file = tmp_path / f"conc_test_{trial}.sqlite3"
        team_store = TeamStore(db_path=db_file)
        barrier = threading.Barrier(num_threads)
        errors: list[Exception] = []

        def worker(thread_idx: int) -> None:
            team_id = f"t_{trial}_{thread_idx}"
            team = Team(
                team_id=team_id,
                name=f"Team {thread_idx}",
                league="euroleague",
                mode="classic",
                season="2026/27",
                round_number=1,
                turn_number=1,
                bank_tenths=0,
                transfers_remaining=4,
                squad=[],
                settings=TeamSettings(),
            )
            try:
                barrier.wait(timeout=5.0)
                team_store.create_team(team)
            except ValueError:
                # Expected when MAX_TEAMS limit reached
                pass
            except Exception as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            for f in futures:
                f.result()

        assert not errors, f"Unexpected errors in trial {trial}: {errors}"

        # Inspect resulting database
        conn = sqlite3.connect(db_file)
        try:
            total_teams = conn.execute("SELECT COUNT(*) FROM managed_teams;").fetchone()[0]
            active_teams = conn.execute("SELECT COUNT(*) FROM managed_teams WHERE is_active = 1;").fetchone()[0]

            assert total_teams <= MAX_TEAMS, f"Exceeded MAX_TEAMS: {total_teams} teams in trial {trial}"
            assert active_teams <= 1, f"Multiple active teams: {active_teams} active teams in trial {trial}"
        finally:
            conn.close()


def test_p2_1_compare_and_set_lost_updates(tmp_path: Path) -> None:
    """Lost updates test: two update_team calls from the same stale read -> the second raises ConcurrentModificationError."""
    db_file = tmp_path / "cas_test.sqlite3"
    team_store = TeamStore(db_path=db_file)

    initial_team = Team(
        team_id="cas_team",
        name="Original Name",
        league="euroleague",
        mode="classic",
        season="2026/27",
        round_number=1,
        turn_number=1,
        bank_tenths=100,
        transfers_remaining=4,
        squad=[],
        settings=TeamSettings(),
    )
    team_store.create_team(initial_team)

    # Read 1 and Read 2 (same initial state)
    read1 = team_store.get_team("cas_team")
    read2 = team_store.get_team("cas_team")
    assert read1 is not None and read2 is not None
    assert read1.updated_at == read2.updated_at

    # Update 1 succeeds
    read1.name = "Updated by Worker 1"
    res1 = team_store.update_team(read1)
    assert res1.name == "Updated by Worker 1"
    assert res1.updated_at != read2.updated_at

    # Update 2 with stale updated_at MUST raise ConcurrentModificationError
    read2.name = "Conflicting Update by Worker 2"
    with pytest.raises(ConcurrentModificationError, match="modified concurrently"):
        team_store.update_team(read2)

    # Verify team state remains as set by Update 1
    final_team = team_store.get_team("cas_team")
    assert final_team is not None
    assert final_team.name == "Updated by Worker 1"


def test_p2_1_web_api_concurrent_modification_returns_409(tmp_path: Path) -> None:
    """Web API test: PATCH /api/teams/{id} with stale updated_at returns HTTP 409 Conflict."""
    db_file = tmp_path / "web_cas_test.sqlite3"
    app = create_app(db_path=str(db_file))
    client = TestClient(app)

    # Create team
    res_create = client.post(
        "/api/teams",
        json={"name": "API Test Team", "league": "euroleague", "round_number": 1},
    )
    assert res_create.status_code == 200
    team_data = res_create.json()
    team_id = team_data["team_id"]
    orig_updated_at = team_data["updated_at"]

    # First update succeeds
    res_up1 = client.patch(
        f"/api/teams/{team_id}",
        json={"name": "Updated Once", "updated_at": orig_updated_at},
    )
    assert res_up1.status_code == 200

    # Second update using the original (now stale) updated_at returns 409
    res_up2 = client.patch(
        f"/api/teams/{team_id}",
        json={"name": "Stale Conflict", "updated_at": orig_updated_at},
    )
    assert res_up2.status_code == 409
    assert "modified concurrently" in res_up2.json()["detail"]
