"""CONTRACT-1.0：BE-IF-01/02、DATA-05；调用真实服务，不 Mock 被测方法。

占位骨架阶段应真实失败，不用 xfail/skip 或断言 NotImplementedError 伪造通过。
"""
from uuid import uuid4

import pytest

from company_screening.contracts.boundary import ActorContext, ConfirmSubjectCommand, SearchCommand
from company_screening.errors import ApplicationError
from company_screening.services import ScreeningService, SessionService


def test_new_session_has_no_subject_draft_or_report():
    """BE-IF-01 / DATA-05：显式创建只产生空私有会话。"""
    state = SessionService().create(ActorContext(actor_id=uuid4()))
    assert state.session_generation == 0
    assert state.current_subject is None
    assert state.payload is None
    assert state.draft is None
    assert state.active_operation is None
    assert state.share_receipts == []


def test_restore_keeps_identity_and_does_not_extend_expiry():
    """BE-IF-01 / DATA-05：恢复读取不续期。"""
    service, actor = SessionService(), ActorContext(actor_id=uuid4())
    created = service.create(actor)
    restored = service.restore(actor, created.session_id)
    assert restored.session_id == created.session_id
    assert restored.expires_at == created.expires_at
    assert restored.current_subject is None


def test_other_owner_cannot_restore_session():
    """DATA-05 / BE-ERR-01：非所有者与不存在统一不可用。"""
    service = SessionService()
    created = service.create(ActorContext(actor_id=uuid4()))
    with pytest.raises(ApplicationError) as caught:
        service.restore(ActorContext(actor_id=uuid4()), created.session_id)
    assert caught.value.info.code == "RESOURCE_NOT_FOUND"


def test_reset_makes_private_session_unavailable():
    """DATA-05：重置后无法靠旧ID恢复私人视图。"""
    service, actor = SessionService(), ActorContext(actor_id=uuid4())
    created = service.create(actor)
    service.reset(actor, created.session_id, uuid4())
    with pytest.raises(ApplicationError) as caught:
        service.restore(actor, created.session_id)
    assert caught.value.info.code == "SESSION_EXPIRED"


def test_search_rejects_missing_session():
    """BE-IF-03 / BE-ERR-01：不存在会话返回明确不可用错误。"""
    with pytest.raises(ApplicationError) as caught:
        ScreeningService().search(ActorContext(actor_id=uuid4()), uuid4(), SearchCommand(query="测试企业甲"), uuid4())
    assert caught.value.info.code == "RESOURCE_NOT_FOUND"


def test_unknown_session_cannot_confirm_candidate():
    """BE-IF-03 / DATA-05：候选ID不能代替会话所有权。"""
    command = ConfirmSubjectCommand(search_id=uuid4(), candidate_id=uuid4(),
                                    expected_generation=0, discard_draft=False)
    with pytest.raises(ApplicationError) as caught:
        ScreeningService().confirm(ActorContext(actor_id=uuid4()), uuid4(), command, uuid4())
    assert caught.value.info.code == "RESOURCE_NOT_FOUND"
