"""Initial squad optimization for EuroLeague Fantasy Challenge Classic Mode (V0.5).

Architecture:
- Lives strictly in the quantitative optimization layer (`euroleague_fantasy_manager.optimization`).
- Consumes decoupled `PlayerProjectionContract` and deterministic `OptimizationConstraints`.
- Uses Exact Binary Integer Linear Programming (MILP via `scipy.optimize.milp`)
  to maximize Round-1 expected fantasy points under salary cap and squad legality rules.
"""

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

from ..models import Position
from ..rules import MAX_BUDGET_TENTHS, MAX_PLAYERS_PER_TEAM, SQUAD_SIZE
from .constraints import (
    OptimizationConstraints,
    PlayerProjectionContract,
    validate_squad_constraints,
)


class InitialTeamRiskMode(str, Enum):
    BALANCED = "balanced"
    EXPECTED = "expected"
    CONSERVATIVE = "conservative"
    UPSIDE = "upside"


@dataclass(frozen=True, slots=True)
class InitialTeamOptimizationResult:
    """Detailed result contract for initial squad optimization."""

    squad: list[PlayerProjectionContract]
    objective_value: float
    total_cost_tenths: int
    objective_name: str
    risk_mode: str
    strategy_description: str


def _pos_code(pos: Any) -> str:
    if hasattr(pos, "short_code"):
        return str(pos.short_code)
    try:
        return Position.from_raw(pos).short_code
    except Exception:
        return str(pos)


def optimize_initial_team(
    pool: Sequence[PlayerProjectionContract],
    budget_credits: float = 100.0,
    risk_mode: str = "expected",
    locked_player_ids: Sequence[int] | None = None,
    excluded_player_ids: Sequence[int] | None = None,
    constraints: OptimizationConstraints | None = None,
) -> list[PlayerProjectionContract]:
    """Optimize an 11-player initial squad for Round 1 under salary cap and legality constraints.

    Objective:
        Round 1 expected fantasy production under budget (credits) and Classic Mode quotas:
        4 Guards, 4 Forwards, 2 Centers, 1 Head Coach, max 6 court players per club.

    Args:
        pool: Candidate player projection contracts.
        budget_credits: Maximum allowed squad expenditure in credits (default: 100.0).
        risk_mode: 'expected'/'balanced', 'conservative', or 'upside'.
        locked_player_ids: Player IDs that must be included in the squad.
        excluded_player_ids: Player IDs that cannot be selected.
        constraints: Optional OptimizationConstraints instance.

    Returns:
        A list of exactly 11 PlayerProjectionContracts satisfying all rules.

    Raises:
        ValueError: If constraints are violated or if no legal squad can be formed.
    """
    res = optimize_initial_team_detailed(
        pool=pool,
        budget_credits=budget_credits,
        risk_mode=risk_mode,
        locked_player_ids=locked_player_ids,
        excluded_player_ids=excluded_player_ids,
        constraints=constraints,
    )
    return res.squad


