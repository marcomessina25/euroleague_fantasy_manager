"""Turn 1 -> Turn 2 substitution option value modeling for V0.4."""

from collections import Counter
import math
from typing import Mapping, Sequence

from ..fixtures import normal_cdf, normal_pdf
from ..models import Position
from ..rules import LEGAL_COURT_FORMATIONS
from .constraints import PlayerProjectionContract


def gaussian_call_option(mu_backup: float, mu_primary: float, sigma_primary: float) -> float:
    """Compute E[max(0, mu_backup - S_primary)] where S_primary ~ N(mu_primary, sigma_primary^2).

    Represents the expected improvement when we observe S_primary in Turn 1 and switch to
    the Turn 2 backup (with expectation mu_backup) whenever S_primary < mu_backup.
    """
    if sigma_primary <= 0.05:
        return max(0.0, mu_backup - mu_primary)
    z = (mu_backup - mu_primary) / sigma_primary
    return max(0.0, (mu_backup - mu_primary) * normal_cdf(z) + sigma_primary * normal_pdf(z))


def can_substitute_into_valid_formation(
    starter_positions: Sequence[Position],
    out_position: Position,
    in_position: Position,
    legal_formations: frozenset[tuple[int, int, int]] = LEGAL_COURT_FORMATIONS,
) -> bool:
    """Return True if swapping an out_position with an in_position leaves a legal G-F-C formation."""
    if out_position == in_position:
        return True
    counts = Counter(starter_positions)
    counts[out_position] -= 1
    counts[in_position] += 1
    formation = (counts[Position.GUARD], counts[Position.FORWARD], counts[Position.CENTER])
    return formation in legal_formations


def compute_turn_substitution_option_bonus(
    starter_ids: Sequence[int],
    captain_id: int,
    vice_captain_id: int,
    sixth_man_id: int,
    bench_ids: Sequence[int],
    projections: Mapping[int, PlayerProjectionContract],
) -> tuple[float, float]:
    """Compute (captain_option_bonus, slot_option_bonus) from intra-round Turn 1 -> Turn 2 substitution rights.

    1. Captain Option:
       If Captain plays in Turn 1 and Vice-Captain plays in Turn 2+, we have the option
       to switch 2x captaincy if Captain scores below Vice-Captain's expectation.
    2. Slot Substitution Option:
       If a starter plays in Turn 1 and an unplayed bench player plays in Turn 2+,
       we can substitute out the starter if their realized score is below bench expectation.
    """
    cap_proj = projections[captain_id]
    vc_proj = projections[vice_captain_id]

    cap_option = 0.0
    if cap_proj.turn_number < vc_proj.turn_number and vc_proj.expected_fp > 0.0:
        sigma = cap_proj.uncertainty if cap_proj.uncertainty > 0.0 else 4.0
        cap_option = gaussian_call_option(
            mu_backup=vc_proj.expected_fp,
            mu_primary=cap_proj.expected_fp,
            sigma_primary=sigma,
        )

    # 2. Slot substitution options
    starter_projs = [projections[sid] for sid in starter_ids]
    starter_positions = [p.position for p in starter_projs]
    t1_starters = [p for p in starter_projs if p.turn_number == 1]

    sub_eligible_bench = [projections[sixth_man_id]] + [projections[bid] for bid in bench_ids]
    t2_bench = [p for p in sub_eligible_bench if p.turn_number >= 2 and p.expected_fp > 0.0]

    slot_option = 0.0
    matched_bench_ids: set[int] = set()

    for s in sorted(t1_starters, key=lambda x: x.expected_fp):
        candidates = [
            b for b in t2_bench
            if b.player_id not in matched_bench_ids
            and can_substitute_into_valid_formation(starter_positions, s.position, b.position)
        ]
        if not candidates:
            continue
        best_b = max(candidates, key=lambda x: x.expected_fp)
        sigma = s.uncertainty if s.uncertainty > 0.0 else 4.0
        gain = gaussian_call_option(
            mu_backup=best_b.expected_fp,
            mu_primary=s.expected_fp,
            sigma_primary=sigma,
        )
        # Factor in bench points difference: starter was 1.0x, bench was 0.5x
        # Real net gain from subbing: delta = S_bench - S_starter + 0.5*S_starter - 0.5*S_bench = 0.5 * (S_bench - S_starter)
        slot_option += 0.5 * gain
        matched_bench_ids.add(best_b.player_id)

    return round(cap_option, 2), round(slot_option, 2)
