"""Historical decision backtesting and oracle regret evaluation (Phase L)."""

from dataclasses import dataclass
from typing import Mapping, Sequence

from ..models import Position
from .constraints import OptimizationConstraints, PlayerProjectionContract
from .lineup import FixedSquadLineupOptimizer, OptimalLineupDecision
from .objective import RiskMode


@dataclass(frozen=True, slots=True)
class RoundBacktestResult:
    """Audited backtest outcome for a single historical round."""

    round_number: int
    recommended_score: float
    oracle_score: float
    lineup_regret: float
    captain_regret: float
    sixth_man_regret: float
    bench_regret: float
    formation_regret: float
    recommended_formation: str
    oracle_formation: str
    recommended_captain_id: int
    oracle_captain_id: int
    recommended_sixth_man_id: int
    oracle_sixth_man_id: int


@dataclass(frozen=True, slots=True)
class OptimizationBacktestSummary:
    """Aggregated decision backtest metrics over historical rounds."""

    season: str
    model_name: str
    rounds_evaluated: int
    avg_recommended_score: float
    avg_oracle_score: float
    avg_lineup_regret: float
    avg_captain_regret: float
    avg_sixth_man_regret: float
    avg_bench_regret: float
    avg_formation_regret: float
    round_results: tuple[RoundBacktestResult, ...]

    def to_markdown(self) -> str:
        lines = [
            f"# Decision Optimization Backtest Report -- {self.season}",
            "",
            f"- **Model:** `{self.model_name}`",
            f"- **Rounds Evaluated:** {self.rounds_evaluated}",
            f"- **Avg Recommended Realized Score:** {self.avg_recommended_score:.2f} FP",
            f"- **Avg Oracle Realized Score:** {self.avg_oracle_score:.2f} FP",
            f"- **Avg Lineup Regret:** {self.avg_lineup_regret:.2f} FP",
            f"- **Avg Captain Regret:** {self.avg_captain_regret:.2f} FP",
            f"- **Avg Sixth Man Regret:** {self.avg_sixth_man_regret:.2f} FP",
            f"- **Avg Bench Regret:** {self.avg_bench_regret:.2f} FP",
            f"- **Avg Formation Regret:** {self.avg_formation_regret:.2f} FP",
            "",
            "| Round | Rec Score | Oracle Score | Lineup Regret | Cap Regret | 6th Regret | Bench Regret | Form Regret | Rec Form | Oracle Form |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in self.round_results:
            lines.append(
                f"| R{r.round_number:02d} | {r.recommended_score:.1f} | {r.oracle_score:.1f} | "
                f"{r.lineup_regret:.2f} | {r.captain_regret:.2f} | {r.sixth_man_regret:.2f} | "
                f"{r.bench_regret:.2f} | {r.formation_regret:.2f} | `{r.recommended_formation}` | `{r.oracle_formation}` |"
            )
        return "\n".join(lines)


def score_lineup_with_actuals(
    starter_ids: Sequence[int],
    captain_id: int,
    sixth_man_id: int,
    bench_ids: Sequence[int],
    head_coach_id: int,
    actuals: Mapping[int, float],
) -> float:
    """Calculate the exact realized fantasy score of a lineup given actual game points."""
    starters_sum = sum(actuals.get(sid, 0.0) for sid in starter_ids)
    captain_extra = actuals.get(captain_id, 0.0)
    sixth_man = actuals.get(sixth_man_id, 0.0)
    bench_sum = 0.5 * sum(actuals.get(bid, 0.0) for bid in bench_ids)
    coach = actuals.get(head_coach_id, 0.0)
    return round(starters_sum + captain_extra + sixth_man + bench_sum + coach, 2)


class HistoricalDecisionBacktester:
    """Evaluate decision quality and oracle regret across historical rounds."""

    def __init__(
        self,
        constraints: OptimizationConstraints | None = None,
        risk_mode: RiskMode = RiskMode.EXPECTED,
        risk_lambda: float = 0.15,
    ) -> None:
        self.constraints = constraints or OptimizationConstraints()
        self.risk_mode = risk_mode
        self.risk_lambda = risk_lambda
        self.optimizer = FixedSquadLineupOptimizer(
            constraints=self.constraints,
            risk_mode=self.risk_mode,
            risk_lambda=self.risk_lambda,
            include_option_value=False,  # static hindsight comparison
        )

    def evaluate_round(
        self,
        round_number: int,
        squad_contracts: Sequence[PlayerProjectionContract],
        actuals_by_id: Mapping[int, float],
    ) -> RoundBacktestResult:
        """Evaluate a single round's recommendation and compare with hindsight oracle."""
        # 1. Model's recommended lineup based strictly on pre-round predictions
        rec_decision = self.optimizer.optimize(
            squad_contracts, round_number=round_number, top_alternatives=0
        )

        # 2. Oracle lineup: solved using actual realization as the projection
        oracle_contracts = [
            PlayerProjectionContract(
                player_id=p.player_id,
                player_name=p.player_name,
                position=p.position,
                team_id=p.team_id,
                team_code=p.team_code,
                price_tenths=p.price_tenths,
                expected_fp=actuals_by_id.get(p.player_id, 0.0),
                probability_play=1.0,
                expected_minutes=20.0,
                fp_per_minute=1.0,
                uncertainty=0.0,
                turn_number=1,
            )
            for p in squad_contracts
        ]
        oracle_decision = self.optimizer.optimize(
            oracle_contracts, round_number=round_number, top_alternatives=0
        )

        # 3. Realized scores
        rec_score = score_lineup_with_actuals(
            starter_ids=rec_decision.starter_ids,
            captain_id=rec_decision.captain_id,
            sixth_man_id=rec_decision.sixth_man_id,
            bench_ids=rec_decision.bench_ids,
            head_coach_id=rec_decision.head_coach_id,
            actuals=actuals_by_id,
        )
        oracle_score = score_lineup_with_actuals(
            starter_ids=oracle_decision.starter_ids,
            captain_id=oracle_decision.captain_id,
            sixth_man_id=oracle_decision.sixth_man_id,
            bench_ids=oracle_decision.bench_ids,
            head_coach_id=oracle_decision.head_coach_id,
            actuals=actuals_by_id,
        )

        # 4. Regret components
        lineup_reg = max(0.0, round(oracle_score - rec_score, 2))

        # Captain regret: difference between best possible starter and chosen captain
        best_starter_act = max(actuals_by_id.get(sid, 0.0) for sid in rec_decision.starter_ids)
        chosen_cap_act = actuals_by_id.get(rec_decision.captain_id, 0.0)
        cap_reg = max(0.0, round(best_starter_act - chosen_cap_act, 2))

        # Sixth man regret: bench player moving from 0.5x to 1.0x gives 0.5x gain
        bench_pool = [rec_decision.sixth_man_id] + list(rec_decision.bench_ids)
        best_bench_act = max(actuals_by_id.get(pid, 0.0) for pid in bench_pool)
        chosen_sixth_act = actuals_by_id.get(rec_decision.sixth_man_id, 0.0)
        sixth_reg = max(0.0, round(0.5 * (best_bench_act - chosen_sixth_act), 2))

        # Bench regret: 0.5 * (oracle bench - model bench)
        oracle_bench_fpts = 0.5 * sum(actuals_by_id.get(bid, 0.0) for bid in oracle_decision.bench_ids)
        model_bench_fpts = 0.5 * sum(actuals_by_id.get(bid, 0.0) for bid in rec_decision.bench_ids)
        bench_reg = max(0.0, round(oracle_bench_fpts - model_bench_fpts, 2))

        # Formation regret: difference in court starters sum
        oracle_starters_sum = sum(actuals_by_id.get(sid, 0.0) for sid in oracle_decision.starter_ids)
        model_starters_sum = sum(actuals_by_id.get(sid, 0.0) for sid in rec_decision.starter_ids)
        form_reg = max(0.0, round(oracle_starters_sum - model_starters_sum, 2))

        return RoundBacktestResult(
            round_number=round_number,
            recommended_score=rec_score,
            oracle_score=oracle_score,
            lineup_regret=lineup_reg,
            captain_regret=cap_reg,
            sixth_man_regret=sixth_reg,
            bench_regret=bench_reg,
            formation_regret=form_reg,
            recommended_formation=rec_decision.formation,
            oracle_formation=oracle_decision.formation,
            recommended_captain_id=rec_decision.captain_id,
            oracle_captain_id=oracle_decision.captain_id,
            recommended_sixth_man_id=rec_decision.sixth_man_id,
            oracle_sixth_man_id=oracle_decision.sixth_man_id,
        )

    def evaluate_season(
        self,
        season: str,
        model_name: str,
        rounds_data: Mapping[int, tuple[Sequence[PlayerProjectionContract], Mapping[int, float]]],
    ) -> OptimizationBacktestSummary:
        """Run backtesting across all rounds in a season."""
        results: list[RoundBacktestResult] = []
        for r_num in sorted(rounds_data.keys()):
            contracts, actuals = rounds_data[r_num]
            res = self.evaluate_round(r_num, contracts, actuals)
            results.append(res)

        if not results:
            return OptimizationBacktestSummary(
                season=season,
                model_name=model_name,
                rounds_evaluated=0,
                avg_recommended_score=0.0,
                avg_oracle_score=0.0,
                avg_lineup_regret=0.0,
                avg_captain_regret=0.0,
                avg_sixth_man_regret=0.0,
                avg_bench_regret=0.0,
                avg_formation_regret=0.0,
                round_results=(),
            )

        n = len(results)
        return OptimizationBacktestSummary(
            season=season,
            model_name=model_name,
            rounds_evaluated=n,
            avg_recommended_score=round(sum(r.recommended_score for r in results) / n, 2),
            avg_oracle_score=round(sum(r.oracle_score for r in results) / n, 2),
            avg_lineup_regret=round(sum(r.lineup_regret for r in results) / n, 2),
            avg_captain_regret=round(sum(r.captain_regret for r in results) / n, 2),
            avg_sixth_man_regret=round(sum(r.sixth_man_regret for r in results) / n, 2),
            avg_bench_regret=round(sum(r.bench_regret for r in results) / n, 2),
            avg_formation_regret=round(sum(r.formation_regret for r in results) / n, 2),
            round_results=tuple(results),
        )
