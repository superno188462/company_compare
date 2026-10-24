"""COL-IF-02：公共API材料复用、单工具采集及会话私有浏览编排。"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from threading import RLock
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from .collection_clock import utc_now
from .contracts.boundary import ActorContext, ErrorInfo, ErrorCode, OperationHandle, ProviderCategoryBatch, ProviderRecord, ProviderFailureCode, WorkspaceState
from .contracts.collection_storage import CollectionCacheKey, CollectionFetchKey, StoredCollectionBatch, StoredCollectionPage
from .contracts.generated import (
    CollectionOperationView, CollectionOverview, CollectionRecordsPage,
    CollectionToolName, LoadCollectionPageCommand, RefreshCollectionToolCommand, Category,
    HintCode, JudicialToolName, SnapshotToolName, QueryDiagnostic, Subject, ToolCoverage,
)
from .errors import ApplicationError, ProviderError, StorageError, CollectionConflictError
from .ports import CollectionStorePort, CompanyDataPort

if TYPE_CHECKING:
    from .services import SessionService


PLAN: dict[Category, tuple[str, ...]] = {
    Category.basic: ("get_company_registration_info", "get_shareholder_info"),
    Category.abnormal: ("get_business_exception",),
    Category.penalty: ("get_administrative_penalty",),
    Category.judicial: tuple(item.value for item in JudicialToolName),
    Category.asset: ("get_equity_freeze", "get_judicial_assistance", "get_chattel_mortgage_info", "get_land_mortgage_info"),
}
SCOPE: dict[Category, str] = {
    Category.basic: "工商登记、股东及出资", Category.abnormal: "经营异常", Category.penalty: "行政处罚",
    Category.judicial: "失信、被执行、限高、司法案件、裁判文书及法院公告",
    Category.asset: "股权冻结、司法协助、动产抵押及土地抵押",
}


def _error(code: ErrorCode) -> ApplicationError:
    """将可预期应用错误映射到既有固定提示，不传播内部异常正文。"""
    hint = (HintCode.CONFIRM_SUBJECT if code == "SUBJECT_UNCONFIRMED" else
            HintCode.OPERATION_CONFLICT if code in ("OPERATION_CONFLICT", "IDEMPOTENCY_CONFLICT") else
            HintCode.SESSION_EXPIRED if code == "SESSION_EXPIRED" else HintCode.INTERNAL_ERROR)
    exc = ApplicationError(code)
    exc.info = ErrorInfo(code=code, hint_id=hint, fields=[], retryable=False)
    return exc


@dataclass
class _Entry:
    batch_id: UUID | None = None
    obtained_from: str = "none"
    error: ErrorInfo | None = None
    diagnostic: QueryDiagnostic | None = None
    report_batch_id: UUID | None = None
    report_ids: set[str] = field(default_factory=set)
    report_times: dict[str, datetime] = field(default_factory=dict)


@dataclass
class _Bindings:
    generation: int
    revision: int = 1
    entries: dict[str, _Entry] = field(default_factory=dict)
    observed: dict[str, int] = field(default_factory=dict)


@dataclass
class _Task:
    actor: ActorContext
    handle: OperationHandle
    kind: str
    fingerprint: str
    started_at: datetime
    state: str = "queued"
    result: CollectionOverview | None = None
    error: ErrorInfo | None = None


class CollectionService:
    """只编排授权浏览、单页采集与更新；不把浏览新增页自动加入报告。"""

    def __init__(
        self, *, session_service: SessionService, company_data: CompanyDataPort | None,
        store: CollectionStorePort, scope_id: str, clock: Callable[[], datetime] = utc_now,
        task_submitter: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        """COLLECTION-WIRING-1：注入存储、提供方及时钟，私有状态随会话清理。"""
        self._sessions, self._provider, self._store = session_service, company_data, store
        self._scope, self._clock, self._submitter = scope_id, clock, task_submitter
        self._lock = RLock()
        self._bindings: dict[tuple[UUID, int], _Bindings] = {}
        self._tasks: dict[UUID, _Task] = {}
        self._keys: dict[tuple[UUID, UUID, str, UUID], UUID] = {}
        self._projections: dict[tuple[UUID, int, Category], dict[str, tuple[UUID, dict[str, datetime]]]] = {}
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="collection")
        self._sessions._collection_cleanup = self._forget

    def _forget(self, sid: UUID) -> None:
        """私有会话结束时清理浏览绑定、诊断、任务与幂等定位，不删除公共API页。"""
        with self._lock:
            for identity in list(self._bindings):
                if identity[0] == sid:
                    del self._bindings[identity]
            for projection in list(self._projections):
                if projection[0] == sid:
                    del self._projections[projection]
            for operation_key in list(self._keys):
                if operation_key[1] == sid:
                    del self._keys[operation_key]
            for operation_id, task in list(self._tasks.items()):
                if task.handle.session_id == sid:
                    del self._tasks[operation_id]

    def _key(self, subject: Subject, name: str) -> CollectionCacheKey:
        """固定查询身份只从可信主体和组合根作用域构造。"""
        return CollectionCacheKey(provider="tianyan_mcp", scope_id=self._scope,
                                  normalization_version="collection-1", subject_credit_code=subject.credit_code.root,
                                  tool_name=CollectionToolName(name), arguments_json="{}",
                                  page_size=20 if name in PLAN[Category.judicial] else None)

    def _state(self, actor: ActorContext, sid: UUID) -> tuple[WorkspaceState, _Bindings]:
        """先授权再读公共批次绑定；主体切换/会话结束时清除旧私有元数据。"""
        try:
            workspace = self._sessions.restore(actor, sid)
        except ApplicationError as exc:
            if exc.info.code == "SESSION_EXPIRED":
                with self._lock:
                    for key in list(self._bindings):
                        if key[0] == sid:
                            del self._bindings[key]
                    for opid, task in list(self._tasks.items()):
                        if task.handle.session_id == sid:
                            del self._tasks[opid]
            raise
        if workspace.current_subject is None:
            raise _error("SUBJECT_UNCONFIRMED")
        with self._lock:
            identity = (sid, workspace.session_generation)
            for old in list(self._bindings):
                if old[0] == sid and old != identity:
                    del self._bindings[old]
            if identity not in self._bindings:
                self._bindings[identity] = _Bindings(workspace.session_generation, entries={
                    name: _Entry() for names in PLAN.values() for name in names
                })
            return workspace, self._bindings[identity]

    def _pages(self, key: CollectionCacheKey, batch: StoredCollectionBatch) -> list[StoredCollectionPage]:
        """只读取此批次已提交连续页，保留页级时间；非司法为一次完整快照。"""
        result: list[StoredCollectionPage] = []
        for number in range(1, batch.revision + 1):
            page = self._store.get_page(key, batch.batch_id, number)
            if page is None:
                raise StorageError("Committed collection page unavailable")
            result.append(page)
        return result

    def _fetch(
        self, subject: Subject, name: str, *, batch: StoredCollectionBatch | None = None,
        page_number: int = 1, refresh: bool = False,
    ) -> tuple[StoredCollectionBatch, str]:
        """取得单页或完整快照，先查公共缓存/协调，再整页验证并原子提交。"""
        key = self._key(subject, name)
        if batch is None and not refresh:
            found = self._store.latest(key)
            if found is not None:
                return found, "cache"
        if batch is not None:
            found_page = self._store.get_page(key, batch.batch_id, page_number)
            if found_page is not None:
                found = self._store.get_batch(key, batch.batch_id)
                if found is None:
                    raise StorageError("Collection batch unavailable")
                return found, "cache"
        request = CollectionFetchKey(key=key, batch_id=batch.batch_id if batch else None,
                                     page_number=page_number,
                                     mode="refresh_tool" if refresh else "load_page" if batch else "initial",
                                     refresh_round_id=uuid4() if refresh else None)
        deadline = time.monotonic() + 60
        while True:
            claim = self._store.claim(request)
            if claim.state == "acquired":
                break
            if batch is not None and self._store.get_page(key, batch.batch_id, page_number) is not None:
                found = self._store.get_batch(key, batch.batch_id)
                if found is not None:
                    return found, "cache"
            elif batch is None and not refresh:
                found = self._store.latest(key)
                if found is not None:
                    return found, "cache"
            if time.monotonic() >= deadline:
                failure = ProviderError("Collection pending timeout")
                failure.code, failure.retryable = "UPSTREAM_TIMEOUT", True
                raise failure
            time.sleep(0.05)
        try:
            # claim之前的cache miss不能成为并发重复查询的理由。
            if not refresh:
                found = (self._store.get_batch(key, batch.batch_id) if batch is not None
                         and self._store.get_page(key, batch.batch_id, page_number) is not None
                         else self._store.latest(key) if batch is None else None)
                if found is not None:
                    return found, "cache"
            if self._provider is None:
                failure = ProviderError("Provider unavailable")
                failure.code, failure.retryable = "UPSTREAM_AUTH", False
                raise failure
            judicial = name in PLAN[Category.judicial]
            requested_at = self._clock()
            response = (self._provider.fetch_judicial_page(subject, JudicialToolName(name), page_number=page_number, page_size=20)
                        if judicial else self._provider.fetch_tool_snapshot(subject, SnapshotToolName(name)))
            if (self._clock() - requested_at).total_seconds() >= 60:
                failure = ProviderError("Collection request timeout")
                failure.code, failure.retryable = "UPSTREAM_TIMEOUT", True
                raise failure
            raw = response.model_dump(mode="json")
            from .contracts.generated import ProviderJudicialPage, ProviderToolSnapshot
            (ProviderJudicialPage if judicial else ProviderToolSnapshot).model_validate(raw)
            if raw["binding_credit_code"] != subject.credit_code.root or raw["tool_name"] != name:
                failure = ProviderError("Collection subject mismatch")
                failure.code, failure.retryable = "SUBJECT_RESPONSE_MISMATCH", False
                raise failure
            records = [ProviderRecord.model_validate(row) for row in raw["records"]]
            invalid = any(row.record_credit_code not in (None, subject.credit_code.root) for row in records)
            invalid |= len({row.record_id for row in records}) != len(records)
            invalid |= judicial and (raw["page_number"] != page_number or raw["page_size"] != 20)
            old_records = {row.record_id: row for page in self._pages(key, batch) for row in page.records} if batch else {}
            for row in records:
                if row.record_id in old_records and old_records[row.record_id] != row:
                    invalid = True
            all_records = {**old_records, **{row.record_id: row for row in records}}
            total = raw.get("total_count") if judicial else len(records)
            more = raw.get("has_more") if judicial else False
            invalid |= total is not None and total < len(all_records)
            invalid |= judicial and not records and total is not None and total > len(old_records)
            if invalid:
                failure = ProviderError("Collection page invalid or changed")
                failure.code, failure.retryable = "UPSTREAM_INVALID", False
                raise failure
            page = StoredCollectionPage(batch_id=batch.batch_id if batch else uuid4(), page_number=page_number,
                                         queried_at=raw["queried_at"], records=records)
            updated = StoredCollectionBatch(
                key=key, batch_id=page.batch_id, revision=batch.revision + 1 if batch else 1,
                first_fetched_at=min(batch.first_fetched_at, page.queried_at) if batch else page.queried_at,
                last_fetched_at=max(batch.last_fetched_at, page.queried_at) if batch else page.queried_at,
                total_count=total, has_more=more,
                total_changed=(batch.total_changed or (batch.total_count is not None and total is not None
                                                       and batch.total_count != total)) if batch else False,
                collected_count=len(all_records),
            )
            return self._store.commit(updated, page, claim_id=claim.claim_id,
                                      expected_revision=batch.revision if batch else None), "live"
        except CollectionConflictError:
            if batch is not None and self._store.get_page(key, batch.batch_id, page_number) is not None:
                found = self._store.get_batch(key, batch.batch_id)
                if found is not None:
                    return found, "cache"
            raise
        except (ValueError, TypeError):
            failure = ProviderError("Collection response invalid")
            failure.code, failure.retryable = "UPSTREAM_INVALID", False
            raise failure from None
        finally:
            self._store.finish(claim.claim_id)

    def overview(self, actor: ActorContext, sid: UUID) -> CollectionOverview:
        """COL-IF-01/03：读取已确认主体固定批次的概览；不发起上游查询。"""
        try:
            workspace, bindings = self._state(actor, sid)
            subject = workspace.current_subject
            assert subject is not None
            tools: list[dict[str, Any]] = []
            with self._lock:
                for category, names in PLAN.items():
                    for name in names:
                        entry = bindings.entries[name]
                        batch = self._store.get_batch(self._key(subject, name), entry.batch_id) if entry.batch_id else None
                        if batch is not None and bindings.observed.get(name) != batch.revision:
                            bindings.observed[name] = batch.revision
                            bindings.revision += 1
                        pages = self._pages(self._key(subject, name), batch) if batch else []
                        complete = (batch is not None and batch.has_more is False and not batch.total_changed
                                    and batch.total_count is not None and batch.total_count == batch.collected_count)
                        state = ("empty" if batch.collected_count == 0 else "complete") if batch and complete else "partial" if batch else "error" if entry.error else "not_requested"
                        next_page = (len(pages) + 1 if batch and category == Category.judicial and batch.has_more is not False
                                     and pages and pages[-1].records else None)
                        tools.append({
                            "tool_name": name, "category": category.value,
                            "batch_id": batch.batch_id if batch else None,
                            "batch_revision": batch.revision if batch else None,
                            "state": state, "collected_count": batch.collected_count if batch else 0,
                            "total_count": batch.total_count if batch else None,
                            "has_more": batch.has_more if batch else None, "next_upstream_page": next_page,
                            "first_fetched_at": batch.first_fetched_at if batch else None,
                            "last_fetched_at": batch.last_fetched_at if batch else None,
                            "obtained_from": entry.obtained_from if batch else "none",
                            "report_batch_id": entry.report_batch_id,
                            "report_included_count": len(entry.report_ids),
                            "last_error": entry.error.model_dump(mode="json") if entry.error else None,
                            "diagnostic": entry.diagnostic.model_dump(mode="json") if entry.diagnostic else None,
                            "total_changed": batch.total_changed if batch else False,
                        })
                return CollectionOverview.model_validate({
                    "session_id": sid, "session_generation": workspace.session_generation,
                    "subject_credit_code": subject.credit_code.root, "collection_revision": bindings.revision,
                    "tools": tools, "report_evidence_version": workspace.payload.api_status.evidence_version if workspace.payload else None,
                    "report_evidence_count": len(workspace.payload.evidence_list) if workspace.payload else 0,
                })
        except StorageError:
            raise _error("STORAGE_UNAVAILABLE") from None

    def records(
        self, actor: ActorContext, sid: UUID, tool_name: CollectionToolName,
        batch_id: UUID, *, page: int = 1,
    ) -> CollectionRecordsPage:
        """COL-IF-01/04：当前绑定批次的存量展示页，每页20，不取上游。"""
        workspace, bindings = self._state(actor, sid)
        subject = workspace.current_subject
        assert subject is not None
        name = tool_name.value
        if bindings.entries[name].batch_id != batch_id:
            raise _error("RESOURCE_NOT_FOUND")
        if isinstance(page, bool) or page < 1:
            raise _error("INPUT_INVALID")
        try:
            key = self._key(subject, name)
            batch = self._store.get_batch(key, batch_id)
            if batch is None:
                raise _error("RESOURCE_NOT_FOUND")
            rows: dict[str, tuple[ProviderRecord, datetime]] = {}
            for stored in self._pages(key, batch):
                for row in stored.records:
                    rows.setdefault(row.record_id, (row, stored.queried_at))
            current = self.overview(actor, sid)
            category = next(category for category, names in PLAN.items() if name in names)
            values = list(rows.values())[(page - 1) * 20:page * 20]
            items = [{**row.model_dump(mode="json"), "record_key": hashlib.sha256(
                f"{batch_id}:{name}:{row.record_id}".encode()).hexdigest(),
                "subject_credit_code": subject.credit_code.root, "category": category.value,
                "tool_name": name, "source": "tianyan", "snapshot_time": at,
                "verification_status": "original_not_verified"} for row, at in values]
            return CollectionRecordsPage.model_validate({
                "session_id": sid, "session_generation": workspace.session_generation,
                "subject_credit_code": subject.credit_code.root, "tool_name": name,
                "batch_id": batch_id, "batch_revision": batch.revision,
                "collection_revision": current.collection_revision, "page": page, "page_size": 20,
                "items": items, "next_page": page + 1 if page * 20 < len(rows) else None,
            })
        except StorageError:
            raise _error("STORAGE_UNAVAILABLE") from None

    def _category_batch(
        self, actor: ActorContext, sid: UUID, subject: Subject, category: Category,
        *, record_limit: int = 200, bypass: bool = False,
    ) -> ProviderCategoryBatch:
        """首查/原类别重查的报告窗口投影；公共浏览页与报告纳入范围独立。"""
        _, bindings = self._state(actor, sid)
        records: list[ProviderRecord] = []
        coverage: list[dict[str, Any]] = []
        successes: list[datetime] = []
        first_failure: ProviderError | None = None
        adopted: dict[str, tuple[UUID, dict[str, datetime]]] = {}
        for name in PLAN[category]:
            entry = bindings.entries[name]
            budget = record_limit - len(records)
            if category == Category.judicial and budget <= 0:
                existing = self._store.latest(self._key(subject, name))
                if existing is not None and entry.batch_id is None:
                    entry.batch_id, entry.obtained_from = existing.batch_id, "cache"
                coverage.append(dict(tool_name=name,status="not_requested",accepted_count=0,total_count=None,has_more=None))
                continue
            try:
                batch, obtained = self._fetch(subject, name, refresh=bypass)
                entry.batch_id, entry.obtained_from = batch.batch_id, obtained
                entry.error, entry.diagnostic = None, None
                key = self._key(subject, name)
                first = self._store.get_page(key, batch.batch_id, 1)
                if first is None:
                    raise StorageError("Collection first page unavailable")
                successes.append(first.queried_at)
                chosen = first.records[:min(20, budget)] if category == Category.judicial else first.records
                records.extend(chosen)
                adopted[name] = (batch.batch_id, {item.record_id: first.queried_at for item in chosen})
                if category == Category.judicial:
                    # 首轮报告只使用首页，公共库已完整取得也不代表本报告包含后续页。
                    complete = batch.total_count is not None and batch.total_count == len(chosen) and batch.has_more is False and not batch.total_changed
                    coverage.append(dict(tool_name=name,status=("complete" if chosen else "empty") if complete else "partial",
                                         accepted_count=len(chosen),total_count=batch.total_count,
                                         has_more=False if complete else True if batch.total_count is not None and batch.total_count > len(chosen) else None))
            except ProviderError as exc:
                first_failure = first_failure or exc
                entry.error = ErrorInfo(code=exc.code,hint_id=HintCode.QUERY_ERROR,fields=[],retryable=exc.retryable)
                entry.diagnostic = exc.diagnostic
                if category == Category.judicial:
                    coverage.append(dict(tool_name=name,status="error",accepted_count=0,total_count=None,has_more=None))
        if first_failure is not None and (category != Category.judicial or not successes):
            raise first_failure
        self._projections[(sid, bindings.generation, category)] = adopted
        partial = any(item["status"] not in ("complete", "empty") for item in coverage)
        return ProviderCategoryBatch(
            binding_credit_code=subject.credit_code.root, category=category,
            queried_at=min(successes) if successes else self._clock(),
            scope_description=SCOPE[category] + ("；报告仅覆盖首轮选定材料" if category == Category.judicial else "；完整取得范围"),
            records=records, completeness="partial" if partial else "complete",
            tool_coverage=[ToolCoverage.model_validate(item) for item in coverage] if category == Category.judicial else [],
            error_code=first_failure.code if first_failure else None,
            diagnostic=first_failure.diagnostic if first_failure else None,
        )

    def _accept_projection(self, actor: ActorContext, sid: UUID, category: Category) -> None:
        """只有原报告编排已接受该类别后，才更新报告使用批次/记录映射。"""
        _, bindings = self._state(actor, sid)
        selected = self._projections.pop((sid, bindings.generation, category), {})
        for name in PLAN[category]:
            entry = bindings.entries[name]
            chosen = selected.get(name)
            entry.report_batch_id = chosen[0] if chosen else None
            entry.report_times = chosen[1] if chosen else {}
            entry.report_ids = set(entry.report_times)

    def _snapshot_at(self, actor: ActorContext, sid: UUID, category: Category, record_id: str, fallback: datetime) -> datetime:
        """报告中每条记录沿用所属页的原时间，不把混合批次统一伪装成新查。"""
        _, bindings = self._state(actor, sid)
        selected = self._projections.get((sid, bindings.generation, category), {})
        return next((times[record_id] for _, times in selected.values() if record_id in times), fallback)

    def _start(
        self, actor: ActorContext, sid: UUID,
        command: LoadCollectionPageCommand | RefreshCollectionToolCommand, key: UUID, kind: str,
    ) -> OperationHandle:
        """原子登记浏览任务；幂等重放优先于修订冲突，不自动扩大工具范围。"""
        workspace, bindings = self._state(actor, sid)
        fingerprint = command.model_dump_json()
        identity = (actor.actor_id, sid, kind, key)
        with self._lock:
            old_id = self._keys.get(identity)
            if old_id is not None:
                old = self._tasks.get(old_id)
                if old is None or old.handle.session_generation != workspace.session_generation or old.fingerprint != fingerprint:
                    raise _error("IDEMPOTENCY_CONFLICT")
                return old.handle.model_copy(deep=True)
            current = self.overview(actor, sid)
            if command.expected_generation != workspace.session_generation or command.expected_collection_revision != current.collection_revision:
                raise _error("OPERATION_CONFLICT")
            name = command.tool_name.value
            entry = bindings.entries[name]
            expected_batch = command.batch_id if isinstance(command, LoadCollectionPageCommand) else command.expected_batch_id
            if entry.batch_id != expected_batch:
                raise _error("RESOURCE_NOT_FOUND")
            if isinstance(command, LoadCollectionPageCommand):
                row = next(item for item in current.tools if item.tool_name.value == name)
                next_page = row.next_upstream_page.root if row.next_upstream_page else None
                assert workspace.current_subject is not None
                exists = self._store.get_page(self._key(workspace.current_subject, name), command.batch_id, command.page_number)
                if exists is None and command.page_number != next_page:
                    raise _error("OPERATION_CONFLICT")
            handle = self._sessions._begin_collection(actor, sid, workspace.session_generation, uuid4())
            self._sessions.activity(actor, sid)
            task = _Task(actor, handle, kind, fingerprint, self._clock())
            self._tasks[handle.operation_id] = task
            self._keys[identity] = handle.operation_id
        if self._submitter is not None:
            self._submitter(lambda: self._run(task, command))
        else:
            self._executor.submit(self._run, task, command)
        return handle.model_copy(deep=True)

    def _run(self, task: _Task, command: LoadCollectionPageCommand | RefreshCollectionToolCommand) -> None:
        """执行单工具采集，安全公共提交与私有会话写回分别守卫。"""
        if task.state == "failed":
            return
        task.state = "running"
        name = command.tool_name.value
        try:
            workspace, bindings = self._state(task.actor, task.handle.session_id)
            if workspace.session_generation != task.handle.session_generation:
                raise _error("OPERATION_CONFLICT")
            subject = workspace.current_subject
            assert subject is not None
            key = self._key(subject, name)
            old = self._store.get_batch(key, command.batch_id) if isinstance(command, LoadCollectionPageCommand) else None
            if isinstance(command, LoadCollectionPageCommand) and old is None:
                raise _error("RESOURCE_NOT_FOUND")
            batch, obtained = self._fetch(subject, name, batch=old,
                page_number=command.page_number if isinstance(command, LoadCollectionPageCommand) else 1,
                refresh=isinstance(command, RefreshCollectionToolCommand))
            workspace, bindings = self._state(task.actor, task.handle.session_id)
            if workspace.session_generation != task.handle.session_generation:
                raise _error("OPERATION_CONFLICT")
            if task.state == "failed" or (self._clock() - task.started_at).total_seconds() >= 60:
                raise _error("UPSTREAM_TIMEOUT")
            with self._lock:
                entry = bindings.entries[name]
                if entry.batch_id != batch.batch_id:
                    bindings.revision += 1
                entry.batch_id, entry.obtained_from = batch.batch_id, obtained
                entry.error, entry.diagnostic = None, None
            task.result = self.overview(task.actor, task.handle.session_id)
            task.state = "succeeded"
        except ProviderError as exc:
            if task.state == "failed" and task.error is not None:
                return
            task.error = ErrorInfo(code=exc.code, hint_id=HintCode.QUERY_ERROR, fields=[], retryable=exc.retryable)
            task.state = "failed"
            try:
                workspace, bindings = self._state(task.actor, task.handle.session_id)
                if workspace.session_generation == task.handle.session_generation:
                    with self._lock:
                        bindings.entries[name].error = task.error
                        bindings.entries[name].diagnostic = exc.diagnostic
                        bindings.revision += 1
            except ApplicationError:
                pass
        except (ApplicationError, StorageError, CollectionConflictError) as exc:
            if task.state == "failed" and task.error is not None:
                return
            task.error = (exc.info if isinstance(exc, ApplicationError) else
                          _error("STORAGE_UNAVAILABLE" if isinstance(exc, StorageError) else "OPERATION_CONFLICT").info)
            task.state = "failed"
            try:
                workspace, bindings = self._state(task.actor, task.handle.session_id)
                if workspace.session_generation == task.handle.session_generation:
                    bindings.entries[name].error = task.error
                    bindings.entries[name].diagnostic = None
                    bindings.revision += 1
            except ApplicationError:
                pass
        except Exception:
            task.error = _error("INTERNAL_ERROR").info
            task.state = "failed"
        finally:
            self._sessions._finish_collection(task.actor, task.handle)

    def load_page(
        self, actor: ActorContext, sid: UUID, command: LoadCollectionPageCommand, key: UUID,
    ) -> OperationHandle:
        """COL-IF-04/06：幂等取得所选司法工具下一页，保留报告和私人草稿。"""
        return self._start(actor, sid, command, key, "load_page")

    def refresh_tool(
        self, actor: ActorContext, sid: UUID, command: RefreshCollectionToolCommand, key: UUID,
    ) -> OperationHandle:
        """COL-IF-05/06：主动新建单工具成功批次；失败保留旧资料。"""
        return self._start(actor, sid, command, key, "refresh_tool")

    def operation(self, actor: ActorContext, sid: UUID, opid: UUID) -> CollectionOperationView:
        """COL-DATA-04：只读本会话采集任务，公共数据不意味着任务公开。"""
        workspace, _ = self._state(actor, sid)
        with self._lock:
            task = self._tasks.get(opid)
            if (task is None or task.actor.actor_id != actor.actor_id or task.handle.session_id != sid
                    or task.handle.session_generation != workspace.session_generation):
                raise _error("RESOURCE_NOT_FOUND")
            if task.state in ("queued", "running") and (self._clock() - task.started_at).total_seconds() >= 60:
                task.state, task.result, task.error = "failed", None, _error("UPSTREAM_TIMEOUT").info
                self._sessions._finish_collection(actor, task.handle)
            return CollectionOperationView.model_validate({
                **task.handle.model_dump(mode="json"), "kind": task.kind, "state": task.state,
                "result": task.result.model_dump(mode="json") if task.result else None,
                "error": task.error.model_dump(mode="json") if task.error else None,
            })
