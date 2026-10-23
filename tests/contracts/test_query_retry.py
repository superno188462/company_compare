"""QUERY-RETRY-TEST-1：CONTRACT-1.0，BE-IF-03/05/06、DATA-02/05。

固定范围内的失败类别重试；合成提供方与可控队列，不访问收费接口。
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.dependencies import get_actor
from company_screening.contracts.boundary import ActorContext, RetryQueryCommand
from company_screening.contracts.generated import Category
from company_screening.errors import ApplicationError
from company_screening.services import ScreeningService, SessionService
from test_query_operation import (
    QueryFakeCompanyData, _batch, _confirm, _configure_all_empty, _provider_error, _record,
)
from test_submission_service import save_draft, submit_command


def retry_workspace(record_count=1):
    actor = ActorContext(actor_id=uuid4())
    sessions = SessionService()
    queued = []
    provider = QueryFakeCompanyData()
    _configure_all_empty(provider)
    provider.responses[Category.basic] = _batch(Category.basic, records=[
        _record().model_copy(update={"record_id": f"REG-{index}"}) for index in range(record_count)
    ])
    provider.responses[Category.penalty] = _provider_error("UPSTREAM_AUTH")
    provider.responses[Category.abnormal] = _provider_error("UPSTREAM_TIMEOUT", retryable=True)
    service = ScreeningService(
        session_service=sessions, company_data=provider, task_submitter=queued.append,
    )
    sid, initial = _confirm(service, sessions, actor)
    queued.pop(0)()
    assert service.operation(actor, sid, initial.operation_id).state == "succeeded"
    return SimpleNamespace(actor=actor, sessions=sessions, queued=queued, provider=provider,
                           service=service, sid=sid)


def retry_command(ctx, categories=None, generation=None):
    state = ctx.sessions.restore(ctx.actor, ctx.sid)
    return RetryQueryCommand(
        expected_generation=generation or state.session_generation,
        categories=categories or [Category.penalty],
    )


def test_retry_queries_only_selected_error_category_and_returns_complete_payload(validators):
    """BE-IF-03/06：只查询所选失败类别，终态保留未重试类别并通过Schema。"""
    ctx = retry_workspace()
    before = ctx.sessions.restore(ctx.actor, ctx.sid).payload
    ctx.provider.responses[Category.penalty] = _batch(Category.penalty, records=[_record()])
    call_count = len(ctx.provider.fetch_calls)
    handle = ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx), uuid4())
    pending = ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id)
    assert pending.state in ("queued", "running")
    assert pending.result is None and pending.error is None
    assert len(ctx.queued) == 1
    ctx.queued.pop(0)()
    view = ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id)
    assert view.state == "succeeded" and view.error is None
    result = view.result
    assert result is not None
    validators[1].validate(result.model_dump(mode="json"))
    assert ctx.provider.fetch_calls[call_count:] == [Category.penalty]
    assert result.api_status.categories.penalty.root.status == "ok"
    assert result.api_status.categories.basic == before.api_status.categories.basic
    assert result.api_status.categories.abnormal == before.api_status.categories.abnormal
    assert result.api_status.planned_categories == before.api_status.planned_categories
    assert result.api_status.tianyan_status == "partial"
    assert result.api_status.evidence_version == before.api_status.evidence_version + 1
    assert result.api_status.result_revision > before.api_status.result_revision
    assert len(result.evidence_list) == 2
    assert result.evidence_list[0] == before.evidence_list[0]
    assert result.api_status.operation_id == handle.operation_id
    assert ctx.sessions.restore(ctx.actor, ctx.sid).active_operation is None


def test_explicit_retry_is_allowed_after_user_changes_upstream_entitlement():
    """BE-IF-03：用户显式重试原鉴权失败类别；不因旧错误不可自动重试而永久禁用。"""
    ctx = retry_workspace()
    ctx.provider.responses[Category.penalty] = _batch(Category.penalty)
    handle = ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx), uuid4())
    ctx.queued.pop(0)()
    result = ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id).result
    assert result.api_status.categories.penalty.root.status == "empty"
    assert result.api_status.categories.penalty.root.error_code is None
    assert len(result.evidence_list) == 1
    assert result.api_status.tianyan_status == "partial"


def test_retry_keeps_private_evidence_draft_and_submission_receipt_on_upstream_failure():
    """DATA-02/03：重试仍失败时已有成功类别、用户证据、草稿与提交回执不丢失。"""
    ctx = retry_workspace()
    draft = save_draft(ctx)
    ctx.service.submit(ctx.actor, ctx.sid, submit_command(ctx, draft), uuid4())
    ctx.queued.pop(0)()
    next_draft = save_draft(ctx, content="重试期间仍需保留的草稿")
    before = ctx.sessions.restore(ctx.actor, ctx.sid).payload
    handle = ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx), uuid4())
    ctx.queued.pop(0)()
    after = ctx.sessions.restore(ctx.actor, ctx.sid)
    assert after.draft == next_draft
    assert after.payload.evidence_list == before.evidence_list
    assert after.payload.api_status.last_submission == before.api_status.last_submission
    assert after.payload.summary_text == before.summary_text
    assert after.payload.api_status.categories.penalty.root.status == "error"
    assert after.payload.api_status.categories.penalty.root.error_code == "UPSTREAM_AUTH"
    assert after.payload.api_status.tianyan_status == "partial"
    assert ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id).state == "succeeded"


@pytest.mark.parametrize("categories", [[Category.basic], [Category.judicial],
                                         [Category.penalty, Category.penalty]])
def test_retry_rejects_successful_empty_or_duplicate_categories(categories):
    """BE-IF-03/ERR-01：成功、成功无记录和重复类别不能冒充失败类别重试。"""
    ctx = retry_workspace()
    before = ctx.sessions.restore(ctx.actor, ctx.sid)
    call_count = len(ctx.provider.fetch_calls)
    with pytest.raises(ApplicationError) as caught:
        ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx, categories), uuid4())
    assert caught.value.info.code == "INPUT_INVALID"
    after = ctx.sessions.restore(ctx.actor, ctx.sid)
    assert after.payload == before.payload and after.active_operation is None
    assert len(ctx.provider.fetch_calls) == call_count and ctx.queued == []


def test_retry_multiple_failed_categories_uses_fixed_serial_category_order():
    """BE-IF-03：多类别仍按既有类别顺序串行，只触达请求的失败范围。"""
    ctx = retry_workspace()
    call_count = len(ctx.provider.fetch_calls)
    handle = ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(
        ctx, [Category.penalty, Category.abnormal],
    ), uuid4())
    ctx.queued.pop(0)()
    assert ctx.provider.fetch_calls[call_count:] == [Category.abnormal, Category.penalty]
    assert ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id).state == "succeeded"


def test_retry_same_key_replays_original_handle_without_requery():
    """DATA-05：运行中与终态同键同请求回放，不重复启动外部查询。"""
    ctx = retry_workspace()
    command, key = retry_command(ctx), uuid4()
    handle = ctx.service.retry_queries(ctx.actor, ctx.sid, command, key)
    assert ctx.service.retry_queries(ctx.actor, ctx.sid, command, key) == handle
    assert len(ctx.queued) == 1
    ctx.queued.pop(0)()
    call_count = len(ctx.provider.fetch_calls)
    assert ctx.service.retry_queries(ctx.actor, ctx.sid, command, key) == handle
    assert len(ctx.provider.fetch_calls) == call_count and ctx.queued == []


def test_retry_same_key_changed_categories_is_conflict():
    """DATA-05：同一幂等键不能改成另一个查询范围。"""
    ctx = retry_workspace()
    key = uuid4()
    ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx), key)
    with pytest.raises(ApplicationError) as caught:
        ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx, [Category.abnormal]), key)
    assert caught.value.info.code == "IDEMPOTENCY_CONFLICT"
    assert len(ctx.queued) == 1


def test_retry_different_operation_cannot_overlap():
    """DATA-05：同代次已有任务时拒绝另一个重试，不创建第二个活动任务。"""
    ctx = retry_workspace()
    first = ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx), uuid4())
    with pytest.raises(ApplicationError) as caught:
        ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx, [Category.abnormal]), uuid4())
    assert caught.value.info.code == "OPERATION_CONFLICT"
    assert ctx.sessions.restore(ctx.actor, ctx.sid).active_operation == first
    assert len(ctx.queued) == 1


def test_retry_stale_generation_does_not_change_workspace():
    """DATA-05：旧代次请求不能查询或覆盖新主体。"""
    ctx = retry_workspace()
    before = ctx.sessions.restore(ctx.actor, ctx.sid)
    with pytest.raises(ApplicationError) as caught:
        ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx, generation=2), uuid4())
    assert caught.value.info.code == "OPERATION_CONFLICT"
    assert ctx.sessions.restore(ctx.actor, ctx.sid).payload == before.payload
    assert ctx.queued == []


def test_retry_wrong_owner_cannot_query_known_session():
    """DATA-05：任务入口也校验会话所有权。"""
    ctx = retry_workspace()
    with pytest.raises(ApplicationError) as caught:
        ctx.service.retry_queries(ActorContext(actor_id=uuid4()), ctx.sid, retry_command(ctx), uuid4())
    assert caught.value.info.code == "RESOURCE_NOT_FOUND"
    assert ctx.queued == []


def test_retry_subject_mismatch_marks_category_error_and_keeps_existing_evidence():
    """BE-IF-03：新响应主体错配仍是类别失败，不污染原证据集合。"""
    ctx = retry_workspace()
    before = ctx.sessions.restore(ctx.actor, ctx.sid).payload
    ctx.provider.responses[Category.penalty] = _batch(
        Category.penalty, records=[_record()], binding_credit_code="91310000MA1ABCDEFX",
    )
    handle = ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx), uuid4())
    ctx.queued.pop(0)()
    result = ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id).result
    assert result.evidence_list == before.evidence_list
    assert result.api_status.categories.penalty.root.error_code == "SUBJECT_RESPONSE_MISMATCH"


def test_retry_exceeding_total_limit_does_not_truncate_or_remove_existing_evidence():
    """BE-IF-03 / DATA-03：总数超过200时新类别报错，旧成功集合保留。"""
    ctx = retry_workspace(record_count=200)
    before = ctx.sessions.restore(ctx.actor, ctx.sid).payload
    ctx.provider.responses[Category.penalty] = _batch(Category.penalty, records=[_record()])
    handle = ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx), uuid4())
    ctx.queued.pop(0)()
    result = ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id).result
    assert result.evidence_list == before.evidence_list
    assert result.api_status.categories.penalty.root.status == "error"
    assert result.api_status.categories.penalty.root.error_code == "UPSTREAM_INCOMPLETE"


def test_late_retry_after_reset_cannot_restore_private_state():
    """BE-IF-06：会话结束后迟到重试任务不能恢复私人结果。"""
    ctx = retry_workspace()
    ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx), uuid4())
    ctx.sessions.reset(ctx.actor, ctx.sid, uuid4())
    ctx.queued.pop(0)()
    with pytest.raises(ApplicationError) as caught:
        ctx.sessions.restore(ctx.actor, ctx.sid)
    assert caught.value.info.code == "SESSION_EXPIRED"


def test_retry_http_returns_202_then_complete_payload(validators):
    """BE-IF-03/06：HTTP端点接通服务，使用既有操作查询返回完整终态。"""
    ctx = retry_workspace()
    app = create_app(screening_service=ctx.service, session_service=ctx.sessions)
    app.dependency_overrides[get_actor] = lambda: ctx.actor
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/sessions/{ctx.sid}/queries/retry",
            json=retry_command(ctx).model_dump(mode="json"),
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 202
        handle = response.json()
        ctx.queued.pop(0)()
        terminal = client.get(f"/api/v1/sessions/{ctx.sid}/operations/{handle['operation_id']}")
        assert terminal.status_code == 200
        assert terminal.json()["state"] == "succeeded"
        validators[1].validate(terminal.json()["result"])


def test_retry_http_rejects_non_failed_category_with_422():
    """BE-ERR-01：成功类别不能绕过页面按钮约束发起重试。"""
    ctx = retry_workspace()
    app = create_app(screening_service=ctx.service, session_service=ctx.sessions)
    app.dependency_overrides[get_actor] = lambda: ctx.actor
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/sessions/{ctx.sid}/queries/retry",
            json=retry_command(ctx, [Category.basic]).model_dump(mode="json"),
            headers={"Idempotency-Key": str(uuid4())},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INPUT_INVALID"
    assert ctx.queued == []
