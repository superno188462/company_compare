"""COL-DATA-01 / COL-IF-02：仅服务端使用的持久化与取数协调声明。"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, StrictStr

from .base import ContractModel
from .boundary import CreditCode, ProviderRecord, SmallText
from .generated import CollectionToolName

NonNegativeCount = Annotated[StrictInt, Field(ge=0)]
PositiveCount = Annotated[StrictInt, Field(ge=1)]


class CollectionCacheKey(ContractModel):
    """公共材料身份；不接收客户端作用域，不包含实际凭据。"""

    provider: SmallText = Field(description="服务端提供方标识。")
    scope_id: SmallText = Field(description="服务端凭据/权益/端点作用域，不向客户端或模型公开。")
    normalization_version: SmallText = Field(description="规范化结构版本；不同版本不复用。")
    subject_credit_code: CreditCode = Field(description="已经人工确认的主体代码。")
    tool_name: CollectionToolName = Field(description="固定计划中的真实工具。")
    arguments_json: StrictStr = Field(description="规范化固定查询参数JSON；不得从客户端透传。")
    page_size: Literal[20] | None = Field(description="司法固定20；非司法完整快照为null。")


class StoredCollectionBatch(ContractModel):
    """已成功取得批次元信息，无TTL、无私人所有者或诊断。"""

    key: CollectionCacheKey = Field(description="包括主体与服务端作用域的完整缓存身份。")
    batch_id: UUID = Field(description="成功采集批次的稳定标识。")
    revision: PositiveCount = Field(description="接纳新页时递增；追加不重置批次取得时间。")
    first_fetched_at: AwareDatetime = Field(description="本批首次有效取得时间。")
    last_fetched_at: AwareDatetime = Field(description="本批最近有效页实际取得时间。")
    total_count: NonNegativeCount | None = Field(description="最近有效页声明总数，未知为null。")
    has_more: StrictBool | None = Field(description="是否还有上游页，未知为null。")
    total_changed: StrictBool = Field(description="跨页已知总数发生变化，不代表原子快照。")
    collected_count: NonNegativeCount = Field(description="去重后已取得材料数，不受报告200条预算限制。")


class StoredCollectionPage(ContractModel):
    """一次成功接纳的上游页或非司法完整快照；不是浏览展示页。"""

    batch_id: UUID = Field(description="所属采集批次。")
    page_number: PositiveCount = Field(description="上游连续页号；非司法完整快照为1。")
    queried_at: AwareDatetime = Field(description="本页实际取得时间，不因访问改变。")
    records: list[ProviderRecord] = Field(max_length=200, description="完整规范化记录；司法至多20，非司法完整快照至多200。")


class CollectionFetchKey(ContractModel):
    """同页缺失查询的公共协调身份，不包含用户/会话/任务详情。"""

    key: CollectionCacheKey = Field(description="采集目标的完整缓存身份。")
    batch_id: UUID | None = Field(description="追加页所属批次；初查和新刷新为null。")
    page_number: PositiveCount = Field(description="目标上游页，首查或刷新为1。")
    mode: Literal["initial", "load_page", "refresh_tool"] = Field(description="初查、追加或明确刷新。")
    refresh_round_id: UUID | None = Field(description="主动更新轮次UUID；非更新为null，防止永久键挡住以后更新。")


class CollectionFetchClaim(ContractModel):
    """60秒取数协调租约，与API材料保存期限无关。"""

    claim_id: UUID = Field(description="仅服务端用于校验本次采集的有效持有者。")
    state: Literal["acquired", "pending"] = Field(description="只有acquired可请求上游；pending复用已提交页或等待。")
    lease_until: AwareDatetime = Field(description="租约终止时间，迟到持有者不得覆盖新claim提交。")
