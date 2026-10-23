"""CONTRACT-1.0：BE-IF-03、DATA-05 搜索应用服务契约。"""

from datetime import date
from uuid import uuid4

import pytest

from company_screening.contracts.boundary import (
    ActorContext,
    ProviderCandidate,
    ProviderCategoryBatch,
    ProviderSearchPage,
    SearchCommand,
)
from company_screening.contracts.generated import Category, Subject
from company_screening.errors import ApplicationError, ProviderError
from company_screening.services import ScreeningService, SessionService


class FakeCompanyData:
    """只模拟端口契约，不复制应用服务实现。"""

    def __init__(self, page: ProviderSearchPage) -> None:
        self.page = page
        self.search_calls: list[SearchCommand] = []
        self.error: ProviderError | None = None

    def search(self, command: SearchCommand) -> ProviderSearchPage:
        self.search_calls.append(command)
        if self.error is not None:
            raise self.error
        return self.page.model_copy(deep=True)

    def fetch_category(self, subject: Subject, category: Category) -> ProviderCategoryBatch:
        raise NotImplementedError()


def _single_candidate_page() -> ProviderSearchPage:
    return ProviderSearchPage(items=[ProviderCandidate(
        name="测试企业甲",
        credit_code="91310000MA1ABCDEF0",
        registered_region=None,
        legal_representative="测试法人",
        established_on=date(2020, 1, 2),
    )], next_cursor=None, total=1)


def test_activity_extends_owned_session_expiry() -> None:
    """BE-NFR-02：明确用户活动续期，读取仍由restore保持不续期。"""
    sessions = SessionService()
    actor = ActorContext(actor_id=uuid4())
    created = sessions.create(actor)

    renewed = sessions.activity(actor, created.session_id)
    restored = sessions.restore(actor, created.session_id)

    assert renewed.expires_at > created.expires_at
    assert restored.expires_at == renewed.expires_at


def test_search_returns_candidate_without_confirming_single_result() -> None:
    """BE-IF-03：单候选仍只返回卡片，不自动绑定主体。"""
    sessions = SessionService()
    actor = ActorContext(actor_id=uuid4())
    workspace = sessions.create(actor)
    provider = FakeCompanyData(_single_candidate_page())
    service = ScreeningService(session_service=sessions, company_data=provider)

    result = service.search(actor, workspace.session_id, SearchCommand(query=" 测试企业甲 "), uuid4())

    assert len(provider.search_calls) == 1
    assert provider.search_calls[0].query == "测试企业甲"
    assert len(result.items) == 1
    assert result.items[0].selectable is True
    assert result.items[0].candidate_id
    assert sessions.restore(actor, workspace.session_id).current_subject is None


def test_search_marks_candidate_without_credit_code_unselectable() -> None:
    """BE-IF-03：缺少合法信用代码的候选不能进入确认。"""
    sessions = SessionService()
    actor = ActorContext(actor_id=uuid4())
    workspace = sessions.create(actor)
    provider = FakeCompanyData(ProviderSearchPage(items=[ProviderCandidate(
        name="测试企业甲", credit_code=None, registered_region=None,
        legal_representative=None, established_on=None,
    )], next_cursor=None, total=1))

    result = ScreeningService(session_service=sessions, company_data=provider).search(
        actor, workspace.session_id, SearchCommand(query="测试企业甲"), uuid4()
    )

    assert result.items[0].selectable is False


def test_search_same_idempotency_key_replays_without_provider_call() -> None:
    """DATA-05：同键同内容回放原搜索，不重复消耗提供方调用。"""
    sessions = SessionService()
    actor = ActorContext(actor_id=uuid4())
    workspace = sessions.create(actor)
    provider = FakeCompanyData(_single_candidate_page())
    service = ScreeningService(session_service=sessions, company_data=provider)
    key = uuid4()
    command = SearchCommand(query="测试企业甲")

    first = service.search(actor, workspace.session_id, command, key)
    replay = service.search(actor, workspace.session_id, command, key)

    assert replay == first
    assert len(provider.search_calls) == 1


def test_search_same_idempotency_key_with_different_input_conflicts() -> None:
    """DATA-05：同键不同内容拒绝，原结果仍保留。"""
    sessions = SessionService()
    actor = ActorContext(actor_id=uuid4())
    workspace = sessions.create(actor)
    provider = FakeCompanyData(_single_candidate_page())
    service = ScreeningService(session_service=sessions, company_data=provider)
    key = uuid4()
    service.search(actor, workspace.session_id, SearchCommand(query="测试企业甲"), key)

    with pytest.raises(ApplicationError) as caught:
        service.search(actor, workspace.session_id, SearchCommand(query="测试企业乙"), key)

    assert caught.value.info.code == "IDEMPOTENCY_CONFLICT"
    assert len(provider.search_calls) == 1


def test_search_checks_session_owner_before_provider() -> None:
    """DATA-05：另一所有者不能借会话ID调用提供方。"""
    sessions = SessionService()
    owner = ActorContext(actor_id=uuid4())
    workspace = sessions.create(owner)
    provider = FakeCompanyData(_single_candidate_page())

    with pytest.raises(ApplicationError) as caught:
        ScreeningService(session_service=sessions, company_data=provider).search(
            ActorContext(actor_id=uuid4()), workspace.session_id,
            SearchCommand(query="测试企业甲"), uuid4(),
        )

    assert caught.value.info.code == "RESOURCE_NOT_FOUND"
    assert provider.search_calls == []


def test_search_maps_provider_error_without_exposing_detail() -> None:
    """BE-ERR-01：提供方错误转换成应用错误结构。"""
    sessions = SessionService()
    actor = ActorContext(actor_id=uuid4())
    workspace = sessions.create(actor)
    provider = FakeCompanyData(_single_candidate_page())
    upstream = ProviderError("private provider detail")
    upstream.code = "UPSTREAM_LIMIT"
    upstream.retryable = False
    provider.error = upstream

    with pytest.raises(ApplicationError) as caught:
        ScreeningService(session_service=sessions, company_data=provider).search(
            actor, workspace.session_id, SearchCommand(query="测试企业甲"), uuid4()
        )

    assert caught.value.info.code == "UPSTREAM_LIMIT"
    assert caught.value.info.retryable is False
    assert "private provider detail" not in str(caught.value)
