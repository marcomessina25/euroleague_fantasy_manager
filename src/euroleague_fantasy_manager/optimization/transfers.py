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
    """Evaluate and recommend optimal legal 1..4 transfers.

    Search Boundaries:
      - Default mode: Candidate-pruned fast heuristic search. Filters incoming player
        pool using candidate generator and applies mathematical upper-bound pruning
        (2.0 * sum(in) < 0.5 * sum(out)) to eliminate non-viable trade packages.
      - Exhaustive mode (`exhaustive_candidates=True`): Exact search evaluating all
        possible legal transfer combinations within the defined candidate pool.
    """

    def __init__(
        self,
        constraints: OptimizationConstraints | None = None,
        lineup_optimizer: FixedSquadLineupOptimizer | None = None,
        candidate_generator: CandidateGenerator | None = None,
        transfer_penalty_cost: float = 0.0,
    ) -> None:
        """Initialize TransferOptimizer.

        Parameters
        ----------
        constraints : OptimizationConstraints, optional
            Fantasy rules and budget constraints.
        lineup_optimizer : FixedSquadLineupOptimizer, optional
            Inner lineup optimizer for evaluated squads.
        candidate_generator : CandidateGenerator, optional
            Candidate pool generator for incoming targets.
        transfer_penalty_cost : float, default 0.0
            Subjective strategy parameter (not an official fantasy rule) used to penalize
            turnover or preserve trades across rounds. In official EuroLeague Fantasy
            Classic rules, legal scheduled trades incur 0 penalty.
        """
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
        """Find the top legal trade packages ranked by net score gain.

        Parameters
        ----------
        exhaustive_candidates : bool, default False
            When False, uses fast candidate pruning to accelerate large market searches.
            When True, runs exact exhaustive evaluation across all candidate combinations.
        """
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

        # FAST PATH: Unlimited full-squad overhaul solved via MILP squad optimizer when max_trades > 5 or unconstrained
        if unlimited and (max_trades is None or max_trades > 5):
            from .initial_team import optimize_initial_team

            total_budget_tenths = sum(p.price_tenths for p in squad_contracts) + bank_tenths
            total_budget_credits = total_budget_tenths / 10.0

            # The candidate pool for overhaul includes both existing squad and market
            combined_pool = list({p.player_id: p for p in (squad_contracts + market_contracts)}.values())

            # Solve multiple diverse options across risk modes and structural variants
            unique_squads: list[list[PlayerProjectionContract]] = []
            seen_squad_keys: set[tuple[int, ...]] = set()

            if len(combined_pool) >= 11:
                # 1. Primary solutions across risk modes
                for r_mode in ("expected", "balanced", "conservative", "upside"):
                    try:
                        sq = optimize_initial_team(
                            pool=combined_pool,
                            budget_credits=total_budget_credits,
                            risk_mode=r_mode,
                            constraints=self.constraints,
                        )
                        s_key = tuple(sorted(p.player_id for p in sq))
                        if s_key not in seen_squad_keys:
                            seen_squad_keys.add(s_key)
                            unique_squads.append(sq)
                    except Exception:
                        pass

                # 2. Structural alternatives: omit most expensive new arrival of primary squad
                if unique_squads:
                    top_new = sorted(
                        [p for p in unique_squads[0] if p.player_id not in {s.player_id for s in squad_contracts}],
                        key=lambda x: x.price_tenths,
                        reverse=True,
                    )
                    if top_new:
                        try:
                            sq_alt = optimize_initial_team(
                                pool=combined_pool,
                                budget_credits=total_budget_credits,
                                risk_mode="expected",
                                excluded_player_ids=[top_new[0].player_id],
                                constraints=self.constraints,
                            )
                            s_key = tuple(sorted(p.player_id for p in sq_alt))
                            if s_key not in seen_squad_keys:
                                seen_squad_keys.add(s_key)
                                unique_squads.append(sq_alt)
                        except Exception:
                            pass

                # 3. Core-retaining alternative: lock the highest-expected player from current squad
                best_curr = max(squad_contracts, key=lambda x: x.expected_fp, default=None)
                if best_curr:
                    try:
                        sq_lock = optimize_initial_team(
                            pool=combined_pool,
                            budget_credits=total_budget_credits,
                            risk_mode="expected",
                            locked_player_ids=[best_curr.player_id],
                            constraints=self.constraints,
                        )
                        s_key = tuple(sorted(p.player_id for p in sq_lock))
                        if s_key not in seen_squad_keys:
                            seen_squad_keys.add(s_key)
                            unique_squads.append(sq_lock)
                    except Exception:
                        pass

            # Build recommendations from unique solutions
            squad_ids = {p.player_id for p in squad_contracts}
            for sol_sq in unique_squads:
                sol_ids = set(p.player_id for p in sol_sq)
                out_players = tuple(p for p in squad_contracts if p.player_id not in sol_ids)
                in_players = tuple(p for p in sol_sq if p.player_id not in squad_ids)

                if max_trades and len(in_players) > max_trades:
                    continue

                new_lineup = self.lineup_optimizer.optimize(
                    sol_sq, round_number=round_number, top_alternatives=0
                )
                gross_gain = round(new_lineup.objective_value - current_score, 2)
                cost = 0.0 if unlimited else self.transfer_penalty_cost * len(out_players)
                net_val = round(gross_gain - cost, 2)
                rem_bank = total_budget_tenths - sum(p.price_tenths for p in sol_sq)

                rec = TransferRecommendation(
                    out_players=out_players,
                    in_players=in_players,
                    remaining_bank_tenths=rem_bank,
                    new_lineup=new_lineup,
                    gross_score_gain=gross_gain,
                    transfer_cost=cost,
                    net_transfer_value=net_val,
                )
                all_recommendations.append(rec)
                evaluated_count += 1

            if all_recommendations:
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
                    total_evaluated_packages=max(1, evaluated_count),
                    is_exhaustive=True,
                )

        # 2-STAGE SCREENING PATH: For limited transfers (1..4) or bounded unlimited transfers (1..5)
        effective_max_trades = max_trades if (unlimited and max_trades is not None and max_trades <= 5) else min(max_trades, 4)

        # Dynamic candidate filtering limits to prevent combinatorial explosion
        cand_limits = {1: 15, 2: 8, 3: 5, 4: 4, 5: 3}
        cand_limit = cand_limits.get(effective_max_trades, 3) if not exhaustive_candidates else 50

        # Stage 1: Fast screening of legal trade combinations
        screened_packages: list[tuple[float, tuple[PlayerProjectionContract, ...], tuple[PlayerProjectionContract, ...], int, int]] = []

        for k in range(1, effective_max_trades + 1):
            for out_combo in combinations(squad_contracts, k):
                out_ids = [p.player_id for p in out_combo]
                out_positions = Counter(p.position for p in out_combo)
                sales_val = sum(p.price_tenths for p in out_combo)
                max_budget = bank_tenths + sales_val

                pos_candidate_lists: list[Sequence[PlayerProjectionContract]] = []
                valid_positions = True
                for pos, count in out_positions.items():
                    cands = candidate_pool.for_position(pos)
                    if not exhaustive_candidates:
                        cands = cands[:cand_limit]
                    if len(cands) < count:
                        valid_positions = False
                        break
                    pos_combos = list(combinations(cands, count))
                    pos_candidate_lists.append(pos_combos)

                if not valid_positions:
                    continue

                out_exp_sum = sum(p.expected_fp for p in out_combo)

                for in_tuple_of_tuples in product(*pos_candidate_lists):
                    in_players: list[PlayerProjectionContract] = []
                    for sub_tuple in in_tuple_of_tuples:
                        in_players.extend(sub_tuple)

                    purchases_val = sum(p.price_tenths for p in in_players)
                    if purchases_val > max_budget:
                        continue

                    # Mathematical upper bound pruning
                    max_in_pts = 2.0 * sum(p.expected_fp for p in in_players)
                    min_out_pts = 0.5 * out_exp_sum
                    if max_in_pts < min_out_pts:
                        continue

                    evaluated_count += 1

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

                    in_exp_sum = sum(p.expected_fp for p in in_players)
                    proxy_gain = in_exp_sum - out_exp_sum
                    screened_packages.append((proxy_gain, tuple(out_combo), tuple(in_players), new_bank, k))

        # Stage 2: Evaluate exact lineup optimization for top screened packages
        if not exhaustive_candidates and len(screened_packages) > 25:
            screened_packages.sort(key=lambda x: x[0], reverse=True)
            screened_packages = screened_packages[:25]

        for proxy_gain, out_combo, in_players, new_bank, k in screened_packages:
            out_ids_set = {p.player_id for p in out_combo}
            remaining = [p for p in squad_contracts if p.player_id not in out_ids_set]
            new_squad = remaining + list(in_players)

            new_lineup = self.lineup_optimizer.optimize(
                new_squad, round_number=round_number, top_alternatives=0
            )
            gross_gain = round(new_lineup.objective_value - current_score, 2)
            cost = 0.0 if unlimited else self.transfer_penalty_cost * k
            net_val = round(gross_gain - cost, 2)

            rec = TransferRecommendation(
                out_players=out_combo,
                in_players=in_players,
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
