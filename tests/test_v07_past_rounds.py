"""V0.7 W5 — entering lineups and trades for rounds in the past.

Storage was already keyed per round (``managed_team_squads`` is
``PRIMARY KEY (team_id, round_number, player_id)``) and the dashboard already
accepted a ``round_number``. What was missing was a ``round_number`` on the
*write* path, a record of the trade events themselves, and invalidation of the
checkpoints that a past-round edit makes inconsistent.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from euroleague_fantasy_manager.multi_team.models import Team, TeamRosterUnit
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.web.app import create_app

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
    league_id INTEGER NOT NULL, competition_code TEXT NOT NULL,
    season_code TEXT NOT NULL, matchday_id INTEGER, round_number INTEGER NOT NULL,
    num_turns INTEGER NOT NULL, raw_archive_path TEXT
);
CREATE TABLE IF NOT EXISTS players (
    snapshot_id INTEGER NOT NULL, id INTEGER NOT NULL, first_name TEXT, last_name TEXT,
    name TEXT NOT NULL, position INTEGER NOT NULL, position_code TEXT NOT NULL,
    team_id INTEGER NOT NULL, team_code TEXT NOT NULL, team_name TEXT NOT NULL,
    price_tenths INTEGER NOT NULL, status TEXT, probability_of_playing REAL,
    turn_number INTEGER, last_match_pts REAL, avg_fantasy_pts REAL,
    total_plus_tenths INTEGER, popularity REAL, is_injured INTEGER, is_on_fire INTEGER
);
CREATE TABLE IF NOT EXISTS fixtures (
    snapshot_id INTEGER NOT NULL, id INTEGER NOT NULL, round_number INTEGER NOT NULL,
    turn_number INTEGER NOT NULL, started_at TEXT, status TEXT, home_team_id INTEGER,
    home_team_code TEXT, away_team_id INTEGER, away_team_code TEXT,
    home_score INTEGER, away_score INTEGER
);
CREATE TABLE IF NOT EXISTS teams (
    snapshot_id INTEGER NOT NULL, id INTEGER NOT NULL, name TEXT NOT NULL, short_name TEXT NOT NULL
);
"""

SEASON = "2026/27"

# Six clubs, so an 11-unit squad can satisfy the max-6-players-per-club rule.
_CLUBS = [(140, "BAR"), (141, "RMB"), (142, "OLY"), (143, "PAN"), (144, "FBB"), (145, "MIL")]

# 8 guards, 8 forwards, 4 centers, 2 coaches -> room to trade within quotas.
_ROSTER_PLAN = (
    [(5000 + i, 1, "G") for i in range(8)]
    + [(5100 + i, 2, "F") for i in range(8)]
    + [(5200 + i, 3, "C") for i in range(4)]
    + [(5300 + i, 4, "HC") for i in range(2)]
)

# Deterministic club assignment, spreading each position group across clubs so
# that no club holds more than six of the units used by the test squad.
_CLUB_OF = {pid: _CLUBS[i % len(_CLUBS)] for i, (pid, _, _) in enumerate(_ROSTER_PLAN)}


def _seed_market(db_file: Path) -> None:
    with sqlite3.connect(db_file) as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT INTO snapshots (id, created_at, league_id, competition_code, season_code, "
            "matchday_id, round_number, num_turns, raw_archive_path) "
            "VALUES (1, '2026-09-24T10:00:00Z', 10, 'E', 'E2026', 1, 2, 2, 'raw.json')"
        )
        for idx, (pid, pos_idx, pos_code) in enumerate(_ROSTER_PLAN):
            club_id, club_code = _CLUB_OF[pid]
            conn.execute(
                "INSERT INTO players (snapshot_id, id, first_name, last_name, name, position, "
                "position_code, team_id, team_code, team_name, price_tenths, status, "
                "probability_of_playing, turn_number, avg_fantasy_pts, last_match_pts, "
                "total_plus_tenths, popularity, is_injured, is_on_fire) "
                "VALUES (1, ?, 'P', ?, ?, ?, ?, ?, ?, ?, ?, 'starter', "
                "1.0, 1, ?, 0.0, 0, 0.0, 0, 0)",
                (
                    pid,
                    f"Unit{pid}",
                    f"P Unit{pid}",
                    pos_idx,
                    pos_code,
                    club_id,
                    club_code,
                    f"Club {club_code}",
                    60 + idx,
                    6.0 + (idx % 7),
                ),
            )
        # Every club plays in both rounds, so no unit is treated as postponed.
        fixture_id = 100
        for rnd in (1, 2):
            for pair_idx in range(0, len(_CLUBS), 2):
                home_id, home_code = _CLUBS[pair_idx]
                away_id, away_code = _CLUBS[pair_idx + 1]
                conn.execute(
                    "INSERT INTO fixtures (snapshot_id, id, round_number, turn_number, started_at, "
                    "status, home_team_id, home_team_code, away_team_id, away_team_code, "
                    "home_score, away_score) "
                    "VALUES (1, ?, ?, 1, '2026-09-24T18:00:00Z', 'scheduled', ?, ?, ?, ?, NULL, NULL)",
                    (fixture_id, rnd, home_id, home_code, away_id, away_code),
                )
                fixture_id += 1


