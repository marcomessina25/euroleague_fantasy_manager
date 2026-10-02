"""Injury vacancy redistribution and positional usage surges for V0.8 (W3).

Models the reality of European basketball rotations:
When a high-usage starter or primary ball-handler is ruled out (OUT, DOUBTFUL, or low P(play)),
their vacated minutes and usage do not vanish. They are redistributed to primary backups
at the same and adjacent positions, generating predictable fantasy surges (Delta Usage, Delta xP).
"""

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING, Any, Sequence

from ..evaluation.features import PointInTimeFeatureRow

if TYPE_CHECKING:
    from .fantasy_points import DecomposedProjection


@dataclass(frozen=True, slots=True)
class InjuryVacancy:
    """Vacated minutes and usage from an unavailable or doubtful player."""

    player_id: int
    player_name: str
    position: str
    team_code: str
    vacated_minutes: float
    vacated_usage: float
    play_probability: float
    status: str


@dataclass(frozen=True, slots=True)
class SurgeAdjustment:
    """Calculated minutes, usage, and expected points lift from teammate injury."""

    player_id: int
    player_name: str
    position: str
    team_code: str
    vacated_by_id: int | None
    vacated_by_name: str
    delta_minutes: float
    delta_usage: float
    delta_fp_per_min: float
    base_xp: float
    surged_xp: float
    surge_pct: float
    is_surge_candidate: bool
    badge: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "position": self.position,
            "team_code": self.team_code,
            "vacated_by_id": self.vacated_by_id,
            "vacated_by_name": self.vacated_by_name,
            "delta_minutes": self.delta_minutes,
            "delta_usage": self.delta_usage,
            "delta_fp_per_min": self.delta_fp_per_min,
            "base_xp": self.base_xp,
            "surged_xp": self.surged_xp,
            "surge_pct": self.surge_pct,
            "is_surge_candidate": self.is_surge_candidate,
            "badge": self.badge,
        }


def identify_team_vacancies(
    players: Sequence[PointInTimeFeatureRow],
    min_vacated_minutes_threshold: float = 6.0,
) -> list[InjuryVacancy]:
    """Identify players on a team who are out/doubtful and vacate significant rotation minutes."""
    vacancies: list[InjuryVacancy] = []
    for p in players:
        pos = p.position.upper().strip()
        if pos == "HC":
            continue

        p_play = p.play_probability
        status = p.pre_round_status.lower().strip()

        # Check if player is ruled out, doubtful, or has low play probability
        is_unavailable = (
            status in ("out", "doubtful", "dnp", "injured")
            or p_play <= 0.35
        )

        if not is_unavailable:
            continue

        # Estimate expected playing time when healthy
        healthy_minutes = max(p.season_avg_minutes, p.last_5_minutes, p.ewma_minutes)
        if healthy_minutes <= 0.0:
            credits = p.quotation_at_decision_tenths / 10.0
            healthy_minutes = 12.0 + max(0.0, credits - 7.0) * 1.5

        # Vacated minutes weighted by absence probability (1 - p_play)
        absent_prob = max(0.0, 1.0 - p_play)
        vacated_min = round(healthy_minutes * absent_prob, 2)

        if vacated_min < min_vacated_minutes_threshold:
            continue

        base_usage = p.usage if p.usage > 0.0 else 0.18
        vacated_usg = round(base_usage * absent_prob, 3)

        vacancies.append(
            InjuryVacancy(
                player_id=p.player_id,
                player_name=p.player_name,
                position=pos,
                team_code=p.team_code,
                vacated_minutes=vacated_min,
                vacated_usage=vacated_usg,
                play_probability=round(p_play, 2),
                status=status if status else "out",
            )
        )
    return vacancies


def _positional_affinity(pos_a: str, pos_b: str) -> float:
    """Return positional replacement affinity weight in [0.0, 1.0]."""
    a = pos_a.upper().strip()
    b = pos_b.upper().strip()
    if a == b:
        return 1.00
    # Wing flexibility: Guard <-> Forward sharing
    if (a == "G" and b == "F") or (a == "F" and b == "G"):
        return 0.35
    # Frontcourt flexibility: Forward <-> Center sharing
    if (a == "F" and b == "C") or (a == "C" and b == "F"):
        return 0.40
    # Guard to Center is essentially 0
    return 0.05


