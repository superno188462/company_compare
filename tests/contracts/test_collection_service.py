"""COLLECTION-TEST-1，COLLECTION-1.0：真实CollectionService+SQLite，外部提供方可控。"""

from copy import deepcopy
import json
from uuid import UUID, uuid4

import pytest

from company_screening.contracts.boundary import ActorContext, EditableDraft, RetryQueryCommand
from company_screening.contracts.generated import Category, CollectionToolName, ProviderJudicialPage
from company_screening.errors import ApplicationError
from collection_support import (
    CASE, CODE, STAMP, TOOLS, CollectionProvider, Clock, drain, dump, finish, load_command,
    make_context, open_workspace, overview, provider_failure, record, refresh_command, tool_view,
)


def read(ctx, actor, sid, *, page=1, tool=CASE):
    item = tool_view(ctx, actor, sid, tool)
    return dump(ctx.collections.records(actor, sid, CollectionToolName(tool), UUID(item["batch_id"]), page=page))


def load(ctx, actor, sid, *, page=None, key=None):
    handle = ctx.collections.load_page(actor, sid, load_command(ctx, actor, sid, page=page), key or uuid4())
    return finish(ctx, actor, sid, handle)


def refresh(ctx, actor, sid, *, tool=CASE):
    handle = ctx.collections.refresh_tool(actor, sid, refresh_command(ctx, actor, sid, tool=tool), uuid4())
    return finish(ctx, actor, sid, handle)


def test_second_user_reuses_same_company_without_repeating_api_calls(tmp_path):
    """COL-IF-03/AC-02：A查询后B人工确认同代码再复用，仍隔离私有会话。"""
    ctx = make_context(tmp_path)
    a, aid = open_workspace(ctx)
    calls = list(ctx.provider.calls)
    b, bid = open_workspace(ctx)
    assert ctx.provider.calls == calls
    assert len(calls) == 14 and all(row[0] != "legacy" for row in calls)
    av, bv = tool_view(ctx,a,aid), tool_view(ctx,b,bid)
    assert av["batch_id"] == bv["batch_id"] and bv["obtained_from"] == "cache"
    assert bv["first_fetched_at"] == av["first_fetched_at"]
    assert overview(ctx,b,bid)["session_id"] != overview(ctx,a,aid)["session_id"]


def test_cache_has_no_age_expiration_and_no_new_fetch_on_old_data(tmp_path):
    """COL-NFR-01/IF-03：多年后新会话仍可复用，取得时间不刷新。"""
    clock, provider = Clock(), None
    provider = CollectionProvider(clock)
    first = make_context(tmp_path, clock=clock, provider=provider)
    a, aid = open_workspace(first)
    original = tool_view(first,a,aid)
    count = len(provider.calls)
    clock.advance(days=3650)
    restarted = make_context(tmp_path, clock=clock, provider=provider)
    b, bid = open_workspace(restarted)
    reused = tool_view(restarted,b,bid)
    assert len(provider.calls) == count
    assert reused["batch_id"] == original["batch_id"]
    assert reused["first_fetched_at"] == original["first_fetched_at"]


def test_new_data_source_scope_does_not_reuse_old_scope(tmp_path):
    """COL-DATA-01：缓存不能越过当前数据源权限作用域。"""
    clock, provider = Clock(), CollectionProvider(Clock())
    first = make_context(tmp_path, provider=provider, clock=clock)
    open_workspace(first)
    count = len(provider.calls)
    second = make_context(tmp_path, scope="scope-B", provider=provider, clock=clock)
    open_workspace(second)
    assert len(provider.calls) == count + 14


def test_empty_success_is_cached_but_failed_tool_is_requested_again(tmp_path):
    """COL-IF-03/ERR-01：失败不是无记录，成功空结果可复用。"""
    ctx = make_context(tmp_path)
    ctx.provider.overrides[(TOOLS[-1],1)] = provider_failure()
    a, aid = open_workspace(ctx)
    before = len(ctx.provider.calls)
    b, bid = open_workspace(ctx)
    assert ctx.provider.calls[before:] == [(TOOLS[-1],1,None)]
    failed = tool_view(ctx,b,bid,TOOLS[-1])
    assert failed["state"] == "error" and failed["batch_id"] is None
    assert tool_view(ctx,b,bid,TOOLS[2])["state"] == "empty"


