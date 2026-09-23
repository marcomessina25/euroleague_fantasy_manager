"""Point prediction, ranking, value-ranking, and fantasy lineup decision regret metrics for V0.2.5."""

from dataclasses import dataclass
import math
from statistics import median
from typing import Sequence

from ..expected_points import PlayerProjection
from ..lineup import optimize_court_lineup
from ..models import Player, Position
from .baselines import PredictionRecord


@dataclass(frozen=True, slots=True)
class ModelEvaluationSummary:
    model_name: str
    model_version: str
    dataset_version: str
    season: str
    rounds_evaluated: int
    player_samples: int
    coach_samples: int
    mae: float
    mae_ci95: float
    rmse: float
    median_ae: float
    bias: float
    spearman: float
    kendall_tau: float
    top5_recall: float
    top10_recall: float
    top20_recall: float
    value_spearman: float
    coach_mae: float
    coach_rmse: float
    coach_bias: float
    active_player_samples: int = 0
    active_mae: float = 0.0
    active_rmse: float = 0.0
    active_bias: float = 0.0
    active_spearman: float = 0.0
    price_provenance_counts: dict[str, int] | None = None
    brier_score: float = 0.0
    log_loss: float = 0.0


@dataclass(frozen=True, slots=True)
class DecisionEvaluationSummary:
    model_name: str
    rounds_evaluated: int
    avg_recommended_actual_score: float
    avg_oracle_actual_score: float
    avg_lineup_regret: float
    avg_captain_regret: float
    avg_sixth_man_regret: float
    avg_bench_regret: float
    avg_formation_regret: float


def _average_ranks(values: Sequence[float]) -> list[float]:
    """Compute 1-based fractional ranks with tie averaging."""
    n = len(values)
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def spearman_correlation(predicted: Sequence[float], actual: Sequence[float]) -> float:
    """Compute exact Pearson correlation over tie-averaged ranks."""
    n = len(predicted)
    if n < 2 or len(actual) != n:
        return 0.0
    rx = _average_ranks(predicted)
    ry = _average_ranks(actual)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    vx = sum((rx[i] - mx) ** 2 for i in range(n))
    vy = sum((ry[i] - my) ** 2 for i in range(n))
    denom = math.sqrt(vx * vy)
    if denom <= 1e-12:
        return 0.0
    return round(cov / denom, 4)


def kendall_tau(predicted: Sequence[float], actual: Sequence[float]) -> float:
    """Compute Kendall rank correlation coefficient tau-a."""
    n = len(predicted)
    if n < 2 or len(actual) != n:
        return 0.0
    concordant = 0
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx = predicted[i] - predicted[j]
            dy = actual[i] - actual[j]
            prod = dx * dy
            if prod > 0:
                concordant += 1
            elif prod < 0:
                discordant += 1
    pairs = n * (n - 1) / 2.0
    return round((concordant - discordant) / pairs, 4) if pairs > 0 else 0.0


def top_k_recall(predicted: Sequence[float], actual: Sequence[float], k: int) -> float:
    """Compute fraction of top-K actual performers captured in top-K predicted performers."""
    n = len(predicted)
    if n == 0:
        return 0.0
    eff_k = max(1, min(int(k), n))
    pred_top_idx = {
        idx
        for idx, _ in sorted(enumerate(predicted), key=lambda item: (item[1], -item[0]), reverse=True)[:eff_k]
    }
    act_top_idx = {
        idx
        for idx, _ in sorted(enumerate(actual), key=lambda item: (item[1], -item[0]), reverse=True)[:eff_k]
    }
    return round(len(pred_top_idx & act_top_idx) / float(eff_k), 4)


