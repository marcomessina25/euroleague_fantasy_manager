"""Comprehensive test suite for V0.45 Closed-Loop Evaluation & Live Decision State."""

import json
from pathlib import Path
import pytest

from euroleague_fantasy_manager.cli import main
from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
from euroleague_fantasy_manager.optimization.lineup import FixedSquadLineupOptimizer
from euroleague_fantasy_manager.tracking import (
    ClosedLoopEvaluator,
    DecisionEvent,
    DecisionLogger,
    DecisionOutcome,
    DecisionProvenance,
    DecisionRecord,
    DecisionStore,
    DecisionType,
    LineupPayload,
    OutcomeStatus,
    OutcomeUpdater,
    StateSnapshot,
    TransferPayload,
    TurnSubPayload,
    export_closed_loop_csv,
    format_decision_detail,
    format_decisions_table,
)


def make_test_player(
    pid: int,
    pos: Position,
    expected_fp: float,
    price_tenths: int = 100,
    turn: int = 1,
    team_id: int = 1,
) -> PlayerProjectionContract:
    return PlayerProjectionContract(
        player_id=pid,
        player_name=f"Player_{pid}",
        position=pos,
        team_id=team_id,
        team_code=f"TM{team_id}",
        price_tenths=price_tenths,
        expected_fp=expected_fp,
        probability_play=1.0,
        expected_minutes=25.0 if pos != Position.HEAD_COACH else 40.0,
        fp_per_minute=round(expected_fp / 25.0, 3) if pos != Position.HEAD_COACH else 0.0,
        uncertainty=3.0,
        turn_number=turn,
    )


def make_standard_squad() -> list[PlayerProjectionContract]:
    """11-unit squad: 4G, 4F, 2C, 1HC."""
    return [
        make_test_player(101, Position.GUARD, expected_fp=22.0, turn=1, team_id=1),
        make_test_player(102, Position.GUARD, expected_fp=18.0, turn=1, team_id=2),
        make_test_player(103, Position.GUARD, expected_fp=14.0, turn=2, team_id=3),
        make_test_player(104, Position.GUARD, expected_fp=10.0, turn=2, team_id=4),
        make_test_player(201, Position.FORWARD, expected_fp=24.0, turn=1, team_id=1),
        make_test_player(202, Position.FORWARD, expected_fp=19.0, turn=1, team_id=2),
        make_test_player(203, Position.FORWARD, expected_fp=13.0, turn=2, team_id=3),
        make_test_player(204, Position.FORWARD, expected_fp=9.0, turn=2, team_id=4),
        make_test_player(301, Position.CENTER, expected_fp=21.0, turn=1, team_id=1),
        make_test_player(302, Position.CENTER, expected_fp=16.0, turn=2, team_id=2),
        make_test_player(401, Position.HEAD_COACH, expected_fp=15.0, turn=1, team_id=5),
    ]


# ---------------------------------------------------------------------------
# Phase 1: Models & Serialization
# ---------------------------------------------------------------------------


def test_models_serialization_roundtrip():
    payload = LineupPayload(
        formation="2-2-1",
        starter_ids=(101, 102, 201, 202, 301),
        captain_id=201,
        vice_captain_id=101,
        sixth_man_id=302,
        bench_ids=(103, 104, 203, 204),
        head_coach_id=401,
        expected_score=118.5,
        projected_scores={101: 22.0, 201: 24.0},
    )
    d = payload.to_dict()
    reconstructed = LineupPayload.from_dict(d)
    assert reconstructed.formation == "2-2-1"
    assert reconstructed.starter_ids == (101, 102, 201, 202, 301)
    assert reconstructed.captain_id == 201
    assert reconstructed.vice_captain_id == 101
    assert reconstructed.sixth_man_id == 302
    assert reconstructed.projected_scores[101] == 22.0

    tx_payload = TransferPayload(
        out_player_ids=(104,),
        in_player_ids=(999,),
        num_trades=1,
        net_transfer_value=6.5,
        bank_tenths_before=50,
        bank_tenths_after=10,
    )
    reconstructed_tx = TransferPayload.from_dict(tx_payload.to_dict())
    assert reconstructed_tx.num_trades == 1
    assert reconstructed_tx.out_player_ids == (104,)
    assert reconstructed_tx.in_player_ids == (999,)

    prov = DecisionProvenance(
        model_id="fp_decomposed_v03",
        model_version="0.3.0",
        optimizer_version="0.4.5",
        risk_mode="conservative",
        risk_lambda=0.20,
    )
    reconstructed_prov = DecisionProvenance.from_dict(prov.to_dict())
    assert reconstructed_prov.risk_mode == "conservative"
    assert reconstructed_prov.risk_lambda == 0.20


