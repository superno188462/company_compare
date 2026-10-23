"""CONTRACT-1.0：BE-IF-01、DATA-05 匿名Cookie会话HTTP契约。"""

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import create_app
from company_screening.contracts.boundary import ErrorEnvelope, WorkspaceState
from company_screening.services import SessionService


def test_create_session_sets_private_signed_cookie_and_replays_key() -> None:
    """BE-IF-01 / DATA-05：所有者只在HttpOnly Cookie中，同键不重复创建。"""
    app = create_app(session_service=SessionService())
    key = str(uuid4())

    with TestClient(app) as client:
        first = client.post("/api/v1/sessions", headers={"Idempotency-Key": key})
        replay = client.post("/api/v1/sessions", headers={"Idempotency-Key": key})

    assert first.status_code == 201
    assert replay.status_code == 201
    assert WorkspaceState.model_validate(first.json()).session_id == WorkspaceState.model_validate(replay.json()).session_id
    cookie = first.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "actor" not in first.text.lower()


def test_restore_requires_same_cookie_and_does_not_extend_expiry() -> None:
    """DATA-05：会话ID不是访问凭据，读取不续期。"""
    app = create_app(session_service=SessionService())
    with TestClient(app) as owner:
        created_response = owner.post("/api/v1/sessions", headers={"Idempotency-Key": str(uuid4())})
        created = WorkspaceState.model_validate(created_response.json())
        restored = owner.get(f"/api/v1/sessions/{created.session_id}")

    assert restored.status_code == 200
    assert WorkspaceState.model_validate(restored.json()).expires_at == created.expires_at

    with TestClient(app) as stranger:
        denied = stranger.get(f"/api/v1/sessions/{created.session_id}")
    assert denied.status_code == 404
    assert ErrorEnvelope.model_validate(denied.json()).error.code == "RESOURCE_NOT_FOUND"


def test_activity_renews_and_reset_expires_owned_session() -> None:
    """BE-NFR-02 / DATA-05：活动续期；结束后同所有者得到SESSION_EXPIRED。"""
    app = create_app(session_service=SessionService())
    with TestClient(app) as client:
        created = WorkspaceState.model_validate(client.post(
            "/api/v1/sessions", headers={"Idempotency-Key": str(uuid4())},
        ).json())
        activity = client.post(f"/api/v1/sessions/{created.session_id}/activity", json={})
        ended = client.delete(
            f"/api/v1/sessions/{created.session_id}",
            headers={"Idempotency-Key": str(uuid4())},
        )
        restored = client.get(f"/api/v1/sessions/{created.session_id}")

    assert activity.status_code == 200
    assert activity.json()["expires_at"] > created.expires_at.isoformat().replace("+00:00", "Z")
    assert ended.status_code == 204
    assert restored.status_code == 410
    assert ErrorEnvelope.model_validate(restored.json()).error.code == "SESSION_EXPIRED"
