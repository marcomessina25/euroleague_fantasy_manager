"""Single-round transfer optimizer for V0.4 (Phase F)."""

from collections import Counter
from dataclasses import dataclass
from itertools import combinations, product
from typing import Mapping, Sequence

from ..models import Player, Position
from .candidates import CandidateGenerator, CandidatePool
from .constraints import (
    OptimizationConstraints,
    PlayerProjectionContract,
    validate_transfers_constraints,
)
from .lineup import FixedSquadLineupOptimizer, OptimalLineupDecision
from .objective import RiskMode


@dataclass(frozen=True, slots=True)
class TransferRecommendation:
    """A concrete evaluated legal transfer package and resulting lineup."""

    out_players: tuple[PlayerProjectionContract, ...]
    in_players: tuple[PlayerProjectionContract, ...]
    remaining_bank_tenths: int
    new_lineup: OptimalLineupDecision
    gross_score_gain: float
    transfer_cost: float
    net_transfer_value: float

    @property
    def trade_count(self) -> int:
        return len(self.out_players)


@dataclass(frozen=True, slots=True)
class TransferOptimizationResult:
    """Summary of transfer optimization across trade counts."""

    round_number: int | None
    current_lineup: OptimalLineupDecision
    recommendations: tuple[TransferRecommendation, ...]
    total_evaluated_packages: int
    is_exhaustive: bool


class TransferOptimizer:
    """Evaluate and recommend optimal legal 1..4 transfers."""

    def __init__(
        self,
        constraints: OptimizationConstraints | None = None,
        lineup_optimizer: FixedSquadLineupOptimizer | None = None,
        candidate_generator: CandidateGenerator | None = None,
        transfer_penalty_cost: float = 0.0,
    ) -> None:
        self.constraints = constraints or OptimizationConstraints()
        self.lineup_optimizer = lineup_optimizer or FixedSquadLineupOptimizer(
            constraints=self.constraints
        )
        self.candidate_generator = candidate_generator or CandidateGenerator(
            constraints=self.constraints
        )
        self.transfer_penalty_cost = transfer_penalty_cost

    def optimize_transfers(
        self,
        current_squad: Sequence[PlayerProjectionContract | Player],
        market: Sequence[PlayerProjectionContract | Player],
        bank_tenths: int = 0,
        round_number: int | None = None,
        max_trades: int = 1,
        unlimited: bool = False,
        exhaustive_candidates: bool = False,
        top_n: int = 5,
        market_projections: Mapping[int, PlayerProjectionContract] | None = None,
    ) -> TransferOptimizationResult:
        """Find the top legal trade packages ranked by net score gain."""
        # 1. Normalize current squad
        squad_contracts: list[PlayerProjectionContract] = []
        for p in current_squad:
            if isinstance(p, PlayerProjectionContract):
                squad_contracts.append(p)
            else:
                proj = market_projections.get(p.id) if market_projections else None
                if proj is not None:
                    squad_contracts.append(proj)
                else:
                    squad_contracts.append(PlayerProjectionContract.from_player(p))

        # 2. Normalize market
        market_contracts: list[PlayerProjectionContract] = []
        for p in market:
            if isinstance(p, PlayerProjectionContract):
                market_contracts.append(p)
            else:
                proj = market_projections.get(p.id) if market_projections else None
                if proj is not None:
                    market_contracts.append(proj)
                else:
                    market_contracts.append(PlayerProjectionContract.from_player(p))

        # 3. Base lineup of current squad
        current_lineup = self.lineup_optimizer.optimize(
            squad_contracts, round_number=round_number, top_alternatives=0
        )
        current_score = current_lineup.objective_value

        # 4. Generate candidate pool per position
        candidate_pool = self.candidate_generator.generate_candidates(
            market=market_contracts,
            current_squad=squad_contracts,
            exhaustive=exhaustive_candidates,
        )

        all_recommendations: list[TransferRecommendation] = []
        evaluated_count = 0

        effective_max_trades = min(max_trades, 4) if not unlimited else min(max_trades, 11)

        # 5. Evaluate trade counts 1..effective_max_trades
        for k in range(1, effective_max_trades + 1):
            for out_combo in combinations(squad_contracts, k):
                out_ids = [p.player_id for p in out_combo]
                out_positions = Counter(p.position for p in out_combo)

                # Group candidate options by position required
                pos_candidate_lists: list[Sequence[PlayerProjectionContract]] = []
                valid_positions = True
                for pos, count in out_positions.items():
                    cands = candidate_pool.for_position(pos)
                    if not exhaustive_candidates and count >= 2:
                        cands = cands[:6]
                    if len(cands) < count:
                        valid_positions = False
                        break
                    # We need combinations of 'count' from cands
                    pos_combos = list(combinations(cands, count))
                    pos_candidate_lists.append(pos_combos)

                if not valid_positions:
                    continue

                # Cartesian product across the different positions
                for in_tuple_of_tuples in product(*pos_candidate_lists):
                    # Flatten the chosen incoming players
                    in_players: list[PlayerProjectionContract] = []
                    for sub_tuple in in_tuple_of_tuples:
                        in_players.extend(sub_tuple)

                    # Mathematical upper bound pruning
                    max_in_pts = 2.0 * sum(p.expected_fp for p in in_players)
                    min_out_pts = 0.5 * sum(p.expected_fp for p in out_combo)
                    if max_in_pts < min_out_pts:
                        continue

                    evaluated_count += 1

                    # Quick pre-filter: financial feasibility
                    sales_val = sum(p.price_tenths for p in out_combo)
                    purchases_val = sum(p.price_tenths for p in in_players)
                    if bank_tenths + sales_val < purchases_val:
                        continue

                    # Validate transfer constraints
                    val_res, new_bank = validate_transfers_constraints(
                        current_squad=squad_contracts,
                        out_ids=out_ids,
                        in_players=in_players,
                        bank_tenths=bank_tenths,
                        constraints=self.constraints,
                    )
                    if not val_res.is_valid:
                        continue

                    # Construct new squad
                    out_set = set(out_ids)
                    remaining = [p for p in squad_contracts if p.player_id not in out_set]
                    new_squad = remaining + in_players

                    # Optimize lineup for new squad
                    new_lineup = self.lineup_optimizer.optimize(
                        new_squad, round_number=round_number, top_alternatives=0
                    )
                    gross_gain = round(new_lineup.objective_value - current_score, 2)
                    cost = self.transfer_penalty_cost * k
                    net_val = round(gross_gain - cost, 2)

                    rec = TransferRecommendation(
                        out_players=tuple(out_combo),
                        in_players=tuple(in_players),
                        remaining_bank_tenths=new_bank,
                        new_lineup=new_lineup,
                        gross_score_gain=gross_gain,
                        transfer_cost=cost,
                        net_transfer_value=net_val,
                    )
                    all_recommendations.append(rec)

        # 6. Rank recommendations by net transfer value desc, remaining bank desc
        all_recommendations.sort(
            key=lambda r: (
                r.net_transfer_value,
                r.gross_score_gain,
                r.remaining_bank_tenths,
                -r.trade_count,
            ),
            reverse=True,
        )

        return TransferOptimizationResult(
            round_number=round_number,
            current_lineup=current_lineup,
            recommendations=tuple(all_recommendations[:top_n]),
            total_evaluated_packages=evaluated_count,
            is_exhaustive=candidate_pool.is_exhaustive,
        )
