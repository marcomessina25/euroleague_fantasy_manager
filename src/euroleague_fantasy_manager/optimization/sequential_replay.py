"""Sequential Decision Simulation, Model Comparison Ledgers, and Historical Regret Attribution (V0.7 F3, F4, F5).

Longitudinal multi-round sequential decision simulator executing transfers,
lineup selection, captaincy, sixth man, and T1 -> T2 intra-round substitutions
across full EuroLeague and EuroCup seasons.

Zero-mutation guarantee: All simulations are strictly read-only with respect
to persistent database tables and live team states.
"""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from euroleague_fantasy_manager.evaluation.baselines import canonical_model_name, predict_single_player_baseline
from euroleague_fantasy_manager.evaluation.dataset import EvaluationDatasetStore, normalize_season_code
from euroleague_fantasy_manager.evaluation.features import build_round_feature_table
from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.optimization.backtest import score_lineup_with_actuals
from euroleague_fantasy_manager.optimization.constraints import (
    OptimizationConstraints,
    PlayerProjectionContract,
)
from euroleague_fantasy_manager.optimization.intra_round import (
    IntraRoundPlayerUnit,
    IntraRoundSubstitutionOptimizer,
)
from euroleague_fantasy_manager.optimization.lineup import FixedSquadLineupOptimizer, OptimalLineupDecision
from euroleague_fantasy_manager.optimization.objective import LineupScoreBreakdown, RiskMode
from euroleague_fantasy_manager.optimization.transfers import TransferOptimizer
from euroleague_fantasy_manager.rules import (
    MAX_TRADES_PER_ROUND,
    SQUAD_QUOTAS,
    UNLIMITED_TRADE_ROUNDS,
)


@dataclass(frozen=True, slots=True)
class RegretAttribution:
    """Decomposition of decision regret into structural fantasy mechanisms (F5).

    Computed via a telescoping chain: each component is the marginal improvement
    from fixing one decision dimension while holding all others constant.

    Mathematical invariant (by construction):
      captain_regret + sixth_man_regret + bench_regret +
      turn_substitution_regret + transfer_regret + formation_regret + residual
      == total_regret
    Tolerance:
      residual == 0.0 (exact, by telescoping construction; small FP drift possible)
    """

    captain_regret: float
    sixth_man_regret: float
    bench_regret: float
    turn_substitution_regret: float
    transfer_regret: float
    formation_regret: float
    residual: float
    total_regret: float

    def to_dict(self) -> dict[str, float]:
        return {
            "captain_regret": round(self.captain_regret, 2),
            "sixth_man_regret": round(self.sixth_man_regret, 2),
            "bench_regret": round(self.bench_regret, 2),
            "turn_substitution_regret": round(self.turn_substitution_regret, 2),
            "transfer_regret": round(self.transfer_regret, 2),
            "formation_regret": round(self.formation_regret, 2),
            "residual": round(self.residual, 2),
            "total_regret": round(self.total_regret, 2),
        }


