/** FE-IF-01：API Client 能力声明，不包含请求、重试或业务实现。 */
import type {
  ConfirmSubjectCommand, EditableDraft, ManualDraft, OperationHandle, OperationView,
  RetryAnalysisCommand, RetryQueryCommand, SearchCommand, SearchResult, SessionExpiry,
  SubmitEvidenceCommand, UUID, WithdrawalResult, WorkspaceState,
} from "../contracts/boundary.js";

export interface ScreeningApiClient {
  /** POST sessions：显式创建，key为幂等键。 */
  createSession(key: UUID): Promise<WorkspaceState>;
  /** GET sessions/{sid}：恢复不续期。 */
  restoreSession(sid: UUID): Promise<WorkspaceState>;
  /** 仅明确用户活动，后台轮询不能调用。 */
  notifyActivity(sid: UUID): Promise<SessionExpiry>;
  /** 结束私人会话，已共享资料另按共享规则管理。 */
  resetSession(sid: UUID, key: UUID): Promise<void>;
  /** 搜索候选，单条也不自动确认。 */
  search(sid: UUID, command: SearchCommand, key: UUID): Promise<SearchResult>;
  /** 用户点击后确认指定候选。 */
  confirmSubject(sid: UUID, command: ConfirmSubjectCommand, key: UUID): Promise<OperationHandle>;
  /** 仅保存草稿，不调用LLM。 */
  saveDraft(sid: UUID, draft: EditableDraft, key: UUID): Promise<ManualDraft>;
  /** 明确清空，解除预填充来源关联。 */
  clearDraft(sid: UUID, key: UUID): Promise<void>;
  /** 接纳合法草稿，随后自动分析。 */
  submitEvidence(sid: UUID, command: SubmitEvidenceCommand, key: UUID): Promise<OperationHandle>;
  /** 只对当前版本重分析，不重复保存。 */
  retryAnalysis(sid: UUID, command: RetryAnalysisCommand, key: UUID): Promise<OperationHandle>;
  /** 只重试原计划失败类别。 */
  retryQueries(sid: UUID, command: RetryQueryCommand, key: UUID): Promise<OperationHandle>;
  /** 只读进度或完整终态，不续期。 */
  getOperation(sid: UUID, opid: UUID): Promise<OperationView>;
  /** 服务端仍验证当前所有者。 */
  withdrawShare(receiptId: UUID, key: UUID): Promise<WithdrawalResult>;
}
