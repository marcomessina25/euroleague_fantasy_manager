"""Walk-forward evaluation runner, round inspector, and Markdown/CSV report generator for V0.2.5."""

import csv
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ..fixtures import DATABASE_PATH, PROJECT_ROOT
from ..prediction.calibration import fit_out_of_sample_calibrator
from ..prediction.registry import get_model_registry
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
    PairedModelComparison,
    compute_paired_model_comparison,
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
            SELECT player_id, fantasy_points, pir, minutes, player_status, price_provenance
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
    actual_status_map = {int(r["player_id"]): str(r["player_status"]) for r in actual_rows}
    price_prov_map = {int(r["player_id"]): str(r["price_provenance"]) for r in actual_rows}
    actual_meta = {
        int(r["player_id"]): {
            "actual_fantasy_points": float(r["fantasy_points"]),
            "actual_pir": float(r["pir"]),
            "actual_minutes": float(r["minutes"]),
            "actual_status": str(r["player_status"]),
            "price_provenance": str(r["price_provenance"]),
        }
        for r in actual_rows
    }

    models = ("season_mean", "last5", "ewma", "xpdk_v02")
    preds_by_model = predict_round_baselines(
        feature_table=features_by_pid,
        actual_points_by_player=actual_fpts,
        models=models,
        actual_status_by_player=actual_status_map,
        price_provenance_by_player=price_prov_map,
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
                "price_provenance": price_prov_map.get(pid, "reconstructed"),
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
        "price_coverage_by_season": store.get_price_coverage_by_season(),
        "games": [dict(g) for g in games_rows],
        "player_count": len(player_inspection),
        "players": player_inspection,
    }


def format_evaluation_console_table(
    model_summaries: Sequence[ModelEvaluationSummary],
    decision_summaries: Sequence[DecisionEvaluationSummary],
    paired_comparisons: Sequence[PairedModelComparison] | None = None,
) -> str:
    """Format the console evaluation summary matching Section 18 of docs/v025/v025.md."""
    lines: list[str] = []
    lines.append("MODEL                  MAE     RMSE    BIAS    SPEARMAN   TOP10   VALUE_RHO   BRIER")
    for ms in model_summaries:
        lines.append(
            f"{ms.model_name:<20} {ms.mae:>6.2f}  {ms.rmse:>6.2f}  {ms.bias:>+6.2f}  "
            f"{ms.spearman:>8.3f}   {ms.top10_recall:>5.2f}   {ms.value_spearman:>9.3f}   {ms.brier_score:>5.3f}"
        )
    lines.append("")
    lines.append("Fantasy lineup simulation")
    lines.append("MODEL                  ACTUAL AVG SCORE   CAP REGRET   6TH REGRET   LINEUP REGRET")
    for ds in decision_summaries:
        lines.append(
            f"{ds.model_name:<20} {ds.avg_recommended_actual_score:>16.2f}   "
            f"{ds.avg_captain_regret:>10.2f}   {ds.avg_sixth_man_regret:>10.2f}   "
            f"{ds.avg_lineup_regret:>13.2f}"
        )
    if paired_comparisons:
        lines.append("")
        lines.append("Paired Model Comparisons (Delta = Model A - Model B; dMAE < 0 is better)")
        lines.append("PAIR                              dMAE (+/-95% CI)    dRMSE    dSPEARMAN   dLINEUP")
        for pc in paired_comparisons:
            pair_label = f"{pc.model_a} vs {pc.model_b}"
            lines.append(
                f"{pair_label:<32} {pc.delta_mae:>+6.2f} +/- {pc.delta_mae_ci95:<5.2f}  "
                f"{pc.delta_rmse:>+6.2f}   {pc.delta_spearman:>+9.3f}   {pc.delta_lineup_score:>+7.2f}"
            )
    return "\n".join(lines)


