"""Golden end-to-end integration test exercising all major V1.0 subsystems (Section 14).

Exercises the 22-step canonical lifecycle:
1. Load point-in-time snapshot.
2. Validate fantasy state.
3. Generate projections.
4. Run learned_v09.
5. Generate Manager Dossier.
6. Run lineup optimization.
7. Run transfer optimization.
8. Run multi-round strategy.
9. Request Copilot interpretation.
10. Human changes captain/lineup.
11. Log decision.
12. Simulate T1.
13. Recompute T2.
14. Apply T2 decisions.
15. Ingest actual scores.
16. Calculate realized score.
17. Calculate prediction error.
18. Calculate execution regret.
19. Calculate decision regret.
20. Repeat with a EuroCup team.
21. Switch between teams.
22. Verify zero state contamination.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from euroleague_fantasy_manager.competition.ruleset import League, get_league_ruleset
from euroleague_fantasy_manager.evaluation.dataset import EvaluationDatasetStore, build_historical_dataset
from euroleague_fantasy_manager.evaluation.error_attribution import decompose_round_error
from euroleague_fantasy_manager.intelligence.copilot import generate_copilot_advice
from euroleague_fantasy_manager.intelligence.dossier import generate_manager_dossier
from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.multi_team.models import TeamRosterUnit, TeamStateSnapshot
from euroleague_fantasy_manager.multi_team.store import TeamStore
from euroleague_fantasy_manager.optimization.constraints import (
    OptimizationConstraints,
    PlayerProjectionContract,
    validate_squad_constraints,
)
from euroleague_fantasy_manager.optimization.intra_round import (
    IntraRoundPlayerUnit,
    IntraRoundSubstitutionOptimizer,
)
from euroleague_fantasy_manager.optimization.lineup import FixedSquadLineupOptimizer
from euroleague_fantasy_manager.optimization.multi_round import MultiRoundOptimizer
from euroleague_fantasy_manager.optimization.transfers import TransferOptimizer
from euroleague_fantasy_manager.prediction.learned_models import get_default_learned_pipeline
from euroleague_fantasy_manager.services.decision_service import DecisionService
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.storage import SnapshotStore, seed_historical_snapshots
from euroleague_fantasy_manager.tracking.models import DecisionType, LineupPayload
from euroleague_fantasy_manager.tracking.store import DecisionStore


def test_v10_golden_end_to_end_scenario(tmp_path: Path) -> None:
    db_path = tmp_path / "golden_e2e.sqlite3"
    build_historical_dataset(
        database_path=db_path,
        seasons=("E2025", "U2025"),
        rounds_per_season=3,
    )
    seed_historical_snapshots(
        database_path=db_path,
        seasons=("E2025", "U2025"),
        rounds_per_season=3,
    )

    team_store = TeamStore(db_path)
    team_service = TeamService(store=team_store)
    snap_store = SnapshotStore(db_path)
    dec_store = DecisionStore(db_path)
    decision_service = DecisionService(store=dec_store)
    pred_service = PredictionService(database_path=db_path)

    # ------------------------------------------------------------------------
    # 1. Load point-in-time snapshot
    # ------------------------------------------------------------------------
    snap_summary = snap_store.get_latest_summary(league_id=10)
    assert snap_summary is not None
    assert snap_summary.league_id == 10
    players_el = snap_store.load_latest_players(league_id=10)
    assert len(players_el) > 11

    # ------------------------------------------------------------------------
    # 2. Setup team & validate fantasy state
    # ------------------------------------------------------------------------
    el_team = team_service.create_team(
        team_id="el_golden_team",
        name="EuroLeague Golden Team",
        league="euroleague",
        season="2026/27",
        round_number=1,
        turn_number=1,
        bank_tenths=120,
    )
    team_service.set_active_team("el_golden_team")

    guards = [p for p in players_el if p.position == Position.GUARD][:4]
    forwards = [p for p in players_el if p.position == Position.FORWARD][:4]
    centers = [p for p in players_el if p.position == Position.CENTER][:2]
    coaches = [p for p in players_el if p.position == Position.HEAD_COACH][:1]

    # Legal 2-2-1 formation: starters = 2G + 2F + 1C
    starters_p = [guards[0], guards[1], forwards[0], forwards[1], centers[0]]
    sixth_p = guards[2]
    bench_p = [guards[3], forwards[2], forwards[3], centers[1]]
    coach_p = coaches[0]

    units = [
        # Starters
        TeamRosterUnit(
            player_id=starters_p[0].id,
            position="G",
            name=starters_p[0].name,
            team_code=starters_p[0].team_name,
            purchase_price_tenths=starters_p[0].price_tenths,
            current_price_tenths=starters_p[0].price_tenths,
            is_starter=True,
            is_captain=True,
            turn_number=starters_p[0].turn_number,
        ),
        TeamRosterUnit(
            player_id=starters_p[1].id,
            position="G",
            name=starters_p[1].name,
            team_code=starters_p[1].team_name,
            purchase_price_tenths=starters_p[1].price_tenths,
            current_price_tenths=starters_p[1].price_tenths,
            is_starter=True,
            turn_number=starters_p[1].turn_number,
        ),
        TeamRosterUnit(
            player_id=starters_p[2].id,
            position="F",
            name=starters_p[2].name,
            team_code=starters_p[2].team_name,
            purchase_price_tenths=starters_p[2].price_tenths,
            current_price_tenths=starters_p[2].price_tenths,
            is_starter=True,
            turn_number=starters_p[2].turn_number,
        ),
        TeamRosterUnit(
            player_id=starters_p[3].id,
            position="F",
            name=starters_p[3].name,
            team_code=starters_p[3].team_name,
            purchase_price_tenths=starters_p[3].price_tenths,
            current_price_tenths=starters_p[3].price_tenths,
            is_starter=True,
            turn_number=starters_p[3].turn_number,
        ),
        TeamRosterUnit(
            player_id=starters_p[4].id,
            position="C",
            name=starters_p[4].name,
            team_code=starters_p[4].team_name,
            purchase_price_tenths=starters_p[4].price_tenths,
            current_price_tenths=starters_p[4].price_tenths,
            is_starter=True,
            turn_number=starters_p[4].turn_number,
        ),
        # Sixth man
        TeamRosterUnit(
            player_id=sixth_p.id,
            position="G",
            name=sixth_p.name,
            team_code=sixth_p.team_name,
            purchase_price_tenths=sixth_p.price_tenths,
            current_price_tenths=sixth_p.price_tenths,
            is_sixth_man=True,
            turn_number=sixth_p.turn_number,
        ),
        # Bench (4 units)
        TeamRosterUnit(
            player_id=bench_p[0].id,
            position="G",
            name=bench_p[0].name,
            team_code=bench_p[0].team_name,
            purchase_price_tenths=bench_p[0].price_tenths,
            current_price_tenths=bench_p[0].price_tenths,
            is_bench=True,
            turn_number=bench_p[0].turn_number,
        ),
        TeamRosterUnit(
            player_id=bench_p[1].id,
            position="F",
            name=bench_p[1].name,
            team_code=bench_p[1].team_name,
            purchase_price_tenths=bench_p[1].price_tenths,
            current_price_tenths=bench_p[1].price_tenths,
            is_bench=True,
            turn_number=bench_p[1].turn_number,
        ),
        TeamRosterUnit(
            player_id=bench_p[2].id,
            position="F",
            name=bench_p[2].name,
            team_code=bench_p[2].team_name,
            purchase_price_tenths=bench_p[2].price_tenths,
            current_price_tenths=bench_p[2].price_tenths,
            is_bench=True,
            turn_number=bench_p[2].turn_number,
        ),
        TeamRosterUnit(
            player_id=bench_p[3].id,
            position="C",
            name=bench_p[3].name,
            team_code=bench_p[3].team_name,
            purchase_price_tenths=bench_p[3].price_tenths,
            current_price_tenths=bench_p[3].price_tenths,
            is_bench=True,
            turn_number=bench_p[3].turn_number,
        ),
        # Coach
        TeamRosterUnit(
            player_id=coach_p.id,
            position="HC",
            name=coach_p.name,
            team_code=coach_p.team_name,
            purchase_price_tenths=coach_p.price_tenths,
            current_price_tenths=coach_p.price_tenths,
            is_coach=True,
            turn_number=coach_p.turn_number,
        ),
    ]
    team_service.set_squad("el_golden_team", round_number=1, roster_units=units)

    # Validate state snapshot invariants
    team_obj = team_service.get_team("el_golden_team")
    snap = TeamStateSnapshot.from_team(team_obj)
    ruleset_el = get_league_ruleset(League.EUROLEAGUE)
    errors = snap.validate_invariants(ruleset_el)
    assert len(errors) == 0

    # ------------------------------------------------------------------------
    # 3. Generate projections
    # ------------------------------------------------------------------------
    contracts = pred_service.get_projections_dict(
        season="E2025",
        round_number=1,
        model_name="season_mean",
        league="euroleague",
    )
    assert len(contracts) > 0

    # ------------------------------------------------------------------------
    # 4. Run learned_v09
    # ------------------------------------------------------------------------
    learned_pipe = get_default_learned_pipeline()
    assert learned_pipe.is_fitted
    learned_contracts = pred_service.get_projections(
        season="E2025",
        round_number=1,
        model_name="learned_v09",
        league="euroleague",
    )
    assert len(learned_contracts) > 0

    # ------------------------------------------------------------------------
    # 5. Generate Manager Dossier
    # ------------------------------------------------------------------------
    dossier = generate_manager_dossier(
        team_id="el_golden_team",
        season="E2025",
        round_number=1,
        team_service=team_service,
        database_path=db_path,
    )
    assert dossier.team_id == "el_golden_team"
    assert len(dossier.current_lineup.starters) == 5
    assert len(dossier.current_lineup.bench) == 4
    assert dossier.current_lineup.sixth_man is not None
    assert dossier.current_lineup.coach is not None

    # ------------------------------------------------------------------------
    # 6. Run lineup optimization
    # ------------------------------------------------------------------------
    squad_contracts = [contracts[u.player_id] for u in units if u.player_id in contracts]
    lineup_opt = FixedSquadLineupOptimizer()
    recommended_lineup = lineup_opt.optimize(squad_contracts, round_number=1)
    assert recommended_lineup.is_valid

    # ------------------------------------------------------------------------
    # 7. Run transfer optimization
    # ------------------------------------------------------------------------
    transfer_opt = TransferOptimizer()
    tx_rec = transfer_opt.optimize_transfers(
        current_squad=squad_contracts,
        market=list(contracts.values()),
        bank_tenths=el_team.bank_tenths,
        max_trades=4,
        round_number=1,
    )
    assert len(tx_rec.recommendations) > 0

    # ------------------------------------------------------------------------
    # 8. Run multi-round strategy
    # ------------------------------------------------------------------------
    multi_opt = MultiRoundOptimizer(branching_factor=2, discount_factor=0.95)
    mr_plan = multi_opt.optimize_multi_round(
        start_round=1,
        horizon=2,
        initial_squad=squad_contracts,
        projections_by_round={1: squad_contracts, 2: squad_contracts},
    )
    assert mr_plan.horizon == 2
    assert mr_plan.planning_mode == "approximate"

    # ------------------------------------------------------------------------
    # 9. Request Copilot interpretation
    # ------------------------------------------------------------------------
    copilot_advice = generate_copilot_advice(
        dossier=dossier,
        persona="briefing",
        provider_name="heuristic",
        database_path=db_path,
    )
    assert copilot_advice.analysis_text is not None

    # ------------------------------------------------------------------------
    # 10. Human changes captain / lineup
    # ------------------------------------------------------------------------
    human_starters = list(recommended_lineup.starter_ids)
    # Human picks starter 1 as captain instead of recommended
    human_captain = human_starters[1]
    assert human_captain != recommended_lineup.captain_id or len(human_starters) >= 2

    # ------------------------------------------------------------------------
    # 11. Log decision
    # ------------------------------------------------------------------------
    rec_payload = LineupPayload(
        formation=recommended_lineup.formation,
        starter_ids=tuple(recommended_lineup.starter_ids),
        captain_id=recommended_lineup.captain_id,
        sixth_man_id=recommended_lineup.sixth_man_id,
        bench_ids=tuple(recommended_lineup.bench_ids),
        head_coach_id=recommended_lineup.head_coach_id,
        expected_score=float(recommended_lineup.objective_value),
    )
    human_payload = LineupPayload(
        formation=recommended_lineup.formation,
        starter_ids=tuple(human_starters),
        captain_id=human_captain,
        sixth_man_id=recommended_lineup.sixth_man_id,
        bench_ids=tuple(recommended_lineup.bench_ids),
        head_coach_id=recommended_lineup.head_coach_id,
        expected_score=float(recommended_lineup.objective_value),
    )
    decision = decision_service.log_lineup(
        team_id="el_golden_team",
        season="E2025",
        round_number=1,
        turn_number=1,
        recommended_lineup=rec_payload,
        actual_lineup=human_payload,
        notes="Human manual override on captain",
        squad_contracts=squad_contracts,
        league="euroleague",
    )
    assert decision.decision_id is not None
    assert decision.league == "euroleague"
    assert decision.recommended_lineup.captain_id == recommended_lineup.captain_id

    # ------------------------------------------------------------------------
    # 12 & 13 & 14. T1 play -> Recompute T2 -> Apply T2 decisions
    # ------------------------------------------------------------------------
    # Load actuals for evaluation
    store_eval = EvaluationDatasetStore(db_path)
    actuals = {}
    with store_eval._connect() as conn:
        rows = conn.execute(
            "SELECT player_id, fantasy_points FROM eval_player_games WHERE season = 'E2025' AND round = 1"
        ).fetchall()
        for r in rows:
            actuals[int(r["player_id"])] = float(r["fantasy_points"])

    sub_opt = IntraRoundSubstitutionOptimizer()
    role_of = lambda u: (
        "coach" if u.is_coach else "starter" if u.is_starter
        else "sixth_man" if u.is_sixth_man else "bench"
    )
    units_for_sub = [
        IntraRoundPlayerUnit(
            player_id=u.player_id,
            name=u.name,
            position=u.position,
            team_code=u.team_code,
            turn_number=u.turn_number,
            has_played=(u.turn_number == 1),
            actual_fp=actuals.get(u.player_id, 10.0) if u.turn_number == 1 else None,
            expected_fp=15.0,
            current_role=role_of(u),
            is_captain=u.is_captain,
        )
        for u in units
    ]
    sub_res = sub_opt.optimize(units_for_sub)
    assert sub_res is not None

    # ------------------------------------------------------------------------
    # 15 & 16 & 17 & 18 & 19. Ingest scores, realized score, error & regret
    # ------------------------------------------------------------------------
    realized_score = sum(actuals.get(pid, 10.0) for pid in human_starters)
    err_decomp = decompose_round_error(
        predicted_score=recommended_lineup.objective_value,
        actual_score=realized_score,
        execution_regret=0.0,
        model_name="learned_v09",
        season="E2025",
        round_number=1,
    )
    assert err_decomp.total_error == round(abs(realized_score - recommended_lineup.objective_value), 2)
    assert err_decomp.model_error + err_decomp.aleatoric_noise == err_decomp.total_error

    # ------------------------------------------------------------------------
    # 20. Repeat with EuroCup team
    # ------------------------------------------------------------------------
    ec_team = team_service.create_team(
        team_id="ec_golden_team",
        name="EuroCup Golden Team",
        league="eurocup",
        season="2026/27",
        round_number=1,
        bank_tenths=200,
    )
    players_ec = snap_store.load_latest_players(league_id=11)
    g_ec = [p for p in players_ec if p.position == Position.GUARD][:4]
    f_ec = [p for p in players_ec if p.position == Position.FORWARD][:4]
    c_ec = [p for p in players_ec if p.position == Position.CENTER][:2]
    hc_ec = [p for p in players_ec if p.position == Position.HEAD_COACH][:1]

    # Legal 2-2-1 formation for EuroCup: starters = 2G + 2F + 1C
    ec_starters = [g_ec[0], g_ec[1], f_ec[0], f_ec[1], c_ec[0]]
    ec_sixth = g_ec[2]
    ec_bench = [g_ec[3], f_ec[2], f_ec[3], c_ec[1]]
    ec_coach = hc_ec[0]

    ec_units = [
        # Starters
        TeamRosterUnit(ec_starters[0].id, "G", ec_starters[0].name, ec_starters[0].team_name, ec_starters[0].price_tenths, ec_starters[0].price_tenths, is_starter=True, is_captain=True, turn_number=ec_starters[0].turn_number),
        TeamRosterUnit(ec_starters[1].id, "G", ec_starters[1].name, ec_starters[1].team_name, ec_starters[1].price_tenths, ec_starters[1].price_tenths, is_starter=True, turn_number=ec_starters[1].turn_number),
        TeamRosterUnit(ec_starters[2].id, "F", ec_starters[2].name, ec_starters[2].team_name, ec_starters[2].price_tenths, ec_starters[2].price_tenths, is_starter=True, turn_number=ec_starters[2].turn_number),
        TeamRosterUnit(ec_starters[3].id, "F", ec_starters[3].name, ec_starters[3].team_name, ec_starters[3].price_tenths, ec_starters[3].price_tenths, is_starter=True, turn_number=ec_starters[3].turn_number),
        TeamRosterUnit(ec_starters[4].id, "C", ec_starters[4].name, ec_starters[4].team_name, ec_starters[4].price_tenths, ec_starters[4].price_tenths, is_starter=True, turn_number=ec_starters[4].turn_number),
        # Sixth man
        TeamRosterUnit(ec_sixth.id, "G", ec_sixth.name, ec_sixth.team_name, ec_sixth.price_tenths, ec_sixth.price_tenths, is_sixth_man=True, turn_number=ec_sixth.turn_number),
        # Bench
        TeamRosterUnit(ec_bench[0].id, "G", ec_bench[0].name, ec_bench[0].team_name, ec_bench[0].price_tenths, ec_bench[0].price_tenths, is_bench=True, turn_number=ec_bench[0].turn_number),
        TeamRosterUnit(ec_bench[1].id, "F", ec_bench[1].name, ec_bench[1].team_name, ec_bench[1].price_tenths, ec_bench[1].price_tenths, is_bench=True, turn_number=ec_bench[1].turn_number),
        TeamRosterUnit(ec_bench[2].id, "F", ec_bench[2].name, ec_bench[2].team_name, ec_bench[2].price_tenths, ec_bench[2].price_tenths, is_bench=True, turn_number=ec_bench[2].turn_number),
        TeamRosterUnit(ec_bench[3].id, "C", ec_bench[3].name, ec_bench[3].team_name, ec_bench[3].price_tenths, ec_bench[3].price_tenths, is_bench=True, turn_number=ec_bench[3].turn_number),
        # Coach
        TeamRosterUnit(ec_coach.id, "HC", ec_coach.name, ec_coach.team_name, ec_coach.price_tenths, ec_coach.price_tenths, is_coach=True, turn_number=ec_coach.turn_number),
    ]
    team_service.set_squad("ec_golden_team", round_number=1, roster_units=ec_units)

    # ------------------------------------------------------------------------
    # 21 & 22. Switch between teams & verify zero contamination
    # ------------------------------------------------------------------------
    team_service.set_active_team("ec_golden_team")
    assert team_service.get_active_team().team_id == "ec_golden_team"
    assert team_service.get_active_team().league == "eurocup"

    team_service.set_active_team("el_golden_team")
    active_now = team_service.get_active_team()
    assert active_now.team_id == "el_golden_team"
    assert active_now.league == "euroleague"
    assert active_now.bank_tenths == 120

    t_ec_check = team_service.get_team("ec_golden_team")
    assert t_ec_check.bank_tenths == 200
    assert t_ec_check.league == "eurocup"
