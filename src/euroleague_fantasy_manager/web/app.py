"""FastAPI application factory and workstation server runner (Phase C to M)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import webbrowser

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from euroleague_fantasy_manager.multi_team.store import TeamStore
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.web.api.routes_teams import router as teams_router
from euroleague_fantasy_manager.web.api.routes_workstation import router as workstation_router
from euroleague_fantasy_manager.web.deps import set_db_path


def create_app(db_path: str | Path = "data/euroleague.sqlite3") -> FastAPI:
    """Create and configure the local FastAPI workstation application."""
    set_db_path(db_path)

    app = FastAPI(
        title="EuroLeague Fantasy Manager Workstation",
        description="Local-first decision-support and multi-team management workstation.",
        version="0.5.0",
    )

    web_dir = Path(__file__).parent
    static_dir = web_dir / "static"
    templates_dir = web_dir / "templates"

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(teams_router)
    app.include_router(workstation_router)

    # Initialize default team if none exist
    _ensure_initial_team(db_path)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        index_file = templates_dir / "index.html"
        if index_file.exists():
            return index_file.read_text(encoding="utf-8")
        return "<h1>EuroLeague Fantasy Workstation</h1><p>Template not found.</p>"

    return app


def _ensure_initial_team(db_path: str | Path) -> None:
    """Populate default team from config if database is empty."""
    store = TeamStore(db_path=db_path)
    teams = store.list_teams()
    if not teams:
        ts = TeamService(store=store)
        # Check if config squad exists
        cfg_path = Path("config/current_squad.json")
        if not cfg_path.exists():
            cfg_path = Path("config/current_squad.example.json")

        if cfg_path.exists():
            try:
                ts.import_from_config(team_id="team_1", config_path=cfg_path)
                return
            except Exception:
                pass

        # Fallback create empty team
        ts.create_team(
            team_id="team_1",
            name="Primary Squad",
            season="2026/27",
            round_number=1,
            turn_number=1,
            bank_tenths=100,
        )


def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = False,
    db_path: str | Path = "data/euroleague.sqlite3",
) -> None:
    """Run local uvicorn development server."""
    import uvicorn

    app = create_app(db_path=db_path)
    url = f"http://{host}:{port}"
    print(f"\n🏀 EuroLeague Fantasy Workstation starting on {url}")
    print("Press Ctrl+C to stop.\n")

    if open_browser:
        webbrowser.open(url)

    uvicorn.run(app, host=host, port=port, log_level="info")
