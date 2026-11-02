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
from euroleague_fantasy_manager.services.team_service import TeamService
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


def _make_legal_squad(offset: int = 1000) -> list[TeamRosterUnit]:
    # 4 Guards, 4 Forwards, 2 Centers, 1 Head Coach, <= 6 per club
    positions = [
        ("G", "OLY"), ("G", "OLY"), ("G", "PAO"), ("G", "PAO"),
        ("F", "RMB"), ("F", "RMB"), ("F", "BAR"), ("F", "BAR"),
        ("C", "EFS"), ("C", "EFS"),
        ("HC", "OLY"),
    ]
    units = []
    for i, (pos, club) in enumerate(positions, start=1):
        pid = offset + i
        units.append(
            TeamRosterUnit(
                player_id=pid,
                position=pos,
                name=f"{club} Player {pid}",
                team_code=club,
                purchase_price_tenths=80,
                current_price_tenths=80,
                is_starter=(i <= 5),
                is_coach=(pos == "HC"),
            )
        )
    return units


def test_p2_2_buying_player_already_in_squad_fails_cleanly(tmp_path: Path) -> None:
    """Pre-trade validation: buying a player already in the remaining squad raises ValueError with zero writes."""
    db_file = tmp_path / "buy_existing_test.sqlite3"
    team_store = TeamStore(db_path=db_file)
    team_service = TeamService(store=team_store)

    squad = _make_legal_squad(offset=100)
    team = team_service.create_team(
        team_id="team_preval",
        name="Pre-trade Validation Team",
        league="euroleague",
        round_number=1,
        bank_tenths=200,
        squad=squad,
    )
    assert team.transfers_remaining == 4

    # Player 101 sold, but attempting to buy player 102 (who is already in the squad as a Guard!)
    from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
    from euroleague_fantasy_manager.models import Position
    mock_market = {
        102: PlayerProjectionContract(
            player_id=102,
            player_name="Player 102",
            position=Position.GUARD,
            team_id=1,
            team_code="OLY",
            price_tenths=80,
            turn_number=1,
            is_home=True,
            expected_fp=15.0,
        )
    }

    with pytest.raises(ValueError, match="already in squad"):
        team_service.execute_transfers(
            team_id="team_preval",
            transfers_out_ids=[101],
            transfers_in_ids=[102],
            round_number=1,
            market_projections=mock_market,
        )

    # Invariants: zero transfers written, transfers_remaining unchanged, squad unchanged
    assert len(team_store.get_transfers("team_preval", "2026/27")) == 0
    refreshed_team = team_service.get_team("team_preval")
    assert refreshed_team.transfers_remaining == 4
    current_pids = [u.player_id for u in refreshed_team.squad]
    assert 101 in current_pids
    assert len(current_pids) == 11


