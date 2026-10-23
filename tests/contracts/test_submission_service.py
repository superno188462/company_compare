"""待评审：CONTRACT-1.0，BE-IF-04/06 与 DATA-01/03/05。

只覆盖自行录入、未请求共享的接纳切片，以及不合格共享请求的前置拒绝。
提供方为合成替身；不访问网络、不修改现有108项锁定用例。
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from company_screening.contracts.boundary import (
    ActorContext, ConfirmSubjectCommand, EditableDraft, ProviderCandidate,
    ProviderCategoryBatch, ProviderRecord, ProviderSearchPage, SearchCommand,
    SubmitEvidenceCommand,
)
from company_screening.contracts.generated import Category, Subject
from company_screening.errors import ApplicationError
from company_screening.services import ScreeningService, SessionService


CODE = "91310000MA1ABCDEF0"
OTHER_CODE = "91310000MA1ABCDEFX"


class SubmissionCompanyData:
    """只提供确定的合成候选和完整详情批次。"""

    def __init__(self, record_count=0):
        self.record_count = record_count

    def search(self, command: SearchCommand) -> ProviderSearchPage:
        return ProviderSearchPage(items=[ProviderCandidate(
            name="接纳测试企业", credit_code=CODE, registered_region=None,
            legal_representative=None, established_on=None,
        )], next_cursor=None, total=1)

    def fetch_category(self, subject: Subject, category: Category) -> ProviderCategoryBatch:
        records = []
        if category == Category.basic:
            records = [ProviderRecord(
                record_id=f"SYNTHETIC-{index}", content=f"合成登记线索{index}",
                record_credit_code=CODE, event_time=None, source_url=None,
                source_publisher=None,
            ) for index in range(self.record_count)]
        return ProviderCategoryBatch(
            binding_credit_code=CODE, category=category,
            queried_at=datetime.now(timezone.utc), scope_description="合成测试完整范围",
            records=records,
        )


def make_workspace(record_count=0):
    """通过公开搜索/确认/轮询接口建立测试前置状态。"""
    actor = ActorContext(actor_id=uuid4())
    sessions = SessionService()
    queued = []
    now = datetime.now(timezone.utc)
    service = ScreeningService(
        session_service=sessions, company_data=SubmissionCompanyData(record_count),
        clock=lambda: now, task_submitter=queued.append,
    )
    workspace = sessions.create(actor)
    search = service.search(actor, workspace.session_id, SearchCommand(query="合成企业"), uuid4())
    handle = service.confirm(actor, workspace.session_id, ConfirmSubjectCommand(
        search_id=search.search_id, candidate_id=search.items[0].candidate_id,
        expected_generation=0, discard_draft=False,
    ), uuid4())
    queued.pop(0)()
    assert service.operation(actor, workspace.session_id, handle.operation_id).state == "succeeded"
    return SimpleNamespace(
        actor=actor, sessions=sessions, service=service, sid=workspace.session_id,
        queued=queued, now=now,
    )


def save_draft(ctx, **changes):
    values = dict(
        record_credit_code=CODE, content="合成手工线索：请核对其原始来源。",
        source_url=None, observed_at=None, event_time=None, category="other",
    )
    values.update(changes)
    return ctx.service.save_draft(
        ctx.actor, ctx.sid, EditableDraft.model_validate(values), uuid4(),
    )


def submit_command(ctx, saved, **changes):
    state = ctx.sessions.restore(ctx.actor, ctx.sid)
    values = dict(
        draft_id=saved.draft_id, expected_generation=state.session_generation,
        expected_evidence_version=state.payload.api_status.evidence_version,
        snapshot_acknowledged=False, share_consent=False,
    )
    values.update(changes)
    return SubmitEvidenceCommand.model_validate(values)


def test_private_submission_returns_handle_and_complete_payload(validators):
    """BE-IF-04/06：接纳自行录入线索，不把草稿/来源链接冒充官方核验。"""
    ctx = make_workspace()
    saved = save_draft(ctx)
    before = ctx.sessions.restore(ctx.actor, ctx.sid).payload
    handle = ctx.service.submit(ctx.actor, ctx.sid, submit_command(ctx, saved), uuid4())
    pending = ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id)
    assert pending.state in ("queued", "running")
    assert pending.result is None and pending.error is None

    ctx.queued.pop(0)()
    finished = ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id)
    assert finished.state == "succeeded" and finished.error is None
    result = finished.result
    assert result is not None
    validators[1].validate(result.model_dump(mode="json"))
    assert len(result.evidence_list) == 1
    evidence = result.evidence_list[0].root
    assert evidence.content == saved.content
    assert evidence.subject_credit_code.root == CODE
    assert evidence.source == "user_self"
    assert evidence.hint_id == "SOURCE_USER_SELF"
    assert evidence.verification_status == "original_not_verified"
    assert evidence.snapshot_time is None and evidence.source_url is None
    assert evidence.provider_record_id is None and evidence.derived_from is None
    assert evidence.origin_id
    assert result.api_status.tianyan_status == before.api_status.tianyan_status
    assert result.api_status.categories == before.api_status.categories
    assert result.api_status.evidence_version == before.api_status.evidence_version + 1
    assert result.api_status.result_revision > before.api_status.result_revision
    receipt = result.api_status.last_submission
    assert receipt.operation_id == handle.operation_id
    assert receipt.evidence_id == evidence.evidence_id
    assert receipt.share_status == "not_requested" and receipt.share_receipt_id is None
    assert "EVIDENCE_SAVED" in result.ui_hint_group
    after = ctx.sessions.restore(ctx.actor, ctx.sid)
    assert after.draft is None and after.active_operation is None
    assert after.payload == result and after.share_receipts == []


def test_missing_model_does_not_roll_back_accepted_evidence():
    """BE-IF-04/05：当前未配置模型时报告失败，已经接纳的证据仍然保存。"""
    ctx = make_workspace()
    saved = save_draft(ctx)
    handle = ctx.service.submit(ctx.actor, ctx.sid, submit_command(ctx, saved), uuid4())
    ctx.queued.pop(0)()
    result = ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id).result
    assert result is not None and len(result.evidence_list) == 1
    assert result.api_status.llm_status == "error"
    assert result.summary_text == "" and result.api_status.summary_evidence_version is None
    assert "REPORT_FAILED" in result.ui_hint_group
    assert "NO_EVIDENCE" not in result.ui_hint_group
    assert ctx.sessions.restore(ctx.actor, ctx.sid).payload == result


@pytest.mark.parametrize("changes,code,field,message_key", [
    ({"record_credit_code": None}, "CREDIT_MISSING", None, None),
    ({"record_credit_code": OTHER_CODE}, "CREDIT_MISMATCH", None, None),
    ({"content": f"来源记录明确指向 {OTHER_CODE}"}, "CREDIT_CONFLICT", None, None),
    ({"content": " \n\t"}, "INPUT_INVALID", "content", "content_required"),
    ({"source_url": "javascript:alert(1)"}, "INPUT_INVALID", "source_url", "url_format"),
    ({"source_url": "https://name:password@example.invalid/record"}, "INPUT_INVALID", "source_url", "url_format"),
    ({"source_url": "https://example.invalid/\nrecord"}, "INPUT_INVALID", "source_url", "url_format"),
    ({"observed_at": "2026-10-23T10:00:00"}, "INPUT_INVALID", "observed_at", "time_format"),
    ({"observed_at": "不是日期"}, "INPUT_INVALID", "observed_at", "time_format"),
    ({"observed_at": "2099-01-01T00:00:00Z"}, "INPUT_INVALID", "observed_at", "future_time"),
])
def test_invalid_submission_preserves_draft_and_has_no_side_effect(changes, code, field, message_key):
    """BE-IF-04 / DATA-01：归属、链接、时间和正文非法时不接纳、不启动任务。"""
    ctx = make_workspace()
    saved = save_draft(ctx, **changes)
    before = ctx.sessions.restore(ctx.actor, ctx.sid)
    with pytest.raises(ApplicationError) as caught:
        ctx.service.submit(ctx.actor, ctx.sid, submit_command(ctx, saved), uuid4())
    assert caught.value.info.code == code
    if field is not None:
        assert any(issue.field == field and issue.message_key == message_key
                   for issue in caught.value.info.fields)
    after = ctx.sessions.restore(ctx.actor, ctx.sid)
    assert after.current_subject == before.current_subject
    assert after.draft == before.draft and after.payload == before.payload
    assert after.active_operation == before.active_operation
    assert after.share_receipts == before.share_receipts
    assert ctx.queued == []


@pytest.mark.parametrize("changes", [
    {"expected_generation": 2}, {"expected_evidence_version": 99}, {"draft_id": uuid4()},
])
def test_stale_submission_is_rejected_without_replacing_state(changes):
    """BE-IF-04 / DATA-05：陈旧主体、输入版本或草稿ID不能消费新草稿。"""
    ctx = make_workspace()
    saved = save_draft(ctx)
    before = ctx.sessions.restore(ctx.actor, ctx.sid)
    with pytest.raises(ApplicationError) as caught:
        ctx.service.submit(ctx.actor, ctx.sid, submit_command(ctx, saved, **changes), uuid4())
    assert caught.value.info.code == "OPERATION_CONFLICT"
    after = ctx.sessions.restore(ctx.actor, ctx.sid)
    assert after.draft == before.draft and after.payload == before.payload
    assert after.active_operation is None and ctx.queued == []


def test_submission_replay_does_not_append_or_enqueue_twice():
    """DATA-05：同键同内容在运行中及终态重放均返回原句柄。"""
    ctx = make_workspace()
    saved = save_draft(ctx)
    command, key = submit_command(ctx, saved), uuid4()
    handle = ctx.service.submit(ctx.actor, ctx.sid, command, key)
    assert ctx.service.submit(ctx.actor, ctx.sid, command, key) == handle
    assert len(ctx.queued) == 1
    ctx.queued.pop(0)()
    assert ctx.service.submit(ctx.actor, ctx.sid, command, key) == handle
    assert len(ctx.sessions.restore(ctx.actor, ctx.sid).payload.evidence_list) == 1
    assert ctx.queued == []


def test_submission_key_cannot_be_reused_with_changed_consent():
    """DATA-05：同键不同请求拒绝，而非隐式修改既有共享选择。"""
    ctx = make_workspace()
    saved = save_draft(ctx)
    command, key = submit_command(ctx, saved), uuid4()
    ctx.service.submit(ctx.actor, ctx.sid, command, key)
    with pytest.raises(ApplicationError) as caught:
        ctx.service.submit(ctx.actor, ctx.sid, command.model_copy(update={"share_consent": True}), key)
    assert caught.value.info.code == "IDEMPOTENCY_CONFLICT"
    assert len(ctx.queued) == 1


def test_another_submission_cannot_overlap_active_operation():
    """DATA-05：同代次已有修改任务时不接纳第二条，保留下一条草稿。"""
    ctx = make_workspace()
    first = save_draft(ctx)
    ctx.service.submit(ctx.actor, ctx.sid, submit_command(ctx, first), uuid4())
    second = save_draft(ctx, content="下一条合成线索")
    with pytest.raises(ApplicationError) as caught:
        ctx.service.submit(ctx.actor, ctx.sid, submit_command(ctx, second), uuid4())
    assert caught.value.info.code == "OPERATION_CONFLICT"
    assert ctx.sessions.restore(ctx.actor, ctx.sid).draft == second
    assert len(ctx.queued) == 1


def test_completion_keeps_newer_draft():
    """BE-IF-04：上一次接纳任务结束不能清除用户刚保存的下一条草稿。"""
    ctx = make_workspace()
    first = save_draft(ctx)
    handle = ctx.service.submit(ctx.actor, ctx.sid, submit_command(ctx, first), uuid4())
    second = save_draft(ctx, content="接纳期间新保存的草稿")
    ctx.queued.pop(0)()
    after = ctx.sessions.restore(ctx.actor, ctx.sid)
    assert after.draft == second
    assert len(after.payload.evidence_list) == 1
    assert after.payload.evidence_list[0].root.content == first.content
    assert ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id).state == "succeeded"


def test_share_request_missing_metadata_is_rejected_before_acceptance():
    """BE-IF-04 / DATA-04：不能悄悄取消用户共享选择后仅保存私人证据。"""
    ctx = make_workspace()
    saved = save_draft(ctx)
    before = ctx.sessions.restore(ctx.actor, ctx.sid)
    with pytest.raises(ApplicationError) as caught:
        ctx.service.submit(ctx.actor, ctx.sid, submit_command(ctx, saved, share_consent=True), uuid4())
    assert caught.value.info.code == "SHARE_REQUIREMENTS"
    after = ctx.sessions.restore(ctx.actor, ctx.sid)
    assert after.draft == saved and after.payload == before.payload
    assert after.share_receipts == [] and ctx.queued == []


def test_valid_declared_time_is_preserved_separately_from_acceptance_time():
    """DATA-01：查看时间保留实际时刻，不能改成系统接纳时间或事件时间。"""
    ctx = make_workspace()
    observed = ctx.now - timedelta(days=2)
    saved = save_draft(ctx, observed_at=observed.isoformat(), event_time="合成2025年度")
    handle = ctx.service.submit(ctx.actor, ctx.sid, submit_command(ctx, saved), uuid4())
    ctx.queued.pop(0)()
    evidence = ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id).result.evidence_list[0].root
    serialized = evidence.model_dump(mode="json")
    assert datetime.fromisoformat(serialized["snapshot_time"].replace("Z", "+00:00")) == observed
    assert datetime.fromisoformat(serialized["captured_at"].replace("Z", "+00:00")) >= ctx.now
    assert evidence.event_time.root == "合成2025年度"


def test_submission_cannot_exceed_200_evidence_records():
    """DATA-03：已有200条时拒绝添加，不能截断或挤掉旧证据。"""
    ctx = make_workspace(record_count=200)
    saved = save_draft(ctx)
    before = ctx.sessions.restore(ctx.actor, ctx.sid)
    with pytest.raises(ApplicationError) as caught:
        ctx.service.submit(ctx.actor, ctx.sid, submit_command(ctx, saved), uuid4())
    assert caught.value.info.code == "INPUT_TOO_LARGE"
    after = ctx.sessions.restore(ctx.actor, ctx.sid)
    assert after.payload == before.payload and after.draft == saved
    assert ctx.queued == []


def test_other_owner_cannot_submit_known_session_and_draft_ids():
    """DATA-05：公开会话和草稿ID不能代替所有权凭据。"""
    ctx = make_workspace()
    saved = save_draft(ctx)
    with pytest.raises(ApplicationError) as caught:
        ctx.service.submit(ActorContext(actor_id=uuid4()), ctx.sid, submit_command(ctx, saved), uuid4())
    assert caught.value.info.code == "RESOURCE_NOT_FOUND"
    assert ctx.sessions.restore(ctx.actor, ctx.sid).draft == saved
    assert ctx.queued == []


def test_unconfirmed_session_cannot_submit_a_guessed_draft():
    """BE-RULE-01：绕过前端直接提交也不能跳过主体确认。"""
    actor = ActorContext(actor_id=uuid4())
    sessions = SessionService()
    state = sessions.create(actor)
    queued = []
    service = ScreeningService(session_service=sessions, task_submitter=queued.append)
    command = SubmitEvidenceCommand(
        draft_id=uuid4(), expected_generation=1, expected_evidence_version=0,
        snapshot_acknowledged=False, share_consent=False,
    )
    with pytest.raises(ApplicationError) as caught:
        service.submit(actor, state.session_id, command, uuid4())
    assert caught.value.info.code == "SUBJECT_UNCONFIRMED"
    assert sessions.restore(actor, state.session_id).payload is None
    assert queued == []


def test_reset_prevents_late_submission_result_from_restoring_private_data():
    """BE-IF-06 / DATA-05：任务迟到不能恢复已经结束的会话。"""
    ctx = make_workspace()
    saved = save_draft(ctx)
    handle = ctx.service.submit(ctx.actor, ctx.sid, submit_command(ctx, saved), uuid4())
    ctx.sessions.reset(ctx.actor, ctx.sid, uuid4())
    ctx.queued.pop(0)()
    with pytest.raises(ApplicationError) as caught:
        ctx.sessions.restore(ctx.actor, ctx.sid)
    assert caught.value.info.code == "SESSION_EXPIRED"
    with pytest.raises(ApplicationError):
        ctx.service.operation(ctx.actor, ctx.sid, handle.operation_id)
