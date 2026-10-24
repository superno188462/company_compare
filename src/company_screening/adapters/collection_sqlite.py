"""COLLECTION-WIRING-1：SQLite公共资料持久化与采集协调；不在导入时建库。"""

from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from uuid import UUID, uuid4

from ..collection_clock import utc_now
from ..contracts.collection_storage import (
    CollectionCacheKey, CollectionFetchClaim, CollectionFetchKey,
    StoredCollectionBatch, StoredCollectionPage,
)
from ..errors import CollectionConflictError, StorageError


class SqliteCollectionStore:
    """实现CollectionStorePort的持久化边界，无API资料自动过期时间。"""

    def __init__(self, database_path: Path, *, clock: Callable[[], datetime] = utc_now) -> None:
        """注入数据库路径和可信时钟；测试使用独立临时目录。"""
        self._path, self._clock = database_path, clock
        try:
            database_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(database_path, timeout=10)) as db, db:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS collection_batches (
                        batch_id TEXT PRIMARY KEY, cache_key TEXT NOT NULL,
                        started REAL NOT NULL, data TEXT NOT NULL);
                    CREATE INDEX IF NOT EXISTS collection_latest
                        ON collection_batches(cache_key, started DESC, batch_id DESC);
                    CREATE TABLE IF NOT EXISTS collection_pages (
                        batch_id TEXT NOT NULL, page_number INTEGER NOT NULL, data TEXT NOT NULL,
                        PRIMARY KEY(batch_id, page_number));
                    CREATE TABLE IF NOT EXISTS collection_claims (
                        request TEXT PRIMARY KEY, claim_id TEXT UNIQUE NOT NULL,
                        lease_until REAL NOT NULL);
                """)
        except (OSError, sqlite3.Error):
            raise StorageError("Collection storage unavailable") from None

    def latest(self, key: CollectionCacheKey) -> StoredCollectionBatch | None:
        """COL-IF-03：按首次成功取得时间及批次ID选择，不受资料年龄影响。"""
        try:
            with closing(sqlite3.connect(self._path, timeout=10)) as db:
                row = db.execute("SELECT data FROM collection_batches WHERE cache_key=? "
                                 "ORDER BY started DESC, batch_id DESC LIMIT 1", (key.model_dump_json(),)).fetchone()
            return StoredCollectionBatch.model_validate_json(row[0]) if row else None
        except (sqlite3.Error, ValueError):
            raise StorageError("Collection storage unavailable") from None

    def get_batch(self, key: CollectionCacheKey, batch_id: UUID) -> StoredCollectionBatch | None:
        """COL-IF-02：读取同作用域指定批次。"""
        try:
            with closing(sqlite3.connect(self._path, timeout=10)) as db:
                row = db.execute("SELECT data FROM collection_batches WHERE batch_id=? AND cache_key=?",
                                 (str(batch_id), key.model_dump_json())).fetchone()
            return StoredCollectionBatch.model_validate_json(row[0]) if row else None
        except (sqlite3.Error, ValueError):
            raise StorageError("Collection storage unavailable") from None

    def get_page(self, key: CollectionCacheKey, batch_id: UUID, page_number: int) -> StoredCollectionPage | None:
        """COL-IF-04：读取已有页；缺页不等于存储不可用。"""
        try:
            with closing(sqlite3.connect(self._path, timeout=10)) as db:
                row = db.execute("SELECT p.data FROM collection_pages p JOIN collection_batches b "
                                 "ON p.batch_id=b.batch_id WHERE b.cache_key=? AND p.batch_id=? AND p.page_number=?",
                                 (key.model_dump_json(), str(batch_id), page_number)).fetchone()
            return StoredCollectionPage.model_validate_json(row[0]) if row else None
        except (sqlite3.Error, ValueError):
            raise StorageError("Collection storage unavailable") from None

    def commit(
        self, batch: StoredCollectionBatch, page: StoredCollectionPage, *,
        claim_id: UUID, expected_revision: int | None,
    ) -> StoredCollectionBatch:
        """COL-IF-02/NFR-04：验证有效claim和修订，原子提交或完整拒绝。"""
        try:
            with closing(sqlite3.connect(self._path, timeout=10)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT request,lease_until FROM collection_claims WHERE claim_id=?",
                                 (str(claim_id),)).fetchone()
                if row is None or row[1] <= self._clock().timestamp():
                    raise CollectionConflictError("Collection claim no longer valid")
                request = CollectionFetchKey.model_validate_json(row[0])
                if (request.key != batch.key or page.batch_id != batch.batch_id
                    or request.page_number != page.page_number
                    or (request.batch_id is not None and request.batch_id != batch.batch_id)):
                    raise CollectionConflictError("Collection claim target changed")
                old = db.execute("SELECT data FROM collection_batches WHERE batch_id=?", (str(batch.batch_id),)).fetchone()
                if expected_revision is None:
                    if old is not None or page.page_number != 1 or batch.revision != 1:
                        raise CollectionConflictError("Collection initial commit changed")
                else:
                    if old is None:
                        raise CollectionConflictError("Collection batch missing")
                    previous = StoredCollectionBatch.model_validate_json(old[0])
                    if previous.key != batch.key or previous.revision != expected_revision or batch.revision != expected_revision + 1:
                        raise CollectionConflictError("Collection revision changed")
                    count = db.execute("SELECT MAX(page_number) FROM collection_pages WHERE batch_id=?",
                                       (str(batch.batch_id),)).fetchone()[0]
                    if page.page_number != count + 1:
                        raise CollectionConflictError("Collection page not consecutive")
                db.execute("INSERT INTO collection_pages(batch_id,page_number,data) VALUES(?,?,?)",
                           (str(batch.batch_id), page.page_number, page.model_dump_json()))
                db.execute("INSERT OR REPLACE INTO collection_batches(batch_id,cache_key,started,data) VALUES(?,?,?,?)",
                           (str(batch.batch_id), batch.key.model_dump_json(), batch.first_fetched_at.timestamp(), batch.model_dump_json()))
            return batch.model_copy(deep=True)
        except (sqlite3.Error, ValueError):
            raise StorageError("Collection storage unavailable") from None

    def claim(self, request: CollectionFetchKey) -> CollectionFetchClaim:
        """COL-NFR-04：同页协调，60秒租约与资料保留期限无关。"""
        now, encoded = self._clock(), request.model_dump_json()
        try:
            with closing(sqlite3.connect(self._path, timeout=10)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT claim_id,lease_until FROM collection_claims WHERE request=?", (encoded,)).fetchone()
                if row and row[1] > now.timestamp():
                    return CollectionFetchClaim(claim_id=row[0], state="pending",
                                                lease_until=datetime.fromtimestamp(row[1], tz=now.tzinfo))
                claim = CollectionFetchClaim(claim_id=uuid4(), state="acquired", lease_until=now + timedelta(seconds=60))
                db.execute("INSERT OR REPLACE INTO collection_claims(request,claim_id,lease_until) VALUES(?,?,?)",
                           (encoded, str(claim.claim_id), claim.lease_until.timestamp()))
            return claim
        except sqlite3.Error:
            raise StorageError("Collection storage unavailable") from None

    def finish(self, claim_id: UUID) -> None:
        """释放取数协调，不删除已保存的批次和页。"""
        try:
            with closing(sqlite3.connect(self._path, timeout=10)) as db, db:
                db.execute("DELETE FROM collection_claims WHERE claim_id=?", (str(claim_id),))
        except sqlite3.Error:
            raise StorageError("Collection storage unavailable") from None
