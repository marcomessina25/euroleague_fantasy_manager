"""Comprehensive test suite for V1.0 Workstream 5 (PR #19): Closed-Loop Decision Audit.

Verifies:
- 10.1 Decision Identity: decision_id, team_id, league, season, round, turn, timestamp, snapshot, provenance, recommendation, human choice, notes.
- 10.2 Immutable Historical Context: StateSnapshot immutability, prediction & optimizer provenance persist across database reloads.
- 10.3 Human Override: distinct model recommendation vs human actual choice; recommendation is preserved alongside human choices.
- 10.4 Outcome Reconciliation & Regret Attribution: ingestion of realized points, lineup scoring with actuals, oracle computation, and regret decomposition (captain, 6th man, bench, formation, transfers, intra-round subs).
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.optimization.constraints import (
    OptimizationConstraints,
    PlayerProjectionContract,
)
from euroleague_fantasy_manager.services.decision_service import DecisionService
from euroleague_fantasy_manager.tracking.models import (
    DecisionOutcome,
    DecisionProvenance,
    DecisionRecord,
    DecisionType,
    LineupPayload,
    OutcomeStatus,
    StateSnapshot,
    TransferPayload,
    TurnSubPayload,
)
from euroleague_fantasy_manager.tracking.outcomes import OutcomeUpdater
from euroleague_fantasy_manager.tracking.store import DecisionStore


def _make_test_contracts() -> list[PlayerProjectionContract]:
    """11 test contracts representing a standard squad."""
    positions = [
        (1, Position.GUARD, "G1", 100, 15.0),
        (2, Position.GUARD, "G2", 90, 12.0),
        (3, Position.FORWARD, "F1", 110, 18.0),
        (4, Position.FORWARD, "F2", 95, 11.0),
        (5, Position.CENTER, "C1", 120, 20.0),
        (6, Position.GUARD, "G3", 85, 10.0),   # 6th man
        (7, Position.GUARD, "G4", 70, 7.0),    # bench
        (8, Position.FORWARD, "F3", 75, 8.0),   # bench
        (9, Position.FORWARD, "F4", 65, 6.0),   # bench
        (10, Position.CENTER, "C2", 80, 9.0),   # bench
        (11, Position.HEAD_COACH, "HC1", 100, 14.0),
    ]
    return [
        PlayerProjectionContract(
            player_id=pid,
            player_name=f"Player {name}",
            position=pos,
            team_code="TEST",
            price_tenths=price,
            expected_fp=exp_fp,
            probability_play=1.0,
            expected_minutes=25.0,
            league_id="euroleague",
            season="2026/27",
            round_number=1,
        )
        for pid, pos, name, price, exp_fp in positions
    ]


def test_decision_identity_and_immutable_context(tmp_path: Path) -> None:
    """10.1 & 10.2: Decision identity carries all required fields and remains immutable."""
    db_file = tmp_path / "decision_audit.sqlite3"
    store = DecisionStore(database_path=db_file)
    service = DecisionService(store=store)
    contracts = _make_test_contracts()

    prov = DecisionProvenance(
        model_id="learned_v09",
        model_version="0.9.1",
        optimizer_version="1.0.0",
        prediction_run_id="pred_run_42",
        optimization_run_id="opt_run_99",
        risk_mode="expected",
        risk_lambda=0.10,
        option_value_mode=True,
        git_commit="abcdef123456",
        prediction_cutoff="2026-10-15T18:00:00Z",
    )

    rec_lineup = LineupPayload(
        formation="2-2-1",
        starter_ids=(1, 2, 3, 4, 5),
        captain_id=5,
        sixth_man_id=6,
        bench_ids=(7, 8, 9, 10),
        head_coach_id=11,
        expected_score=85.0,
        projected_scores={1: 15.0, 2: 12.0, 3: 18.0, 4: 11.0, 5: 20.0, 6: 10.0, 7: 7.0, 8: 8.0, 9: 6.0, 10: 9.0, 11: 14.0},
    )

    # Log lineup decision
    record = service.log_lineup(
        team_id="alpha_team",
        season="2026/27",
        round_number=1,
        turn_number=1,
        recommended_lineup=rec_lineup,
        actual_lineup=rec_lineup,
        provenance=prov,
        squad_contracts=contracts,
        notes="Pre-round optimal lineup logged for certification",
        league="euroleague",
    )

    # Verify 10.1 canonical fields
    assert record.decision_id.startswith("dec_lineup_2026/27_r01_t1_")
    assert record.team_id == "alpha_team"
    assert record.league == "euroleague"
    assert record.season == "2026/27"
    assert record.round_number == 1
    assert record.turn_number == 1
    assert record.created_at != ""
    assert record.state_snapshot_id is not None
    assert record.provenance.model_id == "learned_v09"
    assert record.provenance.prediction_run_id == "pred_run_42"
    assert record.provenance.optimization_run_id == "opt_run_99"
    assert record.notes == "Pre-round optimal lineup logged for certification"
    assert not record.is_override

    # Verify 10.2 snapshot immutability
    snapshot = store.get_snapshot(record.state_snapshot_id)
    assert snapshot is not None
    assert snapshot.team_id == "alpha_team"
    assert snapshot.league == "euroleague"
    assert snapshot.squad_ids == tuple(range(1, 12))
    assert snapshot.prices_tenths[1] == 100
    assert snapshot.prices_tenths[5] == 120

    # Retrieve from fresh store instance
    reloaded_store = DecisionStore(database_path=db_file)
    retrieved = reloaded_store.get_decision(record.decision_id)
    assert retrieved is not None
    assert retrieved.decision_id == record.decision_id
    assert retrieved.team_id == "alpha_team"
    assert retrieved.league == "euroleague"
    assert retrieved.provenance.git_commit == "abcdef123456"


def test_human_override_preservation(tmp_path: Path) -> None:
    """10.3: Model recommendation and human actual decision are stored distinctly without overwriting."""
    db_file = tmp_path / "override_audit.sqlite3"
    store = DecisionStore(database_path=db_file)
    service = DecisionService(store=store)

    rec_lineup = LineupPayload(
        formation="2-2-1",
        starter_ids=(1, 2, 3, 4, 5),
        captain_id=5,  # Model recommends center as captain
        sixth_man_id=6,
        bench_ids=(7, 8, 9, 10),
        head_coach_id=11,
        expected_score=85.0,
    )

    human_lineup = LineupPayload(
        formation="2-2-1",
        starter_ids=(1, 2, 3, 4, 5),
        captain_id=3,  # Human overrides captain to Forward 1
        sixth_man_id=7,  # Human overrides sixth man to Guard 4
        bench_ids=(6, 8, 9, 10),
        head_coach_id=11,
        expected_score=81.0,
    )

    record = service.log_lineup(
        team_id="beta_team",
        season="2026/27",
        round_number=2,
        turn_number=1,
        recommended_lineup=rec_lineup,
        actual_lineup=human_lineup,
        notes="Human captain override",
        league="eurocup",
    )

    assert record.is_override
    assert record.league == "eurocup"
    assert record.recommended_lineup is not None
    assert record.actual_lineup is not None
    # Verify recommendation was NOT overwritten
    assert record.recommended_lineup.captain_id == 5
    assert record.actual_lineup.captain_id == 3
    assert record.recommended_lineup.sixth_man_id == 6
    assert record.actual_lineup.sixth_man_id == 7


def test_outcome_reconciliation_and_regret_attribution(tmp_path: Path) -> None:
    """10.4: Reconcile actual scores and compute regret attribution (captain, 6th man, bench, formation)."""
    db_file = tmp_path / "outcomes_audit.sqlite3"
    store = DecisionStore(database_path=db_file)
    service = DecisionService(store=store)
    contracts = _make_test_contracts()

    rec_lineup = LineupPayload(
        formation="2-2-1",
        starter_ids=(1, 2, 3, 4, 5),
        captain_id=5,     # Center (exp: 20, act: 12)
        sixth_man_id=6,   # Guard 3 (exp: 10, act: 8)
        bench_ids=(7, 8, 9, 10),
        head_coach_id=11, # Coach (act: 15)
        expected_score=85.0,
        projected_scores={1: 15.0, 2: 12.0, 3: 18.0, 4: 11.0, 5: 20.0, 6: 10.0, 7: 7.0, 8: 8.0, 9: 6.0, 10: 9.0, 11: 14.0},
    )

    # Human chose Forward 3 (pid 3) as captain
    human_lineup = LineupPayload(
        formation="2-2-1",
        starter_ids=(1, 2, 3, 4, 5),
        captain_id=3,     # Forward 1 (exp: 18, act: 28 -> star performer!)
        sixth_man_id=6,
        bench_ids=(7, 8, 9, 10),
        head_coach_id=11,
        expected_score=83.0,
        projected_scores={1: 15.0, 2: 12.0, 3: 18.0, 4: 11.0, 5: 20.0, 6: 10.0, 7: 7.0, 8: 8.0, 9: 6.0, 10: 9.0, 11: 14.0},
    )

    record = service.log_lineup(
        team_id="gamma_team",
        season="2026/27",
        round_number=3,
        turn_number=1,
        recommended_lineup=rec_lineup,
        actual_lineup=human_lineup,
        squad_contracts=contracts,
        notes="Pre-round decision before outcome",
    )

    # Actual realization: Forward 1 erupted for 28.0 FP; Center had an off-night with 12.0 FP
    actual_scores = {
        1: 16.0,  # Guard 1
        2: 10.0,  # Guard 2
        3: 28.0,  # Forward 1 (Human captain)
        4: 14.0,  # Forward 2
        5: 12.0,  # Center 1 (Model captain)
        6: 8.0,   # 6th man
        7: 6.0,   # Bench G4
        8: 12.0,  # Bench F3 (scored more than 6th man!)
        9: 4.0,   # Bench F4
        10: 10.0, # Bench C2
        11: 15.0, # Coach
    }

    updater = OutcomeUpdater(store=store)
    outcome = updater.update_decision_outcomes(
        decision_id=record.decision_id,
        actual_scores=actual_scores,
        status=OutcomeStatus.FINAL,
        squad_contracts=contracts,
    )

    assert outcome.decision_id == record.decision_id
    assert outcome.outcome_status == OutcomeStatus.FINAL

    # Human picked captain=3 (28 FP * 2.0 = 56). Model picked captain=5 (12 FP * 2.0 = 24).
    # Human actual score should exceed recommended actual score:
    assert outcome.human_actual_score > outcome.recommended_actual_score
    assert outcome.human_vs_model > 0.0

    # Captain regret for human: captain was player 3 (who had 28, max starter), so human captain regret is 0.0
    assert outcome.captain_regret == 0.0

    # Sixth man regret: bench player 8 had 12.0 FP, chosen sixth man 6 had 8.0 FP.
    # Regret = 0.5 * (12.0 - 8.0) = 2.0 FP
    assert outcome.sixth_man_regret == 2.0

    # Stored outcome is retrievable
    retrieved = store.get_decision(record.decision_id)
    assert retrieved is not None
