"""Single-round transfer optimizer for V0.4 (Phase F)."""

from collections import Counter
from dataclasses import dataclass
from itertools import combinations, product
from typing import Mapping, Sequence

from ..models import Player
from .candidates import CandidateGenerator
from .constraints import (
    OptimizationConstraints,
    PlayerProjectionContract,
    club_key,
    validate_transfers_constraints,
)
from .lineup import FixedSquadLineupOptimizer, OptimalLineupDecision


def _club_key(p: PlayerProjectionContract) -> int | str | None:
    """Club identity used by the court-player club quota (mirrors validate_squad_constraints)."""
    return club_key(p)


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
    liquidation_urgency: float = 0.0
    drw_penalty_applied: float = 0.0

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
    stage2_evaluations: int = 0
    widened: bool = False
    pruning_notes: tuple[str, ...] = ()


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
        dynamic_opportunity_cost: bool = False,
        is_drw_approaching: bool = False,
        min_net_gain_threshold: float = 0.0,
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
        dynamic_opportunity_cost : bool, default False
            When True, dynamically computes opportunity cost based on player liquidation urgency
            and DRW option value preservation.
        is_drw_approaching : bool, default False
            When True, elevates opportunity cost of trading healthy players due to approaching DRW.
        min_net_gain_threshold : float, default 0.0
            Minimum net score gain required to justify speculative trades of healthy assets.
        """
        if constraints is None:
            from euroleague_fantasy_manager.competition.ruleset import get_league_ruleset
            self.constraints = OptimizationConstraints.from_ruleset(get_league_ruleset())
        else:
            self.constraints = constraints
        self.lineup_optimizer = lineup_optimizer or FixedSquadLineupOptimizer(
            constraints=self.constraints
        )
        self.candidate_generator = candidate_generator or CandidateGenerator(
            constraints=self.constraints
        )
        self.transfer_penalty_cost = transfer_penalty_cost
        self.dynamic_opportunity_cost = dynamic_opportunity_cost
        self.is_drw_approaching = is_drw_approaching
        self.min_net_gain_threshold = min_net_gain_threshold

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
        dynamic_opportunity_cost: bool | None = None,
        is_drw_approaching: bool | None = None,
        min_net_gain_threshold: float | None = None,
    ) -> TransferOptimizationResult:
        """Find the top legal trade packages ranked by net score gain.

        Parameters
        ----------
        exhaustive_candidates : bool, default False
            When False, uses fast candidate pruning to accelerate large market searches.
            When True, runs exact exhaustive evaluation across all candidate combinations.
        """
        # 1. Resolve policy flags
        use_dynamic = self.dynamic_opportunity_cost if dynamic_opportunity_cost is None else dynamic_opportunity_cost
        drw_app = self.is_drw_approaching if is_drw_approaching is None else is_drw_approaching
        min_thresh = self.min_net_gain_threshold if min_net_gain_threshold is None else min_net_gain_threshold

        # 2. Normalize current squad
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
            exhaustive=True,
        )

        all_recommendations: list[TransferRecommendation] = []
        evaluated_count = 0

        # FAST PATH: Unlimited full-squad overhaul solved via MILP squad optimizer
        if unlimited:
            from .initial_team import optimize_initial_team

            total_budget_tenths = sum(p.price_tenths for p in squad_contracts) + bank_tenths
            total_budget_credits = total_budget_tenths / 10.0

            # The candidate pool for overhaul includes both existing squad and market
            combined_pool = list({p.player_id: p for p in (squad_contracts + market_contracts)}.values())
            existing_squad_ids = [p.player_id for p in squad_contracts]

            # Solve multiple diverse options across risk modes and structural variants
            unique_squads: list[list[PlayerProjectionContract]] = []
            seen_squad_keys: set[tuple[int, ...]] = set()

            if len(combined_pool) >= 11:
                # 1. Primary solutions across risk modes with max_changes = max_trades constraint
                for r_mode in ("expected", "balanced", "conservative", "upside"):
                    try:
                        sq = optimize_initial_team(
                            pool=combined_pool,
                            budget_credits=total_budget_credits,
                            risk_mode=r_mode,
                            constraints=self.constraints,
                            max_changes=max_trades,
                            existing_squad_ids=existing_squad_ids,
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
                                max_changes=max_trades,
                                existing_squad_ids=existing_squad_ids,
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
                            max_changes=max_trades,
                            existing_squad_ids=existing_squad_ids,
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

                if not in_players:
                    continue
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

        # 2-STAGE SCREENING PATH: Always run 1..4 screened path as well so smaller packages are offered
        effective_max_trades = min(max_trades if max_trades is not None else 4, 4)

        # Candidate limits per trade size k bound the combinatorial search
        cand_limits_by_k = {1: 15, 2: 8, 3: 5, 4: 4, 5: 3}
        # Exact lineup re-optimization (stage 2) is the dominant cost, so its budget scales with top_n
        stage2_cap = max(25, top_n)

        max_per_club = self.constraints.max_players_per_club
        squad_club_counts = Counter(c for c in (_club_key(p) for p in squad_contracts) if c is not None)
        min_price_in_pool = min((p.price_tenths for p in market_contracts), default=0)
        squad_pids = {p.player_id for p in squad_contracts}

        widened_flag = False
        pruning_notes_list: list[str] = []

        # Stage 1: Fast screening of legal trade combinations
        packages_by_k: dict[int, list[tuple[float, tuple[PlayerProjectionContract, ...], tuple[PlayerProjectionContract, ...], int, int]]] = {}
        screened_packages: list[tuple[float, tuple[PlayerProjectionContract, ...], tuple[PlayerProjectionContract, ...], int, int]] = []

        for k in range(1, effective_max_trades + 1):
            base_cand_limit = cand_limits_by_k.get(k, 3) if not exhaustive_candidates else 50

            def _evaluate_level_k(limit: int) -> list[tuple[float, tuple[PlayerProjectionContract, ...], tuple[PlayerProjectionContract, ...], int, int]]:
                nonlocal evaluated_count
                packages: list[tuple[float, tuple[PlayerProjectionContract, ...], tuple[PlayerProjectionContract, ...], int, int]] = []
                for out_combo in combinations(squad_contracts, k):
                    out_positions = Counter(p.position for p in out_combo)
                    sales_val = sum(p.price_tenths for p in out_combo)
                    max_budget = bank_tenths + sales_val
                    remaining_club_counts = squad_club_counts.copy()
                    remaining_club_counts.subtract(c for c in (_club_key(p) for p in out_combo) if c is not None)

                    pos_candidate_lists: list[Sequence[PlayerProjectionContract]] = []
                    valid_positions = True
                    cutoff_budget = max_budget - (k - 1) * min_price_in_pool

                    for pos, count in out_positions.items():
                        cands = candidate_pool.for_position(pos)
                        # OPT-3: Filter candidates BEFORE truncation:
                        # 1. Not already in the squad
                        # 2. Affordable: price <= max_budget - (k-1)*min_price_in_pool
                        # 3. Within club headroom: remaining_club_counts[club] < max_per_club
                        filtered = [
                            c for c in cands
                            if c.player_id not in squad_pids
                            and c.price_tenths <= cutoff_budget
                            and (_club_key(c) is None or remaining_club_counts[_club_key(c)] < max_per_club)
                        ]
                        if not exhaustive_candidates:
                            filtered = filtered[:limit]
                        if len(filtered) < count:
                            valid_positions = False
                            break
                        pos_candidate_lists.append(list(combinations(filtered, count)))

                    if not valid_positions:
                        continue

                    out_exp_sum = sum(p.expected_fp for p in out_combo)
                    if unlimited:
                        cost_k = 0.0
                    elif use_dynamic:
                        from .trade_policy import TradeCostContext, compute_package_transfer_cost
                        ctx = TradeCostContext(is_drw_approaching=drw_app, min_net_gain_threshold=min_thresh)
                        cost_k, _, _ = compute_package_transfer_cost(out_combo, context=ctx)
                    else:
                        cost_k = round(self.transfer_penalty_cost * k, 2)

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

                        # Club quota (court players only); positions are preserved by construction
                        in_club_counts = Counter(c for c in (_club_key(p) for p in in_players) if c is not None)
                        if any(
                            remaining_club_counts[club] + n > max_per_club
                            for club, n in in_club_counts.items()
                        ):
                            continue

                        evaluated_count += 1
                        new_bank = max_budget - purchases_val
                        in_exp_sum = sum(p.expected_fp for p in in_players)
                        proxy_net = round((in_exp_sum - out_exp_sum) - cost_k, 2)
                        packages.append((proxy_net, tuple(out_combo), tuple(in_players), new_bank, k))
                return packages

            k_packages = _evaluate_level_k(base_cand_limit)
            if not k_packages and not exhaustive_candidates:
                doubled_limit = base_cand_limit * 2
                k_packages = _evaluate_level_k(doubled_limit)
                if k_packages:
                    widened_flag = True
                    pruning_notes_list.append(f"Level k={k} produced 0 packages; widened candidate limit to {doubled_limit}")

            # Keep top candidates per trade size k
            k_packages.sort(key=lambda x: x[0], reverse=True)
            packages_by_k[k] = k_packages

        # Stage 2: Quota-based allocation per trade size k (OPT-4)
        if exhaustive_candidates:
            for pkgs in packages_by_k.values():
                screened_packages.extend(pkgs)
        else:
            import math
            quota_k = math.ceil(stage2_cap / max(1, effective_max_trades))
            remaining_packages = []

            for k in range(1, effective_max_trades + 1):
                pkgs = packages_by_k.get(k, [])
                screened_packages.extend(pkgs[:quota_k])
                remaining_packages.extend(pkgs[quota_k:])

            # Redistribute unused slots to other sizes in order of best proxy
            if len(screened_packages) < stage2_cap and remaining_packages:
                remaining_packages.sort(key=lambda x: x[0], reverse=True)
                needed_slots = stage2_cap - len(screened_packages)
                screened_packages.extend(remaining_packages[:needed_slots])

        stage2_evaluations = 0
        for proxy_gain, out_combo, in_players, new_bank, k in screened_packages:
            stage2_evaluations += 1
            val_res, _ = validate_transfers_constraints(
                current_squad=squad_contracts,
                out_ids=[p.player_id for p in out_combo],
                in_players=in_players,
                bank_tenths=bank_tenths,
                constraints=self.constraints,
            )
            if not val_res.is_valid:
                continue

            out_ids_set = {p.player_id for p in out_combo}
            remaining = [p for p in squad_contracts if p.player_id not in out_ids_set]
            new_squad = remaining + list(in_players)

            new_lineup = self.lineup_optimizer.optimize(
                new_squad, round_number=round_number, top_alternatives=0
            )
            gross_gain = round(new_lineup.objective_value - current_score, 2)
            if unlimited:
                cost = 0.0
                urg = 0.0
                drw_prem = 0.0
            elif use_dynamic:
                from .trade_policy import TradeCostContext, compute_package_transfer_cost
                ctx = TradeCostContext(is_drw_approaching=drw_app, min_net_gain_threshold=min_thresh)
                cost, urg, drw_prem = compute_package_transfer_cost(out_combo, context=ctx)
            else:
                cost = round(self.transfer_penalty_cost * k, 2)
                urg = 0.0
                drw_prem = 0.0

            net_val = round(gross_gain - cost, 2)

            if use_dynamic and min_thresh > 0.0:
                from .trade_policy import is_trade_package_justified
                if not is_trade_package_justified(gross_gain, net_val, out_combo, min_net_gain_threshold=min_thresh):
                    continue

            rec = TransferRecommendation(
                out_players=out_combo,
                in_players=in_players,
                remaining_bank_tenths=new_bank,
                new_lineup=new_lineup,
                gross_score_gain=gross_gain,
                transfer_cost=cost,
                net_transfer_value=net_val,
                liquidation_urgency=urg,
                drw_penalty_applied=drw_prem,
            )
            all_recommendations.append(rec)

        # 6. Deduplicate and rank recommendations by net transfer value desc, remaining bank desc
        seen_rec_keys = set()
        deduped_recs = []
        for r in all_recommendations:
            r_key = (
                tuple(sorted(p.player_id for p in r.out_players)),
                tuple(sorted(p.player_id for p in r.in_players)),
            )
            if r_key not in seen_rec_keys:
                seen_rec_keys.add(r_key)
                deduped_recs.append(r)
        all_recommendations = deduped_recs

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
            is_exhaustive=False if unlimited else candidate_pool.is_exhaustive,
            stage2_evaluations=stage2_evaluations,
            widened=widened_flag,
            pruning_notes=tuple(pruning_notes_list),
        )
