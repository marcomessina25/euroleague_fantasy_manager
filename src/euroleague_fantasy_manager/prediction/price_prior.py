"""Price and position prior heuristic predictive model (price_prior_v1)."""

from __future__ import annotations

from euroleague_fantasy_manager.models import Player, Position
from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract


def predict_player_price_prior(
    player: Player,
    is_home: bool = True,
    turn_number: int = 1,
    opponent_code: str = "",
    has_played: bool = False,
    actual_fp: float | None = None,
    is_bye: bool = False,
    snapshot_id: int | None = None,
) -> PlayerProjectionContract:
    """Compute projection contract using the price_prior_v1 heuristic."""
    if is_bye:
        return PlayerProjectionContract(
            player_id=player.id,
            player_name=player.name,
            position=player.position,
            team_id=player.team_id,
            team_code=player.team_code,
            price_tenths=player.price_tenths,
            expected_fp=0.0,
            probability_play=0.0,
            expected_minutes=0.0,
            fp_per_minute=0.0,
            uncertainty=0.0,
            prediction_spread=0.0,
            turn_number=player.turn_number,
            opponent_code="BYE",
            is_home=True,
            actual_fp=None,
            has_played=False,
            is_bye=True,
            pre_round_status="bye",
            model_version="price_prior_v1",
            feature_version="1.0.0",
            provenance={
                "snapshot_id": snapshot_id,
                "source": "live",
                "model": "price_prior_v1",
            },
        )

    cr = player.credits
    pos_enum = player.position
    is_injured = bool(player.is_injured or str(getattr(player, "status", "")).lower() in ("out", "injured"))
    if pos_enum == Position.HEAD_COACH:
        base_hc = 11.0 if is_home else 8.5
        exp_fp = max(4.0, min(16.0, round(base_hc + (cr - 6.0) * 0.6, 2)))
        exp_min = 40.0
        fp_per_min = round(exp_fp / 40.0, 3)
        p_play = 1.0
    elif is_injured:
        p_play = 0.0
        exp_min = 0.0
        fp_per_min = 0.0
        exp_fp = 0.0
    else:
        is_starter = (player.status.lower() in ("starter", "start") or cr >= 11.0)
        if is_starter:
            exp_min = min(30.0, max(18.0, 22.0 + (cr - 10.0) * 0.8))
        else:
            exp_min = min(22.0, max(6.0, 12.0 + (cr - 7.0) * 0.7))

        pos_code = pos_enum.short_code if hasattr(pos_enum, "short_code") else str(pos_enum)
        pos_base = 0.54 if "G" in pos_code else (0.56 if "F" in pos_code else 0.60)
        fp_per_min = max(0.32, min(0.85, pos_base + (cr - 10.5) * 0.028))
        loc_mult = 1.05 if is_home else 0.95
        p_play = player.probability_of_playing
        raw_exp = exp_min * fp_per_min * loc_mult
        exp_fp = round(p_play * raw_exp, 2)

        if player.avg_fantasy_pts is not None and player.avg_fantasy_pts > 0:
            exp_fp = round(0.6 * player.avg_fantasy_pts + 0.4 * exp_fp, 2)

    unc_val = round(max(3.0, exp_fp * 0.25), 2)
    spread_val = round(max(6.0, exp_fp * 0.50), 2)

    return PlayerProjectionContract(
        player_id=player.id,
        player_name=player.name,
        position=player.position,
        team_id=player.team_id,
        team_code=player.team_code,
        price_tenths=player.price_tenths,
        expected_fp=exp_fp,
        probability_play=p_play,
        expected_minutes=round(exp_min, 1),
        fp_per_minute=round(fp_per_min, 3),
        uncertainty=unc_val,
        prediction_spread=spread_val,
        turn_number=turn_number,
        opponent_code=opponent_code,
        is_home=is_home,
        actual_fp=actual_fp,
        has_played=has_played,
        is_bye=False,
        pre_round_status=str(getattr(player, "status", "available")),
        model_version="price_prior_v1",
        feature_version="1.0.0",
        provenance={
            "snapshot_id": snapshot_id,
            "source": "live",
            "model": "price_prior_v1",
        },
    )