# ---------------------------------------------------------------------------
# Phase 2: DecisionStore & Team Isolation
# ---------------------------------------------------------------------------


def test_decision_store_crud_and_team_isolation(tmp_path: Path):
    db_file = tmp_path / "test_decisions.db"
    store = DecisionStore(db_file)

    # 1. State Snapshot
    snap = StateSnapshot(
        snapshot_id="snap_001",
        team_id="team_alpha",
        season="2026",
        round_number=1,
        turn_number=1,
        squad_ids=(101, 102, 201, 202, 301),
        prices_tenths={101: 120, 102: 110},
        bank_tenths=50,
    )
    store.save_snapshot(snap)
    loaded_snap = store.get_snapshot("snap_001")
    assert loaded_snap is not None
    assert loaded_snap.team_id == "team_alpha"
    assert loaded_snap.bank_tenths == 50

    # 2. Decision Record for Team Alpha
    rec_alpha = DecisionRecord(
        decision_id="dec_alpha_r01",
        team_id="team_alpha",
        season="2026",
        round_number=1,
        turn_number=1,
        decision_type=DecisionType.LINEUP,
        created_at="2026-09-23T12:00:00Z",
        provenance=DecisionProvenance(),
        state_snapshot_id="snap_001",
        notes="Captain Vezenkov",
    )
    store.log_decision(rec_alpha)

    # 3. Decision Record for Team Beta
    rec_beta = DecisionRecord(
        decision_id="dec_beta_r01",
        team_id="team_beta",
        season="2026",
        round_number=1,
        turn_number=1,
        decision_type=DecisionType.LINEUP,
        created_at="2026-09-23T12:00:00Z",
        provenance=DecisionProvenance(),
        state_snapshot_id="snap_001",
        notes="Captain James",
    )
    store.log_decision(rec_beta)

    # Verify team isolation
    alpha_decs = store.list_decisions(team_id="team_alpha")
    beta_decs = store.list_decisions(team_id="team_beta")
    assert len(alpha_decs) == 1
    assert alpha_decs[0].decision_id == "dec_alpha_r01"
    assert len(beta_decs) == 1
    assert beta_decs[0].decision_id == "dec_beta_r01"

    # Audit Events logged
    events = store.list_events("dec_alpha_r01")
    assert len(events) >= 1
    assert events[0].event_type == "DECISION_LOGGED"


# ---------------------------------------------------------------------------
# Phase 3: DecisionLogger & Override Tracking
# ---------------------------------------------------------------------------


