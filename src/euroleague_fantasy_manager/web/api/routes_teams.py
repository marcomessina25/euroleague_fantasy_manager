"""Team management REST endpoints for the local workstation."""

from __future__ import annotations

import re
import time
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.multi_team.models import TeamRosterUnit, TeamSettings
from euroleague_fantasy_manager.optimization.constraints import (
    OptimizationConstraints,
    PlayerProjectionContract,
    validate_squad_constraints,
)
from euroleague_fantasy_manager.services.decision_service import DecisionService
from euroleague_fantasy_manager.services.optimization_service import OptimizationService
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.web.deps import (
    get_decision_service,
    get_optimization_service,
    get_prediction_service,
    get_team_service,
)

router = APIRouter(prefix="/api/teams", tags=["teams"])


class CreateTeamRequest(BaseModel):
    team_id: str | None = None
    name: str
    mode: str = "classic"
    season: str = "2026/27"
    round_number: int = 1
    turn_number: int = 1
    bank_tenths: int | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    player_ids: list[int] = Field(default_factory=list)
    recommended_player_ids: list[int] = Field(default_factory=list)


class UpdateTeamRequest(BaseModel):
    name: str | None = None
    round_number: int | None = None
    turn_number: int | None = None
    bank_tenths: int | None = None
    transfers_remaining: int | None = None
    settings: dict[str, Any] | None = None


class UpdateLineupRequest(BaseModel):
    starter_ids: list[int]
    captain_id: int
    sixth_man_id: int
    bench_ids: list[int]
    coach_id: int


@router.get("")
def list_teams(service: TeamService = Depends(get_team_service)) -> list[dict[str, Any]]:
    teams = service.list_teams()
    return [t.to_dict() for t in teams]


@router.post("")
def create_team(
    req: CreateTeamRequest,
    service: TeamService = Depends(get_team_service),
    prediction_service: PredictionService = Depends(get_prediction_service),
    optimization_service: OptimizationService = Depends(get_optimization_service),
    decision_service: DecisionService = Depends(get_decision_service),
) -> dict[str, Any]:
    try:
        # Generate clean team_id if not provided
        tid = req.team_id
        if not tid:
            clean = re.sub(r"[^a-zA-Z0-9_]", "", req.name.strip().lower().replace(" ", "_"))[:16]
            tid = f"team_{clean or 'squad'}_{int(time.time())}"

        squad_units: list[TeamRosterUnit] = []
        contracts: list[PlayerProjectionContract] = []
        bank_tenths = req.bank_tenths if req.bank_tenths is not None else 1000

        if req.player_ids:
            proj_dict = prediction_service.get_projections_dict(req.season, req.round_number)
            contracts = [proj_dict[pid] for pid in req.player_ids if pid in proj_dict]

            # Validate squad
            val = validate_squad_constraints(contracts, budget_tenths=1000)
            if not val.is_valid:
                raise HTTPException(status_code=400, detail=f"Invalid squad: {'; '.join(val.errors)}")

            # Optimize lineup assignment (starters, captain, 6th man, bench, coach)
            lineup = optimization_service.lineup_optimizer.optimize(contracts, round_number=req.round_number)

            starter_set = set(lineup.starter_ids)
            bench_set = set(lineup.bench_ids)

            for c in contracts:
                pos_str = c.position.name if hasattr(c.position, "name") else str(c.position)
                pid = c.player_id
                squad_units.append(
                    TeamRosterUnit(
                        player_id=pid,
                        position=pos_str,
                        name=c.player_name,
                        team_code=c.team_code,
                        purchase_price_tenths=c.price_tenths,
                        current_price_tenths=c.price_tenths,
                        is_starter=(pid in starter_set),
                        is_captain=(pid == lineup.captain_id),
                        is_sixth_man=(pid == lineup.sixth_man_id),
                        is_bench=(pid in bench_set),
                        is_coach=(pid == lineup.head_coach_id),
                        turn_number=c.turn_number,
                    )
                )

            spent_tenths = sum(c.price_tenths for c in contracts)
            if req.bank_tenths is None:
                bank_tenths = max(0, 1000 - spent_tenths)

        team = service.create_team(
            team_id=tid,
            name=req.name,
            mode=req.mode,
            season=req.season,
            round_number=req.round_number,
            turn_number=req.turn_number,
            bank_tenths=bank_tenths,
            settings=req.settings,
            squad=squad_units,
        )

        # Log initial team creation decision if squad was selected
        if contracts:
            try:
                rec_ids = req.recommended_player_ids or req.player_ids
                decision_service.log_initial_team(
                    team_id=tid,
                    season=req.season,
                    recommended_squad_ids=rec_ids,
                    actual_squad_ids=req.player_ids,
                    notes=f"Initial team draft: {req.name}",
                    squad_contracts=contracts,
                )
            except Exception:
                pass

        # Switch active team to new team
        service.set_active_team(tid)

        return team.to_dict()
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{team_id}")
def get_team(team_id: str, service: TeamService = Depends(get_team_service)) -> dict[str, Any]:
    try:
        team = service.get_team(team_id)
        return team.to_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found.")


@router.put("/{team_id}")
def update_team(team_id: str, req: UpdateTeamRequest, service: TeamService = Depends(get_team_service)) -> dict[str, Any]:
    try:
        team = service.update_team(
            team_id=team_id,
            name=req.name,
            round_number=req.round_number,
            turn_number=req.turn_number,
            bank_tenths=req.bank_tenths,
            transfers_remaining=req.transfers_remaining,
            settings=req.settings,
        )
        return team.to_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found.")


@router.delete("/{team_id}")
def delete_team(team_id: str, service: TeamService = Depends(get_team_service)) -> dict[str, bool]:
    success = service.delete_team(team_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found.")
    return {"success": True}


@router.post("/{team_id}/active")
def set_active_team(team_id: str, service: TeamService = Depends(get_team_service)) -> dict[str, bool]:
    try:
        service.set_active_team(team_id)
        return {"success": True}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found.")


@router.post("/{team_id}/lineup")
def update_lineup(team_id: str, req: UpdateLineupRequest, service: TeamService = Depends(get_team_service)) -> dict[str, Any]:
    try:
        team = service.update_lineup(
            team_id=team_id,
            starter_ids=req.starter_ids,
            captain_id=req.captain_id,
            sixth_man_id=req.sixth_man_id,
            bench_ids=req.bench_ids,
            coach_id=req.coach_id,
        )
        return team.to_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
