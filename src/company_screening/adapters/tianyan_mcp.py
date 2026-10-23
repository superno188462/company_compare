"""天眼查 MCP Shared Core 适配器。"""

from collections.abc import Callable
from datetime import date
import json
import time
from typing import Any

import httpx
from pydantic import ValidationError

from ..contracts.boundary import (
    ProviderCandidate,
    ProviderCategoryBatch,
    ProviderFailureCode,
    ProviderSearchPage,
    SearchCommand,
)
from ..contracts.generated import Category, Subject
from ..errors import ProviderError


def _provider_error(code: ProviderFailureCode, retryable: bool) -> ProviderError:
    """构造不携带上游正文或凭据的适配器错误。"""
    error = ProviderError("Tianyan MCP request failed")
    error.code = code
    error.retryable = retryable
    return error


class TianyanMcpAdapter:
    """把天眼查 MCP 的返回转换成稳定的企业数据端口模型。"""

    def __init__(
        self,
        authorization: str,
        *,
        core_url: str = "https://mcp.tianyancha.com/v1/core/tools/call",
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        """保存服务端凭据和可替换 HTTP 依赖，不在构造时发起网络调用。"""
        if not authorization.strip():
            raise ValueError("TYC_AUTHORIZATION is required")
        self._authorization = authorization
        self._core_url = core_url
        self._client = client or httpx.Client(timeout=8.0)
        self._sleep = sleep or time.sleep

    def search(self, command: SearchCommand) -> ProviderSearchPage:
        """调用 search_companies，只规范化候选，不选择主体。"""
        page_number = 1
        if command.cursor is not None:
            try:
                page_number = int(command.cursor)
            except ValueError as exc:
                raise _provider_error("UPSTREAM_INVALID", False) from exc
            if page_number < 1:
                raise _provider_error("UPSTREAM_INVALID", False)

        body = {
            "tool_name": "search_companies",
            "arguments": {
                "searchKey": command.query.strip(),
                "pageNum": page_number,
                "pageSize": command.page_size,
            },
            "format": "json",
        }
        response: httpx.Response | None = None
        for attempt in range(2):
            try:
                response = self._client.post(
                    self._core_url,
                    headers={
                        "Authorization": self._authorization,
                        "Accept": "application/json",
                    },
                    json=body,
                    timeout=8.0,
                )
            except httpx.TimeoutException as exc:
                if attempt == 0:
                    self._sleep(0.5)
                    continue
                raise _provider_error("UPSTREAM_TIMEOUT", True) from exc
            except httpx.RequestError as exc:
                if attempt == 0:
                    self._sleep(0.5)
                    continue
                raise _provider_error("UPSTREAM_ERROR", True) from exc
            if response.status_code >= 500 and attempt == 0:
                self._sleep(0.5)
                continue
            break

        if response is None:
            raise _provider_error("UPSTREAM_ERROR", True)
        if response.status_code in (401, 403):
            raise _provider_error("UPSTREAM_AUTH", False)
        if response.status_code == 429:
            raise _provider_error("UPSTREAM_LIMIT", False)
        if 400 <= response.status_code < 500:
            raise _provider_error("UPSTREAM_INVALID", False)
        if response.status_code >= 500:
            raise _provider_error("UPSTREAM_ERROR", True)
        if not 200 <= response.status_code < 300:
            raise _provider_error("UPSTREAM_ERROR", False)

        try:
            envelope: Any = response.json()
            content: Any = envelope["content"]
            if isinstance(content, str):
                content = json.loads(content)
            if not isinstance(content, dict) or not isinstance(content.get("items"), list):
                raise TypeError("invalid content")
            total_raw = content.get("total")
            total = int(total_raw) if total_raw is not None and not isinstance(total_raw, bool) else None
            if total is not None and total < 0:
                raise ValueError("invalid total")
            provider_page = int(content.get("pageNum", page_number))
            provider_page_size = int(content.get("pageSize", command.page_size))
            if provider_page < 1 or provider_page_size < 1:
                raise ValueError("invalid pagination")

            candidates: list[ProviderCandidate] = []
            for raw_item in content["items"]:
                if not isinstance(raw_item, dict):
                    raise TypeError("invalid item")
                established_raw = raw_item.get("establishTime") or raw_item.get("estiblishTime")
                established = None
                if established_raw not in (None, ""):
                    established = date.fromisoformat(str(established_raw)[:10])
                credit_raw = raw_item.get("creditCode")
                credit_code = None if credit_raw in (None, "") else str(credit_raw).strip()
                legal_raw = raw_item.get("legalPersonName")
                legal_representative = None if legal_raw in (None, "") else str(legal_raw).strip()
                candidates.append(ProviderCandidate(
                    name=str(raw_item["name"]).strip(),
                    credit_code=credit_code,
                    registered_region=None,
                    legal_representative=legal_representative,
                    established_on=established,
                ))

            next_cursor = None
            if total is not None and provider_page * provider_page_size < total:
                next_cursor = str(provider_page + 1)
            return ProviderSearchPage(items=candidates, next_cursor=next_cursor, total=total)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
            raise _provider_error("UPSTREAM_INVALID", False) from exc

    def fetch_category(self, subject: Subject, category: Category) -> ProviderCategoryBatch:
        """分类查询将在各类别映射确认后逐项实现。"""
        raise NotImplementedError()
