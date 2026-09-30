"""Comprehensive test suite for V0.7 deliverables:
- F1: Multi-season historical datasets (EuroLeague & EuroCup)
- F2: Point-in-time state reconstruction
- F3: Sequential decision simulation (transfers, lineups, T1->T2 substitutions)
- F4: Model-version comparison ledgers (against human decisions and hindsight oracle)
- F5 & F7: Historical regret attribution with documented tolerance (|residual| <= 1.0 FP)
- F8: Strong zero-mutation invariant during simulation replay
- §3.2: Past-round trade execution with forward replay and transfer cap
- §3.3: CLI round-aware entry (elf team set-lineup --round N, elf team trade --round N)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from euroleague_fantasy_manager.cli import main as cli_main
from euroleague_fantasy_manager.evaluation.dataset import (
    EvaluationDatasetStore,
    build_historical_dataset,
)
from euroleague_fantasy_manager.multi_team.models import PointInTimeTeamState, TeamRosterUnit
from euroleague_fantasy_manager.multi_team.store import TeamStore
from euroleague_fantasy_manager.optimization.sequential_replay import (
    ModelComparisonLedger,
    RegretAttribution,
    SequentialDecisionSimulator,
    SequentialSeasonReplayLedger,
)
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.storage import SnapshotStore, seed_historical_snapshots


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Create and seed offline multi-season EuroLeague and EuroCup datasets."""
    db_path = tmp_path / "v07_test.sqlite3"
    build_historical_dataset(
        database_path=db_path,
        seasons=("E2024", "E2025", "U2024", "U2025"),
        rounds_per_season=4,
    )
    seed_historical_snapshots(
        database_path=db_path,
        seasons=("E2024", "E2025", "U2024", "U2025"),
        rounds_per_season=4,
    )
    return db_path


def test_f1_multiseason_datasets_euroleague_and_eurocup(test_db: Path) -> None:
    """F1: Ingest historical round snapshots for EuroLeague AND EuroCup across seasons."""
    store = EvaluationDatasetStore(test_db)
    seasons = store.list_seasons()
    assert "E2024" in seasons
    assert "E2025" in seasons
    assert "U2024" in seasons
    assert "U2025" in seasons

    leagues = store.list_leagues()
    assert "euroleague" in leagues
    assert "eurocup" in leagues

    assert store.list_seasons(league="eurocup") == ["U2024", "U2025"]
    assert store.list_seasons(league="euroleague") == ["E2024", "E2025"]

    snap_store = SnapshotStore(test_db)
    snapshots = snap_store.list_snapshots()
    assert len(snapshots) >= 8  # 4 rounds * 2 leagues


def test_f2_point_in_time_state_reconstruction(test_db: Path) -> None:
    """F2: Reconstruct squad valuation, bank, availability, and price changes at round boundaries."""
    team_store = TeamStore(db_path=test_db)
    service = TeamService(store=team_store)

    # Initial squad for team
    squad_units = [
        TeamRosterUnit(101, "G", "G1", "PAO", 80, 80, is_starter=True, is_captain=True),
        TeamRosterUnit(102, "G", "G2", "OLY", 80, 80, is_starter=True),
        TeamRosterUnit(103, "G", "G3", "RMB", 80, 80, is_bench=True),
        TeamRosterUnit(104, "G", "G4", "BAR", 80, 80, is_bench=True),
        TeamRosterUnit(105, "F", "F1", "FBD", 80, 80, is_starter=True),
        TeamRosterUnit(106, "F", "F2", "EFS", 80, 80, is_starter=True),
        TeamRosterUnit(107, "F", "F3", "MTA", 80, 80, is_sixth_man=True),
        TeamRosterUnit(108, "F", "F4", "ZAL", 80, 80, is_bench=True),
        TeamRosterUnit(109, "C", "C1", "ASV", 80, 80, is_starter=True),
        TeamRosterUnit(110, "C", "C2", "BER", 80, 80, is_bench=True),
        TeamRosterUnit(1001, "HC", "HC1", "PAO", 80, 80, is_coach=True),
    ]

    team = service.create_team(
        team_id="pit_team",
        name="PIT Test Team",
        season="2024/25",
        round_number=1,
        bank_tenths=120,
        squad=squad_units,
    )

    # Reconstruct Round 1 point-in-time state
    pit_r1 = service.reconstruct_point_in_time_state("pit_team", round_number=1, season="2024/25")
    assert isinstance(pit_r1, PointInTimeTeamState)
    assert pit_r1.round_number == 1
    assert pit_r1.bank_tenths == 120
    assert pit_r1.transfers_remaining == 4
    assert len(pit_r1.squad) == 11
    assert pit_r1.squad_valuation_tenths > 0
    assert pit_r1.total_team_value_tenths == pit_r1.squad_valuation_tenths + 120
    assert len(pit_r1.player_availabilities) == 11

    # Execute a trade in Round 1
    service.execute_transfers(
        team_id="pit_team",
        transfers_out_ids=[104],
        transfers_in_ids=[111],
        round_number=1,
        season="2024/25",
    )

    pit_r1_after = service.reconstruct_point_in_time_state("pit_team", round_number=1, season="2024/25")
    assert pit_r1_after.transfers_remaining == 3
    assert 111 in {u.player_id for u in pit_r1_after.squad}
    assert 104 not in {u.player_id for u in pit_r1_after.squad}


