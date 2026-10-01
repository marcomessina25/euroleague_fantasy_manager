"""Team management REST endpoints for the local workstation."""

from __future__ import annotations

import re
import time
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from euroleague_fantasy_manager.competition.ruleset import League
from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.multi_team.models import TeamRosterUnit, TeamSettings
from euroleague_fantasy_manager.rules import MAX_TRADES_PER_ROUND
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
    league: str = "euroleague"
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
    # Omitted means "the team's live round", preserving pre-V0.7 behaviour.
    round_number: int | None = None


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
        league = League.from_str(req.league).value

        # Generate clean team_id if not provided
        tid = req.team_id
        if not tid:
            clean = re.sub(r"[^a-zA-Z0-9_]", "", req.name.strip().lower().replace(" ", "_"))[:16]
            tid = f"team_{clean or 'squad'}_{int(time.time())}"

        squad_units: list[TeamRosterUnit] = []
        contracts: list[PlayerProjectionContract] = []
        bank_tenths = req.bank_tenths if req.bank_tenths is not None else 1000

        if req.player_ids:
            proj_dict = prediction_service.get_projections_dict(req.season, req.round_number, league=league)
            missing = [pid for pid in req.player_ids if pid not in proj_dict]
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Player IDs {missing} do not belong to the selected league '{league}' player pool.",
                )
            contracts = [proj_dict[pid] for pid in req.player_ids]

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
            league=league,
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
            except Exception as e:
                # Transactional rollback: team must not exist if audit record fails
                try:
                    service.delete_team(tid)
                except Exception:
                    pass
                raise HTTPException(
                    status_code=500,
                    detail=f"Required initial-team decision audit log failed: {e}",
                )

        # Switch active team to new team
        service.set_active_team(tid)

        return team.to_dict()
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{team_id}")
def get_team(team_id: str, service: TeamService = Depends(get_team_service)) -> dict[str, Any]:
    try:
        team = service.get_team(team_id)
        return team.to_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found.")


@router.put("/{team_id}")
@router.patch("/{team_id}")
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


@router.get("/{team_id}/rounds")
def list_team_rounds(team_id: str, service: TeamService = Depends(get_team_service)) -> dict[str, Any]:
    """Rounds this team has stored state for, backing the Lineup tab selector."""
    try:
        team = service.get_team(team_id)
        return {
            "team_id": team_id,
            "season": team.season,
            "current_round": team.round_number,
            "rounds": service.get_rounds_with_state(team_id),
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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
            round_number=req.round_number,
        )
        return team.to_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class ExecuteTransfersRequest(BaseModel):
    transfers_out_ids: list[int]
    transfers_in_ids: list[int]
    unlimited: bool = False
    season: str = "2026/27"
    # Entering trades for a PAST round is deliberately not supported yet: it
    # requires per-round financial state to propagate into every later round,
    # which is the point-in-time reconstruction built in V0.7 W6. Accepting the
    # field and rejecting it is clearer than silently applying the trades to the
    # live round. See docs/specs/v07.md.
    round_number: int | None = None


@router.post("/{team_id}/transfers")
def execute_transfers(
    team_id: str,
    req: ExecuteTransfersRequest,
    service: TeamService = Depends(get_team_service),
    prediction_service: PredictionService = Depends(get_prediction_service),
    optimization_service: OptimizationService = Depends(get_optimization_service),
    decision_service: DecisionService = Depends(get_decision_service),
) -> dict[str, Any]:
    """Execute one or more transfers (or unlimited overhaul) for a team's live or past round."""
    try:
        team = service.get_team(team_id)
        target_round = req.round_number if req.round_number is not None else team.round_number

        # Resolve projection contracts for market
        proj_dict = prediction_service.get_projections_dict(req.season, target_round, league=team.league or "euroleague")

        # Snapshot state before transfers for audit rollback
        prev_team = service.get_team(team_id)
        prev_bank_tenths = prev_team.bank_tenths
        prev_transfers_remaining = prev_team.transfers_remaining
        prev_squad = list(service.store.get_squad(team_id, target_round))

        res = service.execute_transfers(
            team_id=team_id,
            transfers_out_ids=req.transfers_out_ids,
            transfers_in_ids=req.transfers_in_ids,
            round_number=target_round,
            season=req.season,
            unlimited=req.unlimited,
            market_projections=proj_dict,
            lineup_optimizer=optimization_service.lineup_optimizer,
        )

        # Log decision audit
        try:
            from euroleague_fantasy_manager.tracking.models import TransferPayload
            payload = TransferPayload(
                out_player_ids=tuple(res["out_ids"]),
                in_player_ids=tuple(res["in_ids"]),
                num_trades=len(res["in_ids"]),
                net_transfer_value=0.0,
                bank_tenths_before=res["base_bank_tenths"],
                bank_tenths_after=res["new_bank_tenths"],
            )
            decision_service.log_transfers(
                team_id=team_id,
                season=req.season,
                round_number=target_round,
                recommended_transfers=payload,
                actual_transfers=payload,
                notes=f"Executed {len(res['out_ids'])} trade(s)" if not req.unlimited else "Executed Unlimited Overhaul",
            )
        except Exception as e:
            # Transactional rollback: revert squad and state if decision log fails
            if target_round == prev_team.round_number:
                service.update_team(
                    team_id=team_id,
                    bank_tenths=prev_bank_tenths,
                    transfers_remaining=prev_transfers_remaining,
                )
            service.set_squad(team_id, target_round, prev_squad, validate=False)
            service.store.delete_transfers_by_ids(res["new_transfer_ids"])
            if target_round < prev_team.round_number:
                service.replay_transfers_forward(team_id, from_round=target_round, season=req.season)
            raise HTTPException(
                status_code=500,
                detail=f"Required transfer decision audit log failed: {e}",
            )

        return service.get_team(team_id).to_dict()
    except HTTPException:
        raise
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RevertRoundStartRequest(BaseModel):
    season: str = "2026/27"
    round_number: int | None = None


@router.post("/{team_id}/revert-round-start")
def revert_round_start(
    team_id: str,
    req: RevertRoundStartRequest | None = None,
    service: TeamService = Depends(get_team_service),
    decision_service: DecisionService = Depends(get_decision_service),
) -> dict[str, Any]:
    """Revert team transfers, substitutions, and budget back to the round start baseline."""
    try:
        season = req.season if req else "2026/27"
        rnd = req.round_number if req else None
        restored_team = service.revert_to_round_start(team_id=team_id, season=season, round_number=rnd)

        # Log decision event
        try:
            from euroleague_fantasy_manager.tracking.models import LineupPayload
            l_payload = LineupPayload(
                formation="2-2-1",
                starter_ids=tuple(u.player_id for u in restored_team.squad if u.is_starter),
                captain_id=restored_team.captain_id or 0,
                sixth_man_id=restored_team.sixth_man_id or 0,
                bench_ids=tuple(u.player_id for u in restored_team.squad if u.is_bench),
                head_coach_id=restored_team.coach_id or 0,
            )
            decision_service.log_lineup(
                team_id=team_id,
                season=season,
                round_number=restored_team.round_number,
                turn_number=restored_team.turn_number,
                recommended_lineup=l_payload,
                actual_lineup=l_payload,
                notes=f"Reverted team state to Round {restored_team.round_number} start baseline",
            )
        except Exception:
            pass

        return {
            "success": True,
            "message": f"Successfully reverted team to Round {restored_team.round_number} start baseline.",
            "team": restored_team.to_dict(),
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

