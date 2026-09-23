"""Workstation API endpoints connecting GUI to application services."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.multi_team.models import TeamRosterUnit
from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
from euroleague_fantasy_manager.services.decision_service import DecisionService
from euroleague_fantasy_manager.services.evaluation_service import EvaluationService
from euroleague_fantasy_manager.services.optimization_service import (
    LineupDecisionView,
    OptimizationService,
)
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.services.scenario_service import (
    ScenarioResult,
    ScenarioService,
)
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.web.deps import (
    get_decision_service,
    get_evaluation_service,
    get_optimization_service,
    get_prediction_service,
    get_scenario_service,
    get_team_service,
)

router = APIRouter(prefix="/api/workstation", tags=["workstation"])


# Request Schemas
class OptimizeLineupRequest(BaseModel):
    team_id: str
    season: str = "2026/27"
    round_number: int | None = None
    risk_mode: str = "expected"
    option_value_mode: str = "captain_eligible"


class OptimizeTransfersRequest(BaseModel):
    team_id: str
    season: str = "2026/27"
    round_number: int | None = None
    max_trades: int = 1
    unlimited: bool = False
    exhaustive: bool = False


class MultiRoundRequest(BaseModel):
    team_id: str
    season: str = "2026/27"
    start_round: int | None = None
    horizon: int = 3
    gamma: float = 0.95


class SimulateTurnSubRequest(BaseModel):
    team_id: str
    season: str = "2026/27"
    round_number: int | None = None
    turn_1_scores: dict[str, float] = Field(default_factory=dict)


class ScenarioRequest(BaseModel):
    team_id: str
    season: str = "2026/27"
    round_number: int | None = None
    rule_out_players: list[int] = Field(default_factory=list)
    force_starters: list[int] = Field(default_factory=list)
    candidate_transfers_out: list[int] = Field(default_factory=list)
    candidate_transfers_in: list[int] = Field(default_factory=list)
    risk_mode_override: str | None = None
    turn_1_scores: dict[str, float] = Field(default_factory=dict)


class UpdateScoresRequest(BaseModel):
    team_id: str
    season: str = "2026/27"
    round_number: int
    actual_scores: dict[str, float] = Field(default_factory=dict)


class LogDecisionRequest(BaseModel):
    team_id: str
    season: str = "2026/27"
    round_number: int
    turn_number: int = 1
    decision_type: str = "lineup"
    notes: str = ""
    override: bool = False


# Endpoints
@router.get("/dashboard")
def get_dashboard(
    team_id: str,
    season: str = "2026/27",
    round_number: int | None = None,
    team_service: TeamService = Depends(get_team_service),
    prediction_service: PredictionService = Depends(get_prediction_service),
    optimization_service: OptimizationService = Depends(get_optimization_service),
) -> dict[str, Any]:
    """Retrieve unified dashboard payload for team workstation (Phase C, D)."""
    try:
        team = team_service.get_team(team_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found.")

    rnd = round_number or team.round_number
    opt_lineup = optimization_service.optimize_lineup(
        team_id=team_id,
        season=season,
        round_number=rnd,
        risk_mode=team.settings.risk_mode,
        option_value_mode=team.settings.option_value_mode,
    )

    # Squad units with projections
    proj_dict = prediction_service.get_projections_dict(season, rnd)
    squad_details = []
    for unit in team.squad:
        c = proj_dict.get(unit.player_id)
        squad_details.append({
            "player_id": unit.player_id,
            "name": unit.name or (c.player_name if c else f"Player {unit.player_id}"),
            "position": unit.position,
            "team_code": unit.team_code or (c.team_code if c else ""),
            "price_tenths": unit.current_price_tenths,
            "credits": round(unit.current_price_tenths / 10.0, 1),
            "is_starter": unit.is_starter,
            "is_captain": unit.is_captain,
            "is_sixth_man": unit.is_sixth_man,
            "is_bench": unit.is_bench,
            "is_coach": unit.is_coach,
            "turn_number": unit.turn_number,
            "expected_fp": round(c.expected_fp, 2) if c else 0.0,
            "probability_play": round(c.probability_play, 2) if c else 1.0,
            "uncertainty": round(c.uncertainty, 2) if c else 0.0,
            "opponent_code": c.opponent_code if c else "",
            "is_home": c.is_home if c else True,
        })

    return {
        "team": team.to_dict(),
        "round_number": rnd,
        "bank_credits": round(team.bank_tenths / 10.0, 1),
        "squad_value_credits": round(team.total_squad_value_tenths / 10.0, 1),
        "squad": squad_details,
        "optimal_lineup": opt_lineup.to_dict(),
        "provenance": {
            "prediction_model": "production_ridge_v03",
            "optimizer_version": "0.5.0",
            "risk_mode": team.settings.risk_mode,
            "option_value_mode": team.settings.option_value_mode,
        },
    }


@router.post("/optimize/lineup")
def optimize_lineup_endpoint(
    req: OptimizeLineupRequest,
    optimization_service: OptimizationService = Depends(get_optimization_service),
) -> dict[str, Any]:
    try:
        res = optimization_service.optimize_lineup(
            team_id=req.team_id,
            season=req.season,
            round_number=req.round_number,
            risk_mode=req.risk_mode,
            option_value_mode=req.option_value_mode,
        )
        return res.to_dict()
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/optimize/transfers")
def optimize_transfers_endpoint(
    req: OptimizeTransfersRequest,
    optimization_service: OptimizationService = Depends(get_optimization_service),
) -> dict[str, Any]:
    try:
        res = optimization_service.optimize_transfers(
            team_id=req.team_id,
            season=req.season,
            round_number=req.round_number,
            max_trades=req.max_trades,
            unlimited=req.unlimited,
            exhaustive=req.exhaustive,
        )

        recs = []
        for r in res.recommendations:
            recs.append({
                "transfers_out": list(r.transfers_out),
                "transfers_in": list(r.transfers_in),
                "net_score_gain": round(r.net_score_gain, 2),
                "budget_delta_tenths": r.budget_delta_tenths,
                "budget_delta_credits": round(r.budget_delta_tenths / 10.0, 1),
                "remaining_bank_tenths": r.remaining_bank_tenths,
                "remaining_bank_credits": round(r.remaining_bank_tenths / 10.0, 1),
                "post_transfer_expected_score": round(r.post_transfer_expected_score, 2),
                "is_legal": r.is_legal,
            })

        return {
            "team_id": req.team_id,
            "best_recommendation": recs[0] if recs else None,
            "recommendations": recs,
            "evaluated_combinations": res.evaluated_combinations,
            "elapsed_seconds": round(res.elapsed_seconds, 3),
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/simulate/turn-sub")
def simulate_turn_sub_endpoint(
    req: SimulateTurnSubRequest,
    scenario_service: ScenarioService = Depends(get_scenario_service),
) -> dict[str, Any]:
    """Simulate Turn 1 -> Turn 2 substitutions with observed Turn 1 scores (Phase F)."""
    try:
        parsed_scores = {int(k): float(v) for k, v in req.turn_1_scores.items()}
        res = scenario_service.simulate(
            team_id=req.team_id,
            season=req.season,
            round_number=req.round_number,
            turn_1_scores=parsed_scores,
        )
        return {
            "team_id": req.team_id,
            "baseline_expected_fp": res.baseline_lineup.expected_total_fp,
            "updated_expected_fp": res.scenario_lineup.expected_total_fp,
            "net_gain": res.delta_expected_score,
            "recommended_lineup": res.scenario_lineup.to_dict(),
            "captain_changed": res.captain_changed,
            "formation_changed": res.formation_changed,
            "substitutions": {
                "starters_in": res.starters_added,
                "starters_out": res.starters_removed,
            },
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/scenarios")
def simulate_scenario_endpoint(
    req: ScenarioRequest,
    scenario_service: ScenarioService = Depends(get_scenario_service),
) -> dict[str, Any]:
    """Execute disposable what-if scenario (Phase M)."""
    try:
        parsed_scores = {int(k): float(v) for k, v in req.turn_1_scores.items()}
        res = scenario_service.simulate(
            team_id=req.team_id,
            season=req.season,
            round_number=req.round_number,
            rule_out_players=req.rule_out_players,
            force_starters=req.force_starters,
            candidate_transfers_out=req.candidate_transfers_out,
            candidate_transfers_in=req.candidate_transfers_in,
            risk_mode_override=req.risk_mode_override,
            turn_1_scores=parsed_scores,
        )
        return res.to_dict()
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/optimize/multi-round")
def optimize_multi_round_endpoint(
    req: MultiRoundRequest,
    optimization_service: OptimizationService = Depends(get_optimization_service),
) -> dict[str, Any]:
    """Multi-round beam search transfer planning (Phase I)."""
    try:
        plan = optimization_service.plan_multi_round(
            team_id=req.team_id,
            season=req.season,
            start_round=req.start_round,
            horizon=req.horizon,
            gamma=req.gamma,
        )
        steps = []
        for s in plan.steps:
            steps.append({
                "round_number": s.round_number,
                "transfers_out": list(s.transfers_out),
                "transfers_in": list(s.transfers_in),
                "expected_score": round(s.expected_score, 2),
                "discounted_score": round(s.discounted_score, 2),
                "formation": s.formation,
                "bank_tenths": s.remaining_bank_tenths,
                "bank_credits": round(s.remaining_bank_tenths / 10.0, 1),
            })
        return {
            "team_id": req.team_id,
            "horizon": plan.horizon,
            "discount_gamma": plan.discount_gamma,
            "total_expected_score": round(plan.total_expected_score, 2),
            "total_discounted_score": round(plan.total_discounted_score, 2),
            "steps": steps,
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/evaluation")
def get_evaluation_endpoint(
    team_id: str,
    season: str = "2026/27",
    window: int = 5,
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
) -> dict[str, Any]:
    """Retrieve closed-loop evaluation summary, regrets, and round history (Phase J, K)."""
    try:
        summary = evaluation_service.get_summary(team_id=team_id, season=season, window=window)
        history = evaluation_service.get_round_history(team_id=team_id, season=season)
        return {
            "team_id": team_id,
            "season": season,
            "summary": summary.to_dict(),
            "history": history,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/evaluation/update-scores")
def update_scores_endpoint(
    req: UpdateScoresRequest,
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
) -> dict[str, Any]:
    """Ingest actual scores and recalculate regret metrics."""
    try:
        parsed_scores = {int(k): float(v) for k, v in req.actual_scores.items()}
        outcomes = evaluation_service.update_scores(
            team_id=req.team_id,
            season=req.season,
            round_number=req.round_number,
            actual_scores=parsed_scores,
        )
        return {
            "updated_decisions": len(outcomes),
            "outcomes": [o.to_dict() for o in outcomes],
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/players")
def list_players_endpoint(
    season: str = "2026/27",
    round_number: int = 1,
    position: str | None = None,
    search: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    limit: int = 50,
    prediction_service: PredictionService = Depends(get_prediction_service),
) -> list[dict[str, Any]]:
    """Player browser for Trade Studio with valuation metrics (Phase G)."""
    contracts = prediction_service.get_projections(season, round_number)
    valuations = prediction_service.get_player_valuations(season, round_number)

    filtered = []
    for c in contracts:
        pos_str = c.position.name if hasattr(c.position, "name") else str(c.position)
        if position and pos_str.upper() != position.upper():
            continue
        if search and search.lower() not in c.player_name.lower() and search.lower() not in c.team_code.lower():
            continue
        if min_price is not None and c.credits < min_price:
            continue
        if max_price is not None and c.credits > max_price:
            continue

        val = valuations.get(c.player_id, {})
        filtered.append({
            "player_id": c.player_id,
            "name": c.player_name,
            "position": pos_str,
            "team_code": c.team_code,
            "price_tenths": c.price_tenths,
            "credits": c.credits,
            "expected_fp": round(c.expected_fp, 2),
            "probability_play": round(c.probability_play, 2),
            "expected_minutes": round(c.expected_minutes, 1),
            "fp_per_credit": val.get("fp_per_credit", 0.0),
            "risk_adjusted_fp": val.get("risk_adjusted_fp", c.expected_fp),
            "turn_number": c.turn_number,
            "opponent_code": c.opponent_code,
            "is_home": c.is_home,
        })

    filtered.sort(key=lambda x: -x["expected_fp"])
    return filtered[:limit]
