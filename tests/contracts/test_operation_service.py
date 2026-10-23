"""CONTRACT-1.0：BE-IF-06 查询任务只读状态契约。"""

from uuid import uuid4

import pytest

from company_screening.contracts.boundary import (
    ActorContext,
    ConfirmSubjectCommand,
    OperationHandle,
    ProviderCandidate,
    ProviderCategoryBatch,
    ProviderSearchPage,
    SearchCommand,
    WorkspaceState,
)
from company_screening.contracts.generated import Category, Subject
from company_screening.errors import ApplicationError
from company_screening.services import ScreeningService, SessionService


class OperationFakeCompanyData:
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


def _queued_operation() -> tuple[ActorContext, SessionService, ScreeningService, WorkspaceState, OperationHandle]:
    actor = ActorContext(actor_id=uuid4())
    sessions = SessionService()
    workspace = sessions.create(actor)
    service = ScreeningService(
        session_service=sessions,
        company_data=OperationFakeCompanyData(),
        task_submitter=lambda task: None,
    )
    search = service.search(actor, workspace.session_id, SearchCommand(query="测试企业甲"), uuid4())
    handle = service.confirm(actor, workspace.session_id, ConfirmSubjectCommand(
        search_id=search.search_id,
        candidate_id=search.items[0].candidate_id,
        expected_generation=0,
        discard_draft=False,
    ), uuid4())
    return actor, sessions, service, workspace, handle


def test_operation_returns_queued_query_without_extending_session() -> None:
    """BE-IF-06 / DATA-05：轮询返回完整状态结构，但不作为用户活动续期。"""
    actor, sessions, service, workspace, handle = _queued_operation()
    before = sessions.restore(actor, workspace.session_id)

    view = service.operation(actor, workspace.session_id, handle.operation_id)
    after = sessions.restore(actor, workspace.session_id)

    assert view.operation_id == handle.operation_id
    assert view.session_generation == 1
    assert view.state == "queued"
    assert view.phase == "query"
    assert view.result is None
    assert view.error is None
    assert after.expires_at == before.expires_at


def test_operation_id_does_not_grant_another_owner_access() -> None:
    """DATA-05：任务ID和会话ID都只是定位符，不能替代所有者Cookie。"""
    _, _, service, workspace, handle = _queued_operation()

    with pytest.raises(ApplicationError) as caught:
        service.operation(
            ActorContext(actor_id=uuid4()),
            workspace.session_id,
            handle.operation_id,
        )

    assert caught.value.info.code == "RESOURCE_NOT_FOUND"
