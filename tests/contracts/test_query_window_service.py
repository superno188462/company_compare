"""WINDOW-TEST-1：QUERY-WINDOW-1.0，服务/HTTP/Schema及报告边界；仅合成依赖。"""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jsonschema import ValidationError

from backend.app import create_app
from backend.dependencies import get_actor
from company_screening.contracts.boundary import ActorContext, ProviderCategoryBatch, RetryQueryCommand
from company_screening.contracts.generated import Category, QueryDiagnostic
from company_screening.errors import ApplicationError
from company_screening.services import ScreeningService, SessionService
from test_query_operation import (
    STAMP, QueryFakeCompanyData, _batch, _confirm, _configure_all_empty, _provider_error, _record,
)
from test_submission_service import save_draft, submit_command


TOOLS = (
    "get_dishonest_info", "get_judgment_debtor_info", "get_high_consumption_restriction",
    "get_judicial_case", "get_judicial_documents", "get_court_notice",
)


class WindowData(QueryFakeCompanyData):
    def __init__(self):
        super().__init__()
        self.limits = []

    def fetch_category(self, subject, category, *, record_limit=200):
        self.limits.append((category, record_limit))
        return super().fetch_category(subject, category)


def window_batch(count=1, *, failure=False):
    records = [_record().model_copy(update={"record_id": f"CASE-{i}"}) for i in range(count)]
    coverage = [dict(tool_name=t, status="empty", accepted_count=0, total_count=0, has_more=False) for t in TOOLS]
    coverage[3] = dict(tool_name=TOOLS[3], status="partial", accepted_count=count, total_count=5564, has_more=True)
    detail = None
    if failure:
        coverage[0] = dict(tool_name=TOOLS[0], status="error", accepted_count=0, total_count=None, has_more=None)
        if count == 0:
            coverage[3] = dict(tool_name=TOOLS[3], status="empty", accepted_count=0, total_count=0, has_more=False)
        detail = QueryDiagnostic(
            diagnostic_id=uuid4(), tool_name=TOOLS[0], phase="request", reason_code="TOOL_ENTITLEMENT_REQUIRED",
            http_status=403, field=None, actual_count=None, limit_count=None,
        )
    return ProviderCategoryBatch(
        binding_credit_code="91310000MA1ABCDEF0", category=Category.judicial, queried_at=STAMP,
        scope_description="司法六项首批范围，未查全", records=records,
        completeness="partial", tool_coverage=coverage,
        error_code="UPSTREAM_AUTH" if failure else None, diagnostic=detail,
    )


def workspace(batch=None, basic_count=1):
    actor, sessions, queued = ActorContext(actor_id=uuid4()), SessionService(), []
    provider = WindowData()
    _configure_all_empty(provider)
    provider.responses[Category.basic] = _batch(Category.basic, records=[
        _record().model_copy(update={"record_id": f"REG-{i}"}) for i in range(basic_count)
    ])
    provider.responses[Category.judicial] = batch if batch is not None else window_batch()
    service = ScreeningService(session_service=sessions, company_data=provider, clock=lambda: STAMP, task_submitter=queued.append)
    sid, handle = _confirm(service, sessions, actor)
    queued.pop(0)()
    return SimpleNamespace(actor=actor, sessions=sessions, queued=queued, provider=provider,
                           service=service, sid=sid, handle=handle)


def result(ctx):
    return ctx.sessions.restore(ctx.actor, ctx.sid).payload


def retry(ctx, key=None):
    return ctx.service.retry_queries(ctx.actor, ctx.sid, RetryQueryCommand(
        expected_generation=1, categories=[Category.judicial],
    ), key or uuid4())


