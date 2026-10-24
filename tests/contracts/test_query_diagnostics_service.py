"""DIAG-TEST-1：诊断SDD v1.0，DIAG-DATA/IF/NFR/AC；固定外部替身。"""

from copy import deepcopy
from uuid import uuid4

import pytest
from jsonschema import ValidationError

from company_screening.contracts.boundary import ActorContext
from company_screening.contracts.generated import Category, QueryDiagnostic, WorkflowPayload
from company_screening.errors import ApplicationError
from company_screening.services import ScreeningService, SessionService
from test_query_operation import (
    STAMP, QueryFakeCompanyData, _batch, _confirm, _configure_all_empty, _provider_error, _record,
)
from test_query_retry import retry_command, retry_workspace
from test_submission_service import save_draft


def detail_model(reason="TOOL_ENTITLEMENT_REQUIRED"):
    return QueryDiagnostic(
        diagnostic_id=uuid4(), tool_name="get_administrative_penalty", phase="request",
        reason_code=reason, http_status=403, field=None, actual_count=None, limit_count=None,
    )


def diag_error(detail=None):
    error = _provider_error("UPSTREAM_AUTH")
    error.diagnostic = detail or detail_model()
    return error


def diagnostics(payload):
    return payload.model_dump(mode="json")["api_status"]["query_diagnostics"]


def test_old_payload_omits_diagnostics_and_round_trips_as_empty_mapping(validators, payload):
    """DIAG-DATA-01：原机器契约样例仍可读，省略新字段不变成含null的类别表。"""
    assert "query_diagnostics" not in payload["api_status"]
    validators[1].validate(payload)
    restored = WorkflowPayload.model_validate(payload).model_dump(mode="json")
    assert restored["api_status"]["query_diagnostics"] == {}
    validators[1].validate(restored)


@pytest.mark.parametrize("field,value", [
    ("tool_name", "untrusted_tool"), ("phase", "SECRET"), ("reason_code", "raw message"),
    ("http_status", 999), ("field", "Authorization"), ("actual_count", -1),
    ("limit_count", 0), ("diagnostic_id", "not-uuid"), ("raw_message", "SECRET"),
])
def test_diagnostic_schema_rejects_uncontrolled_fields_and_values(validators, payload, field, value):
    """DIAG-DATA/NFR-01：白名单、数值及额外字段约束不能被任意错误原文绕过。"""
    detail = detail_model().model_dump(mode="json")
    detail[field] = value
    payload["api_status"]["query_diagnostics"] = {"penalty": detail}
    with pytest.raises(ValidationError):
        validators[1].validate(payload)


def test_diagnostic_mapping_rejects_unknown_categories(validators, payload):
    """DIAG-DATA-01：诊断仅能绑定固定五类，不能建立任意私有数据键。"""
    payload["api_status"]["query_diagnostics"] = {"unknown_company": detail_model().model_dump(mode="json")}
    with pytest.raises(ValidationError):
        validators[1].validate(payload)


def test_legacy_provider_failure_has_unknown_diagnostic_without_guessed_tool(validators):
    """DIAG-DATA/IF-01：旧ProviderError缺失细节时不能从UPSTREAM_AUTH猜具体子接口。"""
    ctx = retry_workspace()
    payload = ctx.sessions.restore(ctx.actor, ctx.sid).payload
    details = diagnostics(payload)
    assert set(details) == {"abnormal", "penalty"}
    assert all(item["reason_code"] == "UNCLASSIFIED_FAILURE" for item in details.values())
    assert all(item["tool_name"] is None and item["http_status"] is None for item in details.values())
    validators[1].validate(payload.model_dump(mode="json"))


def test_config_missing_has_explicit_diagnostic_and_no_invented_http():
    """DIAG-ERR-01：没有配置不冒充天眼查返回403。"""
    ctx = retry_workspace()
    service = ScreeningService(session_service=ctx.sessions, task_submitter=ctx.queued.append)
    handle = service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx), uuid4())
    ctx.queued.pop(0)()
    result = service.operation(ctx.actor, ctx.sid, handle.operation_id).result
    detail = diagnostics(result)["penalty"]
    assert detail["reason_code"] == "PROVIDER_NOT_CONFIGURED" and detail["phase"] == "configuration"
    assert detail["tool_name"] is None and detail["http_status"] is None


def test_failed_retry_replaces_only_its_diagnostic_and_keeps_private_state(validators):
    """DIAG-IF-01：再次失败更新本类原因，其余诊断、证据、草稿和报告保留。"""
    ctx = retry_workspace()
    saved = save_draft(ctx, content="需要保留的合成草稿")
    before = ctx.sessions.restore(ctx.actor, ctx.sid).payload
    new_detail = detail_model()
    ctx.provider.responses[Category.penalty] = diag_error(new_detail)
    handle = ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx), uuid4())
    ctx.queued.pop(0)()
    state = ctx.sessions.restore(ctx.actor, ctx.sid)
    result = ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id).result
    details = diagnostics(result)
    assert details["penalty"] == new_detail.model_dump(mode="json")
    assert details["penalty"]["diagnostic_id"] != diagnostics(before)["penalty"]["diagnostic_id"]
    assert details["abnormal"] == diagnostics(before)["abnormal"]
    assert state.draft == saved and result.evidence_list == before.evidence_list
    assert result.summary_text == before.summary_text
    validators[1].validate(result.model_dump(mode="json"))