def test_decision_logger_recommendation_and_human_override(tmp_path: Path):
    db_file = tmp_path / "test_logger.db"
    store = DecisionStore(db_file)
    logger = DecisionLogger(store=store)

    squad = make_standard_squad()
    opt = FixedSquadLineupOptimizer()
    model_rec = opt.optimize(squad, round_number=1)

    # Case A: Human accepts model recommendation
    rec_record = logger.log_lineup_decision(
        round_number=1,
        season="2026",
        team_id="team_1",
        turn_number=1,
        recommended_decision=model_rec,
        squad_contracts=squad,
        notes="Accepted model recommendation",
    )
    assert not rec_record.is_override
    assert rec_record.actual_lineup.captain_id == model_rec.captain_id
    assert rec_record.actual_lineup.formation == model_rec.formation

    # Case B: Human overrides model captain (Model chose 201, Human chooses 101)
    override_record = logger.log_lineup_decision(
        round_number=2,
        season="2026",
        team_id="team_1",
        turn_number=1,
        recommended_decision=model_rec,
        actual_formation=model_rec.formation,
        actual_starters=model_rec.starter_ids,
        actual_captain=101,  # Human override!
        actual_sixth_man=model_rec.sixth_man_id,
        actual_bench=model_rec.bench_ids,
        actual_coach=model_rec.head_coach_id,
        squad_contracts=squad,
        notes="Prefer Guard captain in R2",
    )
    assert override_record.is_override
    assert override_record.recommended_lineup.captain_id == model_rec.captain_id
    assert override_record.actual_lineup.captain_id == 101


# ---------------------------------------------------------------------------
# Phase 4: Outcome Ingestion & Retrospective Regrets
# ---------------------------------------------------------------------------


def test_outcome_updater_regret_and_prediction_errors(tmp_path: Path):
    db_file = tmp_path / "test_outcomes.db"
    store = DecisionStore(db_file)
    logger = DecisionLogger(store=store)
    updater = OutcomeUpdater(store=store)

    squad = make_standard_squad()
    opt = FixedSquadLineupOptimizer()
    model_rec = opt.optimize(squad, round_number=5)

    # Human overrode captain to 101 (projected 22.0) while model recommended 201 (projected 24.0)
    record = logger.log_lineup_decision(
        round_number=5,
        season="2026",
        team_id="team_1",
        turn_number=1,
        recommended_decision=model_rec,
        actual_formation=model_rec.formation,
        actual_starters=model_rec.starter_ids,
        actual_captain=101,
        actual_sixth_man=model_rec.sixth_man_id,
        actual_bench=model_rec.bench_ids,
        actual_coach=model_rec.head_coach_id,
        squad_contracts=squad,
    )

    # Actual realization:
    # Player 101 chokes (scored 8.0)
    # Player 201 performs well (scored 26.0)
    # Player 202 explodes (scored 32.0)
    actuals = {
        101: 8.0,
        102: 15.0,
        103: 12.0,
        104: 6.0,
        201: 26.0,
        202: 32.0,
        203: 10.0,
        204: 4.0,
        301: 20.0,
        302: 18.0,
        401: 15.0,
    }

    outcome = updater.update_decision_outcomes(record.decision_id, actuals)

    assert outcome.outcome_status == OutcomeStatus.FINAL
    # Model recommended 201 as captain (26.0), Human picked 101 (8.0)
    # Model score must be higher than Human score by (26.0 - 8.0) = 18.0 FP
    assert outcome.recommended_actual_score - outcome.human_actual_score == pytest.approx(18.0, abs=1e-2)
    assert outcome.human_vs_model == pytest.approx(-18.0, abs=1e-2)

    # Best starter was 202 (32.0). Chosen captain was 101 (8.0) -> Captain Regret = 32.0 - 8.0 = 24.0
    assert outcome.captain_regret == pytest.approx(24.0, abs=1e-2)

    # Oracle score >= Recommended score >= Human score
    assert outcome.oracle_actual_score >= outcome.recommended_actual_score
    assert outcome.human_regret >= outcome.model_regret

    # Prediction error computed on squad
    assert outcome.prediction_mae > 0.0
    assert outcome.prediction_rmse >= outcome.prediction_mae


# ---------------------------------------------------------------------------
# Phase 5: Turn 1 -> Turn 2 Decision & Transfer Evaluation
# ---------------------------------------------------------------------------


