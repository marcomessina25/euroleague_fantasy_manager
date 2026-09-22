"""Walk-forward evaluation runner, round inspector, and Markdown/CSV report generator for V0.25."""

import csv
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from ..fixtures import DATABASE_PATH, PROJECT_ROOT
from .baselines import PredictionRecord, canonical_model_name, predict_round_baselines
from .dataset import (
    DATASET_VERSION,
    EvaluationDatasetStore,
    build_historical_dataset,
    normalize_season_code,
)
from .features import build_round_feature_table
from .metrics import (
    DecisionEvaluationSummary,
    ModelEvaluationSummary,
    compute_point_and_ranking_metrics,
    evaluate_round_lineup_decisions,
)

DEFAULT_EVAL_REPORTS_DIR = PROJECT_ROOT / "reports" / "evaluation"


def parse_rounds_spec(rounds_spec: str | None, available_rounds: Sequence[int]) -> list[int]:
    """Parse a round specification like '1:34', '2-8', '5', or '1,3,5' against available rounds."""
    avail_sorted = sorted(set(int(r) for r in available_rounds))
    if not avail_sorted:
        return []
    if not rounds_spec or not str(rounds_spec).strip():
        return avail_sorted

    spec = str(rounds_spec).strip()
    if ":" in spec or "-" in spec:
        sep = ":" if ":" in spec else "-"
        parts = spec.split(sep, 1)
        lo = int(parts[0].strip()) if parts[0].strip() else avail_sorted[0]
        hi = int(parts[1].strip()) if parts[1].strip() else avail_sorted[-1]
        return [r for r in avail_sorted if lo <= r <= hi]
    if "," in spec:
        wanted = {int(x.strip()) for x in spec.split(",") if x.strip()}
        return [r for r in avail_sorted if r in wanted]
    single = int(spec)
    return [r for r in avail_sorted if r == single]


def _ensure_dataset_present(store: EvaluationDatasetStore, target_season: str) -> None:
    seasons_present = store.list_seasons()
    if target_season not in seasons_present:
        default_seasons = sorted(set(["E2022", "E2023", "E2024", "E2025", target_season]))
        build_historical_dataset(database_path=store.database_path, seasons=default_seasons)


def inspect_historical_round(
    season: str | int = "2025",
    round_number: int = 8,
    database_path: Path = DATABASE_PATH,
    ewma_alpha: float = 0.25,
) -> dict[str, Any]:
    """Inspect point-in-time inputs, baseline predictions, and actual outcomes for a historical round."""
    store = EvaluationDatasetStore(database_path)
    norm_season = normalize_season_code(season)
    _ensure_dataset_present(store, norm_season)

    cutoff = store.get_round_decision_cutoff(norm_season, round_number)
    features_by_pid = build_round_feature_table(
        season=norm_season,
        round_number=round_number,
        database_path=database_path,
        decision_cutoff=cutoff,
        ewma_alpha=ewma_alpha,
    )

    with store._connect() as conn:
        actual_rows = conn.execute(
            """
            SELECT player_id, fantasy_points, pir, minutes, player_status
            FROM eval_player_games
            WHERE season = ? AND round = ?
            """,
            (norm_season, int(round_number)),
        ).fetchall()
        games_rows = conn.execute(
            """
            SELECT game_id, game_date, turn_number, home_team_id, away_team_id, home_score, away_score
            FROM eval_games
            WHERE season = ? AND round = ?
            ORDER BY game_id
            """,
            (norm_season, int(round_number)),
        ).fetchall()

    actual_fpts = {int(r["player_id"]): float(r["fantasy_points"]) for r in actual_rows}
    actual_meta = {
        int(r["player_id"]): {
            "actual_fantasy_points": float(r["fantasy_points"]),
            "actual_pir": float(r["pir"]),
            "actual_minutes": float(r["minutes"]),
            "actual_status": str(r["player_status"]),
        }
        for r in actual_rows
    }

    models = ("season_mean", "last5", "ewma", "xpdk_v02")
    preds_by_model = predict_round_baselines(
        feature_table=features_by_pid,
        actual_points_by_player=actual_fpts,
        models=models,
    )

    player_inspection: list[dict[str, Any]] = []
    for pid, feat in sorted(features_by_pid.items()):
        m_preds = {
            m: next(r.prediction for r in recs if r.player_id == pid)
            for m, recs in preds_by_model.items()
        }
        player_inspection.append(
            {
                "player_id": pid,
                "name": feat.player_name,
                "position": feat.position,
                "team": feat.team_code,
                "opponent": feat.opponent_team_code,
                "home": feat.home,
                "turn": feat.turn_number,
                "quotation_credits": round(feat.quotation_at_decision_tenths / 10.0, 1),
                "pre_round_status": feat.pre_round_status,
                "cold_start_source": feat.cold_start_source,
                "games_played_before_cutoff": feat.games_played,
                "season_avg_before_cutoff": round(feat.season_avg_fantasy_points, 2),
                "last5_avg_before_cutoff": round(feat.last_5_avg, 2),
                "ewma_before_cutoff": round(feat.ewma_fantasy_points, 2),
                "predictions": m_preds,
                "actual": actual_meta.get(pid, {}),
            }
        )

    return {
        "dataset_version": DATASET_VERSION,
        "season": norm_season,
        "round": int(round_number),
        "decision_cutoff": cutoff,
        "games": [dict(g) for g in games_rows],
        "player_count": len(player_inspection),
        "players": player_inspection,
    }


