/** FE-IF-01：同源 HTTP Client；统一携带匿名 Cookie 与结构化错误。 */
import type {
  ConfirmSubjectCommand, EditableDraft, ErrorEnvelope, ErrorInfo, ManualDraft, OperationHandle, OperationView,
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

const FALLBACK_ERROR: ErrorInfo = {
  code: "INTERNAL_ERROR",
  hint_id: "INTERNAL_ERROR",
  fields: [],
  retryable: false,
};

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error?: unknown }).error;
  return typeof error === "object" && error !== null
    && "code" in error && typeof (error as { code?: unknown }).code === "string"
    && "hint_id" in error && typeof (error as { hint_id?: unknown }).hint_id === "string"
    && "fields" in error && Array.isArray((error as { fields?: unknown }).fields)
    && "retryable" in error && typeof (error as { retryable?: unknown }).retryable === "boolean";
}

export class ApiClientError extends Error {
  readonly info: ErrorInfo;
  readonly operationId: UUID | null;
  readonly status: number;

  constructor(status: number, envelope: ErrorEnvelope | null) {
    super("Screening API request failed");
    this.name = "ApiClientError";
    this.status = status;
    this.info = envelope?.error ?? FALLBACK_ERROR;
    this.operationId = envelope?.operation_id ?? null;
  }
}

type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export class HttpScreeningApiClient implements ScreeningApiClient {
  readonly #baseUrl: string;
  readonly #fetcher: Fetcher;

  constructor(baseUrl = "/api/v1", fetcher: Fetcher = (input, init) => fetch(input, init)) {
    this.#baseUrl = baseUrl.replace(/\/$/, "");
    this.#fetcher = fetcher;
  }

  async #request<T>(
    path: string,
    method: "GET" | "POST" | "PUT" | "DELETE",
    options: { body?: unknown; key?: UUID } = {},
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (options.key !== undefined) headers["Idempotency-Key"] = options.key;
    const response = await this.#fetcher(`${this.#baseUrl}${path}`, {
      method,
      headers,
      credentials: "include",
      ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
    });
    if (!response.ok) {
      let parsed: unknown = null;
      try {
        parsed = await response.json();
      } catch {
        parsed = null;
      }
      throw new ApiClientError(response.status, isErrorEnvelope(parsed) ? parsed : null);
    }
    if (response.status === 204) return undefined as T;
    return await response.json() as T;
  }

  createSession(key: UUID): Promise<WorkspaceState> {
    return this.#request("/sessions", "POST", { key });
  }

  restoreSession(sid: UUID): Promise<WorkspaceState> {
    return this.#request(`/sessions/${encodeURIComponent(sid)}`, "GET");
  }

  notifyActivity(sid: UUID): Promise<SessionExpiry> {
    return this.#request(`/sessions/${encodeURIComponent(sid)}/activity`, "POST", { body: {} });
  }

  resetSession(sid: UUID, key: UUID): Promise<void> {
    return this.#request(`/sessions/${encodeURIComponent(sid)}`, "DELETE", { key });
  }

  search(sid: UUID, command: SearchCommand, key: UUID): Promise<SearchResult> {
    return this.#request(`/sessions/${encodeURIComponent(sid)}/search`, "POST", { body: command, key });
  }

  confirmSubject(sid: UUID, command: ConfirmSubjectCommand, key: UUID): Promise<OperationHandle> {
    return this.#request(`/sessions/${encodeURIComponent(sid)}/confirm`, "POST", { body: command, key });
  }

  saveDraft(sid: UUID, draft: EditableDraft, key: UUID): Promise<ManualDraft> {
    return this.#request(`/sessions/${encodeURIComponent(sid)}/draft`, "PUT", { body: draft, key });
  }

  clearDraft(sid: UUID, key: UUID): Promise<void> {
    return this.#request(`/sessions/${encodeURIComponent(sid)}/draft`, "DELETE", { key });
  }

  submitEvidence(sid: UUID, command: SubmitEvidenceCommand, key: UUID): Promise<OperationHandle> {
    return this.#request(`/sessions/${encodeURIComponent(sid)}/evidence`, "POST", { body: command, key });
  }

  retryAnalysis(sid: UUID, command: RetryAnalysisCommand, key: UUID): Promise<OperationHandle> {
    return this.#request(`/sessions/${encodeURIComponent(sid)}/analysis/retry`, "POST", { body: command, key });
  }

  retryQueries(sid: UUID, command: RetryQueryCommand, key: UUID): Promise<OperationHandle> {
    return this.#request(`/sessions/${encodeURIComponent(sid)}/queries/retry`, "POST", { body: command, key });
  }

  getOperation(sid: UUID, opid: UUID): Promise<OperationView> {
    return this.#request(
      `/sessions/${encodeURIComponent(sid)}/operations/${encodeURIComponent(opid)}`,
      "GET",
    );
  }

  withdrawShare(receiptId: UUID, key: UUID): Promise<WithdrawalResult> {
    return this.#request(`/shares/${encodeURIComponent(receiptId)}/withdraw`, "POST", { body: {}, key });
  }
}

export const screeningApi: ScreeningApiClient = new HttpScreeningApiClient();
