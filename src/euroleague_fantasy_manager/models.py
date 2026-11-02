"""Domain models for EuroLeague and EuroCup Fantasy Challenge independent of transport format."""

from dataclasses import dataclass
from enum import IntEnum


class Position(IntEnum):
    GUARD = 1
    FORWARD = 2
    CENTER = 3
    HEAD_COACH = 4

    @property
    def short_code(self) -> str:
        return {
            Position.GUARD: "G",
            Position.FORWARD: "F",
            Position.CENTER: "C",
            Position.HEAD_COACH: "HC",
        }[self]

    @classmethod
    def from_raw(cls, value: int | str | dict[str, object]) -> "Position":
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            raw_name = str(value.get("name") or value.get("id") or "")
            return cls.from_raw(raw_name)
        if isinstance(value, int):
            mapping = {
                1: cls.GUARD,
                2: cls.FORWARD,
                3: cls.CENTER,
                4: cls.HEAD_COACH,
                28: cls.GUARD,
                29: cls.FORWARD,
                30: cls.CENTER,
                31: cls.HEAD_COACH,
            }
            if value in mapping:
                return mapping[value]
        norm = str(value).strip().upper().replace("_", " ").replace("-", " ")
        str_mapping = {
            "1": cls.GUARD,
            "2": cls.FORWARD,
            "3": cls.CENTER,
            "4": cls.HEAD_COACH,
            "28": cls.GUARD,
            "29": cls.FORWARD,
            "30": cls.CENTER,
            "31": cls.HEAD_COACH,
            "G": cls.GUARD,
            "GUARD": cls.GUARD,
            "GUARDS": cls.GUARD,
            "F": cls.FORWARD,
            "FORWARD": cls.FORWARD,
            "FORWARDS": cls.FORWARD,
            "C": cls.CENTER,
            "CENTER": cls.CENTER,
            "CENTERS": cls.CENTER,
            "HC": cls.HEAD_COACH,
            "COACH": cls.HEAD_COACH,
            "HEAD COACH": cls.HEAD_COACH,
        }
        if norm in str_mapping:
            return str_mapping[norm]
        raise ValueError(f"Unrecognized EuroLeague Fantasy position: {value!r}")


class UnknownPlayerError(ValueError):
    """Raised when a player ID cannot be resolved in snapshots or market data."""

    def __init__(self, player_id: int, message: str | None = None) -> None:
        self.player_id = player_id
        super().__init__(message or f"Player {player_id} not found in database snapshot.")


def normalize_position(raw: object) -> Position:
    """Normalize a raw position value (int, str, dict, or Position) to a Position enum.

    Raises ValueError on unknown or missing values.
    """
    if raw is None:
        raise ValueError("Position cannot be None")
    return Position.from_raw(raw)



@dataclass(frozen=True, slots=True)
class Player:
    id: int
    name: str
    position: Position
    team_id: int
    team_code: str
    price_tenths: int
    status: str = "starter"
    probability_of_playing: float = 1.0
    turn_number: int = 1
    avg_fantasy_pts: float | None = None
    last_match_pts: float = 0.0
    total_plus_tenths: int | None = None
    popularity: float | None = None
    is_injured: bool = False
    is_on_fire: bool = False
    has_played: bool = False
    first_name: str = ""
    last_name: str = ""
    team_name: str = ""

    @property
    def credits(self) -> float:
        return round(self.price_tenths / 10.0, 1)
class NoSnapshotForRoundError(RuntimeError):
    """Raised when no snapshot exists for a requested round."""

    def __init__(self, round_number: int, season: str, league: str | None = None) -> None:
        self.round_number = round_number
        self.season = season
        self.league = league
        super().__init__(f"No snapshot found for round {round_number} (season {season}, league {league}).")



class ModelUnavailableError(Exception):
    """Raised when a requested predictive model cannot be run because required features are unavailable."""

    def __init__(self, model: str, reason: str) -> None:
        self.model = model
        self.reason = reason
        super().__init__(f"Model '{model}' unavailable: {reason}")