def test_turn_sub_and_transfer_decisions(tmp_path: Path):
    db_file = tmp_path / "test_turns.db"
    store = DecisionStore(db_file)
    logger = DecisionLogger(store=store)
    updater = OutcomeUpdater(store=store)

    # 1. Turn Substitution Decision
    t1_scores = {101: 8.0, 201: 10.0}
    turn_rec = logger.log_turn_substitution(
        round_number=3,
        t1_actuals=t1_scores,
        season="2026",
        team_id="team_1",
        substituted_out_id=101,  # Sub out underperforming Guard 101 (8.0)
        substituted_in_id=103,   # Sub in unplayed Turn 2 Guard 103
        old_captain_id=201,      # Captain switch from 201 to 302
        new_captain_id=302,
        resulting_lineup=LineupPayload(
            formation="2-2-1",
            starter_ids=(103, 102, 201, 202, 301),
            captain_id=302,
            sixth_man_id=101,
            bench_ids=(104, 203, 204),
            head_coach_id=401,
        ),
    )
    assert turn_rec.decision_type == DecisionType.TURN_SUB

    # Realized scores for Turn 2:
    actuals = {
        101: 8.0,
        102: 15.0,
        103: 20.0,  # Turn 2 sub-in was brilliant! 20.0 FP
        104: 5.0,
        201: 10.0,
        202: 18.0,
        203: 10.0,
        204: 6.0,
        301: 16.0,
        302: 24.0,  # Captain switch to 302 was brilliant! (24.0 vs 10.0)
        401: 10.0,
    }

    out_turn = updater.update_decision_outcomes(turn_rec.decision_id, actuals)
    assert out_turn.turn_sub_regret is not None
    assert out_turn.turn_sub_regret > 0.0, "Substitution and captain switch delivered positive net gains"

    # 2. Transfer Decision
    tx_rec = logger.log_transfer_decision(
        round_number=4,
        season="2026",
        team_id="team_1",
        actual_out_ids=[104],  # Sold weak player 104
        actual_in_ids=[999],   # Bought superstar 999
        bank_tenths_before=100,
        bank_tenths_after=20,
    )
    assert tx_rec.decision_type == DecisionType.TRANSFERS
    assert tx_rec.actual_transfers.num_trades == 1

    actuals_r4 = dict(actuals)
    actuals_r4[104] = 4.0
    actuals_r4[999] = 28.0  # Transferred-in player scored 28.0 vs 4.0

    # Attach dummy actual lineup for transfer outcome scoring
    store.log_decision(
        DecisionRecord(
            decision_id=tx_rec.decision_id,
            team_id=tx_rec.team_id,
            season=tx_rec.season,
            round_number=tx_rec.round_number,
            turn_number=1,
            decision_type=DecisionType.TRANSFERS,
            created_at=tx_rec.created_at,
            provenance=tx_rec.provenance,
            actual_lineup=turn_rec.actual_lineup,
            actual_transfers=tx_rec.actual_transfers,
        )
    )

    out_tx = updater.update_decision_outcomes(tx_rec.decision_id, actuals_r4)
    assert out_tx.transfer_regret == 24.0  # 28.0 - 4.0 = +24.0 net transfer gain


# ---------------------------------------------------------------------------
# Phase 6: Longitudinal ClosedLoopEvaluator & Drift Monitoring
# ---------------------------------------------------------------------------


