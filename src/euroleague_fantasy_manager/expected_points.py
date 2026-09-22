"""Baseline Expected Fantasy Points (xPDK) model for Court Players (PIR + 10% Win Bonus) and Head Coaches."""

from dataclasses import dataclass
import math
from pathlib import Path

from .fixtures import (
    DATABASE_PATH,
    MARGIN_STD_DEV,
    compute_matchup_metrics,
    compute_team_strengths,
    get_current_round,
    normal_cdf,
    position_fdr_multiplier,
)
from .models import Player, Position
from .storage import SnapshotStore


@dataclass(frozen=True, slots=True)
class PlayerProjection:
    player_id: int
    name: str
    position: Position
    team_id: int
    team_code: str
    price_tenths: int
    credits: float
    status: str
    turn_number: int
    opponent_code: str
    is_home: bool
    fdr: int
    win_probability: float
    expected_margin: float
    availability_factor: float
    base_pir: float
    expected_pdk: float
    sigma_pdk: float


def expected_coach_pdk(expected_margin: float, margin_std: float = MARGIN_STD_DEV) -> tuple[float, float]:
    """Compute exact expected Head Coach points and std dev under M ~ N(expected_margin, margin_std^2).

    Coach scoring brackets:
      Win by 21+       : +25
      Win by 11..20    : +20
      Win by 1..10/OT  : +10
      Loss by 1..10/OT :  -5
      Loss by 11..20   : -10
      Loss by 21+      : -20
    """
    std = max(1.0, float(margin_std))
    c_m20 = normal_cdf((-20.5 - expected_margin) / std)
    c_m10 = normal_cdf((-10.5 - expected_margin) / std)
    c_0 = normal_cdf((0.0 - expected_margin) / std)
    c_p10 = normal_cdf((10.5 - expected_margin) / std)
    c_p20 = normal_cdf((20.5 - expected_margin) / std)

    p_loss_21_plus = c_m20
    p_loss_11_20 = max(0.0, c_m10 - c_m20)
    p_loss_1_10 = max(0.0, c_0 - c_m10)
    p_win_1_10 = max(0.0, c_p10 - c_0)
    p_win_11_20 = max(0.0, c_p20 - c_p10)
    p_win_21_plus = max(0.0, 1.0 - c_p20)

    outcomes = [
        (-20.0, p_loss_21_plus),
        (-10.0, p_loss_11_20),
        (-5.0, p_loss_1_10),
        (10.0, p_win_1_10),
        (20.0, p_win_11_20),
        (25.0, p_win_21_plus),
    ]
    mean_val = sum(val * prob for val, prob in outcomes)
    variance = sum(prob * ((val - mean_val) ** 2) for val, prob in outcomes)
    return round(mean_val, 2), round(math.sqrt(max(4.0, variance)), 2)


def compute_availability_factor(player: Player) -> float:
    """Return availability & depth-chart multiplier A_i in [0.0, 1.0]."""
    status_norm = player.status.strip().lower()
    if player.is_injured or status_norm in ("out", "injured", "suspended") or player.probability_of_playing <= 0.0:
        return 0.0
    role_weight = 1.00 if status_norm == "starter" else 0.85
    return round(max(0.0, min(1.0, float(player.probability_of_playing))) * role_weight, 4)