def optimize_initial_team_detailed(
    pool: Sequence[PlayerProjectionContract],
    budget_credits: float = 100.0,
    risk_mode: str = "expected",
    locked_player_ids: Sequence[int] | None = None,
    excluded_player_ids: Sequence[int] | None = None,
    constraints: OptimizationConstraints | None = None,
) -> InitialTeamOptimizationResult:
    """Detailed version of optimize_initial_team returning metadata and objective value."""
    cfg = constraints or OptimizationConstraints()
    budget_limit_tenths = int(round(budget_credits * 10))

    if not pool:
        raise ValueError("Player pool is empty; cannot optimize initial squad.")

    # Deduplicate pool by player_id
    seen_pids = set()
    deduped_pool: list[PlayerProjectionContract] = []
    for c in pool:
        if c.player_id not in seen_pids:
            seen_pids.add(c.player_id)
            deduped_pool.append(c)

    excluded_set = set(excluded_player_ids or [])
    locked_set = set(locked_player_ids or [])

    # Check for overlapping locked and excluded players
    overlap = locked_set.intersection(excluded_set)
    if overlap:
        raise ValueError(f"Player(s) {overlap} cannot be simultaneously locked and excluded.")

    # Filter out excluded players
    market = [c for c in deduped_pool if c.player_id not in excluded_set]

    # Verify all locked players exist in candidate pool
    market_pids = {c.player_id for c in market}
    missing_locked = locked_set - market_pids
    if missing_locked:
        raise ValueError(f"Locked player(s) {missing_locked} not found in available player pool.")

    locked_contracts = [c for c in market if c.player_id in locked_set]

    # Validate locked players consistency
    if len(locked_contracts) > cfg.squad_size:
        raise ValueError(
            f"Cannot lock {len(locked_contracts)} players; maximum squad size is {cfg.squad_size}."
        )

    # Check locked players budget
    locked_cost = sum(c.price_tenths for c in locked_contracts)
    if locked_cost > budget_limit_tenths:
        raise ValueError(
            f"Locked players cost {locked_cost / 10.0:.1f} Cr, which exceeds budget limit of {budget_credits:.1f} Cr."
        )

    # Check locked players positional quotas
    locked_pos_counts = Counter(_pos_code(c.position) for c in locked_contracts)
    target_quotas = {"G": 4, "F": 4, "C": 2, "HC": 1}
    for pos_code, req_quota in target_quotas.items():
        if locked_pos_counts[pos_code] > req_quota:
            raise ValueError(
                f"Too many locked players for position '{pos_code}': "
                f"{locked_pos_counts[pos_code]} locked vs quota of {req_quota}."
            )

    # Check locked players club quotas (court players only)
    locked_court = [c for c in locked_contracts if _pos_code(c.position) != "HC"]
    locked_club_counts = Counter(c.team_id or c.team_code for c in locked_court if (c.team_id or c.team_code))
    for club, count in locked_club_counts.items():
        if count > cfg.max_players_per_club:
            raise ValueError(
                f"Too many locked players from club '{club}': {count} locked vs max {cfg.max_players_per_club}."
            )

    # If user already locked a complete, legal 11-player squad
    if len(locked_contracts) == cfg.squad_size:
        val = validate_squad_constraints(locked_contracts, budget_tenths=budget_limit_tenths, constraints=cfg)
        if not val.is_valid:
            raise ValueError(f"Locked squad is invalid: {'; '.join(val.errors)}")
        obj_val = sum(c.expected_fp for c in locked_contracts)
        return InitialTeamOptimizationResult(
            squad=locked_contracts,
            objective_value=round(obj_val, 2),
            total_cost_tenths=locked_cost,
            objective_name="round_1_expected_fp_maximization",
            risk_mode=risk_mode,
            strategy_description="User-locked 11-player squad verified under budget and legality rules.",
        )

    # Binary Integer Linear Programming (MILP) with scipy
    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp

        n = len(market)
        obj_weights = np.zeros(n)
        for i, c in enumerate(market):
            if risk_mode.lower() == "conservative":
                val = c.expected_fp - 0.2 * getattr(c, "uncertainty", 0.0)
            elif risk_mode.lower() == "upside":
                val = c.expected_fp + 0.2 * getattr(c, "uncertainty", 0.0)
            else:
                val = c.expected_fp

            # Deterministic, stable tie-breaking: slight boost for lower price then player_id
            tie_break = (1.0 / (1.0 + max(1, c.price_tenths))) * 1e-4 - (c.player_id % 1000) * 1e-7
            obj_weights[i] = -(val + tie_break)  # Minimize negative for maximization

        A_rows = []
        b_l = []
        b_u = []

        # Constraint 1: Budget limit
        prices = np.array([float(c.price_tenths) for c in market], dtype=float)
        A_rows.append(prices)
        b_l.append(0.0)
        b_u.append(float(budget_limit_tenths))

        # Constraint 2: Total squad size = 11
        A_rows.append(np.ones(n, dtype=float))
        b_l.append(float(cfg.squad_size))
        b_u.append(float(cfg.squad_size))

        # Constraint 3: Position quotas (4G, 4F, 2C, 1HC)
        for pos_code, req_quota in target_quotas.items():
            row = np.array([1.0 if _pos_code(c.position) == pos_code else 0.0 for c in market], dtype=float)
            A_rows.append(row)
            b_l.append(float(req_quota))
            b_u.append(float(req_quota))

        # Constraint 4: Club quota (max 6 court players per club)
        unique_clubs = {c.team_id or c.team_code for c in market if _pos_code(c.position) != "HC"}
        for club_id in unique_clubs:
            if not club_id:
                continue
            row = np.array(
                [
                    1.0 if (_pos_code(c.position) != "HC" and (c.team_id or c.team_code) == club_id) else 0.0
                    for c in market
                ],
                dtype=float,
            )
            A_rows.append(row)
            b_l.append(0.0)
            b_u.append(float(cfg.max_players_per_club))

        # Constraint 5: Locked players (x_i = 1)
        for i, c in enumerate(market):
            if c.player_id in locked_set:
                row = np.zeros(n, dtype=float)
                row[i] = 1.0
                A_rows.append(row)
                b_l.append(1.0)
                b_u.append(1.0)

        A_mat = np.array(A_rows)
        constraints_obj = LinearConstraint(A_mat, b_l, b_u)
        integrality = np.ones(n)
        bounds = Bounds(0.0, 1.0)

        res = milp(c=obj_weights, integrality=integrality, constraints=constraints_obj, bounds=bounds)
        if res.success:
            selected_indices = np.where(res.x > 0.5)[0]
            if len(selected_indices) == cfg.squad_size:
                selected = [market[idx] for idx in selected_indices]
                val = validate_squad_constraints(selected, budget_tenths=budget_limit_tenths, constraints=cfg)
                if val.is_valid:
                    total_c = sum(c.price_tenths for c in selected)
                    raw_expected = sum(c.expected_fp for c in selected)
                    return InitialTeamOptimizationResult(
                        squad=selected,
                        objective_value=round(raw_expected, 2),
                        total_cost_tenths=total_c,
                        objective_name="round_1_expected_fp_maximization",
                        risk_mode=risk_mode,
                        strategy_description="Exact MILP Round-1 starting squad optimization under budget & quotas.",
                    )
        raise ValueError("Initial squad optimization is infeasible under the given budget and constraints.")
    except ImportError:
        # Fallback to greedy knapsack heuristic if scipy is unavailable
        return _fallback_greedy_knapsack(
            market=market,
            locked_contracts=locked_contracts,
            budget_limit_tenths=budget_limit_tenths,
            cfg=cfg,
            risk_mode=risk_mode,
        )


