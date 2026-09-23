"""FastAPI dependency providers for application services."""

from __future__ import annotations

from pathlib import Path

from euroleague_fantasy_manager.multi_team.store import TeamStore
from euroleague_fantasy_manager.services.decision_service import DecisionService
from euroleague_fantasy_manager.services.evaluation_service import EvaluationService
from euroleague_fantasy_manager.services.optimization_service import OptimizationService
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.services.scenario_service import ScenarioService
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.tracking.store import DecisionStore

_db_path: str = "data/euroleague.sqlite3"


def set_db_path(path: str | Path) -> None:
    global _db_path
    _db_path = str(path)


def get_db_path() -> str:
    return _db_path


def get_team_service() -> TeamService:
    store = TeamStore(db_path=_db_path)
    return TeamService(store=store)


def get_prediction_service() -> PredictionService:
    return PredictionService(database_path=_db_path)


from fastapi import Depends


def get_optimization_service(
    team_service: TeamService = Depends(get_team_service),
    prediction_service: PredictionService = Depends(get_prediction_service),
) -> OptimizationService:
    return OptimizationService(team_service=team_service, prediction_service=prediction_service)


def get_decision_service() -> DecisionService:
    ds = DecisionStore(database_path=_db_path)
    return DecisionService(store=ds)


def get_scenario_service(
    team_service: TeamService = Depends(get_team_service),
    prediction_service: PredictionService = Depends(get_prediction_service),
    optimization_service: OptimizationService = Depends(get_optimization_service),
) -> ScenarioService:
    return ScenarioService(team_service=team_service, prediction_service=prediction_service, optimization_service=optimization_service)


def get_evaluation_service() -> EvaluationService:
    ds = DecisionStore(database_path=_db_path)
    return EvaluationService(store=ds)