def test_closed_loop_evaluator_longitudinal_summary(tmp_path: Path):
    db_file = tmp_path / "test_evaluator.db"
    store = DecisionStore(db_file)
    logger = DecisionLogger(store=store)
    updater = OutcomeUpdater(store=store)

    squad = make_standard_squad()
    opt = FixedSquadLineupOptimizer()

    # Simulate 3 rounds of decisions and outcomes
    for r in range(1, 4):
        rec = opt.optimize(squad, round_number=r)
        dec = logger.log_lineup_decision(
            round_number=r,
            season="2026",
            team_id="my_team",
            recommended_decision=rec,
            actual_formation=rec.formation,
            actual_starters=rec.starter_ids,
            actual_captain=rec.captain_id if r != 2 else 101,  # Override on round 2
            actual_sixth_man=rec.sixth_man_id,
            actual_bench=rec.bench_ids,
            actual_coach=rec.head_coach_id,
            squad_contracts=squad,
        )
        actuals = {p.player_id: p.expected_fp + (r * 2.0) for p in squad}
        updater.update_decision_outcomes(dec.decision_id, actuals)

    evaluator = ClosedLoopEvaluator(store=store)
    summary = evaluator.evaluate_decisions(team_id="my_team", season="2026", rolling_window=2)

    assert summary.decisions_count == 3
    assert summary.outcomes_evaluated == 3
    assert summary.avg_human_score > 0.0
    assert summary.avg_oracle_score >= summary.avg_human_score
    assert summary.overall_prediction_mae > 0.0
    assert "last_3_rounds" in summary.rolling_mae_windows
    assert "G" in summary.segment_mae

    md_report = summary.to_markdown()
    assert "# V0.45 Closed-Loop Decision & Regret Report" in md_report
    assert "Avg Human Realized Score:" in md_report

    csv_path = tmp_path / "summary.csv"
    export_closed_loop_csv(summary, csv_path)
    assert csv_path.exists()
    content = csv_path.read_text(encoding="utf-8")
    assert "round_number,turn_number,decision_id" in content


# ---------------------------------------------------------------------------
# Phase 7: CLI End-to-End Workflow Tests
# ---------------------------------------------------------------------------


def test_cli_closed_loop_workflow(tmp_path: Path, capsys):
    db_file = tmp_path / "cli_closed_loop.db"

    # Step 1: Log decision using CLI
    rc_log = main([
        "--db", str(db_file),
        "log-decision",
        "--season", "2025",
        "--round", "1",
        "--team", "team_champions",
        "--recommend",
    ])
    assert rc_log == 0
    captured_log = capsys.readouterr().out
    assert "Logged decision:" in captured_log
    assert "team_champions" in captured_log

    # Step 2: Inspect decision using CLI
    rc_dec = main([
        "--db", str(db_file),
        "decisions",
        "--team", "team_champions",
    ])
    assert rc_dec == 0
    captured_dec = capsys.readouterr().out
    assert "LOGGED FANTASY DECISIONS" in captured_dec

    # Step 3: Update scores using CLI with synthetic actuals
    synth_actuals = json.dumps({101: 25.0, 102: 18.0, 201: 30.0, 202: 20.0, 301: 22.0, 401: 15.0})
    rc_up = main([
        "--db", str(db_file),
        "update-scores",
        "--season", "2025",
        "--round", "1",
        "--team", "team_champions",
        "--actuals", synth_actuals,
    ])
    assert rc_up == 0
    captured_up = capsys.readouterr().out
    assert "Updated outcomes for dec_" in captured_up

    # Step 4: Evaluate decisions using CLI
    csv_file = tmp_path / "report.csv"
    rc_eval = main([
        "--db", str(db_file),
        "evaluate-decisions",
        "--team", "team_champions",
        "--csv", str(csv_file),
    ])
    assert rc_eval == 0
    captured_eval = capsys.readouterr().out
    assert "V0.45 Closed-Loop Decision & Regret Report" in captured_eval
    assert csv_file.exists()


# ---------------------------------------------------------------------------
# Phase 8: INITIAL_TEAM Decision Extension (for V0.5 Initial Team Builder)
# ---------------------------------------------------------------------------


