"""Multi-team domain models for V0.5 fantasy management workstation."""

from __future__ import annotations

from collections import Counter
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

    def to_snapshot(
        self,
        player_statuses: Mapping[int, str] | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> "TeamStateSnapshot":
        """Capture an immutable read-only snapshot of this team's state."""
        return TeamStateSnapshot.from_team(
            self,
            player_statuses=player_statuses,
            provenance=provenance,
        )

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


@dataclass
class PointInTimeTeamState:
    """Reconstructed point-in-time financial, availability, and squad state at a round boundary."""

    team_id: str
    round_number: int
    season: str
    squad: list[TeamRosterUnit]
    bank_tenths: int
    transfers_remaining: int
    squad_valuation_tenths: int
    total_team_value_tenths: int
    price_changes: dict[int, int] = field(default_factory=dict)
    player_availabilities: dict[int, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "round_number": self.round_number,
            "season": self.season,
            "squad": [u.to_dict() for u in self.squad],
            "bank_tenths": self.bank_tenths,
            "bank_credits": round(self.bank_tenths / 10.0, 1),
            "transfers_remaining": self.transfers_remaining,
            "squad_valuation_tenths": self.squad_valuation_tenths,
            "squad_valuation_credits": round(self.squad_valuation_tenths / 10.0, 1),
            "total_team_value_tenths": self.total_team_value_tenths,
            "total_team_value_credits": round(self.total_team_value_tenths / 10.0, 1),
            "price_changes": self.price_changes,
            "player_availabilities": self.player_availabilities,
        }


@dataclass(frozen=True, slots=True)
class TeamStateSnapshot:
    """Authoritative frozen point-in-time snapshot of fantasy team state.

    Guarantees read-only immutability across the decision pipeline:
    State -> Prediction -> Optimization -> Human Decision.
    """

    team_id: str
    name: str
    league: str
    season: str
    round_number: int
    turn_number: int
    bank_tenths: int
    transfers_remaining: int
    roster: tuple[TeamRosterUnit, ...]
    player_statuses: dict[int, str] = field(default_factory=dict)
    settings: TeamSettings = field(default_factory=TeamSettings)
    snapshot_timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def bank_credits(self) -> float:
        return round(self.bank_tenths / 10.0, 1)

    @property
    def player_ids(self) -> list[int]:
        return [unit.player_id for unit in self.roster]

    @property
    def starter_units(self) -> tuple[TeamRosterUnit, ...]:
        return tuple(unit for unit in self.roster if unit.is_starter)

    @property
    def bench_units(self) -> tuple[TeamRosterUnit, ...]:
        return tuple(unit for unit in self.roster if unit.is_bench)

    @property
    def sixth_man_unit(self) -> TeamRosterUnit | None:
        for unit in self.roster:
            if unit.is_sixth_man:
                return unit
        return None

    @property
    def captain_unit(self) -> TeamRosterUnit | None:
        for unit in self.roster:
            if unit.is_captain:
                return unit
        return None

    @property
    def coach_unit(self) -> TeamRosterUnit | None:
        for unit in self.roster:
            if unit.is_coach or unit.position == "HC":
                return unit
        return None

    @property
    def total_squad_value_tenths(self) -> int:
        return sum(unit.current_price_tenths for unit in self.roster)

    @property
    def total_team_value_tenths(self) -> int:
        return self.total_squad_value_tenths + self.bank_tenths

    @property
    def total_team_value_credits(self) -> float:
        return round(self.total_team_value_tenths / 10.0, 1)

    @property
    def court_players_by_club(self) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for u in self.roster:
            if not u.is_coach and u.position != "HC" and u.team_code:
                counts[u.team_code] += 1
        return dict(counts)

    def validate_invariants(self, ruleset: Any = None) -> list[str]:
        """Verify that this snapshot satisfies all authoritative fantasy rules invariants."""
        errors: list[str] = []
        target_squad_size = getattr(ruleset, "squad_size", 11)
        if len(self.roster) != target_squad_size:
            errors.append(f"Roster size must be exactly {target_squad_size} units, got {len(self.roster)}")

        starters = [u for u in self.roster if u.is_starter]
        bench = [u for u in self.roster if u.is_bench]
        sixth_man = [u for u in self.roster if u.is_sixth_man]
        coaches = [u for u in self.roster if u.is_coach or u.position == "HC"]
        captains = [u for u in self.roster if u.is_captain]

        expected_starters = getattr(ruleset, "starters_count", 5)
        expected_bench = getattr(ruleset, "bench_count", 4)
        expected_sixth = getattr(ruleset, "sixth_man_count", 1)
        expected_coach = getattr(ruleset, "head_coach_count", 1)

        if len(starters) != expected_starters:
            errors.append(f"Starters count must be exactly {expected_starters}, got {len(starters)}")
        if len(bench) != expected_bench:
            errors.append(f"Bench count must be exactly {expected_bench}, got {len(bench)}")
        if len(sixth_man) != expected_sixth:
            errors.append(f"Sixth man count must be exactly {expected_sixth}, got {len(sixth_man)}")
        if len(coaches) != expected_coach:
            errors.append(f"Head coach count must be exactly {expected_coach}, got {len(coaches)}")
        if len(captains) != 1:
            errors.append(f"Captain count must be exactly 1, got {len(captains)}")
        elif not captains[0].is_starter:
            errors.append(f"Captain (id={captains[0].player_id}) must be in the starting 5")

        pids = [u.player_id for u in self.roster]
        if len(set(pids)) != len(pids):
            errors.append("Duplicate player IDs found in roster")

        if self.bank_tenths < 0:
            errors.append(f"Bank cannot be negative, got {self.bank_tenths} tenths")

        # Court formation check
        g_count = sum(1 for u in starters if u.position == "G")
        f_count = sum(1 for u in starters if u.position == "F")
        c_count = sum(1 for u in starters if u.position == "C")
        formation = f"{g_count}-{f_count}-{c_count}"
        valid_formations = getattr(ruleset, "valid_formations", ("2-2-1", "1-2-2", "2-1-2", "1-3-1", "3-1-1"))
        if formation not in valid_formations:
            errors.append(f"Invalid court formation {formation}; must be one of {valid_formations}")

        # Club quota check
        max_quota = getattr(ruleset, "max_court_players_per_club", 6 if self.league == "eurocup" else 3)
        for club, count in self.court_players_by_club.items():
            if count > max_quota:
                errors.append(f"Club quota exceeded for {club}: {count} players (max {max_quota})")

        return errors

    @property
    def is_valid(self) -> bool:
        return len(self.validate_invariants()) == 0

    @classmethod
    def from_team(
        cls,
        team: Team,
        player_statuses: Mapping[int, str] | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> "TeamStateSnapshot":
        """Capture an immutable read-only snapshot of an authoritative Team model."""
        statuses = dict(player_statuses or {})
        prov = dict(provenance or {})
        return cls(
            team_id=team.team_id,
            name=team.name,
            league=team.league,
            season=team.season,
            round_number=team.round_number,
            turn_number=team.turn_number,
            bank_tenths=team.bank_tenths,
            transfers_remaining=team.transfers_remaining,
            roster=tuple(team.squad),
            player_statuses=statuses,
            settings=team.settings,
            provenance=prov,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "name": self.name,
            "league": self.league,
            "season": self.season,
            "round_number": self.round_number,
            "turn_number": self.turn_number,
            "bank_tenths": self.bank_tenths,
            "bank_credits": self.bank_credits,
            "transfers_remaining": self.transfers_remaining,
            "roster": [u.to_dict() for u in self.roster],
            "player_statuses": dict(self.player_statuses),
            "settings": self.settings.to_dict(),
            "snapshot_timestamp": self.snapshot_timestamp,
            "provenance": dict(self.provenance),
            "total_squad_value_tenths": self.total_squad_value_tenths,
            "total_team_value_tenths": self.total_team_value_tenths,
            "total_team_value_credits": self.total_team_value_credits,
        }