def compute_point_and_ranking_metrics(
    records: Sequence[PredictionRecord],
    rounds_evaluated: int = 1,
) -> ModelEvaluationSummary:
    """Compute point error, bias, confidence interval, and round-averaged ranking metrics.

    Court Players (`G, F, C`) and Head Coaches (`HC`) are evaluated strictly separately (Section 7.2).
    """
    if not records:
        raise ValueError("Cannot compute evaluation metrics on empty prediction record sequence.")

    first = records[0]
    player_recs = [r for r in records if r.position != "HC"]
    active_player_recs = [r for r in player_recs if r.actual_status not in ("DNP", "out")]
    coach_recs = [r for r in records if r.position == "HC"]

    if player_recs:
        abs_errors = [abs(r.prediction - r.actual_fantasy_points) for r in player_recs]
        sq_errors = [(r.prediction - r.actual_fantasy_points) ** 2 for r in player_recs]
        signed_errors = [r.prediction - r.actual_fantasy_points for r in player_recs]
        n_p = len(player_recs)
        mae_val = sum(abs_errors) / n_p
        rmse_val = math.sqrt(sum(sq_errors) / n_p)
        med_ae = float(median(abs_errors))
        bias_val = sum(signed_errors) / n_p
        if n_p > 1:
            mean_ae = mae_val
            var_ae = sum((e - mean_ae) ** 2 for e in abs_errors) / (n_p - 1)
            ci95 = 1.96 * math.sqrt(var_ae / n_p)
        else:
            ci95 = 0.0
    else:
        n_p = 0
        mae_val = rmse_val = med_ae = bias_val = ci95 = 0.0

    if active_player_recs:
        act_abs = [abs(r.conditional_prediction - r.actual_fantasy_points) for r in active_player_recs]
        act_sq = [(r.conditional_prediction - r.actual_fantasy_points) ** 2 for r in active_player_recs]
        act_sig = [r.conditional_prediction - r.actual_fantasy_points for r in active_player_recs]
        n_act = len(active_player_recs)
        act_mae = sum(act_abs) / n_act
        act_rmse = math.sqrt(sum(act_sq) / n_act)
        act_bias = sum(act_sig) / n_act
    else:
        n_act = 0
        act_mae = act_rmse = act_bias = 0.0

    # Group court player predictions by (season, round) for ranking metrics
    by_round: dict[tuple[str, int], list[PredictionRecord]] = {}
    for r in player_recs:
        by_round.setdefault((r.season, r.round), []).append(r)

    sp_list: list[float] = []
    act_sp_list: list[float] = []
    kt_list: list[float] = []
    t5_list: list[float] = []
    t10_list: list[float] = []
    t20_list: list[float] = []
    val_sp_list: list[float] = []

    for _, r_list in sorted(by_round.items()):
        preds = [x.prediction for x in r_list]
        acts = [x.actual_fantasy_points for x in r_list]
        sp_list.append(spearman_correlation(preds, acts))
        kt_list.append(kendall_tau(preds, acts))
        t5_list.append(top_k_recall(preds, acts, k=5))
        t10_list.append(top_k_recall(preds, acts, k=10))
        t20_list.append(top_k_recall(preds, acts, k=20))

        act_round = [x for x in r_list if x.actual_status not in ("DNP", "out")]
        if len(act_round) >= 2:
            act_sp_list.append(
                spearman_correlation(
                    [x.conditional_prediction for x in act_round],
                    [x.actual_fantasy_points for x in act_round],
                )
            )

        # Value ranking strictly uses pre-round quotation_at_decision_tenths (Section 12.3)
        pred_vals = [x.prediction / max(4.0, x.quotation_at_decision_tenths / 10.0) for x in r_list]
        act_vals = [x.actual_fantasy_points / max(4.0, x.quotation_at_decision_tenths / 10.0) for x in r_list]
        val_sp_list.append(spearman_correlation(pred_vals, act_vals))

    prov_counts: dict[str, int] = {
        "official_snapshot": 0,
        "archived_fantasy": 0,
        "reconstructed": 0,
        "proxy": 0,
        "missing": 0,
    }
    for r in player_recs:
        p_cat = r.price_provenance if r.price_provenance in prov_counts else "reconstructed"
        prov_counts[p_cat] += 1

    # Separate Head Coach metrics
    if coach_recs:
        c_abs = [abs(r.prediction - r.actual_fantasy_points) for r in coach_recs]
        c_sq = [(r.prediction - r.actual_fantasy_points) ** 2 for r in coach_recs]
        c_sig = [r.prediction - r.actual_fantasy_points for r in coach_recs]
        n_c = len(coach_recs)
        c_mae = sum(c_abs) / n_c
        c_rmse = math.sqrt(sum(c_sq) / n_c)
        c_bias = sum(c_sig) / n_c
    else:
        n_c = 0
    # Availability metrics (Brier score and binary cross-entropy log-loss)
    if player_recs:
        probs = [getattr(r, "play_probability", 1.0) for r in player_recs]
        played_acts = [1.0 if r.actual_status not in ("DNP", "out") else 0.0 for r in player_recs]
        brier = sum((p - y) ** 2 for p, y in zip(probs, played_acts)) / len(player_recs)
        eps = 1e-4
        log_loss_val = sum(
            -(y * math.log(max(eps, min(1.0 - eps, p))) + (1.0 - y) * math.log(max(eps, min(1.0 - eps, 1.0 - p))))
            for p, y in zip(probs, played_acts)
        ) / len(player_recs)
    else:
        brier = log_loss_val = 0.0

    n_rounds = max(1, len(by_round) or rounds_evaluated)
    return ModelEvaluationSummary(
        model_name=first.model_name,
        model_version=first.model_version,
        dataset_version=first.dataset_version,
        season=first.season,
        rounds_evaluated=n_rounds,
        player_samples=n_p,
        coach_samples=n_c,
        mae=round(mae_val, 3),
        mae_ci95=round(ci95, 3),
        rmse=round(rmse_val, 3),
        median_ae=round(med_ae, 3),
        bias=round(bias_val, 3),
        spearman=round(sum(sp_list) / len(sp_list), 4) if sp_list else 0.0,
        kendall_tau=round(sum(kt_list) / len(kt_list), 4) if kt_list else 0.0,
        top5_recall=round(sum(t5_list) / len(t5_list), 4) if t5_list else 0.0,
        top10_recall=round(sum(t10_list) / len(t10_list), 4) if t10_list else 0.0,
        top20_recall=round(sum(t20_list) / len(t20_list), 4) if t20_list else 0.0,
        value_spearman=round(sum(val_sp_list) / len(val_sp_list), 4) if val_sp_list else 0.0,
        coach_mae=round(c_mae, 3),
        coach_rmse=round(c_rmse, 3),
        coach_bias=round(c_bias, 3),
        active_player_samples=n_act,
        active_mae=round(act_mae, 3),
        active_rmse=round(act_rmse, 3),
        active_bias=round(act_bias, 3),
        active_spearman=round(sum(act_sp_list) / len(act_sp_list), 4) if act_sp_list else 0.0,
        price_provenance_counts=prov_counts,
        brier_score=round(brier, 4),
        log_loss=round(log_loss_val, 4),
    )


