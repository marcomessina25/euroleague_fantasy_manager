"""FastAPI dependency providers for application services."""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, HTTPException, Query, Request

from euroleague_fantasy_manager.competition.ruleset import League
from euroleague_fantasy_manager.services.decision_service import DecisionService
from euroleague_fantasy_manager.services.evaluation_service import EvaluationService
from euroleague_fantasy_manager.services.optimization_service import OptimizationService
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.services.scenario_service import ScenarioService
from euroleague_fantasy_manager.services.team_service import TeamService


def get_db_path(request: Request) -> Path:
    return Path(request.app.state.db_path)


def get_team_service(request: Request) -> TeamService:
    return request.app.state.team_service


def get_prediction_service(request: Request) -> PredictionService:
    return request.app.state.prediction_service


def get_decision_service(request: Request) -> DecisionService:
    return request.app.state.decision_service


def get_evaluation_service(request: Request) -> EvaluationService:
    return request.app.state.evaluation_service


def get_optimization_service(
    request: Request,
    team_service: TeamService = Depends(get_team_service),
    prediction_service: PredictionService = Depends(get_prediction_service),
) -> OptimizationService:
    if (
        hasattr(request.app.state, "optimization_service")
        and team_service is request.app.state.team_service
        and prediction_service is request.app.state.prediction_service
    ):
        return request.app.state.optimization_service
    return OptimizationService(team_service=team_service, prediction_service=prediction_service)


def get_scenario_service(
    request: Request,
    team_service: TeamService = Depends(get_team_service),
    prediction_service: PredictionService = Depends(get_prediction_service),
    optimization_service: OptimizationService = Depends(get_optimization_service),
) -> ScenarioService:
    if (
        hasattr(request.app.state, "scenario_service")
        and team_service is request.app.state.team_service
        and prediction_service is request.app.state.prediction_service
        and optimization_service is request.app.state.optimization_service
    ):
        return request.app.state.scenario_service
    return ScenarioService(
        team_service=team_service,
        prediction_service=prediction_service,
        optimization_service=optimization_service,
    )


def parse_league(league: str = Query("euroleague", description="Competition league: 'euroleague' or 'eurocup'.")) -> League:
    """Validate and normalize competition league query parameter. Raises HTTP 400 on unrecognized values."""
    try:
        return League.from_str(league)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