def redistribute_team_vacancies(
    team_players: Sequence[PointInTimeFeatureRow],
    vacancies: Sequence[InjuryVacancy],
) -> dict[int, SurgeAdjustment]:
    """Redistribute vacated minutes and usage across active teammates.

    Returns:
        Mapping of player_id -> SurgeAdjustment
    """
    adjustments: dict[int, SurgeAdjustment] = {}
    if not vacancies:
        for p in team_players:
            if p.position.upper().strip() == "HC":
                continue
            base_xp = round(p.play_probability * p.season_avg_minutes * (p.ewma_fp_per_min or 0.55), 2)
            adjustments[p.player_id] = SurgeAdjustment(
                player_id=p.player_id,
                player_name=p.player_name,
                position=p.position,
                team_code=p.team_code,
                vacated_by_id=None,
                vacated_by_name="",
                delta_minutes=0.0,
                delta_usage=0.0,
                delta_fp_per_min=0.0,
                base_xp=base_xp,
                surged_xp=base_xp,
                surge_pct=0.0,
                is_surge_candidate=False,
                badge=None,
            )
        return adjustments

    # Filter available/active players (candidates to absorb minutes)
    injured_ids = {v.player_id for v in vacancies}
    active_candidates = [
        p for p in team_players
        if p.player_id not in injured_ids and p.position.upper().strip() != "HC" and p.play_probability >= 0.50
    ]

    if not active_candidates:
        return adjustments

    # For each active player, accumulate delta_minutes and delta_usage from all vacancies
    acc_minutes: dict[int, float] = {p.player_id: 0.0 for p in active_candidates}
    acc_usage: dict[int, float] = {p.player_id: 0.0 for p in active_candidates}
    primary_vacated_source: dict[int, tuple[int, str]] = {}

    for vac in vacancies:
        # Compute absorption scores for each candidate
        scores: dict[int, float] = {}
        for cand in active_candidates:
            affinity = _positional_affinity(cand.position, vac.position)
            if affinity <= 0.05:
                continue

            # Capacity: starters already playing 30+ min cannot absorb as many minutes
            current_min = cand.season_avg_minutes if cand.season_avg_minutes > 0 else 16.0
            headroom = max(0.5, 36.5 - current_min)

            # Role weight: rotation players (12-24 min) are primed for the biggest leap
            if 12.0 <= current_min <= 24.0:
                role_mult = 1.35
            elif current_min < 12.0:
                role_mult = 0.90
            else:
                role_mult = 0.75

            score = affinity * headroom * role_mult
            scores[cand.player_id] = score

        total_score = sum(scores.values())
        if total_score <= 0.0:
            continue

        # Distribute minutes & usage (at most 85% of total vacated minutes to avoid rotation bloat)
        distributable_min = vac.vacated_minutes * 0.85
        distributable_usg = vac.vacated_usage * 0.75

        for cand in active_candidates:
            pid = cand.player_id
            if pid not in scores:
                continue
            share = scores[pid] / total_score
            d_min = share * distributable_min
            d_usg = share * distributable_usg

            acc_minutes[pid] += d_min
            acc_usage[pid] += d_usg

            # Track dominant injury source
            if pid not in primary_vacated_source or d_min > acc_minutes[pid] * 0.5:
                primary_vacated_source[pid] = (vac.player_id, vac.player_name)

    # Compute final surge adjustments for all team players
    for p in team_players:
        pid = p.player_id
        pos = p.position.upper().strip()
        if pos == "HC":
            continue

        base_min = p.season_avg_minutes if p.season_avg_minutes > 0.0 else 15.0
        base_rate = p.ewma_fp_per_min if p.ewma_fp_per_min > 0.0 else 0.55
        base_xp = round(p.play_probability * base_min * base_rate, 2)

        if pid in acc_minutes:
            d_min = round(min(12.0, acc_minutes[pid]), 2)
            d_usg = round(min(0.12, acc_usage[pid]), 3)

            # Delta usage directly elevates FP/min efficiency
            base_u = p.usage if p.usage > 0.0 else 0.18
            usage_boost_factor = 1.0 + 0.55 * (d_usg / max(0.10, base_u))
            new_rate = round(base_rate * usage_boost_factor, 4)
            d_rate = round(new_rate - base_rate, 4)

            new_min = min(37.0, base_min + d_min)
            surged_xp = round(p.play_probability * new_min * new_rate, 2)

            surge_pct = round(((surged_xp - base_xp) / max(1.0, base_xp)) * 100.0, 1)
            is_candidate = surge_pct >= 15.0 and d_min >= 2.5

            badge = f"[Surge +{int(round(surge_pct))}%]" if is_candidate else None
            src_id, src_name = primary_vacated_source.get(pid, (None, ""))

            adjustments[pid] = SurgeAdjustment(
                player_id=pid,
                player_name=p.player_name,
                position=pos,
                team_code=p.team_code,
                vacated_by_id=src_id,
                vacated_by_name=src_name,
                delta_minutes=d_min,
                delta_usage=d_usg,
                delta_fp_per_min=d_rate,
                base_xp=base_xp,
                surged_xp=surged_xp,
                surge_pct=surge_pct,
                is_surge_candidate=is_candidate,
                badge=badge,
            )
        else:
            adjustments[pid] = SurgeAdjustment(
                player_id=pid,
                player_name=p.player_name,
                position=pos,
                team_code=p.team_code,
                vacated_by_id=None,
                vacated_by_name="",
                delta_minutes=0.0,
                delta_usage=0.0,
                delta_fp_per_min=0.0,
                base_xp=base_xp,
                surged_xp=base_xp,
                surge_pct=0.0,
                is_surge_candidate=False,
                badge=None,
            )

    return adjustments