def _score_lineup_with_actuals(
    starter_ids: Sequence[int],
    captain_id: int,
    sixth_man_id: int,
    bench_ids: Sequence[int],
    head_coach_id: int,
    actuals_by_id: dict[int, float],
) -> float:
    starters_sum = sum(actuals_by_id.get(pid, 0.0) for pid in starter_ids)
    cap_bonus = actuals_by_id.get(captain_id, 0.0)
    sixth_val = actuals_by_id.get(sixth_man_id, 0.0)
    bench_sum = 0.5 * sum(actuals_by_id.get(bid, 0.0) for bid in bench_ids)
    hc_val = actuals_by_id.get(head_coach_id, 0.0)
    return round(hc_val + starters_sum + cap_bonus + sixth_val + bench_sum, 2)


def evaluate_round_lineup_decisions(
    records_by_round: dict[int, list[PredictionRecord]],
    reference_squad_ids: Sequence[int] | None = None,
) -> DecisionEvaluationSummary:
    """Run lineup optimization on each historical round's predictions and compute actual score and regret metrics."""
    if not records_by_round:
        raise ValueError("Cannot evaluate lineup decisions on empty round dictionary.")

    model_name = next(iter(records_by_round.values()))[0].model_name
    rec_scores: list[float] = []
    oracle_scores: list[float] = []
    lineup_regrets: list[float] = []
    cap_regrets: list[float] = []
    sixth_regrets: list[float] = []
    bench_regrets: list[float] = []
    form_regrets: list[float] = []

    for rnum, r_records in sorted(records_by_round.items()):
        rec_by_id = {r.player_id: r for r in r_records}
        if reference_squad_ids is not None and all(pid in rec_by_id for pid in reference_squad_ids):
            squad_ids = list(reference_squad_ids)
        else:
            # Select a standard 11-unit reference squad (4G, 4F, 2C, 1HC) by pre-round quotation
            guards = sorted([r for r in r_records if r.position == "G"], key=lambda x: (-x.quotation_at_decision_tenths, x.player_id))[:4]
            forwards = sorted([r for r in r_records if r.position == "F"], key=lambda x: (-x.quotation_at_decision_tenths, x.player_id))[:4]
            centers = sorted([r for r in r_records if r.position == "C"], key=lambda x: (-x.quotation_at_decision_tenths, x.player_id))[:2]
            coaches = sorted([r for r in r_records if r.position == "HC"], key=lambda x: (-x.quotation_at_decision_tenths, x.player_id))[:1]
            squad_ids = [r.player_id for r in guards + forwards + centers + coaches]

        squad_players: list[Player] = []
        pred_projections: dict[int, PlayerProjection] = {}
        oracle_projections: dict[int, PlayerProjection] = {}
        actuals_by_id: dict[int, float] = {}

        for pid in squad_ids:
            rec = rec_by_id[pid]
            pos_enum = Position.from_raw(rec.position)
            p_obj = Player(
                id=pid,
                name=rec.player_name,
                position=pos_enum,
                team_id=rec.team_id,
                team_code=rec.team_code,
                price_tenths=rec.quotation_at_decision_tenths,
                status="starter",
                probability_of_playing=1.0,
                turn_number=rec.turn_number,
            )
            squad_players.append(p_obj)
            actuals_by_id[pid] = rec.actual_fantasy_points

            pred_projections[pid] = PlayerProjection(
                player_id=pid,
                name=rec.player_name,
                position=pos_enum,
                team_id=rec.team_id,
                team_code=rec.team_code,
                price_tenths=rec.quotation_at_decision_tenths,
                credits=round(rec.quotation_at_decision_tenths / 10.0, 1),
                status="starter",
                turn_number=rec.turn_number,
                opponent_code="OPP",
                is_home=True,
                fdr=3,
                win_probability=0.5,
                expected_margin=0.0,
                availability_factor=1.0,
                base_pir=rec.prediction,
                expected_pdk=rec.prediction,
                sigma_pdk=rec.sigma_prediction,
            )
            oracle_projections[pid] = PlayerProjection(
                player_id=pid,
                name=rec.player_name,
                position=pos_enum,
                team_id=rec.team_id,
                team_code=rec.team_code,
                price_tenths=rec.quotation_at_decision_tenths,
                credits=round(rec.quotation_at_decision_tenths / 10.0, 1),
                status="starter",
                turn_number=1,  # static hindsight oracle
                opponent_code="OPP",
                is_home=True,
                fdr=3,
                win_probability=0.5,
                expected_margin=0.0,
                availability_factor=1.0,
                base_pir=rec.actual_fantasy_points,
                expected_pdk=rec.actual_fantasy_points,
                sigma_pdk=0.01,
            )

        model_lineup = optimize_court_lineup(squad_players, pred_projections, round_number=rnum)
        oracle_lineup = optimize_court_lineup(squad_players, oracle_projections, round_number=rnum)

        actual_score = _score_lineup_with_actuals(
            starter_ids=model_lineup.starter_ids,
            captain_id=model_lineup.captain_id,
            sixth_man_id=model_lineup.sixth_man_id,
            bench_ids=model_lineup.bench_ids,
            head_coach_id=model_lineup.head_coach_id,
            actuals_by_id=actuals_by_id,
        )
        oracle_score = _score_lineup_with_actuals(
            starter_ids=oracle_lineup.starter_ids,
            captain_id=oracle_lineup.captain_id,
            sixth_man_id=oracle_lineup.sixth_man_id,
            bench_ids=oracle_lineup.bench_ids,
            head_coach_id=oracle_lineup.head_coach_id,
            actuals_by_id=actuals_by_id,
        )

        best_starter_actual = max(actuals_by_id[sid] for sid in model_lineup.starter_ids)
        chosen_cap_actual = actuals_by_id[model_lineup.captain_id]
        cap_reg = max(0.0, round(best_starter_actual - chosen_cap_actual, 2))

        non_starters = [model_lineup.sixth_man_id] + list(model_lineup.bench_ids)
        best_non_starter_actual = max(actuals_by_id[nid] for nid in non_starters)
        chosen_sixth_actual = actuals_by_id[model_lineup.sixth_man_id]
        # Moving a bench unit (0.5x) to 6th man (1.0x) yields 0.5 * (best_non_starter - chosen_sixth)
        sixth_reg = max(0.0, round(0.5 * (best_non_starter_actual - chosen_sixth_actual), 2))

        oracle_bench_half = 0.5 * sum(actuals_by_id[bid] for bid in oracle_lineup.bench_ids)
        model_bench_half = 0.5 * sum(actuals_by_id[bid] for bid in model_lineup.bench_ids)
        bench_reg = max(0.0, round(oracle_bench_half - model_bench_half, 2))

        oracle_starters_sum = sum(actuals_by_id[sid] for sid in oracle_lineup.starter_ids)
        model_starters_sum = sum(actuals_by_id[sid] for sid in model_lineup.starter_ids)
        form_reg = max(0.0, round(oracle_starters_sum - model_starters_sum, 2))

        rec_scores.append(actual_score)
        oracle_scores.append(oracle_score)
        lineup_regrets.append(max(0.0, round(oracle_score - actual_score, 2)))
        cap_regrets.append(cap_reg)
        sixth_regrets.append(sixth_reg)
        bench_regrets.append(bench_reg)
        form_regrets.append(form_reg)

    n = len(rec_scores)
    return DecisionEvaluationSummary(
        model_name=model_name,
        rounds_evaluated=n,
        avg_recommended_actual_score=round(sum(rec_scores) / n, 2),
        avg_oracle_actual_score=round(sum(oracle_scores) / n, 2),
        avg_lineup_regret=round(sum(lineup_regrets) / n, 2),
        avg_captain_regret=round(sum(cap_regrets) / n, 2),
        avg_sixth_man_regret=round(sum(sixth_regrets) / n, 2),
        avg_bench_regret=round(sum(bench_regrets) / n, 2),
        avg_formation_regret=round(sum(form_regrets) / n, 2),
    )


