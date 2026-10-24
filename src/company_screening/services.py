"""BE-IF-02：应用服务；会话、搜索、确认、分类查询编排与任务轮询已实现。"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import re
from threading import RLock
from typing import ClassVar, TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import AnyHttpUrl, ValidationError

from .contracts.boundary import (
    ActorContext, Candidate, ConfirmSubjectCommand, EditableDraft, FieldIssue, ManualDraft, OperationHandle,
    ErrorCode, ErrorInfo, OperationView, RetryAnalysisCommand, RetryQueryCommand, SearchCommand, SearchResult,
    SessionExpiry, SubmitEvidenceCommand, WithdrawalResult, WorkspaceState,
)
from .errors import ApplicationError, ProviderError, StorageError
from .contracts.generated import (
    Category, CategoryResults, HintCode, JudicialToolName, LlmStatus, NullableText,
    QueryDiagnostic, Subject, WorkflowPayload,
)
from .ports import CompanyDataPort

if TYPE_CHECKING:
    from .collections import CollectionService


CATEGORY_ERROR_SCOPE = {
    "basic": "工商登记、股东及出资计划查询未完整完成",
    "abnormal": "经营异常计划查询未完整完成",
    "penalty": "行政处罚计划查询未完整完成",
    "judicial": "失信、被执行、限高、司法案件、裁判文书及法院公告计划查询未完整完成",
    "asset": "股权冻结、司法协助、动产抵押及土地抵押计划查询未完整完成",
}


def _query_diagnostic(
    reason_code: str = "UNCLASSIFIED_FAILURE",
    phase: str = "unknown",
    *,
    field: str | None = None,
    actual_count: int | None = None,
    limit_count: int | None = None,
) -> QueryDiagnostic:
    """生成应用层已知原因；无提供方上下文时不猜HTTP状态或子工具。"""
    return QueryDiagnostic.model_validate({
        "diagnostic_id": uuid4(), "tool_name": None, "phase": phase,
        "reason_code": reason_code, "http_status": None, "field": field,
        "actual_count": actual_count, "limit_count": limit_count,
    })


class SessionService:
    """会话边界；首个开发切片使用进程内存，尚不具备重启持久化能力。"""

    _sessions: ClassVar[dict[UUID, tuple[UUID, WorkspaceState]]] = {}
    _ended: ClassVar[dict[UUID, UUID]] = {}
    _lock: ClassVar[RLock] = RLock()
    _collection_cleanup: Callable[[UUID], None] | None = None

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
        if info.code == "SESSION_EXPIRED" and self._collection_cleanup is not None:
            self._collection_cleanup(sid)
        raise error

    def activity(self, actor: ActorContext, sid: UUID) -> SessionExpiry:
        """BE-NFR-02：只为明确用户活动续期。"""
        with self._lock:
            entry = self._sessions.get(sid)
            now = datetime.now(timezone.utc)
            if entry is not None and entry[0] == actor.actor_id:
                state = entry[1]
                if now < state.expires_at:
                    renewed = state.model_copy(update={"expires_at": now + timedelta(hours=24)})
                    self._sessions[sid] = (actor.actor_id, renewed)
                    return SessionExpiry(expires_at=renewed.expires_at)
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

    def reset(self, actor: ActorContext, sid: UUID, key: UUID) -> None:
        """DATA-05：结束当前会话，使迟到写回失效。"""
        with self._lock:
            # 重复结束本人会话保持幂等；结束标记不含正文、草稿或报告。
            if self._ended.get(sid) == actor.actor_id:
                return
            self.restore(actor, sid)
            del self._sessions[sid]
            self._ended[sid] = actor.actor_id
        if self._collection_cleanup is not None:
            self._collection_cleanup(sid)

    def _confirm_subject(
        self,
        actor: ActorContext,
        sid: UUID,
        subject: Subject,
        expected_generation: int,
        discard_draft: bool,
        operation_id: UUID,
    ) -> OperationHandle:
        """在会话锁内校验代次并原子替换主体上下文。"""
        with self._lock:
            entry = self._sessions.get(sid)
            if entry is None or entry[0] != actor.actor_id:
                info = ErrorInfo(code="RESOURCE_NOT_FOUND", hint_id=HintCode.INTERNAL_ERROR,
                                 fields=[], retryable=False)
                error = ApplicationError(info.code)
                error.info = info
                raise error
            state = entry[1]
            if state.session_generation != expected_generation:
                info = ErrorInfo(code="OPERATION_CONFLICT", hint_id=HintCode.OPERATION_CONFLICT,
                                 fields=[], retryable=False)
                error = ApplicationError(info.code)
                error.info = info
                raise error
            if state.draft is not None and not discard_draft:
                info = ErrorInfo(code="OPERATION_CONFLICT", hint_id=HintCode.OPERATION_CONFLICT,
                                 fields=[], retryable=False)
                error = ApplicationError(info.code)
                error.info = info
                raise error

            handle = OperationHandle(
                operation_id=operation_id,
                session_id=sid,
                session_generation=state.session_generation + 1,
            )
            updated = state.model_copy(update={
                "session_generation": handle.session_generation,
                "current_subject": subject,
                "payload": None,
                "draft": None,
                "active_operation": handle,
            })
            self._sessions[sid] = (actor.actor_id, updated)
            return handle

    def _begin_query_retry(
        self,
        actor: ActorContext,
        sid: UUID,
        command: RetryQueryCommand,
        operation_id: UUID,
    ) -> tuple[OperationHandle, Subject]:
        """原子接纳失败类别重试；保留原结果、草稿及本代次主体。"""
        with self._lock:
            state = self.restore(actor, sid)
            code: ErrorCode | None = None
            hint = HintCode.OPERATION_CONFLICT
            fields: list[FieldIssue] = []
            if state.current_subject is None:
                code, hint = "SUBJECT_UNCONFIRMED", HintCode.CONFIRM_SUBJECT
            elif (
                state.session_generation != command.expected_generation
                or state.payload is None or state.active_operation is not None
            ):
                code = "OPERATION_CONFLICT"
            elif (
                len(set(command.categories)) != len(command.categories)
                or any(
                    category not in state.payload.api_status.planned_categories.root
                    or getattr(state.payload.api_status.categories, category.value).root.status not in ("error", "partial")
                    for category in command.categories
                )
            ):
                code, hint = "INPUT_INVALID", HintCode.LIMIT_EXCEEDED
                fields = [FieldIssue(field="categories", message_key="input_invalid")]
            if code:
                info = ErrorInfo(code=code, hint_id=hint, fields=fields, retryable=False)
                error = ApplicationError(info.code)
                error.info = info
                raise error
            assert state.current_subject is not None
            handle = OperationHandle(
                operation_id=operation_id, session_id=sid,
                session_generation=state.session_generation,
            )
            self._sessions[sid] = (actor.actor_id, state.model_copy(update={"active_operation": handle}))
            return handle, state.current_subject

    def _begin_collection(
        self, actor: ActorContext, sid: UUID, generation: int, operation_id: UUID,
    ) -> OperationHandle:
        """COL-IF-06：浏览写任务与报告任务使用同一会话互斥守卫。"""
        with self._lock:
            state = self.restore(actor, sid)
            if state.session_generation != generation or state.active_operation is not None:
                info = ErrorInfo(code="OPERATION_CONFLICT", hint_id=HintCode.OPERATION_CONFLICT, fields=[], retryable=False)
                error = ApplicationError(info.code)
                error.info = info
                raise error
            handle = OperationHandle(operation_id=operation_id, session_id=sid, session_generation=generation)
            self._sessions[sid] = (actor.actor_id, state.model_copy(update={"active_operation": handle}))
            return handle

    def _finish_collection(self, actor: ActorContext, handle: OperationHandle) -> None:
        """COL-IF-06：只释放当前代次本浏览任务，不改报告、证据或新草稿。"""
        with self._lock:
            try:
                state = self.restore(actor, handle.session_id)
            except ApplicationError:
                return
            if (state.session_generation == handle.session_generation and state.active_operation is not None
                    and state.active_operation.operation_id == handle.operation_id):
                self._sessions[handle.session_id] = (actor.actor_id, state.model_copy(update={"active_operation": None}))

    def _complete_operation(
        self,
        actor: ActorContext,
        handle: OperationHandle,
        payload: WorkflowPayload,
    ) -> bool:
        """仅当会话、代次和活动任务仍匹配时写入完整终态。"""
        with self._lock:
            try:
                self.restore(actor, handle.session_id)
            except ApplicationError:
                return False
            entry = self._sessions.get(handle.session_id)
            if entry is None or entry[0] != actor.actor_id:
                return False
            state = entry[1]
            if (
                state.session_generation != handle.session_generation
                or state.active_operation is None
                or state.active_operation.operation_id != handle.operation_id
            ):
                return False
            updated = state.model_copy(update={"payload": payload, "active_operation": None})
            self._sessions[handle.session_id] = (actor.actor_id, updated)
            return True

    def _save_draft(
        self,
        actor: ActorContext,
        sid: UUID,
        draft: EditableDraft,
    ) -> ManualDraft:
        """在会话锁内保存私有草稿；草稿不进入证据或报告。"""
        with self._lock:
            entry = self._sessions.get(sid)
            if entry is None or entry[0] != actor.actor_id:
                info = ErrorInfo(code="RESOURCE_NOT_FOUND", hint_id=HintCode.INTERNAL_ERROR,
                                 fields=[], retryable=False)
                error = ApplicationError(info.code)
                error.info = info
                raise error
            state = entry[1]
            if state.current_subject is None:
                info = ErrorInfo(code="SUBJECT_UNCONFIRMED", hint_id=HintCode.CONFIRM_SUBJECT,
                                 fields=[], retryable=False)
                error = ApplicationError(info.code)
                error.info = info
                raise error

            source_url = draft.source_url
            if source_url is not None and not source_url.strip():
                source_url = None
            normalized = draft.model_copy(update={"source_url": source_url})
            code = (draft.record_credit_code or "").strip()
            issues: list[HintCode] = []
            if not code:
                issues.append(HintCode.CREDIT_MISSING)
            elif code != state.current_subject.credit_code.root:
                issues.append(HintCode.CREDIT_MISMATCH)

            content_codes = set(re.findall(
                r"(?<![0-9A-Z])[0-9ABCDEFGHJKLMNPQRTUWXY]{18}(?![0-9A-Z])",
                draft.content.upper(),
            ))
            if code and any(content_code != code for content_code in content_codes):
                issues.append(HintCode.CREDIT_CONFLICT)
            has_source_url = source_url is not None and re.fullmatch(r"https?://[^\s]+", source_url) is not None
            has_observed_at = draft.observed_at is not None and bool(draft.observed_at.strip())
            if not has_source_url or not has_observed_at:
                issues.append(HintCode.SOURCE_INFO_MISSING)

            from_snapshot_id = state.draft.from_snapshot_id if state.draft is not None else None
            saved = ManualDraft(
                **normalized.model_dump(),
                draft_id=uuid4(),
                from_snapshot_id=from_snapshot_id,
                issues=issues,
            )
            updated = state.model_copy(update={"draft": saved})
            self._sessions[sid] = (actor.actor_id, updated)
            return saved.model_copy(deep=True)

    def _clear_draft(self, actor: ActorContext, sid: UUID) -> None:
        """在会话锁内清除草稿及其快照来源关联。"""
        with self._lock:
            entry = self._sessions.get(sid)
            if entry is None or entry[0] != actor.actor_id:
                info = ErrorInfo(code="RESOURCE_NOT_FOUND", hint_id=HintCode.INTERNAL_ERROR,
                                 fields=[], retryable=False)
                error = ApplicationError(info.code)
                error.info = info
                raise error
            state = entry[1]
            self._sessions[sid] = (actor.actor_id, state.model_copy(update={"draft": None}))

    def _accept_submission(
        self,
        actor: ActorContext,
        sid: UUID,
        command: SubmitEvidenceCommand,
        operation_id: UUID,
        now: datetime,
    ) -> tuple[OperationHandle, WorkflowPayload]:
        """在会话锁内校验并接纳私人线索；失败保持草稿、证据和任务不变。

        共享发布和快照存储尚未装配，合法共享请求仅记录共享存储失败，
        不把未写入的共享声称为成功；关联快照必须经其存储复核后才可接纳。
        """
        with self._lock:
            state = self.restore(actor, sid)
            code: ErrorCode | None = None
            hint = HintCode.LIMIT_EXCEEDED
            fields: list[FieldIssue] = []
            subject = state.current_subject
            payload = state.payload
            draft = state.draft
            if subject is None:
                code, hint = "SUBJECT_UNCONFIRMED", HintCode.CONFIRM_SUBJECT
            elif (
                state.session_generation != command.expected_generation
                or payload is None
                or payload.api_status.evidence_version != command.expected_evidence_version
                or state.active_operation is not None
                or draft is None
                or draft.draft_id != command.draft_id
            ):
                code, hint = "OPERATION_CONFLICT", HintCode.OPERATION_CONFLICT
            if code:
                info = ErrorInfo(code=code, hint_id=hint, fields=[], retryable=False)
                error = ApplicationError(info.code)
                error.info = info
                raise error
            # 上述分支已排除缺失状态；显式断言同时保证类型收窄。
            assert subject is not None and payload is not None and draft is not None
            record_code = (draft.record_credit_code or "").strip()
            if not record_code:
                code, hint = "CREDIT_MISSING", HintCode.CREDIT_MISSING
            elif re.fullmatch(r"[0-9ABCDEFGHJKLMNPQRTUWXY]{18}", record_code) is None:
                code = "INPUT_INVALID"
                fields = [FieldIssue(field="record_credit_code", message_key="credit_code_format")]
            elif record_code != subject.credit_code.root:
                code, hint = "CREDIT_MISMATCH", HintCode.CREDIT_MISMATCH
            else:
                content_codes = set(re.findall(
                    r"(?<![0-9A-Z])[0-9ABCDEFGHJKLMNPQRTUWXY]{18}(?![0-9A-Z])",
                    draft.content.upper(),
                ))
                if any(item != record_code for item in content_codes):
                    code, hint = "CREDIT_CONFLICT", HintCode.CREDIT_CONFLICT
            if not code and not draft.content.strip():
                code = "INPUT_INVALID"
                fields = [FieldIssue(field="content", message_key="content_required")]

            source_url = draft.source_url
            if not code and source_url is not None:
                try:
                    AnyHttpUrl(source_url)  # 仅做本地地址格式校验，不探测网页。
                    parsed = urlsplit(source_url)
                    valid_url = (
                        parsed.scheme in ("http", "https")
                        and bool(parsed.hostname)
                        and parsed.username is None and parsed.password is None
                        and not any(ord(char) < 32 or ord(char) == 127 or char.isspace()
                                    for char in source_url)
                        and "\\" not in source_url
                    )
                    parsed.port  # 端口格式也需合法；不访问该地址。
                except (ValueError, ValidationError):
                    valid_url = False
                if not valid_url:
                    code = "INPUT_INVALID"
                    fields = [FieldIssue(field="source_url", message_key="url_format")]

            observed_at: datetime | None = None
            if not code and draft.observed_at is not None:
                try:
                    if re.fullmatch(
                        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
                        draft.observed_at,
                    ) is None:
                        raise ValueError("invalid RFC3339")
                    observed_at = datetime.fromisoformat(draft.observed_at.replace("Z", "+00:00"))
                    if observed_at.utcoffset() is None:
                        raise ValueError("missing timezone")
                except ValueError:
                    code = "INPUT_INVALID"
                    fields = [FieldIssue(field="observed_at", message_key="time_format")]
                else:
                    if observed_at > now:
                        code = "INPUT_INVALID"
                        fields = [FieldIssue(field="observed_at", message_key="future_time")]
            if not code and draft.from_snapshot_id is not None:
                if not command.snapshot_acknowledged:
                    code, hint = "SNAPSHOT_CONFIRM_REQUIRED", HintCode.SNAPSHOT_CONFIRM_REQUIRED
                else:
                    # 当前未装配共享存储，不能把未经重新读取的快照当作有效材料。
                    code, hint = "SNAPSHOT_UNAVAILABLE", HintCode.SNAPSHOT_EXPIRED
            if not code and command.share_consent and (
                source_url is None or observed_at is None
                or now >= observed_at + timedelta(days=7)
            ):
                code, hint = "SHARE_REQUIREMENTS", HintCode.SOURCE_INFO_MISSING
                fields = [FieldIssue(field="share_consent", message_key="share_fields_required")]
            if not code and len(payload.evidence_list) >= 200:
                code = "INPUT_TOO_LARGE"
                fields = [FieldIssue(field="content", message_key="evidence_limit")]
            if code:
                info = ErrorInfo(code=code, hint_id=hint, fields=fields, retryable=False)
                error = ApplicationError(info.code)
                error.info = info
                raise error

            handle = OperationHandle(
                operation_id=operation_id, session_id=sid,
                session_generation=state.session_generation,
            )
            evidence_id = f"E-US-{uuid4().hex.upper()}"
            # 只有全部校验成功后才构造新payload；未知的查看时间不能补成现在。
            accepted = payload.model_dump(mode="python")
            accepted["evidence_list"].append({
                "evidence_id": evidence_id, "subject_credit_code": subject.credit_code.root,
                "category": draft.category, "content": draft.content, "source": "user_self",
                "snapshot_time": observed_at, "captured_at": now, "event_time": draft.event_time,
                "source_url": source_url, "source_publisher": None, "provider_record_id": None,
                "origin_id": f"user:{uuid4()}", "derived_from": None,
                "verification_status": "original_not_verified", "hint_id": "SOURCE_USER_SELF",
            })
            status = accepted["api_status"]
            status.update({
                "operation_id": operation_id,
                "evidence_version": payload.api_status.evidence_version + 1,
                "result_revision": payload.api_status.result_revision + 1,
                "llm_status": "running",
                "last_submission": {
                    "operation_id": operation_id, "evidence_id": evidence_id,
                    "share_status": "error" if command.share_consent else "not_requested",
                    "share_receipt_id": None,
                },
            })
            hints: list[HintCode] = [item for item in payload.ui_hint_group if item not in (
                HintCode.NO_EVIDENCE, HintCode.REPORT_FAILED, HintCode.REPORT_INVALID,
                HintCode.EVIDENCE_SAVED, HintCode.SHARE_FAILED, HintCode.SHARE_SAVED,
            )]
            hints.extend([HintCode.SOURCE_USER_SELF, HintCode.EVIDENCE_SAVED])
            if source_url is None or observed_at is None:
                hints.append(HintCode.SOURCE_INFO_MISSING)
            if command.share_consent:
                hints.append(HintCode.SHARE_FAILED)
            if payload.api_status.summary_evidence_version is not None:
                hints.append(HintCode.REPORT_STALE)
            accepted["ui_hint_group"] = list(dict.fromkeys(hints))
            accepted_payload = WorkflowPayload.model_validate(accepted)
            self._sessions[sid] = (actor.actor_id, state.model_copy(update={
                "payload": accepted_payload, "draft": None, "active_operation": handle,
            }, deep=True))
            return handle, accepted_payload.model_copy(deep=True)


class ScreeningService:
    """搜索、证据提交和受控报告工作流边界。"""

    _searches: ClassVar[dict[UUID, tuple[UUID, UUID, datetime, SearchResult]]] = {}
    _idempotency: ClassVar[dict[tuple[UUID, UUID, UUID], tuple[str, SearchResult]]] = {}
    _confirm_idempotency: ClassVar[dict[tuple[UUID, UUID, UUID], tuple[str, OperationHandle]]] = {}
    _draft_idempotency: ClassVar[
        dict[tuple[UUID, UUID, UUID], tuple[str, int, ManualDraft]]
    ] = {}
    _clear_draft_idempotency: ClassVar[set[tuple[UUID, UUID, UUID]]] = set()
    _submission_idempotency: ClassVar[
        dict[tuple[UUID, UUID, UUID], tuple[str, OperationHandle]]
    ] = {}
    _retry_idempotency: ClassVar[
        dict[tuple[UUID, UUID, UUID], tuple[str, OperationHandle]]
    ] = {}
    _operations: ClassVar[dict[UUID, tuple[UUID, UUID, int, OperationView]]] = {}
    _lock: ClassVar[RLock] = RLock()
    _query_executor: ClassVar[ThreadPoolExecutor] = ThreadPoolExecutor(
        max_workers=4,
        thread_name_prefix="company-screening-query",
    )

    def __init__(
        self,
        *,
        session_service: SessionService | None = None,
        company_data: CompanyDataPort | None = None,
        clock: Callable[[], datetime] | None = None,
        task_submitter: Callable[[Callable[[], None]], object] | None = None,
        collection_service: CollectionService | None = None,
    ) -> None:
        """注入会话和提供方端口；缺少真实端口时不使用合成数据兜底。"""
        self._session_service = session_service or SessionService()
        self._company_data = company_data
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._task_submitter = task_submitter or self._query_executor.submit
        self._collection_service = collection_service

    def search(self, actor: ActorContext, sid: UUID, command: SearchCommand, key: UUID) -> SearchResult:
        """BE-IF-03：仅返回候选，不自动确认。"""
        query = command.query.strip()
        if not query:
            info = ErrorInfo(code="INPUT_INVALID", hint_id=HintCode.LIMIT_EXCEEDED,
                             fields=[FieldIssue(field="query", message_key="company_name_required")],
                             retryable=False)
            error = ApplicationError(info.code)
            error.info = info
            raise error
        normalized = command.model_copy(update={"query": query})

        # 所有权和有效期在任何外部调用之前校验；搜索属于明确用户活动。
        self._session_service.restore(actor, sid)
        self._session_service.activity(actor, sid)
        fingerprint = normalized.model_dump_json()
        idempotency_key = (actor.actor_id, sid, key)

        with self._lock:
            existing = self._idempotency.get(idempotency_key)
            if existing is not None:
                if existing[0] != fingerprint:
                    info = ErrorInfo(code="IDEMPOTENCY_CONFLICT", hint_id=HintCode.OPERATION_CONFLICT,
                                     fields=[], retryable=False)
                    error = ApplicationError(info.code)
                    error.info = info
                    raise error
                return existing[1].model_copy(deep=True)

            if self._company_data is None:
                info = ErrorInfo(code="UPSTREAM_AUTH", hint_id=HintCode.SEARCH_FAILED,
                                 fields=[], retryable=False)
                error = ApplicationError(info.code)
                error.info = info
                raise error

            try:
                provider_page = self._company_data.search(normalized)
            except ProviderError as exc:
                info = ErrorInfo(code=exc.code, hint_id=HintCode.SEARCH_FAILED,
                                 fields=[], retryable=exc.retryable)
                error = ApplicationError(info.code)
                error.info = info
                raise error from None

            result = SearchResult(
                search_id=uuid4(),
                items=[Candidate(
                    candidate_id=uuid4(),
                    name=item.name,
                    credit_code=item.credit_code,
                    registered_region=item.registered_region,
                    legal_representative=item.legal_representative,
                    established_on=item.established_on,
                    selectable=item.credit_code is not None,
                ) for item in provider_page.items],
                next_cursor=provider_page.next_cursor,
                total=provider_page.total,
            )
            self._searches[result.search_id] = (
                actor.actor_id, sid, self._clock() + timedelta(minutes=10),
                result.model_copy(deep=True),
            )
            self._idempotency[idempotency_key] = (fingerprint, result.model_copy(deep=True))
            return result

    def confirm(self, actor: ActorContext, sid: UUID, command: ConfirmSubjectCommand, key: UUID) -> OperationHandle:
        """BE-IF-03：人工确认后才开始详情流水线。"""
        # 会话归属必须先于候选查询；确认属于明确用户活动。
        self._session_service.restore(actor, sid)
        self._session_service.activity(actor, sid)
        fingerprint = command.model_dump_json()
        idempotency_key = (actor.actor_id, sid, key)

        with self._lock:
            existing = self._confirm_idempotency.get(idempotency_key)
            if existing is not None:
                if existing[0] != fingerprint:
                    info = ErrorInfo(code="IDEMPOTENCY_CONFLICT", hint_id=HintCode.OPERATION_CONFLICT,
                                     fields=[], retryable=False)
                    error = ApplicationError(info.code)
                    error.info = info
                    raise error
                return existing[1].model_copy(deep=True)

            stored_search = self._searches.get(command.search_id)
            if (
                stored_search is None
                or stored_search[0] != actor.actor_id
                or stored_search[1] != sid
                or self._clock() >= stored_search[2]
            ):
                info = ErrorInfo(code="CANDIDATE_INVALID", hint_id=HintCode.CONFIRM_SUBJECT,
                                 fields=[], retryable=False)
                error = ApplicationError(info.code)
                error.info = info
                raise error

            candidate = next(
                (item for item in stored_search[3].items if item.candidate_id == command.candidate_id),
                None,
            )
            if candidate is None or not candidate.selectable or candidate.credit_code is None:
                info = ErrorInfo(code="CANDIDATE_INVALID", hint_id=HintCode.CONFIRM_SUBJECT,
                                 fields=[], retryable=False)
                error = ApplicationError(info.code)
                error.info = info
                raise error

            subject = Subject(
                name=candidate.name,
                credit_code=candidate.credit_code,
                registered_region=(NullableText(root=candidate.registered_region)
                                   if candidate.registered_region is not None else None),
                legal_representative=(NullableText(root=candidate.legal_representative)
                                      if candidate.legal_representative is not None else None),
                established_on=candidate.established_on,
                confirmed_at=self._clock(),
            )
            handle = self._session_service._confirm_subject(
                actor,
                sid,
                subject,
                command.expected_generation,
                command.discard_draft,
                uuid4(),
            )
            self._operations[handle.operation_id] = (
                actor.actor_id,
                sid,
                handle.session_generation,
                OperationView(
                    **handle.model_dump(),
                    state="queued",
                    phase="query",
                    result=None,
                    error=None,
                ),
            )
            self._confirm_idempotency[idempotency_key] = (fingerprint, handle.model_copy(deep=True))

        try:
            self._task_submitter(
                lambda: self._run_query_operation(actor, handle, subject)
            )
        except Exception:
            self._fail_operation(
                handle.operation_id,
                ErrorInfo(code="INTERNAL_ERROR", hint_id=HintCode.INTERNAL_ERROR,
                          fields=[], retryable=False),
            )
        return handle

    def _fail_operation(self, opid: UUID, info: ErrorInfo) -> None:
        """收敛脱敏失败并释放本任务，保留结果且不清除新代次的活动任务。"""
        with self._lock, self._session_service._lock:
            stored = self._operations.get(opid)
            if stored is None:
                return
            failed = stored[3].model_copy(update={
                "state": "failed",
                "phase": "complete",
                "result": None,
                "error": info,
            }, deep=True)
            self._operations[opid] = (stored[0], stored[1], stored[2], failed)
            entry = self._session_service._sessions.get(stored[1])
            if entry is not None and entry[0] == stored[0]:
                state = entry[1]
                if (state.session_generation == stored[2] and state.active_operation is not None
                        and state.active_operation.operation_id == opid):
                    self._session_service._sessions[stored[1]] = (
                        entry[0], state.model_copy(update={"active_operation": None}),
                    )

    def _run_query_operation(
        self,
        actor: ActorContext,
        handle: OperationHandle,
        subject: Subject,
        retry_categories: tuple[Category, ...] | None = None,
    ) -> None:
        """在后台串行执行已接纳的查询范围并守卫完整终态写回。"""
        with self._lock:
            stored = self._operations.get(handle.operation_id)
            if stored is None or stored[3].state in ("succeeded", "failed"):
                return
            running = stored[3].model_copy(update={"state": "running", "phase": "query"}, deep=True)
            self._operations[handle.operation_id] = (stored[0], stored[1], stored[2], running)
        try:
            payload = self._execute_query_operation(actor, handle, subject, retry_categories)
            if not self._session_service._complete_operation(actor, handle, payload):
                info = ErrorInfo(code="OPERATION_CONFLICT", hint_id=HintCode.OPERATION_CONFLICT,
                                 fields=[], retryable=False)
                self._fail_operation(handle.operation_id, info)
                return
        except ApplicationError as exc:
            self._fail_operation(handle.operation_id, exc.info)
            return
        except Exception:
            info = ErrorInfo(code="INTERNAL_ERROR", hint_id=HintCode.INTERNAL_ERROR,
                             fields=[], retryable=False)
            self._fail_operation(handle.operation_id, info)
            return

        with self._lock:
            stored = self._operations.get(handle.operation_id)
            if stored is None:
                return
            succeeded = stored[3].model_copy(update={
                "state": "succeeded",
                "phase": "complete",
                "result": payload,
                "error": None,
            }, deep=True)
            self._operations[handle.operation_id] = (stored[0], stored[1], stored[2], succeeded)

    def _execute_query_operation(
        self,
        actor: ActorContext,
        handle: OperationHandle,
        subject: Subject,
        retry_categories: tuple[Category, ...] | None = None,
    ) -> WorkflowPayload:
        """执行原计划或其失败子集；成功替换整类平台记录，失败保留旧材料。"""
        workspace = self._session_service.restore(actor, handle.session_id)
        if (
            workspace.session_generation != handle.session_generation
            or workspace.current_subject != subject
            or workspace.active_operation is None
            or workspace.active_operation.operation_id != handle.operation_id
        ):
            info = ErrorInfo(code="OPERATION_CONFLICT", hint_id=HintCode.OPERATION_CONFLICT,
                             fields=[], retryable=False)
            error = ApplicationError(info.code)
            error.info = info
            raise error

        previous = workspace.payload if retry_categories is not None else None
        category_results: dict[str, dict[str, object]] = (
            previous.api_status.categories.model_dump(mode="python") if previous is not None else {}
        )
        evidence_rows: list[dict[str, object]] = (
            previous.model_dump(mode="python")["evidence_list"] if previous is not None else []
        )
        query_diagnostics = {
            key: detail.model_copy(deep=True)
            for key, detail in (previous.api_status.query_diagnostics or {}).items()
            if getattr(previous.api_status.categories, key).root.status in ("error", "partial")
        } if previous is not None else {}
        planned = previous.api_status.planned_categories.root if previous is not None else list(Category)
        expected_credit = subject.credit_code.root
        for category in Category:
            if category not in planned or (retry_categories is not None and category not in retry_categories):
                continue
            query_diagnostics.pop(category.value, None)
            attempted_at = self._clock()
            if self._company_data is None:
                query_diagnostics[category.value] = _query_diagnostic("PROVIDER_NOT_CONFIGURED", "configuration")
                category_results[category.value] = {
                    "status": "error",
                    "record_count": 0,
                    "queried_at": attempted_at,
                    "scope_description": CATEGORY_ERROR_SCOPE[category.value],
                    "error_code": "UPSTREAM_AUTH",
                }
                continue
            try:
                retained_rows = [row for row in evidence_rows if not (
                    row["source"] == "tianyan" and row["category"] == category.value
                )]
                if category == Category.judicial:
                    record_budget = min(120, 200 - len(retained_rows))
                    if record_budget <= 0:
                        if self._collection_service is not None:
                            self._collection_service._category_batch(actor, handle.session_id, subject, category, record_limit=0)
                        capacity_error = ProviderError("No evidence capacity for judicial window")
                        capacity_error.code, capacity_error.retryable = "UPSTREAM_INCOMPLETE", False
                        capacity_error.diagnostic = _query_diagnostic(
                            "RECORD_LIMIT_EXCEEDED", "aggregate", field="record_count",
                            actual_count=len(retained_rows), limit_count=200,
                        )
                        raise capacity_error
                    batch = (self._collection_service._category_batch(actor, handle.session_id, subject, category,
                             record_limit=record_budget, bypass=retry_categories is not None)
                             if self._collection_service is not None else
                             self._company_data.fetch_category(subject, category, record_limit=record_budget))
                else:
                    record_budget = 200
                    batch = (self._collection_service._category_batch(actor, handle.session_id, subject, category,
                             bypass=retry_categories is not None) if self._collection_service is not None else
                             self._company_data.fetch_category(subject, category))
                if batch.category != category:
                    provider_failure = ProviderError("Provider category does not match query")
                    provider_failure.code, provider_failure.retryable = "UPSTREAM_INVALID", False
                    provider_failure.diagnostic = _query_diagnostic("RESPONSE_INVALID", "response")
                    raise provider_failure
                if batch.binding_credit_code != expected_credit:
                    query_diagnostics[category.value] = _query_diagnostic(
                        "SUBJECT_MISMATCH", "record", field="record_credit_code",
                    )
                    category_results[category.value] = {
                        "status": "error",
                        "record_count": 0,
                        "queried_at": batch.queried_at,
                        "scope_description": CATEGORY_ERROR_SCOPE[category.value],
                        "error_code": "SUBJECT_RESPONSE_MISMATCH",
                    }
                    continue
                if any(record.record_credit_code not in (None, expected_credit) for record in batch.records):
                    query_diagnostics[category.value] = _query_diagnostic(
                        "SUBJECT_MISMATCH", "record", field="record_credit_code",
                    )
                    category_results[category.value] = {
                        "status": "error",
                        "record_count": 0,
                        "queried_at": batch.queried_at,
                        "scope_description": CATEGORY_ERROR_SCOPE[category.value],
                        "error_code": "SUBJECT_RESPONSE_MISMATCH",
                    }
                    continue
                invalid_coverage = False
                if category != Category.judicial:
                    invalid_coverage = (batch.completeness != "complete" or bool(batch.tool_coverage)
                                        or batch.error_code is not None or batch.diagnostic is not None)
                elif batch.tool_coverage:
                    coverage_rows = batch.tool_coverage
                    tool_names = [item.tool_name.value for item in coverage_rows]
                    has_failure = any(item.status.value == "error" for item in coverage_rows)
                    unfinished = any(item.status.value not in ("complete", "empty") for item in coverage_rows)
                    reliable = any(item.status.value in ("complete", "empty", "partial") for item in coverage_rows)
                    invalid_coverage = (
                        len(tool_names) != 6 or set(tool_names) != {item.value for item in JudicialToolName}
                        or sum(item.accepted_count for item in coverage_rows) != len(batch.records)
                        or (batch.completeness == "partial") != unfinished or not reliable
                        or (batch.error_code is not None) != has_failure
                        or (batch.diagnostic is not None and not has_failure)
                    )
                    for item in coverage_rows:
                        status = item.status.value
                        if status == "complete":
                            invalid_coverage |= (item.accepted_count == 0 or item.total_count != item.accepted_count
                                                 or item.has_more is not False)
                        elif status == "empty":
                            invalid_coverage |= item.accepted_count != 0 or item.total_count != 0 or item.has_more is not False
                        elif status in ("error", "not_requested"):
                            invalid_coverage |= (item.accepted_count != 0 or item.total_count is not None
                                                 or item.has_more is not None)
                        else:
                            invalid_coverage |= (item.has_more is False or (
                                item.total_count is not None and item.total_count < item.accepted_count
                            ))
                elif batch.completeness != "complete" or batch.error_code is not None or batch.diagnostic is not None:
                    invalid_coverage = True
                if invalid_coverage:
                    coverage_error = ProviderError("Provider coverage does not match evidence")
                    coverage_error.code, coverage_error.retryable = "UPSTREAM_INVALID", False
                    coverage_error.diagnostic = _query_diagnostic("RESPONSE_INVALID", "aggregate")
                    raise coverage_error
                record_ids = [record.record_id for record in batch.records]
                if category == Category.judicial and len(batch.records) > record_budget:
                    budget_error = ProviderError("Provider exceeded judicial record budget")
                    budget_error.code, budget_error.retryable = "UPSTREAM_INCOMPLETE", False
                    budget_error.diagnostic = _query_diagnostic(
                        "RECORD_LIMIT_EXCEEDED", "aggregate", field="record_count",
                        actual_count=len(batch.records), limit_count=record_budget,
                    )
                    raise budget_error
                if len(record_ids) != len(set(record_ids)) or len(retained_rows) + len(batch.records) > 200:
                    duplicate = len(record_ids) != len(set(record_ids))
                    query_diagnostics[category.value] = _query_diagnostic(
                        "DUPLICATE_RECORDS" if duplicate else "RECORD_LIMIT_EXCEEDED", "aggregate",
                        field="record_id" if duplicate else "record_count",
                        actual_count=None if duplicate else len(retained_rows) + len(batch.records),
                        limit_count=None if duplicate else 200,
                    )
                    category_results[category.value] = {
                        "status": "error",
                        "record_count": 0,
                        "queried_at": batch.queried_at,
                        "scope_description": CATEGORY_ERROR_SCOPE[category.value],
                        "error_code": "UPSTREAM_INCOMPLETE",
                    }
                    continue

                category_evidence: list[dict[str, object]] = []
                for record in batch.records:
                    digest = hashlib.sha256(
                        f"{category.value}:{record.record_id}".encode("utf-8")
                    ).hexdigest()[:20].upper()
                    category_evidence.append({
                        "evidence_id": f"E-TY-{category.value.upper()}-{digest}",
                        "subject_credit_code": expected_credit,
                        "category": category.value,
                        "content": record.content,
                        "source": "tianyan",
                        "snapshot_time": (self._collection_service._snapshot_at(actor, handle.session_id, category, record.record_id, batch.queried_at)
                                          if self._collection_service is not None else batch.queried_at),
                        "captured_at": self._clock(),
                        "event_time": record.event_time,
                        "source_url": record.source_url,
                        "source_publisher": record.source_publisher,
                        "provider_record_id": record.record_id,
                        "origin_id": f"tyc:{category.value}:{digest.lower()}",
                        "derived_from": None,
                        "verification_status": "original_not_verified",
                        "hint_id": "SOURCE_TIANYAN",
                    })
                # 仅接纳已校验的批次，司法窗口将未取得范围同时发布；用户来源始终保留。
                evidence_rows = [*retained_rows, *category_evidence]
                if self._collection_service is not None:
                    self._collection_service._accept_projection(actor, handle.session_id, category)
                category_results[category.value] = {
                    "status": "partial" if batch.completeness == "partial" else "ok" if batch.records else "empty",
                    "record_count": len(batch.records),
                    "queried_at": batch.queried_at,
                    "scope_description": batch.scope_description,
                    "error_code": batch.error_code,
                    "tool_coverage": [item.model_dump(mode="python") for item in batch.tool_coverage],
                }
                if batch.error_code is not None:
                    query_diagnostics[category.value] = (
                        QueryDiagnostic.model_validate(batch.diagnostic.model_dump(mode="python"))
                        if batch.diagnostic is not None else _query_diagnostic()
                    )
            except StorageError:
                info = ErrorInfo(code="STORAGE_UNAVAILABLE", hint_id=HintCode.INTERNAL_ERROR, fields=[], retryable=True)
                error = ApplicationError(info.code)
                error.info = info
                raise error from None
            except ProviderError as exc:
                try:
                    detail = (QueryDiagnostic.model_validate(exc.diagnostic.model_dump(mode="python"))
                              if exc.diagnostic is not None else _query_diagnostic())
                except (AttributeError, TypeError, ValueError):
                    detail = _query_diagnostic()
                query_diagnostics[category.value] = detail
                category_results[category.value] = {
                    "status": "error",
                    "record_count": 0,
                    "queried_at": attempted_at,
                    "scope_description": CATEGORY_ERROR_SCOPE[category.value],
                    "error_code": exc.code,
                }
            except Exception:
                query_diagnostics[category.value] = _query_diagnostic()
                category_results[category.value] = {
                    "status": "error",
                    "record_count": 0,
                    "queried_at": attempted_at,
                    "scope_description": CATEGORY_ERROR_SCOPE[category.value],
                    "error_code": "UPSTREAM_INVALID",
                }

        # 兼容旧省略字段与新默认空数组，不能因等值覆盖的序列化差异递增分析版本。
        category_results = CategoryResults.model_validate(category_results).model_dump(mode="python")
        statuses = [str(category_results[category.value]["status"]) for category in planned]
        if all(status == "error" for status in statuses):
            tianyan_status = "error"
        elif any(status in ("error", "partial") for status in statuses):
            tianyan_status = "partial"
        elif any(status == "ok" for status in statuses):
            tianyan_status = "ok"
        else:
            tianyan_status = "empty"

        changed = previous is None or (
            evidence_rows != previous.model_dump(mode="python")["evidence_list"]
            or category_results != previous.api_status.categories.model_dump(mode="python")
        )
        hints: list[HintCode] = ([item for item in previous.ui_hint_group if item not in (
            HintCode.PARTIAL_COVERAGE, HintCode.QUERY_ERROR, HintCode.QUERY_EMPTY,
            HintCode.NO_EVIDENCE, HintCode.SOURCE_TIANYAN,
            HintCode.REPORT_FAILED, HintCode.REPORT_INVALID, HintCode.REPORT_STALE,
        )] if previous is not None else [HintCode.DISCLOSURE_LIMITED])
        llm_status = previous.api_status.llm_status.value if previous is not None else "skipped_no_evidence"
        if any(row["source"] == "tianyan" for row in evidence_rows):
            hints.append(HintCode.SOURCE_TIANYAN)
        if evidence_rows and changed:
            # 模型尚未装配；覆盖改变后明确报告失败，绝不编造当前版本报告。
            llm_status = "error"
        elif not evidence_rows:
            llm_status = "skipped_no_evidence"
        if llm_status == "error":
            hints.append(HintCode.REPORT_FAILED)
        elif llm_status == "invalid_output":
            hints.append(HintCode.REPORT_INVALID)
        elif llm_status == "skipped_no_evidence":
            hints.append(HintCode.NO_EVIDENCE)
        if tianyan_status == "partial":
            hints.append(HintCode.PARTIAL_COVERAGE)
        elif tianyan_status == "error":
            hints.append(HintCode.QUERY_ERROR)
        elif tianyan_status == "empty":
            hints.append(HintCode.QUERY_EMPTY)

        evidence_version = previous.api_status.evidence_version + int(changed) if previous is not None else 1
        if (previous is not None and previous.api_status.summary_evidence_version is not None
                and previous.api_status.summary_evidence_version < evidence_version):
            hints.append(HintCode.REPORT_STALE)
        return WorkflowPayload.model_validate({
            "subject": subject,
            "evidence_list": evidence_rows,
            "summary_text": previous.summary_text if previous is not None and evidence_rows else "",
            "api_status": {
                "tianyan_status": tianyan_status,
                "planned_categories": planned,
                "categories": category_results,
                "query_diagnostics": query_diagnostics,
                "session_id": handle.session_id,
                "session_generation": handle.session_generation,
                "operation_id": handle.operation_id,
                "result_revision": previous.api_status.result_revision + 1 if previous is not None else 1,
                "evidence_version": evidence_version,
                "summary_evidence_version": (previous.api_status.summary_evidence_version
                                             if previous is not None and evidence_rows else None),
                "summary_generated_at": (previous.api_status.summary_generated_at
                                         if previous is not None and evidence_rows else None),
                "llm_status": llm_status,
                "snapshot_status": (previous.api_status.snapshot_status
                                    if previous is not None and previous.api_status.snapshot_status != "available"
                                    else "not_checked"),
                "snapshot_draft": None,
                "last_submission": previous.api_status.last_submission if previous is not None else None,
            },
            "ui_hint_group": list(dict.fromkeys(hints)),
        })

    def save_draft(self, actor: ActorContext, sid: UUID, draft: EditableDraft, key: UUID) -> ManualDraft:
        """BE-IF-04：保存草稿，不接纳证据或调用模型。"""
        workspace = self._session_service.restore(actor, sid)
        self._session_service.activity(actor, sid)
        if workspace.current_subject is None:
            info = ErrorInfo(code="SUBJECT_UNCONFIRMED", hint_id=HintCode.CONFIRM_SUBJECT,
                             fields=[], retryable=False)
            error = ApplicationError(info.code)
            error.info = info
            raise error
        fingerprint = draft.model_dump_json()
        idempotency_key = (actor.actor_id, sid, key)
        with self._lock:
            existing = self._draft_idempotency.get(idempotency_key)
            if existing is not None:
                if existing[0] != fingerprint or existing[1] != workspace.session_generation:
                    info = ErrorInfo(code="IDEMPOTENCY_CONFLICT", hint_id=HintCode.OPERATION_CONFLICT,
                                     fields=[], retryable=False)
                    error = ApplicationError(info.code)
                    error.info = info
                    raise error
                return existing[2].model_copy(deep=True)
            saved = self._session_service._save_draft(actor, sid, draft)
            self._draft_idempotency[idempotency_key] = (
                fingerprint,
                workspace.session_generation,
                saved.model_copy(deep=True),
            )
            return saved

    def clear_draft(self, actor: ActorContext, sid: UUID, key: UUID) -> None:
        """BE-IF-04：明确清空当前草稿及其预填充关联。"""
        self._session_service.restore(actor, sid)
        self._session_service.activity(actor, sid)
        idempotency_key = (actor.actor_id, sid, key)
        with self._lock:
            if idempotency_key in self._clear_draft_idempotency:
                return
            self._session_service._clear_draft(actor, sid)
            self._clear_draft_idempotency.add(idempotency_key)

    def submit(self, actor: ActorContext, sid: UUID, command: SubmitEvidenceCommand, key: UUID) -> OperationHandle:
        """BE-IF-04：校验服务端草稿后原子接纳，返回自动分析任务句柄。

        同键同请求回放原句柄；同键不同内容拒绝。校验不通过保留草稿，
        已经接纳后模型不可用不回滚证据。共享存储尚未配置，不发布共享。
        """
        self._session_service.restore(actor, sid)
        fingerprint = command.model_dump_json()
        idempotency_key = (actor.actor_id, sid, key)
        # 锁的固定次序与确认/草稿流程一致；接纳、任务和幂等记录一起提交。
        with self._lock, self._session_service._lock:
            existing = self._submission_idempotency.get(idempotency_key)
            if existing is not None:
                if existing[0] != fingerprint:
                    info = ErrorInfo(
                        code="IDEMPOTENCY_CONFLICT", hint_id=HintCode.OPERATION_CONFLICT,
                        fields=[], retryable=False,
                    )
                    error = ApplicationError(info.code)
                    error.info = info
                    raise error
                return existing[1].model_copy(deep=True)
            handle, accepted = self._session_service._accept_submission(
                actor, sid, command, uuid4(), self._clock(),
            )
            self._operations[handle.operation_id] = (
                actor.actor_id, sid, handle.session_generation,
                OperationView(
                    **handle.model_dump(), state="queued", phase="analyze", result=None, error=None,
                ),
            )
            self._submission_idempotency[idempotency_key] = (
                fingerprint, handle.model_copy(deep=True),
            )
            self._session_service.activity(actor, sid)
        try:
            self._task_submitter(lambda: self._run_submission_operation(actor, handle, accepted))
        except Exception:
            # 当前收敛只处理“模型未配置”，无网络调用；排队失败也给出可靠完整终态。
            self._run_submission_operation(actor, handle, accepted)
        return handle

    def _run_submission_operation(
        self,
        actor: ActorContext,
        handle: OperationHandle,
        accepted_payload: WorkflowPayload,
    ) -> None:
        """收敛接纳任务；当前未配置模型时如实失败，已保存证据不回滚。"""
        with self._lock:
            stored = self._operations.get(handle.operation_id)
            if stored is None or stored[3].state in ("succeeded", "failed"):
                return
            running = stored[3].model_copy(update={"state": "running", "phase": "analyze"})
            self._operations[handle.operation_id] = (stored[0], stored[1], stored[2], running)
        try:
            result = accepted_payload.model_copy(deep=True)
            result.api_status.llm_status = LlmStatus.error
            result.api_status.result_revision += 1
            result.ui_hint_group = list(dict.fromkeys([
                *result.ui_hint_group, HintCode.REPORT_FAILED,
            ]))
            if not self._session_service._complete_operation(actor, handle, result):
                self._fail_operation(handle.operation_id, ErrorInfo(
                    code="OPERATION_CONFLICT", hint_id=HintCode.OPERATION_CONFLICT,
                    fields=[], retryable=False,
                ))
                return
        except Exception:
            self._fail_operation(handle.operation_id, ErrorInfo(
                code="INTERNAL_ERROR", hint_id=HintCode.INTERNAL_ERROR,
                fields=[], retryable=False,
            ))
            return
        with self._lock:
            stored = self._operations.get(handle.operation_id)
            if stored is not None:
                self._operations[handle.operation_id] = (
                    stored[0], stored[1], stored[2], stored[3].model_copy(update={
                        "state": "succeeded", "phase": "complete", "result": result, "error": None,
                    }, deep=True),
                )

    def retry_analysis(self, actor: ActorContext, sid: UUID, command: RetryAnalysisCommand, key: UUID) -> OperationHandle:
        """BE-IF-05：仅重新分析当前版本，不重复录入。"""
        raise NotImplementedError()

    def retry_queries(self, actor: ActorContext, sid: UUID, command: RetryQueryCommand, key: UUID) -> OperationHandle:
        """BE-IF-03/05：接纳原计划失败类别的显式重试，同键回放且不重复查询。"""
        fingerprint = command.model_dump_json()
        idempotency_key = (actor.actor_id, sid, key)
        with self._lock, self._session_service._lock:
            workspace = self._session_service.restore(actor, sid)
            existing = self._retry_idempotency.get(idempotency_key)
            if existing is not None:
                if existing[0] != fingerprint:
                    info = ErrorInfo(code="IDEMPOTENCY_CONFLICT", hint_id=HintCode.OPERATION_CONFLICT,
                                     fields=[], retryable=False)
                    error = ApplicationError(info.code)
                    error.info = info
                    raise error
                if existing[1].session_generation != workspace.session_generation:
                    info = ErrorInfo(code="OPERATION_CONFLICT", hint_id=HintCode.OPERATION_CONFLICT,
                                     fields=[], retryable=False)
                    error = ApplicationError(info.code)
                    error.info = info
                    raise error
                return existing[1].model_copy(deep=True)
            handle, subject = self._session_service._begin_query_retry(actor, sid, command, uuid4())
            self._operations[handle.operation_id] = (
                actor.actor_id, sid, handle.session_generation,
                OperationView(**handle.model_dump(), state="queued", phase="query", result=None, error=None),
            )
            self._retry_idempotency[idempotency_key] = (fingerprint, handle.model_copy(deep=True))
            self._session_service.activity(actor, sid)
        categories = tuple(category for category in Category if category in command.categories)
        try:
            self._task_submitter(lambda: self._run_query_operation(actor, handle, subject, categories))
        except Exception:
            self._fail_operation(handle.operation_id, ErrorInfo(
                code="INTERNAL_ERROR", hint_id=HintCode.INTERNAL_ERROR, fields=[], retryable=False,
            ))
        return handle

    def operation(self, actor: ActorContext, sid: UUID, opid: UUID) -> OperationView:
        """BE-IF-06：只读进度或完整终态，不续期。"""
        self._session_service.restore(actor, sid)
        with self._lock:
            stored = self._operations.get(opid)
            if stored is not None and stored[0] == actor.actor_id and stored[1] == sid:
                return stored[3].model_copy(deep=True)
        info = ErrorInfo(code="RESOURCE_NOT_FOUND", hint_id=HintCode.INTERNAL_ERROR,
                         fields=[], retryable=False)
        error = ApplicationError(info.code)
        error.info = info
        raise error


class ShareService:
    """共享回执所有权与撤回边界。"""

    def withdraw(self, actor: ActorContext, receipt_id: UUID, key: UUID) -> WithdrawalResult:
        """DATA-04 / BE-IF-04：本人撤回，重复请求保持幂等。"""
        raise NotImplementedError()
