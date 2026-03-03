import pytest
from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_greeting_doesnt_classify():
    """Greetings should stay in OPEN state"""
    resp = client.post(
        "/chat",
        json={"chat_id": "testuser", "session_id": None, "message": "hello"},
        headers={"X-API-Key": "test-key.test-secret-123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    state = (data.get("updatedConversationState") or {}).get("state")
    assert state in (None, "OPEN_INTAKE", "OPEN")


def test_complete_conversation_flow():
    """Full flow from greeting to submission"""
    headers = {"X-API-Key": "test-key.test-secret-123"}

    # Start conversation
    r1 = client.post(
        "/chat",
        json={"chat_id": "flowuser", "session_id": None, "message": "hi"},
        headers=headers,
    )
    assert r1.status_code == 200
    body1 = r1.json()
    session_id = body1["session_id"]

    # Describe an issue that should classify clearly
    r2 = client.post(
        "/chat",
        json={
            "chat_id": "flowuser",
            "session_id": session_id,
            "message": "there is a water leak on my street",
        },
        headers=headers,
    )
    assert r2.status_code == 200

    # Provide a location
    r3 = client.post(
        "/chat",
        json={
            "chat_id": "flowuser",
            "session_id": session_id,
            "message": "123 Main Street, Johannesburg",
        },
        headers=headers,
    )
    assert r3.status_code == 200

    # Confirm
    r4 = client.post(
        "/chat",
        json={
            "chat_id": "flowuser",
            "session_id": session_id,
            "message": "yes, that's correct",
        },
        headers=headers,
    )
    assert r4.status_code == 200


def test_invalid_api_key():
    """Should reject invalid API keys"""
    resp = client.post(
        "/chat",
        json={"chat_id": "testuser", "session_id": None, "message": "hello"},
        headers={"X-API-Key": "invalid-key"},
    )
    assert resp.status_code in (401, 403, 409)


def test_empty_message():
    """Should handle empty messages gracefully"""
    resp = client.post(
        "/chat",
        json={"chat_id": "testuser", "session_id": None, "message": "   "},
        headers={"X-API-Key": "test-key.test-secret-123"},
    )
    # Pydantic validation should reject this
    assert resp.status_code == 422


def test_database_failure(monkeypatch):
    """Should have fallback when DB is down"""
    from src.core import session_manager as sm_module

    original_get_pool = sm_module.pg_fetchone

    def failing_pg_fetchone(*args, **kwargs):
        import psycopg2

        raise psycopg2.OperationalError("simulated failure")

    monkeypatch.setattr(sm_module, "pg_fetchone", failing_pg_fetchone)

    try:
        resp = client.post(
            "/chat",
            json={"chat_id": "failuser", "session_id": None, "message": "hello"},
            headers={"X-API-Key": "test-key.test-secret-123"},
        )
        # Even if DB fails, the global handler should return JSON 500, not crash
        assert resp.status_code in (200, 500)
        data = resp.json()
        assert isinstance(data, dict)
    finally:
        monkeypatch.setattr(sm_module, "pg_fetchone", original_get_pool)

