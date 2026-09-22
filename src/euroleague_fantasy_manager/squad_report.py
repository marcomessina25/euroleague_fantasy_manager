"""Detailed current-squad financial, capital-gain, and legality report generator for V0.2."""

import json
from pathlib import Path
from typing import Any

from .fixtures import DATABASE_PATH, DEFAULT_SQUAD_PATH, PROJECT_ROOT, get_current_round
from .models import Player
from .rules import MAX_PLAYERS_PER_TEAM, SQUAD_QUOTAS, UNLIMITED_TRADE_ROUNDS, validate_squad
from .squad_state import load_current_squad
from .storage import SnapshotStore
from .transfers import selling_price_tenths

SQUAD_REPORT_PATH = PROJECT_ROOT / "reports" / "squad_report.json"


def _fmt_cr(tenths: int) -> str:
    return f"{tenths / 10:.1f} Cr"


def _fmt_signed_cr(tenths: int) -> str:
    sign = "+" if tenths >= 0 else ""
    return f"{sign}{tenths / 10:.1f} Cr"


def generate_squad_report(
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    report_path: Path | None = SQUAD_REPORT_PATH,
    round_number: int | None = None,
) -> dict[str, Any]:
    """Generate a detailed financial, capital-gain, club-quota, and rule report for the 11-unit squad."""
    state = load_current_squad(squad_path)
    store = SnapshotStore(database_path)
    all_players = store.load_latest_players()
    if not all_players:
        raise RuntimeError("No players found in snapshot database. Run `elf update` first.")

    players_by_id: dict[int, Player] = {p.id: p for p in all_players}

    units_detail: list[dict[str, Any]] = []
    squad_models: list[Player] = []
    total_purchase_tenths = 0
    total_current_tenths = 0
    total_selling_tenths = 0
    team_counts: dict[str, int] = {}
    position_counts: dict[str, int] = {"G": 0, "F": 0, "C": 0, "HC": 0}

    for pid in state.player_ids:
        p = players_by_id.get(pid)
        if p is None:
            raise RuntimeError(f"Squad unit ID {pid} was not found in the latest SQLite snapshot.")
        squad_models.append(p)

        buy_tenths = state.purchase_prices_tenths.get(pid, p.price_tenths)
        cur_tenths = p.price_tenths
        sell_tenths = selling_price_tenths(p, buy_tenths)
        cap_gain_tenths = sell_tenths - buy_tenths

        total_purchase_tenths += buy_tenths
        total_current_tenths += cur_tenths
        total_selling_tenths += sell_tenths

        pos_code = p.position.short_code
        position_counts[pos_code] = position_counts.get(pos_code, 0) + 1
        if pos_code != "HC":
            team_counts[p.team_code] = team_counts.get(p.team_code, 0) + 1

        units_detail.append(
            {
                "id": p.id,
                "name": p.name,
                "position": pos_code,
                "team": p.team_code,
                "status": p.status,
                "turn": p.turn_number,
                "probability_of_playing": p.probability_of_playing,
                "avg_fantasy_pts": p.avg_fantasy_pts,
                "purchase_price_tenths": buy_tenths,
                "purchase_price_fmt": _fmt_cr(buy_tenths),
                "current_price_tenths": cur_tenths,
                "current_price_fmt": _fmt_cr(cur_tenths),
                "selling_price_tenths": sell_tenths,
                "selling_price_fmt": _fmt_cr(sell_tenths),
                "capital_gain_tenths": cap_gain_tenths,
                "capital_gain_fmt": _fmt_signed_cr(cap_gain_tenths),
            }
        )

    validation = validate_squad(squad_models, budget_tenths=None)
    total_capital_gain_tenths = total_selling_tenths - total_purchase_tenths
    total_team_value_tenths = state.bank_tenths + total_selling_tenths
    active_round = round_number if round_number is not None else (state.round_number or get_current_round(store))
    next_windows = [w for w in sorted(UNLIMITED_TRADE_ROUNDS) if w >= active_round]

    report: dict[str, Any] = {
        "season": state.season,
        "league_id": state.league_id,
        "round_number": active_round,
        "squad_size": len(units_detail),
        "is_valid": validation.is_valid,
        "validation_errors": list(validation.errors),
        "financials": {
            "bank_tenths": state.bank_tenths,
            "bank_fmt": _fmt_cr(state.bank_tenths),
            "squad_purchase_value_tenths": total_purchase_tenths,
            "squad_purchase_value_fmt": _fmt_cr(total_purchase_tenths),
            "squad_current_value_tenths": total_current_tenths,
            "squad_current_value_fmt": _fmt_cr(total_current_tenths),
            "squad_selling_value_tenths": total_selling_tenths,
            "squad_selling_value_fmt": _fmt_cr(total_selling_tenths),
            "unrealized_capital_gain_tenths": total_capital_gain_tenths,
            "unrealized_capital_gain_fmt": _fmt_signed_cr(total_capital_gain_tenths),
            "total_team_value_tenths": total_team_value_tenths,
            "total_team_value_fmt": _fmt_cr(total_team_value_tenths),
        },
        "state": {
            "round_number": active_round,
            "free_trades": state.free_trades,
            "unlimited_windows_remaining": next_windows,
            "next_unlimited_window_round": next_windows[0] if next_windows else None,
        },
        "breakdown": {
            "positions": position_counts,
            "required_positions": {k.short_code: v for k, v in SQUAD_QUOTAS.items()},
            "teams": team_counts,
            "max_players_per_team": MAX_PLAYERS_PER_TEAM,
        },
        "units": units_detail,
    }

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return report