def format_evaluation_console_table(
    model_summaries: Sequence[ModelEvaluationSummary],
    decision_summaries: Sequence[DecisionEvaluationSummary],
) -> str:
    """Format the console evaluation summary matching Section 18 of docs/v025/v025.md."""
    lines: list[str] = []
    lines.append("MODEL         MAE     RMSE    BIAS    SPEARMAN   TOP10   VALUE_RHO")
    for ms in model_summaries:
        lines.append(
            f"{ms.model_name:<13} {ms.mae:>6.2f}  {ms.rmse:>6.2f}  {ms.bias:>+6.2f}  "
            f"{ms.spearman:>8.3f}   {ms.top10_recall:>5.2f}   {ms.value_spearman:>9.3f}"
        )
    lines.append("")
    lines.append("Fantasy lineup simulation")
    lines.append("MODEL         ACTUAL AVG SCORE   CAP REGRET   6TH REGRET   LINEUP REGRET")
    for ds in decision_summaries:
        lines.append(
            f"{ds.model_name:<13} {ds.avg_recommended_actual_score:>16.2f}   "
            f"{ds.avg_captain_regret:>10.2f}   {ds.avg_sixth_man_regret:>10.2f}   "
            f"{ds.avg_lineup_regret:>13.2f}"
        )
    return "\n".join(lines)


