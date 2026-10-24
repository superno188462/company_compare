"""COLLECTION-TEST-1，COLLECTION-1.0：COL-IF-02/03/06、NFR-01/02/04/06。

直接使用真实SQLite适配器及临时数据库，不用内存替身证明持久化行为。
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
from uuid import UUID, uuid4

import pytest

from company_screening.adapters.collection_sqlite import SqliteCollectionStore
from company_screening.errors import CollectionConflictError, StorageError
from collection_support import (
    CODE, OTHER_CODE, STAMP, Clock, cache_key, dump, fetch_key, publish, stored_pair,
)


def test_committed_records_survive_new_store_instance_without_rewriting_time(tmp_path):
    """COL-NFR-01：重启式重新建实例读取同一文件，正文和原时间不变。"""
    path, clock, key = tmp_path / "test.sqlite", Clock(), cache_key()
    first = SqliteCollectionStore(path, clock=clock)
    batch = publish(first, key)
    clock.advance(days=3650)
    second = SqliteCollectionStore(path, clock=clock)
    saved = second.latest(key)
    assert dump(saved) == dump(batch)
    page = second.get_page(key, batch.batch_id, 1)
    assert len(page.records) == 20 and page.queried_at == STAMP
    assert "expires_at" not in dump(saved)


def test_missing_page_and_missing_batch_are_none_not_empty_success(tmp_path):
    """COL-IF-02：缺失与成功空页不同，存储错误不能被吞成None。"""
    store, key = SqliteCollectionStore(tmp_path / "test.sqlite"), cache_key()
    assert store.latest(key) is None
    assert store.get_batch(key, uuid4()) is None
    assert store.get_page(key, uuid4(), 1) is None


@pytest.mark.parametrize("changes", [
    {"subject_credit_code": OTHER_CODE}, {"scope_id": "scope-B"},
    {"provider": "different"}, {"normalization_version": "v2"},
    {"tool_name": "get_court_notice"}, {"arguments_json": '{"filter":"other"}'},
])
def test_every_cache_identity_dimension_is_isolated(tmp_path, changes):
    """COL-DATA-01/IF-03：同名/别账号/别工具/版本/查询参数不串用。"""
    store, key = SqliteCollectionStore(tmp_path / "test.sqlite", clock=Clock()), cache_key()
    batch = publish(store, key)
    other = cache_key(**changes)
    assert store.latest(other) is None
    assert store.get_batch(other, batch.batch_id) is None
    assert store.get_page(other, batch.batch_id, 1) is None


def test_newest_success_is_selected_by_initial_fetch_not_last_appended_page(tmp_path):
    """COL-IF-03：给旧批次追加页不使其抢回新用户默认。"""
    clock, key = Clock(), cache_key()
    store = SqliteCollectionStore(tmp_path / "test.sqlite", clock=clock)
    old = publish(store, key)
    clock.advance(hours=1)
    new = publish(store, key, at=clock(), batch_id=uuid4())
    clock.advance(hours=1)
    claim = store.claim(fetch_key(key, batch_id=old.batch_id, page=2, mode="load_page"))
    updated, page = stored_pair(key, batch_id=old.batch_id, revision=2, page=2, at=clock())
    store.commit(updated, page, claim_id=claim.claim_id, expected_revision=1)
    assert store.latest(key).batch_id == new.batch_id
    assert store.get_batch(key, old.batch_id).revision == 2


def test_equal_fetch_times_have_stable_batch_id_order(tmp_path):
    """COL-IF-03：同时刻批次按ID稳定倒序，不能取决于SQL未指定顺序。"""
    store, key = SqliteCollectionStore(tmp_path / "test.sqlite", clock=Clock()), cache_key()
    larger = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
    smaller = UUID("11111111-1111-4111-8111-111111111111")
    publish(store, key, batch_id=larger)
    publish(store, key, batch_id=smaller)
    assert store.latest(key).batch_id == larger


def test_complete_empty_snapshot_is_persisted_and_reused(tmp_path):
    """COL-IF-03/NFR-01：空响应是明确成功，保留时间和0，不反复收费查询。"""
    clock, key = Clock(), cache_key()
    store = SqliteCollectionStore(tmp_path / "test.sqlite", clock=clock)
    claim = store.claim(fetch_key(key))
    batch, page = stored_pair(key, count=0, total=0)
    store.commit(batch, page, claim_id=claim.claim_id, expected_revision=None)
    saved = store.latest(key)
    assert saved.collected_count == 0 and saved.total_count == 0
    assert saved.has_more is False and saved.first_fetched_at == STAMP
    assert store.get_page(key, saved.batch_id, 1).records == []


def test_same_page_claim_is_shared_across_store_instances(tmp_path):
    """COL-IF-06/NFR-04：同页并发只授予一个有效采集者。"""
    path, clock, request = tmp_path / "test.sqlite", Clock(), fetch_key(cache_key())
    a, b = SqliteCollectionStore(path, clock=clock), SqliteCollectionStore(path, clock=clock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda store: store.claim(request), [a, b]))
    assert sorted(value.state for value in claims) == ["acquired", "pending"]


def test_different_pages_and_refresh_rounds_do_not_share_claims(tmp_path):
    """COL-IF-06：明确不同更新轮次可各查询，不能永久阻止以后更新。"""
    store, key, batch_id = SqliteCollectionStore(tmp_path / "test.sqlite", clock=Clock()), cache_key(), uuid4()
    requests = [fetch_key(key, batch_id=batch_id, page=n, mode="load_page") for n in (2,3)]
    requests += [fetch_key(key, mode="refresh_tool", refresh_round_id=uuid4()) for _ in range(2)]
    claims = [store.claim(value) for value in requests]
    assert all(value.state == "acquired" for value in claims)
    assert len({value.claim_id for value in claims}) == 4


def test_expired_claim_can_be_reacquired_at_exact_sixty_second_boundary(tmp_path):
    """COL-NFR-04：租约60秒，非资料过期；精确边界允许接管。"""
    clock, key = Clock(), cache_key()
    store = SqliteCollectionStore(tmp_path / "test.sqlite", clock=clock)
    first = store.claim(fetch_key(key))
    assert first.lease_until == STAMP + timedelta(seconds=60)
    clock.advance(seconds=59)
    assert store.claim(fetch_key(key)).state == "pending"
    clock.advance(seconds=1)
    next_claim = store.claim(fetch_key(key))
    assert next_claim.state == "acquired" and next_claim.claim_id != first.claim_id


def test_expired_holder_cannot_overwrite_replacement_commit(tmp_path):
    """COL-NFR-04：迟到结果不能用旧claim覆盖新批次。"""
    clock, key = Clock(), cache_key()
    store = SqliteCollectionStore(tmp_path / "test.sqlite", clock=clock)
    old_claim = store.claim(fetch_key(key))
    clock.advance(seconds=60)
    new_claim = store.claim(fetch_key(key))
    valid, page = stored_pair(key, at=clock())
    store.commit(valid, page, claim_id=new_claim.claim_id, expected_revision=None)
    invalid, invalid_page = stored_pair(key, at=STAMP)
    with pytest.raises(CollectionConflictError):
        store.commit(invalid, invalid_page, claim_id=old_claim.claim_id, expected_revision=None)
    assert store.latest(key).batch_id == valid.batch_id
    assert store.get_batch(key, invalid.batch_id) is None


def test_claim_bound_to_other_subject_cannot_commit_page(tmp_path):
    """COL-IF-02：claim不只是随机UUID，必须绑定key/批次/页。"""
    store = SqliteCollectionStore(tmp_path / "test.sqlite", clock=Clock())
    claim = store.claim(fetch_key(cache_key(subject_credit_code=OTHER_CODE)))
    batch, page = stored_pair()
    with pytest.raises(CollectionConflictError):
        store.commit(batch, page, claim_id=claim.claim_id, expected_revision=None)
    assert store.latest(batch.key) is None


def test_wrong_revision_rolls_back_both_page_and_metadata(tmp_path):
    """COL-IF-02/NFR-04：修订冲突不能插了页却没更新计数。"""
    store, key = SqliteCollectionStore(tmp_path / "test.sqlite", clock=Clock()), cache_key()
    original = publish(store, key)
    claim = store.claim(fetch_key(key, batch_id=original.batch_id, page=2, mode="load_page"))
    batch, page = stored_pair(key, batch_id=original.batch_id, revision=2, page=2)
    with pytest.raises(CollectionConflictError):
        store.commit(batch, page, claim_id=claim.claim_id, expected_revision=99)
    assert dump(store.get_batch(key, original.batch_id)) == dump(original)
    assert store.get_page(key, original.batch_id, 2) is None


def test_finish_releases_coordination_without_deleting_saved_material(tmp_path):
    """COL-IF-02/NFR-01：finish仅结束协调，不是删除长期缓存。"""
    store, key = SqliteCollectionStore(tmp_path / "test.sqlite", clock=Clock()), cache_key()
    saved = publish(store, key)
    claim = store.claim(fetch_key(key, mode="refresh_tool", refresh_round_id=uuid4()))
    store.finish(claim.claim_id)
    assert store.latest(key).batch_id == saved.batch_id
    assert store.get_page(key, saved.batch_id, 1) is not None


def test_storage_open_failure_is_safe_and_does_not_claim_empty(tmp_path):
    """COL-ERR-01/NFR-06：目录不可作为数据库文件，报安全StorageError。"""
    with pytest.raises(StorageError) as caught:
        store = SqliteCollectionStore(tmp_path, clock=Clock())
        store.latest(cache_key())
    assert str(tmp_path) not in str(caught.value)


def test_store_contains_only_public_material_and_metadata(tmp_path):
    """COL-NFR-02：持久化类型与读取内容不包含私人字段和失败诊断。"""
    path, clock = tmp_path / "test.sqlite", Clock()
    store = SqliteCollectionStore(path, clock=clock)
    saved = publish(store)
    value = json.dumps([dump(saved),dump(store.get_page(saved.key,saved.batch_id,1))],ensure_ascii=False)
    assert "合成公开记录" in value
    for name in ("actor_id", "session_id", "draft", "summary_text", "diagnostic", "authorization", "last_error"):
        assert f'"{name}"' not in value


def test_old_batch_remains_readable_after_new_success(tmp_path):
    """COL-IF-05：其他工作台绑定的旧批次不被新刷新物理覆盖。"""
    clock, key = Clock(), cache_key()
    store = SqliteCollectionStore(tmp_path / "test.sqlite", clock=clock)
    old = publish(store, key)
    clock.advance(hours=1)
    new = publish(store, key, at=clock())
    assert store.latest(key).batch_id == new.batch_id
    assert store.get_page(key, old.batch_id, 1).queried_at == STAMP
