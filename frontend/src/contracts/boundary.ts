/** BE-DATA-02：HTTP 边界类型；模型字段与后端 SDD 对齐。 */
import type dictionary from "../../../contracts/text-dict.json";
import type { Category, HintCode, Subject, WorkflowPayload } from "./generated.js";

/** 公开定位标识，不能单独用作授权凭据。 */
export type UUID = string;
/** 带时区的 RFC3339 字符串。 */
export type Timestamp = string;
export type EvidenceCategory = Category | "other";
export type ValidationMessageKey = keyof typeof dictionary.validation;
export type ErrorCode =
  | "INPUT_INVALID" | "SUBJECT_UNCONFIRMED" | "CANDIDATE_INVALID"
  | "CREDIT_MISSING" | "CREDIT_MISMATCH" | "CREDIT_CONFLICT"
  | "SNAPSHOT_CONFIRM_REQUIRED" | "SNAPSHOT_UNAVAILABLE" | "SHARE_REQUIREMENTS"
  | "SESSION_EXPIRED" | "RESOURCE_NOT_FOUND" | "OPERATION_CONFLICT"
  | "IDEMPOTENCY_CONFLICT" | "UPSTREAM_TIMEOUT" | "UPSTREAM_AUTH"
  | "UPSTREAM_LIMIT" | "UPSTREAM_ERROR" | "UPSTREAM_INVALID"
  | "UPSTREAM_INCOMPLETE" | "SUBJECT_RESPONSE_MISMATCH"
  | "INPUT_TOO_LARGE" | "STORAGE_UNAVAILABLE" | "INTERNAL_ERROR";

export interface SearchCommand {
  /** 公司名称，1～200字符；不是自由提问。 */
  query: string;
  /** 省略时20，范围1～20。 */
  page_size?: number;
  /** 省略时null，长度1～512。 */
  cursor?: string | null;
}

export interface Candidate {
  /** 绑定本次搜索的候选ID。 */
  candidate_id: UUID;
  name: string;
  /** 缺少有效代码不能确认。 */
  credit_code: string | null;
  registered_region: string | null;
  legal_representative: string | null;
  established_on: string | null;
  /** 仍需用户点击，不能据此自动确认。 */
  selectable: boolean;
}

export interface SearchResult {
  search_id: UUID;
  items: Candidate[];
  next_cursor: string | null;
  total: number | null;
}

export interface ConfirmSubjectCommand {
  search_id: UUID;
  candidate_id: UUID;
  expected_generation: number;
  discard_draft: boolean;
}

export interface EditableDraft {
  /** 用户核对的来源记录代码，不自动伪装成官网值。 */
  record_credit_code: string | null;
  content: string;
  source_url: string | null;
  observed_at: string | null;
  event_time: string | null;
  category: EvidenceCategory;
}

export interface ManualDraft extends EditableDraft {
  draft_id: UUID;
  /** 服务端维护，客户端不能通过修改source去除来源关联。 */
  from_snapshot_id: UUID | null;
  issues: HintCode[];
}

export interface SubmitEvidenceCommand {
  draft_id: UUID;
  expected_generation: number;
  expected_evidence_version: number;
  /** 独立于是否共享。 */
  snapshot_acknowledged: boolean;
  /** 默认不勾选。 */
  share_consent: boolean;
}

export interface RetryAnalysisCommand {
  expected_generation: number;
  expected_evidence_version: number;
}

export interface RetryQueryCommand {
  expected_generation: number;
  /** 仅原计划中的失败类别，1～5项且唯一。 */
  categories: Category[];
}

export interface OperationHandle {
  operation_id: UUID;
  session_id: UUID;
  session_generation: number;
}

export interface FieldIssue {
  field: string;
  message_key: ValidationMessageKey;
}

export interface ErrorInfo {
  code: ErrorCode;
  hint_id: HintCode;
  fields: FieldIssue[];
  retryable: boolean;
}

export interface ErrorEnvelope {
  error: ErrorInfo;
  operation_id: UUID | null;
}

export interface OperationView extends OperationHandle {
  state: "queued" | "running" | "succeeded" | "failed";
  phase: "query" | "snapshot" | "save" | "share" | "analyze" | "assemble" | "complete";
  /** 终态完整payload，不是流式文本片段。 */
  result: WorkflowPayload | null;
  error: ErrorInfo | null;
}

export interface ShareReceipt {
  receipt_id: UUID;
  subject_credit_code: string;
  shared_at: Timestamp;
  expires_at: Timestamp;
  state: "active" | "withdrawn";
}

export interface WorkspaceState {
  session_id: UUID;
  expires_at: Timestamp;
  session_generation: number;
  current_subject: Subject | null;
  payload: WorkflowPayload | null;
  draft: ManualDraft | null;
  active_operation: OperationHandle | null;
  share_receipts: ShareReceipt[];
}

export interface WithdrawalResult {
  receipt_id: UUID;
  state: "withdrawn";
}

export interface SessionExpiry {
  expires_at: Timestamp;
}
