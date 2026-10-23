"""BE-IF-02：应用服务；会话、搜索、确认、分类查询编排与任务轮询已实现。"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
from threading import RLock
from typing import ClassVar
from uuid import UUID, uuid4

from .contracts.boundary import (
    ActorContext, Candidate, ConfirmSubjectCommand, EditableDraft, FieldIssue, ManualDraft, OperationHandle,
    ErrorInfo, OperationView, RetryAnalysisCommand, RetryQueryCommand, SearchCommand, SearchResult,
    SessionExpiry, SubmitEvidenceCommand, WithdrawalResult, WorkspaceState,
)
from .errors import ApplicationError, ProviderError
from .contracts.generated import Category, HintCode, NullableText, Subject, WorkflowPayload
from .ports import CompanyDataPort


CATEGORY_ERROR_SCOPE = {
    "basic": "工商登记、股东及出资计划查询未完整完成",
    "abnormal": "经营异常计划查询未完整完成",
    "penalty": "行政处罚计划查询未完整完成",
    "judicial": "失信、被执行、限高、司法案件、裁判文书及法院公告计划查询未完整完成",
    "asset": "股权冻结、司法协助、动产抵押及土地抵押计划查询未完整完成",
}


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


class ScreeningService:
    """搜索、证据提交和受控报告工作流边界。"""

    _searches: ClassVar[dict[UUID, tuple[UUID, UUID, datetime, SearchResult]]] = {}
    _idempotency: ClassVar[dict[tuple[UUID, UUID, UUID], tuple[str, SearchResult]]] = {}
    _confirm_idempotency: ClassVar[dict[tuple[UUID, UUID, UUID], tuple[str, OperationHandle]]] = {}
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
    ) -> None:
        """注入会话和提供方端口；缺少真实端口时不使用合成数据兜底。"""
        self._session_service = session_service or SessionService()
        self._company_data = company_data
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._task_submitter = task_submitter or self._query_executor.submit

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
        """把无法可靠形成完整结果的任务收敛为脱敏失败终态。"""
        with self._lock:
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

    def _run_query_operation(
        self,
        actor: ActorContext,
        handle: OperationHandle,
        subject: Subject,
    ) -> None:
        """在后台串行执行固定五类查询并写入完整终态。"""
        with self._lock:
            stored = self._operations.get(handle.operation_id)
            if stored is None:
                return
            running = stored[3].model_copy(update={"state": "running", "phase": "query"}, deep=True)
            self._operations[handle.operation_id] = (stored[0], stored[1], stored[2], running)
        try:
            payload = self._execute_query_operation(actor, handle, subject)
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
    ) -> WorkflowPayload:
        """执行固定查询计划；类别失败只进入覆盖状态，不伪装成空结果。"""
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

        category_results: dict[str, dict[str, object]] = {}
        evidence_rows: list[dict[str, object]] = []
        expected_credit = subject.credit_code.root
        for category in Category:
            attempted_at = self._clock()
            if self._company_data is None:
                category_results[category.value] = {
                    "status": "error",
                    "record_count": 0,
                    "queried_at": attempted_at,
                    "scope_description": CATEGORY_ERROR_SCOPE[category.value],
                    "error_code": "UPSTREAM_AUTH",
                }
                continue
            try:
                batch = self._company_data.fetch_category(subject, category)
                if batch.category != category:
                    raise ValueError("category mismatch")
                if batch.binding_credit_code != expected_credit:
                    category_results[category.value] = {
                        "status": "error",
                        "record_count": 0,
                        "queried_at": batch.queried_at,
                        "scope_description": CATEGORY_ERROR_SCOPE[category.value],
                        "error_code": "SUBJECT_RESPONSE_MISMATCH",
                    }
                    continue
                if any(record.record_credit_code not in (None, expected_credit) for record in batch.records):
                    category_results[category.value] = {
                        "status": "error",
                        "record_count": 0,
                        "queried_at": batch.queried_at,
                        "scope_description": CATEGORY_ERROR_SCOPE[category.value],
                        "error_code": "SUBJECT_RESPONSE_MISMATCH",
                    }
                    continue
                record_ids = [record.record_id for record in batch.records]
                if len(record_ids) != len(set(record_ids)) or len(evidence_rows) + len(batch.records) > 200:
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
                        "snapshot_time": batch.queried_at,
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
                evidence_rows.extend(category_evidence)
                category_results[category.value] = {
                    "status": "ok" if batch.records else "empty",
                    "record_count": len(batch.records),
                    "queried_at": batch.queried_at,
                    "scope_description": batch.scope_description,
                    "error_code": None,
                }
            except ProviderError as exc:
                category_results[category.value] = {
                    "status": "error",
                    "record_count": 0,
                    "queried_at": attempted_at,
                    "scope_description": CATEGORY_ERROR_SCOPE[category.value],
                    "error_code": exc.code,
                }
            except Exception:
                category_results[category.value] = {
                    "status": "error",
                    "record_count": 0,
                    "queried_at": attempted_at,
                    "scope_description": CATEGORY_ERROR_SCOPE[category.value],
                    "error_code": "UPSTREAM_INVALID",
                }

        statuses = [str(category_results[category.value]["status"]) for category in Category]
        if all(status == "error" for status in statuses):
            tianyan_status = "error"
        elif any(status == "error" for status in statuses):
            tianyan_status = "partial"
        elif any(status == "ok" for status in statuses):
            tianyan_status = "ok"
        else:
            tianyan_status = "empty"

        hints = [HintCode.DISCLOSURE_LIMITED]
        if evidence_rows:
            hints.extend([HintCode.SOURCE_TIANYAN, HintCode.REPORT_FAILED])
            llm_status = "error"
        else:
            hints.append(HintCode.NO_EVIDENCE)
            llm_status = "skipped_no_evidence"
        if tianyan_status == "partial":
            hints.append(HintCode.PARTIAL_COVERAGE)
        elif tianyan_status == "error":
            hints.append(HintCode.QUERY_ERROR)
        elif tianyan_status == "empty":
            hints.append(HintCode.QUERY_EMPTY)

        return WorkflowPayload.model_validate({
            "subject": subject,
            "evidence_list": evidence_rows,
            "summary_text": "",
            "api_status": {
                "tianyan_status": tianyan_status,
                "planned_categories": [category.value for category in Category],
                "categories": category_results,
                "session_id": handle.session_id,
                "session_generation": handle.session_generation,
                "operation_id": handle.operation_id,
                "result_revision": 1,
                "evidence_version": 1,
                "summary_evidence_version": None,
                "summary_generated_at": None,
                "llm_status": llm_status,
                "snapshot_status": "not_checked",
                "snapshot_draft": None,
                "last_submission": None,
            },
            "ui_hint_group": hints,
        })

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