def test_past_round_trade_forward_replay_and_cap_enforcement(test_db: Path) -> None:
    """§3.2: Past-round trade execution, forward replay into live round, and transfer cap enforcement."""
    team_store = TeamStore(db_path=test_db)
    service = TeamService(store=team_store)

    squad_units = [
        TeamRosterUnit(101, "G", "G1", "PAO", 80, 80, is_starter=True, is_captain=True),
        TeamRosterUnit(102, "G", "G2", "OLY", 80, 80, is_starter=True),
        TeamRosterUnit(103, "G", "G3", "RMB", 80, 80, is_bench=True),
        TeamRosterUnit(104, "G", "G4", "BAR", 80, 80, is_bench=True),
        TeamRosterUnit(105, "F", "F1", "FBD", 80, 80, is_starter=True),
        TeamRosterUnit(106, "F", "F2", "EFS", 80, 80, is_starter=True),
        TeamRosterUnit(107, "F", "F3", "MTA", 80, 80, is_sixth_man=True),
        TeamRosterUnit(108, "F", "F4", "ZAL", 80, 80, is_bench=True),
        TeamRosterUnit(109, "C", "C1", "ASV", 80, 80, is_starter=True),
        TeamRosterUnit(110, "C", "C2", "BER", 80, 80, is_bench=True),
        TeamRosterUnit(1001, "HC", "HC1", "PAO", 80, 80, is_coach=True),
    ]

    # Create team at live round 2
    service.create_team(
        team_id="replay_team",
        name="Replay Test Team",
        season="2024/25",
        round_number=1,
        bank_tenths=100,
        squad=squad_units,
    )
    # Advance to round 2
    service.set_squad("replay_team", 2, squad_units, validate=False, advance_team_round=True)
    live_team = service.get_team("replay_team")
    assert live_team.round_number == 2

    # Execute trade in past Round 1 (sell 104, buy 111)
    res = service.execute_transfers(
        team_id="replay_team",
        transfers_out_ids=[104],
        transfers_in_ids=[111],
        round_number=1,
        season="2024/25",
    )
    assert res["target_round"] == 1

    # Round 1 squad has 111
    r1_pids = {u.player_id for u in service.store.get_squad("replay_team", 1)}
    assert 111 in r1_pids and 104 not in r1_pids

    # Forward propagation: Round 2 squad and checkpoint updated
    r2_pids = {u.player_id for u in service.store.get_squad("replay_team", 2)}
    assert 111 in r2_pids and 104 not in r2_pids

    r2_chk = service.store.get_round_checkpoint("replay_team", 2, "2024/25")
    chk_pids = {u.player_id for u in r2_chk["squad"]}
    assert 111 in chk_pids and 104 not in chk_pids

    # Revert round start on live round 2 restores checkpoint baseline (which has 111)
    reverted = service.revert_to_round_start("replay_team", "2024/25", round_number=2)
    assert 111 in {u.player_id for u in reverted.squad}

    # Transfer cap: Round 1 had 1 trade, only 3 remain. Attempting 4 trades fails with ValueError
    with pytest.raises(ValueError, match="transfers remaining"):
        service.execute_transfers(
            team_id="replay_team",
            transfers_out_ids=[101, 102, 103, 111],
            transfers_in_ids=[104, 112, 113, 114],
            round_number=1,
            season="2024/25",
        )


