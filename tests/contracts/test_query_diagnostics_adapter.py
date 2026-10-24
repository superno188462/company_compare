"""DIAG-TEST-1：诊断SDD v1.0，DIAG-ERR-01/NFR-01；假HTTP，不调用真实API。"""

import json

import httpx
import pytest

from company_screening.adapters.tianyan_mcp import TianyanMcpAdapter
from company_screening.contracts.generated import Category
from company_screening.errors import ProviderError
from test_tianyan_mcp_adapter import _subject, _tool_response


SECRET = "FAKE-SECRET-DIAG-ONLY"
PRIVATE = "合成私有正文不应进入诊断<script>alert('test')</script>"
PENALTY_TOOL = "get_administrative_penalty"


def adapter_for(handler, *, page_size=100):
    return TianyanMcpAdapter(
        SECRET, client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None, detail_page_size=page_size,
    )


def diagnostic_from(adapter, category=Category.penalty):
    with pytest.raises(ProviderError) as caught:
        adapter.fetch_category(_subject(), category)
    detail = caught.value.diagnostic
    assert detail is not None, "分类失败必须保留脱敏诊断"
    serialized = detail.model_dump_json()
    assert SECRET not in serialized and PRIVATE not in serialized
    assert SECRET not in str(caught.value) and PRIVATE not in str(caught.value)
    return caught.value, detail.model_dump(mode="json")


@pytest.mark.parametrize("status,body,reason,code", [
    (401, {"message": SECRET + PRIVATE}, "AUTH_REQUIRED", "UPSTREAM_AUTH"),
    (403, {"error": "forbidden", "message": SECRET + PRIVATE}, "AUTH_REQUIRED", "UPSTREAM_AUTH"),
    (403, {"error": "insufficient_entitlement", "message": SECRET + PRIVATE}, "TOOL_ENTITLEMENT_REQUIRED", "UPSTREAM_AUTH"),
    (429, {"message": SECRET + PRIVATE}, "RATE_OR_QUOTA_LIMIT", "UPSTREAM_LIMIT"),
    (400, {"message": SECRET + PRIVATE}, "REQUEST_REJECTED", "UPSTREAM_INVALID"),
    (503, {"message": SECRET + PRIVATE}, "SERVICE_UNAVAILABLE", "UPSTREAM_ERROR"),
    (302, {"message": SECRET + PRIVATE}, "REQUEST_REJECTED", "UPSTREAM_ERROR"),
])
def test_http_failure_keeps_actual_status_tool_and_controlled_reason(status, body, reason, code, caplog):
    """DIAG-ERR-01/NFR-01：已知HTTP状态和工具保留，原始message不暴露。"""
    error, detail = diagnostic_from(adapter_for(lambda _: httpx.Response(status, json=body)))
    assert error.code == code
    assert detail["reason_code"] == reason
    assert detail["http_status"] == status and detail["tool_name"] == PENALTY_TOOL
    assert detail["phase"] == "request"
    assert SECRET not in caplog.text and PRIVATE not in caplog.text


@pytest.mark.parametrize("exception,reason,code", [
    (httpx.ReadTimeout, "REQUEST_TIMEOUT", "UPSTREAM_TIMEOUT"),
    (httpx.ConnectError, "NETWORK_ERROR", "UPSTREAM_ERROR"),
])
def test_transport_failure_does_not_invent_http_status(exception, reason, code):
    """DIAG-ERR-01：没有响应时HTTP状态为null，不伪造200或鉴权错误。"""
    def handler(request):
        raise exception(SECRET + PRIVATE, request=request)
    error, detail = diagnostic_from(adapter_for(handler))
    assert error.code == code and detail["reason_code"] == reason
    assert detail["http_status"] is None and detail["tool_name"] == PENALTY_TOOL


@pytest.mark.parametrize("body,reason,phase,field", [
    ({"items": "bad", "total": 0}, "PAGINATION_INVALID", "pagination", "items"),
    ({"items": [], "total": True}, "PAGINATION_INVALID", "pagination", "total"),
    ({"items": [], "total": 0, "pageNum": 2}, "PAGINATION_INVALID", "pagination", "pageNum"),
    ({"items": [], "total": 0, "_warnings": [SECRET + PRIVATE]}, "UPSTREAM_WARNING", "response", None),
    ({"items": [{"id": "r1", "creditCode": "INVALID"}], "total": 1}, "RECORD_INVALID", "record", "record_credit_code"),
    ({"items": [{"id": "r1", "creditCode": "91310000MA1ABCDEFX"}], "total": 1}, "SUBJECT_MISMATCH", "record", "record_credit_code"),
    ({"items": [{"id": "r1", "sourceUrl": "javascript:alert(1)"}], "total": 1}, "RECORD_INVALID", "record", "source_url"),
    ({"items": [{"id": "r1", "decisionDate": "字" * 257}], "total": 1}, "RECORD_INVALID", "record", "event_time"),
    ({"items": [{"id": "r1", "detail": "字" * 5000}], "total": 1}, "CONTENT_LIMIT_EXCEEDED", "record", "content"),
    ({"items": [], "total": 201}, "RECORD_LIMIT_EXCEEDED", "pagination", "total"),
    ({"items": [{"id": "same"}, {"id": "same"}], "total": 2}, "DUPLICATE_RECORDS", "aggregate", "record_id"),
])
def test_parsing_and_limits_identify_known_stage_and_field(body, reason, phase, field):
    """DIAG-ERR-01：解析、完整性和应用上限各有确定原因，不改变原失败语义。"""
    _, detail = diagnostic_from(adapter_for(lambda _: httpx.Response(
        200, json=_tool_response(PENALTY_TOOL, body),
    )))
    assert detail["reason_code"] == reason
    assert detail["phase"] == phase and detail["field"] == field
    assert detail["tool_name"] == PENALTY_TOOL and detail["http_status"] == 200
    if reason == "CONTENT_LIMIT_EXCEEDED":
        assert detail["actual_count"] > 4000 and detail["limit_count"] == 4000
    if reason == "RECORD_LIMIT_EXCEEDED":
        assert detail["actual_count"] == 201 and detail["limit_count"] == 200