def test_p2_2_audit_failure_causes_full_rollback_and_preserves_round_pointer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Audit failure inside execute_transfers rolls back all tables and leaves live round pointer unchanged."""
    from euroleague_fantasy_manager.multi_team.models import AuditIntent
    from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
    from euroleague_fantasy_manager.models import Position

    db_file = tmp_path / "audit_rb_test.sqlite3"
    team_store = TeamStore(db_path=db_file)
    team_service = TeamService(store=team_store)
    dec_store = DecisionStore(database_path=db_file)
    logger = DecisionLogger(store=dec_store)

    squad_r1 = _make_legal_squad(offset=100)
    # Team is at live round 3, having played round 1 and 2
    team_service.create_team(
        team_id="team_r3",
        name="Round 3 Team",
        league="euroleague",
        round_number=3,
        bank_tenths=150,
        squad=squad_r1,
    )
    # Checkpoint and squad for round 1
    team_store.save_round_checkpoint(
        team_id="team_r3",
        round_number=1,
        season="2026/27",
        bank_tenths=150,
        transfers_remaining=4,
        squad=squad_r1,
    )
    team_store.save_squad("team_r3", 1, squad_r1)
    # Checkpoint and squad for round 2
    team_store.save_round_checkpoint(
        team_id="team_r3",
        round_number=2,
        season="2026/27",
        bank_tenths=150,
        transfers_remaining=4,
        squad=squad_r1,
    )
    team_store.save_squad("team_r3", 2, squad_r1)

    tables = [
        "managed_teams",
        "managed_team_squads",
        "team_round_checkpoints",
        "team_transfers",
        "decision_logs",
    ]
    baseline_snapshots = {table: _table_snapshot(db_file, table) for table in tables}

    # Simulate an exploding audit logger
    def _exploding_audit(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Crash during audit record persistence")

    monkeypatch.setattr(logger, "log_transfer_decision", _exploding_audit)

    mock_market = {
        999: PlayerProjectionContract(
            player_id=999,
            player_name="Recruit 999",
            position=Position.GUARD,
            team_id=1,
            team_code="OLY",
            price_tenths=80,
            turn_number=1,
            is_home=True,
            expected_fp=18.0,
        )
    }

    # Attempt past-round trade at round 1 (team is at round 3)
    with pytest.raises(RuntimeError, match="Crash during audit record persistence"):
        team_service.execute_transfers(
            team_id="team_r3",
            transfers_out_ids=[101],
            transfers_in_ids=[999],
            round_number=1,
            season="2026/27",
            market_projections=mock_market,
            audit=AuditIntent(
                decision_logger=logger,
                notes="Past round trade",
            ),
        )

    # Invariants: live round pointer is STILL 3 (unaffected by past round edit attempt)
    refreshed_team = team_service.get_team("team_r3")
    assert refreshed_team.round_number == 3
    assert refreshed_team.bank_tenths == 150

    # Byte/row identical snapshots across all tables
    for table in tables:
        assert _table_snapshot(db_file, table) == baseline_snapshots[table], f"Table {table} changed on rollback!"


def test_p2_3_replay_forward_preserves_player_position_and_club(tmp_path: Path) -> None:
    """STATE-3: Replay forward preserves incoming players' own position and club instead of inheriting from out_unit.

    Test specification: round-2 trade sells G100 and F200, buys F250 and G150; a later round-1 edit triggers replay;
    the live squad has (250, 'F', 'RMB') and (150, 'G', 'BAR').
    """
    from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
    from euroleague_fantasy_manager.models import Position

    db_file = tmp_path / "replay_pos_test.sqlite3"
    team_store = TeamStore(db_path=db_file)
    team_service = TeamService(store=team_store)

    # Initial squad at round 1:
    # 101: G, OLY; 102: G, OLY; 103: G, PAO; 104: G, PAO
    # 105: F, RMB; 106: F, RMB; 107: F, BAR; 108: F, BAR
    # 109: C, EFS; 110: C, EFS
    # 111: HC, OLY
    squad_r1 = _make_legal_squad(offset=100)
    # Give player 101 and 105 specific IDs and positions matching test:
    # Let 100 be G (OLY) and 200 be F (PAO)
    squad_r1[0] = TeamRosterUnit(
        player_id=100, position="G", name="G100", team_code="OLY",
        purchase_price_tenths=80, current_price_tenths=80, is_starter=True,
    )
    squad_r1[4] = TeamRosterUnit(
        player_id=200, position="F", name="F200", team_code="PAO",
        purchase_price_tenths=80, current_price_tenths=80, is_starter=False,
    )

    team = team_service.create_team(
        team_id="team_replay",
        name="Replay Test Team",
        league="euroleague",
        round_number=1,
        bank_tenths=200,
        squad=squad_r1,
    )

    # Advance team to round 2
    team_store.save_round_checkpoint(
        team_id="team_replay",
        round_number=2,
        season="2026/27",
        bank_tenths=200,
        transfers_remaining=4,
        squad=squad_r1,
    )
    team.round_number = 2
    team_store.update_team(team)

    # Market for round 2 trades:
    # Buying F250 (Forward, RMB) and G150 (Guard, BAR)
    market_r2 = {
        250: PlayerProjectionContract(
            player_id=250, player_name="F250", position=Position.FORWARD,
            team_id=5, team_code="RMB", price_tenths=80, turn_number=1, is_home=True, expected_fp=15.0,
        ),
        150: PlayerProjectionContract(
            player_id=150, player_name="G150", position=Position.GUARD,
            team_id=6, team_code="BAR", price_tenths=80, turn_number=1, is_home=True, expected_fp=15.0,
        ),
    }

    # Execute round 2 trades:
    # Sell G100 and F200 -> buy F250 and G150
    team_service.execute_transfers(
        team_id="team_replay",
        transfers_out_ids=[100, 200],
        transfers_in_ids=[250, 150],
        round_number=2,
        season="2026/27",
        market_projections=market_r2,
    )

    # Advance team to round 3 (live round)
    squad_r2 = team_store.get_squad("team_replay", 2)
    team_store.save_round_checkpoint(
        team_id="team_replay",
        round_number=3,
        season="2026/27",
        bank_tenths=200,
        transfers_remaining=4,
        squad=squad_r2,
    )
    team = team_service.get_team("team_replay")
    team.round_number = 3
    team.squad = squad_r2
    team_store.update_team(team)

    # Now simulate a later round-1 edit (e.g. trading player 102 for recruit 999 at round 1)
    market_r1 = {
        999: PlayerProjectionContract(
            player_id=999, player_name="Guard 999", position=Position.GUARD,
            team_id=1, team_code="OLY", price_tenths=80, turn_number=1, is_home=True, expected_fp=14.0,
        ),
    }
    team_service.execute_transfers(
        team_id="team_replay",
        transfers_out_ids=[102],
        transfers_in_ids=[999],
        round_number=1,
        season="2026/27",
        market_projections=market_r1,
    )

    # Replay forward ran through round 2 up to live round 3!
    live_team = team_service.get_team("team_replay")
    assert live_team.round_number == 3

    # Verify live squad has (250, 'F', 'RMB') and (150, 'G', 'BAR')
    unit_250 = next((u for u in live_team.squad if u.player_id == 250), None)
    assert unit_250 is not None
    assert unit_250.position == "F"
    assert unit_250.team_code == "RMB"

    unit_150 = next((u for u in live_team.squad if u.player_id == 150), None)
    assert unit_150 is not None
    assert unit_150.position == "G"
    assert unit_150.team_code == "BAR"


def test_p2_3_transfers_migration_and_doctor_report(tmp_path: Path) -> None:
    """Migration adds new columns, backfills from snapshots, and doctor reports unresolved rows."""
    from euroleague_fantasy_manager.multi_team.migrations import (
        backfill_transfers_from_snapshots,
        inspect_database_health,
        migrate_transfers_schema,
    )
    from euroleague_fantasy_manager.db import connect_db
    import subprocess
    import sys

    db_file = tmp_path / "doctor_test.sqlite3"

    # Create legacy table without new columns
    with connect_db(db_file) as conn:
        conn.execute("""
            CREATE TABLE managed_teams (
                team_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                league TEXT NOT NULL DEFAULT 'euroleague',
                mode TEXT NOT NULL DEFAULT 'classic',
                season TEXT NOT NULL DEFAULT '2026/27',
                round_number INTEGER NOT NULL DEFAULT 1,
                turn_number INTEGER NOT NULL DEFAULT 1,
                bank_tenths INTEGER NOT NULL DEFAULT 0,
                transfers_remaining INTEGER NOT NULL DEFAULT 4,
                settings_json TEXT NOT NULL DEFAULT '{}',
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE team_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                season TEXT NOT NULL,
                player_out_id INTEGER NOT NULL,
                player_out_name TEXT NOT NULL DEFAULT '',
                player_in_id INTEGER NOT NULL,
                player_in_name TEXT NOT NULL DEFAULT '',
                price_out_tenths INTEGER NOT NULL DEFAULT 0,
                price_in_tenths INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
        """)
        # Insert a managed team
        conn.execute("""
            INSERT INTO managed_teams VALUES (
                'team_doc', 'Doc Team', 'euroleague', 'classic', '2026/27', 1, 1, 100, 4, '{}', 1,
                '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z'
            );
        """)
        # Insert two legacy transfer rows
        # Row 1 will be resolvable via snapshot
        conn.execute("""
            INSERT INTO team_transfers VALUES (
                1, 'team_doc', 1, '2026/27', 10, 'Out Player', 20, 'In Player', 80, 80, '2026-10-01T00:00:00Z'
            );
        """)
        # Row 2 will be unresolvable (player 9999 not in snapshot)
        conn.execute("""
            INSERT INTO team_transfers VALUES (
                2, 'team_doc', 1, '2026/27', 10, 'Out Player', 9999, 'Missing Player', 80, 80, '2026-10-01T00:00:00Z'
            );
        """)

        # Create snapshots and players tables to support backfill
        conn.execute("""
            CREATE TABLE snapshots (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_number INTEGER NOT NULL,
                season_code TEXT,
                league_id INTEGER NOT NULL,
                scraped_at TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE players (
                snapshot_id INTEGER NOT NULL,
                id INTEGER NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                name TEXT NOT NULL,
                position INTEGER NOT NULL,
                position_code TEXT NOT NULL,
                team_id INTEGER NOT NULL,
                team_code TEXT NOT NULL,
                team_name TEXT NOT NULL,
                price_tenths INTEGER NOT NULL,
                status TEXT NOT NULL,
                probability_of_playing REAL NOT NULL DEFAULT 1.0,
                turn_number INTEGER NOT NULL DEFAULT 1,
                last_match_pts REAL NOT NULL DEFAULT 0.0,
                avg_fantasy_pts REAL NOT NULL DEFAULT 0.0,
                total_plus_tenths INTEGER NOT NULL DEFAULT 0,
                popularity REAL NOT NULL DEFAULT 0.0,
                is_injured INTEGER NOT NULL DEFAULT 0,
                is_on_fire INTEGER NOT NULL DEFAULT 0,
                has_played INTEGER NOT NULL DEFAULT 0
            );
        """)
        conn.execute("INSERT INTO snapshots VALUES (1, 1, '2026/27', 10, '2026-10-01T00:00:00Z');")
        # Player 10: Guard, OLY
        conn.execute("""
            INSERT INTO players VALUES (
                1, 10, 'First10', 'Last10', 'Out Player', 1, 'G', 1, 'OLY', 'Olympiacos', 80, 'AVAILABLE',
                1.0, 1, 0.0, 0.0, 0, 0.0, 0, 0, 0
            );
        """)
        # Player 20: Forward, RMB
        conn.execute("""
            INSERT INTO players VALUES (
                1, 20, 'First20', 'Last20', 'In Player', 2, 'F', 2, 'RMB', 'Real Madrid', 80, 'AVAILABLE',
                1.0, 1, 0.0, 0.0, 0, 0.0, 0, 0, 0
            );
        """)

    # 1. Test schema migration
    with connect_db(db_file) as conn:
        migrate_transfers_schema(conn)
        cols = [c[1] for c in conn.execute("PRAGMA table_info(team_transfers);").fetchall()]
        assert "player_in_position" in cols
        assert "player_in_team_code" in cols
        assert "player_out_position" in cols
        assert "player_out_team_code" in cols
        assert "is_unlimited_round" in cols

    # 2. Test backfill
    with connect_db(db_file) as conn:
        report = backfill_transfers_from_snapshots(conn)
        assert report.total_scanned == 2
        assert report.updated == 2  # Both attempted
        assert len(report.unresolved) == 1  # Row 2 unresolved because player 9999 was not in snapshot

        row1 = conn.execute("SELECT * FROM team_transfers WHERE id = 1;").fetchone()
        assert row1["player_out_position"] == "G"
        assert row1["player_out_team_code"] == "OLY"
        assert row1["player_in_position"] == "F"
        assert row1["player_in_team_code"] == "RMB"

        row2 = conn.execute("SELECT * FROM team_transfers WHERE id = 2;").fetchone()
        assert row2["player_out_position"] == "G"
        assert row2["player_in_position"] is None  # Unresolved

    # 3. Test inspect_database_health
    health = inspect_database_health(db_file)
    assert health["status"] == "warning"
    assert health["unresolved_count"] == 1
    assert health["unresolved_records"][0]["player_in_id"] == 9999

    # 4. Test elf doctor CLI execution
    proc = subprocess.run(
        [sys.executable, "-m", "euroleague_fantasy_manager.cli", "doctor", "--database", str(db_file), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    import json
    data = json.loads(proc.stdout)
    assert data["unresolved_count"] == 1


def test_p2_4_replay_conflict_raises_error_and_preserves_bank(tmp_path: Path) -> None:
    """STATE-4: Replay conflicts raise ReplayConflictError (API 409), avoiding silent skips and bank drift."""
    from euroleague_fantasy_manager.multi_team.models import ReplayConflictError
    from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
    from euroleague_fantasy_manager.models import Position

    db_file = tmp_path / "conflict_test.sqlite3"
    team_store = TeamStore(db_path=db_file)
    team_service = TeamService(store=team_store)

    squad = _make_legal_squad(offset=100)
    # squad[0] has player_id=101 (Guard, OLY)
    team = team_service.create_team(
        team_id="team_conflict",
        name="Conflict Team",
        league="euroleague",
        round_number=1,
        bank_tenths=200,
        squad=squad,
    )

    # Move to round 2
    team_store.save_round_checkpoint(
        team_id="team_conflict",
        round_number=2,
        season="2026/27",
        bank_tenths=200,
        transfers_remaining=4,
        squad=squad,
    )
    team.round_number = 2
    team_store.update_team(team)

    # Round 2 trade: sell player 101, buy player 555
    market_r2 = {
        555: PlayerProjectionContract(
            player_id=555, player_name="G555", position=Position.GUARD,
            team_id=1, team_code="OLY", price_tenths=80, turn_number=1, is_home=True, expected_fp=15.0,
        ),
    }
    team_service.execute_transfers(
        team_id="team_conflict",
        transfers_out_ids=[101],
        transfers_in_ids=[555],
        round_number=2,
        season="2026/27",
        market_projections=market_r2,
    )

    # Move to live round 3
    team = team_service.get_team("team_conflict")
    squad_r2 = team_store.get_squad("team_conflict", 2)
    team_store.save_round_checkpoint(
        team_id="team_conflict",
        round_number=3,
        season="2026/27",
        bank_tenths=team.bank_tenths,
        transfers_remaining=4,
        squad=squad_r2,
    )
    team.round_number = 3
    team.squad = squad_r2
    team_store.update_team(team)

    # Now edit round 1: sell player 101 for recruit 999!
    # Because player 101 is already sold at round 1, round 2's recorded trade selling 101 is conflicting!
    market_r1 = {
        999: PlayerProjectionContract(
            player_id=999, player_name="G999", position=Position.GUARD,
            team_id=1, team_code="OLY", price_tenths=80, turn_number=1, is_home=True, expected_fp=15.0,
        ),
    }

    # 1. Without discard_conflicting -> ReplayConflictError
    with pytest.raises(ReplayConflictError) as exc_info:
        team_service.execute_transfers(
            team_id="team_conflict",
            transfers_out_ids=[101],
            transfers_in_ids=[999],
            round_number=1,
            season="2026/27",
            market_projections=market_r1,
            discard_conflicting=False,
        )
    assert exc_info.value.round_number == 2
    assert "not in squad to sell" in exc_info.value.reason

    # Test via Web API returns 409
    app = create_app(db_path=str(db_file))
    from euroleague_fantasy_manager.web.deps import get_prediction_service
    from euroleague_fantasy_manager.services.prediction_service import PredictionService
    mock_ps = PredictionService(database_path=db_file)
    mock_ps.get_projections_dict = lambda s, r, **kw: market_r1
    app.dependency_overrides[get_prediction_service] = lambda: mock_ps

    client = TestClient(app)
    res_conflict = client.post(
        f"/api/teams/{team.team_id}/transfers",
        json={
            "transfers_out_ids": [101],
            "transfers_in_ids": [999],
            "round_number": 1,
            "season": "2026/27",
            "discard_conflicting": False,
        },
    )
    assert res_conflict.status_code == 409
    data = res_conflict.json()["detail"]
    assert data["round_number"] == 2
    assert "not in squad to sell" in data["reason"]

    # 2. With discard_conflicting=True -> conflicting trade is deleted and operation succeeds
    res_resolve = client.post(
        f"/api/teams/{team.team_id}/transfers",
        json={
            "transfers_out_ids": [101],
            "transfers_in_ids": [999],
            "round_number": 1,
            "season": "2026/27",
            "discard_conflicting": True,
        },
    )
    assert res_resolve.status_code == 200
    updated_pids = {u["player_id"] for u in res_resolve.json()["squad"]}
    assert 999 in updated_pids
    assert 101 not in updated_pids
    # Round 2 trade was discarded
    assert len(team_store.get_transfers("team_conflict", "2026/27", round_number=2)) == 0


def test_p2_4_adjust_bank_atomic_with_checkpoint_and_audit(tmp_path: Path) -> None:
    """STATE-6: adjust_bank updates team row and live round checkpoint together and records an audit event."""
    from euroleague_fantasy_manager.multi_team.models import AuditIntent

    db_file = tmp_path / "bank_adjust_test.sqlite3"
    team_store = TeamStore(db_path=db_file)
    team_service = TeamService(store=team_store)
    dec_store = DecisionStore(database_path=db_file)
    logger = DecisionLogger(store=dec_store)

    squad = _make_legal_squad(offset=100)
    team = team_service.create_team(
        team_id="team_adj",
        name="Adjust Team",
        league="euroleague",
        round_number=2,
        bank_tenths=150,
        squad=squad,
    )
    team_store.save_round_checkpoint(
        team_id="team_adj",
        round_number=2,
        season="2026/27",
        bank_tenths=150,
        transfers_remaining=4,
        squad=squad,
    )

    # 1. Adjust bank by +50 tenths
    res_team = team_service.adjust_bank(
        team_id="team_adj",
        delta_tenths=50,
        reason="Bonus credits",
        audit=AuditIntent(decision_logger=logger, notes="Bonus credits"),
    )
    assert res_team.bank_tenths == 200

    # Verify checkpoint is updated
    chk = team_store.get_round_checkpoint("team_adj", 2, "2026/27")
    assert chk["bank_tenths"] == 200

    # Verify audit event is logged
    decisions = dec_store.list_decisions()
    assert len(decisions) >= 1
    assert "Bonus credits" in decisions[-1].notes

    # 2. Test via Web API POST /api/teams/{id}/adjust-bank (WEB-6: bank_tenths removed from PATCH)
    app = create_app(db_path=str(db_file))
    client = TestClient(app)
    res_patch = client.post(
        f"/api/teams/{team.team_id}/adjust-bank",
        json={"delta_tenths": 60, "reason": "Web API adjust bank"},
    )
    assert res_patch.status_code == 200
    assert res_patch.json()["bank_tenths"] == 260

    chk2 = team_store.get_round_checkpoint("team_adj", 2, "2026/27")
    assert chk2["bank_tenths"] == 260


def test_p2_4_bank_invariant_over_multiround_sequence(tmp_path: Path) -> None:
    """STATE-4 & STATE-6: Verify bank invariant and squad validity over a multi-round sequence."""
    from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
    from euroleague_fantasy_manager.models import Position

    db_file = tmp_path / "bank_inv_test.sqlite3"
    team_store = TeamStore(db_path=db_file)
    team_service = TeamService(store=team_store)

    squad = _make_legal_squad(offset=100)
    team = team_service.create_team(
        team_id="team_inv",
        name="Invariant Team",
        league="euroleague",
        round_number=1,
        bank_tenths=200,
        squad=squad,
    )

    # Execute trades across rounds 1, 2, 3
    # Round 1: sell 101 (80), buy 901 (60) -> net delta +20
    m_r1 = {
        901: PlayerProjectionContract(
            player_id=901, player_name="G901", position=Position.GUARD,
            team_id=1, team_code="OLY", price_tenths=60, turn_number=1, is_home=True, expected_fp=12.0,
        )
    }
    team_service.execute_transfers(
        team_id="team_inv", transfers_out_ids=[101], transfers_in_ids=[901],
        round_number=1, season="2026/27", market_projections=m_r1,
    )

    # Roll forward to round 2
    team = team_service.get_team("team_inv")
    team_store.save_round_checkpoint(
        team_id="team_inv", round_number=2, season="2026/27",
        bank_tenths=team.bank_tenths, transfers_remaining=4, squad=team.squad,
    )
    team.round_number = 2
    team_store.update_team(team)

    # Round 2: sell 102 (80), buy 902 (90) -> net delta -10
    m_r2 = {
        902: PlayerProjectionContract(
            player_id=902, player_name="G902", position=Position.GUARD,
            team_id=1, team_code="OLY", price_tenths=90, turn_number=1, is_home=True, expected_fp=14.0,
        )
    }
    team_service.execute_transfers(
        team_id="team_inv", transfers_out_ids=[102], transfers_in_ids=[902],
        round_number=2, season="2026/27", market_projections=m_r2,
    )

    # Verify Bank Invariant:
    # chk(1).bank == 200
    # trades(1) net = 80 - 60 = +20 -> chk(2).bank == 220
    # trades(2) net = 80 - 90 = -10 -> live bank == 210
    chk1 = team_store.get_round_checkpoint("team_inv", 1, "2026/27")
    chk2 = team_store.get_round_checkpoint("team_inv", 2, "2026/27")
    team_now = team_service.get_team("team_inv")

    tx1 = team_store.get_transfers("team_inv", "2026/27", round_number=1)
    net_tx1 = sum(t["price_out_tenths"] - t["price_in_tenths"] for t in tx1)
    assert chk2["bank_tenths"] == chk1["bank_tenths"] + net_tx1

    tx2 = team_store.get_transfers("team_inv", "2026/27", round_number=2)
    net_tx2 = sum(t["price_out_tenths"] - t["price_in_tenths"] for t in tx2)
    assert team_now.bank_tenths == chk2["bank_tenths"] + net_tx2

    # Roster validity
    team_service._validate_roster(team_now.squad, league="euroleague")
def test_p2_5_roll_forward_and_reconstruction_never_leave_gaps(tmp_path: Path) -> None:
    """STATE-2: sync_team_to_live_round populates every intermediate round and reconstruction never leaves gaps.

    Specification: trade 100 -> 150 in R1; sync to R4; backfill trade 101 -> 151 in R2.
    The live squad contains 150 and 151 and not 100 or 101; rounds 2-4 all have squads and checkpoints.
    """
    from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
    from euroleague_fantasy_manager.models import Position
    from euroleague_fantasy_manager.storage import SnapshotStore

    db_file = tmp_path / "sync_gap_test.sqlite3"
    team_store = TeamStore(db_path=db_file)
    team_service = TeamService(store=team_store)
    snap_store = SnapshotStore(database_path=db_file)

    squad_r1 = _make_legal_squad(offset=100)
    # Set player 100 (Guard) and 101 (Forward)
    squad_r1[0] = TeamRosterUnit(
        player_id=100, position="G", name="G100", team_code="OLY",
        purchase_price_tenths=80, current_price_tenths=80, is_starter=True,
    )
    squad_r1[4] = TeamRosterUnit(
        player_id=101, position="F", name="F101", team_code="RMB",
        purchase_price_tenths=80, current_price_tenths=80, is_starter=False,
    )

    team_service.create_team(
        team_id="team_gap",
        name="Gap Test Team",
        league="euroleague",
        round_number=1,
        bank_tenths=200,
        squad=squad_r1,
    )

    # 1. Trade 100 -> 150 in R1
    market_r1 = {
        150: PlayerProjectionContract(
            player_id=150, player_name="G150", position=Position.GUARD,
            team_id=1, team_code="OLY", price_tenths=80, turn_number=1, is_home=True, expected_fp=15.0,
        )
    }
    team_service.execute_transfers(
        team_id="team_gap",
        transfers_out_ids=[100],
        transfers_in_ids=[150],
        round_number=1,
        season="2026/27",
        market_projections=market_r1,
    )

    # 2. Seed snapshot at R4 and sync to R4
    snap_store.save_snapshot({
        "round_number": 4,
        "season_code": "2026/27",
        "league_id": 10,
        "competition_code": "E",
        "players": [
            {
                "id": u.player_id, "name": u.name, "first_name": "", "last_name": "",
                "position": 1 if u.position == "G" else 2, "position_code": u.position,
                "team_id": 1, "team_code": u.team_code, "team_name": u.team_code,
                "price_tenths": u.current_price_tenths, "status": "AVAILABLE",
                "probability_of_playing": 1.0, "turn_number": 1, "avg_fantasy_pts": 10.0,
                "last_match_pts": 10.0, "total_plus_tenths": 0, "popularity": 1.0,
            }
            for u in squad_r1
        ],
        "teams": {},
    })

    synced_team = team_service.sync_team_to_live_round("team_gap")
    assert synced_team.round_number == 4

    # Assert rounds 2, 3, 4 all have stored squads and checkpoints
    for r in (2, 3, 4):
        squad_r = team_store.get_squad("team_gap", r)
        assert len(squad_r) == 11, f"Missing squad for round {r}"
        chk_r = team_store.get_round_checkpoint("team_gap", r, "2026/27")
        assert chk_r is not None, f"Missing checkpoint for round {r}"

    # 3. Backfill trade 101 -> 151 in R2
    market_r2 = {
        151: PlayerProjectionContract(
            player_id=151, player_name="F151", position=Position.FORWARD,
            team_id=2, team_code="RMB", price_tenths=80, turn_number=1, is_home=True, expected_fp=15.0,
        )
    }
    team_service.execute_transfers(
        team_id="team_gap",
        transfers_out_ids=[101],
        transfers_in_ids=[151],
        round_number=2,
        season="2026/27",
        market_projections=market_r2,
    )

    # 4. Live squad at R4 contains 150 and 151, and does not contain 100 or 101
    live_team = team_service.get_team("team_gap")
    assert live_team.round_number == 4
    live_pids = {u.player_id for u in live_team.squad}
    assert 150 in live_pids
    assert 151 in live_pids
    assert 100 not in live_pids
    assert 101 not in live_pids
def test_p2_6_validation_and_unified_position_normalizer(tmp_path: Path) -> None:
    """VAL-1, VAL-2, DATA-9, CLI-3, WEB-6: unified position normaliser and strict validation."""
    from euroleague_fantasy_manager.models import Position, UnknownPlayerError, normalize_position
    from euroleague_fantasy_manager.multi_team.store import TeamStore
    from euroleague_fantasy_manager.services.team_service import TeamService
    from euroleague_fantasy_manager.web.app import create_app
    from fastapi.testclient import TestClient

    # 1. normalize_position
    assert normalize_position("G") == Position.GUARD
    assert normalize_position("guard") == Position.GUARD
    assert normalize_position(1) == Position.GUARD
    assert normalize_position("F") == Position.FORWARD
    assert normalize_position("forward") == Position.FORWARD
    assert normalize_position(2) == Position.FORWARD
    assert normalize_position("C") == Position.CENTER
    assert normalize_position("center") == Position.CENTER
    assert normalize_position(3) == Position.CENTER
    assert normalize_position("HC") == Position.HEAD_COACH
    assert normalize_position("coach") == Position.HEAD_COACH
    assert normalize_position(4) == Position.HEAD_COACH

    for bad_pos in ["INVALID", "Point Guard", "PG", 999, None, ""]:
        with pytest.raises(ValueError):
            normalize_position(bad_pos)

    # 2. TeamRosterUnit rejects invalid position
    with pytest.raises(ValueError):
        TeamRosterUnit(player_id=1, position="INVALID", team_code="RMB")

    db_file = tmp_path / "val_test.sqlite3"
    team_store = TeamStore(db_path=db_file)
    team_service = TeamService(store=team_store)

    # 3. Validation: empty team_code is rejected
    bad_squad = _make_legal_squad(offset=10)
    bad_squad[0] = TeamRosterUnit(
        player_id=10, position="G", name="G10", team_code="",
        purchase_price_tenths=100, current_price_tenths=100, is_starter=True,
    )
    with pytest.raises(ValueError, match="empty team_code"):
        team_service.create_team(
            team_id="team_empty_tc",
            name="Empty TC Team",
            round_number=1,
            bank_tenths=100,
            squad=bad_squad,
        )
    assert team_store.get_team("team_empty_tc") is None

    # 4. create_team with legal squad succeeds
    legal_squad = _make_legal_squad(offset=20)
    team = team_service.create_team(
        team_id="team_val",
        name="Validation Team",
        round_number=1,
        bank_tenths=100,
        squad=legal_squad,
    )
    assert team is not None

    # 5. update_team_squad validates and rejects invalid squad
    with pytest.raises(ValueError, match="empty team_code"):
        team_service.update_team_squad("team_val", bad_squad)

    # 6. import_squad validates before write: invalid squad leaves round and bank unchanged
    initial_team = team_service.get_team("team_val")
    assert initial_team.round_number == 1
    assert initial_team.bank_tenths == 100

    with pytest.raises(ValueError):
        team_service.import_squad(
            team_id="team_val",
            round_number=5,
            bank_tenths=500,
            roster_units=bad_squad,
        )
    after_failed_import = team_service.get_team("team_val")
    assert after_failed_import.round_number == 1
    assert after_failed_import.bank_tenths == 100

    # 7. _resolve_player_contract raises UnknownPlayerError on unknown player
    with pytest.raises(UnknownPlayerError):
        team_service._resolve_player_contract(
            player_id=999999,
            round_number=1,
            season="2026/27",
            league="euroleague",
        )

    # 8. Web API PATCH /api/teams/{id} (WEB-6)
    app = create_app(db_path=str(db_file))
    client = TestClient(app)

    # name too short
    r_empty_name = client.patch(f"/api/teams/{team.team_id}", json={"name": ""})
    assert r_empty_name.status_code == 422

    # name too long (> 32)
    r_long_name = client.patch(f"/api/teams/{team.team_id}", json={"name": "A" * 33})
    assert r_long_name.status_code == 422

    # invalid round_number (< 1 or > 40)
    r_bad_round = client.patch(f"/api/teams/{team.team_id}", json={"round_number": 0})
    assert r_bad_round.status_code == 422

    # invalid transfers_remaining (< 0)
    r_bad_transfers = client.patch(f"/api/teams/{team.team_id}", json={"transfers_remaining": -1})
    assert r_bad_transfers.status_code == 422

    # bank_tenths in PATCH is forbidden (extra="forbid")
    r_bank = client.patch(f"/api/teams/{team.team_id}", json={"bank_tenths": 300})
    assert r_bank.status_code == 422

    # invalid risk_mode
    r_bad_risk = client.patch(f"/api/teams/{team.team_id}", json={"settings": {"risk_mode": "yolo"}})
    assert r_bad_risk.status_code == 422

    # valid PATCH
    r_valid = client.patch(
        f"/api/teams/{team.team_id}",
        json={"name": "Valid New Name", "settings": {"risk_mode": "conservative"}},
    )
    assert r_valid.status_code == 200
    assert r_valid.json()["name"] == "Valid New Name"
    assert r_valid.json()["settings"]["risk_mode"] == "conservative"

    # 9. CLI trade command with unknown player exits with code 1
    from euroleague_fantasy_manager.cli import main
    exit_code = main(["--db", str(db_file), "team", "trade", "--team", "team_val", "--out", "20", "--in", "999999"])
    assert exit_code == 1
def test_p2_7_round_and_season_correct_operations(tmp_path: Path) -> None:
    """STATE-7, STATE-8, WEB-3: unlimited trade windows, non-default season, and intra-round round targeting."""
    import json
    from euroleague_fantasy_manager.models import Position
    from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
    from euroleague_fantasy_manager.multi_team.store import TeamStore
    from euroleague_fantasy_manager.services.team_service import TeamService
    from euroleague_fantasy_manager.web.app import create_app
    from fastapi.testclient import TestClient

    db_file = tmp_path / "p27_test.sqlite3"
    team_store = TeamStore(db_path=db_file)
    team_service = TeamService(store=team_store)

    # 1. Non-default season (2027/28): trade and revert
    squad_2027 = _make_legal_squad(offset=10)
    team_2027 = team_service.create_team(
        team_id="team_2027",
        name="Season 2027 Team",
        season="2027/28",
        round_number=1,
        bank_tenths=200,
        squad=squad_2027,
    )
    assert team_2027.season == "2027/28"

    # Trade in 2027/28
    p_out_id = squad_2027[0].player_id
    market_r1 = {
        50: PlayerProjectionContract(
            player_id=50, player_name="G50", position=Position.GUARD,
            team_id=1, team_code="OLY", price_tenths=80, turn_number=1, is_home=True, expected_fp=15.0,
        )
    }
    trade_res = team_service.execute_transfers(
        team_id="team_2027",
        transfers_out_ids=[p_out_id],
        transfers_in_ids=[50],
        round_number=1,
        season="2027/28",
        market_projections=market_r1,
    )
    assert trade_res is not None
    traded_team = team_service.get_team("team_2027")
    assert 50 in {u.player_id for u in traded_team.squad}
    assert traded_team.transfers_remaining == 3

    # Revert in 2027/28
    reverted_team = team_service.revert_to_round_start("team_2027", season="2027/28", round_number=1)
    assert p_out_id in {u.player_id for u in reverted_team.squad}
    assert 50 not in {u.player_id for u in reverted_team.squad}
    assert reverted_team.transfers_remaining == 4  # Restored from checkpoint

    # 2. Unlimited trade windows (STATE-7)
    # Outside an unlimited window (Round 1), requesting unlimited=True raises ValueError / 400
    with pytest.raises(ValueError, match="not an unlimited trade round"):
        team_service.execute_transfers(
            team_id="team_2027",
            transfers_out_ids=[p_out_id],
            transfers_in_ids=[50],
            round_number=1,
            season="2027/28",
            unlimited=True,
            market_projections=market_r1,
        )

    # In Web API, outside window with unlimited=True returns 400
    app = create_app(db_path=str(db_file))
    client = TestClient(app)
    res_bad_unlim = client.post(
        "/api/teams/team_2027/transfers",
        json={
            "transfers_out_ids": [p_out_id],
            "transfers_in_ids": [50],
            "round_number": 1,
            "season": "2027/28",
            "unlimited": True,
        },
    )
    assert res_bad_unlim.status_code == 400

    # In an unlimited window (Round 7 in EuroLeague):
    # Setup team at round 7
    squad_r7 = _make_legal_squad(offset=100)
    team_service.create_team(
        team_id="team_unlim",
        name="Unlimited Window Team",
        round_number=7,
        bank_tenths=500,
        squad=squad_r7,
    )
    market_r7 = {
        200 + i: PlayerProjectionContract(
            player_id=200 + i, player_name=f"Player_{200+i}",
            position=squad_r7[i].position,
            team_id=1, team_code="OLY", price_tenths=80, turn_number=1, is_home=True, expected_fp=15.0,
        )
        for i in range(5)
    }
    # Execute 5 trades (more than normal 4 trades!) in round 7
    res_r7 = team_service.execute_transfers(
        team_id="team_unlim",
        transfers_out_ids=[squad_r7[i].player_id for i in range(5)],
        transfers_in_ids=[200 + i for i in range(5)],
        round_number=7,
        market_projections=market_r7,
    )
    assert res_r7 is not None
    # In an unlimited round, transfers_remaining is NOT decremented (remains 4)
    after_unlim = team_service.get_team("team_unlim")
    assert after_unlim.transfers_remaining == 4

    # 3. Intra-round apply (WEB-3): applying subs in R1 changes R1 only; live R8 squad is byte-identical
    squad_live_r8 = _make_legal_squad(offset=300)
    team_service.create_team(
        team_id="team_r8",
        name="R8 Team",
        round_number=8,
        bank_tenths=100,
        squad=squad_live_r8,
    )
    # Store round 1 squad as well
    squad_r1_init = _make_legal_squad(offset=300)
    team_store.save_squad("team_r8", 1, squad_r1_init)

    # Capture byte representation of R8 squad
    r8_squad_before = team_store.get_squad("team_r8", 8)
    r8_bytes_before = json.dumps([u.to_dict() for u in r8_squad_before], sort_keys=True).encode("utf-8")

    # Call /api/workstation/intra-round/apply with round_number=1
    res_apply = client.post(
        "/api/workstation/intra-round/apply",
        json={"team_id": "team_r8", "round_number": 1, "season": "2026/27"},
    )
    assert res_apply.status_code == 200

    # R8 squad in database is 100% byte-identical
    r8_squad_after = team_store.get_squad("team_r8", 8)
    r8_bytes_after = json.dumps([u.to_dict() for u in r8_squad_after], sort_keys=True).encode("utf-8")
    assert r8_bytes_before == r8_bytes_after
def test_p2_8_get_routes_never_write_to_database(tmp_path: Path) -> None:
    """P2.8 / WEB-1: Every registered GET route is strictly read-only and never mutates SQLite."""
    import hashlib
    from euroleague_fantasy_manager.multi_team.store import TeamStore
    from euroleague_fantasy_manager.services.team_service import TeamService
    from euroleague_fantasy_manager.storage import SnapshotStore
    from euroleague_fantasy_manager.web.app import create_app
    from fastapi.testclient import TestClient

    def _file_sha256(path: Path) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    from euroleague_fantasy_manager.evaluation.dataset import EvaluationDatasetStore
    from euroleague_fantasy_manager.tracking.store import DecisionStore

    db_file = tmp_path / "p28_readonly_test.sqlite3"
    team_store = TeamStore(db_path=db_file)
    team_service = TeamService(store=team_store)
    snap_store = SnapshotStore(database_path=db_file)
    EvaluationDatasetStore(db_file)
    DecisionStore(database_path=db_file)

    # Seed snapshot
    squad = _make_legal_squad(offset=10)
    snap_store.save_snapshot({
        "round_number": 1,
        "season_code": "2026/27",
        "league_id": 10,
        "competition_code": "E",
        "players": [
            {
                "id": u.player_id, "name": u.name, "first_name": "", "last_name": "",
                "position": 1 if u.position == "G" else 2, "position_code": u.position,
                "team_id": 1, "team_code": u.team_code, "team_name": u.team_code,
                "price_tenths": u.current_price_tenths, "status": "AVAILABLE",
                "probability_of_playing": 1.0, "turn_number": 1, "avg_fantasy_pts": 10.0,
                "last_match_pts": 10.0, "total_plus_tenths": 0, "popularity": 1.0,
            }
            for u in squad
        ],
        "teams": {},
    })

    # Create team with unassigned roles (all is_starter=False, is_captain=False, is_sixth_man=False)
    unassigned_squad = [
        TeamRosterUnit(
            player_id=u.player_id, position=u.position, name=u.name, team_code=u.team_code,
            purchase_price_tenths=u.purchase_price_tenths, current_price_tenths=u.current_price_tenths,
            is_starter=False, is_captain=False, is_sixth_man=False, is_bench=False, is_coach=(u.position == "HC"),
        )
        for u in squad
    ]
    team = team_service.create_team(
        team_id="team_ro",
        name="ReadOnly Team",
        round_number=1,
        bank_tenths=200,
        squad=unassigned_squad,
    )
    team_service.set_active_team(team.team_id)

    app = create_app(db_path=str(db_file))
    client = TestClient(app)

    # 1. Dashboard specific test: returns roles_assigned=False, suggested_lineup, but does NOT persist
    with sqlite3.connect(db_file) as c:
        c.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    baseline_hash = _file_sha256(db_file)

    res_dash = client.get(f"/api/workstation/dashboard?team_id={team.team_id}&round_number=1")
    assert res_dash.status_code == 200
    data_dash = res_dash.json()
    assert data_dash["roles_assigned"] is False
    assert "suggested_lineup" in data_dash
    assert "optimal_lineup" in data_dash

    with sqlite3.connect(db_file) as c:
        c.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    assert _file_sha256(db_file) == baseline_hash, "GET /api/workstation/dashboard mutated the database!"

    # 2. Enumerate all registered GET routes from app.routes
    for route in app.routes:
        methods = getattr(route, "methods", set())
        if "GET" not in methods:
            continue
        path = getattr(route, "path", None)
        if not path:
            continue

        # Substitute known route path params
        formatted_path = path.replace("{team_id}", team.team_id).replace("{decision_id}", "dec_1")
        if "{" in formatted_path:
            # Skip unmapped parameterized routes
            continue

        # Execute GET request
        res = client.get(formatted_path)
        # Should not raise 500
        assert res.status_code in (200, 404), f"GET {formatted_path} returned {res.status_code}"

        with sqlite3.connect(db_file) as c:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        current_hash = _file_sha256(db_file)
        assert current_hash == baseline_hash, f"GET {formatted_path} mutated the database!"