def test_partial_has_evidence_counts_coverage_and_valid_input_output(validators):
    """WINDOW-DATA/IF-01：真实接纳计数及覆盖进入模型，诊断不进入模型。"""
    ctx = workspace(window_batch(20, failure=True))
    payload = result(ctx).model_dump(mode="json")
    judicial = payload["api_status"]["categories"]["judicial"]
    assert judicial["status"] == "partial" and judicial["record_count"] == 20
    assert payload["api_status"]["tianyan_status"] == "partial"
    assert len(payload["evidence_list"]) == 21
    assert judicial["tool_coverage"][3]["total_count"] == 5564
    assert (Category.judicial, 120) in ctx.provider.limits
    validators[1].validate(payload)
    model_input = {"subject": payload["subject"], "evidence_list": payload["evidence_list"],
                   "api_status": {k: payload["api_status"][k] for k in ("tianyan_status", "planned_categories", "categories")}}
    validators[0].validate(model_input)
    assert "query_diagnostics" not in model_input["api_status"]
    assert payload["api_status"]["query_diagnostics"]["judicial"]["http_status"] == 403


def test_range_limit_without_failure_has_no_failure_diagnostic():
    """WINDOW-ERR-01：主动首批范围不是调用失败，不凭空生成权限诊断。"""
    ctx = workspace()
    payload = result(ctx)
    assert payload.api_status.categories.judicial.root.status == "partial"
    assert payload.api_status.categories.judicial.root.error_code is None
    assert "judicial" not in payload.api_status.query_diagnostics


def test_partial_zero_records_does_not_trigger_empty_snapshot():
    """WINDOW-IF-02：部分子项成功空、部分失败，不等于全部无记录。"""
    ctx = workspace(window_batch(0, failure=True), basic_count=0)
    payload = result(ctx)
    assert payload.api_status.tianyan_status.value == "partial"
    assert payload.api_status.categories.judicial.root.status == "partial"
    assert payload.api_status.snapshot_status.value == "not_checked"
    assert payload.api_status.llm_status.value == "skipped_no_evidence"


def test_remaining_capacity_is_passed_to_provider_and_other_evidence_retained():
    """WINDOW-IF-01：197条既有记录保留，只给司法3条预算。"""
    ctx = workspace(window_batch(3), basic_count=197)
    assert len(result(ctx).evidence_list) == 200
    assert (Category.judicial, 3) in ctx.provider.limits
    assert result(ctx).api_status.categories.basic.root.record_count == 197


def test_zero_capacity_does_not_query_or_discard_existing_records():
    """WINDOW-IF-01：无容量时不请求明细，不静默挤掉之前接纳内容。"""
    ctx = workspace(basic_count=200)
    assert Category.judicial not in ctx.provider.fetch_calls
    assert len(result(ctx).evidence_list) == 200
    assert result(ctx).api_status.categories.judicial.root.status == "error"
    assert result(ctx).api_status.query_diagnostics["judicial"].reason_code.value == "RECORD_LIMIT_EXCEEDED"


def test_partial_retry_is_idempotent_and_replaces_instead_of_appending():
    """WINDOW-IF-02：partial可重查同范围；同键只排一个任务，结果不重复追加。"""
    ctx = workspace(window_batch(2))
    before = result(ctx)
    ctx.provider.responses[Category.judicial] = window_batch(3)
    key = uuid4()
    first, second = retry(ctx, key), retry(ctx, key)
    assert first.operation_id == second.operation_id and len(ctx.queued) == 1
    ctx.queued.pop(0)()
    after = result(ctx)
    assert len(after.evidence_list) == 4
    assert after.api_status.categories.basic == before.api_status.categories.basic
    assert after.api_status.evidence_version == before.api_status.evidence_version + 1


def test_partial_retry_preserves_user_evidence_and_current_draft():
    """WINDOW-IF-02：重取窗口不能清除私人线索或正在编辑的下一条草稿。"""
    ctx = workspace()
    saved = save_draft(ctx)
    ctx.service.submit(ctx.actor, ctx.sid, submit_command(ctx, saved), uuid4())
    ctx.queued.pop(0)()
    newer = save_draft(ctx, content="新的未提交草稿")
    users = [x for x in result(ctx).evidence_list if x.root.source == "user_self"]
    retry(ctx)
    ctx.queued.pop(0)()
    state = ctx.sessions.restore(ctx.actor, ctx.sid)
    assert state.draft == newer
    assert [x for x in state.payload.evidence_list if x.root.source == "user_self"] == users


