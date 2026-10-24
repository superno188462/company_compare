"""天眼查 MCP Shared Core 适配器。"""

from collections.abc import Callable
from datetime import date, datetime, timezone
import hashlib
import json
import time
from typing import Any
from uuid import uuid4

import httpx
from pydantic import ValidationError

from ..contracts.boundary import (
    ProviderCandidate,
    ProviderCategoryBatch,
    ProviderFailureCode,
    ProviderRecord,
    ProviderSearchPage,
    SearchCommand,
)
from ..contracts.generated import Category, CreditCode, QueryDiagnostic, Subject
from ..errors import ProviderError


_CATEGORY_TOOL_PLAN: dict[Category, tuple[tuple[str, bool], ...]] = {
    Category.basic: (
        ("get_company_registration_info", False),
        ("get_shareholder_info", True),
    ),
    Category.abnormal: (("get_business_exception", True),),
    Category.penalty: (("get_administrative_penalty", True),),
    Category.judicial: (
        ("get_dishonest_info", True),
        ("get_judgment_debtor_info", True),
        ("get_high_consumption_restriction", True),
        ("get_judicial_case", True),
        ("get_judicial_documents", True),
        ("get_court_notice", True),
    ),
    Category.asset: (
        ("get_equity_freeze", True),
        ("get_judicial_assistance", True),
        ("get_chattel_mortgage_info", True),
        ("get_land_mortgage_info", True),
    ),
}

_CATEGORY_SCOPE: dict[Category, str] = {
    Category.basic: "工商登记、股东及出资",
    Category.abnormal: "经营异常",
    Category.penalty: "行政处罚",
    Category.judicial: "失信、被执行、限高、司法案件、裁判文书及法院公告",
    Category.asset: "股权冻结、司法协助、动产抵押及土地抵押",
}

_SENSITIVE_KEY_PARTS = (
    "score", "rating", "risklevel", "phone", "mobile", "telephone", "email", "contact",
    "wechat", "qq",
)
_CREDIT_KEYS = ("creditCode", "companyCreditCode", "socialCreditCode")
_ID_KEYS = (
    "id", "recordId", "caseId", "uuid", "punishNumber", "decisionNumber", "caseNo",
    "regNumber", "documentNumber",
)
_TIME_KEYS = (
    "eventTime", "decisionDate", "publishDate", "registerDate", "updateTimes",
    "establishTime", "estiblishTime", "fromTime", "date", "time",
)
_URL_KEYS = ("sourceUrl", "detailUrl", "url")
_PUBLISHER_KEYS = (
    "sourcePublisher", "publishDepartment", "decisionDepartment", "regInstitute", "sourceName",
)


class _ToolContent(dict[str, Any]):
    """只在单次调用栈中携带HTTP元数据，属性不进入响应内容或证据。"""

    http_status: int


class _ToolRecords(list[ProviderRecord]):
    """已完整取得的子工具记录及最后一次实际HTTP状态。"""

    http_status: int | None = None


class _SourceItem(dict[str, Any]):
    """在规范化期间保留聚合来源命名空间，不向正文注入内部字段。"""

    source_name: str


