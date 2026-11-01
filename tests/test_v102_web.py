"""Tests for Phase P5: Local server security & frontend state (v102.md Phase P5)."""

from pathlib import Path
import pytest
from starlette.testclient import TestClient

from euroleague_fantasy_manager import __version__
from euroleague_fantasy_manager.web.app import create_app, run_server


def test_p5_1_trusted_host_blocks_unauthorized_host(tmp_path: Path):
    """WEB-1: Non-whitelisted Host header is rejected with 400 Bad Request."""
    db_file = tmp_path / "web_sec.sqlite3"
    app = create_app(db_path=db_file)
    client = TestClient(app)

    # Valid hosts
    for h in ("localhost", "127.0.0.1", "testserver"):
        res = client.get("/", headers={"host": h})
        assert res.status_code == 200

    # Invalid host
    res_bad = client.get("/", headers={"host": "attacker.evil.com"})
    assert res_bad.status_code == 400


def test_p5_1_cross_origin_mutation_forbidden(tmp_path: Path):
    """WEB-1: State-mutating methods with cross-origin Origin are rejected with 403."""
    db_file = tmp_path / "web_sec.sqlite3"
    app = create_app(db_path=db_file)
    client = TestClient(app)

    # Cross-origin POST
    res = client.post(
        "/api/teams",
        headers={"origin": "http://evil.com"},
        json={"name": "Hack Squad", "league": "euroleague"},
    )
    assert res.status_code == 403
    assert "Cross-origin mutation forbidden" in res.text

    # Cross-origin DELETE
    res_del = client.delete(
        "/api/teams/fake_id",
        headers={"origin": "https://malicious.org"},
    )
    assert res_del.status_code == 403


def test_p5_1_mutation_requires_json_content_type(tmp_path: Path):
    """WEB-1: State-mutating methods with body require application/json or multipart/form-data."""
    db_file = tmp_path / "web_sec.sqlite3"
    app = create_app(db_path=db_file)
    client = TestClient(app)

    # POST with body and text/plain -> 415
    res = client.post(
        "/api/teams",
        headers={"content-type": "text/plain"},
        content=b"some plain text body",
    )
    assert res.status_code == 415
    assert "Content-Type must be application/json" in res.text


