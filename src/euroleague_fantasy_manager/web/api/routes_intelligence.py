"""Workstation API endpoints for V0.6 Strategic Intelligence & LLM Copilot."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from euroleague_fantasy_manager.intelligence.copilot import (
    CopilotAdviceResult,
    generate_copilot_advice,
)
from euroleague_fantasy_manager.intelligence.dossier import (
    ManagerDossier,
    generate_manager_dossier,
)
from euroleague_fantasy_manager.intelligence.providers import list_available_providers
from euroleague_fantasy_manager.intelligence.strategic_analysis import (
    StrategicAnalysisResult,
    analyze_dossier,
)
from euroleague_fantasy_manager.services.optimization_service import OptimizationService
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.web.deps import (
    get_optimization_service,
    get_prediction_service,
    get_team_service,
)

router = APIRouter(prefix="/api/workstation", tags=["intelligence"])


class CopilotAdviseRequest(BaseModel):
    team_id: str
    season: str = "2026/27"
    round_number: int | None = None
    persona: str = "briefing"
    provider: str = "heuristic"
    tier: str = "standard"
    model: str | None = None
    api_key: str | None = None


@router.get("/dossier")
def get_manager_dossier_endpoint(
    team_id: str = Query(..., description="Target managed team ID"),
    season: str = Query("2026/27", description="Season code"),
    round_number: int | None = Query(None, description="Round number"),
    team_service: TeamService = Depends(get_team_service),
    prediction_service: PredictionService = Depends(get_prediction_service),
    optimization_service: OptimizationService = Depends(get_optimization_service),
) -> dict[str, Any]:
    """Generate and return a deterministic Manager Dossier for the active team squad."""
    try:
        dossier = generate_manager_dossier(
            team_id=team_id,
            season=season,
            round_number=round_number,
            team_service=team_service,
            prediction_service=prediction_service,
            optimization_service=optimization_service,
        )
        return dossier.to_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating manager dossier: {e}")


@router.get("/strategic-analysis")
def get_strategic_analysis_endpoint(
    team_id: str = Query(..., description="Target managed team ID"),
    season: str = Query("2026/27", description="Season code"),
    round_number: int | None = Query(None, description="Round number"),
    team_service: TeamService = Depends(get_team_service),
    prediction_service: PredictionService = Depends(get_prediction_service),
    optimization_service: OptimizationService = Depends(get_optimization_service),
) -> dict[str, Any]:
    """Run deterministic strategic analysis (Assumptions, Sensitivities, Devil's Advocate) without LLM."""
    try:
        dossier = generate_manager_dossier(
            team_id=team_id,
            season=season,
            round_number=round_number,
            team_service=team_service,
            prediction_service=prediction_service,
            optimization_service=optimization_service,
        )
        strat = analyze_dossier(dossier)
        return strat.to_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error running strategic analysis: {e}")


@router.post("/copilot/advise")
def copilot_advise_endpoint(
    req: CopilotAdviseRequest,
    team_service: TeamService = Depends(get_team_service),
    prediction_service: PredictionService = Depends(get_prediction_service),
    optimization_service: OptimizationService = Depends(get_optimization_service),
) -> dict[str, Any]:
    """Request copilot narrative advice grounded in the deterministic Manager Dossier.

    Guarantees zero persistent state mutation. Falls back gracefully to heuristic analysis on provider failure.
    """
    try:
        dossier = generate_manager_dossier(
            team_id=req.team_id,
            season=req.season,
            round_number=req.round_number,
            team_service=team_service,
            prediction_service=prediction_service,
            optimization_service=optimization_service,
        )
        advice = generate_copilot_advice(
            dossier=dossier,
            persona=req.persona,
            provider_name=req.provider,
            api_key=req.api_key,
            model=req.model,
            database_path=prediction_service.database_path,
        )
        return advice.to_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Team '{req.team_id}' not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Copilot advice error: {e}")


@router.get("/copilot/providers")
def get_available_providers_endpoint() -> list[dict[str, Any]]:
    """List available LLM providers and configuration status."""
    return list_available_providers()
