"""FastAPI application factory and workstation server runner (Phase C to M)."""

from __future__ import annotations

import logging
from pathlib import Path
import webbrowser

from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from euroleague_fantasy_manager import __version__

from euroleague_fantasy_manager import paths
from euroleague_fantasy_manager.multi_team.store import TeamStore
from euroleague_fantasy_manager.services.decision_service import DecisionService
from euroleague_fantasy_manager.services.evaluation_service import EvaluationService
from euroleague_fantasy_manager.services.optimization_service import OptimizationService
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.services.scenario_service import ScenarioService
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.tracking.store import DecisionStore
from euroleague_fantasy_manager.web.api.routes_intelligence import router as intelligence_router
from euroleague_fantasy_manager.web.api.routes_teams import router as teams_router
from euroleague_fantasy_manager.web.api.routes_workstation import router as workstation_router

logger = logging.getLogger(__name__)


def create_app(db_path: str | Path = "data/euroleague.sqlite3") -> FastAPI:
    """Create and configure the local FastAPI workstation application."""
    db_path = Path(db_path)

    app = FastAPI(
        title="EuroLeague Fantasy Manager Workstation",
        description="Local-first decision-support and multi-team management workstation.",
        version=__version__,
    )

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
    )

    @app.middleware("http")
    async def same_origin_json_only(request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin:
                parsed = urlparse(origin)
                if parsed.hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
                    return Response("Cross-origin mutation forbidden", status_code=403)
            # Require JSON content type on mutations with body
            ct = request.headers.get("content-type", "")
            if request.headers.get("content-length") not in {None, "0"}:
                if not ct.startswith("application/json") and not ct.startswith("multipart/form-data"):
                    return Response("Content-Type must be application/json", status_code=415)
        response = await call_next(request)
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    team_store = TeamStore(db_path=db_path)
    team_service = TeamService(store=team_store)
    prediction_service = PredictionService(database_path=db_path)
    decision_store = DecisionStore(database_path=db_path)
    decision_service = DecisionService(store=decision_store)
    evaluation_service = EvaluationService(store=decision_store)
    optimization_service = OptimizationService(
        team_service=team_service,
        prediction_service=prediction_service,
    )
    scenario_service = ScenarioService(
        team_service=team_service,
        prediction_service=prediction_service,
        optimization_service=optimization_service,
    )

    app.state.db_path = db_path
    app.state.team_store = team_store
    app.state.team_service = team_service
    app.state.prediction_service = prediction_service
    app.state.decision_store = decision_store
    app.state.decision_service = decision_service
    app.state.evaluation_service = evaluation_service
    app.state.optimization_service = optimization_service
    app.state.scenario_service = scenario_service

    web_dir = Path(__file__).parent
    static_dir = web_dir / "static"
    templates_dir = web_dir / "templates"

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(teams_router)
    app.include_router(workstation_router)
    app.include_router(intelligence_router)

    # Initialize default team if none exist
    _ensure_initial_team(team_service)

    @app.get("/api/version")
    def get_version() -> dict[str, str]:
        return {"version": __version__}

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        index_file = templates_dir / "index.html"
        if index_file.exists():
            return index_file.read_text(encoding="utf-8")
        return "<h1>EuroLeague Fantasy Workstation</h1><p>Template not found.</p>"

    return app


def _ensure_initial_team(team_service: TeamService) -> None:
    """Populate default team from config if database is empty."""
    teams = team_service.list_teams()
    if not teams:
        # Check if config squad exists
        cfg_path = paths.squad_config_path()
        if not cfg_path.exists() and Path("config/current_squad.json").exists():
            cfg_path = Path("config/current_squad.json")
        elif not cfg_path.exists():
            cfg_path = paths.elf_home() / "config" / "current_squad.example.json"
            if not cfg_path.exists() and Path("config/current_squad.example.json").exists():
                cfg_path = Path("config/current_squad.example.json")

        if cfg_path.exists():
            try:
                team_service.import_from_config(team_id="team_1", config_path=cfg_path)
                return
            except Exception as e:  # noqa: BLE001 - seeding is best-effort; fall back to an empty team
                logger.warning("Not seeding team_1 from %s: %s", cfg_path, e)

        # Fallback create empty team
        team_service.create_team(
            team_id="team_1",
            name="Primary Squad",
            season="2026/27",
            round_number=1,
            turn_number=1,
            bank_tenths=1000,
        )


def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = False,
    db_path: str | Path = "data/euroleague.sqlite3",
) -> None:
    """Run local uvicorn development server."""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Binding to external host '{host}' is forbidden for local workstation security.")
    import uvicorn

    app = create_app(db_path=db_path)

    if open_browser:
        webbrowser.open(f"http://{host}:{port}/")

    logger.info("Starting EuroLeague Fantasy Workstation on http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