@dataclass(frozen=True, slots=True)
class PairedModelComparison:
    """Head-to-head paired model comparison across matched player-round observations (Phase A)."""

    model_a: str
    model_b: str
    sample_count: int
    delta_mae: float  # MAE(A) - MAE(B) (<0 means A is better)
    delta_mae_ci95: float
    delta_rmse: float  # RMSE(A) - RMSE(B) (<0 means A is better)
    delta_spearman: float  # Spearman(A) - Spearman(B) (>0 means A is better)
    delta_top10_recall: float  # Top10(A) - Top10(B) (>0 means A is better)
    delta_value_spearman: float  # ValSpearman(A) - ValSpearman(B) (>0 means A is better)
    delta_lineup_score: float  # Score(A) - Score(B) (>0 means A is better)
    delta_captain_regret: float  # Regret(A) - Regret(B) (<0 means A is better)


def compute_paired_model_comparison(
    records_a: Sequence[PredictionRecord],
    records_b: Sequence[PredictionRecord],
    decision_summary_a: DecisionEvaluationSummary | None = None,
    decision_summary_b: DecisionEvaluationSummary | None = None,
) -> PairedModelComparison:
    """Compute paired differences with confidence intervals between two model prediction sets."""
    if not records_a or not records_b:
        raise ValueError("Cannot compute paired comparison with empty records.")

    map_b = {(r.season, r.round, r.player_id): r for r in records_b if r.position != "HC"}
    pairs: list[tuple[PredictionRecord, PredictionRecord]] = []
    for ra in records_a:
        if ra.position == "HC":
            continue
        key = (ra.season, ra.round, ra.player_id)
        if key in map_b:
            pairs.append((ra, map_b[key]))

    if not pairs:
        raise ValueError("No common player-round observations found between models.")

    diff_ae: list[float] = []
    for ra, rb in pairs:
        err_a = abs(ra.prediction - ra.actual_fantasy_points)
        err_b = abs(rb.prediction - rb.actual_fantasy_points)
        diff_ae.append(err_a - err_b)

    n = len(diff_ae)
    mean_diff_ae = sum(diff_ae) / n
    var_diff_ae = sum((d - mean_diff_ae) ** 2 for d in diff_ae) / max(1, n - 1)
    se_mae = math.sqrt(var_diff_ae / n)
    ci95 = 1.96 * se_mae

    rmse_a = math.sqrt(sum((ra.prediction - ra.actual_fantasy_points) ** 2 for ra, _ in pairs) / n)
    rmse_b = math.sqrt(sum((rb.prediction - rb.actual_fantasy_points) ** 2 for _, rb in pairs) / n)
    delta_rmse = rmse_a - rmse_b

    # Round-level ranking comparisons
    by_round_a: dict[tuple[str, int], list[PredictionRecord]] = {}
    by_round_b: dict[tuple[str, int], list[PredictionRecord]] = {}
    for ra, rb in pairs:
        r_key = (ra.season, ra.round)
        by_round_a.setdefault(r_key, []).append(ra)
        by_round_b.setdefault(r_key, []).append(rb)

    sp_diffs: list[float] = []
    t10_diffs: list[float] = []
    vsp_diffs: list[float] = []

    for r_key in sorted(by_round_a.keys()):
        list_a = by_round_a[r_key]
        list_b = by_round_b[r_key]
        p_a = [x.prediction for x in list_a]
        p_b = [x.prediction for x in list_b]
        y_act = [x.actual_fantasy_points for x in list_a]
        sp_a = spearman_correlation(p_a, y_act)
        sp_b = spearman_correlation(p_b, y_act)
        sp_diffs.append(sp_a - sp_b)

        t10_a = top_k_recall(p_a, y_act, k=10)
        t10_b = top_k_recall(p_b, y_act, k=10)
        t10_diffs.append(t10_a - t10_b)

        v_a = [x.prediction / max(4.0, x.quotation_at_decision_tenths / 10.0) for x in list_a]
        v_b = [x.prediction / max(4.0, x.quotation_at_decision_tenths / 10.0) for x in list_b]
        v_act = [x.actual_fantasy_points / max(4.0, x.quotation_at_decision_tenths / 10.0) for x in list_a]
        vsp_a = spearman_correlation(v_a, v_act)
        vsp_b = spearman_correlation(v_b, v_act)
        vsp_diffs.append(vsp_a - vsp_b)

    d_lineup = 0.0
    d_cap_reg = 0.0
    if decision_summary_a is not None and decision_summary_b is not None:
        d_lineup = decision_summary_a.avg_recommended_actual_score - decision_summary_b.avg_recommended_actual_score
        d_cap_reg = decision_summary_a.avg_captain_regret - decision_summary_b.avg_captain_regret

    return PairedModelComparison(
        model_a=records_a[0].model_name,
        model_b=records_b[0].model_name,
        sample_count=n,
        delta_mae=round(mean_diff_ae, 3),
        delta_mae_ci95=round(ci95, 3),
        delta_rmse=round(delta_rmse, 3),
        delta_spearman=round(sum(sp_diffs) / len(sp_diffs), 4) if sp_diffs else 0.0,
        delta_top10_recall=round(sum(t10_diffs) / len(t10_diffs), 4) if t10_diffs else 0.0,
        delta_value_spearman=round(sum(vsp_diffs) / len(vsp_diffs), 4) if vsp_diffs else 0.0,
        delta_lineup_score=round(d_lineup, 2),
        delta_captain_regret=round(d_cap_reg, 2),
    )
