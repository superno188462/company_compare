"""CONTRACT-1.0：BE-IF-03 人工确认主体 HTTP 契约。"""

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import create_app
from company_screening.contracts.boundary import (
    OperationHandle,
    ProviderCandidate,
    ProviderCategoryBatch,
    ProviderSearchPage,
    SearchCommand,
    WorkspaceState,
)
from company_screening.contracts.generated import Category, Subject
from company_screening.services import ScreeningService, SessionService


class ConfirmHttpCompanyData:
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


def test_confirm_http_updates_workspace_only_after_explicit_request() -> None:
    """BE-IF-01/03：同一Cookie明确确认后，恢复视图才出现主体。"""
    sessions = SessionService()
    screening = ScreeningService(
        session_service=sessions,
        company_data=ConfirmHttpCompanyData(),
        task_submitter=lambda task: None,
    )
    app = create_app(screening_service=screening, session_service=sessions)

    with TestClient(app) as client:
        created = WorkspaceState.model_validate(client.post(
            "/api/v1/sessions", headers={"Idempotency-Key": str(uuid4())},
        ).json())
        search_response = client.post(
            f"/api/v1/sessions/{created.session_id}/search",
            json={"query": "测试企业甲"},
            headers={"Idempotency-Key": str(uuid4())},
        )
        search_result = search_response.json()
        before = WorkspaceState.model_validate(client.get(f"/api/v1/sessions/{created.session_id}").json())
        confirmed = client.post(
            f"/api/v1/sessions/{created.session_id}/confirm",
            json={
                "search_id": search_result["search_id"],
                "candidate_id": search_result["items"][0]["candidate_id"],
                "expected_generation": 0,
                "discard_draft": False,
            },
            headers={"Idempotency-Key": str(uuid4())},
        )
        after = WorkspaceState.model_validate(client.get(f"/api/v1/sessions/{created.session_id}").json())

    assert before.current_subject is None
    assert confirmed.status_code == 202
    handle = OperationHandle.model_validate(confirmed.json())
    assert handle.session_generation == 1
    assert after.current_subject is not None
    assert after.current_subject.name == "测试企业甲"
    assert after.active_operation == handle
