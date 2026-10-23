"""CONTRACT-1.0：BE-IF-07、BE-NFR-01 天眼查 MCP 适配器。"""

from datetime import date, datetime, timezone
import json
from typing import Any

import httpx
import pytest

from company_screening.adapters.tianyan_mcp import TianyanMcpAdapter
from company_screening.contracts.boundary import SearchCommand
from company_screening.contracts.generated import Category, CreditCode, Subject
from company_screening.errors import ProviderError


def _response(content: dict[str, Any]) -> dict[str, Any]:
    return {"tool_name": "search_companies", "format": "json", "content": content}


def _subject() -> Subject:
    return Subject(
        name="北京百度网讯科技有限公司",
        credit_code=CreditCode("91110000802100433B"),
        registered_region=None,
        legal_representative="梁志祥",
        established_on=date(2001, 6, 5),
        confirmed_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
    )


def _tool_response(tool_name: str, content: dict[str, Any] | str) -> dict[str, Any]:
    return {"tool_name": tool_name, "format": "json", "content": content}


def test_search_maps_candidates_and_next_page_without_selecting_subject() -> None:
    """BE-IF-07：按当前官方 Shared Core 请求映射候选及页码游标。"""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = request.read().decode("utf-8")
        return httpx.Response(200, json=_response({
            "items": [{
                "name": "北京百度网讯科技有限公司",
                "creditCode": "91110000802100433B",
                "legalPersonName": "梁志祥",
                "establishTime": "2001-06-05 00:00:00.0",
                "id": 22822,
            }],
            "pageNum": "1", "pageSize": "1", "total": 2,
        }))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    page = TianyanMcpAdapter("local-secret", client=client).search(
        SearchCommand(query=" 北京百度网讯科技有限公司 ", page_size=1)
    )

    assert captured["authorization"] == "local-secret"
    assert '"tool_name":"search_companies"' in captured["body"]
    assert '"searchKey":"北京百度网讯科技有限公司"' in captured["body"]
    assert page.total == 2
    assert page.next_cursor == "2"
    assert page.items[0].name == "北京百度网讯科技有限公司"
    assert page.items[0].credit_code == "91110000802100433B"
    assert page.items[0].legal_representative == "梁志祥"
    assert page.items[0].established_on.isoformat() == "2001-06-05"
    assert page.items[0].registered_region is None


def test_search_uses_cursor_as_provider_page_number() -> None:
    """BE-IF-07：应用只把游标作为不透明值回传，适配器负责解释。"""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(__import__("json").loads(request.read()))
        return httpx.Response(200, json=_response({
            "items": [], "pageNum": "2", "pageSize": "20", "total": 20,
        }))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    page = TianyanMcpAdapter("local-secret", client=client).search(
        SearchCommand(query="测试企业", cursor="2")
    )

    assert seen["arguments"]["pageNum"] == 2
    assert page.items == []
    assert page.next_cursor is None


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [(401, "UPSTREAM_AUTH", False), (403, "UPSTREAM_AUTH", False),
     (429, "UPSTREAM_LIMIT", False), (400, "UPSTREAM_INVALID", False)],
)
def test_search_maps_http_failures(status: int, code: str, retryable: bool) -> None:
    """BE-IF-07：提供方失败不能冒充空结果，也不暴露原始响应。"""
    client = httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(status, json={"error": "provider detail"})
    ))

    with pytest.raises(ProviderError) as caught:
        TianyanMcpAdapter("local-secret", client=client).search(SearchCommand(query="测试企业"))

    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert "provider detail" not in str(caught.value)


def test_search_retries_one_transient_failure() -> None:
    """BE-NFR-01：瞬时网络/服务错误最多重试一次，间隔0.5秒。"""
    attempts = 0
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json=_response({
            "items": [], "pageNum": "1", "pageSize": "20", "total": 0,
        }))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    page = TianyanMcpAdapter("local-secret", client=client, sleep=sleeps.append).search(
        SearchCommand(query="测试企业")
    )

    assert page.items == []
    assert attempts == 2
    assert sleeps == [0.5]


@pytest.mark.parametrize("content", [
    None,
    {"items": "not-a-list", "pageNum": 1, "pageSize": 20, "total": 0},
    {"items": [{"name": "测试企业", "creditCode": "INVALID"}], "pageNum": 1, "pageSize": 20, "total": 1},
])
def test_search_rejects_invalid_provider_content(content: Any) -> None:
    """BE-IF-03/07：非法或主体字段失真的响应是错误，不是空结果。"""
    client = httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=_response(content))
    ))

    with pytest.raises(ProviderError) as caught:
        TianyanMcpAdapter("local-secret", client=client).search(SearchCommand(query="测试企业"))

    assert caught.value.code == "UPSTREAM_INVALID"
    assert caught.value.retryable is False