@pytest.mark.parametrize("body", [None, {"tool_name": "unexpected", "content": {}},
                                       {"tool_name": PENALTY_TOOL, "content": "not-json"}])
def test_invalid_response_envelope_still_preserves_tool_and_http(body):
    """DIAG-ERR-01：格式解析出错时也保留实际响应状态，不宣称上游一定有错。"""
    _, detail = diagnostic_from(adapter_for(lambda _: httpx.Response(200, json=body)))
    assert detail["reason_code"] == "RESPONSE_INVALID" and detail["phase"] == "response"
    assert detail["tool_name"] == PENALTY_TOOL and detail["http_status"] == 200


@pytest.mark.parametrize("scenario,reason", [
    ("changed", "PAGINATION_CHANGED"), ("count_mismatch", "PAGINATION_INCOMPLETE"),
    ("empty_next_page", "PAGINATION_INCOMPLETE"),
])
def test_incomplete_pagination_records_specific_reason(scenario, reason):
    """DIAG-ERR-01：变动总数、数量不符和空下一页不能仅留下宽泛错误码。"""
    def handler(request):
        page = json.loads(request.read())["arguments"]["pageNum"]
        items = [{"id": f"r{page}"}]
        total, page_size = 2, 1
        if scenario == "changed" and page == 2:
            total = 3
        if scenario == "count_mismatch":
            page_size = 100
        if scenario == "empty_next_page":
            items = []
        return httpx.Response(200, json=_tool_response(PENALTY_TOOL, {
            "items": items, "total": total, "pageNum": page, "pageSize": page_size,
        }))
    _, detail = diagnostic_from(adapter_for(handler, page_size=1))
    assert detail["reason_code"] == reason and detail["phase"] == "pagination"
    assert detail["tool_name"] == PENALTY_TOOL and detail["http_status"] == 200


def test_basic_failure_points_to_shareholders_after_successful_registration():
    """DIAG-IF-01：整类失败精确定位首个失败子工具，不把工商登记成功抹成权限失败。"""
    def handler(request):
        tool = json.loads(request.read())["tool_name"]
        if tool == "get_company_registration_info":
            return httpx.Response(200, json=_tool_response(tool, {"sources": {"base": {"id": "r1"}}}))
        return httpx.Response(403, json={"error": "insufficient_entitlement", "message": SECRET + PRIVATE})
    error, detail = diagnostic_from(adapter_for(handler), Category.basic)
    assert error.code == "UPSTREAM_AUTH"
    assert detail["tool_name"] == "get_shareholder_info"
    assert detail["reason_code"] == "TOOL_ENTITLEMENT_REQUIRED" and detail["http_status"] == 403


def test_registration_invalid_sources_is_located_without_raw_payload():
    """DIAG-ERR-01：工商对象解析不兼容时定位sources，不把原始正文保存作诊断。"""
    _, detail = diagnostic_from(adapter_for(lambda _: httpx.Response(
        200, json=_tool_response("get_company_registration_info", {"sources": SECRET + PRIVATE}),
    )), Category.basic)
    assert detail["reason_code"] == "RESPONSE_INVALID" and detail["field"] == "sources"
    assert detail["tool_name"] == "get_company_registration_info" and detail["http_status"] == 200


def test_combined_category_limit_distinguishes_application_limit_from_entitlement():
    """DIAG-ERR-01：登记1条加股东200条超过类别上限；不是权限/额度不足。"""
    def handler(request):
        body = json.loads(request.read())
        tool = body["tool_name"]
        if tool == "get_company_registration_info":
            return httpx.Response(200, json=_tool_response(tool, {"sources": {"base": {"id": "reg"}}}))
        page = body["arguments"]["pageNum"]
        return httpx.Response(200, json=_tool_response(tool, {
            "items": [{"id": f"r{page}-{i}"} for i in range(100)],
            "total": 200, "pageNum": page, "pageSize": 100,
        }))
    error, detail = diagnostic_from(adapter_for(handler), Category.basic)
    assert error.code == "UPSTREAM_INCOMPLETE"
    assert detail["reason_code"] == "RECORD_LIMIT_EXCEEDED" and detail["phase"] == "aggregate"
    assert detail["actual_count"] == 201 and detail["limit_count"] == 200


def test_success_http_status_is_not_hardcoded_during_later_parsing_failure():
    """DIAG-DATA-01：已收到201但分页非法，诊断应保留201而非机械补为200。"""
    _, detail = diagnostic_from(adapter_for(lambda _: httpx.Response(
        201, json=_tool_response(PENALTY_TOOL, {"items": "bad", "total": 0}),
    )))
    assert detail["reason_code"] == "PAGINATION_INVALID" and detail["http_status"] == 201
