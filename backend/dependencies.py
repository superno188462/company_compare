"""HTTP 所有者验证与应用服务依赖，不读取客户端自报 actor_id。"""

import hashlib
import hmac
from uuid import UUID, uuid4

from company_screening.contracts.boundary import ActorContext
from company_screening.services import ScreeningService, SessionService
from fastapi import Request, Response

OWNER_COOKIE = "company_screening_owner"


def get_actor(request: Request, response: Response) -> ActorContext:
    """BE-NFR-03 / DATA-05：验证签名Cookie，非法或缺失时签发新匿名所有者。"""
    secret: bytes = request.app.state.cookie_secret
    actor_id: UUID | None = None
    raw_cookie = request.cookies.get(OWNER_COOKIE)
    if raw_cookie:
        identifier, separator, signature = raw_cookie.partition(".")
        if separator:
            expected = hmac.new(secret, identifier.encode("ascii", errors="ignore"), hashlib.sha256).hexdigest()
            if hmac.compare_digest(signature, expected):
                try:
                    actor_id = UUID(identifier)
                except ValueError:
                    actor_id = None
    if actor_id is None:
        actor_id = uuid4()
        identifier = str(actor_id)
        signature = hmac.new(secret, identifier.encode("ascii"), hashlib.sha256).hexdigest()
        response.set_cookie(
            key=OWNER_COOKIE,
            value=f"{identifier}.{signature}",
            httponly=True,
            secure=request.app.state.cookie_secure,
            samesite="strict",
            path="/api/v1",
        )
    return ActorContext(actor_id=actor_id)


def get_screening_service(request: Request) -> ScreeningService:
    """从组合根取得同一进程内共享的搜索应用服务。"""
    service: ScreeningService = request.app.state.screening_service
    return service


def get_session_service(request: Request) -> SessionService:
    """从组合根取得会话服务，确保所有路由共享同一存储边界。"""
    service: SessionService = request.app.state.session_service
    return service