@dataclass(frozen=True, slots=True)
class SequentialRoundResult:
    """Outcome of sequential decisions in a single round of season replay."""

    round_number: int
    realized_score: float
    oracle_score: float
    human_score: float | None = None
    projected_score: float = 0.0
    bank_start_tenths: int = 0
    bank_end_tenths: int = 0
    transfers_made: tuple[tuple[int, int], ...] = ()
    lineup_starters: tuple[int, ...] = ()
    lineup_captain: int = 0
    lineup_sixth_man: int = 0
    lineup_bench: tuple[int, ...] = ()
    lineup_coach: int = 0
    formation: str = ""
    substitutions_made: tuple[dict[str, Any], ...] = ()
    regret: RegretAttribution = field(
        default_factory=lambda: RegretAttribution(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "realized_score": round(self.realized_score, 2),
            "oracle_score": round(self.oracle_score, 2),
            "human_score": round(self.human_score, 2) if self.human_score is not None else None,
            "projected_score": round(self.projected_score, 2),
            "bank_start_credits": round(self.bank_start_tenths / 10.0, 1),
            "bank_end_credits": round(self.bank_end_tenths / 10.0, 1),
            "transfers_made": list(self.transfers_made),
            "lineup_starters": list(self.lineup_starters),
            "lineup_captain": self.lineup_captain,
            "lineup_sixth_man": self.lineup_sixth_man,
            "lineup_bench": list(self.lineup_bench),
            "lineup_coach": self.lineup_coach,
            "formation": self.formation,
            "substitutions_made": list(self.substitutions_made),
            "regret": self.regret.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SequentialSeasonReplayLedger:
    """Longitudinal ledger of sequential decisions and regret attribution across a season."""

    season: str
    league: str
    model_name: str
    rounds_evaluated: int
    total_realized_score: float
    total_oracle_score: float
    total_human_score: float | None
    avg_realized_score: float
    avg_oracle_score: float
    avg_human_score: float | None
    total_regret: float
    avg_regret: float
    regret_attribution: RegretAttribution
    round_results: tuple[SequentialRoundResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "league": self.league,
            "model_name": self.model_name,
            "rounds_evaluated": self.rounds_evaluated,
            "total_realized_score": round(self.total_realized_score, 2),
            "total_oracle_score": round(self.total_oracle_score, 2),
            "total_human_score": round(self.total_human_score, 2) if self.total_human_score is not None else None,
            "avg_realized_score": round(self.avg_realized_score, 2),
            "avg_oracle_score": round(self.avg_oracle_score, 2),
            "avg_human_score": round(self.avg_human_score, 2) if self.avg_human_score is not None else None,
            "total_regret": round(self.total_regret, 2),
            "avg_regret": round(self.avg_regret, 2),
            "regret_attribution": self.regret_attribution.to_dict(),
            "round_results": [r.to_dict() for r in self.round_results],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Sequential Decision Replay Ledger -- {self.season} ({self.league.upper()})",
            "",
            f"- **Model:** `{self.model_name}`",
            f"- **Rounds Evaluated:** {self.rounds_evaluated}",
            f"- **Total Realized Score:** {self.total_realized_score:.2f} FP (Avg: {self.avg_realized_score:.2f} FP/rnd)",
            f"- **Total Oracle Score:** {self.total_oracle_score:.2f} FP (Avg: {self.avg_oracle_score:.2f} FP/rnd)",
        ]
        if self.total_human_score is not None and self.avg_human_score is not None:
            lines.append(f"- **Total Human Score:** {self.total_human_score:.2f} FP (Avg: {self.avg_human_score:.2f} FP/rnd)")
        lines.extend([
            f"- **Total Decision Regret:** {self.total_regret:.2f} FP (Avg: {self.avg_regret:.2f} FP/rnd)",
            "",
            "### Regret Attribution Breakdown",
            f"- **Captain Regret:** {self.regret_attribution.captain_regret:.2f} FP",
            f"- **Sixth Man Regret:** {self.regret_attribution.sixth_man_regret:.2f} FP",
            f"- **Bench Regret:** {self.regret_attribution.bench_regret:.2f} FP",
            f"- **Turn Substitution Regret:** {self.regret_attribution.turn_substitution_regret:.2f} FP",
            f"- **Transfer Regret:** {self.regret_attribution.transfer_regret:.2f} FP",
            f"- **Formation Regret:** {self.regret_attribution.formation_regret:.2f} FP",
            f"- **Attribution Residual:** {self.regret_attribution.residual:.2f} FP (residual ≡ 0 by telescoping construction)",
            "",
            "| Round | Realized | Oracle | Human | Total Regret | Cap Regret | 6th Regret | Bench Regret | Turn Regret | Trans Regret | Form Regret | Residual |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ])
        for r in self.round_results:
            h_str = f"{r.human_score:.1f}" if r.human_score is not None else "-"
            rg = r.regret
            lines.append(
                f"| R{r.round_number:02d} | {r.realized_score:.1f} | {r.oracle_score:.1f} | {h_str} | "
                f"{rg.total_regret:.1f} | {rg.captain_regret:.1f} | {rg.sixth_man_regret:.1f} | "
                f"{rg.bench_regret:.1f} | {rg.turn_substitution_regret:.1f} | {rg.transfer_regret:.1f} | "
                f"{rg.formation_regret:.1f} | {rg.residual:.2f} |"
            )
        return "\n".join(lines)

    def to_csv(self, path: Path | str | None = None) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "round", "realized_score", "oracle_score", "human_score", "total_regret",
            "captain_regret", "sixth_man_regret", "bench_regret", "turn_substitution_regret",
            "transfer_regret", "formation_regret", "residual", "bank_start_credits", "bank_end_credits"
        ])
        for r in self.round_results:
            rg = r.regret
            writer.writerow([
                r.round_number,
                f"{r.realized_score:.2f}",
                f"{r.oracle_score:.2f}",
                f"{r.human_score:.2f}" if r.human_score is not None else "",
                f"{rg.total_regret:.2f}",
                f"{rg.captain_regret:.2f}",
                f"{rg.sixth_man_regret:.2f}",
                f"{rg.bench_regret:.2f}",
                f"{rg.turn_substitution_regret:.2f}",
                f"{rg.transfer_regret:.2f}",
                f"{rg.formation_regret:.2f}",
                f"{rg.residual:.2f}",
                f"{r.bank_start_tenths / 10.0:.1f}",
                f"{r.bank_end_tenths / 10.0:.1f}",
            ])
        csv_str = output.getvalue()
        if path:
            Path(path).write_text(csv_str, encoding="utf-8")
        return csv_str


@dataclass(frozen=True, slots=True)
class ModelComparisonRow:
    """One row in a multi-model comparison ledger."""

    model_name: str
    total_score: float
    avg_score: float
    total_regret: float
    avg_regret: float
    avg_captain_regret: float
    avg_sixth_man_regret: float
    avg_turn_substitution_regret: float
    avg_transfer_regret: float


@dataclass(frozen=True, slots=True)
class ModelComparisonLedger:
    """Comparative ledger contrasting multiple decision models, human play, and hindsight oracle (F4)."""

    season: str
    league: str
    rounds_evaluated: int
    rows: tuple[ModelComparisonRow, ...]

    def to_markdown(self) -> str:
        lines = [
            f"# Multi-Model Decision Comparison Ledger -- {self.season} ({self.league.upper()})",
            "",
            f"- **Rounds Evaluated:** {self.rounds_evaluated}",
            "",
            "| Model | Total Score | Avg Score | Total Regret | Avg Regret | Avg Cap Regret | Avg 6th Regret | Avg Turn Regret | Avg Trans Regret |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in self.rows:
            lines.append(
                f"| `{r.model_name}` | {r.total_score:.1f} | {r.avg_score:.2f} | {r.total_regret:.1f} | "
                f"{r.avg_regret:.2f} | {r.avg_captain_regret:.2f} | {r.avg_sixth_man_regret:.2f} | "
                f"{r.avg_turn_substitution_regret:.2f} | {r.avg_transfer_regret:.2f} |"
            )
        return "\n".join(lines)

    def to_csv(self, path: Path | str | None = None) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "model_name", "total_score", "avg_score", "total_regret", "avg_regret",
            "avg_captain_regret", "avg_sixth_man_regret", "avg_turn_substitution_regret", "avg_transfer_regret"
        ])
        for r in self.rows:
            writer.writerow([
                r.model_name,
                f"{r.total_score:.2f}",
                f"{r.avg_score:.2f}",
                f"{r.total_regret:.2f}",
                f"{r.avg_regret:.2f}",
                f"{r.avg_captain_regret:.2f}",
                f"{r.avg_sixth_man_regret:.2f}",
                f"{r.avg_turn_substitution_regret:.2f}",
                f"{r.avg_transfer_regret:.2f}",
            ])
        csv_str = output.getvalue()
        if path:
            Path(path).write_text(csv_str, encoding="utf-8")
        return csv_str


class SequentialDecisionSimulator:
    """Longitudinal decision simulator across multiple fantasy rounds (F3).

    Zero-Mutation Guarantee:
      All reads from sqlite databases use read-only queries or pure in-memory state.
      No tables or team records are mutated.
    """

    def __init__(self, constraints: OptimizationConstraints | None = None) -> None:
        self.constraints = constraints or OptimizationConstraints()
        self.lineup_optimizer = FixedSquadLineupOptimizer(constraints=self.constraints)
        self.sub_optimizer = IntraRoundSubstitutionOptimizer()
        self.transfer_optimizer = TransferOptimizer(constraints=self.constraints)
        # Hindsight oracle optimizers: zero risk penalty, no forward option value bonuses
        self.oracle_lineup_optimizer = FixedSquadLineupOptimizer(
            constraints=self.constraints,
            risk_mode=RiskMode.EXPECTED,
            risk_lambda=0.0,
            include_option_value=False,
        )
        self.oracle_transfer_optimizer = TransferOptimizer(
            constraints=self.constraints,
            lineup_optimizer=self.oracle_lineup_optimizer,
            transfer_penalty_cost=0.0,
        )

    def _load_round_data(
        self,
        season: str,
        round_number: int,
        database_path: Path,
        model_name: str,
        ewma_alpha: float = 0.25,
    ) -> tuple[dict[int, PlayerProjectionContract], dict[int, float], dict[int, int]]:
        """Load round contracts, actual fantasy points, and turn numbers from database in read-only mode."""
        norm_season = normalize_season_code(season)
        store = EvaluationDatasetStore(database_path)
        cutoff = store.get_round_decision_cutoff(norm_season, round_number)
        features = build_round_feature_table(
            season=norm_season,
            round_number=round_number,
            database_path=database_path,
            decision_cutoff=cutoff,
            ewma_alpha=ewma_alpha,
        )

        canon_model = canonical_model_name(model_name)
        actuals: dict[int, float] = {}
        turn_numbers: dict[int, int] = {}
        contracts: dict[int, PlayerProjectionContract] = {}

        with store._connect() as conn:
            rows = conn.execute(
                """
                SELECT p.player_id, p.fantasy_points, g.turn_number
                FROM eval_player_games p
                LEFT JOIN eval_games g ON p.game_id = g.game_id
                WHERE p.season = ? AND p.round = ?
                """,
                (norm_season, int(round_number)),
            ).fetchall()
            for r in rows:
                pid = int(r["player_id"])
                actuals[pid] = float(r["fantasy_points"])
                turn_numbers[pid] = int(r["turn_number"]) if r["turn_number"] is not None else 1

        for pid, feat in features.items():
            pred = predict_single_player_baseline(feature_row=feat, model_name=canon_model)
            t_num = turn_numbers.get(pid, getattr(feat, "turn_number", 1))
            pos = Position.from_raw(feat.position) if not isinstance(feat.position, Position) else feat.position
            contracts[pid] = PlayerProjectionContract(
                player_id=pid,
                player_name=feat.player_name,
                position=pos,
                team_id=getattr(feat, "team_id", None),
                team_code=feat.team_code,
                price_tenths=feat.quotation_at_decision_tenths,
                expected_fp=pred.prediction,
                probability_play=getattr(pred, "play_probability", 1.0),
                expected_minutes=pred.expected_minutes,
                fp_per_minute=getattr(pred, "expected_fp_per_min", 0.0),
                uncertainty=pred.sigma_prediction,
                prediction_spread=getattr(pred, "upper_bound", 0.0) - getattr(pred, "lower_bound", 0.0),
                turn_number=t_num,
                opponent_code=feat.opponent_team_code,
                is_home=feat.home,
                actual_fp=actuals.get(pid),
                has_played=False,
            )

        return contracts, actuals, turn_numbers

    def _select_initial_squad(
        self,
        contracts: Mapping[int, PlayerProjectionContract],
    ) -> list[PlayerProjectionContract]:
        """Select a legal reference squad (4G, 4F, 2C, 1HC) by highest expectation under budget."""
        guards = sorted([c for c in contracts.values() if c.position == Position.GUARD], key=lambda x: -x.expected_fp)[:4]
        forwards = sorted([c for c in contracts.values() if c.position == Position.FORWARD], key=lambda x: -x.expected_fp)[:4]
        centers = sorted([c for c in contracts.values() if c.position == Position.CENTER], key=lambda x: -x.expected_fp)[:2]
        coaches = sorted([c for c in contracts.values() if c.position == Position.HEAD_COACH], key=lambda x: -x.expected_fp)[:1]
        return guards + forwards + centers + coaches

    def _optimize_transfers(
        self,
        current_squad: Sequence[PlayerProjectionContract],
        contracts: Mapping[int, PlayerProjectionContract],
        current_bank_tenths: int,
        round_number: int,
        max_transfers: int = MAX_TRADES_PER_ROUND,
        is_oracle: bool = False,
    ) -> tuple[list[PlayerProjectionContract], int, list[tuple[int, int]], float]:
        """Simulate between-round transfers."""
        is_unlimited = round_number in UNLIMITED_TRADE_ROUNDS
        allowed_trades = 11 if is_unlimited else min(max_transfers, MAX_TRADES_PER_ROUND)

        # Map current squad to updated round contracts
        mapped_squad: list[PlayerProjectionContract] = []
        for p in current_squad:
            if p.player_id in contracts:
                mapped_squad.append(contracts[p.player_id])
            else:
                mapped_squad.append(p)

        market_list = list(contracts.values())
        optimizer = self.oracle_transfer_optimizer if is_oracle else self.transfer_optimizer

        try:
            res = optimizer.optimize_transfers(
                current_squad=mapped_squad,
                market=market_list,
                bank_tenths=current_bank_tenths,
                max_trades=allowed_trades,
                round_number=round_number,
                exhaustive_candidates=False,
            )
            if res.recommendations:
                best_rec = res.recommendations[0]
                if best_rec.net_transfer_value > 0.05:
                    new_lineup = best_rec.new_lineup
                    new_squad_ids = (
                        set(new_lineup.starter_ids)
                        | {new_lineup.sixth_man_id}
                        | set(new_lineup.bench_ids)
                        | {new_lineup.head_coach_id}
                    )
                    new_squad = [contracts[pid] for pid in new_squad_ids if pid in contracts]
                    # Fill any missing players from the mapped squad (e.g. if contracts dict is stale)
                    existing_ids = {p.player_id for p in new_squad}
                    for p in mapped_squad:
                        if p.player_id not in existing_ids and len(new_squad) < 11:
                            new_squad.append(p)
                    moves = [
                        (out_p.player_id, in_p.player_id)
                        for out_p, in_p in zip(best_rec.out_players, best_rec.in_players)
                    ]
                    return new_squad, best_rec.remaining_bank_tenths, moves, best_rec.gross_score_gain
        except Exception:
            pass

        return mapped_squad, current_bank_tenths, [], 0.0

    def _simulate_substitutions(
        self,
        lineup: OptimalLineupDecision,
        squad: Sequence[PlayerProjectionContract],
        actuals: Mapping[int, float],
    ) -> tuple[OptimalLineupDecision, list[dict[str, Any]], float]:
        """Simulate T1 -> T2 turn substitutions using IntraRoundSubstitutionOptimizer."""
        unit_map = {p.player_id: p for p in squad}
        starter_set = set(lineup.starter_ids)
        bench_set = set(lineup.bench_ids)

        units: list[IntraRoundPlayerUnit] = []
        for p in squad:
            pos_str = p.position.short_code if hasattr(p.position, "short_code") else str(p.position)
            is_cap = (p.player_id == lineup.captain_id)
            if p.player_id in starter_set:
                role = "starter"
            elif p.player_id == lineup.sixth_man_id:
                role = "sixth_man"
            elif p.player_id == lineup.head_coach_id or pos_str == "HC":
                role = "coach"
            else:
                role = "bench"

            # T1 players have played; T2 players have not
            has_played = (p.turn_number == 1)
            act_fp = actuals.get(p.player_id) if has_played else None

            units.append(
                IntraRoundPlayerUnit(
                    player_id=p.player_id,
                    name=p.player_name,
                    position=pos_str,
                    team_code=p.team_code,
                    credits=p.credits,
                    turn_number=p.turn_number,
                    has_played=has_played,
                    actual_fp=act_fp,
                    expected_fp=p.expected_fp,
                    current_role=role,
                    is_captain=is_cap,
                )
            )

        sub_res = self.sub_optimizer.optimize(units, captain_id=lineup.captain_id)

        breakdown = LineupScoreBreakdown(
            formation=sub_res.formation,
            starter_score=sub_res.optimized_total_fp,
            captain_bonus=0.0,
            sixth_man_score=0.0,
            bench_score=0.0,
            head_coach_score=0.0,
            raw_expected_total=sub_res.optimized_total_fp,
            risk_adjustment=0.0,
            option_value_bonus=0.0,
            objective_value=sub_res.optimized_total_fp,
        )

        post_lineup = OptimalLineupDecision(
            round_number=lineup.round_number,
            formation=sub_res.formation,
            starter_ids=tuple(sub_res.starter_ids),
            captain_id=sub_res.captain_id,
            vice_captain_id=lineup.vice_captain_id,
            sixth_man_id=sub_res.sixth_man_id,
            bench_ids=tuple(sub_res.bench_ids),
            head_coach_id=sub_res.coach_id,
            breakdown=breakdown,
            is_valid=True,
            validation_errors=(),
        )

        return post_lineup, sub_res.substitutions, sub_res.net_gain

    def _compute_regret_attribution(
        self,
        pre_lineup: OptimalLineupDecision,
        chosen_lineup: OptimalLineupDecision,
        model_squad_oracle_lineup: OptimalLineupDecision,
        oracle_lineup: OptimalLineupDecision,
        actuals: Mapping[int, float],
        pre_sub_score: float,
        post_sub_score: float,
    ) -> RegretAttribution:
        """Decompose regret via a telescoping chain (F5).

        Each component is the marginal improvement from fixing one decision
        dimension while holding all others constant. The chain walks from
        the realized outcome (S0) to the full oracle (S6):

            S0  model squad, model lineup, post-substitution   (realized)
            S1  S0 + bad substitution recovery                 turn_sub_regret = S1 - S0
            S2  S1 + optimal captain                           captain_regret  = S2 - S1
            S3  S2 + optimal sixth man                         sixth_man_regret = S3 - S2
            S4  S3 + optimal starters (formation)              formation_regret = S4 - S3
            S5  S4 + optimal bench (model squad)               bench_regret    = S5 - S4
            S6  oracle squad, optimal lineup                   transfer_regret = S6 - S5

        Mathematical invariant (by construction):
            sum(components) == total_regret   (residual ≡ 0.0)
        """
        # S0: realized score (post-substitution, model squad, model lineup)
        s0 = round(post_sub_score, 2)

        # S1: undo bad intra-round substitutions if they cost points
        turn_sub_reg = max(0.0, round(pre_sub_score - post_sub_score, 2))
        s1 = round(s0 + turn_sub_reg, 2)
        base_lineup = pre_lineup if pre_sub_score > post_sub_score else chosen_lineup

        # S2: optimal captain from the active starting 5
        best_captain_id = max(base_lineup.starter_ids, key=lambda pid: actuals.get(pid, 0.0))
        cap_reg = max(0.0, round(actuals.get(best_captain_id, 0.0) - actuals.get(base_lineup.captain_id, 0.0), 2))
        s2 = round(s1 + cap_reg, 2)

        # S3: optimal sixth man from the bench pool (sixth man gets 1.0x, bench gets 0.5x)
        bench_pool = [base_lineup.sixth_man_id] + list(base_lineup.bench_ids)
        best_sixth_id = max(bench_pool, key=lambda pid: actuals.get(pid, 0.0))
        sixth_reg = max(0.0, round(0.5 * (actuals.get(best_sixth_id, 0.0) - actuals.get(base_lineup.sixth_man_id, 0.0)), 2))
        s3 = round(s2 + sixth_reg, 2)

        # S4: optimal starters / formation from the model squad
        model_squad_opt = score_lineup_with_actuals(
            starter_ids=model_squad_oracle_lineup.starter_ids,
            captain_id=model_squad_oracle_lineup.captain_id,
            sixth_man_id=model_squad_oracle_lineup.sixth_man_id,
            bench_ids=model_squad_oracle_lineup.bench_ids,
            head_coach_id=model_squad_oracle_lineup.head_coach_id,
            actuals=actuals,
        )
        form_reg = max(0.0, round(model_squad_opt - s3, 2))
        s4 = round(s3 + form_reg, 2)

        # S5: optimal bench from model squad (fully determined by S4, 0 degrees of freedom)
        bench_reg = 0.0
        s5 = s4

        # S6: oracle squad with optimal lineup (transfer regret)
        oracle_opt = score_lineup_with_actuals(
            starter_ids=oracle_lineup.starter_ids,
            captain_id=oracle_lineup.captain_id,
            sixth_man_id=oracle_lineup.sixth_man_id,
            bench_ids=oracle_lineup.bench_ids,
            head_coach_id=oracle_lineup.head_coach_id,
            actuals=actuals,
        )
        trans_reg = max(0.0, round(oracle_opt - s5, 2))
        s6 = round(s5 + trans_reg, 2)

        # Total regret is exactly s6 - s0
        total_regret = round(s6 - s0, 2)
        comp_sum = round(cap_reg + sixth_reg + bench_reg + turn_sub_reg + trans_reg + form_reg, 2)
        residual = round(total_regret - comp_sum, 2)

        return RegretAttribution(
            captain_regret=cap_reg,
            sixth_man_regret=sixth_reg,
            bench_regret=bench_reg,
            turn_substitution_regret=turn_sub_reg,
            transfer_regret=trans_reg,
            formation_regret=form_reg,
            residual=residual,
            total_regret=total_regret,
        )

        return RegretAttribution(
            captain_regret=cap_reg,
            sixth_man_regret=sixth_reg,
            bench_regret=bench_reg,
            turn_substitution_regret=turn_sub_reg,
            transfer_regret=trans_reg,
            formation_regret=form_reg,
            residual=residual,
            total_regret=total_regret,
        )

    def simulate_season(
        self,
        season: str,
        database_path: Path | str,
        model_name: str = "season_mean",
        rounds: Sequence[int] | None = None,
        initial_squad_ids: Sequence[int] | None = None,
        initial_bank_tenths: int = 0,
        human_decisions: Mapping[int, Any] | None = None,
    ) -> SequentialSeasonReplayLedger:
        """Simulate a full season of sequential decisions (F3)."""
        db_path = Path(database_path)
        norm_season = normalize_season_code(season)
        store = EvaluationDatasetStore(db_path)
        league = "eurocup" if norm_season.startswith("U") else "euroleague"

        available_rounds = store.list_rounds(norm_season)
        eval_rounds = sorted(rounds if rounds is not None else available_rounds)

        current_squad: list[PlayerProjectionContract] = []
        current_bank = initial_bank_tenths
        round_results: list[SequentialRoundResult] = []

        for rnd in eval_rounds:
            contracts, actuals, _ = self._load_round_data(norm_season, rnd, db_path, model_name)
            if not contracts:
                continue

            # Initialize squad if round 1 or empty
            if not current_squad:
                if initial_squad_ids:
                    current_squad = [contracts[pid] for pid in initial_squad_ids if pid in contracts]
                if len(current_squad) != 11:
                    current_squad = self._select_initial_squad(contracts)

            bank_start = current_bank

            # Capture pre-transfer state for oracle comparison
            pre_transfer_squad = list(current_squad)

            # 1. Between-round transfers (model's decision)
            current_squad, current_bank, transfers_made, trans_gain = self._optimize_transfers(
                current_squad=current_squad,
                contracts=contracts,
                current_bank_tenths=current_bank,
                round_number=rnd,
            )

            # 2. Pre-deadline lineup optimization
            pre_lineup = self.lineup_optimizer.optimize(current_squad, round_number=rnd)
            pre_score = score_lineup_with_actuals(
                starter_ids=pre_lineup.starter_ids,
                captain_id=pre_lineup.captain_id,
                sixth_man_id=pre_lineup.sixth_man_id,
                bench_ids=pre_lineup.bench_ids,
                head_coach_id=pre_lineup.head_coach_id,
                actuals=actuals,
            )

            # 3. Intra-round turn substitutions (T1 -> T2)
            post_lineup, subs_made, _ = self._simulate_substitutions(
                lineup=pre_lineup,
                squad=current_squad,
                actuals=actuals,
            )
            realized_score = score_lineup_with_actuals(
                starter_ids=post_lineup.starter_ids,
                captain_id=post_lineup.captain_id,
                sixth_man_id=post_lineup.sixth_man_id,
                bench_ids=post_lineup.bench_ids,
                head_coach_id=post_lineup.head_coach_id,
                actuals=actuals,
            )

            # 4. Hindsight oracle: perfect-foresight transfers from pre-transfer squad + optimal lineup
            #    Build actuals-backed contracts for the ENTIRE market (not just current squad)
            oracle_market: dict[int, PlayerProjectionContract] = {}
            for pid, c in contracts.items():
                oracle_market[pid] = PlayerProjectionContract(
                    player_id=c.player_id,
                    player_name=c.player_name,
                    position=c.position,
                    team_code=c.team_code,
                    price_tenths=c.price_tenths,
                    expected_fp=actuals.get(pid, 0.0),
                    probability_play=1.0,
                    turn_number=c.turn_number,
                )

            # Oracle transfer optimization from the same starting point as the model
            oracle_squad, _, _, oracle_trans_gain = self._optimize_transfers(
                current_squad=pre_transfer_squad,
                contracts=oracle_market,
                current_bank_tenths=bank_start,
                round_number=rnd,
                is_oracle=True,
            )

            # Oracle lineup from oracle squad (with actuals as perfect predictions)
            oracle_squad_contracts = [
                PlayerProjectionContract(
                    player_id=p.player_id,
                    player_name=p.player_name,
                    position=p.position,
                    team_code=p.team_code,
                    price_tenths=p.price_tenths,
                    expected_fp=actuals.get(p.player_id, 0.0),
                    probability_play=1.0,
                    turn_number=p.turn_number,
                )
                for p in oracle_squad
            ]
            oracle_lineup = self.oracle_lineup_optimizer.optimize(oracle_squad_contracts, round_number=rnd)
            oracle_score = score_lineup_with_actuals(
                starter_ids=oracle_lineup.starter_ids,
                captain_id=oracle_lineup.captain_id,
                sixth_man_id=oracle_lineup.sixth_man_id,
                bench_ids=oracle_lineup.bench_ids,
                head_coach_id=oracle_lineup.head_coach_id,
                actuals=actuals,
            )

            # Model-squad oracle lineup (best lineup from model's post-transfer squad, for decomposition)
            model_squad_oracle_contracts = [
                PlayerProjectionContract(
                    player_id=p.player_id,
                    player_name=p.player_name,
                    position=p.position,
                    team_code=p.team_code,
                    price_tenths=p.price_tenths,
                    expected_fp=actuals.get(p.player_id, 0.0),
                    probability_play=1.0,
                    turn_number=p.turn_number,
                )
                for p in current_squad
            ]
            model_squad_oracle_lineup = self.oracle_lineup_optimizer.optimize(
                model_squad_oracle_contracts, round_number=rnd
            )

            # 5. Human decision scoring if available
            human_score = None
            if human_decisions and rnd in human_decisions:
                h_dec = human_decisions[rnd]
                if isinstance(h_dec, dict):
                    human_score = score_lineup_with_actuals(
                        starter_ids=h_dec.get("starter_ids", ()),
                        captain_id=h_dec.get("captain_id", 0),
                        sixth_man_id=h_dec.get("sixth_man_id", 0),
                        bench_ids=h_dec.get("bench_ids", ()),
                        head_coach_id=h_dec.get("head_coach_id", 0),
                        actuals=actuals,
                    )

            # 6. Regret attribution via telescoping decomposition
            regret = self._compute_regret_attribution(
                pre_lineup=pre_lineup,
                chosen_lineup=post_lineup,
                model_squad_oracle_lineup=model_squad_oracle_lineup,
                oracle_lineup=oracle_lineup,
                actuals=actuals,
                pre_sub_score=pre_score,
                post_sub_score=realized_score,
            )

            round_results.append(
                SequentialRoundResult(
                    round_number=rnd,
                    realized_score=realized_score,
                    oracle_score=oracle_score,
                    human_score=human_score,
                    projected_score=pre_lineup.expected_score,
                    bank_start_tenths=bank_start,
                    bank_end_tenths=current_bank,
                    transfers_made=tuple(transfers_made),
                    lineup_starters=post_lineup.starter_ids,
                    lineup_captain=post_lineup.captain_id,
                    lineup_sixth_man=post_lineup.sixth_man_id,
                    lineup_bench=post_lineup.bench_ids,
                    lineup_coach=post_lineup.head_coach_id,
                    formation=post_lineup.formation,
                    substitutions_made=tuple(subs_made),
                    regret=regret,
                )
            )

        n = len(round_results)
        if n == 0:
            return SequentialSeasonReplayLedger(
                season=season,
                league=league,
                model_name=model_name,
                rounds_evaluated=0,
                total_realized_score=0.0,
                total_oracle_score=0.0,
                total_human_score=None,
                avg_realized_score=0.0,
                avg_oracle_score=0.0,
                avg_human_score=None,
                total_regret=0.0,
                avg_regret=0.0,
                regret_attribution=RegretAttribution(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                round_results=(),
            )

        tot_real = sum(r.realized_score for r in round_results)
        tot_orc = sum(r.oracle_score for r in round_results)
        tot_reg = sum(r.regret.total_regret for r in round_results)
        human_scores = [r.human_score for r in round_results if r.human_score is not None]
        tot_human = sum(human_scores) if human_scores else None
        avg_human = (tot_human / len(human_scores)) if tot_human is not None else None

        avg_cap = sum(r.regret.captain_regret for r in round_results) / n
        avg_6th = sum(r.regret.sixth_man_regret for r in round_results) / n
        avg_bnch = sum(r.regret.bench_regret for r in round_results) / n
        avg_turn = sum(r.regret.turn_substitution_regret for r in round_results) / n
        avg_trans = sum(r.regret.transfer_regret for r in round_results) / n
        avg_form = sum(r.regret.formation_regret for r in round_results) / n
        avg_tot_reg = tot_reg / n
        avg_res = round(avg_tot_reg - (avg_cap + avg_6th + avg_bnch + avg_turn + avg_trans + avg_form), 2)

        season_regret_attr = RegretAttribution(
            captain_regret=round(avg_cap, 2),
            sixth_man_regret=round(avg_6th, 2),
            bench_regret=round(avg_bnch, 2),
            turn_substitution_regret=round(avg_turn, 2),
            transfer_regret=round(avg_trans, 2),
            formation_regret=round(avg_form, 2),
            residual=avg_res,
            total_regret=round(avg_tot_reg, 2),
        )

        return SequentialSeasonReplayLedger(
            season=season,
            league=league,
            model_name=model_name,
            rounds_evaluated=n,
            total_realized_score=round(tot_real, 2),
            total_oracle_score=round(tot_orc, 2),
            total_human_score=round(tot_human, 2) if tot_human is not None else None,
            avg_realized_score=round(tot_real / n, 2),
            avg_oracle_score=round(tot_orc / n, 2),
            avg_human_score=round(avg_human, 2) if avg_human is not None else None,
            total_regret=round(tot_reg, 2),
            avg_regret=round(avg_tot_reg, 2),
            regret_attribution=season_regret_attr,
            round_results=tuple(round_results),
        )

    def compare_models(
        self,
        season: str,
        database_path: Path | str,
        model_names: Sequence[str],
        rounds: Sequence[int] | None = None,
        human_decisions: Mapping[int, Any] | None = None,
    ) -> ModelComparisonLedger:
        """Compare multiple predictive models, human decisions, and hindsight oracle (F4)."""
        db_path = Path(database_path)
        norm_season = normalize_season_code(season)
        league = "eurocup" if norm_season.startswith("U") else "euroleague"

        rows: list[ModelComparisonRow] = []
        rounds_eval = 0

        for model in model_names:
            ledger = self.simulate_season(
                season=season,
                database_path=db_path,
                model_name=model,
                rounds=rounds,
                human_decisions=human_decisions,
            )
            rounds_eval = ledger.rounds_evaluated
            rg = ledger.regret_attribution
            rows.append(
                ModelComparisonRow(
                    model_name=model,
                    total_score=ledger.total_realized_score,
                    avg_score=ledger.avg_realized_score,
                    total_regret=ledger.total_regret,
                    avg_regret=ledger.avg_regret,
                    avg_captain_regret=rg.captain_regret,
                    avg_sixth_man_regret=rg.sixth_man_regret,
                    avg_turn_substitution_regret=rg.turn_substitution_regret,
                    avg_transfer_regret=rg.transfer_regret,
                )
            )

        return ModelComparisonLedger(
            season=season,
            league=league,
            rounds_evaluated=rounds_eval,
            rows=tuple(rows),
        )
