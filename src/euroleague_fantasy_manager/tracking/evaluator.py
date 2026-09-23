"""Closed-loop decision evaluation, retrospective regret, and longitudinal model drift monitoring."""

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import DecisionOutcome, DecisionRecord
from .store import DecisionStore


@dataclass(frozen=True, slots=True)
class ClosedLoopSummary:
    """Aggregated retrospective performance, regret breakdown, and drift diagnostics."""

    season: str
    team_id: str
    decisions_count: int
    outcomes_evaluated: int
    avg_human_score: float
    avg_recommended_score: float
    avg_oracle_score: float
    avg_human_regret: float
    avg_model_regret: float
    avg_human_vs_model: float
    human_win_rate: float
    human_loss_rate: float
    avg_captain_regret: float
    avg_sixth_man_regret: float
    avg_bench_regret: float
    avg_formation_regret: float
    avg_turn_sub_gain: float
    avg_transfer_gain: float
    overall_prediction_mae: float
    overall_prediction_rmse: float
    overall_prediction_bias: float
    rolling_mae_windows: dict[str, float] = field(default_factory=dict)
    segment_mae: dict[str, float] = field(default_factory=dict)
    round_details: list[dict[str, Any]] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Render a formatted Markdown audit report."""
        lines = [
            f"# V0.45 Closed-Loop Decision & Regret Report -- Season {self.season}",
            "",
            f"- **Team:** `{self.team_id}`",
            f"- **Decisions Logged:** {self.decisions_count}",
            f"- **Evaluated Outcomes:** {self.outcomes_evaluated}",
            "",
            "## 1. Score & Regret Attribution (Human vs Model vs Oracle)",
            f"- **Avg Human Realized Score:** {self.avg_human_score:.2f} FP",
            f"- **Avg Model Recommended Score:** {self.avg_recommended_score:.2f} FP",
            f"- **Avg Hindsight Oracle Score:** {self.avg_oracle_score:.2f} FP",
            f"- **Avg Human Regret (Oracle - Human):** {self.avg_human_regret:.2f} FP",
            f"- **Avg Model Regret (Oracle - Model):** {self.avg_model_regret:.2f} FP",
            f"- **Human vs Model Delta (Human - Model):** {self.avg_human_vs_model:+.2f} FP",
            f"- **Human Win Rate (Human > Model):** {self.human_win_rate:.1f}%",
            f"- **Model Win Rate (Model > Human):** {self.human_loss_rate:.1f}%",
            "",
            "## 2. Component Regret Analysis",
            f"- **Avg Captain Regret:** {self.avg_captain_regret:.2f} FP",
            f"- **Avg Sixth Man Regret:** {self.avg_sixth_man_regret:.2f} FP",
            f"- **Avg Bench Regret:** {self.avg_bench_regret:.2f} FP",
            f"- **Avg Formation Regret:** {self.avg_formation_regret:.2f} FP",
            f"- **Avg Turn Substitution Net Gain:** {self.avg_turn_sub_gain:+.2f} FP",
            f"- **Avg Realized Transfer Net Gain:** {self.avg_transfer_gain:+.2f} FP",
            "",
            "## 3. Retrospective Prediction Accuracy",
            f"- **Squad Prediction MAE:** {self.overall_prediction_mae:.2f} FP",
            f"- **Squad Prediction RMSE:** {self.overall_prediction_rmse:.2f} FP",
            f"- **Squad Prediction Bias:** {self.overall_prediction_bias:+.2f} FP",
        ]

        if self.rolling_mae_windows:
            lines.extend(["", "## 4. Longitudinal Model Drift (Rolling Windows)"])
            for window, val in sorted(self.rolling_mae_windows.items()):
                lines.append(f"- **{window.replace('_', ' ').title()}:** {val:.2f} MAE")

        if self.segment_mae:
            lines.extend(["", "## 5. Segment Drift (By Role / Position)"])
            for pos, val in sorted(self.segment_mae.items()):
                lines.append(f"- **Position {pos}:** {val:.2f} MAE")

        if self.round_details:
            lines.extend([
                "",
                "## 6. Round-by-Round Breakdown",
                "| Round | Decision Type | Override | Human Score | Rec Score | Oracle Score | Human Regret | Model Regret | Captain Regret | Pred MAE |",
                "|---|---|:---:|---|---|---|---|---|---|---|",
            ])
            for d in self.round_details:
                override_sym = "Yes" if d.get("is_override") else "No"
                lines.append(
                    f"| R{d['round_number']:02d} | `{d['decision_type']}` | {override_sym} | "
                    f"{d['human_score']:.1f} | {d['rec_score']:.1f} | {d['oracle_score']:.1f} | "
                    f"{d['human_regret']:.2f} | {d['model_regret']:.2f} | {d['captain_regret']:.2f} | {d['prediction_mae']:.2f} |"
                )

        return "\n".join(lines)


class ClosedLoopEvaluator:
    """Evaluates longitudinal closed-loop decision quality, regret, and model drift."""

    def __init__(self, store: DecisionStore | None = None, database_path: Path | str = "data/fantasy.db") -> None:
        self.store = store or DecisionStore(database_path)

    def evaluate_decisions(
        self,
        team_id: str | None = None,
        season: str | None = None,
        rolling_window: int = 5,
    ) -> ClosedLoopSummary:
        """Run comprehensive retrospective closed-loop evaluation across decisions and outcomes."""
        all_records = self.store.list_decisions(team_id=team_id, season=season)
        outcomes_data = self.store.list_outcomes(team_id=team_id, season=season)

        eff_season = season or (all_records[0].season if all_records else "2026")
        eff_team = team_id or (all_records[0].team_id if all_records else "default_team")

        if not outcomes_data:
            return ClosedLoopSummary(
                season=eff_season,
                team_id=eff_team,
                decisions_count=len(all_records),
                outcomes_evaluated=0,
                avg_human_score=0.0,
                avg_recommended_score=0.0,
                avg_oracle_score=0.0,
                avg_human_regret=0.0,
                avg_model_regret=0.0,
                avg_human_vs_model=0.0,
                human_win_rate=0.0,
                human_loss_rate=0.0,
                avg_captain_regret=0.0,
                avg_sixth_man_regret=0.0,
                avg_bench_regret=0.0,
                avg_formation_regret=0.0,
                avg_turn_sub_gain=0.0,
                avg_transfer_gain=0.0,
                overall_prediction_mae=0.0,
                overall_prediction_rmse=0.0,
                overall_prediction_bias=0.0,
            )

        n = len(outcomes_data)
        human_scores = [out.human_actual_score for _, out in outcomes_data]
        rec_scores = [out.recommended_actual_score for _, out in outcomes_data]
        oracle_scores = [out.oracle_actual_score for _, out in outcomes_data]
        human_regrets = [out.human_regret for _, out in outcomes_data]
        model_regrets = [out.model_regret for _, out in outcomes_data]
        human_vs_models = [out.human_vs_model for _, out in outcomes_data]

        captain_regrets = [out.captain_regret for _, out in outcomes_data]
        sixth_man_regrets = [out.sixth_man_regret for _, out in outcomes_data]
        bench_regrets = [out.bench_regret for _, out in outcomes_data]
        formation_regrets = [out.formation_regret for _, out in outcomes_data]

        turn_sub_gains = [out.turn_sub_regret for _, out in outcomes_data if out.turn_sub_regret is not None]
        tx_gains = [out.transfer_regret for _, out in outcomes_data if out.transfer_regret is not None]

        maes = [out.prediction_mae for _, out in outcomes_data]
        rmses = [out.prediction_rmse for _, out in outcomes_data]
        biases = [out.prediction_bias for _, out in outcomes_data]

        # Win/Loss rate of human vs model
        human_wins = sum(1 for h, m in zip(human_scores, rec_scores) if h > m)
        model_wins = sum(1 for h, m in zip(human_scores, rec_scores) if m > h)
        human_win_rate = round((human_wins / n) * 100.0, 1)
        human_loss_rate = round((model_wins / n) * 100.0, 1)

        # Rolling MAE Windows
        rolling_windows: dict[str, float] = {}
        for w in (3, 5, 10):
            if n >= w:
                recent_maes = maes[-w:]
                rolling_windows[f"last_{w}_rounds"] = round(sum(recent_maes) / len(recent_maes), 2)
            else:
                rolling_windows[f"last_{w}_rounds"] = round(sum(maes) / len(maes), 2)

        # Position Segment MAE
        pos_errors: dict[str, list[float]] = {"G": [], "F": [], "C": [], "HC": []}
        for dec, out in outcomes_data:
            if dec.actual_lineup:
                for pid, pred_fp in dec.actual_lineup.projected_scores.items():
                    act_fp = out.actuals_by_player.get(pid)
                    if act_fp is not None:
                        err = abs(act_fp - pred_fp)
                        if pid == dec.actual_lineup.head_coach_id:
                            pos_errors["HC"].append(err)
                        elif pid in (301, 302, 701, 702):
                            pos_errors["C"].append(err)
                        elif pid in (201, 202, 203, 204, 601, 602):
                            pos_errors["F"].append(err)
                        else:
                            pos_errors["G"].append(err)

        segment_mae = {
            pos: round(sum(errs) / len(errs), 2)
            for pos, errs in pos_errors.items()
            if errs
        }

        # Detailed round breakdown
        round_details: list[dict[str, Any]] = []
        for dec, out in outcomes_data:
            round_details.append({
                "round_number": dec.round_number,
                "turn_number": dec.turn_number,
                "decision_id": dec.decision_id,
                "decision_type": dec.decision_type.value,
                "is_override": dec.is_override,
                "human_score": out.human_actual_score,
                "rec_score": out.recommended_actual_score,
                "oracle_score": out.oracle_actual_score,
                "human_regret": out.human_regret,
                "model_regret": out.model_regret,
                "captain_regret": out.captain_regret,
                "prediction_mae": out.prediction_mae,
            })

        return ClosedLoopSummary(
            season=eff_season,
            team_id=eff_team,
            decisions_count=len(all_records),
            outcomes_evaluated=n,
            avg_human_score=round(sum(human_scores) / n, 2),
            avg_recommended_score=round(sum(rec_scores) / n, 2),
            avg_oracle_score=round(sum(oracle_scores) / n, 2),
            avg_human_regret=round(sum(human_regrets) / n, 2),
            avg_model_regret=round(sum(model_regrets) / n, 2),
            avg_human_vs_model=round(sum(human_vs_models) / n, 2),
            human_win_rate=human_win_rate,
            human_loss_rate=human_loss_rate,
            avg_captain_regret=round(sum(captain_regrets) / n, 2),
            avg_sixth_man_regret=round(sum(sixth_man_regrets) / n, 2),
            avg_bench_regret=round(sum(bench_regrets) / n, 2),
            avg_formation_regret=round(sum(formation_regrets) / n, 2),
            avg_turn_sub_gain=round(sum(turn_sub_gains) / len(turn_sub_gains), 2) if turn_sub_gains else 0.0,
            avg_transfer_gain=round(sum(tx_gains) / len(tx_gains), 2) if tx_gains else 0.0,
            overall_prediction_mae=round(sum(maes) / n, 2),
            overall_prediction_rmse=round(sum(rmses) / n, 2),
            overall_prediction_bias=round(sum(biases) / n, 2),
            rolling_mae_windows=rolling_windows,
            segment_mae=segment_mae,
            round_details=round_details,
        )
