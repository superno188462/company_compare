"""CONTRACT-1.0：BE-IF-04 手工线索草稿服务契约。"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from company_screening.contracts.boundary import ActorContext, EditableDraft
from company_screening.contracts.generated import CreditCode, Subject
from company_screening.errors import ApplicationError
from company_screening.services import ScreeningService, SessionService


def _confirmed_workspace() -> tuple[ActorContext, SessionService, ScreeningService, object]:
    actor = ActorContext(actor_id=uuid4())
    sessions = SessionService()
    state = sessions.create(actor)
    subject = Subject(
        name="测试企业甲",
        credit_code=CreditCode("91310000MA1ABCDEF0"),
        registered_region=None,
        legal_representative=None,
        established_on=None,
        confirmed_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
    )
    sessions._confirm_subject(actor, state.session_id, subject, 0, False, uuid4())
    return actor, sessions, ScreeningService(session_service=sessions), state.session_id


def _draft(**changes: object) -> EditableDraft:
    values: dict[str, object] = {
        "record_credit_code": "91310000MA1ABCDEF0",
        "content": "用户从公开页面手工记录的合成线索。",
        "source_url": "   ",
        "observed_at": None,
        "event_time": None,
        "category": "other",
    }
    values.update(changes)
    return EditableDraft.model_validate(values)


def test_save_draft_requires_confirmed_subject() -> None:
    """BE-IF-04：未确认主体不能建立企业线索草稿。"""
    actor = ActorContext(actor_id=uuid4())
    sessions = SessionService()
    state = sessions.create(actor)
    service = ScreeningService(session_service=sessions)

    with pytest.raises(ApplicationError) as caught:
        service.save_draft(actor, state.session_id, _draft(), uuid4())

    assert caught.value.info.code == "SUBJECT_UNCONFIRMED"
    assert sessions.restore(actor, state.session_id).draft is None


def test_save_draft_only_updates_private_draft_and_marks_issues() -> None:
    """BE-IF-04：错配和来源不全只形成待修正草稿，不改证据或报告。"""
    actor, sessions, service, sid = _confirmed_workspace()
    before = sessions.restore(actor, sid)

    saved = service.save_draft(
        actor,
        sid,
        _draft(
            record_credit_code="91310000MA1ABCDEFX",
            content="记录同时写有当前主体代码 91310000MA1ABCDEF0，需要人工核对归属。",
        ),
        uuid4(),
    )
    after = sessions.restore(actor, sid)

    assert saved.source_url is None
    assert saved.issues == ["CREDIT_MISMATCH", "CREDIT_CONFLICT", "SOURCE_INFO_MISSING"]
    assert after.draft == saved
    assert after.payload == before.payload
    assert after.active_operation == before.active_operation


def test_save_draft_idempotency_does_not_overwrite_newer_edit() -> None:
    """BE-IF-04：旧保存请求重放返回原响应，但不能覆盖后来使用新键保存的草稿。"""
    actor, sessions, service, sid = _confirmed_workspace()
    first_key = uuid4()
    first = service.save_draft(actor, sid, _draft(content="第一版"), first_key)
    second = service.save_draft(actor, sid, _draft(content="第二版"), uuid4())
    replay = service.save_draft(actor, sid, _draft(content="第一版"), first_key)

    assert replay == first
    assert second.draft_id != first.draft_id
    assert sessions.restore(actor, sid).draft == second


def test_save_draft_rejects_same_key_with_different_body() -> None:
    """BE-IF-04：同一幂等键不得代表两次不同编辑。"""
    actor, sessions, service, sid = _confirmed_workspace()
    key = uuid4()
    service.save_draft(actor, sid, _draft(content="第一版"), key)

    with pytest.raises(ApplicationError) as caught:
        service.save_draft(actor, sid, _draft(content="另一版"), key)

    assert caught.value.info.code == "IDEMPOTENCY_CONFLICT"
    assert sessions.restore(actor, sid).draft is not None
    assert sessions.restore(actor, sid).draft.content == "第一版"


def test_clear_draft_is_idempotent_and_does_not_change_subject() -> None:
    """BE-IF-04：明确清空仅移除草稿及来源关联，重复请求无副作用。"""
    actor, sessions, service, sid = _confirmed_workspace()
    service.save_draft(actor, sid, _draft(), uuid4())
    before = sessions.restore(actor, sid)
    key = uuid4()

    service.clear_draft(actor, sid, key)
    service.clear_draft(actor, sid, key)
    after = sessions.restore(actor, sid)

    assert after.draft is None
    assert after.current_subject == before.current_subject
    assert after.payload == before.payload
    assert after.active_operation == before.active_operation
