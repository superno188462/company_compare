"""CONTRACT-1.0：BE-IF-03 搜索 HTTP 垂直切片。"""

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.dependencies import get_actor
from company_screening.contracts.boundary import (
    ActorContext,
    ErrorEnvelope,
    ProviderCandidate,
    ProviderCategoryBatch,
    ProviderSearchPage,
    SearchCommand,
    SearchResult,
)
from company_screening.contracts.generated import Category, Subject
from company_screening.errors import ProviderError
from company_screening.services import ScreeningService, SessionService


class HttpFakeCompanyData:
    def __init__(self) -> None:
        self.calls = 0
        self.error: ProviderError | None = None

    def search(self, command: SearchCommand) -> ProviderSearchPage:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ProviderSearchPage(items=[ProviderCandidate(
            name="测试企业甲", credit_code="91310000MA1ABCDEF0",
            registered_region=None, legal_representative=None, established_on=None,
        )], next_cursor=None, total=1)

    def fetch_category(self, subject: Subject, category: Category) -> ProviderCategoryBatch:
        raise NotImplementedError()


def _test_context() -> tuple[ActorContext, SessionService, HttpFakeCompanyData, ScreeningService]:
    actor = ActorContext(actor_id=uuid4())
    sessions = SessionService()
    provider = HttpFakeCompanyData()
    service = ScreeningService(session_service=sessions, company_data=provider)
    return actor, sessions, provider, service


def test_search_http_returns_contract_result_and_replays_idempotently() -> None:
    """BE-IF-03 / DATA-05：真实路由调用服务，同键重放不重复查询。"""
    actor, sessions, provider, service = _test_context()
    workspace = sessions.create(actor)
    app = create_app(screening_service=service)
    app.dependency_overrides[get_actor] = lambda: actor
    key = str(uuid4())

    with TestClient(app) as client:
        first = client.post(
            f"/api/v1/sessions/{workspace.session_id}/search",
            json={"query": "测试企业甲"}, headers={"Idempotency-Key": key},
        )
        replay = client.post(
            f"/api/v1/sessions/{workspace.session_id}/search",
            json={"query": "测试企业甲"}, headers={"Idempotency-Key": key},
        )

    assert first.status_code == 200
    assert replay.status_code == 200
    first_result = SearchResult.model_validate(first.json())
    assert SearchResult.model_validate(replay.json()) == first_result
    assert first_result.items[0].selectable is True
    assert provider.calls == 1


def test_search_http_maps_provider_limit_to_sanitized_error() -> None:
    """BE-ERR-01：上游限额返回稳定503错误包。"""
    actor, sessions, provider, service = _test_context()
    workspace = sessions.create(actor)
    upstream = ProviderError("private quota detail")
    upstream.code = "UPSTREAM_LIMIT"
    upstream.retryable = False
    provider.error = upstream
    app = create_app(screening_service=service)
    app.dependency_overrides[get_actor] = lambda: actor

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/sessions/{workspace.session_id}/search",
            json={"query": "测试企业甲"},
            headers={"Idempotency-Key": str(uuid4())},
        )

    assert response.status_code == 503
    assert ErrorEnvelope.model_validate(response.json()).error.code == "UPSTREAM_LIMIT"
    assert "private quota detail" not in response.text
