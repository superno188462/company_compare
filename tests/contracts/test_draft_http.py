"""CONTRACT-1.0：BE-IF-04 手工线索草稿 HTTP 契约。"""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import create_app
from company_screening.contracts.boundary import ActorContext, ManualDraft, WorkspaceState
from company_screening.contracts.generated import CreditCode, Subject
from company_screening.services import ScreeningService, SessionService


def _app_with_confirmed_session() -> tuple[object, ActorContext, SessionService, object]:
    actor = ActorContext(actor_id=uuid4())
    sessions = SessionService()
    state = sessions.create(actor)
    subject = Subject(
        name="测试企业甲",
        credit_code=CreditCode("91310000MA1ABCDEF0"),
        registered_region=None,
        legal_representative=None,
        established_on=None,
        confirmed_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
    )
    sessions._confirm_subject(actor, state.session_id, subject, 0, False, uuid4())
    screening = ScreeningService(session_service=sessions)
    app = create_app(screening_service=screening, session_service=sessions)
    from backend.dependencies import get_actor
    app.dependency_overrides[get_actor] = lambda: actor
    return app, actor, sessions, state.session_id


def test_draft_http_save_restore_and_clear() -> None:
    """BE-IF-01/04：保存草稿可恢复，明确DELETE后草稿消失。"""
    app, _, _, sid = _app_with_confirmed_session()
    body = {
        "record_credit_code": None,
        "content": "待核对线索",
        "source_url": None,
        "observed_at": None,
        "event_time": None,
        "category": "other",
    }
    with TestClient(app) as client:
        saved_response = client.put(
            f"/api/v1/sessions/{sid}/draft",
            json=body,
            headers={"Idempotency-Key": str(uuid4())},
        )
        restored = client.get(f"/api/v1/sessions/{sid}")
        cleared = client.delete(
            f"/api/v1/sessions/{sid}/draft",
            headers={"Idempotency-Key": str(uuid4())},
        )
        after_clear = client.get(f"/api/v1/sessions/{sid}")

    assert saved_response.status_code == 200
    saved = ManualDraft.model_validate(saved_response.json())
    assert saved.issues == ["CREDIT_MISSING", "SOURCE_INFO_MISSING"]
    assert WorkspaceState.model_validate(restored.json()).draft == saved
    assert cleared.status_code == 204
    assert WorkspaceState.model_validate(after_clear.json()).draft is None


def test_draft_http_rejects_unconfirmed_subject() -> None:
    """BE-IF-04/ERR-01：绕过前端向未确认会话保存草稿返回脱敏409。"""
    actor = ActorContext(actor_id=uuid4())
    sessions = SessionService()
    state = sessions.create(actor)
    app = create_app(
        screening_service=ScreeningService(session_service=sessions),
        session_service=sessions,
    )
    from backend.dependencies import get_actor
    app.dependency_overrides[get_actor] = lambda: actor

    with TestClient(app) as client:
        response = client.put(
            f"/api/v1/sessions/{state.session_id}/draft",
            json={
                "record_credit_code": None,
                "content": "待核对线索",
                "source_url": None,
                "observed_at": None,
                "event_time": None,
                "category": "other",
            },
            headers={"Idempotency-Key": str(uuid4())},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SUBJECT_UNCONFIRMED"