def test_initial_team_decision_persistence(tmp_path: Path):
    """Verify generic INITIAL_TEAM decision type serialization, persistence, override detection,
    and round-trip retrieval for future V0.5 consumption.
    """
    db_file = tmp_path / "test_initial_team.db"
    store = DecisionStore(db_file)
    logger = DecisionLogger(store=store)

    rec_squad = (101, 102, 103, 104, 201, 202, 203, 204, 301, 302, 401)
    act_squad = (101, 102, 103, 104, 201, 202, 203, 204, 301, 303, 401)  # Replaced 302 with 303
    prices = {
        101: 150, 102: 120, 103: 110, 104: 90,
        201: 160, 202: 140, 203: 100, 204: 80,
        301: 170, 302: 110, 303: 115, 401: 100,
    }
    prov = DecisionProvenance(
        model_id="initial_team_builder_v05",
        model_version="0.5.0-alpha",
        optimizer_version="0.5.0-dev",
        risk_mode="balanced",
        risk_lambda=0.10,
    )

    # 1. Log with human override on squad composition
    record = logger.log_initial_team_decision(
        season="2026",
        team_id="team_draft",
        recommended_squad_ids=rec_squad,
        actual_squad_ids=act_squad,
        prices_tenths=prices,
        bank_tenths=25,
        provenance=prov,
        notes="Replaced center 302 with 303 for upside",
    )

    assert record.decision_type == DecisionType.INITIAL_TEAM
    assert record.decision_type.value == "initial_team"
    assert record.is_override is True
    assert record.recommended_squad_ids == rec_squad
    assert record.actual_squad_ids == act_squad
    assert record.round_number == 1
    assert record.turn_number == 1
    assert record.state_snapshot_id is not None

    # 2. Check snapshot persistence
    snapshot = store.get_snapshot(record.state_snapshot_id)
    assert snapshot is not None
    assert snapshot.team_id == "team_draft"
    assert snapshot.bank_tenths == 25
    assert set(snapshot.squad_ids) == set(act_squad)
    assert snapshot.prices_tenths[303] == 115

    # 3. Round-trip retrieval from SQLite
    retrieved = store.get_decision(record.decision_id)
    assert retrieved is not None
    assert retrieved.decision_id == record.decision_id
    assert retrieved.team_id == "team_draft"
    assert retrieved.decision_type == DecisionType.INITIAL_TEAM
    assert retrieved.is_override is True
    assert retrieved.recommended_squad_ids == rec_squad
    assert retrieved.actual_squad_ids == act_squad
    assert retrieved.provenance.model_id == "initial_team_builder_v05"
    assert retrieved.provenance.optimizer_version == "0.5.0-dev"
    assert retrieved.state_snapshot_id == record.state_snapshot_id
    assert retrieved.notes == "Replaced center 302 with 303 for upside"

    # 4. In-memory dictionary serialization round-trip
    d = retrieved.to_dict()
    assert d["decision_type"] == "initial_team"
    assert d["recommended_squad_ids"] == list(rec_squad)
    assert d["actual_squad_ids"] == list(act_squad)
    assert d["is_override"] is True
    reconstructed = DecisionRecord.from_dict(d)
    assert reconstructed == retrieved

    # 5. Case B: Manager accepts recommendation without override
    rec_accepted = logger.log_initial_team_decision(
        season="2026",
        team_id="team_auto",
        recommended_squad_ids=rec_squad,
        actual_squad_ids=None,  # Defaults to recommended
        prices_tenths=prices,
        bank_tenths=30,
        notes="Accepted optimizer squad as-is",
    )
    assert not rec_accepted.is_override
    assert rec_accepted.recommended_squad_ids == rec_squad
    assert rec_accepted.actual_squad_ids == rec_squad

    retrieved_accepted = store.get_decision(rec_accepted.decision_id)
    assert retrieved_accepted is not None
    assert not retrieved_accepted.is_override
    assert retrieved_accepted.actual_squad_ids == rec_squad

    # 6. Report formatting handles INITIAL_TEAM
    detail_str = format_decision_detail(retrieved)
    assert "INITIAL_TEAM" in detail_str
    assert "CHOSEN SQUAD (11 units)" in detail_str
    assert "RECOMMENDED SQUAD (11 units)" in detail_str


# ---------------------------------------------------------------------------
# Phase 9: Production Oracle Metadata Resolution
# ---------------------------------------------------------------------------


