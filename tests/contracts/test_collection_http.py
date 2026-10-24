"""COLLECTION-TEST-1，COLLECTION-1.0：COL-IF-01、ERR-01、NFR-02/07，真实路由与服务。"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.collection_routes import get_collection_service, router
from backend.dependencies import get_actor
from company_screening.contracts.boundary import ActorContext
from company_screening.services import ScreeningService, SessionService
from collection_support import (
    CASE, client_app, drain, dump, load_command, make_context, open_workspace,
    overview, refresh_command, tool_view,
)


def client_for(ctx, actor):
    app = client_app(ctx)
    app.dependency_overrides[get_actor] = lambda: actor
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("suffix", ["collections", "collections/get_judicial_case/records?batch_id=invalid",
                                   "collection-operations/not-a-uuid"])
def test_isolated_router_rejects_bad_path_and_query_formats(suffix):
    """COL-DATA-01/ERR-01：HTTP格式校验，不执行业务占位函数或真实接口。"""
    app = create_app(screening_service=ScreeningService(),session_service=SessionService())
    app.include_router(router)
    app.dependency_overrides[get_collection_service] = lambda: None
    client = TestClient(app,raise_server_exceptions=False)
    response = client.get(f"/api/v1/sessions/invalid/{suffix}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INPUT_INVALID"


@pytest.mark.parametrize("path,body", [
    ("collections/pages", {}),
    ("collections/pages", dict(expected_generation=1,expected_collection_revision=1,
                               tool_name="get_shareholder_info",batch_id=str(uuid4()),page_number=2)),
    ("collections/pages", dict(expected_generation=True,expected_collection_revision=1,
                               tool_name=CASE,batch_id=str(uuid4()),page_number=2)),
    ("collections/pages", dict(expected_generation=1,expected_collection_revision=1,
                               tool_name=CASE,batch_id=str(uuid4()),page_number=1)),
    ("collections/refresh", dict(expected_generation=1,expected_collection_revision=1,
                                 tool_name="arbitrary",expected_batch_id=None)),
    ("collections/refresh", dict(expected_generation=1,expected_collection_revision=1,
                                 tool_name=CASE,expected_batch_id=None,scope_id="FORGED")),
])
def test_isolated_router_rejects_invalid_write_commands_without_echo(path,body):
    """COL-IF-01/ERR-01：不能伪造主体/作用域，响应不回显原输入。"""
    app = create_app(screening_service=ScreeningService(),session_service=SessionService())
    app.include_router(router)
    app.dependency_overrides[get_collection_service] = lambda: None
    client = TestClient(app,raise_server_exceptions=False)
    response = client.post(f"/api/v1/sessions/{uuid4()}/{path}",json=body,
                            headers={"Idempotency-Key":str(uuid4())})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INPUT_INVALID"
    assert "FORGED" not in response.text and "arbitrary" not in response.text


def test_collection_get_returns_overview_and_local_page_without_queries(tmp_path):
    """COL-IF-01：真实运行时装配后GET概览与本地页均可用，不续期/取上游。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    client = client_for(ctx,actor)
    calls = list(ctx.provider.calls)
    response = client.get(f"/api/v1/sessions/{sid}/collections")
    assert response.status_code == 200
    body = response.json()
    entry = next(item for item in body["tools"] if item["tool_name"]==CASE)
    page = client.get(f"/api/v1/sessions/{sid}/collections/{CASE}/records",
                       params=dict(batch_id=entry["batch_id"],page=1))
    assert page.status_code == 200 and len(page.json()["items"]) == 20
    assert ctx.provider.calls == calls
    assert "scope_id" not in response.text and "authorization" not in page.text.lower()


def test_load_http_returns_handle_and_replay_polls_same_terminal_result(tmp_path):
    """COL-IF-01/06：202任务、幂等重放、200终态；不返回半段报告。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    client = client_for(ctx,actor)
    body,key = dump(load_command(ctx,actor,sid)),str(uuid4())
    path = f"/api/v1/sessions/{sid}/collections/pages"
    first = client.post(path,json=body,headers={"Idempotency-Key":key})
    assert first.status_code == 202
    replay = client.post(path,json=body,headers={"Idempotency-Key":key})
    assert replay.status_code == 202 and replay.json() == first.json()
    drain(ctx)
    result = client.get(f"/api/v1/sessions/{sid}/collection-operations/{first.json()['operation_id']}")
    assert result.status_code == 200 and result.json()["state"] == "succeeded"
    assert result.json()["result"] is not None and result.json()["error"] is None
    assert "summary_text" not in result.text
    assert sum(row==(CASE,2,20) for row in ctx.provider.calls) == 1


@pytest.mark.parametrize("action", ["overview","records","operation"])
def test_other_owner_gets_404_not_public_workspace_access(tmp_path,action):
    """COL-ERR-01/NFR-02：公共缓存复用不开放他人工作台或任务。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    handle = ctx.collections.load_page(actor,sid,load_command(ctx,actor,sid),uuid4())
    client = client_for(ctx,ActorContext(actor_id=uuid4()))
    entry = tool_view(ctx,actor,sid)
    suffix = {"overview":"collections", "records":f"collections/{CASE}/records?batch_id={entry['batch_id']}",
              "operation":f"collection-operations/{handle.operation_id}"}[action]
    response = client.get(f"/api/v1/sessions/{sid}/{suffix}")
    assert response.status_code == 404 and response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_explicit_session_end_returns_410_but_new_owner_can_reuse_api_cache(tmp_path):
    """COL-ERR-01/NFR-02：结束工作台不删除API批次；旧会话不可恢复。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    client = client_for(ctx,actor)
    ctx.sessions.reset(actor,sid,uuid4())
    response = client.get(f"/api/v1/sessions/{sid}/collections")
    assert response.status_code == 410 and response.json()["error"]["code"] == "SESSION_EXPIRED"
    calls = list(ctx.provider.calls)
    other,other_sid = open_workspace(ctx)
    assert ctx.provider.calls == calls
    assert client_for(ctx,other).get(f"/api/v1/sessions/{other_sid}/collections").status_code == 200


def test_write_requires_same_origin_and_idempotency_header(tmp_path):
    """COL-IF-01/NFR-07：外站写和非法幂等头不能启动上游任务。"""
    ctx = make_context(tmp_path)
    actor,sid = open_workspace(ctx)
    client = client_for(ctx,actor)
    calls = list(ctx.provider.calls)
    path,body = f"/api/v1/sessions/{sid}/collections/refresh",dump(refresh_command(ctx,actor,sid))
    missing = client.post(path,json=body)
    assert missing.status_code == 422
    cross = client.post(path,json=body,headers={"Idempotency-Key":str(uuid4()),"Origin":"https://untrusted.invalid"})
    assert cross.status_code == 422 and cross.json()["error"]["code"] == "INPUT_INVALID"
    assert ctx.provider.calls == calls


def test_unconfirmed_session_http_is_409_not_cache_autobinding(tmp_path):
    """COL-IF-01：HTTP也不能跳过人工确认。"""
    ctx = make_context(tmp_path)
    actor = ActorContext(actor_id=uuid4())
    sid = ctx.sessions.create(actor).session_id
    response = client_for(ctx,actor).get(f"/api/v1/sessions/{sid}/collections")
    assert response.status_code == 409 and response.json()["error"]["code"] == "SUBJECT_UNCONFIRMED"
