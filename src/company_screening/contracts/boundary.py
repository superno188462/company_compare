"""BE-DATA-02/BE-IF-07：服务命令和边界模型，仅声明字段与约束。"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, StringConstraints

from .base import ContractModel
from .generated import Category, HintCode, QueryDiagnostic, Subject, ToolCoverage, WorkflowPayload

CreditCode = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9ABCDEFGHJKLMNPQRTUWXY]{18}$")]
SmallText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]
HttpUrl = Annotated[str, StringConstraints(strict=True, pattern=r"^https?://[^\s]+$", max_length=2048)]
EvidenceCategory = Category | Literal["other"]
ProviderFailureCode = Literal[
    "UPSTREAM_TIMEOUT", "UPSTREAM_AUTH", "UPSTREAM_LIMIT", "UPSTREAM_ERROR",
    "UPSTREAM_INVALID", "UPSTREAM_INCOMPLETE", "SUBJECT_RESPONSE_MISMATCH",
]
ModelFailureCode = Literal["MODEL_TIMEOUT", "MODEL_CONTEXT_LIMIT", "MODEL_AUTH", "MODEL_UNAVAILABLE"]
ErrorCode = Literal[
    "INPUT_INVALID", "SUBJECT_UNCONFIRMED", "CANDIDATE_INVALID", "CREDIT_MISSING",
    "CREDIT_MISMATCH", "CREDIT_CONFLICT", "SNAPSHOT_CONFIRM_REQUIRED", "SNAPSHOT_UNAVAILABLE",
    "SHARE_REQUIREMENTS", "SESSION_EXPIRED", "RESOURCE_NOT_FOUND", "OPERATION_CONFLICT",
    "IDEMPOTENCY_CONFLICT", "UPSTREAM_TIMEOUT", "UPSTREAM_AUTH", "UPSTREAM_LIMIT",
    "UPSTREAM_ERROR", "UPSTREAM_INVALID", "UPSTREAM_INCOMPLETE", "SUBJECT_RESPONSE_MISMATCH",
    "INPUT_TOO_LARGE", "STORAGE_UNAVAILABLE", "INTERNAL_ERROR",
]
ValidationMessageKey = Literal[
    "input_invalid",
    "company_name_required", "company_name_length", "credit_code_format", "content_required",
    "content_length", "url_format", "future_time", "time_format", "share_fields_required",
    "snapshot_ack_required", "no_candidate_code", "evidence_limit", "draft_saved", "clipboard_failed",
]
OperationState = Literal["queued", "running", "succeeded", "failed"]
OperationPhase = Literal["query", "snapshot", "save", "share", "analyze", "assemble", "complete"]


class ActorContext(ContractModel):
    """BE-DATA-02：仅由服务端建立的可信所有者上下文，不是请求体。"""

    actor_id: UUID = Field(description="已验证的匿名所有者标识，不发送给模型。")


class SearchCommand(ContractModel):
    """搜索输入；去空白及搜索语义留待实现阶段。"""

    query: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=200)] = Field(description="公司名称查询词。")
    page_size: Annotated[int, Field(strict=True, ge=1, le=20)] = Field(default=20, description="每页候选数。")
    cursor: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=512)] | None = Field(default=None, description="提供方不透明分页游标。")


class ProviderCandidate(ContractModel):
    """BE-IF-07：提供方规范化主体字段，不含人工确认或选择。"""

    name: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=200)] = Field(description="企业全称。")
    credit_code: CreditCode | None = Field(description="缺失时不能确认主体。")
    registered_region: SmallText | None = Field(description="注册省市，未知为 null。")
    legal_representative: SmallText | None = Field(description="法定代表人，未知为 null。")
    established_on: date | None = Field(description="成立日期，未知为 null。")


class Candidate(ProviderCandidate):
    """BE-DATA-02：展示候选；应用生成 ID，用户选择后才可确认。"""

    candidate_id: UUID = Field(description="绑定本次搜索的候选标识。")
    selectable: StrictBool = Field(description="是否具备有效代码可供人工确认。")


class SearchResult(ContractModel):
    """候选页；0或1条都不会自动确认。"""

    search_id: UUID = Field(description="绑定所有者、查询和有效期的搜索标识。")
    items: list[Candidate] = Field(max_length=20, description="本页候选。")
    next_cursor: str | None = Field(description="下一页游标，无下一页为 null。")
    total: Annotated[int, Field(strict=True, ge=0)] | None = Field(description="已知总数；提供方未给出时 null。")


class ConfirmSubjectCommand(ContractModel):
    """BE-IF-03：明确确认指定候选，而非自动选择算法。"""

    search_id: UUID = Field(description="候选所属搜索。")
    candidate_id: UUID = Field(description="用户点击的候选。")
    expected_generation: Annotated[int, Field(strict=True, ge=0)] = Field(description="当前主体代次，首次确认前为0。")
    discard_draft: StrictBool = Field(description="是否明确同意丢弃未提交草稿。")


class EditableDraft(ContractModel):
    """BE-IF-04：允许待修改内容，保存不等于接纳为证据。"""

    record_credit_code: Annotated[str, StringConstraints(strict=True, max_length=64)] | None = Field(description="用户核对的来源主体代码，允许待修正。")
    content: Annotated[str, StringConstraints(strict=True, max_length=4000)] = Field(description="尚未接纳的正文。")
    source_url: Annotated[str, StringConstraints(strict=True, max_length=2048)] | None = Field(description="待核对的来源地址，不触发访问。")
    observed_at: Annotated[str, StringConstraints(strict=True, max_length=64)] | None = Field(description="原始查看时间输入，不自动填现在。")
    event_time: Annotated[str, StringConstraints(strict=True, max_length=256)] | None = Field(description="可选事件时间/期间原文。")
    category: EvidenceCategory = Field(description="取得类别，未分类为 other。")


class ManualDraft(EditableDraft):
    """服务端保存的草稿及来源关联；前端不能伪造其来源。"""

    draft_id: UUID = Field(description="服务端草稿标识。")
    from_snapshot_id: UUID | None = Field(description="预填充来源关联；明确清空前保留。")
    issues: list[HintCode] = Field(description="待修正问题提示编号。")


class SubmitEvidenceCommand(ContractModel):
    """接纳最近保存的服务端草稿；不允许直接指定 source。"""

    draft_id: UUID = Field(description="本次提交的服务端草稿。")
    expected_generation: Annotated[int, Field(strict=True, ge=1)] = Field(description="预期主体代次。")
    expected_evidence_version: Annotated[int, Field(strict=True, ge=0)] = Field(description="预期分析输入版本。")
    snapshot_acknowledged: StrictBool = Field(description="他人快照独立知情确认。")
    share_consent: StrictBool = Field(description="是否主动同意共享，不与知情确认混同。")


class RetryAnalysisCommand(ContractModel):
    """只对当前版本重新分析，不重复保存或共享。"""

    expected_generation: Annotated[int, Field(strict=True, ge=1)] = Field(description="当前主体代次。")
    expected_evidence_version: Annotated[int, Field(strict=True, ge=0)] = Field(description="当前分析输入版本。")


class RetryQueryCommand(ContractModel):
    """仅可重试原计划中的失败类别。"""

    expected_generation: Annotated[int, Field(strict=True, ge=1)] = Field(description="当前主体代次。")
    categories: list[Category] = Field(min_length=1, max_length=5, description="失败类别，唯一性和计划归属由业务层校验。")


class OperationHandle(ContractModel):
    """BE-IF-06：长任务定位，不是读取权限凭据。"""

    operation_id: UUID = Field(description="当前操作标识。")
    session_id: UUID = Field(description="所属会话标识。")
    session_generation: Annotated[int, Field(strict=True, ge=1)] = Field(description="所属主体代次。")


class FieldIssue(ContractModel):
    """错误字段与固定文案键，不返回用户原始值。"""

    field: str = Field(description="出错的请求字段名。")
    message_key: ValidationMessageKey = Field(description="text-dict.validation 中的已有键。")


class ErrorInfo(ContractModel):
    """BE-ERR-01：脱敏、机器可读错误。"""

    code: ErrorCode = Field(description="稳定错误代码。")
    hint_id: HintCode = Field(description="全局提示字典键。")
    fields: list[FieldIssue] = Field(description="就近字段提示。")
    retryable: StrictBool = Field(description="是否允许用户重试，不代表自动重试。")


class ErrorEnvelope(ContractModel):
    """HTTP 非成功响应。"""

    error: ErrorInfo = Field(description="脱敏错误。")
    operation_id: UUID | None = Field(description="已创建操作时用于定位。")


class OperationView(OperationHandle):
    """任务进度/终态；result 与 error 的条件约束待实现。"""

    state: OperationState = Field(description="queued/running/succeeded/failed。")
    phase: OperationPhase = Field(description="当前业务阶段。")
    result: WorkflowPayload | None = Field(description="终态一次性完整结果，非半段报告。")
    error: ErrorInfo | None = Field(description="无法提供可靠结果时的脱敏错误。")


class ShareReceipt(ContractModel):
    """仅本所有者可见的共享回执和当前状态。"""

    receipt_id: UUID = Field(description="回执定位ID，不单独授权撤回。")
    subject_credit_code: CreditCode = Field(description="共享记录主体。")
    shared_at: AwareDatetime = Field(description="服务端共享时间。")
    expires_at: AwareDatetime = Field(description="按来源查看与共享时间共同计算。")
    state: Literal["active", "withdrawn"] = Field(description="当前共享状态。")


class WorkspaceState(ContractModel):
    """BE-IF-01：有效会话恢复视图，不包含所有者凭据。"""

    session_id: UUID = Field(description="会话标识。")
    expires_at: AwareDatetime = Field(description="最后用户操作24小时后。")
    session_generation: Annotated[int, Field(strict=True, ge=0)] = Field(description="未确认主体时为0。")
    current_subject: Subject | None = Field(description="已确认主体，尚未确认时 null。")
    payload: WorkflowPayload | None = Field(description="最近完整结果。")
    draft: ManualDraft | None = Field(description="当前私有草稿，不等于证据。")
    active_operation: OperationHandle | None = Field(description="当前代次在途操作。")
    share_receipts: list[ShareReceipt] = Field(description="本所有者尚未到期的共享回执。")


class WithdrawalResult(ContractModel):
    """共享撤回结果，重复撤回保持幂等。"""

    receipt_id: UUID = Field(description="已撤回回执。")
    state: Literal["withdrawn"] = Field(description="固定为 withdrawn。")


class SessionExpiry(ContractModel):
    """用户活动续期结果。"""

    expires_at: AwareDatetime = Field(description="服务端计算的会话到期时间。")


class ProviderSearchPage(ContractModel):
    """提供方搜索端口返回，不含应用候选ID。"""

    items: list[ProviderCandidate] = Field(max_length=20, description="本页规范化候选。")
    next_cursor: str | None = Field(description="下一页游标。")
    total: Annotated[int, Field(strict=True, ge=0)] | None = Field(description="提供方已知总数。")


class ProviderRecord(ContractModel):
    """BE-IF-07：一条完整取得的规范化提供方记录。"""

    record_id: SmallText = Field(description="提供方类别内稳定记录ID。")
    content: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4000)] = Field(description="实际取得内容，不静默截断。")
    record_credit_code: CreditCode | None = Field(description="原记录中的明确主体代码，无则 null。")
    event_time: SmallText | None = Field(description="来源中明确的事件时间/期间。")
    source_url: HttpUrl | None = Field(description="原记录定位链接，不触发网页读取。")
    source_publisher: SmallText | None = Field(description="原记录所称发布者。")


class ProviderCategoryBatch(ContractModel):
    """分类批次；司法可声明有限范围，其他类别沿用完整批次契约。"""

    binding_credit_code: CreditCode = Field(description="有可验证查询映射的主体代码。")
    category: Category = Field(description="计划类别。")
    queried_at: AwareDatetime = Field(description="实际取得时间。")
    scope_description: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)] = Field(description="实际接口及子范围，不夸大覆盖。")
    records: list[ProviderRecord] = Field(max_length=200, description="实际取得的完整记录；不截断单条正文，成功无记录为空列表。")
    completeness: Literal["complete", "partial"] = Field(default="complete", description="QUERY-WINDOW-1.0：完整或明确有限范围的批次；旧适配器缺省完整。")
    tool_coverage: list[ToolCoverage] = Field(default_factory=list, max_length=6, description="司法固定子工具的本轮取得范围，不包含原始错误或密钥。")
    error_code: ProviderFailureCode | None = Field(default=None, description="部分批次中的第一个子工具错误；仅主动限制范围时为null。")
    diagnostic: QueryDiagnostic | None = Field(default=None, description="首个失败子工具的受控诊断，仅服务端传递，不进入LLM。")
