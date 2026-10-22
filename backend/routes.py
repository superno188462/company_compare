"""BE-IF-01：13个 HTTP 路由声明，处理函数统一保持未实现。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from company_screening.contracts.base import ContractModel
from company_screening.contracts.boundary import (
    ActorContext, ConfirmSubjectCommand, EditableDraft, ManualDraft, OperationHandle,
    OperationView, RetryAnalysisCommand, RetryQueryCommand, SearchCommand, SearchResult,
    SessionExpiry, SubmitEvidenceCommand, WithdrawalResult, WorkspaceState,
)

from .dependencies import get_actor

router = APIRouter(prefix="/api/v1", tags=["企业公开线索筛查"])
TrustedActor = Annotated[ActorContext, Depends(get_actor)]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key", description="同次操作重试沿用原UUID，不能同键更改内容。")]


class EmptyBody(ContractModel):
    """规格中规定的空对象请求，不接收额外业务字段。"""


@router.post("/sessions", response_model=WorkspaceState, status_code=201, summary="显式创建会话", description="BE-IF-01：建立私有工作台，不运行企业查询或分析。")
def create_session(actor: TrustedActor, key: IdempotencyKey) -> WorkspaceState:
    """创建会话边界；所有者及幂等处理尚未实现。"""
    raise NotImplementedError()


@router.get("/sessions/{sid}", response_model=WorkspaceState, summary="恢复会话", description="读取不续期，只能恢复当前所有者的有效会话。")
def restore_session(sid: UUID, actor: TrustedActor) -> WorkspaceState:
    """BE-IF-01 / DATA-05。"""
    raise NotImplementedError()


@router.post("/sessions/{sid}/activity", response_model=SessionExpiry, summary="记录明确用户活动", description="后台轮询不能调用此能力为会话续期。")
def notify_activity(sid: UUID, body: EmptyBody, actor: TrustedActor) -> SessionExpiry:
    """BE-NFR-02：活动续期占位。"""
    raise NotImplementedError()


@router.delete("/sessions/{sid}", status_code=204, response_model=None, summary="结束本次会话", description="清理私有状态并使迟到写回失效；不默认撤回已共享记录。")
def reset_session(sid: UUID, actor: TrustedActor, key: IdempotencyKey) -> None:
    """DATA-05：会话结束占位。"""
    raise NotImplementedError()


@router.post("/sessions/{sid}/search", response_model=SearchResult, summary="搜索候选企业", description="BE-IF-03：单候选也不自动确认。")
def search_companies(sid: UUID, command: SearchCommand, actor: TrustedActor, key: IdempotencyKey) -> SearchResult:
    """只搜索候选；未实现。"""
    raise NotImplementedError()


@router.post("/sessions/{sid}/confirm", response_model=OperationHandle, status_code=202, summary="确认用户选定的主体", description="明确选择后才启动资料查询的长任务。")
def confirm_subject(sid: UUID, command: ConfirmSubjectCommand, actor: TrustedActor, key: IdempotencyKey) -> OperationHandle:
    """BE-IF-03：主体确认占位。"""
    raise NotImplementedError()


@router.put("/sessions/{sid}/draft", response_model=ManualDraft, summary="保存待修改草稿", description="BE-IF-04：草稿保存不接纳证据、不触发LLM。")
def save_draft(sid: UUID, draft: EditableDraft, actor: TrustedActor, key: IdempotencyKey) -> ManualDraft:
    """草稿保存占位。"""
    raise NotImplementedError()


@router.delete("/sessions/{sid}/draft", status_code=204, response_model=None, summary="清空草稿", description="明确清空内容及快照来源关联。")
def clear_draft(sid: UUID, actor: TrustedActor, key: IdempotencyKey) -> None:
    """BE-IF-04：草稿清空占位。"""
    raise NotImplementedError()


@router.post("/sessions/{sid}/evidence", response_model=OperationHandle, status_code=202, summary="提交线索并自动分析", description="校验服务端草稿、主体、知情确认与共享同意。")
def submit_evidence(sid: UUID, command: SubmitEvidenceCommand, actor: TrustedActor, key: IdempotencyKey) -> OperationHandle:
    """BE-IF-04：接纳与自动分析占位。"""
    raise NotImplementedError()


@router.post("/sessions/{sid}/analysis/retry", response_model=OperationHandle, status_code=202, summary="重新分析当前版本", description="不重复接纳或共享线索，空证据不调用LLM。")
def retry_analysis(sid: UUID, command: RetryAnalysisCommand, actor: TrustedActor, key: IdempotencyKey) -> OperationHandle:
    """BE-IF-05：显式分析重试占位。"""
    raise NotImplementedError()


@router.post("/sessions/{sid}/queries/retry", response_model=OperationHandle, status_code=202, summary="重试失败查询类别", description="仅原计划内失败类别可重试，不暗中扩大或缩小范围。")
def retry_queries(sid: UUID, command: RetryQueryCommand, actor: TrustedActor, key: IdempotencyKey) -> OperationHandle:
    """BE-IF-03/05：分类重试占位。"""
    raise NotImplementedError()


@router.get("/sessions/{sid}/operations/{opid}", response_model=OperationView, summary="查看操作状态", description="只读进度或完整终态，不续期、不返回半段报告。")
def get_operation(sid: UUID, opid: UUID, actor: TrustedActor) -> OperationView:
    """BE-IF-06：任务状态读取占位。"""
    raise NotImplementedError()


@router.post("/shares/{receipt_id}/withdraw", response_model=WithdrawalResult, summary="撤回自己的共享", description="验证提交者所有权，重复撤回幂等；回执本身不是授权凭据。")
def withdraw_share(receipt_id: UUID, body: EmptyBody, actor: TrustedActor, key: IdempotencyKey) -> WithdrawalResult:
    """DATA-04：共享撤回占位。"""
    raise NotImplementedError()