def _write_evaluation_artifacts(
    reports_dir: Path,
    season: str,
    model_summaries: Sequence[ModelEvaluationSummary],
    decision_summaries: Sequence[DecisionEvaluationSummary],
    round_rows: Sequence[dict[str, Any]],
    all_predictions: Sequence[PredictionRecord],
    price_coverage_by_season: dict[str, dict[str, int]] | None = None,
    paired_comparisons: Sequence[PairedModelComparison] | None = None,
) -> dict[str, str]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    season_slug = season.lower()
    md_path = reports_dir / f"{season_slug}_baseline_comparison.md"
    round_csv_path = reports_dir / f"{season_slug}_round_by_round.csv"
    pred_csv_path = reports_dir / f"{season_slug}_player_predictions.csv"
    paired_csv_path = reports_dir / f"{season_slug}_paired_comparisons.csv"

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

    # 3. Write paired comparisons CSV
    if paired_comparisons:
        paired_dicts = [asdict(p) for p in paired_comparisons]
        with paired_csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(paired_dicts[0].keys()))
            writer.writeheader()
            writer.writerows(paired_dicts)

    # 4. Write Markdown report
    best_mae_model = min(model_summaries, key=lambda m: m.mae)
    best_spearman_model = max(model_summaries, key=lambda m: m.spearman)
    best_top10_model = max(model_summaries, key=lambda m: m.top10_recall)
    best_lineup_model = max(decision_summaries, key=lambda d: d.avg_recommended_actual_score)
    first_ms = model_summaries[0]

    md_lines = [
        f"# V0.3 Walk-Forward Model Comparison — Season `{season}`",
        "",
        f"- **Dataset Version**: `{first_ms.dataset_version}`",
        f"- **Rounds Evaluated**: `{first_ms.rounds_evaluated}`",
        f"- **All Listed Court Player Samples per Model**: `{first_ms.player_samples}`",
        f"- **Active Court Player Samples (`minutes > 0`) per Model**: `{first_ms.active_player_samples}`",
        f"- **Head Coach Samples per Model**: `{first_ms.coach_samples}`",
        "",
        "## 1a. All Listed Court Players (`G, F, C` — Including DNPs / Inactive as `0.0`)",
        "",
        "| Model | Version | N (All) | MAE (±95% CI) | RMSE | MedAE | Bias | Spearman | Top-5 | Top-10 | Top-20 | Value Spearman | Brier Score |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for ms in model_summaries:
        md_lines.append(
            f"| `{ms.model_name}` | `{ms.model_version}` | `{ms.player_samples}` | `{ms.mae:.2f} ± {ms.mae_ci95:.2f}` | "
            f"`{ms.rmse:.2f}` | `{ms.median_ae:.2f}` | `{ms.bias:+.2f}` | `{ms.spearman:.3f}` | "
            f"`{ms.top5_recall:.2f}` | `{ms.top10_recall:.2f}` | `{ms.top20_recall:.2f}` | `{ms.value_spearman:.3f}` | `{ms.brier_score:.3f}` |"
        )

    md_lines.extend(
        [
            "",
            "## 1b. Active Court Players Only (`G, F, C` with `minutes > 0`)",
            "",
            "| Model | Version | N (Active) | Active MAE | Active RMSE | Active Bias | Active Spearman |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for ms in model_summaries:
        md_lines.append(
            f"| `{ms.model_name}` | `{ms.model_version}` | `{ms.active_player_samples}` | "
            f"`{ms.active_mae:.2f}` | `{ms.active_rmse:.2f}` | `{ms.active_bias:+.2f}` | `{ms.active_spearman:.3f}` |"
        )

    md_lines.extend(
        [
            "",
            "## 2. Separate Head Coach Margin-Bracket Summary (`HC`)",
            "",
            "| Model | N (Coaches) | Coach MAE | Coach RMSE | Coach Bias |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for ms in model_summaries:
        md_lines.append(
            f"| `{ms.model_name}` | `{ms.coach_samples}` | `{ms.coach_mae:.2f}` | `{ms.coach_rmse:.2f}` | `{ms.coach_bias:+.2f}` |"
        )

    md_lines.extend(
        [
            "",
            "## 3. Simplified Fantasy Lineup Decision Simulation (11-Unit Reference Squad)",
            "",
            "> **Scope note:** This table evaluates lineup selection, captain (`2.0x`), sixth-man (`1.0x`), and bench (`0.5x`) role assignments on a standardized 11-unit reference squad per round.",
            "",
            "| Model | Rounds | Actual Avg Score | Oracle Avg Score | Lineup Regret | Captain Regret | 6th-Man Regret | Bench Regret | Formation Regret |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for ds in decision_summaries:
        md_lines.append(
            f"| `{ds.model_name}` | `{ds.rounds_evaluated}` | `{ds.avg_recommended_actual_score:.2f}` | `{ds.avg_oracle_actual_score:.2f}` | "
            f"`{ds.avg_lineup_regret:.2f}` | `{ds.avg_captain_regret:.2f}` | `{ds.avg_sixth_man_regret:.2f}` | "
            f"`{ds.avg_bench_regret:.2f}` | `{ds.avg_formation_regret:.2f}` |"
        )

    if paired_comparisons:
        md_lines.extend(
            [
                "",
                "## 4. Head-to-Head Paired Model Comparisons",
                "",
                "| Pair (A vs B) | N | ΔMAE (±95% CI) | ΔRMSE | ΔSpearman | ΔTop-10 Recall | ΔLineup Score |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for pc in paired_comparisons:
            md_lines.append(
                f"| `{pc.model_a}` vs `{pc.model_b}` | `{pc.sample_count}` | "
                f"`{pc.delta_mae:+.2f} ± {pc.delta_mae_ci95:.2f}` | `{pc.delta_rmse:+.2f}` | "
                f"`{pc.delta_spearman:+.3f}` | `{pc.delta_top10_recall:+.2f}` | `{pc.delta_lineup_score:+.2f}` |"
            )

    if price_coverage_by_season:
        md_lines.extend(
            [
                "",
                "## 5. Historical Pricing Provenance & Coverage by Season",
                "",
                "| Season | `official_snapshot` | `archived_fantasy` | `reconstructed` | `proxy` | `missing` |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for s_code, counts in sorted(price_coverage_by_season.items()):
            md_lines.append(
                f"| `{s_code}` | `{counts.get('official_snapshot', 0)}` | `{counts.get('archived_fantasy', 0)}` | "
                f"`{counts.get('reconstructed', 0)}` | `{counts.get('proxy', 0)}` | `{counts.get('missing', 0)}` |"
            )
        md_lines.append("")
        md_lines.append(
            "> **Pricing caveat:** Because historical fantasy quotations have weaker archival coverage than official box-score statistics, `Value Spearman` (`prediction / price`) should be interpreted alongside price provenance rather than treated as equally reliable across all historical seasons."
        )

    md_lines.extend(
        [
            "",
            "## 6. Benchmark Summary",
            "",
            f"- **Rank-Ordering (`Spearman` / `Value Spearman`)**: `{best_spearman_model.model_name}` leads rank correlation (`Spearman = {best_spearman_model.spearman:.3f}`, `Value Spearman = {best_spearman_model.value_spearman:.3f}`).",
            f"- **Point Error (`MAE` / `RMSE`)**: `{best_mae_model.model_name}` achieves the lowest overall point error (`MAE = {best_mae_model.mae:.2f}`, `RMSE = {best_mae_model.rmse:.2f}`).",
            f"- **Top-10 Recall & Lineup Simulation**: `{best_top10_model.model_name}` achieves `Top-10 Recall = {best_top10_model.top10_recall:.2f}`, and `{best_lineup_model.model_name}` achieves `{best_lineup_model.avg_recommended_actual_score:.2f}` simulated lineup points/round.",
            "- All features and predictions were computed strictly before each round's `decision_cutoff` with zero future data leakage.",
            "",
        ]
    )
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    out_paths = {
        "markdown_report": str(md_path),
        "round_by_round_csv": str(round_csv_path),
        "player_predictions_csv": str(pred_csv_path),
    }
    if paired_comparisons:
        out_paths["paired_comparisons_csv"] = str(paired_csv_path)
    return out_paths


def run_walk_forward_evaluation(
    season: str | int | Sequence[str | int] = "2025",
    rounds: str | None = "1:34",
    models: Sequence[str] = ("season_mean", "last5", "ewma", "xpdk_v02"),
    ewma_alpha: float = 0.25,
    database_path: Path = DATABASE_PATH,
    reports_dir: Path | None = DEFAULT_EVAL_REPORTS_DIR,
    dataset_version: str = DATASET_VERSION,
    calibration_method: str = "linear",
) -> dict[str, Any]:
    """Run chronological round-by-round walk-forward evaluation across `season`(s) and `rounds`."""
    store = EvaluationDatasetStore(database_path)

    if isinstance(season, (list, tuple)):
        target_seasons = [normalize_season_code(s) for s in season]
    elif isinstance(season, str) and ("," in season or " " in season):
        target_seasons = [normalize_season_code(s) for s in season.replace(",", " ").split() if s.strip()]
    else:
        target_seasons = [normalize_season_code(season)]

    for s in target_seasons:
        _ensure_dataset_present(store, s)

    canon_models = [canonical_model_name(m) for m in models]
    records_by_model: dict[str, list[PredictionRecord]] = {m: [] for m in canon_models}
    records_by_model_and_round: dict[str, dict[int, list[PredictionRecord]]] = {m: {} for m in canon_models}
    round_metric_rows: list[dict[str, Any]] = []

    # Historical accumulators for out-of-sample calibration with ZERO test-set leakage
    history_preds: dict[str, list[float]] = {}
    history_acts: dict[str, list[float]] = {}
    history_pos: dict[str, list[str]] = {}

    total_rounds_evaluated: list[int] = []

    with store._connect() as conn:
        for norm_season in target_seasons:
            avail_rows = conn.execute(
                "SELECT round FROM eval_rounds WHERE season = ? ORDER BY round ASC",
                (norm_season,),
            ).fetchall()
            avail_rounds = [int(r["round"]) for r in avail_rows]
            target_rounds = parse_rounds_spec(rounds, avail_rounds)
            if not target_rounds:
                continue

            for rnum in target_rounds:
                total_rounds_evaluated.append(rnum)
                cutoff = store.get_round_decision_cutoff(norm_season, rnum)
                feature_table = build_round_feature_table(
                    season=norm_season,
                    round_number=rnum,
                    database_path=database_path,
                    decision_cutoff=cutoff,
                    ewma_alpha=ewma_alpha,
                )
                actual_rows = conn.execute(
                    "SELECT player_id, fantasy_points, player_status, price_provenance FROM eval_player_games WHERE season = ? AND round = ?",
                    (norm_season, rnum),
                ).fetchall()
                actuals_map = {int(row["player_id"]): float(row["fantasy_points"]) for row in actual_rows}
                status_map = {int(row["player_id"]): str(row["player_status"]) for row in actual_rows}
                prov_map = {int(row["player_id"]): str(row["price_provenance"]) for row in actual_rows}

                # Build out-of-sample calibrators strictly from prior rounds (zero test leakage)
                calibrators: dict[str, Any] = {}
                for m in canon_models:
                    if m == "fp_decomposed_calibrated_v03":
                        source_key = "fp_decomposed_v03" if "fp_decomposed_v03" in history_preds else m
                        calibrator = fit_out_of_sample_calibrator(
                            past_predictions=history_preds.get(source_key, []),
                            past_actuals=history_acts.get(source_key, []),
                            positions=history_pos.get(source_key, []),
                            method=calibration_method,
                        )
                        calibrators[m] = calibrator
                    elif m == "xpdk_calibrated_v03":
                        source_key = "xpdk_v02" if "xpdk_v02" in history_preds else m
                        calibrator = fit_out_of_sample_calibrator(
                            past_predictions=history_preds.get(source_key, []),
                            past_actuals=history_acts.get(source_key, []),
                            positions=history_pos.get(source_key, []),
                            method=calibration_method,
                        )
                        calibrators[m] = calibrator

                # If fp_decomposed_calibrated_v03 is requested but raw fp_decomposed_v03 is not,
                # also predict raw so history has samples to fit the calibrator on
                models_to_predict = list(canon_models)
                if "fp_decomposed_calibrated_v03" in canon_models and "fp_decomposed_v03" not in canon_models:
                    models_to_predict.append("fp_decomposed_v03")
                if "xpdk_calibrated_v03" in canon_models and "xpdk_v02" not in canon_models:
                    models_to_predict.append("xpdk_v02")

                round_preds = predict_round_baselines(
                    feature_table=feature_table,
                    actual_points_by_player=actuals_map,
                    models=models_to_predict,
                    dataset_version=dataset_version,
                    actual_status_by_player=status_map,
                    price_provenance_by_player=prov_map,
                    calibrators_by_model=calibrators,
                )

                # Update historical accumulators for future rounds' calibrators
                for m_pred, p_list in round_preds.items():
                    history_preds.setdefault(m_pred, []).extend([p.prediction for p in p_list if p.position != "HC"])
                    history_acts.setdefault(m_pred, []).extend([p.actual_fantasy_points for p in p_list if p.position != "HC"])
                    history_pos.setdefault(m_pred, []).extend([p.position for p in p_list if p.position != "HC"])

                for m_name in canon_models:
                    p_list = round_preds[m_name]
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
                            "active_player_samples": r_summary.active_player_samples,
                            "mae": r_summary.mae,
                            "active_mae": r_summary.active_mae,
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

    if not total_rounds_evaluated:
        raise ValueError(f"No evaluation rounds matched spec={rounds!r} for seasons={target_seasons}.")

    n_eval_rounds = len(total_rounds_evaluated) // len(target_seasons) if len(target_seasons) > 0 else 1
    model_summaries = [
        compute_point_and_ranking_metrics(records_by_model[m], rounds_evaluated=n_eval_rounds)
        for m in canon_models
    ]
    decision_summaries = [
        evaluate_round_lineup_decisions(records_by_model_and_round[m])
        for m in canon_models
    ]
    dec_by_name = {ds.model_name: ds for ds in decision_summaries}

    # Compute paired model comparisons for all model pairs
    paired_comparisons: list[PairedModelComparison] = []
    if len(canon_models) >= 2:
        for i in range(len(canon_models)):
            for j in range(i + 1, len(canon_models)):
                ma = canon_models[i]
                mb = canon_models[j]
                pc = compute_paired_model_comparison(
                    records_a=records_by_model[ma],
                    records_b=records_by_model[mb],
                    decision_summary_a=dec_by_name.get(ma),
                    decision_summary_b=dec_by_name.get(mb),
                )
                paired_comparisons.append(pc)

    # Persist into prediction_runs, player_predictions, and model_metrics tables
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    registry = get_model_registry()
    primary_season = target_seasons[0] if len(target_seasons) == 1 else "E_MULTI"

    for m in canon_models:
        meta = registry.get(m) if registry.is_registered(m) else None
        run_id = f"{primary_season}_{m}_{dataset_version}"
        store.save_prediction_run(
            {
                "run_id": run_id,
                "model_name": m,
                "model_version": meta.model_version if meta else "0.3.0",
                "model_family": meta.model_family if meta else "predictive",
                "target_type": meta.target_type if meta else "fantasy_points",
                "training_window": f"{primary_season}_walk_forward",
                "feature_set_version": "1.1.0",
                "hyperparameters_json": meta.hyperparameters_json if meta else "{}",
                "calibration_method": meta.calibration_method if meta else "none",
                "created_at": now_iso,
            }
        )
        preds_to_save = [
            {
                "run_id": run_id,
                "season": pr.season,
                "round": pr.round,
                "decision_cutoff": pr.decision_cutoff,
                "player_id": pr.player_id,
                "position": pr.position,
                "cold_start_source": pr.cold_start_source,
                "quotation_at_decision_tenths": pr.quotation_at_decision_tenths,
                "play_probability": pr.play_probability,
                "expected_minutes_if_play": pr.expected_minutes,
                "expected_fp_per_min_if_play": pr.expected_fp_per_min,
                "expected_conditional_fp": pr.conditional_prediction,
                "expected_fantasy_points": pr.prediction,
                "lower_bound": pr.lower_bound,
                "upper_bound": pr.upper_bound,
                "prediction_spread": pr.prediction_spread,
                "expected_fp_per_credit": pr.expected_fp_per_credit,
                "points_above_replacement": pr.points_above_replacement,
                "risk_adjusted_value": pr.risk_adjusted_value,
                "actual_fantasy_points": pr.actual_fantasy_points,
            }
            for pr in records_by_model[m]
        ]
        store.save_player_predictions(preds_to_save)

    metrics_to_save = []
    for ms in model_summaries:
        run_id = f"{primary_season}_{ms.model_name}_{dataset_version}"
        dec_obj = dec_by_name.get(ms.model_name)
        metrics_to_save.append(
            {
                "run_id": run_id,
                "evaluation_mode": "walk_forward",
                "season_scope": primary_season,
                "round_scope": f"1:{len(total_rounds_evaluated)}",
                "slice_type": "all_players",
                "slice_value": "court_and_coach",
                "sample_count": ms.player_samples + ms.coach_samples,
                "mae": ms.mae,
                "rmse": ms.rmse,
                "medae": ms.median_ae,
                "bias": ms.bias,
                "spearman_rho": ms.spearman,
                "top10_recall": ms.top10_recall,
                "top20_recall": ms.top20_recall,
                "captain_hit_rate": 0.0,
                "captain_regret": dec_obj.avg_captain_regret if dec_obj else 0.0,
                "value_spearman_rho": ms.value_spearman,
                "selected_lineup_score": dec_obj.avg_recommended_actual_score if dec_obj else 0.0,
                "oracle_lineup_score": dec_obj.avg_oracle_actual_score if dec_obj else 0.0,
                "lineup_efficiency": 0.0,
                "brier_score": ms.brier_score,
                "log_loss": ms.log_loss,
            }
        )
    store.save_model_metrics(metrics_to_save)

    price_coverage = store.get_price_coverage_by_season()
    all_preds_flat = [pr for m in canon_models for pr in records_by_model[m]]
    artifact_paths: dict[str, str] = {}
    if reports_dir is not None:
        rep_season = target_seasons[0] if len(target_seasons) == 1 else "multi"
        artifact_paths = _write_evaluation_artifacts(
            reports_dir=Path(reports_dir),
            season=rep_season,
            model_summaries=model_summaries,
            decision_summaries=decision_summaries,
            round_rows=round_metric_rows,
            all_predictions=all_preds_flat,
            price_coverage_by_season=price_coverage,
            paired_comparisons=paired_comparisons,
        )

    console_table = format_evaluation_console_table(model_summaries, decision_summaries, paired_comparisons)
    return {
        "dataset_version": dataset_version,
        "season": primary_season,
        "seasons": target_seasons,
        "rounds_evaluated": total_rounds_evaluated,
        "ewma_alpha": ewma_alpha,
        "price_coverage_by_season": price_coverage,
        "models": [asdict(ms) for ms in model_summaries],
        "lineup_simulation": [asdict(ds) for ds in decision_summaries],
        "paired_comparisons": [asdict(pc) for pc in paired_comparisons],
        "round_by_round": round_metric_rows,
        "artifacts": artifact_paths,
        "console_table": console_table,
    }
