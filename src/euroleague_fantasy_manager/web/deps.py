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


def get_optimization_service() -> OptimizationService:
    ts = get_team_service()
    ps = get_prediction_service()
    return OptimizationService(team_service=ts, prediction_service=ps)


def get_decision_service() -> DecisionService:
    ds = DecisionStore(database_path=_db_path)
    return DecisionService(store=ds)


def get_scenario_service() -> ScenarioService:
    ts = get_team_service()
    ps = get_prediction_service()
    opt = get_optimization_service()
    return ScenarioService(team_service=ts, prediction_service=ps, optimization_service=opt)


def get_evaluation_service() -> EvaluationService:
    ds = DecisionStore(database_path=_db_path)
    return EvaluationService(store=ds)
