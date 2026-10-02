"""Ingestion module for official EuroLeague/EuroCup feeds and historical game data."""

from .historical_feeds import (
    HistoricalBoxscoreRecord,
    HistoricalFeedsClient,
    HistoricalGameRecord,
    HistoricalStatsStore,
    ingest_historical_data,
    resolve_feed_season_code,
)

__all__ = [
    "HistoricalBoxscoreRecord",
    "HistoricalFeedsClient",
    "HistoricalGameRecord",
    "HistoricalStatsStore",
    "ingest_historical_data",
    "resolve_feed_season_code",
]

