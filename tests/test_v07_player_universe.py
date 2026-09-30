"""V0.7 W3 — the full player universe must be reachable for manual transfers.

Before V0.7 ``GET /api/workstation/players`` sorted by expected FP and then
sliced (``filtered[:limit]``), so the cheapest players could never be returned
no matter what the caller asked for — and the Trade Studio picker requested only
``limit=40``. Truncation is a display concern, never an existence concern.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from euroleague_fantasy_manager.web.app import create_app

APP_JS = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "euroleague_fantasy_manager"
    / "web"
    / "static"
    / "js"
    / "app.js"
)

MARKET_SIZE = 60

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


@pytest.fixture()
def client_with_market(tmp_path: Path) -> TestClient:
    """A workstation client backed by a market with a wide price/value spread."""
    db_file = tmp_path / "w3_market.sqlite3"
    with sqlite3.connect(db_file) as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT INTO snapshots (id, created_at, league_id, competition_code, season_code, "
            "matchday_id, round_number, num_turns, raw_archive_path) "
            "VALUES (1, '2026-09-24T10:00:00Z', 10, 'E', 'E2026', 1, 1, 2, 'raw.json')"
        )
        for i in range(MARKET_SIZE):
            pos_idx, pos_code = [(1, "G"), (2, "F"), (3, "C")][i % 3]
            # Price and scoring move together, so the cheapest players are also
            # the lowest projected -- precisely the cohort the old sort-then-slice
            # made unreachable.
            price = 40 + i * 3
            avg_fp = 2.0 + i * 0.4
            conn.execute(
                "INSERT INTO players (snapshot_id, id, first_name, last_name, name, position, "
                "position_code, team_id, team_code, team_name, price_tenths, status, "
                "probability_of_playing, turn_number, avg_fantasy_pts, last_match_pts, "
                "total_plus_tenths, popularity, is_injured, is_on_fire) "
                "VALUES (1, ?, ?, ?, ?, ?, ?, 140, 'BAR', 'FC Barcelona', ?, 'starter', "
                "1.0, 1, ?, 0.0, 0, 0.0, 0, 0)",
                (
                    5000 + i,
                    "P",
                    f"Player{i:03d}",
                    f"P Player{i:03d}",
                    pos_idx,
                    pos_code,
                    price,
                    avg_fp,
                ),
            )
        conn.execute(
            "INSERT INTO fixtures (snapshot_id, id, round_number, turn_number, started_at, status, "
            "home_team_id, home_team_code, away_team_id, away_team_code, home_score, away_score) "
            "VALUES (1, 100, 1, 1, '2026-09-24T18:00:00Z', 'scheduled', 140, 'BAR', 141, 'RMB', NULL, NULL)"
        )

    return TestClient(create_app(db_path=db_file))


def _names(payload):
    return [p["name"] for p in payload]


def test_cheapest_players_are_reachable_by_price_sort(client_with_market):
    """The regression: cheap players were unreachable at any limit."""
    client = client_with_market

    res = client.get("/api/workstation/players?sort=price_asc&limit=5")
    assert res.status_code == 200
    cheapest = res.json()
    assert len(cheapest) == 5

    prices = [p["price_tenths"] for p in cheapest]
    assert prices == sorted(prices), "price_asc must be ascending"

    # The single cheapest player in the market must be present.
    assert prices[0] == 40

    # And it must be absent from the default value-sorted first page, proving
    # the old behaviour genuinely hid it.
    top_by_value = client.get("/api/workstation/players?limit=5").json()
    assert 40 not in [p["price_tenths"] for p in top_by_value]


def test_total_count_header_reports_untruncated_total(client_with_market):
    client = client_with_market

    res = client.get("/api/workstation/players?limit=1")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert int(res.headers["X-Total-Count"]) == MARKET_SIZE


def test_total_count_reflects_filters_not_truncation(client_with_market):
    client = client_with_market
    res = client.get("/api/workstation/players?position=G&limit=2")
    assert res.status_code == 200
    assert int(res.headers["X-Total-Count"]) == MARKET_SIZE // 3
    assert len(res.json()) == 2


def test_offset_pages_through_the_whole_universe_without_gaps(client_with_market):
    client = client_with_market

    res_all = client.get("/api/workstation/players?limit=1000&sort=name")
    everyone = _names(res_all.json())
    total = int(res_all.headers["X-Total-Count"])
    assert total == MARKET_SIZE == len(everyone)

    page_size = 7
    collected: list[str] = []
    offset = 0
    while offset < total:
        res = client.get(
            f"/api/workstation/players?sort=name&limit={page_size}&offset={offset}"
        )
        assert res.status_code == 200
        collected.extend(_names(res.json()))
        offset += page_size

    assert collected == everyone, "paging must reproduce the universe exactly once"
    assert len(set(collected)) == len(collected), "paging must not duplicate players"


def test_offset_beyond_total_returns_empty_not_error(client_with_market):
    client = client_with_market
    res = client.get("/api/workstation/players?offset=100000&limit=10")
    assert res.status_code == 200
    assert res.json() == []
    assert int(res.headers["X-Total-Count"]) == MARKET_SIZE


def test_invalid_pagination_and_sort_are_rejected(client_with_market):
    client = client_with_market

    assert client.get("/api/workstation/players?limit=0").status_code == 400
    assert client.get("/api/workstation/players?limit=999999").status_code == 400
    assert client.get("/api/workstation/players?offset=-1").status_code == 400
    assert client.get("/api/workstation/players?sort=bogus").status_code == 400


def test_default_ordering_is_unchanged_for_existing_callers(client_with_market):
    """Backwards compatibility: callers passing only `limit` keep value ordering."""
    client = client_with_market
    res = client.get("/api/workstation/players?limit=10")
    assert res.status_code == 200
    fps = [p["expected_fp"] for p in res.json()]
    assert fps == sorted(fps, reverse=True)


def test_search_reaches_a_low_value_player_directly(client_with_market):
    """Search must find a cheap player the value-sorted page would never show."""
    client = client_with_market
    res = client.get("/api/workstation/players?search=Player000")
    assert res.status_code == 200
    hits = res.json()
    assert len(hits) == 1
    assert hits[0]["price_tenths"] == 40


def test_gui_does_not_hardcode_a_small_player_limit():
    source = APP_JS.read_text(encoding="utf-8")

    assert "limit=40" not in source, "the Trade Studio picker must not hardcode limit=40"
    assert re.search(r"const\s+PLAYER_POOL_PAGE_SIZE\s*=", source)
    assert "X-Total-Count" in source, "the GUI must read the advertised total"
    assert "playerPoolNextPage" in source and "playerPoolPrevPage" in source
