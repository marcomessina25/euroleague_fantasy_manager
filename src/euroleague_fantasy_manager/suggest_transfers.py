"""Automated 1-to-4 trade candidate generator and optimizer (`elf suggest-trades`) for V0.2."""

from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from .expected_points import PlayerProjection, project_all_players
from .fixtures import DATABASE_PATH, DEFAULT_SQUAD_PATH, PROJECT_ROOT, get_current_round
from .lineup import optimize_court_lineup
from .models import Player, Position
from .rules import MAX_PLAYERS_PER_TEAM, MAX_TRADES_PER_ROUND, is_unlimited_trade_round
from .squad_state import CurrentSquadState, load_current_squad
from .storage import SnapshotStore
from .transfers import TradeMove, selling_price_tenths, validate_trades

TRADES_REPORT_PATH = PROJECT_ROOT / "reports" / "suggest_trades_report.json"


@dataclass(frozen=True, slots=True)
class TradeSuggestion:
    rank: int
    trades_count: int
    moves: tuple[dict[str, Any], ...]
    baseline_turn_adjusted_xpdk: float
    new_turn_adjusted_xpdk: float
    net_xpdk_gain: float
    new_static_xpdk: float
    new_option_bonus_xpdk: float
    bank_before_tenths: int
    bank_after_tenths: int
    recommended_formation: str
    recommended_captain: str
    recommended_sixth_man: str
    is_valid: bool


