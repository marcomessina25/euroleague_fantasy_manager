"""Application service for multi-team CRUD and squad management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from euroleague_fantasy_manager.competition.ruleset import League
from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.optimization.constraints import validate_squad_constraints
from euroleague_fantasy_manager.rules import (
    SQUAD_QUOTAS,
    SQUAD_SIZE,
)
from euroleague_fantasy_manager.multi_team.models import (
    Team,
    TeamRosterUnit,
    TeamSettings,
)
from euroleague_fantasy_manager.multi_team.store import (
    MAX_TEAMS,
    TeamStore,
)


class TeamService:
    """Service orchestrating multi-team lifecycle, squad state, and team isolation."""

    def __init__(self, store: TeamStore | None = None, db_path: str | Path = "data/euroleague.sqlite3") -> None:
        self.store = store or TeamStore(db_path=db_path)

    def create_team(
        self,
        team_id: str,
        name: str,
        league: str = "euroleague",
        mode: str = "classic",
        season: str = "2026/27",
        round_number: int = 1,
        turn_number: int = 1,
        bank_tenths: int = 0,
        settings: TeamSettings | dict[str, Any] | None = None,
        squad: Sequence[TeamRosterUnit] | None = None,
    ) -> Team:
        """Create a new isolated team profile (max 6)."""
        league = League.from_str(league).value
        existing = self.store.get_team(team_id)
        if existing:
            raise ValueError(f"Team with ID '{team_id}' already exists.")

        if isinstance(settings, dict):
            parsed_settings = TeamSettings.from_dict(settings)
        elif isinstance(settings, TeamSettings):
            parsed_settings = settings
        else:
            parsed_settings = TeamSettings()

        team = Team(
            team_id=team_id,
            name=name,
            league=league,
            mode=mode,
            season=season,
            round_number=round_number,
            turn_number=turn_number,
            bank_tenths=bank_tenths,
            transfers_remaining=4,
            squad=list(squad or []),
            settings=parsed_settings,
        )
        created = self.store.create_team(team)
        if created.squad:
            self.store.save_round_checkpoint(
                team_id=team_id,
                round_number=round_number,
                season=season,
                bank_tenths=bank_tenths,
                transfers_remaining=4,
                squad=created.squad,
                overwrite=True,
            )
        return created

    def get_team(self, team_id: str) -> Team:
        """Retrieve team by ID, raising KeyError if not found."""
        team = self.store.get_team(team_id)
        if not team:
            raise KeyError(f"Team '{team_id}' not found.")
        return team

    def list_teams(self) -> list[Team]:
        """List all active teams."""
        return self.store.list_teams()

    def update_team(
        self,
        team_id: str,
        name: str | None = None,
        round_number: int | None = None,
        turn_number: int | None = None,
        bank_tenths: int | None = None,
        transfers_remaining: int | None = None,
        settings: TeamSettings | dict[str, Any] | None = None,
    ) -> Team:
        """Update metadata, bank, or settings of an existing team."""
        team = self.get_team(team_id)
        if name is not None:
            team.name = name
        if round_number is not None:
            team.round_number = round_number
        if turn_number is not None:
            team.turn_number = turn_number
        if bank_tenths is not None:
            team.bank_tenths = bank_tenths
        if transfers_remaining is not None:
            team.transfers_remaining = transfers_remaining
        if settings is not None:
            if isinstance(settings, dict):
                team.settings = TeamSettings.from_dict(settings)
            else:
                team.settings = settings
        return self.store.update_team(team)

    def delete_team(self, team_id: str) -> bool:
        """Delete an existing team."""
        return self.store.delete_team(team_id)

    def get_active_team(self) -> Team | None:
        """Return the currently selected active team."""
        return self.store.get_active_team()

    def set_active_team(self, team_id: str) -> None:
        """Set the active team context."""
        self.store.set_active_team(team_id)

    def set_squad(
        self,
        team_id: str,
        round_number: int,
        roster_units: Sequence[TeamRosterUnit],
        validate: bool = True,
        advance_team_round: bool = True,
    ) -> Team:
        """Persist a team's 11-player squad for a round.

        ``advance_team_round=False`` writes the round without moving the team's
        live round pointer, which is what backfilling a past round requires
        (V0.7 W5).
        """
        team = self.get_team(team_id)
        if validate and roster_units:
            self._validate_roster(roster_units)

        self.store.save_squad(team_id, round_number, roster_units)
        if roster_units and advance_team_round:
            # A backfill (advance_team_round=False) must not fabricate a "round-start"
            # checkpoint from today's live bank/transfers state; the round may legitimately
            # have a stored squad with no checkpoint, and get_latest_checkpoint_before_round
            # would otherwise serve this bogus one as historical truth.
            self.store.save_round_checkpoint(
                team_id=team_id,
                round_number=round_number,
                season=team.season,
                bank_tenths=team.bank_tenths,
                transfers_remaining=team.transfers_remaining,
                squad=roster_units,
                overwrite=False,
            )
        if advance_team_round:
            team.round_number = round_number
            team.squad = list(roster_units)
            return self.store.update_team(team)
        return team

    def update_team_squad(
        self,
        team_id: str,
        squad: Sequence[TeamRosterUnit],
    ) -> Team:
        """Convenience method to update squad for the team's current round."""
        team = self.get_team(team_id)
        return self.set_squad(
            team_id=team_id,
            round_number=team.round_number,
            roster_units=squad,
            validate=False,
        )

    def update_lineup(
        self,
        team_id: str,
        starter_ids: Sequence[int],
        captain_id: int,
        sixth_man_id: int,
        bench_ids: Sequence[int],
        coach_id: int,
        round_number: int | None = None,
    ) -> Team:
        """Update role assignments (starters, captain, sixth man, bench) within a squad.

        ``round_number`` defaults to the team's live round, preserving pre-V0.7
        behaviour. Passing an earlier round backfills that round's lineup without
        moving the team's round pointer.
        """
        team = self.get_team(team_id)
        target_round = team.round_number if round_number is None else int(round_number)
        is_backfill = target_round != team.round_number

        current_squad = (
            team.squad if not is_backfill else self.store.get_squad(team_id, target_round)
        )
        if not current_squad:
            raise ValueError(
                f"Team '{team_id}' has no stored squad for round {target_round}; "
                "record the squad for that round before setting its lineup."
            )

        if is_backfill:
            # A backfill silently dropped ids outside the target round's squad and
            # silently demoted units the request omitted; validate it explicitly instead.
            squad_pids = {unit.player_id for unit in current_squad}
            requested_pids = set(starter_ids) | set(bench_ids) | {captain_id, sixth_man_id, coach_id}
            if not requested_pids.issubset(squad_pids):
                unknown = requested_pids - squad_pids
                raise ValueError(
                    f"Players {sorted(unknown)} are not in round {target_round}'s stored squad for team '{team_id}'."
                )

        starter_set = set(starter_ids)
        bench_set = set(bench_ids)

        updated_units: list[TeamRosterUnit] = []
        for unit in current_squad:
            pid = unit.player_id
            is_cap = (pid == captain_id)
            is_6th = (pid == sixth_man_id)
            is_star = (pid in starter_set)
            is_bnch = (pid in bench_set)
            is_cch = (pid == coach_id or unit.position == "HC")

            updated_unit = TeamRosterUnit(
                player_id=unit.player_id,
                position=unit.position,
                name=unit.name,
                team_code=unit.team_code,
                purchase_price_tenths=unit.purchase_price_tenths,
                current_price_tenths=unit.current_price_tenths,
                is_starter=is_star,
                is_captain=is_cap,
                is_sixth_man=is_6th,
                is_bench=is_bnch,
                is_coach=is_cch,
                turn_number=unit.turn_number,
            )
            updated_units.append(updated_unit)

        if is_backfill:
            # Also validate the resulting shape: a backfill must not persist a
            # half-formed lineup (silently dropped starters, no captain, etc).
            num_starters = sum(1 for u in updated_units if u.is_starter)
            num_captains = sum(1 for u in updated_units if u.is_captain)
            num_sixth = sum(1 for u in updated_units if u.is_sixth_man)
            if num_starters != 5:
                raise ValueError(f"Lineup for round {target_round} must have exactly 5 starters, got {num_starters}.")
            if num_captains != 1:
                raise ValueError(f"Lineup for round {target_round} must have exactly one captain, got {num_captains}.")
            if num_sixth != 1:
                raise ValueError(f"Lineup for round {target_round} must have exactly one sixth man, got {num_sixth}.")

        # A lineup edit only rewrites role flags (starter/captain/sixth man/bench/
        # coach). It changes neither squad membership nor the bank, so no later
        # round's financial state is invalidated and downstream checkpoints stay
        # valid. Trades are different, which is why past-round trade entry waits
        # for the state reconstruction in W6.
        return self.set_squad(
            team_id,
            target_round,
            updated_units,
            validate=False,
            advance_team_round=not is_backfill,
        )

    def get_rounds_with_state(self, team_id: str) -> list[int]:
        """Rounds this team has stored state for, for the Lineup tab selector."""
        team = self.get_team(team_id)
        rounds = self.store.get_rounds_with_state(team_id, team.season)
        if team.round_number not in rounds:
            rounds.append(team.round_number)
        return sorted(rounds)

    def import_from_config(
        self,
        team_id: str,
        config_path: str | Path = "config/current_squad.json",
        player_metadata: dict[int, dict[str, Any]] | None = None,
    ) -> Team:
        """Import team configuration and roster from a JSON squad file."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        player_ids = data.get("player_ids", [])
        purchase_prices = data.get("purchase_prices_tenths", {})
        bank = int(data.get("bank_tenths", 0))
        round_number = int(data.get("round_number", 1))
        season = str(data.get("season", "2026/27"))

        meta = player_metadata or {}
        units: list[TeamRosterUnit] = []
        for pid in player_ids:
            p_meta = meta.get(pid, {})
            pos = p_meta.get("position", "G")
            p_price = int(purchase_prices.get(str(pid), 100))
            units.append(
                TeamRosterUnit(
                    player_id=pid,
                    position=pos,
                    name=p_meta.get("name", f"Player {pid}"),
                    team_code=p_meta.get("team_code", ""),
                    purchase_price_tenths=p_price,
                    current_price_tenths=p_price,
                    is_coach=(pos == "HC"),
                )
            )

        existing = self.store.get_team(team_id)
        if not existing:
            team = self.create_team(
                team_id=team_id,
                name=f"Team {team_id.capitalize()}",
                season=season,
                round_number=round_number,
                bank_tenths=bank,
                squad=units,
            )
        else:
            team = self.set_squad(team_id, round_number, units, validate=False)
            team.bank_tenths = bank
            team = self.store.update_team(team)

        return team

    def _validate_roster(self, units: Sequence[TeamRosterUnit]) -> None:
        """Validate 11 units and official position quotas."""
        if len(units) != SQUAD_SIZE:
            raise ValueError(
                f"Roster must have exactly {SQUAD_SIZE} units, got {len(units)}."
            )

        counts = {"G": 0, "F": 0, "C": 0, "HC": 0}
        for u in units:
            pos = u.position.upper()
            if pos not in counts:
                pos = "G"
            counts[pos] += 1

        for pos, req in SQUAD_QUOTAS.items():
            key = pos.name if hasattr(pos, "name") else str(pos)
            if counts.get(key, 0) != req:
                raise ValueError(
                    f"Invalid squad: requires {req} {key}s, found {counts.get(key, 0)}."
                )

    def revert_to_round_start(
        self,
        team_id: str,
        season: str = "2026/27",
        round_number: int | None = None,
    ) -> Team:
        """Revert team squad, bank, and transfers remaining back to round start baseline."""
        return self.store.revert_to_round_start(
            team_id=team_id,
            season=season,
            round_number=round_number,
        )
