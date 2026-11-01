"""Multi-team management module for EuroLeague Fantasy Manager."""

from euroleague_fantasy_manager.multi_team.migrations import (
    MigrationReport,
    backfill_transfers_from_snapshots,
    inspect_database_health,
    migrate_transfers_schema,
)
from euroleague_fantasy_manager.multi_team.models import (
    AuditIntent,
    Team,
    TeamRosterUnit,
    TeamSettings,
    TeamStateSnapshot,
)
from euroleague_fantasy_manager.multi_team.store import (
    MAX_TEAMS,
    ConcurrentModificationError,
    TeamStore,
)

__all__ = [
    "AuditIntent",
    "MAX_TEAMS",
    "ConcurrentModificationError",
    "MigrationReport",
    "Team",
    "TeamRosterUnit",
    "TeamSettings",
    "TeamStateSnapshot",
    "TeamStore",
    "backfill_transfers_from_snapshots",
    "inspect_database_health",
    "migrate_transfers_schema",
]
