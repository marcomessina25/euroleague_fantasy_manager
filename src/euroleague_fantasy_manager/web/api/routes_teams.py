"""Team management REST endpoints for the local workstation."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from euroleague_fantasy_manager.multi_team.models import TeamRosterUnit, TeamSettings
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.web.deps import get_team_service

router = APIRouter(prefix="/api/teams", tags=["teams"])


class CreateTeamRequest(BaseModel):
    team_id: str
    name: str
    mode: str = "classic"
    season: str = "2026/27"
    round_number: int = 1
    turn_number: int = 1
    bank_tenths: int = 0
    settings: dict[str, Any] = Field(default_factory=dict)


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
def create_team(req: CreateTeamRequest, service: TeamService = Depends(get_team_service)) -> dict[str, Any]:
    try:
        team = service.create_team(
            team_id=req.team_id,
            name=req.name,
            mode=req.mode,
            season=req.season,
            round_number=req.round_number,
            turn_number=req.turn_number,
            bank_tenths=req.bank_tenths,
            settings=req.settings,
        )
        return team.to_dict()
    except ValueError as e:
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