def test_oracle_metadata_resolution_from_snapshot(tmp_path: Path):
    """Verify that OutcomeUpdater obtains true positions and club metadata from StateSnapshot
    instead of hard-coded ID ranges or fabricated defaults.
    """
    db_file = tmp_path / "test_snapshot_meta.db"
    store = DecisionStore(db_file)
    logger = DecisionLogger(store=store)
    updater = OutcomeUpdater(store=store)

    # Real-world-like IDs that do NOT match any synthetic test conventions (e.g. 5011..5021)
    squad = [
        make_test_player(5011, Position.GUARD, expected_fp=20.0, team_id=1),      # G
        make_test_player(5012, Position.GUARD, expected_fp=15.0, team_id=2),      # G
        make_test_player(5013, Position.GUARD, expected_fp=12.0, team_id=3),      # G
        make_test_player(5014, Position.GUARD, expected_fp=10.0, team_id=4),      # G
        make_test_player(5015, Position.FORWARD, expected_fp=25.0, team_id=1),    # F
        make_test_player(5016, Position.FORWARD, expected_fp=18.0, team_id=2),    # F
        make_test_player(5017, Position.FORWARD, expected_fp=14.0, team_id=3),    # F
        make_test_player(5018, Position.FORWARD, expected_fp=8.0, team_id=4),     # F
        make_test_player(5019, Position.CENTER, expected_fp=22.0, team_id=1),     # C
        make_test_player(5020, Position.CENTER, expected_fp=16.0, team_id=2),     # C
        make_test_player(5021, Position.HEAD_COACH, expected_fp=15.0, team_id=5), # HC
    ]

    opt = FixedSquadLineupOptimizer()
    rec = opt.optimize(squad, round_number=1)

    # Log lineup decision with squad_contracts
    record = logger.log_lineup_decision(
        round_number=1,
        season="2026",
        team_id="my_team",
        recommended_decision=rec,
        squad_contracts=squad,
    )

    # Verify StateSnapshot contains player metadata
    snap = store.get_snapshot(record.state_snapshot_id)
    assert snap is not None
    assert 5019 in snap.player_metadata
    assert snap.player_metadata[5019]["position"] == "C"
    assert snap.player_metadata[5015]["position"] == "F"
    assert snap.player_metadata[5021]["position"] == "HC"

    # Evaluate outcomes
    actuals = {
        5011: 18.0, 5012: 14.0, 5013: 16.0, 5014: 8.0,
        5015: 30.0, 5016: 20.0, 5017: 12.0, 5018: 6.0,
        5019: 24.0, 5020: 18.0, 5021: 15.0,
    }
    outcome = updater.update_decision_outcomes(record.decision_id, actuals)
    assert outcome.outcome_status == OutcomeStatus.FINAL
    assert outcome.oracle_actual_score >= outcome.human_actual_score
    assert outcome.human_regret >= 0.0


