"""Tests for POST /api/kitchen endpoint (TDD — write tests first).

Run from repo root:
    cd server && ../.venv/bin/pytest web/tests/test_kitchen.py -v
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app


# ── helpers ───────────────────────────────────────────────────────────────────

def _client():
    """Return TestClient (handles lifespan automatically)."""
    return TestClient(app, raise_server_exceptions=True)


# ── POST /api/kitchen  ────────────────────────────────────────────────────────


def test_kitchen_menu_ready_creates_task_with_correct_payload():
    """menu_ready action must create a TABLE_TO_DISPLAY task destined for KITCHEN."""
    captured: list[tuple] = []

    async def fake_control_post(path: str, payload: dict) -> dict:
        captured.append((path, payload))
        return {"task_id": "T-0042"}

    with patch("main._control_post", side_effect=fake_control_post):
        with _client() as c:
            resp = c.post(
                "/api/kitchen",
                json={"action": "menu_ready", "disp_id": "DISP_01"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["task_id"] == "T-0042"
    assert body["disp_id"] == "DISP_01"

    assert len(captured) == 1, "expected exactly one control-server call"
    path, payload = captured[0]
    assert path == "/tasks"
    assert payload["task_type"] == 3        # TABLE_TO_DISPLAY
    assert payload["dest_id"] == "KITCHEN"
    assert payload.get("priority", 0) >= 2  # at least NORMAL priority


def test_kitchen_menu_ready_missing_disp_id_returns_422():
    """menu_ready without disp_id should be rejected with 422."""
    with _client() as c:
        resp = c.post("/api/kitchen", json={"action": "menu_ready"})

    assert resp.status_code == 422


def test_kitchen_menu_ready_empty_disp_id_returns_422():
    """menu_ready with empty disp_id string should be rejected with 422."""
    with _client() as c:
        resp = c.post("/api/kitchen", json={"action": "menu_ready", "disp_id": "  "})

    assert resp.status_code == 422


def test_kitchen_unknown_action_returns_ok():
    """Unknown / legacy actions must not raise — return 200 ok."""
    with _client() as c:
        resp = c.post("/api/kitchen", json={"action": "some_legacy_event"})

    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_kitchen_empty_body_returns_ok():
    """Empty body (no action key) should not crash — return 200 ok."""
    with _client() as c:
        resp = c.post("/api/kitchen", json={})

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
