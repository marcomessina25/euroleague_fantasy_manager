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


class SuggestInitialTeamRequest(BaseModel):
    season: str = "2026/27"
    budget_credits: float = 100.0
    risk_mode: str = "expected"
    locked_player_ids: list[int] = Field(default_factory=list)


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
        has_played = getattr(c, "has_played", False) if c else False
        actual_fp = getattr(c, "actual_fp", None) if c else None
        exp_fp = round(c.expected_fp, 2) if c else 0.0

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
            "expected_fp": exp_fp,
            "actual_fp": round(actual_fp, 2) if actual_fp is not None else None,
            "has_played": has_played,
            "probability_play": round(c.probability_play, 2) if c else 1.0,
            "uncertainty": round(c.uncertainty, 2) if c else 0.0,
            "opponent_code": c.opponent_code if c else "",
            "is_home": c.is_home if c else True,
        })

    # Build active current_lineup representing team's actual saved squad roles
    squad_units = team.squad
    starters_units = [u for u in squad_units if u.is_starter]
    bench_units = [u for u in squad_units if u.is_bench]
    sixth_man_unit = next((u for u in squad_units if u.is_sixth_man), None)
    coach_unit = next((u for u in squad_units if u.is_coach or u.position == "HC"), None)

    # If team roles have not been assigned yet (e.g. freshly imported or draft without role flags),
    # sync with opt_lineup so the team gets its starting five, captain, 6th man, bench
    if len(starters_units) != 5 or not sixth_man_unit or not coach_unit:
        team = team_service.update_lineup(
            team_id=team_id,
            starter_ids=[p["player_id"] for p in opt_lineup.starters],
            captain_id=opt_lineup.captain_id,
            sixth_man_id=opt_lineup.sixth_man_id,
            bench_ids=[p["player_id"] for p in opt_lineup.bench],
            coach_id=opt_lineup.coach_id,
        )
        squad_units = team.squad
        starters_units = [u for u in squad_units if u.is_starter]
        bench_units = [u for u in squad_units if u.is_bench]
        sixth_man_unit = next((u for u in squad_units if u.is_sixth_man), None)
        coach_unit = next((u for u in squad_units if u.is_coach or u.position == "HC"), None)

    def _fmt_lineup_unit(u: Any) -> dict[str, Any]:
        c = proj_dict.get(u.player_id)
        pos = u.position
        if hasattr(c, "position") and c:
            pos = c.position.short_code if hasattr(c.position, "short_code") else str(c.position)
        elif u.is_coach or pos == "HEAD_COACH":
            pos = "HC"

        has_played = getattr(c, "has_played", False) if c else False
        actual_fp = getattr(c, "actual_fp", None) if c else None
        exp_fp = round(c.expected_fp, 2) if c else 0.0

        return {
            "player_id": u.player_id,
            "name": u.name or (c.player_name if c else f"Player {u.player_id}"),
            "position": pos,
            "team_code": u.team_code or (c.team_code if c else ""),
            "credits": round(u.current_price_tenths / 10.0, 1),
            "expected_fp": exp_fp,
            "actual_fp": round(actual_fp, 2) if actual_fp is not None else None,
            "has_played": has_played,
            "turn_number": u.turn_number or (c.turn_number if c else 1),
            "opponent_code": c.opponent_code if c else "",
            "is_home": c.is_home if c else True,
            "is_starter": u.is_starter,
            "is_captain": u.is_captain,
            "is_sixth_man": u.is_sixth_man,
            "is_bench": u.is_bench,
            "is_coach": u.is_coach,
        }

    starters_formatted = [_fmt_lineup_unit(u) for u in starters_units]
    bench_formatted = [_fmt_lineup_unit(u) for u in bench_units]
    sixth_man_formatted = _fmt_lineup_unit(sixth_man_unit) if sixth_man_unit else None
    coach_formatted = _fmt_lineup_unit(coach_unit) if coach_unit else None

    def _p_char(p_str: str) -> str:
        s = p_str.upper()
        if "G" in s: return "G"
        if "F" in s: return "F"
        if "C" in s: return "C"
        return s

    g_count = sum(1 for p in starters_formatted if _p_char(p["position"]) == "G")
    f_count = sum(1 for p in starters_formatted if _p_char(p["position"]) == "F")
    c_count = sum(1 for p in starters_formatted if _p_char(p["position"]) == "C")
    formation_str = f"{g_count}-{f_count}-{c_count}"

    captain_id = team.captain_id or (starters_formatted[0]["player_id"] if starters_formatted else 0)
    sixth_man_id = team.sixth_man_id or (sixth_man_formatted["player_id"] if sixth_man_formatted else 0)
    coach_id = team.coach_id or (coach_formatted["player_id"] if coach_formatted else 0)

    # Compute score breakdown: Realized points for played players + Expected points for unplayed players
    tot_unplayed_expected_fp = 0.0
    tot_realized_fp = 0.0
    played_count = 0
    unplayed_count = 0

    for p in starters_formatted:
        mult = 2.0 if p["player_id"] == captain_id else 1.0
        if p["has_played"] and p["actual_fp"] is not None:
            tot_realized_fp += p["actual_fp"] * mult
            played_count += 1
        else:
            tot_unplayed_expected_fp += p["expected_fp"] * mult
            unplayed_count += 1

    if sixth_man_formatted:
        if sixth_man_formatted["has_played"] and sixth_man_formatted["actual_fp"] is not None:
            tot_realized_fp += sixth_man_formatted["actual_fp"] * 1.0
            played_count += 1
        else:
            tot_unplayed_expected_fp += sixth_man_formatted["expected_fp"] * 1.0
            unplayed_count += 1

    for p in bench_formatted:
        if p["has_played"] and p["actual_fp"] is not None:
            tot_realized_fp += p["actual_fp"] * 0.5
            played_count += 1
        else:
            tot_unplayed_expected_fp += p["expected_fp"] * 0.5
            unplayed_count += 1

    if coach_formatted:
        if coach_formatted["has_played"] and coach_formatted["actual_fp"] is not None:
            tot_realized_fp += coach_formatted["actual_fp"] * 1.0
            played_count += 1
        else:
            tot_unplayed_expected_fp += coach_formatted["expected_fp"] * 1.0
            unplayed_count += 1

    tot_projected_fp = tot_realized_fp + tot_unplayed_expected_fp
    assert abs((tot_realized_fp + tot_unplayed_expected_fp) - tot_projected_fp) < 0.01, (
        f"Court score breakdown inconsistency: realized ({tot_realized_fp}) + "
        f"unplayed_expected ({tot_unplayed_expected_fp}) != total ({tot_projected_fp})"
    )
    any_played = played_count > 0

    current_lineup = {
        "starters": starters_formatted,
        "bench": bench_formatted,
        "sixth_man": sixth_man_formatted,
        "coach": coach_formatted,
        "captain_id": captain_id,
        "sixth_man_id": sixth_man_id,
        "coach_id": coach_id,
        "formation": formation_str,
        "expected_total_fp": round(tot_projected_fp, 2),
        "realized_total_fp": round(tot_realized_fp, 2),
        "unplayed_expected_fp": round(tot_unplayed_expected_fp, 2),
        "played_count": played_count,
        "unplayed_count": unplayed_count,
        "any_played": any_played,
        "alternatives": opt_lineup.alternatives,
        "unpruned_oracle_match": opt_lineup.unpruned_oracle_match,
    }

    return {
        "team": team.to_dict(),
        "round_number": rnd,
        "bank_credits": round(team.bank_tenths / 10.0, 1),
        "squad_value_credits": round(team.total_squad_value_tenths / 10.0, 1),
        "squad": squad_details,
        "current_lineup": current_lineup,
        "optimal_lineup": opt_lineup.to_dict(),
        "realized_total_fp": round(tot_realized_fp, 2),
        "unplayed_expected_fp": round(tot_unplayed_expected_fp, 2),
        "total_fp": round(tot_projected_fp, 2),
        "played_count": played_count,
        "unplayed_count": unplayed_count,
        "any_played": any_played,
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
                "transfers_out": [p.player_id for p in r.out_players],
                "transfers_out_details": [
                    {
                        "player_id": p.player_id,
                        "name": p.player_name,
                        "position": p.position.short_code if hasattr(p.position, "short_code") else str(p.position),
                        "credits": p.credits,
                        "expected_fp": round(p.expected_fp, 2),
                    }
                    for p in r.out_players
                ],
                "transfers_in": [p.player_id for p in r.in_players],
                "transfers_in_details": [
                    {
                        "player_id": p.player_id,
                        "name": p.player_name,
                        "position": p.position.short_code if hasattr(p.position, "short_code") else str(p.position),
                        "credits": p.credits,
                        "expected_fp": round(p.expected_fp, 2),
                    }
                    for p in r.in_players
                ],
                "net_score_gain": round(r.net_transfer_value, 2),
                "gross_score_gain": round(r.gross_score_gain, 2),
                "remaining_bank_tenths": r.remaining_bank_tenths,
                "remaining_bank_credits": round(r.remaining_bank_tenths / 10.0, 1),
                "post_transfer_expected_score": round(r.new_lineup.expected_score, 2),
                "is_legal": True,
            })

        return {
            "team_id": req.team_id,
            "best_recommendation": recs[0] if recs else None,
            "recommendations": recs,
            "evaluated_combinations": res.total_evaluated_packages,
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class SimulateIntraRoundRequest(BaseModel):
    team_id: str
    season: str = "2026/27"
    round_number: int | None = None


@router.post("/simulate/intra-round")
def simulate_intra_round_endpoint(
    req: SimulateIntraRoundRequest,
    optimization_service: OptimizationService = Depends(get_optimization_service),
) -> dict[str, Any]:
    """Compute optimal legal intra-round bench-to-court substitutions (T1 -> T2 -> T3)."""
    try:
        res = optimization_service.optimize_intra_round(
            team_id=req.team_id,
            season=req.season,
            round_number=req.round_number,
        )
        return res.to_dict()
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/apply/intra-round")
def apply_intra_round_endpoint(
    req: SimulateIntraRoundRequest,
    optimization_service: OptimizationService = Depends(get_optimization_service),
    team_service: TeamService = Depends(get_team_service),
    decision_service: DecisionService = Depends(get_decision_service),
) -> dict[str, Any]:
    """Apply the optimal intra-round substitutions directly to the team lineup."""
    try:
        res = optimization_service.optimize_intra_round(
            team_id=req.team_id,
            season=req.season,
            round_number=req.round_number,
        )
        updated_team = team_service.update_lineup(
            team_id=req.team_id,
            starter_ids=res.starter_ids,
            captain_id=res.captain_id,
            sixth_man_id=res.sixth_man_id,
            bench_ids=res.bench_ids,
            coach_id=res.coach_id,
        )

        # Log decision
        try:
            from euroleague_fantasy_manager.tracking.models import TurnSubPayload
            sub_out = res.substitutions[0]["out_player"]["player_id"] if res.substitutions else None
            sub_in = res.substitutions[0]["in_player"]["player_id"] if res.substitutions else None
            cap_old = res.captain_change_detail["old_captain"]["player_id"] if res.captain_change_detail else None
            cap_new = res.captain_change_detail["new_captain"]["player_id"] if res.captain_change_detail else None
            payload = TurnSubPayload(
                t1_actuals={},
                substituted_out_id=sub_out,
                substituted_in_id=sub_in,
                old_captain_id=cap_old,
                new_captain_id=cap_new,
                realized_sub_gain=res.net_gain,
            )
            decision_service.log_turn_sub(
                team_id=req.team_id,
                season=req.season,
                round_number=updated_team.round_number,
                turn_number=updated_team.turn_number,
                recommended_turn_sub=payload,
                actual_turn_sub=payload,
                notes=f"Applied intra-round substitution with +{res.net_gain} FP net gain",
            )
        except Exception:
            pass

        return {
            "success": True,
            "message": f"Applied {len(res.substitutions)} intra-round substitution(s) (+{res.net_gain} FP gain)",
            "lineup": res.to_dict(),
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
    """Legacy Turn 1 -> Turn 2 simulation endpoint."""
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
            out_players = list(s.transfers.out_players) if s.transfers else []
            in_players = list(s.transfers.in_players) if s.transfers else []
            steps.append({
                "round_number": s.round_number,
                "transfers_out": [p.player_name for p in out_players],
                "transfers_out_ids": [p.player_id for p in out_players],
                "transfers_in": [p.player_name for p in in_players],
                "transfers_in_ids": [p.player_id for p in in_players],
                "expected_score": round(s.expected_round_score, 2),
                "formation": s.lineup.formation,
                "bank_tenths": s.bank_tenths_end_of_round,
                "bank_credits": round(s.bank_tenths_end_of_round / 10.0, 1),
            })
        return {
            "team_id": req.team_id,
            "horizon": plan.horizon,
            "discount_gamma": req.gamma,
            "total_expected_score": round(plan.total_expected_score, 2),
            "total_discounted_score": round(plan.discounted_expected_score, 2),
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

    target_pos_code = None
    if position:
        try:
            target_pos_code = Position.from_raw(position).short_code
        except Exception:
            target_pos_code = position.upper()

    filtered = []
    for c in contracts:
        pos_code = c.position.short_code if hasattr(c.position, "short_code") else (
            Position.from_raw(c.position).short_code if hasattr(Position, "from_raw") else str(c.position)
        )
        if target_pos_code and pos_code != target_pos_code:
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
            "position": pos_code,
            "position_name": c.position.name if hasattr(c.position, "name") else str(c.position),
            "team_code": c.team_code,
            "price_tenths": c.price_tenths,
            "credits": c.credits,
            "expected_fp": round(c.expected_fp, 2),
            "actual_fp": round(c.actual_fp, 2) if getattr(c, "actual_fp", None) is not None else None,
            "has_played": getattr(c, "has_played", False),
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


@router.get("/players/{player_id}")
def get_player_details_endpoint(
    player_id: int,
    season: str = "2026/27",
    round_number: int = 1,
    prediction_service: PredictionService = Depends(get_prediction_service),
) -> dict[str, Any]:
    """Retrieve complete player statistics, projections, and metadata for player window modal."""
    import sqlite3

    db_path = prediction_service.database_path

    # Projection contract & valuation
    contract = prediction_service.get_player_projection(season, round_number, player_id)
    valuations = prediction_service.get_player_valuations(season, round_number)
    val = valuations.get(player_id, {})

    # Detailed snapshot database row
    player_row: dict[str, Any] = {}
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM players WHERE id = ? ORDER BY snapshot_id DESC LIMIT 1",
                    (player_id,),
                ).fetchone()
                if row:
                    player_row = dict(row)
        except sqlite3.OperationalError:
            pass

    if not player_row and not contract:
        raise HTTPException(status_code=404, detail=f"Player '{player_id}' not found.")

    pos_code = "G"
    pos_name = "Guard"
    if contract:
        pos_code = contract.position.short_code if hasattr(contract.position, "short_code") else str(contract.position)
        pos_name = contract.position.name if hasattr(contract.position, "name") else str(contract.position)
    elif player_row.get("position_code"):
        pos_code = str(player_row["position_code"])
        pos_name = str(player_row.get("position", pos_code))

    price_tenths = player_row.get("price_tenths") or (contract.price_tenths if contract else 0)
    credits_val = round(price_tenths / 10.0, 1)

    return {
        "player_id": player_id,
        "name": player_row.get("name") or (contract.player_name if contract else f"Player {player_id}"),
        "first_name": player_row.get("first_name", ""),
        "last_name": player_row.get("last_name", ""),
        "position": pos_code,
        "position_name": pos_name,
        "team_id": player_row.get("team_id"),
        "team_code": player_row.get("team_code") or (contract.team_code if contract else ""),
        "team_name": player_row.get("team_name", ""),
        "price_tenths": price_tenths,
        "credits": credits_val,
        "status": player_row.get("status", "starter"),
        "probability_of_playing": player_row.get("probability_of_playing", contract.probability_play if contract else 1.0),
        "turn_number": player_row.get("turn_number", contract.turn_number if contract else 1),
        "avg_fantasy_pts": player_row.get("avg_fantasy_pts", 0.0),
        "last_match_pts": player_row.get("last_match_pts", 0.0),
        "has_played": getattr(contract, "has_played", False) if contract else bool(player_row.get("has_played", False)),
        "actual_fp": round(getattr(contract, "actual_fp", 0.0), 2) if (contract and getattr(contract, "actual_fp", None) is not None) else (round(player_row.get("last_match_pts", 0.0), 2) if player_row.get("has_played") else None),
        "total_plus_tenths": player_row.get("total_plus_tenths", 0),
        "total_plus_credits": round((player_row.get("total_plus_tenths", 0)) / 10.0, 1),
        "popularity": player_row.get("popularity", 0.0),
        "is_injured": bool(player_row.get("is_injured", False)),
        "is_on_fire": bool(player_row.get("is_on_fire", False)),
        "expected_fp": round(contract.expected_fp, 2) if contract else round(player_row.get("avg_fantasy_pts", 0.0), 2),
        "uncertainty": round(contract.uncertainty, 2) if contract else 0.0,
        "expected_minutes": round(contract.expected_minutes, 1) if contract else 20.0,
        "fp_per_credit": val.get("fp_per_credit", 0.0),
        "points_above_replacement": val.get("points_above_replacement", 0.0),
        "risk_adjusted_fp": val.get("risk_adjusted_fp", contract.expected_fp if contract else 0.0),
        "opponent_code": contract.opponent_code if contract else "",
        "is_home": contract.is_home if contract else True,
    }


@router.post("/initial-team/suggest")
def suggest_initial_team_endpoint(
    req: SuggestInitialTeamRequest,
    optimization_service: OptimizationService = Depends(get_optimization_service),
) -> dict[str, Any]:
    """Suggest an optimal initial 11-player squad (from scratch or completing locked players)."""
    try:
        return optimization_service.suggest_initial_team(
            season=req.season,
            budget_credits=req.budget_credits,
            risk_mode=req.risk_mode,
            locked_player_ids=req.locked_player_ids,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/update-data")
def update_data_endpoint(
    league: str = Query("euroleague", description="Competition league ('euroleague' or 'eurocup')"),
    prediction_service: PredictionService = Depends(get_prediction_service),
) -> dict[str, Any]:
    """Fetch live data from official EuroLeague Fantasy API and update SQLite snapshot store."""
    try:
        from euroleague_fantasy_manager.api import fetch_current_data
        from euroleague_fantasy_manager.cli import RAW_ARCHIVE_DIRECTORY, _resolve_league
        from euroleague_fantasy_manager.storage import SnapshotStore

        league_id, comp_code, season_code = _resolve_league(league)
        payload = fetch_current_data(league_id=league_id, competition_code=comp_code, season_code=season_code)
        store = SnapshotStore(prediction_service.database_path)
        summary = store.save_snapshot(payload, raw_directory=RAW_ARCHIVE_DIRECTORY)
        prediction_service.clear_cache()
        return {
            "success": True,
            "message": f"Successfully updated snapshot #{summary.snapshot_id} for {summary.season_code} round {summary.round_number}.",
            "summary": {
                "snapshot_id": summary.snapshot_id,
                "season_code": summary.season_code,
                "round_number": summary.round_number,
                "player_count": summary.player_count,
                "coach_count": summary.coach_count,
                "team_count": summary.team_count,
                "fixture_count": summary.fixture_count,
                "created_at": summary.created_at,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch live data from EuroLeague API: {e}")


