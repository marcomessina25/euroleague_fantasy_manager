"""Multi-team domain models for V0.5 fantasy management workstation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Mapping, Sequence


@dataclass
class TeamSettings:
    """Team-scoped managerial and optimization preferences."""

    risk_mode: str = "expected"
    risk_lambda: float = 0.5
    option_value_mode: str = "captain_eligible"
    objective: str = "lineup_score"
    custom_weights: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> TeamSettings:
        if not data:
            return cls()
        return cls(
            risk_mode=str(data.get("risk_mode", "expected")),
            risk_lambda=float(data.get("risk_lambda", 0.5)),
            option_value_mode=str(data.get("option_value_mode", "captain_eligible")),
            objective=str(data.get("objective", "lineup_score")),
            custom_weights=dict(data.get("custom_weights") or {}),
        )


@dataclass
class TeamRosterUnit:
    """Individual player or coach slot within a team's 11-unit roster."""

    player_id: int
    position: str
    name: str = ""
    team_code: str = ""
    purchase_price_tenths: int = 100
    current_price_tenths: int = 100
    is_starter: bool = False
    is_captain: bool = False
    is_sixth_man: bool = False
    is_bench: bool = False
    is_coach: bool = False
    turn_number: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TeamRosterUnit:
        return cls(
            player_id=int(data["player_id"]),
            position=str(data.get("position", "G")),
            name=str(data.get("name", "")),
            team_code=str(data.get("team_code", "")),
            purchase_price_tenths=int(data.get("purchase_price_tenths", 100)),
            current_price_tenths=int(data.get("current_price_tenths", 100)),
            is_starter=bool(data.get("is_starter", False)),
            is_captain=bool(data.get("is_captain", False)),
            is_sixth_man=bool(data.get("is_sixth_man", False)),
            is_bench=bool(data.get("is_bench", False)),
            is_coach=bool(data.get("is_coach", False)),
            turn_number=int(data.get("turn_number", 1)),
        )


@dataclass
class Team:
    """Team entity representing an isolated fantasy squad profile (up to 6 teams)."""

    team_id: str
    name: str
    league: str = "euroleague"
    mode: str = "classic"
    season: str = "2026/27"
    round_number: int = 1
    turn_number: int = 1
    bank_tenths: int = 0
    transfers_remaining: int = 4
    squad: list[TeamRosterUnit] = field(default_factory=list)
    settings: TeamSettings = field(default_factory=TeamSettings)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def player_ids(self) -> list[int]:
        return [unit.player_id for unit in self.squad]

    @property
    def starter_ids(self) -> list[int]:
        return [unit.player_id for unit in self.squad if unit.is_starter]

    @property
    def captain_id(self) -> int | None:
        for unit in self.squad:
            if unit.is_captain:
                return unit.player_id
        return None

    @property
    def sixth_man_id(self) -> int | None:
        for unit in self.squad:
            if unit.is_sixth_man:
                return unit.player_id
        return None

    @property
    def bench_ids(self) -> list[int]:
        return [unit.player_id for unit in self.squad if unit.is_bench]

    @property
    def coach_id(self) -> int | None:
        for unit in self.squad:
            if unit.is_coach or unit.position == "HC":
                return unit.player_id
        return None

    @property
    def total_squad_value_tenths(self) -> int:
        return sum(unit.current_price_tenths for unit in self.squad)

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "name": self.name,
            "league": self.league,
            "mode": self.mode,
            "season": self.season,
            "round_number": self.round_number,
            "turn_number": self.turn_number,
            "bank_tenths": self.bank_tenths,
            "transfers_remaining": self.transfers_remaining,
            "squad": [unit.to_dict() for unit in self.squad],
            "settings": self.settings.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Team:
        squad_raw = data.get("squad") or []
        squad = [TeamRosterUnit.from_dict(item) for item in squad_raw]
        settings = TeamSettings.from_dict(data.get("settings"))
        return cls(
            team_id=str(data["team_id"]),
            name=str(data.get("name", data["team_id"])),
            league=str(data.get("league", "euroleague")),
            mode=str(data.get("mode", "classic")),
            season=str(data.get("season", "2026/27")),
            round_number=int(data.get("round_number", 1)),
            turn_number=int(data.get("turn_number", 1)),
            bank_tenths=int(data.get("bank_tenths", 0)),
            transfers_remaining=int(data.get("transfers_remaining", 4)),
            squad=squad,
            settings=settings,
            created_at=str(
                data.get("created_at") or datetime.now(timezone.utc).isoformat()
            ),
            updated_at=str(
                data.get("updated_at") or datetime.now(timezone.utc).isoformat()
            ),
        )
