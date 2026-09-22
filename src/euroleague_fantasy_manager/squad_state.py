"""Private local representation of a manager's current EuroLeague/EuroCup Fantasy squad state."""

import json
from dataclasses import dataclass
from pathlib import Path

from .rules import EUROLEAGUE_LEAGUE_ID, MAX_TRADES_PER_ROUND, SQUAD_SIZE, UNLIMITED_TRADE_ROUNDS


@dataclass(frozen=True, slots=True)
class CurrentSquadState:
    player_ids: tuple[int, ...]
    purchase_prices_tenths: dict[int, int]
    bank_tenths: int
    free_trades: int
    unlimited_windows_remaining: tuple[int, ...]
    season: str
    round_number: int = 1
    league_id: int = EUROLEAGUE_LEAGUE_ID

    def purchase_price(self, player_id: int) -> int:
        try:
            return self.purchase_prices_tenths[player_id]
        except KeyError as error:
            raise ValueError(f"Missing purchase price for player/coach {player_id}.") from error


def load_current_squad(path: Path) -> CurrentSquadState:
    """Load and validate a private 11-unit squad-state JSON file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    player_ids = tuple(int(pid) for pid in raw["player_ids"])
    purchase_prices = {int(player_id): int(price) for player_id, price in raw["purchase_prices_tenths"].items()}

    if len(player_ids) != SQUAD_SIZE:
        raise ValueError(f"Current squad must contain {SQUAD_SIZE} unit IDs (10 players + 1 coach); received {len(player_ids)}.")
    if len(set(player_ids)) != len(player_ids):
        raise ValueError("Current squad cannot contain duplicate player/coach IDs.")
    if set(player_ids) != set(purchase_prices):
        raise ValueError("Player IDs and purchase-price IDs must match exactly.")
    if int(raw["bank_tenths"]) < 0:
        raise ValueError("Bank credits cannot be negative.")

    free_trades = int(raw.get("free_trades", raw.get("free_transfers", MAX_TRADES_PER_ROUND)))
    if free_trades < 0:
        raise ValueError("Free trades cannot be negative.")

    raw_round = raw.get("round_number") or raw.get("gameweek") or 1
    windows = tuple(int(w) for w in raw.get("unlimited_windows_remaining", sorted(UNLIMITED_TRADE_ROUNDS)))
    league_id = int(raw.get("league_id", EUROLEAGUE_LEAGUE_ID))

    return CurrentSquadState(
        player_ids=player_ids,
        purchase_prices_tenths=purchase_prices,
        bank_tenths=int(raw["bank_tenths"]),
        free_trades=free_trades,
        unlimited_windows_remaining=windows,
        season=str(raw.get("season", "2026/27")),
        round_number=int(raw_round),
        league_id=league_id,
    )


def save_current_squad(path: Path, state: CurrentSquadState) -> None:
    """Save current squad state to a JSON file."""
    data = {
        "season": state.season,
        "league_id": state.league_id,
        "round_number": state.round_number,
        "player_ids": list(state.player_ids),
        "purchase_prices_tenths": {str(pid): price for pid, price in state.purchase_prices_tenths.items()},
        "bank_tenths": state.bank_tenths,
        "free_trades": state.free_trades,
        "unlimited_windows_remaining": list(state.unlimited_windows_remaining),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
