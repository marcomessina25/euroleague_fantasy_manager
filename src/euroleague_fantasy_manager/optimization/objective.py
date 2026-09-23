"""Deterministic scoring objectives, risk adjustments, and valuation for V0.4."""

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from ..models import Position
from ..rules import (
    BENCH_MULTIPLIER,
    CAPTAIN_MULTIPLIER,
    HEAD_COACH_MULTIPLIER,
    SIXTH_MAN_MULTIPLIER,
    STARTER_MULTIPLIER,
)
from .constraints import PlayerProjectionContract


class RiskMode(str, Enum):
    """Optimization objective risk adjustment mode."""

    EXPECTED = "expected"
    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"

    @classmethod
    def from_str(cls, val: str | None) -> "RiskMode":
        if not val:
            return cls.EXPECTED
        norm = val.lower().strip()
        for member in cls:
            if member.value == norm:
                return member
        return cls.EXPECTED


@dataclass(frozen=True, slots=True)
class LineupScoreBreakdown:
    """Detailed audited breakdown of a lineup's objective value."""

    formation: str
    starter_score: float
    captain_bonus: float
    sixth_man_score: float
    bench_score: float
    head_coach_score: float
    raw_expected_total: float
    risk_adjustment: float
    option_value_bonus: float
    objective_value: float


def compute_risk_adjusted_player_score(
    expected_fp: float,
    uncertainty: float,
    multiplier: float,
    risk_mode: RiskMode = RiskMode.EXPECTED,
    risk_lambda: float = 0.15,
) -> tuple[float, float]:
    """Compute (raw_expected_fp, risk_adjusted_fp) under a specific multiplier and risk mode.

    Mathematical Interpretation:
      This is an individual risk-adjusted heuristic:
        score_adj = multiplier * E[FP] +/- lambda * (multiplier * sigma)
      - EXPECTED: pure expectation E[FP]
      - CONSERVATIVE: penalizes volatility by -lambda * sigma (downside risk aversion)
      - AGGRESSIVE: rewards volatility by +lambda * sigma (upside / tournament ceiling hunting)

    Note: This is an individual player heuristic, not a full portfolio variance model.
    Inter-player covariance modeling remains out of scope for V0.4.
    """
    raw = multiplier * expected_fp
    sigma = multiplier * max(0.0, uncertainty)

    if risk_mode == RiskMode.CONSERVATIVE:
        adj = -risk_lambda * sigma
    elif risk_mode == RiskMode.AGGRESSIVE:
        adj = +risk_lambda * sigma
    else:
        adj = 0.0

    return raw, raw + adj


def evaluate_lineup_objective(
    starter_ids: Sequence[int],
    captain_id: int,
    sixth_man_id: int,
    bench_ids: Sequence[int],
    head_coach_id: int,
    projections: Mapping[int, PlayerProjectionContract],
    formation_str: str = "",
    risk_mode: RiskMode = RiskMode.EXPECTED,
    risk_lambda: float = 0.15,
    option_value_bonus: float = 0.0,
) -> LineupScoreBreakdown:
    """Evaluate deterministic fantasy objective for a concrete lineup assignment."""
    # 1. Starters: 1.0x each, plus extra 1.0x for the captain (total 2.0x for captain)
    starter_sum = 0.0
    starter_adj_sum = 0.0
    for sid in starter_ids:
        proj = projections[sid]
        raw, adj = compute_risk_adjusted_player_score(
            proj.expected_fp, proj.uncertainty, STARTER_MULTIPLIER, risk_mode, risk_lambda
        )
        starter_sum += raw
        starter_adj_sum += adj

    cap_proj = projections[captain_id]
    # Extra 1.0x for captain (so captain gets 1.0x as starter + 1.0x bonus = 2.0x total)
    cap_bonus_mult = CAPTAIN_MULTIPLIER - STARTER_MULTIPLIER
    cap_raw, cap_adj = compute_risk_adjusted_player_score(
        cap_proj.expected_fp, cap_proj.uncertainty, cap_bonus_mult, risk_mode, risk_lambda
    )

    # 2. Sixth man: 1.0x
    sixth_proj = projections[sixth_man_id]
    sixth_raw, sixth_adj = compute_risk_adjusted_player_score(
        sixth_proj.expected_fp, sixth_proj.uncertainty, SIXTH_MAN_MULTIPLIER, risk_mode, risk_lambda
    )

    # 3. Bench: 0.5x each
    bench_raw = 0.0
    bench_adj = 0.0
    for bid in bench_ids:
        proj = projections[bid]
        raw, adj = compute_risk_adjusted_player_score(
            proj.expected_fp, proj.uncertainty, BENCH_MULTIPLIER, risk_mode, risk_lambda
        )
        bench_raw += raw
        bench_adj += adj

    # 4. Head Coach: 1.0x
    hc_proj = projections[head_coach_id]
    hc_raw, hc_adj = compute_risk_adjusted_player_score(
        hc_proj.expected_fp, hc_proj.uncertainty, HEAD_COACH_MULTIPLIER, risk_mode, risk_lambda
    )

    raw_total = starter_sum + cap_raw + sixth_raw + bench_raw + hc_raw
    adj_total = starter_adj_sum + cap_adj + sixth_adj + bench_adj + hc_adj
    risk_diff = adj_total - raw_total

    objective = adj_total + option_value_bonus

    return LineupScoreBreakdown(
        formation=formation_str,
        starter_score=round(starter_sum, 2),
        captain_bonus=round(cap_raw, 2),
        sixth_man_score=round(sixth_raw, 2),
        bench_score=round(bench_raw, 2),
        head_coach_score=round(hc_raw, 2),
        raw_expected_total=round(raw_total, 2),
        risk_adjustment=round(risk_diff, 2),
        option_value_bonus=round(option_value_bonus, 2),
        objective_value=round(objective, 2),
    )


def compute_positional_replacement_levels(
    projections: Sequence[PlayerProjectionContract],
    percentile: float = 0.30,
) -> dict[Position, float]:
    """Compute replacement-level expected fantasy points by position.

    Used for Value Above Replacement (surplus value) calculations in transfer evaluation.
    """
    by_pos: dict[Position, list[float]] = {
        Position.GUARD: [],
        Position.FORWARD: [],
        Position.CENTER: [],
        Position.HEAD_COACH: [],
    }
    for p in projections:
        by_pos[p.position].append(p.expected_fp)

    replacements: dict[Position, float] = {}
    for pos, scores in by_pos.items():
        if not scores:
            replacements[pos] = 0.0
            continue
        scores.sort()
        idx = max(0, min(int(len(scores) * percentile), len(scores) - 1))
        replacements[pos] = round(scores[idx], 2)

    return replacements