def _unit(pid: int, pos: str, *, starter: bool, captain=False, sixth=False, coach=False) -> TeamRosterUnit:
    club_id, club_code = _CLUB_OF[pid]
    return TeamRosterUnit(
        player_id=pid,
        position=pos,
        name=f"P Unit{pid}",
        team_code=club_code,
        purchase_price_tenths=80,
        current_price_tenths=80,
        is_starter=starter,
        is_captain=captain,
        is_sixth_man=sixth,
        is_bench=not starter and not coach,
        is_coach=coach,
        turn_number=1,
    )


def _legal_squad() -> list[TeamRosterUnit]:
    """4G / 4F / 2C / 1HC."""
    units = [
        _unit(5000, "G", starter=True, captain=True),
        _unit(5001, "G", starter=True),
        _unit(5002, "G", starter=False, sixth=True),
        _unit(5003, "G", starter=False),
        _unit(5100, "F", starter=True),
        _unit(5101, "F", starter=True),
        _unit(5102, "F", starter=False),
        _unit(5103, "F", starter=False),
        _unit(5200, "C", starter=True),
        _unit(5201, "C", starter=False),
        _unit(5300, "HC", starter=False, coach=True),
    ]
    return units


@pytest.fixture()
def ctx(tmp_path: Path):
    db_file = tmp_path / "w5.sqlite3"
    _seed_market(db_file)

    service = TeamService(db_path=db_file)
    service.store.create_team(
        Team(team_id="bt", name="Backfill Team", season=SEASON, round_number=1, bank_tenths=500)
    )
    # Round 1 and round 2 both have stored state; the team's live round is 2.
    service.set_squad("bt", 1, _legal_squad(), validate=False)
    service.set_squad("bt", 2, _legal_squad(), validate=False)

    client = TestClient(create_app(db_path=db_file))
    return {"client": client, "service": service, "db": db_file}


def test_rounds_endpoint_enumerates_stored_rounds(ctx):
    res = ctx["client"].get("/api/teams/bt/rounds")
    assert res.status_code == 200
    body = res.json()
    assert body["current_round"] == 2
    assert body["rounds"] == [1, 2]


def test_lineup_without_round_targets_live_round_unchanged(ctx):
    """Pre-V0.7 behaviour must be byte-for-byte preserved when round is omitted."""
    client, service = ctx["client"], ctx["service"]
    before = service.get_team("bt").round_number

    res = client.post(
        "/api/teams/bt/lineup",
        json={
            "starter_ids": [5000, 5001, 5100, 5101, 5200],
            "captain_id": 5000,
            "sixth_man_id": 5002,
            "bench_ids": [5003, 5102, 5103, 5201],
            "coach_id": 5300,
        },
    )
    assert res.status_code == 200
    assert service.get_team("bt").round_number == before


def test_lineup_for_past_round_does_not_move_live_round(ctx):
    client, service = ctx["client"], ctx["service"]
    assert service.get_team("bt").round_number == 2

    res = client.post(
        "/api/teams/bt/lineup",
        json={
            "starter_ids": [5002, 5003, 5102, 5103, 5201],
            "captain_id": 5002,
            "sixth_man_id": 5000,
            "bench_ids": [5000, 5001, 5100, 5101],
            "coach_id": 5300,
            "round_number": 1,
        },
    )
    assert res.status_code == 200

    # The live round pointer must be untouched by a backfill.
    assert service.get_team("bt").round_number == 2

    # Round 1 now reflects the backfilled lineup...
    r1 = {u.player_id: u for u in service.store.get_squad("bt", 1)}
    assert r1[5002].is_starter is True
    assert r1[5002].is_captain is True
    assert r1[5000].is_starter is False

    # ...and round 2 is untouched.
    r2 = {u.player_id: u for u in service.store.get_squad("bt", 2)}
    assert r2[5000].is_starter is True
    assert r2[5002].is_starter is False