def compute_round_injury_surges(
    feature_table: dict[int, PointInTimeFeatureRow],
) -> dict[int, SurgeAdjustment]:
    """Compute injury vacancy redistribution across all teams for an entire round."""
    # Group players by team code
    by_team: dict[str, list[PointInTimeFeatureRow]] = {}
    for p in feature_table.values():
        by_team.setdefault(p.team_code, []).append(p)

    all_adjustments: dict[int, SurgeAdjustment] = {}
    for team_code, team_roster in by_team.items():
        vacancies = identify_team_vacancies(team_roster)
        team_adjs = redistribute_team_vacancies(team_roster, vacancies)
        all_adjustments.update(team_adjs)

    return all_adjustments


def apply_surges_to_projections(
    projections: Sequence[Any],
    surge_adjustments: dict[int, SurgeAdjustment],
) -> list[Any]:
    """Apply injury usage surge adjustments to decomposed projections and badges."""
    from .fantasy_points import DecomposedProjection

    updated: list[Any] = []
    for proj in projections:
        adj = surge_adjustments.get(proj.player_id)
        if adj is None or not adj.is_surge_candidate or adj.delta_minutes <= 0:
            updated.append(proj)
            continue

        # Adjust minutes and expected fantasy points
        surged_min = round(proj.expected_minutes_if_play + adj.delta_minutes, 2)
        surged_rate = round(proj.expected_fp_per_min_if_play + adj.delta_fp_per_min, 4)
        surged_cond_fp = round(surged_min * surged_rate, 2)
        surged_xp = round(proj.play_probability * surged_cond_fp, 2)

        # Append surge badge
        existing_badges = list(proj.context_badges)
        if adj.badge and adj.badge not in existing_badges:
            existing_badges.append(adj.badge)

        updated.append(
            DecomposedProjection(
                player_id=proj.player_id,
                player_name=proj.player_name,
                position=proj.position,
                team_code=proj.team_code,
                opponent_team_code=proj.opponent_team_code,
                home=proj.home,
                turn_number=proj.turn_number,
                cold_start_source=proj.cold_start_source,
                quotation_at_decision_tenths=proj.quotation_at_decision_tenths,
                play_probability=proj.play_probability,
                expected_minutes_if_play=surged_min,
                expected_fp_per_min_if_play=surged_rate,
                expected_conditional_fp=surged_cond_fp,
                expected_fantasy_points=surged_xp,
                lower_bound=round(proj.lower_bound * (surged_xp / max(1.0, proj.expected_fantasy_points)), 2),
                upper_bound=round(proj.upper_bound * (surged_xp / max(1.0, proj.expected_fantasy_points)), 2),
                prediction_spread=proj.prediction_spread,
                sigma=proj.sigma,
                expected_fp_per_credit=round(surged_xp / max(1.0, proj.quotation_at_decision_tenths / 10.0), 3),
                points_above_replacement=round(surged_xp - 7.5, 2),
                risk_adjusted_value=round(surged_xp - 0.15 * proj.prediction_spread, 2),
                rotation_tier=proj.rotation_tier,
                blowout_risk=proj.blowout_risk,
                foul_fragility=proj.foul_fragility,
                congestion_index=proj.congestion_index,
                context_badges=tuple(existing_badges),
            )
        )
    return updated