def _provider_error(
    code: ProviderFailureCode,
    retryable: bool,
    *,
    reason_code: str = "UNCLASSIFIED_FAILURE",
    phase: str = "unknown",
    tool_name: str | None = None,
    http_status: int | None = None,
    field: str | None = None,
    actual_count: int | None = None,
    limit_count: int | None = None,
) -> ProviderError:
    """仅以白名单及计数生成脱敏诊断，不接收上游消息或异常repr。"""
    error = ProviderError("Tianyan MCP request failed")
    error.code = code
    error.retryable = retryable
    error.diagnostic = QueryDiagnostic.model_validate({
        "diagnostic_id": uuid4(), "tool_name": tool_name, "phase": phase,
        "reason_code": reason_code, "http_status": http_status, "field": field,
        "actual_count": actual_count, "limit_count": limit_count,
    })
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
        detail_page_size: int = 100,
    ) -> None:
        """保存服务端凭据和可替换 HTTP 依赖，不在构造时发起网络调用。"""
        if not authorization.strip():
            raise ValueError("TYC_AUTHORIZATION is required")
        self._authorization = authorization
        self._core_url = core_url
        self._client = client or httpx.Client(timeout=8.0)
        self._sleep = sleep or time.sleep
        if not 1 <= detail_page_size <= 100:
            raise ValueError("detail_page_size must be between 1 and 100")
        self._detail_page_size = detail_page_size

    def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> _ToolContent:
        """调用一次 Shared Core 工具并统一处理重试、鉴权和 JSON 外壳。"""
        body = {"tool_name": tool_name, "arguments": arguments, "format": "json"}
        response: httpx.Response | None = None
        for attempt in range(2):
            try:
                response = self._client.post(
                    self._core_url,
                    headers={"Authorization": self._authorization, "Accept": "application/json"},
                    json=body,
                    timeout=8.0,
                )
            except httpx.TimeoutException as exc:
                if attempt == 0:
                    self._sleep(0.5)
                    continue
                raise _provider_error("UPSTREAM_TIMEOUT", True, reason_code="REQUEST_TIMEOUT",
                                      phase="request", tool_name=tool_name) from exc
            except httpx.RequestError as exc:
                if attempt == 0:
                    self._sleep(0.5)
                    continue
                raise _provider_error("UPSTREAM_ERROR", True, reason_code="NETWORK_ERROR",
                                      phase="request", tool_name=tool_name) from exc
            if response.status_code >= 500 and attempt == 0:
                self._sleep(0.5)
                continue
            break

        if response is None:
            raise _provider_error("UPSTREAM_ERROR", True, reason_code="NETWORK_ERROR",
                                  phase="request", tool_name=tool_name)
        context: dict[str, Any] = {"tool_name": tool_name, "http_status": response.status_code}
        if response.status_code in (401, 403):
            reason = "AUTH_REQUIRED"
            if response.status_code == 403:
                try:
                    rejected = response.json()
                    if isinstance(rejected, dict) and rejected.get("error") == "insufficient_entitlement":
                        reason = "TOOL_ENTITLEMENT_REQUIRED"
                except ValueError:
                    pass
            raise _provider_error("UPSTREAM_AUTH", False, reason_code=reason, phase="request", **context)
        if response.status_code == 429:
            raise _provider_error("UPSTREAM_LIMIT", False, reason_code="RATE_OR_QUOTA_LIMIT",
                                  phase="request", **context)
        if 400 <= response.status_code < 500:
            raise _provider_error("UPSTREAM_INVALID", False, reason_code="REQUEST_REJECTED",
                                  phase="request", **context)
        if response.status_code >= 500:
            raise _provider_error("UPSTREAM_ERROR", True, reason_code="SERVICE_UNAVAILABLE",
                                  phase="request", **context)
        if not 200 <= response.status_code < 300:
            raise _provider_error("UPSTREAM_ERROR", False, reason_code="REQUEST_REJECTED",
                                  phase="request", **context)

        field = "content"
        try:
            envelope: Any = response.json()
            if not isinstance(envelope, dict) or envelope.get("tool_name") != tool_name:
                field = "tool_name"
                raise TypeError("invalid envelope")
            content: Any = envelope["content"]
            if isinstance(content, str):
                content = json.loads(content)
            if not isinstance(content, dict):
                raise TypeError("invalid content")
            result = _ToolContent(content)
            result.http_status = response.status_code
            return result
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise _provider_error("UPSTREAM_INVALID", False, reason_code="RESPONSE_INVALID",
                                  phase="response", field=field, **context) from exc

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

        try:
            content = self._call_tool("search_companies", {
                "searchKey": command.query.strip(),
                "pageNum": page_number,
                "pageSize": command.page_size,
            })
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

    def fetch_category(
        self, subject: Subject, category: Category, *, record_limit: int = 200,
    ) -> ProviderCategoryBatch:
        """司法按已确认窗口返回明确范围；其他类别仍要求完整取得。"""
        if category == Category.judicial:
            return self._fetch_judicial_window(subject, record_limit)
        records: list[ProviderRecord] = []
        http_status: int | None = None
        last_tool: str | None = None
        tool_records: list[ProviderRecord]
        for tool_name, paged in _CATEGORY_TOOL_PLAN[category]:
            last_tool = tool_name
            if paged:
                paged_records = self._fetch_paged_tool(subject, tool_name)
                http_status = paged_records.http_status
                tool_records = paged_records
            else:
                content = self._call_tool(tool_name, {"searchKey": subject.credit_code.root})
                http_status = content.http_status
                try:
                    tool_records = self._registration_records(subject, tool_name, content)
                except ProviderError as exc:
                    if exc.diagnostic is not None:
                        exc.diagnostic = QueryDiagnostic.model_validate({
                            **exc.diagnostic.model_dump(mode="python"),
                            "tool_name": tool_name, "http_status": http_status,
                        })
                    raise
            if len(records) + len(tool_records) > 200:
                raise _provider_error("UPSTREAM_INCOMPLETE", False, reason_code="RECORD_LIMIT_EXCEEDED",
                                      phase="aggregate", tool_name=tool_name, http_status=http_status,
                                      field="record_count", actual_count=len(records) + len(tool_records), limit_count=200)
            records.extend(tool_records)

        if len({record.record_id for record in records}) != len(records):
            raise _provider_error("UPSTREAM_INVALID", False, reason_code="DUPLICATE_RECORDS",
                                  phase="aggregate", field="record_id", tool_name=last_tool, http_status=http_status)
        return ProviderCategoryBatch(
            binding_credit_code=subject.credit_code.root,
            category=category,
            queried_at=datetime.now(timezone.utc),
            scope_description=_CATEGORY_SCOPE[category],
            records=records,
        )

    def _fetch_judicial_window(self, subject: Subject, record_limit: int) -> ProviderCategoryBatch:
        """WINDOW-IF-01：固定六项各取首批，原子接纳有效页并保留真实缺口。"""
        if isinstance(record_limit, bool) or not isinstance(record_limit, int) or record_limit < 1:
            raise _provider_error("UPSTREAM_INCOMPLETE", False, reason_code="RECORD_LIMIT_EXCEEDED",
                                  phase="aggregate", field="record_count", limit_count=200)
        remaining = min(record_limit, 120)
        records: list[ProviderRecord] = []
        coverage: list[dict[str, Any]] = []
        first_error: ProviderError | None = None
        reliable_tools = 0
        for tool_name, _ in _CATEGORY_TOOL_PLAN[Category.judicial]:
            if remaining == 0:
                coverage.append({"tool_name": tool_name, "status": "not_requested", "accepted_count": 0,
                                 "total_count": None, "has_more": None})
                continue
            page_size = min(20, remaining)
            content: _ToolContent | None = None
            try:
                content = self._call_tool(tool_name, {
                    "searchKey": subject.credit_code.root, "pageNum": 1, "pageSize": page_size,
                })
                unknown_total = "items" in content and content.get("total") is None
                page_content: dict[str, Any] = content
                if unknown_total:
                    # 临时计数仅用于已有页结构校验，不能作为公开total或完整性依据。
                    raw_items = content.get("items")
                    page_content = {**content, "total": len(raw_items) if isinstance(raw_items, list) else 0}
                items, declared_total, _ = self._extract_page(page_content, 1)
                if len(items) > page_size:
                    raise _provider_error("UPSTREAM_INVALID", False, reason_code="PAGINATION_INVALID",
                                          phase="pagination", field="items", actual_count=len(items))
                if not items and declared_total > 0:
                    raise _provider_error("UPSTREAM_INCOMPLETE", False, reason_code="PAGINATION_INCOMPLETE",
                                          phase="pagination", field="items", actual_count=0)
                page_records = [self._make_record(subject, tool_name, item, nested_metadata=False) for item in items]
                if len({record.record_id for record in page_records}) != len(page_records):
                    raise _provider_error("UPSTREAM_INVALID", False, reason_code="DUPLICATE_RECORDS",
                                          phase="aggregate", field="record_id")
                total = None if unknown_total else declared_total
                truncated = content.get("_truncated") not in (None, False)
                has_more: bool | None = None if unknown_total else declared_total > len(page_records)
                if truncated and has_more is False:
                    has_more = None
                incomplete = unknown_total or truncated or has_more is True
                records.extend(page_records)
                remaining -= len(page_records)
                reliable_tools += 1
                coverage.append({
                    "tool_name": tool_name,
                    "status": "partial" if incomplete else "complete" if page_records else "empty",
                    "accepted_count": len(page_records), "total_count": total, "has_more": has_more,
                })
            except ProviderError as exc:
                detail: dict[str, Any] = exc.diagnostic.model_dump(mode="python") if exc.diagnostic is not None else {
                    "diagnostic_id": uuid4(), "tool_name": None, "phase": "unknown",
                    "reason_code": "UNCLASSIFIED_FAILURE", "http_status": None,
                    "field": None, "actual_count": None, "limit_count": None,
                }
                detail["tool_name"] = tool_name
                if detail["http_status"] is None and content is not None:
                    detail["http_status"] = content.http_status
                exc.diagnostic = QueryDiagnostic.model_validate(detail)
                if first_error is None:
                    first_error = exc
                coverage.append({"tool_name": tool_name, "status": "error", "accepted_count": 0,
                                 "total_count": None, "has_more": None})
        if reliable_tools == 0 and first_error is not None:
            raise first_error
        partial = any(item["status"] not in ("complete", "empty") for item in coverage)
        return ProviderCategoryBatch.model_validate({
            "binding_credit_code": subject.credit_code.root, "category": Category.judicial,
            "queried_at": datetime.now(timezone.utc),
            "scope_description": "司法固定六项各取第一页、每项最多20条；未完成部分见子工具覆盖" if partial
                                 else _CATEGORY_SCOPE[Category.judicial],
            "records": records, "completeness": "partial" if partial else "complete",
            "tool_coverage": coverage,
            "error_code": first_error.code if first_error is not None else None,
            "diagnostic": first_error.diagnostic if first_error is not None else None,
        })

    def _fetch_paged_tool(self, subject: Subject, tool_name: str) -> _ToolRecords:
        """完整读取一个明细工具的所有页面，并核对页码、总数和类别预算。"""
        records = _ToolRecords()
        expected_total: int | None = None
        page_number = 1
        content: _ToolContent | None = None
        try:
            while True:
                # 新页面无响应时不能沿用上一页的HTTP200。
                content = None
                content = self._call_tool(tool_name, {
                    "searchKey": subject.credit_code.root,
                    "pageNum": page_number,
                    "pageSize": self._detail_page_size,
                })
                records.http_status = content.http_status
                items, total, has_more = self._extract_page(content, page_number)
                if expected_total is None:
                    expected_total = total
                    if total > 200:
                        raise _provider_error("UPSTREAM_INCOMPLETE", False,
                                              reason_code="RECORD_LIMIT_EXCEEDED", phase="pagination",
                                              field="total", actual_count=total, limit_count=200)
                elif total != expected_total:
                    raise _provider_error("UPSTREAM_INCOMPLETE", False, reason_code="PAGINATION_CHANGED",
                                          phase="pagination", field="total")
                for item in items:
                    records.append(self._make_record(subject, tool_name, item, nested_metadata=False))
                if len(records) > 200:
                    raise _provider_error("UPSTREAM_INCOMPLETE", False,
                                          reason_code="RECORD_LIMIT_EXCEEDED", phase="pagination",
                                          field="record_count", actual_count=len(records), limit_count=200)
                if not has_more:
                    break
                if not items:
                    raise _provider_error("UPSTREAM_INCOMPLETE", False, reason_code="PAGINATION_INCOMPLETE",
                                          phase="pagination", field="items", actual_count=len(records))
                page_number += 1

            if expected_total is None or len(records) != expected_total:
                raise _provider_error("UPSTREAM_INCOMPLETE", False, reason_code="PAGINATION_INCOMPLETE",
                                      phase="pagination", field="items", actual_count=len(records))
        except ProviderError as exc:
            if exc.diagnostic is not None:
                detail = exc.diagnostic.model_dump(mode="python")
                detail["tool_name"] = tool_name
                if detail["http_status"] is None and content is not None:
                    detail["http_status"] = content.http_status
                exc.diagnostic = QueryDiagnostic.model_validate(detail)
            raise
        return records

    def _extract_page(
        self, content: dict[str, Any], expected_page: int,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        """解析直接 items 或 sources 聚合分页结构，不猜测缺失的分页元数据。"""
        self._reject_warnings(content)
        if "items" in content:
            return self._page_part(content, expected_page)

        sources = content.get("sources")
        if not isinstance(sources, dict):
            raise _provider_error("UPSTREAM_INVALID", False, reason_code="RESPONSE_INVALID",
                                  phase="response", field="sources")
        all_items: list[dict[str, Any]] = []
        total = 0
        has_more = False
        for source_name, source in sources.items():
            if not isinstance(source, dict):
                raise _provider_error("UPSTREAM_INVALID", False, reason_code="RESPONSE_INVALID",
                                      phase="response", field="sources")
            self._reject_warnings(source)
            if source.get("_empty") is True or source.get("empty") is True:
                source = {**source, "items": source.get("items", []), "total": source.get("total", 0)}
            part_items, part_total, part_more = self._page_part(source, expected_page)
            for item in part_items:
                sourced_item = _SourceItem(item)
                sourced_item.source_name = str(source_name)
                all_items.append(sourced_item)
            total += part_total
            has_more = has_more or part_more
        return all_items, total, has_more

    def _page_part(
        self, content: dict[str, Any], expected_page: int,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        """校验单一分页分片，拒绝布尔数值及不一致的分页声明。"""
        field = "items"
        try:
            raw_items = content["items"]
            if not isinstance(raw_items, list) or any(not isinstance(item, dict) for item in raw_items):
                raise TypeError("invalid items")
            field = "total"
            raw_total = content["total"]
            raw_page = content.get("pageNum", expected_page)
            raw_size = content.get("pageSize", self._detail_page_size)
            if isinstance(raw_total, bool):
                raise TypeError("invalid total")
            total = int(raw_total)
            if total < 0 or len(raw_items) > total:
                raise ValueError("invalid total")
            field = "pageNum"
            if isinstance(raw_page, bool):
                raise TypeError("invalid page")
            page_number = int(raw_page)
            if page_number != expected_page:
                raise ValueError("invalid page")
            field = "pageSize"
            if isinstance(raw_size, bool):
                raise TypeError("invalid page size")
            page_size = int(raw_size)
            if page_size < 1 or len(raw_items) > page_size:
                raise ValueError("invalid pagination")
            return raw_items, total, page_number * page_size < total
        except (KeyError, TypeError, ValueError) as exc:
            raise _provider_error("UPSTREAM_INVALID", False, reason_code="PAGINATION_INVALID",
                                  phase="pagination", field=field) from exc

    def _registration_records(
        self, subject: Subject, tool_name: str, content: dict[str, Any],
    ) -> list[ProviderRecord]:
        """把工商登记的多源对象合并成一条记录，保留认缴与实缴原字段。"""
        self._reject_warnings(content)
        if content.get("_empty") is True:
            return []
        if content.get("items") == [] and content.get("total") == 0:
            return []
        sources = content.get("sources")
        if not isinstance(sources, dict) or not sources:
            raise _provider_error("UPSTREAM_INVALID", False, reason_code="RESPONSE_INVALID",
                                  phase="response", field="sources", tool_name=tool_name)
        for source in sources.values():
            if not isinstance(source, dict):
                raise _provider_error("UPSTREAM_INVALID", False, reason_code="RESPONSE_INVALID",
                                      phase="response", field="sources", tool_name=tool_name)
            self._reject_warnings(source)
        if all(
            isinstance(value, dict) and (value.get("empty") is True or value.get("_empty") is True)
            for value in sources.values()
        ):
            return []
        return [self._make_record(subject, tool_name, {"sources": sources}, nested_metadata=True)]

    def _make_record(
        self, subject: Subject, tool_name: str, raw: dict[str, Any], *, nested_metadata: bool,
    ) -> ProviderRecord:
        """生成稳定记录并移除提供方评分和联系方式，不截断正文。"""
        credit_raw = self._find_value(raw, _CREDIT_KEYS, recursive=nested_metadata)
        credit_code: CreditCode | None = None
        if credit_raw not in (None, ""):
            try:
                credit_code = CreditCode(str(credit_raw).strip())
            except ValidationError as exc:
                raise _provider_error("UPSTREAM_INVALID", False, reason_code="RECORD_INVALID",
                                      phase="record", field="record_credit_code", tool_name=tool_name) from exc
            if credit_code.root != subject.credit_code.root:
                raise _provider_error("SUBJECT_RESPONSE_MISMATCH", False, reason_code="SUBJECT_MISMATCH",
                                      phase="record", field="record_credit_code", tool_name=tool_name)

        cleaned = self._clean_value(raw)
        if not isinstance(cleaned, dict) or not cleaned:
            raise _provider_error("UPSTREAM_INVALID", False, reason_code="RECORD_INVALID",
                                  phase="record", field="content", tool_name=tool_name)
        content = json.dumps(
            {"tool": tool_name, "data": cleaned}, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        if len(content) > 4000:
            raise _provider_error("UPSTREAM_INCOMPLETE", False, reason_code="CONTENT_LIMIT_EXCEEDED",
                                  phase="record", field="content", tool_name=tool_name,
                                  actual_count=len(content), limit_count=4000)

        explicit_id = self._find_value(raw, _ID_KEYS, recursive=nested_metadata)
        canonical = json.dumps(cleaned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        suffix = str(explicit_id).strip() if explicit_id not in (None, "") else hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()[:32]
        namespace = tool_name
        if isinstance(raw, _SourceItem):
            # 聚合来源的ID仅在各自来源内唯一；同一来源的真实重复仍交给批次校验拒绝。
            source_digest = hashlib.sha256(raw.source_name.encode("utf-8")).hexdigest()[:16]
            namespace = f"{tool_name}:source-{source_digest}"
        record_id = f"{namespace}:{suffix}"
        if len(record_id) > 256:
            identity = f"{namespace}:{canonical}"
            record_id = f"{tool_name}:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"

        event_time = self._small_text(self._find_value(raw, _TIME_KEYS, recursive=nested_metadata), field="event_time")
        source_url = self._small_text(self._find_value(raw, _URL_KEYS, recursive=nested_metadata), 2048, field="source_url")
        publisher = self._small_text(self._find_value(raw, _PUBLISHER_KEYS, recursive=nested_metadata), field="source_publisher")
        try:
            return ProviderRecord(
                record_id=record_id,
                content=content,
                record_credit_code=None if credit_code is None else credit_code.root,
                event_time=event_time,
                source_url=source_url,
                source_publisher=publisher,
            )
        except ValidationError as exc:
            location = exc.errors(include_input=False)[0]["loc"]
            field = str(location[0]) if location and location[0] in (
                "record_id", "content", "record_credit_code", "event_time", "source_url", "source_publisher",
            ) else None
            raise _provider_error("UPSTREAM_INVALID", False, reason_code="RECORD_INVALID",
                                  phase="record", field=field, tool_name=tool_name) from exc

    def _clean_value(self, value: Any) -> Any:
        """递归清理评分、评级和联系方式字段，其他公开事实保持原样。"""
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, child in value.items():
                normalized = "".join(character for character in str(key).lower() if character.isalnum())
                if str(key).startswith("_") or any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                    continue
                cleaned[str(key)] = self._clean_value(child)
            return cleaned
        if isinstance(value, list):
            return [self._clean_value(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise _provider_error("UPSTREAM_INVALID", False)

    def _find_value(self, value: Any, keys: tuple[str, ...], *, recursive: bool) -> Any:
        """按确定字段优先级取元数据；仅工商聚合对象允许向下查找。"""
        if not isinstance(value, dict):
            return None
        for key in keys:
            if value.get(key) not in (None, ""):
                return value[key]
        if recursive:
            for child in value.values():
                found = self._find_value(child, keys, recursive=True)
                if found not in (None, ""):
                    return found
        return None

    def _reject_warnings(self, value: Any) -> None:
        """任何非空上游警告都视为未完整取得。"""
        if not isinstance(value, dict):
            return
        warnings = value.get("_warnings")
        if warnings not in (None, "", []):
            raise _provider_error("UPSTREAM_INCOMPLETE", False, reason_code="UPSTREAM_WARNING",
                                  phase="response")

    def _small_text(self, value: Any, maximum: int = 256, *, field: str | None = None) -> str | None:
        """把可选元数据规范化为受限非空文本，拒绝静默截断。"""
        if value in (None, ""):
            return None
        text = str(value).strip()
        if not text:
            return None
        if len(text) > maximum:
            raise _provider_error("UPSTREAM_INVALID", False, reason_code="RECORD_INVALID",
                                  phase="record", field=field)
        return text
