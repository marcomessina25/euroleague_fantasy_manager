"""Deterministic EuroLeague/EuroCup Fantasy Challenge Classic Mode trade validation."""

from dataclasses import dataclass
from typing import Iterable

from .models import Player
from .rules import (
    MAX_TRADES_PER_ROUND,
    ValidationResult,
    is_unlimited_trade_round,
    validate_squad,
)
from .squad_state import CurrentSquadState


@dataclass(frozen=True, slots=True)
class TradeMove:
    out_id: int
    in_id: int


@dataclass(frozen=True, slots=True)
class TradeValidationReport:
    is_valid: bool
    errors: tuple[str, ...]
    trades_count: int
    free_trades_before: int
    free_trades_after: int
    unlimited_active: bool
    total_selling_credits_tenths: int
    total_buying_credits_tenths: int
    net_credit_delta_tenths: int
    bank_before_tenths: int
    bank_after_tenths: int
    resulting_squad_ids: tuple[int, ...]


def selling_price_tenths(player: Player, purchase_price_tenths: int | None = None) -> int:
    """Return the selling price of a player/coach in tenths of a Credit.

    Unlike FPL (which taxes 50% of capital gains), EuroLeague Fantasy Challenge Classic Mode
    realizes 100% of a player's current market quotation upon sale (0% sell-on tax).
    """
    _ = purchase_price_tenths
    return int(player.price_tenths)


def resolve_player_by_name(players: Iterable[Player], query: str) -> Player:
    """Resolve a unique player or head coach by name substring."""
    q = query.strip().lower()
    all_p = list(players)
    exact = [p for p in all_p if p.name.lower() == q or p.last_name.lower() == q]
    if len(exact) == 1:
        return exact[0]
    partial = [p for p in all_p if q in p.name.lower()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise ValueError(f"No player or coach found matching {query!r}.")
    candidates = ", ".join(f"{p.name} ({p.team_code}, {p.position.short_code}, id={p.id})" for p in partial[:5])
    raise ValueError(f"Ambiguous player/coach query {query!r}; matches: {candidates}")


def parse_trade_specs(
    specs: Iterable[str],
    players_by_id: dict[int, Player],
    by_name: bool = False,
) -> list[TradeMove]:
    """Parse CLI trade specifications ('OUT:IN') using integer IDs or player/coach names."""
    moves: list[TradeMove] = []
    all_players = list(players_by_id.values())
    for spec in specs:
        if ":" not in spec:
            raise ValueError(f"Invalid trade format {spec!r}; expected 'OUT:IN'.")
        raw_out, raw_in = [part.strip() for part in spec.split(":", 1)]
        if by_name:
            out_p = resolve_player_by_name(all_players, raw_out)
            in_p = resolve_player_by_name(all_players, raw_in)
            moves.append(TradeMove(out_id=out_p.id, in_id=in_p.id))
        else:
            moves.append(TradeMove(out_id=int(raw_out), in_id=int(raw_in)))
    return moves


def validate_trades(
    state: CurrentSquadState,
    moves: Iterable[TradeMove],
    players_by_id: dict[int, Player],
    unlimited_window: bool = False,
) -> TradeValidationReport:
    """Validate 1..N proposed trades against current squad state, budget, positions, and club limits."""
    move_list = list(moves)
    errors: list[str] = []

    unlimited_active = is_unlimited_trade_round(state.round_number, unlimited_flag=unlimited_window)
    max_allowed = len(state.player_ids) if unlimited_active else min(MAX_TRADES_PER_ROUND, state.free_trades)

    if len(move_list) > max_allowed:
        errors.append(
            f"Proposed {len(move_list)} trades, exceeding the {max_allowed}-trade limit for Round {state.round_number}."
        )

    out_ids = [m.out_id for m in move_list]
    in_ids = [m.in_id for m in move_list]

    if len(set(out_ids)) != len(out_ids):
        errors.append("Cannot sell the same player/coach more than once in a trade batch.")
    if len(set(in_ids)) != len(in_ids):
        errors.append("Cannot buy the same player/coach more than once in a trade batch.")
    if set(out_ids) & set(in_ids):
        errors.append("Cannot trade out and trade in the same player/coach.")

    current_ids = list(state.player_ids)
    total_sell = 0
    total_buy = 0

    for move in move_list:
        if move.out_id not in current_ids:
            errors.append(f"Outgoing unit {move.out_id} is not in the current squad.")
        if move.in_id in current_ids and move.in_id not in out_ids:
            errors.append(f"Incoming unit {move.in_id} is already in the current squad.")

        out_player = players_by_id.get(move.out_id)
        in_player = players_by_id.get(move.in_id)
        if out_player is None:
            errors.append(f"Unknown outgoing unit ID {move.out_id}.")
        else:
            total_sell += selling_price_tenths(out_player, state.purchase_prices_tenths.get(move.out_id))
        if in_player is None:
            errors.append(f"Unknown incoming unit ID {move.in_id}.")
        else:
            total_buy += in_player.price_tenths

    resulting_ids = [pid for pid in current_ids if pid not in set(out_ids)] + in_ids
    bank_after = state.bank_tenths + total_sell - total_buy
    if bank_after < 0:
        errors.append(
            f"Insufficient credits: trades require {-bank_after / 10:.1f} Cr more than available "
            f"(bank before: {state.bank_tenths / 10:.1f} Cr, sell: {total_sell / 10:.1f} Cr, buy: {total_buy / 10:.1f} Cr)."
        )

    if len(resulting_ids) == len(state.player_ids) and all(pid in players_by_id for pid in resulting_ids):
        resulting_players = [players_by_id[pid] for pid in resulting_ids]
        # Pass budget_tenths=None here because bank_after >= 0 already verifies affordability with capital gains
        squad_check: ValidationResult = validate_squad(resulting_players, budget_tenths=None)
        errors.extend(squad_check.errors)

    free_after = state.free_trades if unlimited_active else max(0, state.free_trades - len(move_list))

    return TradeValidationReport(
        is_valid=not errors,
        errors=tuple(errors),
        trades_count=len(move_list),
        free_trades_before=state.free_trades,
        free_trades_after=free_after,
        unlimited_active=unlimited_active,
        total_selling_credits_tenths=total_sell,
        total_buying_credits_tenths=total_buy,
        net_credit_delta_tenths=total_sell - total_buy,
        bank_before_tenths=state.bank_tenths,
        bank_after_tenths=bank_after,
        resulting_squad_ids=tuple(resulting_ids),
    )