def test_reading_local_pages_never_fetches_upstream_or_changes_report(tmp_path):
    """COL-IF-01/04：读取是有界本地查询，不触发上游/LLM或版本变动。"""
    ctx = make_context(tmp_path)
    actor, sid = open_workspace(ctx)
    before = dump(ctx.sessions.restore(actor,sid).payload)
    calls = list(ctx.provider.calls)
    first = read(ctx,actor,sid)
    assert len(first["items"]) == 20 and first["next_page"] is None
    assert read(ctx,actor,sid,page=99)["items"] == []
    assert ctx.provider.calls == calls
    assert dump(ctx.sessions.restore(actor,sid).payload) == before


def test_loading_only_next_selected_tool_appends_browser_and_preserves_report(tmp_path):
    """COL-IF-04/AC-05：新增只影响浏览，报告和草稿一字不改。"""
    ctx = make_context(tmp_path)
    actor, sid = open_workspace(ctx)
    draft = ctx.screening.save_draft(actor,sid,EditableDraft(
        record_credit_code=CODE,content="PRIVATE_DRAFT_KEEP",source_url=None,
        observed_at=None,event_time=None,category="judicial"),uuid4())
    before = ctx.sessions.restore(actor,sid)
    calls = len(ctx.provider.calls)
    load(ctx,actor,sid)
    assert ctx.provider.calls[calls:] == [(CASE,2,20)]
    assert tool_view(ctx,actor,sid)["collected_count"] == 40
    after = ctx.sessions.restore(actor,sid)
    assert dump(after.payload) == dump(before.payload) and dump(after.draft) == dump(draft)
    assert len(read(ctx,actor,sid,page=2)["items"]) == 20


def test_third_user_can_read_pages_saved_by_another_user_without_fetch(tmp_path):
    """COL-IF-03/04：B追加第二页后C复用，不把私人工作台公开。"""
    ctx = make_context(tmp_path)
    a, aid = open_workspace(ctx)
    load(ctx,a,aid)
    calls = list(ctx.provider.calls)
    c, cid = open_workspace(ctx)
    assert ctx.provider.calls == calls
    assert tool_view(ctx,c,cid)["collected_count"] == 40
    assert len(read(ctx,c,cid,page=2)["items"]) == 20
    payload = dump(ctx.sessions.restore(c,cid).payload)
    assert len([e for e in payload["evidence_list"] if e["category"]=="judicial"]) == 20


@pytest.mark.parametrize("kind", ["same-key","different-key"])
def test_same_page_replay_does_not_repeat_upstream_query(tmp_path, kind):
    """COL-IF-06：同键重放或已存页读取都不能重复取数。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    command, key = load_command(ctx,actor,sid), uuid4()
    handle = ctx.collections.load_page(actor,sid,command,key)
    finish(ctx,actor,sid,handle)
    calls = list(ctx.provider.calls)
    if kind == "same-key":
        replay = ctx.collections.load_page(actor,sid,command,key)
        assert replay.operation_id == handle.operation_id
    else:
        replay = ctx.collections.load_page(actor,sid,load_command(ctx,actor,sid,page=2),uuid4())
        finish(ctx,actor,sid,replay)
    assert ctx.provider.calls == calls


def test_same_key_with_changed_page_is_idempotency_conflict(tmp_path):
    """COL-IF-06：幂等键不能改内容，且重放检查先于修订冲突。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    command,key = load_command(ctx,actor,sid),uuid4()
    finish(ctx,actor,sid,ctx.collections.load_page(actor,sid,command,key))
    changed = command.model_copy(update={"page_number":3})
    with pytest.raises(ApplicationError) as caught:
        ctx.collections.load_page(actor,sid,changed,key)
    assert caught.value.info.code == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("change", ["skip-page","stale-revision","wrong-generation","wrong-batch"])