def _fallback_greedy_knapsack(
    market: list[PlayerProjectionContract],
    locked_contracts: list[PlayerProjectionContract],
    budget_limit_tenths: int,
    cfg: OptimizationConstraints,
    risk_mode: str,
) -> InitialTeamOptimizationResult:
    """Greedy value-per-cost heuristic fallback when scipy is not available."""
    def _score(c: PlayerProjectionContract) -> float:
        cost = max(1, c.price_tenths)
        val = c.expected_fp
        if risk_mode.lower() == "conservative":
            val -= 0.2 * getattr(c, "uncertainty", 0.0)
        elif risk_mode.lower() == "upside":
            val += 0.2 * getattr(c, "uncertainty", 0.0)
        return (val * 100.0) / cost

    sorted_pool = sorted(market, key=_score, reverse=True)
    selected = list(locked_contracts)
    pos_counts: dict[str, int] = {"G": 0, "F": 0, "C": 0, "HC": 0}
    club_counts: dict[Any, int] = {}
    for c in selected:
        p_code = _pos_code(c.position)
        if p_code in pos_counts:
            pos_counts[p_code] += 1
        cid = c.team_id or c.team_code
        if p_code != "HC" and cid:
            club_counts[cid] = club_counts.get(cid, 0) + 1

    needed = {"G": 4, "F": 4, "C": 2, "HC": 1}

    for pos, quota in needed.items():
        for c in sorted_pool:
            if _pos_code(c.position) != pos or c in selected:
                continue
            if pos_counts[pos] >= quota:
                break
            cid = c.team_id or c.team_code
            if pos != "HC" and cid and club_counts.get(cid, 0) >= cfg.max_players_per_club:
                continue
            curr_spent = sum(x.price_tenths for x in selected)
            rem_needed = cfg.squad_size - len(selected) - 1
            if curr_spent + c.price_tenths + rem_needed * 40 > budget_limit_tenths:
                continue

            selected.append(c)
            pos_counts[pos] += 1
            if pos != "HC" and cid:
                club_counts[cid] = club_counts.get(cid, 0) + 1

    val = validate_squad_constraints(selected, budget_tenths=budget_limit_tenths, constraints=cfg)
    if not val.is_valid:
        raise ValueError(f"Greedy fallback could not form a valid squad: {'; '.join(val.errors)}")

    total_c = sum(c.price_tenths for c in selected)
    raw_expected = sum(c.expected_fp for c in selected)
    return InitialTeamOptimizationResult(
        squad=selected,
        objective_value=round(raw_expected, 2),
        total_cost_tenths=total_c,
        objective_name="round_1_greedy_heuristic",
        risk_mode=risk_mode,
        strategy_description="Greedy knapsack Round-1 starting squad optimization under budget & quotas.",
    )
