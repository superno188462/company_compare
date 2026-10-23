"""CONTRACT-1.0：BE-IF-07、BE-NFR-01 天眼查 MCP 搜索适配器。"""

from typing import Any

import httpx
import pytest

from company_screening.adapters.tianyan_mcp import TianyanMcpAdapter
from company_screening.contracts.boundary import SearchCommand
from company_screening.errors import ProviderError


def _response(content: dict[str, Any]) -> dict[str, Any]:
    return {"tool_name": "search_companies", "format": "json", "content": content}


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
