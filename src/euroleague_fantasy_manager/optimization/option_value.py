"""Turn 1 -> Turn 2 substitution option value modeling for V0.4."""

from collections import Counter
import math
from typing import Mapping, Sequence

from ..fixtures import normal_cdf, normal_pdf
from ..models import Position
from ..rules import CAPTAIN_MULTIPLIER, LEGAL_COURT_FORMATIONS
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


def compute_captain_option_value(
    captain: PlayerProjectionContract,
    eligible_backups: Sequence[PlayerProjectionContract],
    captain_multiplier: float = CAPTAIN_MULTIPLIER,
    min_sigma: float = 0.05,
) -> tuple[float, PlayerProjectionContract | None]:
    """Compute incremental option value of switching captaincy to an unplayed player in a later turn.

    EuroLeague Fantasy Classic rules allow changing team captain between turns, provided
    the new captain has not yet taken the court (scheduled in a later turn) and is an eligible
    court player (Head Coaches cannot be captain).

    Mathematical Formulation:
      Delta_cap = (captain_multiplier - 1.0) * E[max(0, mu_backup - S_primary)]
    where S_primary ~ N(mu_primary, sigma_primary^2).
    For the official 2.0x captain multiplier, the incremental bonus is (2.0 - 1.0) = 1.0x.

    Candidate Selection:
      Evaluates all eligible unplayed court players (turn_number > captain.turn_number),
      selecting the highest-expectation candidate: argmax_{p} E[FP_p].
    """
    if captain.position == Position.HEAD_COACH:
        return 0.0, None

    # Filter eligible future captains:
    # 1. Exclude the captain himself
    # 2. Exclude Head Coaches (ineligible for captaincy)
    # 3. Must play in a strictly later turn (has not played yet)
    # 4. Must have positive expected fantasy score
    candidates = [
        p for p in eligible_backups
        if p.player_id != captain.player_id
        and p.position != Position.HEAD_COACH
        and p.turn_number > captain.turn_number
        and p.expected_fp > 0.0
    ]
    if not candidates:
        return 0.0, None

    # Best future candidate by expected score (tie-break price desc, id asc)
    best_backup = max(
        candidates,
        key=lambda p: (p.expected_fp, p.price_tenths, -p.player_id),
    )

    sigma = captain.uncertainty if captain.uncertainty >= 0.0 else 4.0
    call_value = gaussian_call_option(
        mu_backup=best_backup.expected_fp,
        mu_primary=captain.expected_fp,
        sigma_primary=sigma,
    )

    # Scale strictly by captain multiplier bonus: (M_cap - 1.0)
    multiplier_factor = max(0.0, captain_multiplier - 1.0)
    option_value = multiplier_factor * call_value

    return round(option_value, 2), best_backup


def compute_turn_substitution_option_bonus(
    starter_ids: Sequence[int],
    captain_id: int,
    sixth_man_id: int,
    bench_ids: Sequence[int],
    projections: Mapping[int, PlayerProjectionContract],
    vice_captain_id: int | None = None,
    captain_multiplier: float = CAPTAIN_MULTIPLIER,
) -> tuple[float, float]:
    """Compute (captain_option_bonus, slot_option_bonus) from intra-round Turn 1 -> Turn 2 substitution rights.

    1. Captain Option:
       Evaluates the right to switch the 2.0x captaincy to the best eligible court player
       playing in a later turn if the Turn 1 captain underperforms.
    2. Slot Substitution Option:
       If a starter plays in Turn 1 and an unplayed bench player plays in Turn 2+,
       we can substitute out the starter if their realized score is below bench expectation.
    """
    cap_proj = projections[captain_id]

    # Evaluate captain option candidates among all court players in the squad
    all_squad_ids = [sid for sid in starter_ids if sid != captain_id] + [sixth_man_id] + list(bench_ids)
    all_squad_court = [projections[pid] for pid in all_squad_ids if projections[pid].position != Position.HEAD_COACH]

    # If an explicit vice_captain_id was given, ensure it is in the backup candidate pool
    if vice_captain_id is not None and vice_captain_id in projections:
        vc_p = projections[vice_captain_id]
        if vc_p not in all_squad_court and vc_p.position != Position.HEAD_COACH:
            all_squad_court.append(vc_p)

    cap_option, _ = compute_captain_option_value(
        captain=cap_proj,
        eligible_backups=all_squad_court,
        captain_multiplier=captain_multiplier,
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
        # Real net gain from subbing: delta = 0.5 * (S_bench - S_starter)
        slot_option += 0.5 * gain
        matched_bench_ids.add(best_b.player_id)

    return round(cap_option, 2), round(slot_option, 2)