def test_invalid_or_stale_page_intent_is_rejected_before_query(tmp_path, change):
    """COL-IF-04/06/ERR-01：连续页/修订/代次/绑定批次不能靠客户端绕过。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    command = load_command(ctx,actor,sid)
    updates = {"skip-page":{"page_number":4},"stale-revision":{"expected_collection_revision":command.expected_collection_revision+1},
               "wrong-generation":{"expected_generation":2},"wrong-batch":{"batch_id":uuid4()}}[change]
    command = command.model_copy(update=updates)
    calls = list(ctx.provider.calls)
    with pytest.raises(ApplicationError) as caught:
        ctx.collections.load_page(actor,sid,command,uuid4())
    assert caught.value.info.code in ("OPERATION_CONFLICT","RESOURCE_NOT_FOUND")
    assert ctx.provider.calls == calls


def test_page_failure_keeps_previous_material_and_does_not_publish_empty(tmp_path):
    """COL-IF-04/ERR-01：第二页403不抹去第一页，也不成为无更多记录。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    before = read(ctx,actor,sid)
    ctx.provider.overrides[(CASE,2)] = provider_failure()
    handle = ctx.collections.load_page(actor,sid,load_command(ctx,actor,sid),uuid4())
    drain(ctx)
    result = dump(ctx.collections.operation(actor,sid,handle.operation_id))
    assert result["state"] == "failed" and result["error"]["code"] == "UPSTREAM_AUTH"
    current = tool_view(ctx,actor,sid)
    assert current["state"] == "partial" and current["collected_count"] == 20
    assert current["last_error"]["code"] == "UPSTREAM_AUTH"
    assert read(ctx,actor,sid)["items"] == before["items"]


def test_refresh_creates_new_batch_without_changing_other_open_workspaces(tmp_path):
    """COL-IF-05/06：更新只切换发起人浏览批次，第三人默认新成功批次。"""
    ctx = make_context(tmp_path)
    a,aid = open_workspace(ctx)
    b,bid = open_workspace(ctx)
    old = tool_view(ctx,a,aid)
    ctx.clock.advance(minutes=1)
    refresh(ctx,b,bid)
    new = tool_view(ctx,b,bid)
    assert new["batch_id"] != old["batch_id"]
    assert tool_view(ctx,a,aid)["batch_id"] == old["batch_id"]
    c,cid = open_workspace(ctx)
    assert tool_view(ctx,c,cid)["batch_id"] == new["batch_id"]


def test_refresh_failure_preserves_old_batch_time_and_original_report(tmp_path):
    """COL-IF-05：新失败不能成为第三人默认，也不能修改旧报告。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    before = tool_view(ctx,actor,sid)
    report = dump(ctx.sessions.restore(actor,sid).payload)
    ctx.provider.overrides[(CASE,1)] = provider_failure()
    handle = ctx.collections.refresh_tool(actor,sid,refresh_command(ctx,actor,sid),uuid4())
    drain(ctx)
    assert dump(ctx.collections.operation(actor,sid,handle.operation_id))["state"] == "failed"
    current = tool_view(ctx,actor,sid)
    assert current["batch_id"] == before["batch_id"] and current["first_fetched_at"] == before["first_fetched_at"]
    assert current["last_error"] is not None and dump(ctx.sessions.restore(actor,sid).payload) == report
    other,other_sid = open_workspace(ctx)
    assert tool_view(ctx,other,other_sid)["batch_id"] == before["batch_id"]
    assert tool_view(ctx,other,other_sid)["last_error"] is None


def test_report_and_browser_batches_are_explicit_after_refresh(tmp_path):
    """COL-DATA-03/IF-05：报告不被静默改成覆盖新批次。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    before = tool_view(ctx,actor,sid)
    assert before["report_batch_id"] == before["batch_id"] and before["report_included_count"] == 20
    refresh(ctx,actor,sid)
    current = tool_view(ctx,actor,sid)
    assert current["report_batch_id"] == before["batch_id"]
    assert current["batch_id"] != current["report_batch_id"]


