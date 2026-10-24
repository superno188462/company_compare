"""WINDOW-TEST-1：QUERY-WINDOW-1.0，WINDOW-IF/ERR/NFR/AC；假HTTP不消耗额度。"""

import json

import httpx
import pytest

from company_screening.adapters.tianyan_mcp import TianyanMcpAdapter
from company_screening.contracts.generated import Category
from company_screening.errors import ProviderError
from test_tianyan_mcp_adapter import _subject


TOOLS = (
    "get_dishonest_info", "get_judgment_debtor_info", "get_high_consumption_restriction",
    "get_judicial_case", "get_judicial_documents", "get_court_notice",
)
CASE = "get_judicial_case"


def adapter_with(responses):
    calls = []

    def handler(request):
        body = json.loads(request.read())
        calls.append(body)
        value = responses.get(body["tool_name"], {"items": [], "total": 0})
        if isinstance(value, int):
            return httpx.Response(value, json={"error": "insufficient_entitlement"})
        return httpx.Response(200, json={"tool_name": body["tool_name"], "content": value})

    return TianyanMcpAdapter(
        "synthetic", client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    ), calls


def cover(batch):
    return {x["tool_name"]: x for x in batch.model_dump(mode="json")["tool_coverage"]}


def test_large_judicial_total_keeps_first_page_and_explicit_partial():
    """WINDOW-IF-01/NFR-01：5564不是整类零接纳；只查固定6项首批，不自动翻页。"""
    adapter, calls = adapter_with({CASE: {
        "items": [{"uuid": f"case-{i}"} for i in range(20)],
        "total": 5564, "pageNum": "1", "pageSize": "20",
    }})
    batch = adapter.fetch_category(_subject(), Category.judicial, record_limit=120)
    assert batch.completeness == "partial" and len(batch.records) == 20
    assert [c["tool_name"] for c in calls] == list(TOOLS)
    assert all(c["arguments"]["pageNum"] == 1 and c["arguments"]["pageSize"] == 20 for c in calls)
    assert cover(batch)[CASE] == dict(
        tool_name=CASE, status="partial", accepted_count=20, total_count=5564, has_more=True,
    )
    assert batch.error_code is None and batch.diagnostic is None


@pytest.mark.parametrize("count", [0, 1, 20])
def test_all_six_tools_complete_when_their_whole_results_fit(count):
    """WINDOW-IF-01：完整空/有记录与partial分开，不把每次窗口都强行标为不完整。"""
    adapter, calls = adapter_with({CASE: {
        "items": [{"uuid": f"case-{i}"} for i in range(count)], "total": count,
    }})
    batch = adapter.fetch_category(_subject(), Category.judicial)
    assert batch.completeness == "complete" and len(batch.records) == count
    assert len(calls) == 6
    assert cover(batch)[CASE]["status"] == ("complete" if count else "empty")
    assert all(x["has_more"] is False for x in cover(batch).values())


def test_each_tool_is_limited_and_category_never_exceeds_120():
    """WINDOW-SCOPE-01：六项均有大结果时最多接纳120条，不把总数相加当独立案件。"""
    adapter, calls = adapter_with({tool: {
        "items": [{"uuid": f"{tool}-{i}"} for i in range(20)], "total": 300,
    } for tool in TOOLS})
    batch = adapter.fetch_category(_subject(), Category.judicial)
    assert len(batch.records) == 120 and len(calls) == 6
    assert all(x["accepted_count"] == 20 and x["status"] == "partial" for x in cover(batch).values())


def test_one_failure_keeps_other_successful_tools_and_first_safe_diagnostic():
    """WINDOW-IF-01/ERR-01：权限失败不能清空后续司法案件，也不自动重试权限错误。"""
    adapter, calls = adapter_with({TOOLS[0]: 403, TOOLS[1]: 429, CASE: {
        "items": [{"uuid": "case-one"}], "total": 1,
    }})
    batch = adapter.fetch_category(_subject(), Category.judicial)
    assert len(calls) == 6 and len(batch.records) == 1 and batch.completeness == "partial"
    assert cover(batch)[TOOLS[0]]["status"] == "error"
    assert cover(batch)[CASE]["status"] == "complete"
    assert batch.error_code == "UPSTREAM_AUTH"
    assert batch.diagnostic.tool_name.value == TOOLS[0]
    assert batch.diagnostic.http_status == 403
    assert "synthetic" not in batch.model_dump_json()


