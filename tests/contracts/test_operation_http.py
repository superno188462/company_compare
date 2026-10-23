"""CONTRACT-1.0：BE-IF-06 查询任务 HTTP 轮询契约。"""

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import create_app
from company_screening.contracts.boundary import (
    OperationView,
    ProviderCandidate,
    ProviderCategoryBatch,
    ProviderSearchPage,
    SearchCommand,
)
from company_screening.contracts.generated import Category, Subject
from company_screening.services import ScreeningService, SessionService


class OperationHttpCompanyData:
    def search(self, command: SearchCommand) -> ProviderSearchPage:
        return ProviderSearchPage(items=[ProviderCandidate(
            name="测试企业甲",
            credit_code="91310000MA1ABCDEF0",
            registered_region=None,
            legal_representative=None,
            established_on=None,
        )], next_cursor=None, total=1)

    def fetch_category(self, subject: Subject, category: Category) -> ProviderCategoryBatch:
        raise NotImplementedError()


def test_operation_http_returns_queued_view_for_same_cookie() -> None:
    """BE-IF-06：确认返回的任务可由同一所有者通过只读端点轮询。"""
    sessions = SessionService()
    screening = ScreeningService(
        session_service=sessions,
        company_data=OperationHttpCompanyData(),
        task_submitter=lambda task: None,
    )
    app = create_app(screening_service=screening, session_service=sessions)

    with TestClient(app) as client:
        created = client.post("/api/v1/sessions", headers={"Idempotency-Key": str(uuid4())}).json()
        sid = created["session_id"]
        search = client.post(
            f"/api/v1/sessions/{sid}/search",
            json={"query": "测试企业甲"},
            headers={"Idempotency-Key": str(uuid4())},
        ).json()
        confirmed = client.post(
            f"/api/v1/sessions/{sid}/confirm",
            json={
                "search_id": search["search_id"],
                "candidate_id": search["items"][0]["candidate_id"],
                "expected_generation": 0,
                "discard_draft": False,
            },
            headers={"Idempotency-Key": str(uuid4())},
        ).json()
        response = client.get(f"/api/v1/sessions/{sid}/operations/{confirmed['operation_id']}")

    assert response.status_code == 200
    view = OperationView.model_validate(response.json())
    assert view.state == "queued"
    assert view.phase == "query"
    assert view.result is None
    assert view.error is None