@pytest.mark.parametrize("changes,accepted,more,changed", [
    ({"total_count":66},40,True,True),
    ({"total_count":None,"has_more":None},40,None,False),
    ({"total_count":None,"has_more":None,"records":[]},20,None,False),
])
def test_total_changes_and_unknown_total_do_not_claim_atomic_completeness(tmp_path, changes, accepted, more, changed):
    """COL-IF-04/DATA-03：总数变化和未知空页保留partial，未知不当成0。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    page = ctx.provider.fetch_judicial_page(ctx.sessions.restore(actor,sid).current_subject,
                                          CASE,page_number=2)
    raw = dump(page)
    raw.update(changes)
    ctx.provider.overrides[(CASE,2)] = ProviderJudicialPage.model_validate(raw)
    load(ctx,actor,sid)
    current = tool_view(ctx,actor,sid)
    assert current["state"] == "partial" and current["collected_count"] == accepted
    assert current["has_more"] is more and current["total_changed"] is changed
    if not changes.get("records",[1]):
        assert current["next_upstream_page"] is None


def test_same_record_across_pages_is_counted_once_and_page_progress_advances(tmp_path):
    """COL-IF-04：跨页完全同一记录去重，不误算新事件或卡住连续页进度。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    raw = [dump(record(19)), *[dump(record(i)) for i in range(20,39)]]
    ctx.provider.overrides[(CASE,2)] = ProviderJudicialPage(
        binding_credit_code=CODE,tool_name=CASE,page_number=2,page_size=20,
        queried_at=ctx.clock(),records=raw,total_count=65,has_more=True)
    load(ctx,actor,sid)
    current = tool_view(ctx,actor,sid)
    assert current["collected_count"] == 39 and current["next_upstream_page"] == 3


def test_same_id_changed_content_rejects_whole_page_without_overwrite(tmp_path):
    """COL-IF-04：同ID异内容不静默覆盖，失败保留全部旧页。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    before = read(ctx,actor,sid)
    page = ProviderJudicialPage(binding_credit_code=CODE,tool_name=CASE,page_number=2,page_size=20,
        queried_at=ctx.clock(),records=[dump(record(19,content="changed")),dump(record(20))],
        total_count=65,has_more=True)
    ctx.provider.overrides[(CASE,2)] = page
    handle = ctx.collections.load_page(actor,sid,load_command(ctx,actor,sid),uuid4())
    drain(ctx)
    assert dump(ctx.collections.operation(actor,sid,handle.operation_id))["state"] == "failed"
    assert read(ctx,actor,sid)["items"] == before["items"]
    assert tool_view(ctx,actor,sid)["collected_count"] == 20


def test_own_session_and_task_required_even_for_public_records(tmp_path):
    """COL-ERR-01/NFR-02：公共材料不意味着可读取别人工作台/任务。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    other = ActorContext(actor_id=uuid4())
    handle = ctx.collections.load_page(actor,sid,load_command(ctx,actor,sid),uuid4())
    for action in (lambda:ctx.collections.overview(other,sid),
                   lambda:ctx.collections.operation(other,sid,handle.operation_id)):
        with pytest.raises(ApplicationError) as caught:
            action()
        assert caught.value.info.code == "RESOURCE_NOT_FOUND"


def test_unconfirmed_subject_cannot_browse_cache(tmp_path):
    """COL-IF-01/RULE-01：不允许只凭公司名或信用代码自动绑定主体。"""
    ctx = make_context(tmp_path)
    actor = ActorContext(actor_id=uuid4())
    sid = ctx.sessions.create(actor).session_id
    with pytest.raises(ApplicationError) as caught:
        ctx.collections.overview(actor,sid)
    assert caught.value.info.code == "SUBJECT_UNCONFIRMED" and ctx.provider.calls == []


