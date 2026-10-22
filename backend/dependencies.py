"""HTTP 所有者验证依赖骨架，不读取客户端自报 actor_id。"""

from company_screening.contracts.boundary import ActorContext
from fastapi import Request


def get_actor(request: Request) -> ActorContext:
    """BE-NFR-03 / DATA-05：验证 Cookie 后创建上下文，尚未实现。"""
    raise NotImplementedError()
