"""组合根骨架；导入此模块不会创建客户端、数据库或启动服务。"""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """BE-IF-01：待实现的应用装配入口，不在骨架阶段注册真实依赖。"""
    raise NotImplementedError()