def test_fetch_basic_requires_registration_and_all_shareholder_pages() -> None:
    """BE-IF-07：工商类别固定包含登记与股东，分页必须完整且不输出评分/联系方式。"""
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        calls.append(body)
        tool = body["tool_name"]
        if tool == "get_company_registration_info":
            return httpx.Response(200, json=_tool_response(tool, {
                "sources": {
                    "base": {
                        "id": 22822,
                        "name": "北京百度网讯科技有限公司",
                        "creditCode": "91110000802100433B",
                        "regCapital": "1342128 万人民币",
                        "actualCapital": "未知",
                        "percentileScore": 99,
                        "phoneNumber": "010-00000000",
                        "updateTimes": "2026-10-20 12:00:00",
                        "sourceName": "天眼查工商信息",
                    },
                    "type": {"companyType": "有限责任公司", "empty": False},
                }
            }))
        assert tool == "get_shareholder_info"
        page = body["arguments"]["pageNum"]
        item = {
            "id": f"shareholder-{page}",
            "name": f"股东{page}",
            "capital": f"{page} 万人民币",
            "email": f"person{page}@example.com",
        }
        return httpx.Response(200, json=_tool_response(tool, {
            "items": [item], "pageNum": page, "pageSize": 1, "total": 2,
        }))

    batch = TianyanMcpAdapter(
        "local-secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        detail_page_size=1,
    ).fetch_category(_subject(), Category.basic)

    assert [call["tool_name"] for call in calls] == [
        "get_company_registration_info", "get_shareholder_info", "get_shareholder_info",
    ]
    assert all(call["arguments"]["searchKey"] == "91110000802100433B" for call in calls)
    assert batch.binding_credit_code == "91110000802100433B"
    assert batch.category == Category.basic
    assert batch.scope_description == "工商登记、股东及出资"
    assert len(batch.records) == 3
    assert batch.records[0].record_credit_code == "91110000802100433B"
    assert batch.records[0].event_time == "2026-10-20 12:00:00"
    assert "percentileScore" not in batch.records[0].content
    assert "phoneNumber" not in batch.records[0].content
    assert "email" not in batch.records[1].content
    assert len({record.record_id for record in batch.records}) == 3


def test_fetch_penalty_accepts_string_content_and_empty_page() -> None:
    """BE-IF-07：Shared Core 的 JSON 字符串正文也要解析；完整空结果才可标为空。"""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        seen.append(body["tool_name"])
        content = json.dumps({
            "items": [], "pageNum": 1, "pageSize": 100, "total": 0,
            "_empty": True, "_summary": "经查无结果",
        }, ensure_ascii=False)
        return httpx.Response(200, json=_tool_response(body["tool_name"], content))

    batch = TianyanMcpAdapter(
        "local-secret", client=httpx.Client(transport=httpx.MockTransport(handler))
    ).fetch_category(_subject(), Category.penalty)

    assert seen == ["get_administrative_penalty"]
    assert batch.records == []
    assert batch.scope_description == "行政处罚"


def test_fetch_category_rejects_partial_subtool_success() -> None:
    """BE-IF-07：同类别任一计划子查询无权限时整类失败，不返回部分记录。"""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.read())
        if body["tool_name"] == "get_company_registration_info":
            return httpx.Response(200, json=_tool_response(body["tool_name"], {
                "sources": {"base": {"id": 1, "creditCode": "91110000802100433B"}}
            }))
        return httpx.Response(403, json={"error": "insufficient_entitlement"})

    adapter = TianyanMcpAdapter(
        "local-secret", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ProviderError) as caught:
        adapter.fetch_category(_subject(), Category.basic)

    assert calls == 2
    assert caught.value.code == "UPSTREAM_AUTH"
    assert caught.value.retryable is False
    assert "insufficient_entitlement" not in str(caught.value)


def test_fetch_category_rejects_explicit_subject_mismatch() -> None:
    """BE-IF-03/07：详情明确返回另一统一社会信用代码时拒绝整类。"""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        return httpx.Response(200, json=_tool_response(body["tool_name"], {
            "sources": {"base": {"id": 1, "creditCode": "91310000MA1ABCDEFX"}}
        }))

    adapter = TianyanMcpAdapter(
        "local-secret", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ProviderError) as caught:
        adapter.fetch_category(_subject(), Category.basic)

    assert caught.value.code == "SUBJECT_RESPONSE_MISMATCH"
    assert caught.value.retryable is False


def test_fetch_category_rejects_more_than_two_hundred_records() -> None:
    """BE-IF-03/07：提供方声明超过类别上限时明确失败，不静默截取前200条。"""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.read())
        return httpx.Response(200, json=_tool_response(body["tool_name"], {
            "items": [{"id": "penalty-1", "decisionDate": "2026-01-01"}],
            "pageNum": 1, "pageSize": 100, "total": 201,
        }))

    adapter = TianyanMcpAdapter(
        "local-secret", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ProviderError) as caught:
        adapter.fetch_category(_subject(), Category.penalty)

    assert calls == 1
    assert caught.value.code == "UPSTREAM_INCOMPLETE"
    assert caught.value.retryable is False


def test_fetch_category_rejects_provider_warning_and_oversized_record() -> None:
    """BE-IF-07：警告或超长记录代表未完整取得，不能删字段或截断后冒充成功。"""
    contents = [
        {"items": [], "pageNum": 1, "pageSize": 100, "total": 0, "_warnings": ["partial"]},
        {"items": [{"id": "too-long", "detail": "字" * 5000}], "pageNum": 1, "pageSize": 100, "total": 1},
    ]
    for content in contents:
        adapter = TianyanMcpAdapter(
            "local-secret",
            client=httpx.Client(transport=httpx.MockTransport(
                lambda request, value=content: httpx.Response(
                    200,
                    json=_tool_response(json.loads(request.read())["tool_name"], value),
                )
            )),
        )
        with pytest.raises(ProviderError) as caught:
            adapter.fetch_category(_subject(), Category.penalty)
        assert caught.value.code == "UPSTREAM_INCOMPLETE"
