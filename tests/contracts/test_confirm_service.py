"""CONTRACT-1.0：BE-IF-03 人工确认主体应用服务契约。"""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from company_screening.contracts.boundary import (
    ActorContext,
    ConfirmSubjectCommand,
    ProviderCandidate,
    ProviderCategoryBatch,
    ProviderSearchPage,
    SearchCommand,
    SearchResult,
    WorkspaceState,
)
from company_screening.contracts.generated import Category, Subject
from company_screening.errors import ApplicationError
from company_screening.services import ScreeningService, SessionService


class ConfirmFakeCompanyData:
    """为搜索阶段提供规范化候选，不实现详情查询。"""

    def __init__(self, candidates: list[ProviderCandidate]) -> None:
        self.candidates = candidates

    def search(self, command: SearchCommand) -> ProviderSearchPage:
        return ProviderSearchPage(items=self.candidates, next_cursor=None, total=len(self.candidates))

    def fetch_category(
        self, subject: Subject, category: Category, *, record_limit: int = 200,
    ) -> ProviderCategoryBatch:
        raise NotImplementedError()


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 23, 8, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def _candidate(*, credit_code: str | None = "91310000MA1ABCDEF0", name: str = "测试企业甲") -> ProviderCandidate:
    return ProviderCandidate(
        name=name,
        credit_code=credit_code,
        registered_region="上海市",
        legal_representative="测试法人",
        established_on=date(2020, 1, 2),
    )


def _search_context(
    candidates: list[ProviderCandidate] | None = None,
) -> tuple[ActorContext, SessionService, ScreeningService, MutableClock, WorkspaceState, SearchResult]:
    actor = ActorContext(actor_id=uuid4())
    sessions = SessionService()
    workspace = sessions.create(actor)
    clock = MutableClock()
    service = ScreeningService(
        session_service=sessions,
        company_data=ConfirmFakeCompanyData(candidates or [_candidate()]),
        clock=clock,
        task_submitter=lambda task: None,
    )
    result = service.search(actor, workspace.session_id, SearchCommand(query="测试企业"), uuid4())
    return actor, sessions, service, clock, workspace, result


def test_confirm_binds_selected_candidate_and_creates_query_handle() -> None:
    """BE-IF-03：只有明确确认后才建立主体、代次和查询任务。"""
    actor, sessions, service, clock, workspace, result = _search_context()
    command = ConfirmSubjectCommand(
        search_id=result.search_id,
        candidate_id=result.items[0].candidate_id,
        expected_generation=0,
        discard_draft=False,
    )

    handle = service.confirm(actor, workspace.session_id, command, uuid4())
    restored = sessions.restore(actor, workspace.session_id)

    assert handle.session_id == workspace.session_id
    assert handle.session_generation == 1
    assert restored.session_generation == 1
    assert restored.current_subject is not None
    assert restored.current_subject.name == "测试企业甲"
    assert restored.current_subject.credit_code.root == "91310000MA1ABCDEF0"
    assert restored.current_subject.confirmed_at.root == clock.now
    assert restored.active_operation == handle
    assert restored.payload is None
    assert restored.draft is None


def test_confirm_rejects_generation_conflict_without_changing_workspace() -> None:
    """BE-IF-03 / DATA-05：陈旧页面不能覆盖已变化的主体代次。"""
    actor, sessions, service, _, workspace, result = _search_context()
    command = ConfirmSubjectCommand(
        search_id=result.search_id,
        candidate_id=result.items[0].candidate_id,
        expected_generation=1,
        discard_draft=False,
    )

    with pytest.raises(ApplicationError) as caught:
        service.confirm(actor, workspace.session_id, command, uuid4())

    assert caught.value.info.code == "OPERATION_CONFLICT"
    restored = sessions.restore(actor, workspace.session_id)
    assert restored.session_generation == 0
    assert restored.current_subject is None


def test_confirm_rejects_candidate_from_another_session() -> None:
    """BE-IF-03：候选必须绑定当前会话，不能跨会话复用。"""
    actor, sessions, service, _, first_workspace, result = _search_context()
    other_workspace = sessions.create(actor)
    command = ConfirmSubjectCommand(
        search_id=result.search_id,
        candidate_id=result.items[0].candidate_id,
        expected_generation=0,
        discard_draft=False,
    )

    with pytest.raises(ApplicationError) as caught:
        service.confirm(actor, other_workspace.session_id, command, uuid4())

    assert caught.value.info.code == "CANDIDATE_INVALID"
    assert sessions.restore(actor, first_workspace.session_id).current_subject is None
    assert sessions.restore(actor, other_workspace.session_id).current_subject is None


def test_confirm_rejects_candidate_without_credit_code() -> None:
    """BE-IF-03：缺信用代码的候选不能进入详情查询。"""
    actor, sessions, service, _, workspace, result = _search_context([_candidate(credit_code=None)])
    command = ConfirmSubjectCommand(
        search_id=result.search_id,
        candidate_id=result.items[0].candidate_id,
        expected_generation=0,
        discard_draft=False,
    )

    with pytest.raises(ApplicationError) as caught:
        service.confirm(actor, workspace.session_id, command, uuid4())

    assert caught.value.info.code == "CANDIDATE_INVALID"
    assert sessions.restore(actor, workspace.session_id).current_subject is None


def test_confirm_rejects_expired_search_result() -> None:
    """BE-IF-03：搜索结果到达10分钟有效期后必须重新搜索。"""
    actor, sessions, service, clock, workspace, result = _search_context()
    clock.now += timedelta(minutes=10)
    command = ConfirmSubjectCommand(
        search_id=result.search_id,
        candidate_id=result.items[0].candidate_id,
        expected_generation=0,
        discard_draft=False,
    )

    with pytest.raises(ApplicationError) as caught:
        service.confirm(actor, workspace.session_id, command, uuid4())

    assert caught.value.info.code == "CANDIDATE_INVALID"
    assert sessions.restore(actor, workspace.session_id).current_subject is None


def test_confirm_idempotency_replays_and_rejects_changed_command() -> None:
    """DATA-05：同键同内容回放原句柄，同键不同内容拒绝。"""
    candidates = [_candidate(), _candidate(name="测试企业乙", credit_code="91310000MA1ABCDEFX")]
    actor, sessions, service, _, workspace, result = _search_context(candidates)
    key = uuid4()
    command = ConfirmSubjectCommand(
        search_id=result.search_id,
        candidate_id=result.items[0].candidate_id,
        expected_generation=0,
        discard_draft=False,
    )

    first = service.confirm(actor, workspace.session_id, command, key)
    replay = service.confirm(actor, workspace.session_id, command, key)
    assert replay == first
    assert sessions.restore(actor, workspace.session_id).session_generation == 1

    changed = command.model_copy(update={"candidate_id": result.items[1].candidate_id})
    with pytest.raises(ApplicationError) as caught:
        service.confirm(actor, workspace.session_id, changed, key)
    assert caught.value.info.code == "IDEMPOTENCY_CONFLICT"
