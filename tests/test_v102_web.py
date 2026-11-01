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
