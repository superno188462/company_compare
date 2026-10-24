"""COL-IF-01：材料只读浏览、指定司法页采集和主动更新的HTTP边界。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request

from company_screening.collections import CollectionService
from company_screening.contracts.boundary import ErrorEnvelope, OperationHandle
from company_screening.errors import ApplicationError
from company_screening.contracts.boundary import ErrorInfo
from company_screening.contracts.generated import HintCode
from company_screening.contracts.generated import (
    CollectionOperationView, CollectionOverview, CollectionRecordsPage, CollectionToolName,
    LoadCollectionPageCommand, RefreshCollectionToolCommand,
)

from .routes import IdempotencyKey, TrustedActor

router = APIRouter(prefix="/api/v1", tags=["企业API材料浏览"], responses={
    status: {"model": ErrorEnvelope, "description": "安全应用错误；hint_id定位固定文案，不含第三方原文。"}
    for status in (404, 409, 410, 422, 500, 503)
})
CollectionSessionId = Annotated[UUID, Path(description="当前所有者已确认主体的会话定位，不是授权凭据。")]
CollectionOperationId = Annotated[UUID, Path(description="本会话采集任务定位，不允许读取其他用户任务。")]


def get_collection_service(request: Request) -> CollectionService:
    """COL-IF-02：读取组合根注入的服务；不在路由创建数据库或客户端。"""
    service: CollectionService = request.app.state.collection_service
    return service


Collections = Annotated[CollectionService, Depends(get_collection_service)]


def _check_write(request: Request) -> None:
    """COL-NFR-07：只接受同源写操作，不依赖浏览器Cookie策略代替服务端检查。"""
    origin = request.headers.get("origin")
    if (origin is not None and origin.rstrip("/") != str(request.base_url).rstrip("/")) or request.headers.get("sec-fetch-site") == "cross-site":
        error = ApplicationError("INPUT_INVALID")
        error.info = ErrorInfo(code="INPUT_INVALID", hint_id=HintCode.INTERNAL_ERROR, fields=[], retryable=False)
        raise error


@router.get("/sessions/{sid}/collections", response_model=CollectionOverview,
            summary="读取已收集API材料概览", description="COL-IF-01：固定批次的原取得时间与覆盖；不取上游，不续期，不生成报告。")
def get_collections(sid: CollectionSessionId, actor: TrustedActor, service: Collections) -> CollectionOverview:
    """COL-IF-01：本会话已确认主体的公共API资料视图。"""
    return service.overview(actor, sid)


@router.get("/sessions/{sid}/collections/{tool_name}/records", response_model=CollectionRecordsPage,
            summary="读取已保存材料的展示页", description="COL-IF-01：仅当前绑定批次，每页20条；不请求上游。")
def get_collection_records(
    sid: CollectionSessionId,
    tool_name: Annotated[CollectionToolName, Path(description="固定计划中的工具名，不接受任意代理工具。")],
    actor: TrustedActor, service: Collections,
    batch_id: Annotated[UUID, Query(description="当前工作台绑定的成功采集批次，不是授权凭据。")],
    page: Annotated[int, Query(ge=1, description="本地材料展示页，从1开始；不是上游页码。")] = 1,
) -> CollectionRecordsPage:
    """COL-IF-01/04：固定20条的本地只读分页。"""
    return service.records(actor, sid, tool_name, batch_id, page=page)


@router.post("/sessions/{sid}/collections/pages", response_model=OperationHandle, status_code=202,
             summary="继续取得所选司法工具下一页", description="COL-IF-04：已存页直接复用，缺页才取上游；不改变报告或草稿。")
def load_collection_page(
    request: Request, sid: CollectionSessionId, command: LoadCollectionPageCommand, actor: TrustedActor,
    key: IdempotencyKey, service: Collections,
) -> OperationHandle:
    """COL-IF-04/06：只启动指定连续页的幂等任务。"""
    _check_write(request)
    return service.load_page(actor, sid, command, key)


@router.post("/sessions/{sid}/collections/refresh", response_model=OperationHandle, status_code=202,
             summary="主动更新单个工具资料", description="COL-IF-05：成功建立新批次，失败保留旧材料；不是重新分析。")
def refresh_collection_tool(
    request: Request, sid: CollectionSessionId, command: RefreshCollectionToolCommand, actor: TrustedActor,
    key: IdempotencyKey, service: Collections,
) -> OperationHandle:
    """COL-IF-05/06：显式绕过所选工具缓存，保留旧报告原文。"""
    _check_write(request)
    return service.refresh_tool(actor, sid, command, key)


@router.get("/sessions/{sid}/collection-operations/{opid}", response_model=CollectionOperationView,
            summary="查看本会话材料采集任务", description="COL-DATA-04：只读任务状态及完整终态，不共享任务或续期。")
def get_collection_operation(
    sid: CollectionSessionId, opid: CollectionOperationId, actor: TrustedActor, service: Collections,
) -> CollectionOperationView:
    """COL-IF-01：公共材料可复用，其他用户的任务不可读取。"""
    return service.operation(actor, sid, opid)
