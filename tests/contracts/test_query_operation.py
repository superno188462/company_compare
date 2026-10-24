"""CONTRACT-1.0：BE-IF-03/06 五类查询任务执行与终态契约。"""

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from company_screening.contracts.boundary import (
    ActorContext,
    ConfirmSubjectCommand,
    ProviderCandidate,
    ProviderCategoryBatch,
    ProviderFailureCode,
    ProviderRecord,
    ProviderSearchPage,
    SearchCommand,
)
from company_screening.contracts.generated import Category, HintCode, Subject
from company_screening.errors import ProviderError
from company_screening.services import ScreeningService, SessionService


STAMP = datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc)


def _provider_error(code: ProviderFailureCode, *, retryable: bool = False) -> ProviderError:
    error = ProviderError("private provider detail")
    error.code = code
    error.retryable = retryable
    return error


class QueryFakeCompanyData:
    def __init__(self, *, company_name: str = "测试企业甲") -> None:
        self.company_name = company_name
        self.responses: dict[Category, ProviderCategoryBatch | ProviderError] = {}
        self.fetch_calls: list[Category] = []

    def search(self, command: SearchCommand) -> ProviderSearchPage:
        return ProviderSearchPage(items=[ProviderCandidate(
            name=self.company_name,
            credit_code="91310000MA1ABCDEF0",
            registered_region=None,
            legal_representative=None,
            established_on=None,
        )], next_cursor=None, total=1)

    def fetch_category(
        self, subject: Subject, category: Category, *, record_limit: int = 200,
    ) -> ProviderCategoryBatch:
        self.fetch_calls.append(category)
        response = self.responses[category]
        if isinstance(response, ProviderError):
            raise response
        return response.model_copy(deep=True)


def _batch(
    category: Category,
    *,
    records: list[ProviderRecord] | None = None,
    binding_credit_code: str = "91310000MA1ABCDEF0",
) -> ProviderCategoryBatch:
    return ProviderCategoryBatch(
        binding_credit_code=binding_credit_code,
        category=category,
        queried_at=STAMP,
        scope_description=f"{category.value}测试范围",
        records=records or [],
    )


def _record() -> ProviderRecord:
    return ProviderRecord(
        record_id="REG-001",
        content="公开登记记录：测试企业甲处于存续状态。",
        record_credit_code="91310000MA1ABCDEF0",
        event_time="2026年度",
        source_url="https://example.com/record/REG-001",
        source_publisher="测试公示来源",
    )


def _configure_all_empty(provider: QueryFakeCompanyData) -> None:
    for category in Category:
        provider.responses[category] = _batch(category)


def _confirm(
    service: ScreeningService,
    sessions: SessionService,
    actor: ActorContext,
):
    workspace = sessions.create(actor)
    search = service.search(actor, workspace.session_id, SearchCommand(query="测试企业"), uuid4())
    handle = service.confirm(actor, workspace.session_id, ConfirmSubjectCommand(
        search_id=search.search_id,
        candidate_id=search.items[0].candidate_id,
        expected_generation=0,
        discard_draft=False,
    ), uuid4())
    return workspace.session_id, handle


def test_query_operation_keeps_successes_and_marks_partial_failures() -> None:
    """DATA-02 / BE-IF-06：类别独立记录，失败类别不能冒充empty或发布部分记录。"""
    provider = QueryFakeCompanyData()
    provider.responses = {
        Category.basic: _batch(Category.basic, records=[_record()]),
        Category.abnormal: _batch(Category.abnormal),
        Category.penalty: _provider_error("UPSTREAM_TIMEOUT", retryable=True),
        Category.judicial: _batch(Category.judicial, binding_credit_code="91310000MA1ABCDEFX"),
        Category.asset: _batch(Category.asset),
    }
    sessions = SessionService()
    actor = ActorContext(actor_id=uuid4())
    service = ScreeningService(
        session_service=sessions,
        company_data=provider,
        task_submitter=lambda task: task(),
    )

    sid, handle = _confirm(service, sessions, actor)
    view = service.operation(actor, sid, handle.operation_id)

    assert provider.fetch_calls == list(Category)
    assert view.state == "succeeded"
    assert view.phase == "complete"
    assert view.error is None
    assert view.result is not None
    assert len(view.result.evidence_list) == 1
    assert view.result.evidence_list[0].root.content.startswith("公开登记记录")
    status = view.result.api_status
    assert status.tianyan_status == "partial"
    assert status.categories.basic.root.status == "ok"
    assert status.categories.abnormal.root.status == "empty"
    assert status.categories.penalty.root.status == "error"
    assert status.categories.penalty.root.error_code == "UPSTREAM_TIMEOUT"
    assert status.categories.judicial.root.error_code == "SUBJECT_RESPONSE_MISMATCH"
    assert status.categories.asset.root.status == "empty"
    assert status.llm_status == "error"
    assert HintCode.PARTIAL_COVERAGE in view.result.ui_hint_group
    assert HintCode.REPORT_FAILED in view.result.ui_hint_group
    assert "private provider detail" not in view.model_dump_json()
    restored = sessions.restore(actor, sid)
    assert restored.payload == view.result
    assert restored.active_operation is None


