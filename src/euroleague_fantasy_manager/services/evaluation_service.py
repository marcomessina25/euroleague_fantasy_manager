"""Application service for evaluation hub, regret analysis, and model drift reporting."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from euroleague_fantasy_manager.tracking.evaluator import (
    ClosedLoopEvaluator,
    ClosedLoopSummary,
)
from euroleague_fantasy_manager.tracking.models import DecisionOutcome
from euroleague_fantasy_manager.tracking.outcomes import OutcomeUpdater
from euroleague_fantasy_manager.tracking.reports import export_closed_loop_csv
from euroleague_fantasy_manager.tracking.store import DecisionStore


class EvaluationService:
    """Orchestrates retrospective scoring, regret analysis, and longitudinal evaluation."""

    def __init__(self, store: DecisionStore | None = None, db_path: str | Path = "data/euroleague.sqlite3") -> None:
        self.store = store or DecisionStore(database_path=db_path)
        self.outcome_updater = OutcomeUpdater(store=self.store)
        self.evaluator = ClosedLoopEvaluator(store=self.store)

    def update_scores(
        self,
        team_id: str,
        season: str,
        round_number: int,
        actual_scores: Mapping[int, float] | None = None,
    ) -> list[DecisionOutcome]:
        """Ingest realized fantasy scores and calculate component regrets."""
        decisions = self.store.list_decisions(team_id=team_id, season=season, round_number=round_number)
        outcomes: list[DecisionOutcome] = []
        for dec in decisions:
            outcome = self.outcome_updater.update_decision_outcomes(
                decision_id=dec.decision_id,
                actual_scores=actual_scores or {},
            )
            outcomes.append(outcome)
        return outcomes

    def get_summary(
        self,
        team_id: str,
        season: str,
        window: int = 5,
    ) -> ClosedLoopSummary:
        """Compute longitudinal summary, win rates, rolling MAE windows, and segment errors."""
        return self.evaluator.evaluate_team_season(
            team_id=team_id,
            season=season,
            window=window,
        )

    def get_round_history(
        self,
        team_id: str,
        season: str,
    ) -> list[dict[str, Any]]:
        """Retrieve historical decisions with projected vs actual score and regrets."""
        decisions = self.store.list_decisions(team_id=team_id, season=season)
        history: list[dict[str, Any]] = []

        for dec in decisions:
            outcome = self.store.get_outcome(dec.decision_id)
            history.append({
                "decision_id": dec.decision_id,
                "round_number": dec.round_number,
                "turn_number": dec.turn_number,
                "decision_type": dec.decision_type.value,
                "is_override": dec.is_override,
                "status": outcome.outcome_status.value if outcome else "PENDING",
                "recommended_score": outcome.recommended_actual_score if outcome else None,
                "actual_score": outcome.human_actual_score if outcome else None,
                "oracle_score": outcome.oracle_actual_score if outcome else None,
                "human_regret": outcome.human_regret if outcome else None,
                "model_regret": outcome.model_regret if outcome else None,
                "captain_regret": outcome.captain_regret if outcome else None,
                "sixth_man_regret": outcome.sixth_man_regret if outcome else None,
                "bench_regret": outcome.bench_regret if outcome else None,
                "formation_regret": outcome.formation_regret if outcome else None,
                "turn_sub_regret": outcome.turn_sub_regret if outcome else None,
                "prediction_mae": outcome.prediction_mae if outcome else None,
            })

        return sorted(history, key=lambda x: (x["round_number"], x["turn_number"]))

    def export_csv(
        self,
        team_id: str,
        season: str,
        target_path: str | Path,
        window: int = 5,
    ) -> None:
        """Export evaluation summary to CSV file."""
        summary = self.get_summary(team_id=team_id, season=season, window=window)
        export_closed_loop_csv(summary=summary, target_path=target_path)