def test_reset_blocks_late_workspace_write_but_keeps_public_saved_data(tmp_path):
    """COL-IF-06/NFR-02：结束会话不删公共数据；迟到任务不能恢复私有视图。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    ctx.collections.load_page(actor,sid,load_command(ctx,actor,sid),uuid4())
    ctx.sessions.reset(actor,sid,uuid4())
    drain(ctx)
    with pytest.raises(ApplicationError) as caught:
        ctx.collections.overview(actor,sid)
    assert caught.value.info.code == "SESSION_EXPIRED"
    calls = len(ctx.provider.calls)
    other,bid = open_workspace(ctx)
    assert len(ctx.provider.calls) == calls
    assert tool_view(ctx,other,bid)["collected_count"] >= 20


def test_read_only_overview_does_not_renew_session(tmp_path):
    """COL-IF-01/NFR-02：读取/轮询不能当明确用户活动续期。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    expiry = ctx.sessions.restore(actor,sid).expires_at
    overview(ctx,actor,sid)
    read(ctx,actor,sid)
    assert ctx.sessions.restore(actor,sid).expires_at == expiry


def test_successful_load_task_preserves_original_model_input_shape(tmp_path):
    """COL-IF-03/04：浏览模型/诊断/作用域不进入原LLM输入。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    original = dump(ctx.sessions.restore(actor,sid).payload)
    load(ctx,actor,sid)
    after = dump(ctx.sessions.restore(actor,sid).payload)
    assert after == original
    assert set(after) == {"subject","evidence_list","summary_text","api_status","ui_hint_group"}
    for entry in after["evidence_list"]:
        assert "scope_id" not in entry and "collection_revision" not in entry


def test_other_mutating_operation_is_rejected_while_load_pending(tmp_path):
    """COL-IF-06：浏览写任务和原报告查询重试共享互斥边界。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    ctx.collections.load_page(actor,sid,load_command(ctx,actor,sid),uuid4())
    with pytest.raises(ApplicationError) as caught:
        ctx.screening.retry_queries(actor,sid,RetryQueryCommand(expected_generation=1,categories=[Category.judicial]),uuid4())
    assert caught.value.info.code == "OPERATION_CONFLICT"


def test_two_users_request_same_missing_page_only_once(tmp_path):
    """COL-IF-06/NFR-04：两个会话先后排队同页，实际提供方只收到一次取数。"""
    ctx = make_context(tmp_path)
    a,aid = open_workspace(ctx)
    b,bid = open_workspace(ctx)
    first = ctx.collections.load_page(a,aid,load_command(ctx,a,aid),uuid4())
    second = ctx.collections.load_page(b,bid,load_command(ctx,b,bid),uuid4())
    drain(ctx)
    assert dump(ctx.collections.operation(a,aid,first.operation_id))["state"] == "succeeded"
    assert dump(ctx.collections.operation(b,bid,second.operation_id))["state"] == "succeeded"
    assert sum(row==(CASE,2,20) for row in ctx.provider.calls) == 1
    assert tool_view(ctx,a,aid)["collected_count"] == tool_view(ctx,b,bid)["collected_count"] == 40


def test_observing_another_users_new_page_changes_browser_revision_only(tmp_path):
    """COL-DATA-03：可观察同批次已提交新页，修订递增一次但报告不变。"""
    ctx = make_context(tmp_path)
    a,aid = open_workspace(ctx)
    b,bid = open_workspace(ctx)
    before = overview(ctx,b,bid)
    report = dump(ctx.sessions.restore(b,bid).payload)
    load(ctx,a,aid)
    after = overview(ctx,b,bid)
    assert after["collection_revision"] > before["collection_revision"]
    assert overview(ctx,b,bid)["collection_revision"] == after["collection_revision"]
    assert dump(ctx.sessions.restore(b,bid).payload) == report


