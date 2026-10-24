"""BE-IF-07：可替换外部协作者，禁止在导入时创建实际客户端。"""

from typing import Literal, Protocol
from uuid import UUID

from .contracts.boundary import ProviderCategoryBatch, ProviderSearchPage, SearchCommand
from .contracts.collection_storage import (
    CollectionCacheKey, CollectionFetchClaim, CollectionFetchKey,
    StoredCollectionBatch, StoredCollectionPage,
)
from .contracts.generated import (
    Category, JudicialToolName, LlmInput, ProviderJudicialPage, ProviderToolSnapshot,
    SnapshotToolName, Subject,
)


class CompanyDataPort(Protocol):
    """仅企业授权接口能力，无任意网页访问能力。"""

    def search(self, command: SearchCommand) -> ProviderSearchPage:
        """搜索候选；不得代用户选择。"""
        raise NotImplementedError()

    def fetch_category(
        self, subject: Subject, category: Category, *, record_limit: int = 200,
    ) -> ProviderCategoryBatch:
        """返回分类批次；司法窗口遵守剩余容量，其他类别仍要求完整取得。"""
        raise NotImplementedError()

    def fetch_tool_snapshot(self, subject: Subject, tool_name: SnapshotToolName) -> ProviderToolSnapshot:
        """COL-IF-02：单个非司法工具完整取得，超预算或分页不完整必须报错。"""
        raise NotImplementedError()

    def fetch_judicial_page(
        self, subject: Subject, tool_name: JudicialToolName, *,
        page_number: int, page_size: Literal[20] = 20,
    ) -> ProviderJudicialPage:
        """COL-IF-02/04：只请求指定司法页并完整校验，不自动翻页。"""
        raise NotImplementedError()


class CollectionStorePort(Protocol):
    """COL-IF-02 / NFR-01：可替换持久化端口，无自动过期或私有材料存储。"""

    def latest(self, key: CollectionCacheKey) -> StoredCollectionBatch | None:
        """仅同作用域最近成功批次；按首次取得时间和batch_id稳定排序。"""
        raise NotImplementedError()

    def get_batch(self, key: CollectionCacheKey, batch_id: UUID) -> StoredCollectionBatch | None:
        """读取指定旧绑定批次，不偷偷替换成最新批次。"""
        raise NotImplementedError()

    def get_page(
        self, key: CollectionCacheKey, batch_id: UUID, page_number: int,
    ) -> StoredCollectionPage | None:
        """只读已存页；不存在与存储错误必须区分。"""
        raise NotImplementedError()

    def commit(
        self, batch: StoredCollectionBatch, page: StoredCollectionPage, *,
        claim_id: UUID, expected_revision: int | None,
    ) -> StoredCollectionBatch:
        """验证有效claim和预期修订后原子提交；冲突/失败不得部分保存。"""
        raise NotImplementedError()

    def claim(self, request: CollectionFetchKey) -> CollectionFetchClaim:
        """取得60秒同页协调身份；pending不得启动重复查询。"""
        raise NotImplementedError()

    def finish(self, claim_id: UUID) -> None:
        """释放本次取数协调身份，不删除已提交公共API材料。"""
        raise NotImplementedError()


class ReportModelPort(Protocol):
    """只读固定输入的文本分析节点，无工具调用。"""

    def generate(self, input: LlmInput, system_prompt: str) -> str:
        """返回报告原文；超时或接入错误抛 ModelError。"""
        raise NotImplementedError()
