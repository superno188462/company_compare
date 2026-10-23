"""BE-ERR-01：HTTP错误包与固定文案键，不回显原始输入或异常详情。"""
import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import Response

from company_screening.contracts.boundary import (
    ErrorEnvelope, ErrorInfo, FieldIssue, ValidationMessageKey,
)
from company_screening.contracts.generated import HintCode
from company_screening.errors import ApplicationError

ERROR_STATUS = {
    "INPUT_INVALID": 422, "SUBJECT_UNCONFIRMED": 409, "CANDIDATE_INVALID": 409,
    "CREDIT_MISSING": 422, "CREDIT_MISMATCH": 422, "CREDIT_CONFLICT": 422,
    "SNAPSHOT_CONFIRM_REQUIRED": 422, "SNAPSHOT_UNAVAILABLE": 409, "SHARE_REQUIREMENTS": 422,
    "SESSION_EXPIRED": 410, "RESOURCE_NOT_FOUND": 404, "OPERATION_CONFLICT": 409,
    "IDEMPOTENCY_CONFLICT": 409, "UPSTREAM_TIMEOUT": 504, "UPSTREAM_AUTH": 502,
    "UPSTREAM_LIMIT": 503, "UPSTREAM_ERROR": 502, "UPSTREAM_INVALID": 502,
    "UPSTREAM_INCOMPLETE": 502, "SUBJECT_RESPONSE_MISMATCH": 502,
    "INPUT_TOO_LARGE": 422, "STORAGE_UNAVAILABLE": 503, "INTERNAL_ERROR": 500,
}


def validation_error(request: Request, exc: Exception) -> JSONResponse:
    """422只返回字段位置和字典键；缺少专用提示时使用TEXT-1.1通用键。"""
    assert isinstance(exc, RequestValidationError)
    fields: list[FieldIssue] = []
    for issue in exc.errors():
        location = tuple(issue.get("loc", ()))
        parts = location[1:] if location and location[0] in {"body", "query", "path", "header", "cookie"} else location
        field = ".".join(str(part) for part in parts) or "body"
        key: ValidationMessageKey = "input_invalid"
        if field == "query":
            if issue["type"] in {"missing", "string_too_short"}:
                key = "company_name_required"
            elif issue["type"] == "string_too_long":
                key = "company_name_length"
        elif field == "content":
            if issue["type"] == "string_too_long":
                key = "content_length"
            elif issue["type"] in {"missing", "string_too_short"}:
                key = "content_required"
        item = FieldIssue(field=field, message_key=key)
        if item not in fields:
            fields.append(item)
    body = ErrorEnvelope(error=ErrorInfo(code="INPUT_INVALID", hint_id=HintCode.LIMIT_EXCEEDED,
                                        fields=fields, retryable=False), operation_id=None)
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))


def application_error(request: Request, exc: Exception) -> JSONResponse:
    """按BE-ERR-01映射状态，只传播应用已脱敏的结构，不读取异常文本。"""
    assert isinstance(exc, ApplicationError)
    body = ErrorEnvelope(error=exc.info, operation_id=None)
    return JSONResponse(status_code=ERROR_STATUS[exc.info.code], content=body.model_dump(mode="json"))


def internal_error(request: Request, exc: Exception) -> JSONResponse:
    """未分类异常只记录诊断编号；响应、日志均不包含异常正文或请求内容。"""
    logging.getLogger(__name__).error("unhandled_request diagnostic_id=%s", uuid4())
    body = ErrorEnvelope(error=ErrorInfo(code="INTERNAL_ERROR", hint_id=HintCode.INTERNAL_ERROR,
                                        fields=[], retryable=False), operation_id=None)
    return JSONResponse(status_code=500, content=body.model_dump(mode="json"))


async def sanitize_unhandled(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """在服务器异常日志层之前收敛未处理异常，防止异常正文写入访问日志。"""
    try:
        return await call_next(request)
    except Exception as exc:
        return internal_error(request, exc)