def test_f3_sequential_decision_simulation(test_db: Path) -> None:
    """F3: Full multi-round sequential decision simulation across a season."""
    sim = SequentialDecisionSimulator()
    ledger = sim.simulate_season(
        season="E2024",
        database_path=test_db,
        model_name="season_mean",
        rounds=[1, 2, 3, 4],
    )

    assert isinstance(ledger, SequentialSeasonReplayLedger)
    assert ledger.season == "E2024"
    assert ledger.league == "euroleague"
    assert ledger.rounds_evaluated == 4
    assert ledger.total_realized_score > 0
    assert ledger.total_oracle_score >= ledger.total_realized_score
    assert len(ledger.round_results) == 4

    for r in ledger.round_results:
        assert len(r.lineup_starters) == 5
        assert r.lineup_captain in r.lineup_starters
        assert r.lineup_sixth_man > 0
        assert len(r.lineup_bench) == 4
        assert r.lineup_coach > 0
        assert r.realized_score > 0
        assert r.oracle_score >= r.realized_score

    # Markdown export test
    md = ledger.to_markdown()
    assert "# Sequential Decision Replay Ledger" in md
    assert "Regret Attribution Breakdown" in md

    # CSV export test
    csv_str = ledger.to_csv()
    assert "realized_score,oracle_score" in csv_str


def test_f4_model_version_comparison_ledger(test_db: Path) -> None:
    """F4: Compare decision model versions against actual human decisions and hindsight oracle."""
    sim = SequentialDecisionSimulator()

    human_mock = {
        1: {
            "starter_ids": (101, 102, 105, 106, 109),
            "captain_id": 101,
            "sixth_man_id": 107,
            "bench_ids": (103, 104, 108, 110),
            "head_coach_id": 1001,
        }
    }

    comp = sim.compare_models(
        season="E2024",
        database_path=test_db,
        model_names=["season_mean", "ewma"],
        rounds=[1, 2],
        human_decisions=human_mock,
    )

    assert isinstance(comp, ModelComparisonLedger)
    assert len(comp.rows) == 2
    assert comp.rows[0].model_name == "season_mean"
    assert comp.rows[1].model_name == "ewma"

    md = comp.to_markdown()
    assert "Multi-Model Decision Comparison Ledger" in md
    assert "`season_mean`" in md
    assert "`ewma`" in md

    csv_str = comp.to_csv()
    assert "model_name,total_score" in csv_str


def test_f5_f7_regret_attribution_tolerance(test_db: Path) -> None:
    """F5 & F7: Decompose regret into Captain, 6th Man, Bench, Turn Sub, Transfer regret with |residual| <= 1.0."""
    sim = SequentialDecisionSimulator()
    ledger = sim.simulate_season(
        season="E2024",
        database_path=test_db,
        model_name="season_mean",
        rounds=[1, 2, 3],
    )

    for r in ledger.round_results:
        rg = r.regret
        assert isinstance(rg, RegretAttribution)
        assert rg.captain_regret >= 0.0
        assert rg.sixth_man_regret >= 0.0
        assert rg.bench_regret >= 0.0
        assert rg.turn_substitution_regret >= 0.0
        assert rg.transfer_regret >= 0.0
        assert rg.formation_regret >= 0.0

        # Mathematical decomposition summation:
        comp_sum = (
            rg.captain_regret
            + rg.sixth_man_regret
            + rg.bench_regret
            + rg.turn_substitution_regret
            + rg.transfer_regret
            + rg.formation_regret
            + rg.residual
        )
        assert comp_sum == pytest.approx(rg.total_regret, abs=0.05)

        # Regret attribution tolerance requirement (|residual| <= 1.0 FP):
        assert abs(rg.residual) <= 1.0

    # Season-level regret attribution
    s_rg = ledger.regret_attribution
    s_sum = (
        s_rg.captain_regret
        + s_rg.sixth_man_regret
        + s_rg.bench_regret
        + s_rg.turn_substitution_regret
        + s_rg.transfer_regret
        + s_rg.formation_regret
        + s_rg.residual
    )
    assert s_sum == pytest.approx(ledger.avg_regret, abs=0.05)
    assert abs(s_rg.residual) <= 1.0