def test_p5_1_local_origin_allowed(tmp_path: Path):
    """WEB-1: Mutations from localhost / 127.0.0.1 origins are allowed."""
    db_file = tmp_path / "web_sec.sqlite3"
    app = create_app(db_path=db_file)
    client = TestClient(app)

    res = client.post(
        "/api/teams",
        headers={"origin": "http://localhost:8000"},
        json={"name": "Valid Local Team", "league": "euroleague", "season": "2026/27", "round_number": 1},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Valid Local Team"


def test_p5_1_security_headers_present_on_all_responses(tmp_path: Path):
    """WEB-10: CSP, nosniff, DENY, and Referrer-Policy headers are present."""
    db_file = tmp_path / "web_sec.sqlite3"
    app = create_app(db_path=db_file)
    client = TestClient(app)

    res = client.get("/")
    assert res.status_code == 200
    assert "default-src 'self'" in res.headers["content-security-policy"]
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["referrer-policy"] == "no-referrer"


def test_p5_1_version_endpoint_and_badge(tmp_path: Path):
    """WEB-10: GET /api/version returns single-sourced package version."""
    db_file = tmp_path / "web_sec.sqlite3"
    app = create_app(db_path=db_file)
    client = TestClient(app)

    res = client.get("/api/version")
    assert res.status_code == 200
    assert res.json() == {"version": __version__}


def test_p5_1_run_server_rejects_external_hosts():
    """WEB-1: run_server raises ValueError if non-local host is requested."""
    with pytest.raises(ValueError, match="forbidden"):
        run_server(host="0.0.0.0")

    with pytest.raises(ValueError, match="forbidden"):
        run_server(host="192.168.1.50")


def test_p5_2_static_no_inline_template_handlers():
    """WEB-2: Static check that app.js contains no inline on*="...${ handlers."""
    import re

    app_js = Path(__file__).resolve().parent.parent / "src" / "euroleague_fantasy_manager" / "web" / "static" / "js" / "app.js"
    assert app_js.is_file()
    content = app_js.read_text(encoding="utf-8")

    pat = r'on[a-z]+\s*=\s*["\']' + r'[^"\']*\$\{'
    matches = re.findall(pat, content, re.IGNORECASE)
    assert len(matches) == 0, f"Found {len(matches)} inline template handlers in app.js: {matches}"


def test_p5_2_node_render_test():
    """WEB-2: Run Node.js rendering and click delegation harness."""
    import shutil
    import subprocess

    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("Node.js not installed on system")

    js_test = Path(__file__).resolve().parent / "js" / "test_render.mjs"
    assert js_test.is_file()

    res = subprocess.run([node_bin, str(js_test)], capture_output=True, text=True)
    assert res.returncode == 0, f"Node render test failed: {res.stderr}\n{res.stdout}"
    assert "All JS render tests passed" in res.stdout


def test_p5_2_team_id_validation_regex(tmp_path: Path):
    """WEB-10: Server validates team_id against ^[A-Za-z0-9_-]{1,40}$ on create."""
    db_file = tmp_path / "team_val.sqlite3"
    app = create_app(db_path=db_file)
    client = TestClient(app)

    # Valid team_ids
    for valid_id in ("team_val_1", "team-alpha", "TEAM_2026", "a" * 40):
        res = client.post("/api/teams", json={
            "team_id": valid_id,
            "name": f"Team {valid_id}",
            "league": "euroleague",
        })
        assert res.status_code == 200, f"Expected 200 for valid team_id '{valid_id}', got {res.status_code}"

    # Invalid team_ids
    for invalid_id in ("team/evil", "team id", "team<script>", "a" * 41, "", "team.dot"):
        res = client.post("/api/teams", json={
            "team_id": invalid_id,
            "name": "Invalid Team",
            "league": "euroleague",
        })
        assert res.status_code == 422, f"Expected 422 for invalid team_id '{invalid_id}', got {res.status_code}"


def test_p5_2_team_id_migration(tmp_path: Path):
    """WEB-10: TeamStore migration safely renames legacy invalid team_ids."""
    import sqlite3
    from euroleague_fantasy_manager.multi_team.store import TeamStore

    db_file = tmp_path / "legacy_teams.sqlite3"
    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE managed_teams (
            team_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            league TEXT NOT NULL DEFAULT 'euroleague',
            mode TEXT NOT NULL DEFAULT 'classic',
            season TEXT NOT NULL DEFAULT '2026/27',
            round_number INTEGER NOT NULL DEFAULT 1,
            turn_number INTEGER NOT NULL DEFAULT 1,
            bank_tenths INTEGER NOT NULL DEFAULT 0,
            transfers_remaining INTEGER NOT NULL DEFAULT 4,
            settings_json TEXT NOT NULL DEFAULT '{}',
            is_active INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
    """)
    conn.execute("INSERT INTO managed_teams (team_id, name) VALUES ('team invalid/bad! id', 'Legacy Team');")
    conn.commit()
    conn.close()

    # Initializing TeamStore runs migration
    store = TeamStore(db_path=db_file)
    teams = store.list_teams()
    assert len(teams) == 1
    migrated_id = teams[0].team_id
    import re
    assert re.match(r"^[A-Za-z0-9_-]{1,40}$", migrated_id)
    assert migrated_id.startswith("team_invalid_bad__id")


def test_p5_3_dashboard_missing_squad_returns_404(tmp_path: Path):
    """WEB-4, WEB-8: For a round without a stored squad, dashboard returns 404 with code 'no_squad_for_round'."""
    db_file = tmp_path / "dash_missing.sqlite3"
    app = create_app(db_path=db_file)
    client = TestClient(app)

    # team_1 exists but has empty squad
    res = client.get("/api/workstation/dashboard?team_id=team_1&season=2026/27&round_number=2")
    assert res.status_code == 404
    data = res.json()
    assert "detail" in data
    assert data["detail"].get("code") == "no_squad_for_round"


def test_p5_3_new_empty_team_defaults_to_100_credits(tmp_path: Path):
    """WEB-4: New empty teams default to bank_tenths: 1000 (100.0 credits)."""
    db_file = tmp_path / "new_team_bank.sqlite3"
    app = create_app(db_path=db_file)
    client = TestClient(app)

    res = client.post("/api/teams", json={
        "team_id": "team_new_100",
        "name": "Hundred Credit Squad",
        "league": "euroleague",
        "round_number": 1,
    })
    assert res.status_code == 200
    team_data = res.json()
    assert team_data["bank_tenths"] == 1000
    assert team_data["bank_credits"] == 100.0
