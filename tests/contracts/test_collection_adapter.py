"""COLLECTION-TEST-1，COLLECTION-1.0：COL-DATA-02、IF-02/04、DEP-01、ERR-01。"""

import json

import httpx
import pytest

from company_screening.adapters.tianyan_mcp import TianyanMcpAdapter
from company_screening.contracts.generated import JudicialToolName, SnapshotToolName
from company_screening.errors import ProviderError
from collection_support import CASE, CODE, OTHER_CODE, dump
from test_tianyan_mcp_adapter import _subject as _legacy_subject

SECRET = "FAKE-COLLECTION-KEY"


def _subject():
    """COLLECTION-TEST-FIX-1已确认：只统一合成主体夹具，断言不变。"""
    value = _legacy_subject().model_dump(mode="json")
    value["credit_code"] = CODE
    return type(_legacy_subject()).model_validate(value)


def adapter_for(body, *, status=200):
    calls = []

    def handler(request):
        value = json.loads(request.read())
        calls.append(value)
        content = body(value) if callable(body) else body
        payload = dict(tool_name=value["tool_name"], content=content) if status == 200 else content
        return httpx.Response(status, json=payload)

    return TianyanMcpAdapter(SECRET, client=httpx.Client(transport=httpx.MockTransport(handler)),
                             sleep=lambda _: None), calls


@pytest.mark.parametrize("tool", list(JudicialToolName))
def test_second_page_requests_only_the_selected_tool(tool):
    """COL-IF-02/04：不是重新查六工具，第二页不被写成第一页。"""
    adapter, calls = adapter_for(dict(items=[{"uuid": f"page-two-{i}"} for i in range(20)],
                                    total=5564, pageNum=2, pageSize=20))
    value = dump(adapter.fetch_judicial_page(_subject(), tool, page_number=2))
    assert len(calls) == 1
    assert calls[0]["tool_name"] == tool.value
    assert calls[0]["arguments"] == dict(searchKey=CODE, pageNum=2, pageSize=20)
    assert value["page_number"] == 2 and value["page_size"] == 20
    assert len(value["records"]) == 20 and value["total_count"] == 5564 and value["has_more"] is True
    assert value["binding_credit_code"] == CODE and value["tool_name"] == tool.value


@pytest.mark.parametrize("count,total,more", [(0,0,False),(5,25,False),(20,40,False),(20,None,None)])
def test_known_final_page_and_unknown_total_remain_distinct(count, total, more):
    """COL-DATA-02/IF-04：总数未知不是0，最后页与未证完整分开。"""
    adapter, calls = adapter_for(dict(items=[{"uuid": str(i)} for i in range(count)], total=total,
                                    pageNum=1 if total==0 else 2, pageSize=20))
    value = dump(adapter.fetch_judicial_page(_subject(), JudicialToolName(CASE), page_number=1 if total==0 else 2))
    assert value["total_count"] == total and value["has_more"] is more
    assert len(value["records"]) == count and len(calls) == 1


@pytest.mark.parametrize("body", [
    {"items": "invalid", "total": 100},
    {"items": [{"uuid": str(i)} for i in range(21)], "total": 100},
    {"items": [{"uuid": "same"}, {"uuid": "same"}], "total": 100},
    {"items": [{"uuid": "wrong", "creditCode": OTHER_CODE}], "total": 100},
    {"items": [{"uuid": "long", "detail": "字" * 5000}], "total": 100},
    {"items": [{"uuid": "r"}], "total": 100, "pageNum": 1},
    {"items": [], "total": 100, "pageNum": 2},
    {"items": [{"uuid": "r"}], "total": 0},
    {"items": [], "total": 0, "_warnings": ["PRIVATE_WARNING"]},
])
def test_invalid_page_is_rejected_atomically_without_silent_cleanup(body):
    """COL-DATA-02/IF-04：错页/重复/错主体/超长/矛盾元数据整页拒绝。"""
    adapter, calls = adapter_for(body)
    with pytest.raises(ProviderError) as caught:
        adapter.fetch_judicial_page(_subject(), JudicialToolName(CASE), page_number=2)
    assert caught.value.code in ("UPSTREAM_INVALID", "UPSTREAM_INCOMPLETE", "SUBJECT_RESPONSE_MISMATCH")
    assert len(calls) == 1
    assert SECRET not in str(caught.value) and "PRIVATE_WARNING" not in str(caught.value)


@pytest.mark.parametrize("status,code,reason,count", [
    (401,"UPSTREAM_AUTH","AUTH_REQUIRED",1), (403,"UPSTREAM_AUTH","TOOL_ENTITLEMENT_REQUIRED",1),
    (429,"UPSTREAM_LIMIT","RATE_OR_QUOTA_LIMIT",1), (500,"UPSTREAM_ERROR","SERVICE_UNAVAILABLE",2),
])
def test_auth_quota_and_transient_errors_keep_safe_diagnostics(status, code, reason, count):
    """COL-DEP-01/ERR-01：不重试权限/额度，瞬时5xx至多重试一次，诊断脱敏。"""
    adapter, calls = adapter_for(dict(error="insufficient_entitlement", raw=SECRET), status=status)
    with pytest.raises(ProviderError) as caught:
        adapter.fetch_judicial_page(_subject(), JudicialToolName(CASE), page_number=2)
    assert caught.value.code == code and len(calls) == count
    detail = dump(caught.value.diagnostic)
    assert detail["reason_code"] == reason and detail["tool_name"] == CASE
    assert SECRET not in json.dumps(detail) and "insufficient_entitlement" not in json.dumps(detail)


def test_non_judicial_snapshot_follows_all_pages_and_only_selected_tool():
    """COL-DATA-02/IF-02：非司法完整性不被首批窗口化；单工具不重查整类。"""
    adapter, calls = adapter_for(lambda call: dict(
        items=[{"id": f"row-{call['arguments']['pageNum']}-{i}"} for i in range(100 if call['arguments']['pageNum']==1 else 1)],
        total=101, pageNum=call["arguments"]["pageNum"], pageSize=100))
    result = dump(adapter.fetch_tool_snapshot(_subject(), SnapshotToolName.get_shareholder_info))
    assert len(result["records"]) == 101 and len(calls) == 2
    assert {call["tool_name"] for call in calls} == {"get_shareholder_info"}


def test_non_judicial_over_200_is_failure_not_truncated_success():
    """COL-DATA-02/COMPAT-01：非司法仍限完整200条，不能只保存首批冒充完成。"""
    adapter, calls = adapter_for(dict(items=[], total=201))
    with pytest.raises(ProviderError) as caught:
        adapter.fetch_tool_snapshot(_subject(), SnapshotToolName.get_shareholder_info)
    assert caught.value.code == "UPSTREAM_INCOMPLETE" and len(calls) == 1


def test_normalization_excludes_score_and_contact_without_losing_evidence():
    """COL-DATA-01/02：只保存原规范化材料，无评分和无关联系方式。"""
    adapter, _ = adapter_for(dict(items=[dict(uuid="r", caseNo="合成案号", phone="FAKE_PHONE", riskLevel="FAKE_RISK")], total=1))
    value = dump(adapter.fetch_judicial_page(_subject(), JudicialToolName(CASE), page_number=1))
    assert "合成案号" in value["records"][0]["content"]
    assert "FAKE_PHONE" not in json.dumps(value) and "FAKE_RISK" not in json.dumps(value)
