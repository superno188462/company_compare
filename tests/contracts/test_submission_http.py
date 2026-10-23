"""待评审：CONTRACT-1.0，BE-IF-04/06 与 BE-ERR-01 的传输契约。"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.dependencies import get_actor
from test_submission_service import make_workspace, save_draft, submit_command


def test_http_submission_returns_202_and_terminal_payload(validators):
    """BE-IF-04/06：提交返回句柄，排队不泄露半段结果，轮询终态返回完整结构。"""
    ctx = make_workspace()
    saved = save_draft(ctx)
    command = submit_command(ctx, saved)
    app = create_app(screening_service=ctx.service, session_service=ctx.sessions)
    app.dependency_overrides[get_actor] = lambda: ctx.actor
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/sessions/{ctx.sid}/evidence",
            json=command.model_dump(mode="json"),
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 202
        handle = response.json()
        assert set(handle) == {"operation_id", "session_id", "session_generation"}
        path = f"/api/v1/sessions/{ctx.sid}/operations/{handle['operation_id']}"
        pending = client.get(path).json()
        assert pending["result"] is None and pending["error"] is None
        ctx.queued.pop(0)()
        completed = client.get(path)
        assert completed.status_code == 200
        body = completed.json()
        assert body["state"] == "succeeded"
        validators[1].validate(body["result"])
        assert len(body["result"]["evidence_list"]) == 1


def test_http_wrong_subject_preserves_draft_and_uses_structured_error():
    """BE-ERR-01：代码错配返回422；不暴露原文、凭据或堆栈。"""
    ctx = make_workspace()
    saved = save_draft(ctx, record_credit_code="91310000MA1ABCDEFX", content="私有测试正文不应进入错误包")
    app = create_app(screening_service=ctx.service, session_service=ctx.sessions)
    app.dependency_overrides[get_actor] = lambda: ctx.actor
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/sessions/{ctx.sid}/evidence",
            json=submit_command(ctx, saved).model_dump(mode="json"),
            headers={"Idempotency-Key": str(uuid4())},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CREDIT_MISMATCH"
    assert response.json()["error"]["hint_id"] == "CREDIT_MISMATCH"
    assert saved.content not in response.text and "Traceback" not in response.text
    assert ctx.sessions.restore(ctx.actor, ctx.sid).draft == saved
    assert ctx.queued == []


@pytest.mark.parametrize("field", ["source", "system_prompt", "question"])
def test_http_submission_rejects_client_source_and_model_overrides(field):
    """BE-IF-04/05：客户端不能越过服务端来源判定或注入模型控制字段。"""
    ctx = make_workspace()
    saved = save_draft(ctx)
    body = submit_command(ctx, saved).model_dump(mode="json")
    body[field] = "不应被接受"
    app = create_app(screening_service=ctx.service, session_service=ctx.sessions)
    app.dependency_overrides[get_actor] = lambda: ctx.actor
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/sessions/{ctx.sid}/evidence", json=body,
            headers={"Idempotency-Key": str(uuid4())},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INPUT_INVALID"
    assert ctx.sessions.restore(ctx.actor, ctx.sid).draft == saved
    assert ctx.queued == []
