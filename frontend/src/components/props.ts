/** FE-DATA-02：组件输入与回调，仅声明契约，不提前实现页面。 */
import type dictionary from "../../../contracts/text-dict.json";
import type {
  EditableDraft, SearchResult, ShareReceipt, UUID,
} from "../contracts/boundary.js";
import type {
  Category, Evidence, QueryCoverage, Subject, WorkflowStatus,
} from "../contracts/generated.js";
import type { FieldErrors } from "../workspace/state.js";

export interface SearchPanelProps {
  queryText: string;
  busy: boolean;
  onQueryChange(value: string): void;
  onSearch(): void;
}

export interface CandidateListProps {
  result: SearchResult;
  busy: boolean;
  /** 只在用户明确点击时调用。 */
  onConfirm(candidateId: UUID): void;
}

export interface SubjectHeaderProps {
  subject: Subject | null;
}

export interface CoveragePanelProps {
  coverage: QueryCoverage;
  busy: boolean;
  onRetry(categories: Category[]): void;
}

export interface EvidenceCardProps {
  evidence: Evidence;
}

export interface ReportPanelProps {
  summaryText: string;
  status: WorkflowStatus;
  onRetry(): void;
}

export interface ManualEvidenceFormProps {
  draft: EditableDraft;
  fromSnapshot: boolean;
  snapshotAcknowledged: boolean;
  shareConsent: boolean;
  busy: boolean;
  fieldErrors: FieldErrors;
  onChange(value: EditableDraft): void;
  onSaveDraft(): void;
  onSubmit(): void;
  onClear(): void;
  onAcknowledge(value: boolean): void;
  onShareChange(value: boolean): void;
}

export type OfficialSite = (typeof dictionary.official_sites)[number];

export interface OfficialLinksProps {
  sites: OfficialSite[];
  /** 仅主动复制固定地址，不能读取剪贴板或网页。 */
  onCopy(url: string): void;
}

export interface ShareReceiptListProps {
  receipts: ShareReceipt[];
  onWithdraw(receiptId: UUID): void;
}
