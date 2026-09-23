"""Multi-round short-horizon planning optimizer (Phase H) for V0.4."""

from dataclasses import dataclass
from typing import Mapping, Sequence

from ..models import Player
from .candidates import CandidateGenerator
from .constraints import OptimizationConstraints, PlayerProjectionContract
from .lineup import FixedSquadLineupOptimizer, OptimalLineupDecision
from .transfers import TransferOptimizer, TransferRecommendation


@dataclass(frozen=True, slots=True)
class RoundDecisionStep:
    """Action plan and optimal lineup for a specific round in the multi-round horizon."""

    round_number: int
    transfers: TransferRecommendation | None
    lineup: OptimalLineupDecision
    bank_tenths_end_of_round: int
    expected_round_score: float


@dataclass(frozen=True, slots=True)
class MultiRoundPlan:
    """Complete multi-round transfer and lineup strategy over horizon N=2..4."""

    start_round: int
    horizon: int
    steps: tuple[RoundDecisionStep, ...]
    total_expected_score: float
    discounted_expected_score: float
    final_bank_tenths: int


class MultiRoundOptimizer:
    """Short-horizon multi-round dynamic optimizer."""

    def __init__(
        self,
        constraints: OptimizationConstraints | None = None,
        discount_factor: float = 0.95,
        max_trades_per_round: int = 2,
        branching_factor: int = 4,
    ) -> None:
        self.constraints = constraints or OptimizationConstraints()
        self.discount_factor = discount_factor
        self.max_trades_per_round = max_trades_per_round
        self.branching_factor = branching_factor
        self.lineup_optimizer = FixedSquadLineupOptimizer(constraints=self.constraints, include_option_value=False)
        self.candidate_generator = CandidateGenerator(constraints=self.constraints, max_candidates_per_pos=6)
        self.transfer_optimizer = TransferOptimizer(
            constraints=self.constraints,
            lineup_optimizer=self.lineup_optimizer,
            candidate_generator=self.candidate_generator,
        )

    def optimize_multi_round(
        self,
        start_round: int,
        horizon: int,
        initial_squad: Sequence[PlayerProjectionContract | Player],
        projections_by_round: Mapping[int, Sequence[PlayerProjectionContract]],
        initial_bank_tenths: int = 0,
    ) -> MultiRoundPlan:
        """Find the optimal sequential plan over rounds [start_round, start_round + horizon - 1]."""
        horizon = max(1, min(horizon, 4))
        rounds = [start_round + i for i in range(horizon)]

        # State representation for search:
        # (cumulative_discounted_score, cumulative_raw_score, current_squad_ids, current_bank, steps_tuple)
        initial_contracts = [
            p if isinstance(p, PlayerProjectionContract) else PlayerProjectionContract.from_player(p)
            for p in initial_squad
        ]

        states: list[tuple[float, float, list[PlayerProjectionContract], int, list[RoundDecisionStep]]] = [
            (0.0, 0.0, initial_contracts, initial_bank_tenths, [])
        ]

        for step_idx, r_num in enumerate(rounds):
            discount = self.discount_factor ** step_idx
            market_r = projections_by_round.get(r_num, ())
            proj_dict = {p.player_id: p for p in market_r}

            next_states: list[tuple[float, float, list[PlayerProjectionContract], int, list[RoundDecisionStep]]] = []

            for cum_disc, cum_raw, squad_units, bank, prior_steps in states:
                # Update squad units to round r_num projections
                updated_squad = [
                    proj_dict.get(p.player_id, p) for p in squad_units
                ]

                # Option 0: No transfers (hold current squad)
                hold_lineup = self.lineup_optimizer.optimize(
                    updated_squad, round_number=r_num, top_alternatives=0
                )
                hold_step = RoundDecisionStep(
                    round_number=r_num,
                    transfers=None,
                    lineup=hold_lineup,
                    bank_tenths_end_of_round=bank,
                    expected_round_score=hold_lineup.expected_score,
                )
                next_states.append((
                    cum_disc + discount * hold_lineup.expected_score,
                    cum_raw + hold_lineup.expected_score,
                    updated_squad,
                    bank,
                    prior_steps + [hold_step],
                ))

                # Options 1..K: legal transfers
                trans_res = self.transfer_optimizer.optimize_transfers(
                    current_squad=updated_squad,
                    market=market_r,
                    bank_tenths=bank,
                    round_number=r_num,
                    max_trades=self.max_trades_per_round,
                    top_n=self.branching_factor,
                )

                for rec in trans_res.recommendations:
                    out_ids = {p.player_id for p in rec.out_players}
                    new_squad = [p for p in updated_squad if p.player_id not in out_ids] + list(rec.in_players)
                    trade_step = RoundDecisionStep(
                        round_number=r_num,
                        transfers=rec,
                        lineup=rec.new_lineup,
                        bank_tenths_end_of_round=rec.remaining_bank_tenths,
                        expected_round_score=rec.new_lineup.expected_score,
                    )
                    next_states.append((
                        cum_disc + discount * rec.new_lineup.expected_score,
                        cum_raw + rec.new_lineup.expected_score,
                        new_squad,
                        rec.remaining_bank_tenths,
                        prior_steps + [trade_step],
                    ))

            # Prune next_states to top branching factor to maintain bounded beam search
            next_states.sort(key=lambda s: s[0], reverse=True)
            states = next_states[: self.branching_factor]

        best_disc, best_raw, final_squad, final_bank, best_steps = states[0]

        return MultiRoundPlan(
            start_round=start_round,
            horizon=horizon,
            steps=tuple(best_steps),
            total_expected_score=round(best_raw, 2),
            discounted_expected_score=round(best_disc, 2),
            final_bank_tenths=final_bank,
        )
