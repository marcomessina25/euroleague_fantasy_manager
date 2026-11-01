"""Zero-dependency client for official EuroLeague/EuroCup Fantasy Challenge & EuroLeague Feeds APIs."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
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


def _get_json(
    url: str,
    *,
    retries: int = 3,
    backoff: float = 0.5,
    timeout: int = 15,
) -> Any:
    """Fetch JSON from a full URL with retries on URLError, 429 and 5xx."""
    last_exc: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            request = Request(url, headers=DEFAULT_HEADERS)
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as e:
            last_exc = e
            if e.code == 429 or 500 <= e.code < 600:
                if attempt < retries - 1:
                    time.sleep(backoff * (2**attempt))
                    continue
            raise
        except URLError as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(backoff * (2**attempt))
                continue
            raise
        except Exception as e:
            last_exc = e
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed to fetch {url}")


def get_json(url: str, timeout_seconds: int = 25) -> Any:
    """Fetch JSON from a full URL using standard library urllib."""
    return _get_json(url, timeout=timeout_seconds)


def fetch_fantasy_endpoint(endpoint: str, timeout_seconds: int = 25) -> Any:
    """Fetch a JSON payload from fantaking-api.dunkest.com/api/v1."""
    url = f"{FANTASY_API_BASE_URL}/{endpoint.lstrip('/')}"
    return _get_json(url, timeout=timeout_seconds)


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


def fetch_player_profile(
    player_id: int,
    league_id: int = EUROLEAGUE_LEAGUE_ID,
    round_number: int | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Fetch individual player or coach fantasy profile with on-disk caching keyed by (player_id, round)."""
    if cache_dir is not None and round_number is not None:
        c_path = cache_dir / f"profile_{player_id}_r{round_number}.json"
        if c_path.exists():
            try:
                return json.loads(c_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    url = f"{FANTASY_API_BASE_URL}/players/{player_id}/profile?league={league_id}"
    payload = _get_json(url)
    data = payload.get("data", payload)

    if cache_dir is not None and round_number is not None and isinstance(data, dict):
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            c_path = cache_dir / f"profile_{player_id}_r{round_number}.json"
            c_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    return data


import re


def resolve_season_code(
    config: dict[str, Any],
    competition_code: str,
    override: str | None = None,
) -> tuple[str, str]:
    """Resolve season code from explicit override or config payload, returning (season_code, source)."""
    if override:
        return override.strip(), "override"

    if config.get("season_code"):
        return str(config["season_code"]).strip(), "config"
    if config.get("season"):
        raw_s = str(config["season"]).strip()
        year_match = re.search(r"20\d{2}", raw_s)
        if year_match:
            return f"{competition_code}{year_match.group(0)}", "config"

    cur_round = config.get("current_round", {})
    if isinstance(cur_round, dict):
        started_at = str(cur_round.get("started_at", ""))
        year_match = re.search(r"20\d{2}", started_at)
        if year_match:
            return f"{competition_code}{year_match.group(0)}", "config"

    for md in config.get("matchdays", []):
        for rnd in md.get("rounds", []):
            started_at = str(rnd.get("started_at", ""))
            year_match = re.search(r"20\d{2}", started_at)
            if year_match:
                return f"{competition_code}{year_match.group(0)}", "config"

    # Documented fallback if no season/timestamp could be extracted from feed
    return f"{competition_code}2026", "fallback"


def fetch_official_clubs(competition_code: str = "E", season_code: str | None = None) -> list[dict[str, Any]]:
    """Fetch official EuroLeague ('E') or EuroCup ('U') clubs from IncrowdSports v2 feeds."""
    code = season_code or f"{competition_code}2026"
    url = f"{EUROLEAGUE_FEEDS_BASE_URL}/competitions/{competition_code}/seasons/{code}/clubs"
    try:
        payload = get_json(url)
        return payload.get("data", []) if isinstance(payload, dict) else []
    except Exception:
        return []


def fetch_current_data(
    league_id: int = EUROLEAGUE_LEAGUE_ID,
    competition_code: str = "E",
    season_code: str | None = None,
    upcoming_rounds: int = 6,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Fetch a complete point-in-time snapshot of config, multi-round schedules, match lineups, and official clubs."""
    config = fetch_league_config(league_id=league_id)
    resolved_season_code, season_code_source = resolve_season_code(config, competition_code, override=season_code)
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

    unique_player_ids: set[int] = set()
    for mdata in ordered_match_lineups:
        for side in ("home_team", "away_team"):
            for p in mdata.get(side, {}).get("lineups", []):
                pid = p.get("id")
                if pid:
                    unique_player_ids.add(int(pid))

    profiles_by_id: dict[int, dict[str, Any]] = {}
    missing_fields_set: set[str] = set()
    if unique_player_ids:
        with ThreadPoolExecutor(max_workers=min(8, len(unique_player_ids))) as profile_pool:
            future_to_pid = {
                profile_pool.submit(fetch_player_profile, pid, league_id, current_round_num, cache_dir): pid
                for pid in unique_player_ids
            }
            for fut in as_completed(future_to_pid):
                pid = future_to_pid[fut]
                try:
                    prof = fut.result()
                    if isinstance(prof, dict):
                        profiles_by_id[pid] = prof
                    else:
                        missing_fields_set.add("avg_fantasy_pts")
                except Exception:
                    missing_fields_set.add("avg_fantasy_pts")

    for mdata in ordered_match_lineups:
        for side in ("home_team", "away_team"):
            for p in mdata.get(side, {}).get("lineups", []):
                pid = int(p.get("id", 0))
                prof = profiles_by_id.get(pid)
                if prof:
                    if p.get("avg_fantasy_pts") is None:
                        p["avg_fantasy_pts"] = prof.get("avg_fantasy_pts")
                    if p.get("popularity") is None:
                        p["popularity"] = prof.get("popularity")
                    if p.get("total_plus") is None:
                        p["total_plus"] = prof.get("total_plus")

    official_clubs = fetch_official_clubs(competition_code=competition_code, season_code=resolved_season_code)

    return {
        "league_id": league_id,
        "competition_code": competition_code,
        "season_code": resolved_season_code,
        "season_code_source": season_code_source,
        "config": config,
        "schedule": schedule,
        "schedules": ordered_schedules,
        "match_lineups": ordered_match_lineups,
        "official_clubs": official_clubs,
        "player_profiles": profiles_by_id,
        "missing_fields": sorted(missing_fields_set),
    }