def test_f8_zero_mutation_invariant(test_db: Path) -> None:
    """F8 Zero-Mutation Invariant: Database must remain byte-for-byte identical after simulation replay."""
    hash_before = _hash_file(test_db)

    sim = SequentialDecisionSimulator()
    ledger = sim.simulate_season(
        season="E2024",
        database_path=test_db,
        model_name="season_mean",
        rounds=[1, 2],
    )
    assert ledger.rounds_evaluated == 2

    comp = sim.compare_models(
        season="E2024",
        database_path=test_db,
        model_names=["season_mean", "ewma"],
        rounds=[1, 2],
    )
    assert len(comp.rows) == 2

    hash_after = _hash_file(test_db)
    assert hash_before == hash_after, "Replay violated zero-mutation invariant: database file was modified!"


def test_cli_round_aware_entry(test_db: Path) -> None:
    """§3.3: CLI round-aware entry commands (elf team set-lineup --round N, elf team trade --round N)."""
    # 1. Create team via CLI
    code = cli_main([
        "--db", str(test_db),
        "team", "create",
        "--id", "cli_team",
        "--name", "CLI Team",
        "--season", "2024/25",
        "--bank", "100",
    ])
    assert code == 0

    # 2. Seed round 1 squad via service
    service = TeamService(db_path=test_db)
    squad_units = [
        TeamRosterUnit(101, "G", "G1", "PAO", 80, 80, is_starter=True, is_captain=True),
        TeamRosterUnit(102, "G", "G2", "OLY", 80, 80, is_starter=True),
        TeamRosterUnit(103, "G", "G3", "RMB", 80, 80, is_bench=True),
        TeamRosterUnit(104, "G", "G4", "BAR", 80, 80, is_bench=True),
        TeamRosterUnit(105, "F", "F1", "FBD", 80, 80, is_starter=True),
        TeamRosterUnit(106, "F", "F2", "EFS", 80, 80, is_starter=True),
        TeamRosterUnit(107, "F", "F3", "MTA", 80, 80, is_sixth_man=True),
        TeamRosterUnit(108, "F", "F4", "ZAL", 80, 80, is_bench=True),
        TeamRosterUnit(109, "C", "C1", "ASV", 80, 80, is_starter=True),
        TeamRosterUnit(110, "C", "C2", "BER", 80, 80, is_bench=True),
        TeamRosterUnit(1001, "HC", "HC1", "PAO", 80, 80, is_coach=True),
    ]
    service.set_squad("cli_team", 1, squad_units, validate=False, advance_team_round=True)

    # 3. Test elf team set-lineup with --round 1
    code = cli_main([
        "--db", str(test_db),
        "team", "set-lineup",
        "--team", "cli_team",
        "--round", "1",
        "--starters", "101,102,105,106,109",
        "--captain", "102",
        "--sixth-man", "107",
        "--bench", "103,104,108,110",
        "--coach", "1001",
    ])
    assert code == 0

    team_r1 = service.store.get_squad("cli_team", 1)
    cap = next(u for u in team_r1 if u.player_id == 102)
    assert cap.is_captain is True

    # 4. Test elf team trade with --round 1
    code = cli_main([
        "--db", str(test_db),
        "team", "trade",
        "--team", "cli_team",
        "--round", "1",
        "--out", "104",
        "--in", "111",
        "--season", "2024/25",
    ])
    assert code == 0

    team_r1_post = service.store.get_squad("cli_team", 1)
    pids = {u.player_id for u in team_r1_post}
    assert 111 in pids
    assert 104 not in pids
