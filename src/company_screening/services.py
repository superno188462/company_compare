"""BE-IF-02：应用服务骨架；所有业务方法尚未实现。"""

from uuid import UUID

from .contracts.boundary import (
    ActorContext, ConfirmSubjectCommand, EditableDraft, ManualDraft, OperationHandle,
    OperationView, RetryAnalysisCommand, RetryQueryCommand, SearchCommand, SearchResult,
    SessionExpiry, SubmitEvidenceCommand, WithdrawalResult, WorkspaceState,
)


class SessionService:
    """会话创建、恢复、续期和结束边界；不在此阶段实现权限或存储。"""

    def create(self, actor: ActorContext) -> WorkspaceState:
        """BE-IF-01 / DATA-05：显式创建私有会话。"""
        raise NotImplementedError()

    def restore(self, actor: ActorContext, sid: UUID) -> WorkspaceState:
        """BE-IF-01 / DATA-05：恢复状态；读取不续期。"""
        raise NotImplementedError()

    def activity(self, actor: ActorContext, sid: UUID) -> SessionExpiry:
        """BE-NFR-02：只为明确用户活动续期。"""
        raise NotImplementedError()

    def reset(self, actor: ActorContext, sid: UUID, key: UUID) -> None:
        """DATA-05：结束当前会话，使迟到写回失效。"""
        raise NotImplementedError()


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
