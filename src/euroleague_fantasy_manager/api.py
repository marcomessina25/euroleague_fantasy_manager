"""Zero-dependency client for official EuroLeague/EuroCup Fantasy Challenge & EuroLeague Feeds APIs."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from typing import Any
from urllib.request import Request, urlopen

from .rules import EUROLEAGUE_LEAGUE_ID


FANTASY_API_BASE_URL = "https://fantaking-api.dunkest.com/api/v1"
EUROLEAGUE_FEEDS_BASE_URL = "https://feeds.incrowdsports.com/provider/euroleague-feeds/v2"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) euroleague-fantasy-manager/0.1",
    "Accept": "application/json",
    "Origin": "https://euroleaguefantasy.euroleaguebasketball.net",
    "Referer": "https://euroleaguefantasy.euroleaguebasketball.net/",
}


def get_json(url: str, timeout_seconds: int = 25) -> Any:
    """Fetch JSON from a full URL using standard library urllib."""
    request = Request(url, headers=DEFAULT_HEADERS)
    with urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_fantasy_endpoint(endpoint: str, timeout_seconds: int = 25) -> Any:
    """Fetch a JSON payload from fantaking-api.dunkest.com/api/v1."""
    url = f"{FANTASY_API_BASE_URL}/{endpoint.lstrip('/')}"
    return get_json(url, timeout_seconds=timeout_seconds)


def fetch_league_config(league_id: int = EUROLEAGUE_LEAGUE_ID) -> dict[str, Any]:
    """Fetch the league configuration (teams, matchdays, current_matchday, game_modes_configs)."""
    payload = fetch_fantasy_endpoint(f"leagues/{league_id}/config")
    return payload.get("data", payload)


def fetch_matchday_schedule(schedule_id: int, matchday_id: int) -> dict[str, Any]:
    """Fetch all turns (rounds) and scheduled matches for a given matchday."""
    payload = fetch_fantasy_endpoint(f"schedules/{schedule_id}/matchdays/{matchday_id}")
    return payload.get("data", payload)


def fetch_match_lineups(match_id: int) -> dict[str, Any]:
    """Fetch home and away team rosters (players + head coaches, prices, statuses) for a match."""
    payload = fetch_fantasy_endpoint(f"matches/{match_id}/lineups")
    return payload.get("data", payload)


def fetch_player_profile(player_id: int, league_id: int = EUROLEAGUE_LEAGUE_ID) -> dict[str, Any]:
    """Fetch individual player or coach fantasy profile (quotation, popularity, total_plus, avg_fantasy_pts)."""
    payload = fetch_fantasy_endpoint(f"players/{player_id}/profile?league={league_id}")
    return payload.get("data", payload)


def fetch_official_clubs(competition_code: str = "E", season_code: str = "E2026") -> list[dict[str, Any]]:
    """Fetch official EuroLeague ('E') or EuroCup ('U') clubs from IncrowdSports v2 feeds."""
    url = f"{EUROLEAGUE_FEEDS_BASE_URL}/competitions/{competition_code}/seasons/{season_code}/clubs"
    try:
        payload = get_json(url)
        return payload.get("data", []) if isinstance(payload, dict) else []
    except Exception:
        return []


def fetch_current_data(
    league_id: int = EUROLEAGUE_LEAGUE_ID,
    competition_code: str = "E",
    season_code: str = "E2026",
    upcoming_rounds: int = 6,
) -> dict[str, Any]:
    """Fetch a complete point-in-time snapshot of config, multi-round schedules, match lineups, and official clubs."""
    config = fetch_league_config(league_id=league_id)
    schedule_id = int(config["current_schedule_id"])
    current_md = config["current_matchday"]
    matchday_id = int(current_md["id"])
    current_round_num = int(current_md.get("number", 1))

    all_matchdays = config.get("matchdays", [])
    target_mds = [
        md for md in all_matchdays
        if int(md.get("number", 0)) >= current_round_num
    ][: max(1, upcoming_rounds)]
    if not target_mds:
        target_mds = [{"id": matchday_id, "number": current_round_num}]

    schedules_by_num: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(6, len(target_mds))) as md_pool:
        future_to_num = {
            md_pool.submit(fetch_matchday_schedule, schedule_id, int(md["id"])): int(md.get("number", 1))
            for md in target_mds
        }
        for fut in as_completed(future_to_num):
            rnum = future_to_num[fut]
            try:
                sched_data = fut.result()
                sched_data["number"] = rnum
                schedules_by_num[rnum] = sched_data
            except Exception:
                pass

    schedule = schedules_by_num.get(current_round_num) or fetch_matchday_schedule(schedule_id=schedule_id, matchday_id=matchday_id)
    ordered_schedules = [schedules_by_num[k] for k in sorted(schedules_by_num)] or [schedule]

    match_ids: list[tuple[int, int]] = []
    for turn in schedule.get("rounds", []):
        turn_num = int(turn.get("number", 1))
        for match in turn.get("matches", []):
            match_ids.append((turn_num, int(match["id"])))

    lineups_by_match: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(10, max(1, len(match_ids)))) as pool:
        future_to_mid = {
            pool.submit(fetch_match_lineups, mid): (turn_num, mid)
            for turn_num, mid in match_ids
        }
        for future in as_completed(future_to_mid):
            turn_num, mid = future_to_mid[future]
            match_data = future.result()
            match_data["turn_number"] = turn_num
            lineups_by_match[mid] = match_data

    ordered_match_lineups = [lineups_by_match[mid] for _, mid in match_ids if mid in lineups_by_match]
    official_clubs = fetch_official_clubs(competition_code=competition_code, season_code=season_code)

    return {
        "league_id": league_id,
        "competition_code": competition_code,
        "season_code": season_code,
        "config": config,
        "schedule": schedule,
        "schedules": ordered_schedules,
        "match_lineups": ordered_match_lineups,
        "official_clubs": official_clubs,
    }
