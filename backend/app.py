"""开发阶段HTTP组合根；导入不启动服务或连接外部提供方。"""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from company_screening.contracts.boundary import ErrorEnvelope
from company_screening.errors import ApplicationError

from .error_handlers import application_error, internal_error, sanitize_unhandled, validation_error
from .routes import router


def create_app() -> FastAPI:
    """BE-IF-01/ERR-01：装配现有路由和错误包，业务接口仍处于开发阶段。"""
    app = FastAPI(
        title="企业公开线索筛查 API", version="0.1.0",
        description="开发中的接口契约。会话HTTP、身份验证、企业查询和分析尚未接通；文档可见不代表接口已可用。",
    )
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(ApplicationError, application_error)
    app.add_exception_handler(Exception, internal_error)
    app.middleware("http")(sanitize_unhandled)
    app.include_router(router, responses={
        status: {"model": ErrorEnvelope, "description": "脱敏的应用错误；文案由hint_id及字段键定位。"}
        for status in (404, 409, 410, 422, 500, 502, 503, 504)
    })
    return app