def test_total_retry_failure_keeps_previous_partial_records_and_old_time():
    """WINDOW-IF-02：新批次全部失败时不删除上一批可靠材料。"""
    ctx = workspace()
    old = result(ctx).evidence_list
    ctx.provider.responses[Category.judicial] = _provider_error("UPSTREAM_AUTH")
    retry(ctx)
    ctx.queued.pop(0)()
    assert result(ctx).evidence_list == old
    assert result(ctx).api_status.categories.judicial.root.status == "error"


def test_complete_recovery_removes_partial_diagnostic():
    """WINDOW-IF-02：恢复完整结果后清掉该类旧失败原因。"""
    ctx = workspace(window_batch(failure=True))
    ctx.provider.responses[Category.judicial] = _batch(Category.judicial, records=[_record()])
    retry(ctx)
    ctx.queued.pop(0)()
    assert result(ctx).api_status.categories.judicial.root.status == "ok"
    assert "judicial" not in result(ctx).api_status.query_diagnostics


@pytest.mark.parametrize("bad_kind", ["count", "duplicate_tool", "complete_with_partial", "non_judicial_partial"])
def test_invalid_batch_coverage_does_not_publish_misleading_scope(bad_kind):
    """WINDOW-DATA/RULE-01：覆盖与证据不一致不能发布为可靠窗口。"""
    batch = window_batch()
    if bad_kind == "count":
        batch.tool_coverage[3].accepted_count = 2
    elif bad_kind == "duplicate_tool":
        batch.tool_coverage[4] = batch.tool_coverage[3].model_copy()
    elif bad_kind == "complete_with_partial":
        batch.completeness = "complete"
    else:
        batch.category = Category.basic
    ctx = workspace(batch)
    assert result(ctx).api_status.categories.judicial.root.status == "error"
    assert all(x.root.category != "judicial" for x in result(ctx).evidence_list)


def test_partial_retry_rejects_other_owner_and_stale_generation():
    """WINDOW-IF-02：新增partial重试不削弱所有权与代次校验。"""
    ctx = workspace()
    for actor, generation in [(ActorContext(actor_id=uuid4()), 1), (ctx.actor, 2)]:
        with pytest.raises(ApplicationError):
            ctx.service.retry_queries(actor, ctx.sid, RetryQueryCommand(
                expected_generation=generation, categories=[Category.judicial],
            ), uuid4())
    assert ctx.queued == []


def test_partial_retry_http_uses_existing_endpoint_and_returns_full_payload(validators):
    """WINDOW-IF-02：沿用现有202/轮询端点，不另建自由查询接口。"""
    ctx = workspace()
    app = create_app(screening_service=ctx.service, session_service=ctx.sessions)
    app.dependency_overrides[get_actor] = lambda: ctx.actor
    with TestClient(app) as client:
        response = client.post(f"/api/v1/sessions/{ctx.sid}/queries/retry", json={
            "expected_generation": 1, "categories": ["judicial"],
        }, headers={"Idempotency-Key": str(uuid4())})
        assert response.status_code == 202
        ctx.queued.pop(0)()
        terminal = client.get(f"/api/v1/sessions/{ctx.sid}/operations/{response.json()['operation_id']}")
        assert terminal.status_code == 200 and terminal.json()["state"] == "succeeded"
        validators[1].validate(terminal.json()["result"])
        assert terminal.json()["result"]["api_status"]["categories"]["judicial"]["status"] == "partial"


@pytest.mark.parametrize("field,value", [
    ("tool_name", "untrusted_tool"), ("status", "safe"), ("accepted_count", -1),
    ("total_count", -1), ("has_more", "unknown"), ("raw_response", "private"),
])
def test_tool_coverage_schema_rejects_uncontrolled_values(validators, payload, field, value):
    """WINDOW-DATA/NFR-01：五个固定字段，不收上游原文、任意工具或伪布尔值。"""
    body = deepcopy(payload)
    item = window_batch().model_dump(mode="json")["tool_coverage"][3]
    item[field] = value
    body["api_status"]["categories"]["judicial"]["tool_coverage"] = [item]
    with pytest.raises(ValidationError):
        validators[1].validate(body)
