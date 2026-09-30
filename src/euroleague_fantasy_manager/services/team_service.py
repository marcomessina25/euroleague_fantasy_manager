"""Application service for multi-team CRUD and squad management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from euroleague_fantasy_manager.competition.ruleset import League
from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.optimization.constraints import (
    PlayerProjectionContract,
    validate_squad_constraints,
)
from euroleague_fantasy_manager.rules import (
    MAX_TRADES_PER_ROUND,
    SQUAD_QUOTAS,
    SQUAD_SIZE,
    UNLIMITED_TRADE_ROUNDS,
)
from euroleague_fantasy_manager.multi_team.models import (
    PointInTimeTeamState,
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
        coach_id: int | None = None,
        round_number: int | None = None,
        head_coach_id: int | None = None,
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

        eff_coach_id = coach_id if coach_id is not None else head_coach_id
        if eff_coach_id is None:
            c_unit = next((u for u in current_squad if u.is_coach or u.position == "HC"), None)
            eff_coach_id = c_unit.player_id if c_unit else 0

        if is_backfill:
            # A backfill silently dropped ids outside the target round's squad and
            # silently demoted units the request omitted; validate it explicitly instead.
            squad_pids = {unit.player_id for unit in current_squad}
            requested_pids = set(starter_ids) | set(bench_ids) | {captain_id, sixth_man_id, eff_coach_id}
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
            is_cch = (pid == eff_coach_id or unit.position == "HC")

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
            raw = str(u.position).upper()
            if "GUARD" in raw or raw == "G" or raw == "1":
                pos = "G"
            elif "FORWARD" in raw or raw == "F" or raw == "2":
                pos = "F"
            elif "CENTER" in raw or raw == "C" or raw == "3":
                pos = "C"
            elif "COACH" in raw or raw == "HC" or raw == "4":
                pos = "HC"
            else:
                pos = "G"
            counts[pos] += 1

        for pos, req in SQUAD_QUOTAS.items():
            key = pos.short_code if hasattr(pos, "short_code") else str(pos)
            if counts.get(key, 0) != req:
                pos_display = pos.name if hasattr(pos, "name") else str(pos)
                raise ValueError(
                    f"Invalid squad: requires {req} {pos_display}s, found {counts.get(key, 0)}."
                )

    def revert_to_round_start(
        self,
        team_id: str,
        season: str = "2026/27",
        round_number: int | None = None,
    ) -> Team:
        """Revert team squad, bank, and transfers remaining back to round start baseline."""
        team = self.get_team(team_id)
        rnd = round_number or team.round_number
        res = self.store.revert_to_round_start(
            team_id=team_id,
            season=season,
            round_number=rnd,
        )
        if rnd < team.round_number:
            self.replay_transfers_forward(team_id, from_round=rnd, season=season)
            return self.get_team(team_id)
        return res

    def reconstruct_point_in_time_state(
        self,
        team_id: str,
        round_number: int,
        season: str | None = None,
    ) -> PointInTimeTeamState:
        """Reconstruct point-in-time financial, availability, and squad state at a round boundary (F2)."""
        team = self.get_team(team_id)
        eff_season = season or team.season

        # 1. Base squad at this round
        squad = self.store.get_squad(team_id, round_number)
        if not squad:
            chk = self.store.get_latest_checkpoint_before_round(team_id, round_number, eff_season)
            squad = [TeamRosterUnit.from_dict(u.to_dict()) for u in chk["squad"]] if chk else [TeamRosterUnit.from_dict(u.to_dict()) for u in team.squad]

        # 2. Checkpoint baseline for this round
        try:
            chk = self.store.get_round_checkpoint(team_id, round_number, eff_season)
            start_bank = chk["bank_tenths"]
            start_rem = chk["transfers_remaining"]
        except ValueError:
            chk = self.store.get_latest_checkpoint_before_round(team_id, round_number, eff_season)
            start_bank = chk["bank_tenths"] if chk else team.bank_tenths
            start_rem = chk["transfers_remaining"] if chk else MAX_TRADES_PER_ROUND

        # 3. Apply any transfers executed within this round
        transfers = self.store.get_transfers(team_id, eff_season, round_number=round_number)
        net_trade_value = sum(t["price_out_tenths"] - t["price_in_tenths"] for t in transfers)
        current_bank = start_bank + net_trade_value
        current_rem = max(0, start_rem - len(transfers))

        # 4. Valuation and availabilities from snapshot if available
        price_changes: dict[int, int] = {}
        player_availabilities: dict[int, str] = {}
        try:
            from euroleague_fantasy_manager.storage import SnapshotStore
            snap_store = SnapshotStore(self.store.db_path)
            snap = snap_store.get_snapshot_by_round(
                season=eff_season,
                round_number=round_number,
                league=getattr(team, "league", "euroleague") or "euroleague",
            )
            if snap:
                snap_players = snap_store.load_players_for_snapshot(snap["snapshot_id"])
                price_map = {p["player_id"]: p.get("price_tenths", 0) for p in snap_players}
                status_map = {p["player_id"]: p.get("status", "AVAILABLE") for p in snap_players}
                for u in squad:
                    if u.player_id in price_map and price_map[u.player_id] > 0:
                        u.current_price_tenths = price_map[u.player_id]
                    price_changes[u.player_id] = u.current_price_tenths - u.purchase_price_tenths
                    player_availabilities[u.player_id] = status_map.get(u.player_id, "AVAILABLE")
        except Exception:
            pass

        for u in squad:
            if u.player_id not in price_changes:
                price_changes[u.player_id] = u.current_price_tenths - u.purchase_price_tenths
            if u.player_id not in player_availabilities:
                player_availabilities[u.player_id] = "AVAILABLE"

        squad_valuation = sum(u.current_price_tenths for u in squad)
        total_team_value = squad_valuation + current_bank

        return PointInTimeTeamState(
            team_id=team_id,
            round_number=round_number,
            season=eff_season,
            squad=list(squad),
            bank_tenths=current_bank,
            transfers_remaining=current_rem,
            squad_valuation_tenths=squad_valuation,
            total_team_value_tenths=total_team_value,
            price_changes=price_changes,
            player_availabilities=player_availabilities,
        )

    def replay_transfers_forward(self, team_id: str, from_round: int, season: str) -> None:
        """Propagate squad and bank changes forward from a past round edit up to live round (§3.2)."""
        team = self.get_team(team_id)
        live_round = team.round_number
        if from_round >= live_round:
            return

        for r in range(from_round + 1, live_round + 1):
            prev_pit = self.reconstruct_point_in_time_state(team_id, r - 1, season=season)
            incoming_squad = [TeamRosterUnit.from_dict(u.to_dict()) for u in prev_pit.squad]
            incoming_bank = prev_pit.bank_tenths

            # Overwrite round r's start checkpoint with incoming state
            self.store.save_round_checkpoint(
                team_id=team_id,
                round_number=r,
                season=season,
                bank_tenths=incoming_bank,
                transfers_remaining=MAX_TRADES_PER_ROUND,
                squad=incoming_squad,
                overwrite=True,
            )

            # Replay any recorded trades in round r
            r_transfers = self.store.get_transfers(team_id, season, round_number=r)
            cur_squad = list(incoming_squad)
            cur_bank = incoming_bank
            for t in r_transfers:
                out_id = t["player_out_id"]
                in_id = t["player_in_id"]
                out_unit = next((u for u in cur_squad if u.player_id == out_id), None)
                if out_unit:
                    new_unit = TeamRosterUnit(
                        player_id=in_id,
                        position=out_unit.position,
                        name=t.get("player_in_name") or f"Player {in_id}",
                        team_code=out_unit.team_code,
                        purchase_price_tenths=t.get("price_in_tenths", 0),
                        current_price_tenths=t.get("price_in_tenths", 0),
                        is_starter=out_unit.is_starter,
                        is_captain=out_unit.is_captain,
                        is_sixth_man=out_unit.is_sixth_man,
                        is_bench=out_unit.is_bench,
                        is_coach=out_unit.is_coach,
                        turn_number=out_unit.turn_number,
                    )
                    cur_squad = [u if u.player_id != out_id else new_unit for u in cur_squad]
                    cur_bank += t["price_out_tenths"] - t["price_in_tenths"]

            cur_rem_trades = max(0, MAX_TRADES_PER_ROUND - len(r_transfers))
            self.store.save_squad(team_id, r, cur_squad)

            if r == live_round:
                team.bank_tenths = cur_bank
                team.transfers_remaining = cur_rem_trades
                team.squad = cur_squad
                self.store.update_team(team)

    def execute_transfers(
        self,
        team_id: str,
        transfers_out_ids: Sequence[int],
        transfers_in_ids: Sequence[int],
        round_number: int | None = None,
        season: str = "2026/27",
        unlimited: bool = False,
        market_projections: Mapping[int, Any] | None = None,
        lineup_optimizer: Any | None = None,
    ) -> dict[str, Any]:
        """Execute one or more transfers for a live or past round with forward replay (§3.2)."""
        team = self.get_team(team_id)
        target_round = round_number if round_number is not None else team.round_number
        if target_round > team.round_number:
            raise ValueError(
                f"Cannot execute transfers for future round {target_round} (live round is {team.round_number})."
            )

        pit = self.reconstruct_point_in_time_state(team_id, target_round, season=season)
        base_squad = pit.squad
        base_bank_tenths = pit.bank_tenths
        base_transfers_remaining = pit.transfers_remaining

        out_ids = set(transfers_out_ids)
        in_ids = list(transfers_in_ids)
        ordered_out = list(dict.fromkeys(transfers_out_ids))

        if len(out_ids) != len(in_ids):
            raise ValueError("Number of players sold must match number of players bought.")

        is_unlimited = unlimited or (target_round in UNLIMITED_TRADE_ROUNDS)
        if not is_unlimited and len(out_ids) > base_transfers_remaining:
            raise ValueError(
                f"Requested {len(out_ids)} trades, but only {base_transfers_remaining} transfers remaining."
            )

        current_pids = {u.player_id for u in base_squad}
        if not out_ids.issubset(current_pids):
            missing = out_ids - current_pids
            raise ValueError(f"Players {missing} are not in current squad.")

        sell_value_tenths = sum(u.current_price_tenths for u in base_squad if u.player_id in out_ids)

        new_contracts: list[Any] = []
        for pid in in_ids:
            if market_projections and pid in market_projections:
                new_contracts.append(market_projections[pid])
            else:
                contract = self._resolve_player_contract(pid, target_round, season, getattr(team, "league", "euroleague"))
                new_contracts.append(contract)

        buy_cost_tenths = sum(c.price_tenths for c in new_contracts)
        new_bank_tenths = base_bank_tenths + sell_value_tenths - buy_cost_tenths

        if new_bank_tenths < 0:
            deficit_credits = round(abs(new_bank_tenths) / 10.0, 1)
            raise ValueError(f"Insufficient budget: trades exceed available bank by {deficit_credits} cr.")

        kept_units = [u for u in base_squad if u.player_id not in out_ids]
        recruits_units = [
            TeamRosterUnit(
                player_id=c.player_id,
                position=c.position.short_code if hasattr(c.position, "short_code") else str(c.position),
                name=c.player_name,
                team_code=c.team_code,
                purchase_price_tenths=c.price_tenths,
                current_price_tenths=c.price_tenths,
                is_starter=False,
                is_captain=False,
                is_sixth_man=False,
                is_bench=True,
                is_coach=(getattr(c, "position", "") == Position.HEAD_COACH or getattr(c, "position", "") == "HC"),
                turn_number=getattr(c, "turn_number", 1),
            )
            for c in new_contracts
        ]
        candidate_squad = kept_units + recruits_units

        # Validate squad constraints
        self._validate_roster(candidate_squad)

        # Assign roles
        if lineup_optimizer and market_projections:
            full_contracts = [market_projections[u.player_id] for u in candidate_squad if u.player_id in market_projections]
            if len(full_contracts) == len(candidate_squad):
                lineup = lineup_optimizer.optimize(full_contracts, round_number=target_round)
                starter_set = set(lineup.starter_ids)
                bench_set = set(lineup.bench_ids)
                assigned_units = []
                for u in candidate_squad:
                    pid = u.player_id
                    assigned_units.append(
                        TeamRosterUnit(
                            player_id=u.player_id,
                            position=u.position,
                            name=u.name,
                            team_code=u.team_code,
                            purchase_price_tenths=u.purchase_price_tenths,
                            current_price_tenths=u.current_price_tenths,
                            is_starter=(pid in starter_set),
                            is_captain=(pid == lineup.captain_id),
                            is_sixth_man=(pid == lineup.sixth_man_id),
                            is_bench=(pid in bench_set),
                            is_coach=(pid == lineup.head_coach_id or u.position == "HC"),
                            turn_number=u.turn_number,
                        )
                    )
            else:
                assigned_units = self._assign_squad_roles(base_squad, kept_units, recruits_units)
        else:
            assigned_units = self._assign_squad_roles(base_squad, kept_units, recruits_units)

        out_by_id = {u.player_id: u for u in base_squad}
        new_transfer_ids = self.store.record_transfers(
            team_id=team_id,
            round_number=target_round,
            season=season,
            moves=[
                {
                    "player_out_id": out_pid,
                    "player_out_name": getattr(out_by_id.get(out_pid), "name", ""),
                    "player_in_id": contract.player_id,
                    "player_in_name": contract.player_name,
                    "price_out_tenths": getattr(out_by_id.get(out_pid), "current_price_tenths", 0),
                    "price_in_tenths": contract.price_tenths,
                }
                for out_pid, contract in zip(ordered_out, new_contracts)
            ],
        )

        self.store.save_squad(team_id, target_round, assigned_units)

        if target_round == team.round_number:
            rem_trades = base_transfers_remaining if is_unlimited else max(0, base_transfers_remaining - len(out_ids))
            self.update_team(
                team_id=team_id,
                bank_tenths=new_bank_tenths,
                transfers_remaining=rem_trades,
            )
        else:
            self.replay_transfers_forward(team_id, from_round=target_round, season=season)

        return {
            "team": self.get_team(team_id),
            "target_round": target_round,
            "new_transfer_ids": new_transfer_ids,
            "out_ids": list(out_ids),
            "in_ids": in_ids,
            "base_bank_tenths": base_bank_tenths,
            "new_bank_tenths": new_bank_tenths,
        }

    def _assign_squad_roles(
        self,
        base_squad: Sequence[TeamRosterUnit],
        kept_units: Sequence[TeamRosterUnit],
        recruits_units: Sequence[TeamRosterUnit],
    ) -> list[TeamRosterUnit]:
        """Preserve starting and special roles from base squad, slotting recruits into open roles."""
        assigned = [TeamRosterUnit.from_dict(u.to_dict()) for u in kept_units]

        starters_count = sum(1 for u in assigned if u.is_starter)
        has_captain = any(u.is_captain for u in assigned)
        has_sixth = any(u.is_sixth_man for u in assigned)

        for r in recruits_units:
            unit = TeamRosterUnit.from_dict(r.to_dict())
            if unit.is_coach:
                assigned.append(unit)
                continue
            if starters_count < 5:
                unit.is_starter = True
                unit.is_bench = False
                starters_count += 1
                if not has_captain:
                    unit.is_captain = True
                    has_captain = True
            elif not has_sixth:
                unit.is_sixth_man = True
                unit.is_bench = False
                has_sixth = True
            else:
                unit.is_bench = True
                unit.is_starter = False
            assigned.append(unit)

        return assigned

    def _resolve_player_contract(
        self,
        player_id: int,
        round_number: int,
        season: str,
        league: str = "euroleague",
    ) -> PlayerProjectionContract:
        """Resolve a minimal projection contract from database snapshots or defaults."""
        try:
            from euroleague_fantasy_manager.storage import SnapshotStore
            snap_store = SnapshotStore(self.store.db_path)
            snap = snap_store.get_snapshot_by_round(season, round_number, league=league)
            if snap:
                players = snap_store.load_players_for_snapshot(snap["snapshot_id"])
                p_row = next((p for p in players if p["player_id"] == player_id), None)
                if p_row:
                    pos_str = str(p_row.get("position", "G")).upper()
                    if "COACH" in pos_str or pos_str == "HC":
                        pos = Position.HEAD_COACH
                    elif "C" in pos_str:
                        pos = Position.CENTER
                    elif "F" in pos_str:
                        pos = Position.FORWARD
                    else:
                        pos = Position.GUARD
                    return PlayerProjectionContract(
                        player_id=player_id,
                        player_name=p_row.get("name") or f"Player {player_id}",
                        position=pos,
                        team_code=p_row.get("team_code") or "",
                        price_tenths=int(p_row.get("price_tenths", 100)),
                        turn_number=int(p_row.get("turn_number", 1)),
                    )
        except Exception:
            pass

        return PlayerProjectionContract(
            player_id=player_id,
            player_name=f"Player {player_id}",
            position=Position.GUARD,
            team_code="",
            price_tenths=100,
            turn_number=1,
        )