def test_more_than_200_browser_records_do_not_expand_report_budget(tmp_path):
    """COL-IF-03/04/NFR-03：浏览累计超过200，原报告证据/版本/原文不变。"""
    ctx = make_context(tmp_path)
    for number in range(1,13):
        start,end = (number-1)*20,min(number*20,230)
        ctx.provider.overrides[(CASE,number)] = ProviderJudicialPage(
            binding_credit_code=CODE,tool_name=CASE,page_number=number,page_size=20,
            queried_at=ctx.clock(),records=[dump(record(i)) for i in range(start,end)],
            total_count=230,has_more=end<230)
    actor,sid = open_workspace(ctx)
    before = dump(ctx.sessions.restore(actor,sid).payload)
    for number in range(2,13):
        load(ctx,actor,sid,page=number)
    entry = tool_view(ctx,actor,sid)
    assert entry["collected_count"] == 230 and entry["state"] == "complete"
    assert entry["has_more"] is False and entry["next_upstream_page"] is None
    assert dump(ctx.sessions.restore(actor,sid).payload) == before
    assert len(before["evidence_list"]) <= 200
    assert len(read(ctx,actor,sid,page=12)["items"]) == 10


def test_refresh_does_not_combine_old_second_page_with_new_first_page(tmp_path):
    """COL-IF-05：新旧页不拼成同一个批次。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    load(ctx,actor,sid)
    assert tool_view(ctx,actor,sid)["collected_count"] == 40
    refresh(ctx,actor,sid)
    current = tool_view(ctx,actor,sid)
    assert current["collected_count"] == 20 and current["next_upstream_page"] == 2
    assert read(ctx,actor,sid,page=2)["items"] == []


def test_refresh_success_clears_previous_tool_failure(tmp_path):
    """COL-IF-05/ERR-01：失败是当前会话诊断；下次成功清除，不遗留旧原因。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    ctx.provider.overrides[(CASE,1)] = provider_failure()
    handle = ctx.collections.refresh_tool(actor,sid,refresh_command(ctx,actor,sid),uuid4())
    drain(ctx)
    assert tool_view(ctx,actor,sid)["last_error"] is not None
    del ctx.provider.overrides[(CASE,1)]
    refresh(ctx,actor,sid)
    current = tool_view(ctx,actor,sid)
    assert current["last_error"] is None and current["diagnostic"] is None


def test_private_accepted_evidence_is_not_copied_to_next_user(tmp_path):
    """COL-NFR-02/AC-06：私人接纳证据可影响本报告，但不进入API共享缓存。"""
    from company_screening.contracts.boundary import SubmitEvidenceCommand
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    draft = ctx.screening.save_draft(actor,sid,EditableDraft(
        record_credit_code=CODE,content="PRIVATE_ACCEPTED_NOT_SHARED",source_url=None,
        observed_at=None,event_time=None,category="judicial"),uuid4())
    before = ctx.sessions.restore(actor,sid)
    ctx.screening.submit(actor,sid,SubmitEvidenceCommand(
        draft_id=draft.draft_id,expected_generation=1,expected_evidence_version=before.payload.api_status.evidence_version,
        snapshot_acknowledged=False,share_consent=False),uuid4())
    drain(ctx)
    assert "PRIVATE_ACCEPTED_NOT_SHARED" in ctx.sessions.restore(actor,sid).payload.model_dump_json()
    other,other_sid = open_workspace(ctx)
    assert "PRIVATE_ACCEPTED_NOT_SHARED" not in ctx.sessions.restore(other,other_sid).payload.model_dump_json()
    assert "PRIVATE_ACCEPTED_NOT_SHARED" not in json.dumps(read(ctx,other,other_sid),ensure_ascii=False)
    for path in tmp_path.glob("collection-test.sqlite*"):
        assert b"PRIVATE_ACCEPTED_NOT_SHARED" not in path.read_bytes()