def test_query_operation_all_empty_skips_model_and_reports_information_gap() -> None:
    """DATA-02/03：五类完整成功但全空时不调用模型，也不表述为无风险。"""
    provider = QueryFakeCompanyData()
    _configure_all_empty(provider)
    sessions = SessionService()
    actor = ActorContext(actor_id=uuid4())
    service = ScreeningService(
        session_service=sessions,
        company_data=provider,
        task_submitter=lambda task: task(),
    )

    sid, handle = _confirm(service, sessions, actor)
    result = service.operation(actor, sid, handle.operation_id).result

    assert result is not None
    assert result.evidence_list == []
    assert result.summary_text == ""
    assert result.api_status.tianyan_status == "empty"
    assert result.api_status.llm_status == "skipped_no_evidence"
    assert HintCode.QUERY_EMPTY in result.ui_hint_group
    assert HintCode.NO_EVIDENCE in result.ui_hint_group
    assert HintCode.REPORT_FAILED not in result.ui_hint_group


def test_query_operation_without_provider_finishes_as_query_error() -> None:
    """BE-NFR-03：未配置真实提供方时明确失败，不用合成详情兜底。"""
    sessions = SessionService()
    actor = ActorContext(actor_id=uuid4())
    search_service = ScreeningService(
        session_service=sessions,
        company_data=QueryFakeCompanyData(),
        task_submitter=lambda task: None,
    )
    workspace = sessions.create(actor)
    search = search_service.search(actor, workspace.session_id, SearchCommand(query="测试企业"), uuid4())
    service = ScreeningService(
        session_service=sessions,
        company_data=None,
        task_submitter=lambda task: task(),
    )
    handle = service.confirm(actor, workspace.session_id, ConfirmSubjectCommand(
        search_id=search.search_id,
        candidate_id=search.items[0].candidate_id,
        expected_generation=0,
        discard_draft=False,
    ), uuid4())

    result = service.operation(actor, workspace.session_id, handle.operation_id).result
    assert result is not None
    assert result.api_status.tianyan_status == "error"
    assert all(getattr(result.api_status.categories, category.value).root.error_code == "UPSTREAM_AUTH"
               for category in Category)
    assert HintCode.QUERY_ERROR in result.ui_hint_group


def test_old_generation_query_cannot_overwrite_new_subject() -> None:
    """DATA-05 / BE-IF-06：切换主体后，旧任务迟到也不能写回新工作台。"""
    queued: list[Callable[[], None]] = []
    provider = QueryFakeCompanyData()
    _configure_all_empty(provider)
    sessions = SessionService()
    actor = ActorContext(actor_id=uuid4())
    service = ScreeningService(
        session_service=sessions,
        company_data=provider,
        task_submitter=lambda task: queued.append(task),
    )
    sid, first = _confirm(service, sessions, actor)

    second_search = service.search(actor, sid, SearchCommand(query="测试企业乙"), uuid4())
    second = service.confirm(actor, sid, ConfirmSubjectCommand(
        search_id=second_search.search_id,
        candidate_id=second_search.items[0].candidate_id,
        expected_generation=1,
        discard_draft=False,
    ), uuid4())

    assert len(queued) == 2
    queued[0]()
    old_view = service.operation(actor, sid, first.operation_id)
    assert old_view.state == "failed"
    assert old_view.error is not None
    assert old_view.error.code == "OPERATION_CONFLICT"
    assert sessions.restore(actor, sid).session_generation == 2
    assert sessions.restore(actor, sid).active_operation == second

    queued[1]()
    assert service.operation(actor, sid, second.operation_id).state == "succeeded"
    assert sessions.restore(actor, sid).session_generation == 2
