"""Web API routes for EuroLeague Fantasy Manager."""

from euroleague_fantasy_manager.web.api.routes_teams import router as teams_router
from euroleague_fantasy_manager.web.api.routes_workstation import router as workstation_router

__all__ = ["teams_router", "workstation_router"]