def test_storage_read_failure_does_not_launch_duplicate_upstream_query(tmp_path):
    """COL-ERR-01：存储故障不能降级成cache miss而对已有材料重复收费。"""
    from company_screening.errors import StorageError

    class UnavailableStore:
        def latest(self, key):
            raise StorageError("safe")

    ctx = make_context(tmp_path)
    from company_screening.collections import CollectionService
    service = CollectionService(session_service=ctx.sessions,company_data=ctx.provider,
        store=UnavailableStore(),scope_id="scope-A",clock=ctx.clock,task_submitter=ctx.queue.append)
    from company_screening.services import ScreeningService
    screening = ScreeningService(session_service=ctx.sessions,company_data=ctx.provider,
        clock=ctx.clock,task_submitter=ctx.queue.append,collection_service=service)
    from test_query_operation import _confirm
    actor = ActorContext(actor_id=uuid4())
    sid,handle = _confirm(screening,ctx.sessions,actor)
    drain(ctx)
    result = screening.operation(actor,sid,handle.operation_id)
    assert result.state == "failed" and result.error.code == "STORAGE_UNAVAILABLE"
    assert ctx.provider.calls == []


def test_non_judicial_subtool_failure_preserves_cache_but_report_category_is_error(tmp_path):
    """COL-IF-03：工商登记成功/股东失败不放宽原非司法完整性。"""
    ctx = make_context(tmp_path)
    ctx.provider.overrides[("get_shareholder_info",1)] = provider_failure()
    actor,sid = open_workspace(ctx)
    payload = dump(ctx.sessions.restore(actor,sid).payload)
    assert payload["api_status"]["categories"]["basic"]["status"] == "error"
    assert not [entry for entry in payload["evidence_list"] if entry["category"]=="basic"]
    registration = tool_view(ctx,actor,sid,"get_company_registration_info")
    assert registration["state"] == "complete" and registration["collected_count"] == 1