def test_lineup_for_round_without_squad_is_rejected(ctx):
    res = ctx["client"].post(
        "/api/teams/bt/lineup",
        json={
            "starter_ids": [5000],
            "captain_id": 5000,
            "sixth_man_id": 5001,
            "bench_ids": [],
            "coach_id": 5300,
            "round_number": 9,
        },
    )
    assert res.status_code == 400
    assert "no stored squad" in res.json()["detail"].lower()


def test_backfill_lineup_rejects_player_ids_outside_the_target_rounds_squad(ctx):
    """Round 1 must reject ids that only exist in round 2's squad, not silently drop them."""
    client, service = ctx["client"], ctx["service"]

    # Diverge round 2's squad from round 1's so 5004 is round-2-only.
    swapped = [u for u in _legal_squad() if u.player_id != 5003]
    swapped.append(_unit(5004, "G", starter=False))
    service.set_squad("bt", 2, swapped, validate=False)

    res = client.post(
        "/api/teams/bt/lineup",
        json={
            "starter_ids": [5000, 5001, 5100, 5101, 5200],
            "captain_id": 5000,
            "sixth_man_id": 5004,
            "bench_ids": [5002, 5003, 5102, 5103],
            "coach_id": 5300,
            "round_number": 1,
        },
    )
    assert res.status_code == 400
    assert "5004" in res.json()["detail"]


def test_backfill_lineup_rejects_a_malformed_resulting_shape(ctx):
    """Fewer than 5 starters must be rejected, not silently persisted."""
    res = ctx["client"].post(
        "/api/teams/bt/lineup",
        json={
            "starter_ids": [5000, 5001, 5100],
            "captain_id": 5000,
            "sixth_man_id": 5002,
            "bench_ids": [5003, 5101, 5102, 5103, 5200, 5201],
            "coach_id": 5300,
            "round_number": 1,
        },
    )
    assert res.status_code == 400
    assert "5 starters" in res.json()["detail"]


def test_lineup_backfill_preserves_downstream_checkpoints(ctx):
    """A lineup edit changes only role flags, so no later round is invalidated.

    Deleting downstream checkpoints here would destroy the live round's
    round-start baseline and permanently break `revert-round-start`.
    """
    service = ctx["service"]
    assert service.store.get_latest_checkpoint_before_round("bt", 2, SEASON) is not None

    res = ctx["client"].post(
        "/api/teams/bt/lineup",
        json={
            "starter_ids": [5002, 5003, 5102, 5103, 5201],
            "captain_id": 5002,
            "sixth_man_id": 5000,
            "bench_ids": [5000, 5001, 5100, 5101],
            "coach_id": 5300,
            "round_number": 1,
        },
    )
    assert res.status_code == 200

    with sqlite3.connect(ctx["db"]) as conn:
        remaining = conn.execute(
            "SELECT round_number FROM team_round_checkpoints WHERE team_id='bt' ORDER BY round_number;"
        ).fetchall()
    assert [r[0] for r in remaining] == [1, 2], "a lineup edit must not invalidate later checkpoints"

    # The live round's round-start baseline must still be usable.
    assert service.store.get_round_checkpoint("bt", 2, SEASON) is not None


def test_backfilled_squad_does_not_fabricate_a_checkpoint(ctx):
    """A backfill must not persist a "round-start" checkpoint built from today's live state."""
    service = ctx["service"]
    assert service.store.get_squad("bt", 3) == []

    service.set_squad("bt", 3, _legal_squad(), validate=False, advance_team_round=False)

    assert service.store.get_squad("bt", 3), "the squad itself must still be written"
    assert service.get_team("bt").round_number == 2, "the live round pointer must be untouched"

    with sqlite3.connect(ctx["db"]) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM team_round_checkpoints WHERE team_id='bt' AND round_number=3;"
        ).fetchone()[0]
    assert count == 0