def _filter_candidate_pool(
    all_players: list[Player],
    projections: dict[int, PlayerProjection],
    squad_ids: set[int],
    per_position_limit: int = 10,
) -> dict[Position, list[Player]]:
    """Select top incoming candidates per position ranked by (xPDK, value-per-credit)."""
    by_pos: dict[Position, list[Player]] = {
        Position.GUARD: [],
        Position.FORWARD: [],
        Position.CENTER: [],
        Position.HEAD_COACH: [],
    }
    for p in all_players:
        if p.id in squad_ids:
            continue
        proj = projections.get(p.id)
        if proj is None or proj.expected_pdk <= 0.0:
            continue
        by_pos[p.position].append(p)

    filtered: dict[Position, list[Player]] = {}
    for pos, plist in by_pos.items():
        # Combine highest raw xPDK and highest value (xPDK / credits)
        top_raw = sorted(plist, key=lambda item: projections[item.id].expected_pdk, reverse=True)[:per_position_limit]
        top_val = sorted(
            plist,
            key=lambda item: projections[item.id].expected_pdk / max(4.0, item.credits),
            reverse=True,
        )[: max(4, per_position_limit // 2)]
        merged: dict[int, Player] = {p.id: p for p in top_raw + top_val}
        filtered[pos] = sorted(merged.values(), key=lambda item: projections[item.id].expected_pdk, reverse=True)
    return filtered


def suggest_trades(
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    num_trades: int = 1,
    round_number: int | None = None,
    top_k: int = 5,
    unlimited_window: bool = False,
    report_path: Path | None = TRADES_REPORT_PATH,
) -> dict[str, Any]:
    """Search legal 1..4 trade combinations and rank by net gain in Turn-Adjusted Squad xPDK."""
    state: CurrentSquadState = load_current_squad(squad_path)
    store = SnapshotStore(database_path)
    target_round = round_number if round_number is not None else (state.round_number or get_current_round(store))

    unlimited_active = is_unlimited_trade_round(target_round, unlimited_flag=unlimited_window)
    max_legal_trades = len(state.player_ids) if unlimited_active else min(MAX_TRADES_PER_ROUND, state.free_trades)
    k = max(1, min(int(num_trades), max_legal_trades))

    all_players = store.load_latest_players()
    players_by_id = {p.id: p for p in all_players}
    squad_players = [players_by_id[pid] for pid in state.player_ids if pid in players_by_id]
    squad_id_set = {p.id for p in squad_players}

    projections = project_all_players(database_path=database_path, round_number=target_round)
    baseline_lineup = optimize_court_lineup(squad_players, projections, round_number=target_round)
    baseline_xp = baseline_lineup.total_turn_adjusted_xpdk

    # Width of candidate pool scales inversely with k so k=1..4 stays fast (< 0.4s)
    pool_limit = {1: 14, 2: 8, 3: 5, 4: 4}.get(k, 4)
    candidate_pool = _filter_candidate_pool(all_players, projections, squad_id_set, per_position_limit=pool_limit)

    # Order outgoing squad members by lowest expected_pdk within each position first
    squad_sorted_out = sorted(squad_players, key=lambda p: projections[p.id].expected_pdk)
    if k >= 3:
        # Focus multi-trade search on the 7 lowest-xPDK squad units to keep combinatorial search instantaneous
        squad_sorted_out = squad_sorted_out[: max(k + 3, 7)]

    initial_team_counts = Counter(p.team_id for p in squad_players if p.position != Position.HEAD_COACH)

    raw_candidates: list[tuple[float, int, list[TradeMove]]] = []

    def _search(
        idx: int,
        remaining_moves: int,
        current_moves: list[TradeMove],
        current_bank_tenths: int,
        marginal_gain: float,
        team_counts: Counter[int],
        used_in_ids: set[int],
    ) -> None:
        if remaining_moves == 0:
            if marginal_gain > -2.0:
                raw_candidates.append((round(marginal_gain, 3), current_bank_tenths, list(current_moves)))
            return

        if idx >= len(squad_sorted_out):
            return
        if len(squad_sorted_out) - idx < remaining_moves:
            return

        # Branch 1: Trade out `squad_sorted_out[idx]`
        out_p = squad_sorted_out[idx]
        out_xp = projections[out_p.id].expected_pdk
        sell_val = selling_price_tenths(out_p, state.purchase_prices_tenths.get(out_p.id))
        if out_p.position != Position.HEAD_COACH:
            team_counts[out_p.team_id] -= 1

        for in_p in candidate_pool.get(out_p.position, []):
            if in_p.id in used_in_ids:
                continue
            new_bank = current_bank_tenths + sell_val - in_p.price_tenths
            if remaining_moves == 1 and new_bank < 0:
                continue
            if in_p.position != Position.HEAD_COACH and team_counts[in_p.team_id] + 1 > MAX_PLAYERS_PER_TEAM:
                continue

            in_xp = projections[in_p.id].expected_pdk
            if in_p.position != Position.HEAD_COACH:
                team_counts[in_p.team_id] += 1
            used_in_ids.add(in_p.id)
            current_moves.append(TradeMove(out_id=out_p.id, in_id=in_p.id))

            _search(
                idx + 1,
                remaining_moves - 1,
                current_moves,
                new_bank,
                marginal_gain + (in_xp - out_xp),
                team_counts,
                used_in_ids,
            )

            current_moves.pop()
            used_in_ids.remove(in_p.id)
            if in_p.position != Position.HEAD_COACH:
                team_counts[in_p.team_id] -= 1

        if out_p.position != Position.HEAD_COACH:
            team_counts[out_p.team_id] += 1

        # Branch 2: Keep `squad_sorted_out[idx]`
        _search(idx + 1, remaining_moves, current_moves, current_bank_tenths, marginal_gain, team_counts, used_in_ids)

    _search(
        idx=0,
        remaining_moves=k,
        current_moves=[],
        current_bank_tenths=state.bank_tenths,
        marginal_gain=0.0,
        team_counts=initial_team_counts,
        used_in_ids=set(),
    )

    # Sort by marginal gain and run full Turn-1 -> Turn-2 lineup optimizer on top candidates
    raw_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    shortlist = raw_candidates[: max(25, top_k * 6)]

    scored_bundles: list[tuple[float, int, list[TradeMove], Any]] = []
    for _, bank_after, moves in shortlist:
        out_set = {m.out_id for m in moves}
        new_squad = [p for p in squad_players if p.id not in out_set] + [
            players_by_id[m.in_id] for m in moves
        ]
        lineup_rec = optimize_court_lineup(new_squad, projections, round_number=target_round)
        delta_xp = round(lineup_rec.total_turn_adjusted_xpdk - baseline_xp, 2)
        scored_bundles.append((delta_xp, bank_after, moves, lineup_rec))

    scored_bundles.sort(key=lambda item: (item[0], item[1]), reverse=True)

    suggestions: list[dict[str, Any]] = []
    for delta_xp, bank_after, moves, lineup_rec in scored_bundles:
        if len(suggestions) >= top_k:
            break
        val_report = validate_trades(state, moves, players_by_id, unlimited_window=unlimited_active)
        if not val_report.is_valid:
            continue

        move_details: list[dict[str, Any]] = []
        for m in moves:
            p_out = players_by_id[m.out_id]
            p_in = players_by_id[m.in_id]
            move_details.append(
                {
                    "out_id": p_out.id,
                    "out_name": p_out.name,
                    "out_team": p_out.team_code,
                    "out_position": p_out.position.short_code,
                    "out_selling_credits": round(selling_price_tenths(p_out) / 10.0, 1),
                    "out_xpdk": projections[p_out.id].expected_pdk,
                    "in_id": p_in.id,
                    "in_name": p_in.name,
                    "in_team": p_in.team_code,
                    "in_position": p_in.position.short_code,
                    "in_buying_credits": p_in.credits,
                    "in_xpdk": projections[p_in.id].expected_pdk,
                }
            )

        suggestion = TradeSuggestion(
            rank=len(suggestions) + 1,
            trades_count=k,
            moves=tuple(move_details),
            baseline_turn_adjusted_xpdk=baseline_xp,
            new_turn_adjusted_xpdk=lineup_rec.total_turn_adjusted_xpdk,
            net_xpdk_gain=delta_xp,
            new_static_xpdk=lineup_rec.static_xpdk,
            new_option_bonus_xpdk=round(
                lineup_rec.captain_option_bonus_xpdk + lineup_rec.slot_option_bonus_xpdk,
                2,
            ),
            bank_before_tenths=state.bank_tenths,
            bank_after_tenths=bank_after,
            recommended_formation=lineup_rec.formation,
            recommended_captain=lineup_rec.captain_name,
            recommended_sixth_man=lineup_rec.sixth_man_name,
            is_valid=val_report.is_valid,
        )
        suggestions.append(asdict(suggestion))

    report = {
        "round_number": target_round,
        "requested_trades": k,
        "unlimited_window_active": unlimited_active,
        "baseline_turn_adjusted_xpdk": baseline_xp,
        "baseline_static_xpdk": baseline_lineup.static_xpdk,
        "suggestions_count": len(suggestions),
        "suggestions": suggestions,
    }

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return report
