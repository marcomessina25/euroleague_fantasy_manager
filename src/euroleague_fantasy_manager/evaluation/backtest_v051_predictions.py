"""Backtest validation script comparing V0.5.0 vs V0.5.1 prediction models.

Validates the decomposed prediction model:
    E[FP] = P(play) * E[min] * E[FP/min] * location_multiplier
against the legacy V0.5.0 naive cost prior:
    E[FP] = price_tenths / 10.0

Metrics:
    - xP MAE (expected vs realized fantasy points)
    - xP RMSE
    - xM MAE (expected vs realized minutes)
    - Spearman rank correlation (predictive ranking consistency)
    - Empirical confidence interval calibration
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import sqlite3
from typing import Sequence

from ..fixtures import DATABASE_PATH
from ..models import Position
from .metrics import spearman_correlation


@dataclass(frozen=True, slots=True)
class PositionMetrics:
    position: str
    samples: int
    v050_mae: float
    v051_mae: float
    v050_spearman: float
    v051_spearman: float
    v051_xm_mae: float


@dataclass(frozen=True, slots=True)
class PredictionBacktestResult:
    total_samples: int
    v050_mae: float
    v051_mae: float
    v050_rmse: float
    v051_rmse: float
    v050_spearman: float
    v051_spearman: float
    v051_xm_mae: float
    ci_1sigma_coverage: float
    ci_90_coverage: float
    by_position: dict[str, PositionMetrics]
    passed_regression_gate: bool

    def summary_markdown(self) -> str:
        gate_status = "PASSED" if self.passed_regression_gate else "FAILED"
        mae_delta = self.v051_mae - self.v050_mae
        mae_pct = (mae_delta / self.v050_mae) * 100.0

        lines = [
            "# V0.5.1 vs V0.5.0 Prediction Model Backtest Validation",
            "",
            f"**Status:** {gate_status}",
            f"**Samples Evaluated:** {self.total_samples:,}",
            "",
            "## Overall Metric Comparison",
            "",
            "| Metric | V0.5.0 (Baseline Prior) | V0.5.1 (Decomposed) | Delta | Improvement |",
            "| :--- | :--- | :--- | :--- | :--- |",
            f"| **xP MAE** | {self.v050_mae:.3f} FP | {self.v051_mae:.3f} FP | {mae_delta:+.3f} FP | {-mae_pct:.1f}% error reduction |",
            f"| **xP RMSE** | {self.v050_rmse:.3f} | {self.v051_rmse:.3f} | {self.v051_rmse - self.v050_rmse:+.3f} | - |",
            f"| **Spearman Rank Corr** | {self.v050_spearman:.4f} | {self.v051_spearman:.4f} | {self.v051_spearman - self.v050_spearman:+.4f} | higher ranking fidelity |",
            f"| **xM MAE** | N/A | {self.v051_xm_mae:.2f} min | - | minutes projection error |",
            f"| **1-sigma CI Coverage** | N/A | {self.ci_1sigma_coverage * 100:.1f}% | - | expected: ~68.3% |",
            f"| **90% CI Coverage** | N/A | {self.ci_90_coverage * 100:.1f}% | - | expected: ~90.0% |",
            "",
            "## By Position Breakdown",
            "",
            "| Position | Samples | V0.5.0 MAE | V0.5.1 MAE | V0.5.0 Spearman | V0.5.1 Spearman | xM MAE |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for pos, pm in sorted(self.by_position.items()):
            lines.append(
                f"| {pos} | {pm.samples} | {pm.v050_mae:.3f} | {pm.v051_mae:.3f} | {pm.v050_spearman:.4f} | {pm.v051_spearman:.4f} | {pm.v051_xm_mae:.2f} |"
            )

        lines.extend([
            "",
            "## Regression Gate Verification",
            f"- **Requirement:** MAE(V0.5.1) <= MAE(V0.5.0) + 0.05",
            f"- **Realized:** {self.v051_mae:.3f} <= {self.v050_mae + 0.05:.3f} -> **{gate_status}**",
        ])
        return "\n".join(lines)


def run_v051_prediction_backtest(
    database_path: Path | str | None = None,
    seasons: Sequence[str] | None = None,
) -> PredictionBacktestResult:
    """Run historical backtest comparing V0.5.0 vs V0.5.1 predictions."""
    db_file = Path(database_path or DATABASE_PATH)
    if not db_file.exists():
        raise FileNotFoundError(f"Database file not found: {db_file}")

    conn = sqlite3.connect(db_file)
    try:
        query = (
            "SELECT player_id, position, pre_round_quotation_tenths, home_away, "
            "starter, minutes, fantasy_points, season "
            "FROM eval_player_games WHERE minutes > 0"
        )
        params: list[str] = []
        if seasons:
            query += f" AND season IN ({','.join('?' for _ in seasons)})"
            params.extend(seasons)

        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    if not rows:
        raise ValueError("No historical evaluation games found matching criteria.")

    v050_preds: list[float] = []
    v051_preds: list[float] = []
    v051_mins: list[float] = []
    actual_fps: list[float] = []
    actual_mins: list[float] = []

    pos_data: dict[str, dict[str, list[float]]] = {}

    ci_1sigma_hits = 0
    ci_90_hits = 0

    for pid, raw_pos, price_tenths, home_away, starter, minutes, fp, season in rows:
        # 1. Normalize position
        pos_str = str(raw_pos).strip().upper()
        if "G" in pos_str:
            norm_pos = "Guard"
        elif "F" in pos_str:
            norm_pos = "Forward"
        elif "C" in pos_str:
            norm_pos = "Center"
        else:
            norm_pos = "Other"

        credits = (price_tenths or 100) / 10.0
        act_fp = float(fp)
        act_min = float(minutes)

        # 2. V0.5.0 Baseline Prior (naive cost in credits)
        v050_xp = credits

        # 3. V0.5.1 Decomposed Model
        is_starter = (starter == 1 or credits >= 11.0)
        if is_starter:
            exp_min = min(30.0, max(18.0, 22.0 + (credits - 10.0) * 0.8))
        else:
            exp_min = min(22.0, max(6.0, 12.0 + (credits - 7.0) * 0.7))

        pos_base = 0.54 if norm_pos == "Guard" else (0.56 if norm_pos == "Forward" else 0.60)
        fp_per_min = max(0.32, min(0.85, pos_base + (credits - 10.5) * 0.028))
        loc_mult = 1.05 if str(home_away).upper() == "H" else 0.95
        v051_xp = round(1.0 * exp_min * fp_per_min * loc_mult, 2)

        sigma = max(3.0, v051_xp * 0.25)
        if abs(act_fp - v051_xp) <= sigma:
            ci_1sigma_hits += 1
        if abs(act_fp - v051_xp) <= 1.645 * sigma:
            ci_90_hits += 1

        v050_preds.append(v050_xp)
        v051_preds.append(v051_xp)
        v051_mins.append(exp_min)
        actual_fps.append(act_fp)
        actual_mins.append(act_min)

        if norm_pos not in pos_data:
            pos_data[norm_pos] = {
                "v050_preds": [],
                "v051_preds": [],
                "v051_mins": [],
                "actual_fps": [],
                "actual_mins": [],
            }
        pos_data[norm_pos]["v050_preds"].append(v050_xp)
        pos_data[norm_pos]["v051_preds"].append(v051_xp)
        pos_data[norm_pos]["v051_mins"].append(exp_min)
        pos_data[norm_pos]["actual_fps"].append(act_fp)
        pos_data[norm_pos]["actual_mins"].append(act_min)

    n = len(rows)
    v050_mae = sum(abs(p - a) for p, a in zip(v050_preds, actual_fps)) / n
    v051_mae = sum(abs(p - a) for p, a in zip(v051_preds, actual_fps)) / n
    v050_rmse = math.sqrt(sum((p - a) ** 2 for p, a in zip(v050_preds, actual_fps)) / n)
    v051_rmse = math.sqrt(sum((p - a) ** 2 for p, a in zip(v051_preds, actual_fps)) / n)
    v050_spearman = spearman_correlation(v050_preds, actual_fps)
    v051_spearman = spearman_correlation(v051_preds, actual_fps)
    v051_xm_mae = sum(abs(m - a) for m, a in zip(v051_mins, actual_mins)) / n

    by_position: dict[str, PositionMetrics] = {}
    for pos, pdict in pos_data.items():
        pn = len(pdict["actual_fps"])
        p_v050_mae = sum(abs(p - a) for p, a in zip(pdict["v050_preds"], pdict["actual_fps"])) / pn
        p_v051_mae = sum(abs(p - a) for p, a in zip(pdict["v051_preds"], pdict["actual_fps"])) / pn
        p_v050_sp = spearman_correlation(pdict["v050_preds"], pdict["actual_fps"])
        p_v051_sp = spearman_correlation(pdict["v051_preds"], pdict["actual_fps"])
        p_xm_mae = sum(abs(m - a) for m, a in zip(pdict["v051_mins"], pdict["actual_mins"])) / pn
        by_position[pos] = PositionMetrics(
            position=pos,
            samples=pn,
            v050_mae=round(p_v050_mae, 3),
            v051_mae=round(p_v051_mae, 3),
            v050_spearman=round(p_v050_sp, 4),
            v051_spearman=round(p_v051_sp, 4),
            v051_xm_mae=round(p_xm_mae, 2),
        )

    passed_gate = v051_mae <= (v050_mae + 0.05)

    return PredictionBacktestResult(
        total_samples=n,
        v050_mae=round(v050_mae, 3),
        v051_mae=round(v051_mae, 3),
        v050_rmse=round(v050_rmse, 3),
        v051_rmse=round(v051_rmse, 3),
        v050_spearman=round(v050_spearman, 4),
        v051_spearman=round(v051_spearman, 4),
        v051_xm_mae=round(v051_xm_mae, 2),
        ci_1sigma_coverage=round(ci_1sigma_hits / n, 4),
        ci_90_coverage=round(ci_90_hits / n, 4),
        by_position=by_position,
        passed_regression_gate=passed_gate,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run V0.5.1 vs V0.5.0 Prediction Calibration Backtest")
    parser.add_argument("--db", default=None, help="Path to SQLite database")
    parser.add_argument("--seasons", nargs="*", default=None, help="Specific seasons to evaluate (e.g. E2024 E2025)")
    parser.add_argument("--output", default=None, help="Path to write markdown validation report")
    args = parser.parse_args()

    res = run_v051_prediction_backtest(database_path=args.db, seasons=args.seasons)
    report = res.summary_markdown()
    print(report)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"\nSaved report to: {out_path}")


if __name__ == "__main__":
    main()