def test_original_category_retry_bypasses_cache_and_keeps_first_window_only(tmp_path):
    """COL-IF-05：原重查重新取原首页范围，不偷偷用缓存或重取浏览追加页。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    load(ctx,actor,sid)
    count = len(ctx.provider.calls)
    handle = ctx.screening.retry_queries(actor,sid,
        RetryQueryCommand(expected_generation=1,categories=[Category.judicial]),uuid4())
    drain(ctx)
    assert ctx.screening.operation(actor,sid,handle.operation_id).state == "succeeded"
    calls = ctx.provider.calls[count:]
    assert len(calls) == 6 and all(row[1:]==(1,20) for row in calls)
    assert len([entry for entry in dump(ctx.sessions.restore(actor,sid).payload)["evidence_list"]
                if entry["category"]=="judicial"]) == 20


def test_browser_task_over_sixty_seconds_fails_without_restoring_private_task(tmp_path):
    """COL-NFR-05：超时任务明确失败，旧材料不丢；不把超时等同空响应。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    subject = ctx.sessions.restore(actor,sid).current_subject
    value = ctx.provider.fetch_judicial_page(subject,CASE,page_number=2)
    def delayed():
        ctx.clock.advance(seconds=61)
        return value
    ctx.provider.overrides[(CASE,2)] = delayed
    handle = ctx.collections.load_page(actor,sid,load_command(ctx,actor,sid),uuid4())
    drain(ctx)
    view = dump(ctx.collections.operation(actor,sid,handle.operation_id))
    assert view["state"] == "failed" and view["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert tool_view(ctx,actor,sid)["collected_count"] >= 20


@pytest.mark.parametrize("basic_count", [197,200])
def test_fixed_upstream_page_size_and_explicit_report_capacity_window(tmp_path,basic_count):
    """COL-IF-03/COMPAT-01：3条剩余仍取20供浏览；0容量不自动取司法。"""
    from company_screening.contracts.generated import ProviderToolSnapshot
    ctx = make_context(tmp_path)
    ctx.provider.overrides[(TOOLS[0],1)] = ProviderToolSnapshot(
        binding_credit_code=CODE,tool_name=TOOLS[0],queried_at=ctx.clock(),
        records=[dump(record(f"registration-{i}")) for i in range(basic_count)])
    first_judicial = TOOLS[4]
    ctx.provider.overrides[(first_judicial,1)] = ProviderJudicialPage(
        binding_credit_code=CODE,tool_name=first_judicial,page_number=1,page_size=20,
        queried_at=ctx.clock(),records=[dump(record(i)) for i in range(20)],total_count=50,has_more=True)
    actor,sid = open_workspace(ctx)
    payload = dump(ctx.sessions.restore(actor,sid).payload)
    assert len(payload["evidence_list"]) == 200
    calls = [row for row in ctx.provider.calls if row[0] in TOOLS[4:10]]
    if basic_count==197:
        assert calls == [(first_judicial,1,20)]
        entry = tool_view(ctx,actor,sid,first_judicial)
        assert entry["collected_count"] == 20 and entry["report_included_count"] == 3
        assert payload["api_status"]["categories"]["judicial"]["status"] == "partial"
    else:
        assert calls == []
        assert payload["api_status"]["categories"]["judicial"]["status"] == "error"


def test_subject_switch_prevents_old_page_task_from_writing_new_generation(tmp_path):
    """COL-IF-06：已排队旧任务不能写回新主体代次或覆盖新草稿。"""
    from company_screening.contracts.boundary import ConfirmSubjectCommand, SearchCommand
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    handle = ctx.collections.load_page(actor,sid,load_command(ctx,actor,sid),uuid4())
    found = ctx.screening.search(actor,sid,SearchCommand(query="切换测试企业"),uuid4())
    ctx.screening.confirm(actor,sid,ConfirmSubjectCommand(
        search_id=found.search_id,candidate_id=found.items[0].candidate_id,
        expected_generation=1,discard_draft=True),uuid4())
    drain(ctx)
    current = ctx.sessions.restore(actor,sid)
    assert current.session_generation == 2
    assert overview(ctx,actor,sid)["session_generation"] == 2
    try:
        old_view = ctx.collections.operation(actor,sid,handle.operation_id)
    except ApplicationError as exc:
        assert exc.info.code in ("RESOURCE_NOT_FOUND","OPERATION_CONFLICT")
    else:
        value = dump(old_view)
        assert value["result"] is None or value["result"]["session_generation"] == 1


def test_idle_twenty_four_hours_expires_private_view_without_deleting_api_cache(tmp_path,monkeypatch):
    """COL-ERR-01/NFR-02：精确24小时会话到期；公共缓存无TTL且可再利用。"""
    from datetime import datetime
    import company_screening.services as services
    clock = Clock()
    class ControlledDateTime(datetime):
        @classmethod
        def now(cls,tz=None):
            return clock().astimezone(tz) if tz else clock().replace(tzinfo=None)
    monkeypatch.setattr(services,"datetime",ControlledDateTime)
    ctx = make_context(tmp_path,clock=clock)
    actor,sid = open_workspace(ctx)
    calls = list(ctx.provider.calls)
    clock.advance(hours=24)
    with pytest.raises(ApplicationError) as caught:
        ctx.collections.overview(actor,sid)
    assert caught.value.info.code == "SESSION_EXPIRED"
    other,other_sid = open_workspace(ctx)
    assert ctx.provider.calls == calls
    assert tool_view(ctx,other,other_sid)["collected_count"] == 20


def test_page_commit_failure_preserves_previous_metadata_and_reports_storage_error(tmp_path,monkeypatch):
    """COL-ERR-01/NFR-04：依赖写失败不发布未持久化新页，也不宣称保存成功。"""
    from company_screening.errors import StorageError
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    previous = tool_view(ctx,actor,sid)
    def unavailable(*args,**kwargs):
        raise StorageError("safe")
    monkeypatch.setattr(ctx.store,"commit",unavailable)
    handle = ctx.collections.load_page(actor,sid,load_command(ctx,actor,sid),uuid4())
    drain(ctx)
    result = dump(ctx.collections.operation(actor,sid,handle.operation_id))
    assert result["state"] == "failed" and result["error"]["code"] == "STORAGE_UNAVAILABLE"
    current = tool_view(ctx,actor,sid)
    assert current["collected_count"] == previous["collected_count"]
    assert current["batch_revision"] == previous["batch_revision"]
    assert read(ctx,actor,sid,page=2)["items"] == []