def test_oracle_metadata_resolution_from_database_eval_players(tmp_path: Path):
    """Verify that OutcomeUpdater queries eval_players/eval_teams from SQLite when snapshot lacks metadata."""
    db_file = tmp_path / "test_db_eval.db"
    store = DecisionStore(db_file)
    updater = OutcomeUpdater(store=store)

    # Populate eval_players & eval_teams in the SQLite database
    with store._connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS eval_teams (
                team_id INTEGER PRIMARY KEY,
                code TEXT NOT NULL,
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS eval_players (
                player_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                position TEXT NOT NULL,
                canonical_team_id INTEGER,
                base_quotation_tenths INTEGER
            );
            INSERT INTO eval_teams (team_id, code, name) VALUES (1, 'RMB', 'Real Madrid'), (2, 'OLY', 'Olympiacos');
            INSERT INTO eval_players (player_id, name, position, canonical_team_id, base_quotation_tenths) VALUES
                (9001, 'Guard Alpha', 'G', 1, 150),
                (9002, 'Guard Beta', 'G', 2, 130),
                (9003, 'Guard Gamma', 'G', 1, 110),
                (9004, 'Guard Delta', 'G', 2, 90),
                (9005, 'Forward Alpha', 'F', 1, 180),
                (9006, 'Forward Beta', 'F', 2, 140),
                (9007, 'Forward Gamma', 'F', 1, 120),
                (9008, 'Forward Delta', 'F', 2, 85),
                (9009, 'Center Alpha', 'C', 1, 175),
                (9010, 'Center Beta', 'C', 2, 125),
                (9011, 'Coach Alpha', 'HC', 1, 100);
            """
        )

    # Create a decision without snapshot metadata
    lineup = LineupPayload(
        formation="2-2-1",
        starter_ids=(9001, 9002, 9005, 9006, 9009),
        captain_id=9005,
        sixth_man_id=9010,
        bench_ids=(9003, 9004, 9007, 9008),
        head_coach_id=9011,
        expected_score=135.0,
    )
    rec = DecisionRecord(
        decision_id="dec_eval_db_001",
        team_id="team_test",
        season="2026",
        round_number=1,
        turn_number=1,
        decision_type=DecisionType.LINEUP,
        created_at="2026-09-23T12:00:00Z",
        provenance=DecisionProvenance(),
        actual_lineup=lineup,
    )
    store.log_decision(rec)

    # Ingest actuals
    actuals = {
        9001: 22.0, 9002: 18.0, 9003: 10.0, 9004: 6.0,
        9005: 28.0, 9006: 19.0, 9007: 12.0, 9008: 5.0,
        9009: 25.0, 9010: 17.0, 9011: 15.0,
    }

    outcome = updater.update_decision_outcomes(rec.decision_id, actuals)
    assert outcome.outcome_status == OutcomeStatus.FINAL
    assert outcome.oracle_actual_score >= outcome.human_actual_score


def test_oracle_metadata_resolution_from_explicit_input(tmp_path: Path):
    """Verify that OutcomeUpdater accepts explicit player_metadata or squad_contracts during evaluation."""
    db_file = tmp_path / "test_explicit_meta.db"
    store = DecisionStore(db_file)
    updater = OutcomeUpdater(store=store)

    squad = [
        make_test_player(7701, Position.GUARD, expected_fp=18.0, team_id=1),
        make_test_player(7702, Position.GUARD, expected_fp=14.0, team_id=2),
        make_test_player(7703, Position.GUARD, expected_fp=11.0, team_id=3),
        make_test_player(7704, Position.GUARD, expected_fp=8.0, team_id=4),
        make_test_player(7705, Position.FORWARD, expected_fp=22.0, team_id=1),
        make_test_player(7706, Position.FORWARD, expected_fp=16.0, team_id=2),
        make_test_player(7707, Position.FORWARD, expected_fp=13.0, team_id=3),
        make_test_player(7708, Position.FORWARD, expected_fp=7.0, team_id=4),
        make_test_player(7709, Position.CENTER, expected_fp=20.0, team_id=1),
        make_test_player(7710, Position.CENTER, expected_fp=15.0, team_id=2),
        make_test_player(7711, Position.HEAD_COACH, expected_fp=12.0, team_id=5),
    ]

    lineup = LineupPayload(
        formation="2-2-1",
        starter_ids=(7701, 7702, 7705, 7706, 7709),
        captain_id=7705,
        sixth_man_id=7710,
        bench_ids=(7703, 7704, 7707, 7708),
        head_coach_id=7711,
    )
    rec = DecisionRecord(
        decision_id="dec_explicit_001",
        team_id="team_test",
        season="2026",
        round_number=1,
        turn_number=1,
        decision_type=DecisionType.LINEUP,
        created_at="2026-09-23T12:00:00Z",
        provenance=DecisionProvenance(),
        actual_lineup=lineup,
    )
    store.log_decision(rec)

    actuals = {p.player_id: p.expected_fp + 2.0 for p in squad}

    # Pass squad_contracts explicitly to update_decision_outcomes
    outcome = updater.update_decision_outcomes(
        decision_id=rec.decision_id,
        actual_scores=actuals,
        squad_contracts=squad,
    )
    assert outcome.outcome_status == OutcomeStatus.FINAL
    assert outcome.oracle_actual_score >= outcome.human_actual_score