def _write_evaluation_artifacts(
    reports_dir: Path,
    season: str,
    model_summaries: Sequence[ModelEvaluationSummary],
    decision_summaries: Sequence[DecisionEvaluationSummary],
    round_rows: Sequence[dict[str, Any]],
    all_predictions: Sequence[PredictionRecord],
) -> dict[str, str]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    season_slug = season.lower()
    md_path = reports_dir / f"{season_slug}_baseline_comparison.md"
    round_csv_path = reports_dir / f"{season_slug}_round_by_round.csv"
    pred_csv_path = reports_dir / f"{season_slug}_player_predictions.csv"

    # 1. Write round-by-round CSV
    if round_rows:
        with round_csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(round_rows[0].keys()))
            writer.writeheader()
            writer.writerows(round_rows)

    # 2. Write player predictions CSV
    if all_predictions:
        pred_dicts = [asdict(p) for p in all_predictions]
        with pred_csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(pred_dicts[0].keys()))
            writer.writeheader()
            writer.writerows(pred_dicts)

    # 3. Write Markdown report
    best_mae_model = min(model_summaries, key=lambda m: m.mae)
    best_lineup_model = max(decision_summaries, key=lambda d: d.avg_recommended_actual_score)

    md_lines = [
        f"# V0.25 Walk-Forward Baseline Comparison — Season `{season}`",
        "",
        f"- **Dataset Version**: `{model_summaries[0].dataset_version}`",
        f"- **Rounds Evaluated**: `{model_summaries[0].rounds_evaluated}`",
        f"- **Court Player Samples per Model**: `{model_summaries[0].player_samples}`",
        f"- **Head Coach Samples per Model**: `{model_summaries[0].coach_samples}`",
        "",
        "## 1. Point Prediction & Ranking Summary (Court Players)",
        "",
        "| Model | Version | MAE (±95% CI) | RMSE | MedAE | Bias | Spearman | Top-5 | Top-10 | Top-20 | Value Spearman |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for ms in model_summaries:
        md_lines.append(
            f"| `{ms.model_name}` | `{ms.model_version}` | `{ms.mae:.2f} ± {ms.mae_ci95:.2f}` | "
            f"`{ms.rmse:.2f}` | `{ms.median_ae:.2f}` | `{ms.bias:+.2f}` | `{ms.spearman:.3f}` | "
            f"`{ms.top5_recall:.2f}` | `{ms.top10_recall:.2f}` | `{ms.top20_recall:.2f}` | `{ms.value_spearman:.3f}` |"
        )

    md_lines.extend(
        [
            "",
            "## 2. Separate Head Coach Margin-Bracket Summary",
            "",
            "| Model | Coach MAE | Coach RMSE | Coach Bias |",
            "|---|---:|---:|---:|",
        ]
    )
    for ms in model_summaries:
        md_lines.append(
            f"| `{ms.model_name}` | `{ms.coach_mae:.2f}` | `{ms.coach_rmse:.2f}` | `{ms.coach_bias:+.2f}` |"
        )

    md_lines.extend(
        [
            "",
            "## 3. Fantasy Lineup Decision Simulation (11-Unit Squad)",
            "",
            "| Model | Actual Avg Score | Oracle Avg Score | Lineup Regret | Captain Regret | 6th-Man Regret | Bench Regret | Formation Regret |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for ds in decision_summaries:
        md_lines.append(
            f"| `{ds.model_name}` | `{ds.avg_recommended_actual_score:.2f}` | `{ds.avg_oracle_actual_score:.2f}` | "
            f"`{ds.avg_lineup_regret:.2f}` | `{ds.avg_captain_regret:.2f}` | `{ds.avg_sixth_man_regret:.2f}` | "
            f"`{ds.avg_bench_regret:.2f}` | `{ds.avg_formation_regret:.2f}` |"
        )

    md_lines.extend(
        [
            "",
            "## 4. Short Interpretation",
            "",
            f"- **Lowest Point Error (`MAE`)**: `{best_mae_model.model_name}` (`MAE = {best_mae_model.mae:.2f}`, `Spearman = {best_mae_model.spearman:.3f}`).",
            f"- **Highest Realized Fantasy Lineup Score**: `{best_lineup_model.model_name}` (`{best_lineup_model.avg_recommended_actual_score:.2f}` actual points/round, `lineup_regret = {best_lineup_model.avg_lineup_regret:.2f}`).",
            "- All features and predictions were computed strictly before each round's `decision_cutoff` with zero future data leakage.",
            "",
        ]
    )
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    return {
        "markdown_report": str(md_path),
        "round_by_round_csv": str(round_csv_path),
        "player_predictions_csv": str(pred_csv_path),
    }


def run_walk_forward_evaluation(
    season: str | int = "2025",
    rounds: str | None = "1:34",
    models: Sequence[str] = ("season_mean", "last5", "ewma", "xpdk_v02"),
    ewma_alpha: float = 0.25,
    database_path: Path = DATABASE_PATH,
    reports_dir: Path | None = DEFAULT_EVAL_REPORTS_DIR,
    dataset_version: str = DATASET_VERSION,
) -> dict[str, Any]:
    """Run chronological round-by-round walk-forward evaluation across `season` and `rounds`."""
    store = EvaluationDatasetStore(database_path)
    norm_season = normalize_season_code(season)
    _ensure_dataset_present(store, norm_season)

    with store._connect() as conn:
        avail_rows = conn.execute(
            "SELECT round FROM eval_rounds WHERE season = ? ORDER BY round ASC",
            (norm_season,),
        ).fetchall()
    avail_rounds = [int(r["round"]) for r in avail_rows]
    target_rounds = parse_rounds_spec(rounds, avail_rounds)
    if not target_rounds:
        raise ValueError(f"No evaluation rounds matched spec={rounds!r} for season={norm_season}.")

    canon_models = [canonical_model_name(m) for m in models]
    records_by_model: dict[str, list[PredictionRecord]] = {m: [] for m in canon_models}
    records_by_model_and_round: dict[str, dict[int, list[PredictionRecord]]] = {m: {} for m in canon_models}
    round_metric_rows: list[dict[str, Any]] = []

    with store._connect() as conn:
        for rnum in target_rounds:
            cutoff = store.get_round_decision_cutoff(norm_season, rnum)
            feature_table = build_round_feature_table(
                season=norm_season,
                round_number=rnum,
                database_path=database_path,
                decision_cutoff=cutoff,
                ewma_alpha=ewma_alpha,
            )
            actual_rows = conn.execute(
                "SELECT player_id, fantasy_points FROM eval_player_games WHERE season = ? AND round = ?",
                (norm_season, rnum),
            ).fetchall()
            actuals_map = {int(row["player_id"]): float(row["fantasy_points"]) for row in actual_rows}

            round_preds = predict_round_baselines(
                feature_table=feature_table,
                actual_points_by_player=actuals_map,
                models=canon_models,
                dataset_version=dataset_version,
            )

            for m_name, p_list in round_preds.items():
                records_by_model[m_name].extend(p_list)
                records_by_model_and_round[m_name][rnum] = p_list
                r_summary = compute_point_and_ranking_metrics(p_list, rounds_evaluated=1)
                round_metric_rows.append(
                    {
                        "dataset_version": dataset_version,
                        "season": norm_season,
                        "round": rnum,
                        "decision_cutoff": cutoff,
                        "model_name": m_name,
                        "model_version": r_summary.model_version,
                        "player_samples": r_summary.player_samples,
                        "mae": r_summary.mae,
                        "rmse": r_summary.rmse,
                        "bias": r_summary.bias,
                        "spearman": r_summary.spearman,
                        "top10_recall": r_summary.top10_recall,
                        "value_spearman": r_summary.value_spearman,
                    }
                )

                # Persist provenance records into eval_predictions
                for pr in p_list:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO eval_predictions (
                            dataset_version, model_name, model_version, decision_cutoff,
                            season, round, player_id, position, cold_start_source,
                            predicted_conditional_points, predicted_unconditional_points,
                            actual_fantasy_points, quotation_at_decision_tenths
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            pr.dataset_version,
                            pr.model_name,
                            pr.model_version,
                            pr.decision_cutoff,
                            pr.season,
                            pr.round,
                            pr.player_id,
                            pr.position,
                            pr.cold_start_source,
                            pr.conditional_prediction,
                            pr.prediction,
                            pr.actual_fantasy_points,
                            pr.quotation_at_decision_tenths,
                        ),
                    )

    model_summaries = [
        compute_point_and_ranking_metrics(records_by_model[m], rounds_evaluated=len(target_rounds))
        for m in canon_models
    ]
    decision_summaries = [
        evaluate_round_lineup_decisions(records_by_model_and_round[m])
        for m in canon_models
    ]

    all_preds_flat = [pr for m in canon_models for pr in records_by_model[m]]
    artifact_paths: dict[str, str] = {}
    if reports_dir is not None:
        artifact_paths = _write_evaluation_artifacts(
            reports_dir=Path(reports_dir),
            season=norm_season,
            model_summaries=model_summaries,
            decision_summaries=decision_summaries,
            round_rows=round_metric_rows,
            all_predictions=all_preds_flat,
        )

    console_table = format_evaluation_console_table(model_summaries, decision_summaries)
    return {
        "dataset_version": dataset_version,
        "season": norm_season,
        "rounds_evaluated": target_rounds,
        "ewma_alpha": ewma_alpha,
        "models": [asdict(ms) for ms in model_summaries],
        "lineup_simulation": [asdict(ds) for ds in decision_summaries],
        "round_by_round": round_metric_rows,
        "artifacts": artifact_paths,
        "console_table": console_table,
    }
