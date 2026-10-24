"""COLLECTION-TEST-1合成协作者与真实被测对象装配；不实现缓存/服务业务。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from backend.app import create_app
from company_screening.adapters.collection_sqlite import SqliteCollectionStore
from company_screening.collections import CollectionService
from company_screening.contracts.boundary import ActorContext, ProviderCategoryBatch, ProviderRecord
from company_screening.contracts.collection_storage import (
    CollectionCacheKey, CollectionFetchKey, StoredCollectionBatch, StoredCollectionPage,
)
from company_screening.contracts.generated import (
    Category, CollectionToolName, JudicialToolName, ProviderJudicialPage, ProviderToolSnapshot,
)
from company_screening.errors import ProviderError
from company_screening.services import ScreeningService, SessionService
from test_query_operation import QueryFakeCompanyData, _confirm

CODE = "91310000MA1ABCDEF0"
OTHER_CODE = "91310000MA1ABCDEFX"
CASE = "get_judicial_case"
STAMP = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
TOOLS = (
    "get_company_registration_info", "get_shareholder_info", "get_business_exception",
    "get_administrative_penalty", "get_dishonest_info", "get_judgment_debtor_info",
    "get_high_consumption_restriction", CASE, "get_judicial_documents", "get_court_notice",
    "get_equity_freeze", "get_judicial_assistance", "get_chattel_mortgage_info", "get_land_mortgage_info",
)
CATEGORIES = ("basic", "basic", "abnormal", "penalty", *(["judicial"] * 6), *(["asset"] * 4))


def dump(value):
    return value.model_dump(mode="json")


class Clock:
    def __init__(self):
        self.now = STAMP

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


def record(index=0, *, code=CODE, content=None):
    return ProviderRecord(record_id=f"record-{index}", content=content or f"合成公开记录{index}",
                          record_credit_code=code, event_time=None, source_url=None, source_publisher=None)


def cache_key(**changes):
    values = dict(provider="synthetic", scope_id="scope-A", normalization_version="v1",
                  subject_credit_code=CODE, tool_name=CASE, arguments_json='{}', page_size=20)
    values.update(changes)
    return CollectionCacheKey(**values)


def fetch_key(key, *, batch_id=None, page=1, mode="initial", refresh_round_id=None):
    return CollectionFetchKey(key=key, batch_id=batch_id, page_number=page, mode=mode,
                              refresh_round_id=refresh_round_id)


def stored_pair(key=None, *, batch_id=None, revision=1, page=1, count=20, total=65, at=STAMP):
    key, batch_id = key or cache_key(), batch_id or uuid4()
    batch = StoredCollectionBatch(key=key, batch_id=batch_id, revision=revision,
                                  first_fetched_at=STAMP, last_fetched_at=at,
                                  total_count=total, has_more=page * 20 < total,
                                  total_changed=False, collected_count=count * page)
    data = StoredCollectionPage(batch_id=batch_id, page_number=page, queried_at=at,
                                records=[record(i + (page - 1) * 20) for i in range(count)])
    return batch, data


def publish(store, key=None, *, at=STAMP, batch_id=None, total=65):
    key = key or cache_key()
    claim = store.claim(fetch_key(key))
    batch, page = stored_pair(key, at=at, batch_id=batch_id, total=total)
    batch.first_fetched_at = at
    saved = store.commit(batch, page, claim_id=claim.claim_id, expected_revision=None)
    store.finish(claim.claim_id)
    return saved


def provider_failure(code="UPSTREAM_AUTH"):
    error = ProviderError("SYNTHETIC_PRIVATE_ERROR")
    error.code, error.retryable = code, False
    return error


class CollectionProvider(QueryFakeCompanyData):
    """仅外部提供方替身；记录公开请求，不替代被测缓存/服务。"""

    def __init__(self, clock):
        super().__init__()
        self.clock, self.calls, self.overrides = clock, [], {}

    def fetch_category(self, subject, category, *, record_limit=200):
        # 未接入新服务时让旧链路也能结束，相关测试会通过调用及概览断言识别未接入。
        self.calls.append(("legacy", category.value, record_limit))
        return ProviderCategoryBatch(binding_credit_code=subject.credit_code.root, category=category,
                                     queried_at=self.clock(), scope_description="合成旧链路", records=[])

    def fetch_tool_snapshot(self, subject, tool_name):
        name = str(tool_name)
        self.calls.append((name, 1, None))
        value = self.overrides.get((name, 1))
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value()
        if value is not None:
            return value
        records = [dump(record("registration"))] if name == TOOLS[0] else []
        return ProviderToolSnapshot(binding_credit_code=subject.credit_code.root, tool_name=name,
                                    queried_at=self.clock(), records=records)

    def fetch_judicial_page(self, subject, tool_name, *, page_number, page_size=20):
        name = str(tool_name)
        self.calls.append((name, page_number, page_size))
        value = self.overrides.get((name, page_number))
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value()
        if value is not None:
            return value
        total = 65 if name == CASE else 0
        start, end = (page_number - 1) * 20, min(page_number * 20, total)
        return ProviderJudicialPage(binding_credit_code=subject.credit_code.root, tool_name=name,
                                    page_number=page_number, page_size=20, queried_at=self.clock(),
                                    records=[dump(record(i)) for i in range(start, end)],
                                    total_count=total, has_more=end < total)


def make_context(tmp_path, *, scope="scope-A", clock=None, provider=None):
    """只在测试正文调用，未实现构造函数形成测试失败而非fixture装配错误。"""
    clock = clock or Clock()
    sessions, queue = SessionService(), []
    provider = provider or CollectionProvider(clock)
    store = SqliteCollectionStore(tmp_path / "collection-test.sqlite", clock=clock)
    collections = CollectionService(session_service=sessions, company_data=provider, store=store,
                                    scope_id=scope, clock=clock, task_submitter=queue.append)
    screening = ScreeningService(session_service=sessions, company_data=provider, clock=clock,
                                  task_submitter=queue.append, collection_service=collections)
    return SimpleNamespace(clock=clock, sessions=sessions, queue=queue, provider=provider,
                           store=store, collections=collections, screening=screening, path=tmp_path)


def open_workspace(ctx, actor=None):
    actor = actor or ActorContext(actor_id=uuid4())
    sid, handle = _confirm(ctx.screening, ctx.sessions, actor)
    drain(ctx)
    view = ctx.screening.operation(actor, sid, handle.operation_id)
    assert view.state == "succeeded", dump(view)
    return actor, sid


def drain(ctx):
    for _ in range(30):
        if not ctx.queue:
            return
        ctx.queue.pop(0)()
    raise AssertionError("任务队列未在预定批次内结束")


def overview(ctx, actor, sid):
    return dump(ctx.collections.overview(actor, sid))


def tool_view(ctx, actor, sid, name=CASE):
    return next(item for item in overview(ctx, actor, sid)["tools"] if item["tool_name"] == name)


def load_command(ctx, actor, sid, *, page=None, tool=CASE):
    from company_screening.contracts.generated import LoadCollectionPageCommand
    view = overview(ctx, actor, sid)
    entry = next(item for item in view["tools"] if item["tool_name"] == tool)
    return LoadCollectionPageCommand(expected_generation=view["session_generation"],
                                      expected_collection_revision=view["collection_revision"],
                                      tool_name=tool, batch_id=entry["batch_id"],
                                      page_number=page or entry["next_upstream_page"])


def refresh_command(ctx, actor, sid, *, tool=CASE):
    from company_screening.contracts.generated import RefreshCollectionToolCommand
    view = overview(ctx, actor, sid)
    entry = next(item for item in view["tools"] if item["tool_name"] == tool)
    return RefreshCollectionToolCommand(expected_generation=view["session_generation"],
                                         expected_collection_revision=view["collection_revision"],
                                         tool_name=tool, expected_batch_id=entry["batch_id"])


def finish(ctx, actor, sid, handle):
    drain(ctx)
    result = ctx.collections.operation(actor, sid, handle.operation_id)
    assert result.state.value == "succeeded", dump(result)
    return dump(result)["result"]


def client_app(ctx):
    return create_app(screening_service=ctx.screening, session_service=ctx.sessions,
                      collection_service=ctx.collections)