def test_trades_are_recorded_as_events(ctx):
    """Only the resulting squad was stored before V0.7; the trades were lost."""
    client, service = ctx["client"], ctx["service"]

    res = client.post(
        "/api/teams/bt/transfers",
        json={
            "transfers_out_ids": [5003],
            "transfers_in_ids": [5004],
            "season": SEASON,
        },
    )
    assert res.status_code == 200, res.text

    events = service.store.get_transfers("bt", SEASON)
    assert len(events) == 1
    assert events[0]["player_out_id"] == 5003
    assert events[0]["player_in_id"] == 5004
    assert events[0]["round_number"] == 2
    assert events[0]["price_in_tenths"] > 0


def test_two_successive_trades_in_same_round_both_stay_recorded(ctx):
    """Recording used to ``clear_transfers`` on every request, wiping the prior trade."""
    client, service = ctx["client"], ctx["service"]

    res1 = client.post(
        "/api/teams/bt/transfers",
        json={"transfers_out_ids": [5003], "transfers_in_ids": [5004], "season": SEASON},
    )
    assert res1.status_code == 200, res1.text

    res2 = client.post(
        "/api/teams/bt/transfers",
        json={"transfers_out_ids": [5102], "transfers_in_ids": [5104], "season": SEASON},
    )
    assert res2.status_code == 200, res2.text

    events = service.store.get_transfers("bt", SEASON, round_number=2)
    assert len(events) == 2
    assert {(e["player_out_id"], e["player_in_id"]) for e in events} == {(5003, 5004), (5102, 5104)}


def test_trade_events_pair_outs_with_ins_in_request_order(ctx):
    """``zip(sorted(out_ids), new_contracts)`` used to mis-pair outs with ins."""
    client, service = ctx["client"], ctx["service"]

    res = client.post(
        "/api/teams/bt/transfers",
        json={
            "transfers_out_ids": [5102, 5003],
            "transfers_in_ids": [5104, 5004],
            "season": SEASON,
        },
    )
    assert res.status_code == 200, res.text

    events = {e["player_out_id"]: e for e in service.store.get_transfers("bt", SEASON, round_number=2)}
    assert events[5102]["player_in_id"] == 5104
    assert events[5003]["player_in_id"] == 5004
    assert events[5102]["price_out_tenths"] == 80
    assert events[5003]["price_out_tenths"] == 80
    assert events[5102]["price_in_tenths"] > 0
    assert events[5003]["price_in_tenths"] > 0


def test_trades_for_a_past_round_succeed_and_propagate_forward(ctx):
    """Past-round TRADE entry is supported in V0.7 W6 with forward replay (§3.2).

    A past-round trade applies to round n, writes the resulting bank/budget as the
    round-start checkpoint of n+1, replays forward through recorded team_transfers,
    updates the live round squad and bank, enforces the transfer cap, and keeps
    revert-round-start fully functional.
    """
    client, service = ctx["client"], ctx["service"]
    assert service.get_team("bt").round_number == 2

    # 1. Execute past-round trade in Round 1: sell 5003, buy 5004
    res = client.post(
        "/api/teams/bt/transfers",
        json={
            "transfers_out_ids": [5003],
            "transfers_in_ids": [5004],
            "season": SEASON,
            "round_number": 1,
        },
    )
    assert res.status_code == 200, res.text

    # Round 1 squad now has 5004 and not 5003
    r1_pids = {u.player_id for u in service.store.get_squad("bt", 1)}
    assert 5004 in r1_pids
    assert 5003 not in r1_pids

    # Round 2 squad received forward propagation
    r2_pids = {u.player_id for u in service.store.get_squad("bt", 2)}
    assert 5004 in r2_pids
    assert 5003 not in r2_pids

    # Round 2 start checkpoint was updated with forward propagation (overwrite=True, not deleted)
    r2_chk = service.store.get_round_checkpoint("bt", 2, SEASON)
    chk_pids = {u.player_id for u in r2_chk["squad"]}
    assert 5004 in chk_pids
    assert 5003 not in chk_pids

    # Revert round start on live round 2 restores cleanly to round 2's starting checkpoint
    reverted_team = service.revert_to_round_start("bt", SEASON, round_number=2)
    assert 5004 in {u.player_id for u in reverted_team.squad}

    # Attempting 4 trades in Round 1 when only 3 remain fails with 400
    res_cap = client.post(
        "/api/teams/bt/transfers",
        json={
            "transfers_out_ids": [5000, 5001, 5002, 5004],
            "transfers_in_ids": [5003, 5100, 5101, 5102],
            "season": SEASON,
            "round_number": 1,
        },
    )
    assert res_cap.status_code == 400
    assert "transfers remaining" in res_cap.text.lower()


