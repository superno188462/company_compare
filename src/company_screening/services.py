"""BE-IF-02：应用服务；会话逐步实现，其余方法仍为占位。"""

from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import ClassVar
from uuid import UUID, uuid4

from .contracts.boundary import (
    ActorContext, ConfirmSubjectCommand, EditableDraft, ManualDraft, OperationHandle,
    ErrorInfo, OperationView, RetryAnalysisCommand, RetryQueryCommand, SearchCommand, SearchResult,
    SessionExpiry, SubmitEvidenceCommand, WithdrawalResult, WorkspaceState,
)
from .errors import ApplicationError
from .contracts.generated import HintCode


class SessionService:
    """会话边界；首个开发切片使用进程内存，尚不具备重启持久化能力。"""

    _sessions: ClassVar[dict[UUID, tuple[UUID, WorkspaceState]]] = {}
    _ended: ClassVar[dict[UUID, UUID]] = {}
    _lock: ClassVar[RLock] = RLock()

    def create(self, actor: ActorContext) -> WorkspaceState:
        """BE-IF-01 / DATA-05：显式创建私有会话。"""
        state = WorkspaceState(
            session_id=uuid4(), expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            session_generation=0, current_subject=None, payload=None, draft=None,
            active_operation=None, share_receipts=[],
        )
        with self._lock:
            self._sessions[state.session_id] = (actor.actor_id, state.model_copy(deep=True))
        return state

    def restore(self, actor: ActorContext, sid: UUID) -> WorkspaceState:
        """BE-IF-01 / DATA-05：恢复状态；读取不续期。"""
        with self._lock:
            entry = self._sessions.get(sid)
            if entry is not None and entry[0] == actor.actor_id:
                state = entry[1]
                if datetime.now(timezone.utc) < state.expires_at:
                    # 返回独立副本，调用者不能绕过服务修改已保存状态。
                    return state.model_copy(deep=True)
                del self._sessions[sid]
                self._ended[sid] = actor.actor_id
            if self._ended.get(sid) == actor.actor_id:
                info = ErrorInfo(code="SESSION_EXPIRED", hint_id=HintCode.SESSION_EXPIRED,
                                 fields=[], retryable=False)
            else:
                info = ErrorInfo(code="RESOURCE_NOT_FOUND", hint_id=HintCode.INTERNAL_ERROR,
                                 fields=[], retryable=False)
            error = ApplicationError(info.code)
            error.info = info
            raise error

    def activity(self, actor: ActorContext, sid: UUID) -> SessionExpiry:
        """BE-NFR-02：只为明确用户活动续期。"""
        raise NotImplementedError()

    def reset(self, actor: ActorContext, sid: UUID, key: UUID) -> None:
        """DATA-05：结束当前会话，使迟到写回失效。"""
        with self._lock:
            # 重复结束本人会话保持幂等；结束标记不含正文、草稿或报告。
            if self._ended.get(sid) == actor.actor_id:
                return
            self.restore(actor, sid)
            del self._sessions[sid]
            self._ended[sid] = actor.actor_id


class ScreeningService:
    """搜索、证据提交和受控报告工作流边界。"""

    def search(self, actor: ActorContext, sid: UUID, command: SearchCommand, key: UUID) -> SearchResult:
        """BE-IF-03：仅返回候选，不自动确认。"""
        raise NotImplementedError()

    def confirm(self, actor: ActorContext, sid: UUID, command: ConfirmSubjectCommand, key: UUID) -> OperationHandle:
        """BE-IF-03：人工确认后才开始详情流水线。"""
        raise NotImplementedError()

    def save_draft(self, actor: ActorContext, sid: UUID, draft: EditableDraft, key: UUID) -> ManualDraft:
        """BE-IF-04：保存草稿，不接纳证据或调用模型。"""
        raise NotImplementedError()

    def clear_draft(self, actor: ActorContext, sid: UUID, key: UUID) -> None:
        """BE-IF-04：明确清空当前草稿及其预填充关联。"""
        raise NotImplementedError()

    def submit(self, actor: ActorContext, sid: UUID, command: SubmitEvidenceCommand, key: UUID) -> OperationHandle:
        """BE-IF-04：校验后接纳、按同意范围共享并自动分析。"""
        raise NotImplementedError()

    def retry_analysis(self, actor: ActorContext, sid: UUID, command: RetryAnalysisCommand, key: UUID) -> OperationHandle:
        """BE-IF-05：仅重新分析当前版本，不重复录入。"""
        raise NotImplementedError()

    def retry_queries(self, actor: ActorContext, sid: UUID, command: RetryQueryCommand, key: UUID) -> OperationHandle:
        """BE-IF-03/05：仅重试原计划中的失败类别。"""
        raise NotImplementedError()

    def operation(self, actor: ActorContext, sid: UUID, opid: UUID) -> OperationView:
        """BE-IF-06：只读进度或完整终态，不续期。"""
        raise NotImplementedError()


class ShareService:
    """共享回执所有权与撤回边界。"""

    def withdraw(self, actor: ActorContext, receipt_id: UUID, key: UUID) -> WithdrawalResult:
        """DATA-04 / BE-IF-04：本人撤回，重复请求保持幂等。"""
        raise NotImplementedError()
