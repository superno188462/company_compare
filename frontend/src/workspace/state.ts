/** FE-DATA-01：工作台展示状态声明，不实现状态转换。 */
import type {
  EditableDraft, OperationHandle, SearchResult, ValidationMessageKey, WorkspaceState,
} from "../contracts/boundary.js";

export type WorkspacePhase =
  | "initial" | "searching" | "candidates" | "querying" | "insufficient"
  | "snapshot_review" | "generating" | "ready" | "error" | "expired";

export type FieldErrors = Partial<Record<string, ValidationMessageKey>>;

export interface WorkspaceViewModel {
  /** 后端确认状态的唯一可信来源。 */
  server: WorkspaceState;
  /** 搜索词不等于当前已确认主体。 */
  queryText: string;
  searchResult: SearchResult | null;
  /** 尚未保存的本地编辑，不等于证据。 */
  localDraft: EditableDraft | null;
  /** 拒绝旧保存响应覆盖新编辑。 */
  draftEditRevision: number;
  /** 默认false，独立于共享。 */
  snapshotAcknowledged: boolean;
  /** 默认false，不能代用户勾选。 */
  shareConsent: boolean;
  activeOperation: OperationHandle | null;
  phase: WorkspacePhase;
  fieldErrors: FieldErrors;
  /** 停止等待不代表服务端任务或计费取消。 */
  isWaiting: boolean;
}