def test_all_tools_failed_remains_error_not_empty_or_success():
    """WINDOW-IF-01：没有任何可靠子范围仍返回错误。"""
    adapter, calls = adapter_with({tool: 403 for tool in TOOLS})
    with pytest.raises(ProviderError) as caught:
        adapter.fetch_category(_subject(), Category.judicial)
    assert caught.value.code == "UPSTREAM_AUTH" and len(calls) == 6


@pytest.mark.parametrize("body", [
    {"items": "invalid", "total": 1},
    {"items": [{"uuid": "same"}, {"uuid": "same"}], "total": 2},
    {"items": [{"uuid": "wrong", "creditCode": "91310000MA1ABCDEFX"}], "total": 1},
    {"items": [{"uuid": "long", "detail": "字" * 5000}], "total": 1},
    {"items": [], "total": 0, "pageNum": 2},
    {"items": [], "total": 0, "_warnings": ["private raw upstream warning"]},
    {"items": [], "total": 50},
    {"items": [{"uuid": str(i)} for i in range(21)], "total": 100},
])
def test_invalid_subtool_page_is_rejected_without_discarding_other_tools(body):
    """WINDOW-IF-01/ERR-01：不通过删字段/裁剪/混入错配来获得成功；仅拒绝该页。"""
    adapter, calls = adapter_with({CASE: body, TOOLS[0]: {
        "items": [{"id": "retained"}], "total": 1,
    }})
    batch = adapter.fetch_category(_subject(), Category.judicial)
    assert len(calls) == 6 and batch.completeness == "partial"
    assert len(batch.records) == 1 and cover(batch)[CASE]["status"] == "error"
    assert batch.diagnostic is not None
    assert "private raw" not in batch.model_dump_json()


def test_small_budget_limits_request_and_marks_unrequested_tools():
    """WINDOW-IF-01：只有3条容量时不多取、不丢其他证据，也不对剩余工具收费查询。"""
    adapter, calls = adapter_with({TOOLS[0]: {
        "items": [{"id": str(i)} for i in range(3)], "total": 100,
    }})
    batch = adapter.fetch_category(_subject(), Category.judicial, record_limit=3)
    assert len(calls) == 1 and calls[0]["arguments"]["pageSize"] == 3
    assert len(batch.records) == 3 and batch.completeness == "partial"
    assert all(cover(batch)[t]["status"] == "not_requested" for t in TOOLS[1:])


def test_empty_tools_do_not_consume_available_record_budget():
    """WINDOW-IF-01：空结果不占接纳条数预算，后面的固定工具仍可查询。"""
    adapter, calls = adapter_with({CASE: {"items": [{"uuid": "one"}], "total": 1}})
    batch = adapter.fetch_category(_subject(), Category.judicial, record_limit=3)
    assert len(calls) == 6 and len(batch.records) == 1
    assert calls[-1]["arguments"]["pageSize"] == 2


def test_missing_total_is_unknown_partial_not_zero():
    """WINDOW-DATA/ERR-01：未知总数不能补零或当作完整。"""
    adapter, _ = adapter_with({CASE: {"items": [{"uuid": "one"}]}})
    batch = adapter.fetch_category(_subject(), Category.judicial)
    assert batch.completeness == "partial" and len(batch.records) == 1
    assert cover(batch)[CASE]["total_count"] is None and cover(batch)[CASE]["has_more"] is None


def test_provider_truncation_signal_prevents_complete_claim():
    """WINDOW-DEP-01：HTTP200和相同total不能掩盖上游明确的截断信号。"""
    adapter, _ = adapter_with({CASE: {
        "items": [{"uuid": "one"}], "total": 1, "_truncated": True,
    }})
    batch = adapter.fetch_category(_subject(), Category.judicial)
    assert batch.completeness == "partial" and cover(batch)[CASE]["status"] == "partial"
    assert cover(batch)[CASE]["has_more"] is not False


def test_cross_source_shareholder_ids_remain_stable_and_distinct():
    """BE-IF-07：不同股东来源的同值ID不应误报重复；重查定位保持稳定。"""
    adapter, _ = adapter_with({
        "get_company_registration_info": {"sources": {"base": {"id": "reg"}}},
        "get_shareholder_info": {"sources": {source: {
            "items": [{"id": "same", "name": "合成股东"}], "total": 1,
        } for source in ("holder", "list")}},
    })
    first = adapter.fetch_category(_subject(), Category.basic)
    second = adapter.fetch_category(_subject(), Category.basic)
    assert len(first.records) == len({r.record_id for r in first.records}) == 3
    assert [r.record_id for r in first.records] == [r.record_id for r in second.records]
