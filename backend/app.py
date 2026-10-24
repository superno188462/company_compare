"""开发阶段HTTP组合根；导入不启动服务或连接外部提供方。"""

import os
import secrets
import hashlib
from pathlib import Path
from threading import RLock

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from company_screening.adapters.tianyan_mcp import TianyanMcpAdapter
from company_screening.collections import CollectionService
from company_screening.adapters.collection_sqlite import SqliteCollectionStore
from company_screening.contracts.boundary import ErrorEnvelope
from company_screening.errors import ApplicationError
from company_screening.services import ScreeningService, SessionService

from .error_handlers import application_error, internal_error, sanitize_unhandled, validation_error
from .routes import router
from .collection_routes import router as collection_router


def create_app(
    *,
    screening_service: ScreeningService | None = None,
    session_service: SessionService | None = None,
    collection_service: CollectionService | None = None,
) -> FastAPI:
    """BE-IF-01/ERR-01：装配路由、错误包和可替换的企业搜索服务。"""
    load_dotenv(override=False)
    session_service = session_service or SessionService()
    if screening_service is None:
        authorization = os.getenv("TYC_AUTHORIZATION", "").strip()
        company_data = None
        if authorization:
            company_data = TianyanMcpAdapter(
                authorization,
                core_url=os.getenv(
                    "TYC_CORE_ENDPOINT",
                    "https://mcp.tianyancha.com/v1/core/tools/call",
                ),
            )
        if collection_service is None:
            core_endpoint = os.getenv("TYC_CORE_ENDPOINT", "https://mcp.tianyancha.com/v1/core/tools/call")
            scope = hashlib.sha256((authorization + "\n" + core_endpoint + "\n" +
                os.getenv("COLLECTION_SCOPE_VERSION", "1")).encode("utf-8")).hexdigest()
            store = SqliteCollectionStore(Path(os.getenv("COLLECTION_DATABASE_PATH",
                str(Path(__file__).resolve().parents[1] / ".local" / "collections.sqlite3"))))
            collection_service = CollectionService(session_service=session_service, company_data=company_data,
                                                    store=store, scope_id=scope)
        screening_service = ScreeningService(
            session_service=session_service,
            company_data=company_data,
            collection_service=collection_service,
        )
    app = FastAPI(
        title="企业公开线索筛查 API", version="0.1.0",
        description="会话、候选搜索、人工确认、五类查询、失败重试、诊断及私人线索接纳已接通。API资料持久化并跨用户复用，可按工具浏览、加载下一页和主动更新；私人线索共享发布和真实模型分析仍在开发。",
    )
    app.state.screening_service = screening_service
    app.state.session_service = session_service
    if collection_service is not None:
        app.state.collection_service = collection_service
    cookie_secret = os.getenv("APP_COOKIE_SECRET", "")
    app.state.cookie_secret = cookie_secret.encode("utf-8") if cookie_secret else secrets.token_bytes(32)
    app.state.cookie_secure = os.getenv("APP_COOKIE_SECURE", "false").lower() == "true"
    app.state.session_create_idempotency = {}
    app.state.session_create_lock = RLock()
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(ApplicationError, application_error)
    app.add_exception_handler(Exception, internal_error)
    app.middleware("http")(sanitize_unhandled)
    app.include_router(router, responses={
        status: {"model": ErrorEnvelope, "description": "脱敏的应用错误；文案由hint_id及字段键定位。"}
        for status in (404, 409, 410, 422, 500, 502, 503, 504)
    })
    if collection_service is not None:
        app.include_router(collection_router)
    return app