def project_player_for_round(
    player: Player,
    fixture_info: dict[str, object] | None,
) -> PlayerProjection:
    """Compute baseline expected fantasy points (xPDK) and uncertainty (sigma_pdk) for a single unit."""
    if fixture_info is not None:
        opp_code = str(fixture_info.get("opponent", "TBD"))
        is_home = bool(fixture_info.get("is_home", True))
        fdr = int(fixture_info.get("fdr", 3))
        win_prob = float(fixture_info.get("win_probability", 0.5))
        exp_margin = float(fixture_info.get("expected_margin", 0.0))
        turn_num = int(fixture_info.get("turn", player.turn_number or 1))
    else:
        opp_code = "TBD"
        is_home = True
        fdr = 3
        win_prob = 0.5
        exp_margin = 0.0
        turn_num = int(player.turn_number or 1)

    if player.position == Position.HEAD_COACH:
        coach_mean, coach_std = expected_coach_pdk(exp_margin)
        return PlayerProjection(
            player_id=player.id,
            name=player.name,
            position=player.position,
            team_id=player.team_id,
            team_code=player.team_code,
            price_tenths=player.price_tenths,
            credits=player.credits,
            status=player.status,
            turn_number=turn_num,
            opponent_code=opp_code,
            is_home=is_home,
            fdr=fdr,
            win_probability=round(win_prob, 4),
            expected_margin=round(exp_margin, 2),
            availability_factor=1.0,
            base_pir=coach_mean,
            expected_pdk=coach_mean,
            sigma_pdk=coach_std,
        )

    avail = compute_availability_factor(player)
    status_norm = player.status.strip().lower()
    price_prior = player.credits * (1.02 if status_norm == "starter" else 0.78)

    if player.avg_fantasy_pts > 0.0:
        base_pir = 0.55 * player.avg_fantasy_pts + 0.45 * price_prior
    elif player.last_match_pts > 0.0:
        base_pir = 0.35 * player.last_match_pts + 0.65 * price_prior
    else:
        base_pir = price_prior

    fdr_mult = position_fdr_multiplier(fdr=fdr, position=player.position, is_home=is_home)
    win_bonus_mult = 1.0 + 0.10 * win_prob

    xpdk = round(avail * base_pir * fdr_mult * win_bonus_mult, 2)
    sigma = round(max(4.0, 0.45 * xpdk), 2) if avail > 0.0 else 0.0

    return PlayerProjection(
        player_id=player.id,
        name=player.name,
        position=player.position,
        team_id=player.team_id,
        team_code=player.team_code,
        price_tenths=player.price_tenths,
        credits=player.credits,
        status=player.status,
        turn_number=turn_num,
        opponent_code=opp_code,
        is_home=is_home,
        fdr=fdr,
        win_probability=round(win_prob, 4),
        expected_margin=round(exp_margin, 2),
        availability_factor=avail,
        base_pir=round(base_pir, 2),
        expected_pdk=xpdk,
        sigma_pdk=sigma,
    )


def project_all_players(
    database_path: Path = DATABASE_PATH,
    round_number: int | None = None,
) -> dict[int, PlayerProjection]:
    """Generate PlayerProjection objects for all players and Head Coaches in the latest snapshot."""
    store = SnapshotStore(database_path)
    if round_number is None:
        round_number = get_current_round(store)

    players = store.load_latest_players()
    teams_map = store.load_latest_teams()
    strengths = compute_team_strengths(players, teams_map)
    fixtures = store.load_latest_fixtures(round_numbers=[round_number])

    team_fixture_map: dict[int, dict[str, object]] = {}
    for fix in fixtures:
        h_id = fix["home_team_id"]
        a_id = fix["away_team_id"]
        tnum = fix["turn_number"]
        h_code = fix["home_team_code"] or teams_map.get(h_id, {}).get("short_name", f"T{h_id}")
        a_code = fix["away_team_code"] or teams_map.get(a_id, {}).get("short_name", f"T{a_id}")

        s_h = strengths.get(h_id, 0.55)
        s_a = strengths.get(a_id, 0.55)
        m_h = compute_matchup_metrics(s_h, s_a, is_home=True)
        m_a = compute_matchup_metrics(s_a, s_h, is_home=False)

        team_fixture_map[h_id] = {
            "opponent": a_code,
            "is_home": True,
            "turn": tnum,
            "fdr": m_h["fdr"],
            "win_probability": m_h["win_probability"],
            "expected_margin": m_h["expected_margin"],
        }
        team_fixture_map[a_id] = {
            "opponent": h_code,
            "is_home": False,
            "turn": tnum,
            "fdr": m_a["fdr"],
            "win_probability": m_a["win_probability"],
            "expected_margin": m_a["expected_margin"],
        }

    return {
        p.id: project_player_for_round(p, team_fixture_map.get(p.team_id))
        for p in players
    }