def test_recovered_retry_removes_its_old_diagnostic_and_preserves_other_category():
    """DIAG-IF-01：成功无记录也清除该类别旧失败详情，不清除其他失败。"""
    ctx = retry_workspace()
    before = diagnostics(ctx.sessions.restore(ctx.actor, ctx.sid).payload)
    ctx.provider.responses[Category.penalty] = _batch(Category.penalty)
    handle = ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx), uuid4())
    ctx.queued.pop(0)()
    result = ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id).result
    assert "penalty" not in diagnostics(result)
    assert diagnostics(result)["abnormal"] == before["abnormal"]
    assert result.api_status.categories.penalty.root.status == "empty"


def test_idempotent_replay_keeps_diagnostic_id_without_new_provider_call():
    """DIAG-IF-01：同键回放保留同一个诊断编号，不重查、不生成新原因。"""
    ctx = retry_workspace()
    command, key = retry_command(ctx), uuid4()
    handle = ctx.service.retry_queries(ctx.actor, ctx.sid, command, key)
    ctx.queued.pop(0)()
    before = ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id).result
    assert diagnostics(before).get("penalty") is not None
    call_count = len(ctx.provider.fetch_calls)
    assert ctx.service.retry_queries(ctx.actor, ctx.sid, command, key) == handle
    after = ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id).result
    assert diagnostics(after) == diagnostics(before) and len(ctx.provider.fetch_calls) == call_count


def test_only_diagnostic_changes_do_not_increment_analysis_input_version():
    """DIAG-IF-01：相同证据和覆盖下，仅更换诊断编号不触发新的分析输入版本。"""
    actor, sessions, queued = ActorContext(actor_id=uuid4()), SessionService(), []
    provider = QueryFakeCompanyData()
    _configure_all_empty(provider)
    provider.responses[Category.penalty] = diag_error()
    service = ScreeningService(
        session_service=sessions, company_data=provider, clock=lambda: STAMP, task_submitter=queued.append,
    )
    sid, first = _confirm(service, sessions, actor)
    queued.pop(0)()
    before = service.operation(actor, sid, first.operation_id).result
    from company_screening.contracts.boundary import RetryQueryCommand
    provider.responses[Category.penalty] = diag_error()
    handle = service.retry_queries(actor, sid, RetryQueryCommand(
        expected_generation=1, categories=[Category.penalty],
    ), uuid4())
    queued.pop(0)()
    after = service.operation(actor, sid, handle.operation_id).result
    assert diagnostics(before)["penalty"]["diagnostic_id"] != diagnostics(after)["penalty"]["diagnostic_id"]
    assert after.api_status.categories == before.api_status.categories
    assert after.api_status.evidence_version == before.api_status.evidence_version
    assert after.api_status.result_revision > before.api_status.result_revision


def test_diagnostics_survive_restore_but_are_not_llm_evidence(validators):
    """DIAG-DATA/NFR-01：会话保留诊断，LLM仍只接收原QueryCoverage字段。"""
    ctx = retry_workspace()
    first = ctx.sessions.restore(ctx.actor, ctx.sid).payload
    again = ctx.sessions.restore(ctx.actor, ctx.sid).payload
    assert diagnostics(first) and diagnostics(again) == diagnostics(first)
    data = again.model_dump(mode="json")
    model_input = {
        "subject": data["subject"], "evidence_list": data["evidence_list"],
        "api_status": {key: data["api_status"][key] for key in ("tianyan_status", "planned_categories", "categories")},
    }
    validators[0].validate(model_input)
    bad_input = deepcopy(model_input)
    bad_input["api_status"]["query_diagnostics"] = diagnostics(first)
    with pytest.raises(ValidationError):
        validators[0].validate(bad_input)


def test_another_owner_cannot_restore_diagnostic_payload():
    """DIAG-IF/NFR-01：诊断随会话隔离，编号不能越权读取。"""
    ctx = retry_workspace()
    assert diagnostics(ctx.sessions.restore(ctx.actor, ctx.sid).payload)
    with pytest.raises(ApplicationError) as caught:
        ctx.sessions.restore(ActorContext(actor_id=uuid4()), ctx.sid)
    assert caught.value.info.code == "RESOURCE_NOT_FOUND"


def test_total_evidence_limit_has_application_diagnostic_without_guessed_subtool():
    """DIAG-ERR-01：总证据限制在应用层触发，不能伪造提供方工具或HTTP状态。"""
    ctx = retry_workspace(record_count=200)
    ctx.provider.responses[Category.penalty] = _batch(Category.penalty, records=[_record()])
    handle = ctx.service.retry_queries(ctx.actor, ctx.sid, retry_command(ctx), uuid4())
    ctx.queued.pop(0)()
    result = ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id).result
    detail = diagnostics(result)["penalty"]
    assert detail["reason_code"] == "RECORD_LIMIT_EXCEEDED" and detail["phase"] == "aggregate"
    assert detail["actual_count"] == 201 and detail["limit_count"] == 200
    assert detail["tool_name"] is None and detail["http_status"] is None
    assert len(result.evidence_list) == 200