def test_trades_for_the_live_round_still_work_when_round_is_named(ctx):
    """Naming the live round explicitly is allowed and behaves normally."""
    client, service = ctx["client"], ctx["service"]

    res = client.post(
        "/api/teams/bt/transfers",
        json={
            "transfers_out_ids": [5003],
            "transfers_in_ids": [5004],
            "season": SEASON,
            "round_number": 2,
        },
    )
    assert res.status_code == 200, res.text
    assert 5004 in {u.player_id for u in service.store.get_squad("bt", 2)}


def test_dashboard_for_a_past_round_uses_that_rounds_squad(ctx):
    """store.get_team always loads the LIVE round squad; a differing round must load its own."""
    client, service = ctx["client"], ctx["service"]

    # Diverge round 1's squad from round 2's so we can tell which one the dashboard used.
    round1_squad = [u for u in _legal_squad() if u.player_id != 5003]
    round1_squad.append(_unit(5004, "G", starter=False))
    service.set_squad("bt", 1, round1_squad, validate=False, advance_team_round=False)

    res = client.get("/api/workstation/dashboard", params={"team_id": "bt", "round_number": 1})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["round_number"] == 1

    squad_ids = {p["player_id"] for p in body["squad"]}
    assert 5004 in squad_ids and 5003 not in squad_ids

    bench_ids = {p["player_id"] for p in body["current_lineup"]["bench"]}
    assert 5004 in bench_ids
    assert body["current_lineup"]["captain_id"] == 5000

    # Round 2 (live) must be untouched by merely viewing round 1.
    r2_ids = {u.player_id for u in service.store.get_squad("bt", 2)}
    assert 5003 in r2_ids and 5004 not in r2_ids
    assert service.get_team("bt").round_number == 2


def test_viewing_a_past_round_does_not_overwrite_the_live_rounds_lineup(ctx):
    """The dashboard's auto role-backfill used to call update_lineup without a round_number,
    silently rewriting the LIVE round's lineup while merely viewing a past one."""
    client, service = ctx["client"], ctx["service"]

    # Round 1 has a squad but no role assignment yet (e.g. a fresh import), which forces
    # the dashboard's auto-sync branch to run.
    unassigned = [
        TeamRosterUnit(
            player_id=u.player_id,
            position=u.position,
            name=u.name,
            team_code=u.team_code,
            purchase_price_tenths=u.purchase_price_tenths,
            current_price_tenths=u.current_price_tenths,
            is_starter=False,
            is_captain=False,
            is_sixth_man=False,
            is_bench=(u.position != "HC"),
            is_coach=(u.position == "HC"),
            turn_number=u.turn_number,
        )
        for u in _legal_squad()
    ]
    service.set_squad("bt", 1, unassigned, validate=False, advance_team_round=False)

    before_round2 = [
        (u.player_id, u.is_starter, u.is_captain, u.is_sixth_man, u.is_bench, u.is_coach)
        for u in service.store.get_squad("bt", 2)
    ]

    res = client.get("/api/workstation/dashboard", params={"team_id": "bt", "round_number": 1})
    assert res.status_code == 200, res.text

    # The live round pointer and round 2's stored lineup are byte-for-byte unchanged.
    assert service.get_team("bt").round_number == 2
    after_round2 = [
        (u.player_id, u.is_starter, u.is_captain, u.is_sixth_man, u.is_bench, u.is_coach)
        for u in service.store.get_squad("bt", 2)
    ]
    assert after_round2 == before_round2

    # Round 1 itself was auto-synced to a full lineup by the dashboard's role backfill.
    round1 = service.store.get_squad("bt", 1)
    assert sum(1 for u in round1 if u.is_starter) == 5


def test_gui_exposes_a_round_selector_on_the_lineup_tab():
    root = Path(__file__).resolve().parents[1] / "src" / "euroleague_fantasy_manager" / "web"
    html = (root / "templates" / "index.html").read_text(encoding="utf-8")
    js = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")

    assert 'id="lineup-round-select"' in html, "Lineup tab must expose a round selector"
    assert "onLineupRoundChange" in js

    # The dashboard read must actually pass the chosen round.
    assert "round_number=${state.viewRoundNumber}" in js

    # Every lineup write must carry the viewed round when backfilling.
    assert "function lineupRoundPayload" in js
    assert js.count("...lineupRoundPayload()") >= 4

    # viewRoundNumber must be distinct from the team's live round pointer.
    assert "viewRoundNumber" in js and "state.roundNumber" in js
