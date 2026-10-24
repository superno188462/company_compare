/** COLLECTION-1.0 / COL-FE-IF-01：同源材料浏览、指定页查询与单项更新客户端。 */
import type { OperationHandle, UUID } from "../contracts/boundary.js";
import type {
  CollectionOperationView, CollectionOverview, CollectionRecordsPage, CollectionToolName,
  LoadCollectionPageCommand, RefreshCollectionToolCommand,
} from "../contracts/generated.js";
import { ApiClientError } from "./client.js";
import type { ErrorEnvelope } from "../contracts/boundary.js";

export interface CollectionApiClient {
  /** 只读当前已确认主体的固定批次概览，不取上游、不续期。 */
  getCollections(sid: UUID): Promise<CollectionOverview>;
  /** 本地已存材料每页20；page省略为1；batchId必须匹配当前绑定。 */
  getCollectionRecords(
    sid: UUID, toolName: CollectionToolName, batchId: UUID, page?: number,
  ): Promise<CollectionRecordsPage>;
  /** 幂等查询所选司法工具下一页，先读存量，不改报告或草稿。 */
  loadCollectionPage(sid: UUID, command: LoadCollectionPageCommand, key: UUID): Promise<OperationHandle>;
  /** 显式更新单工具新批次；失败保留旧资料，不自动分析。 */
  refreshCollectionTool(sid: UUID, command: RefreshCollectionToolCommand, key: UUID): Promise<OperationHandle>;
  /** 仅本会话采集任务，不共享他人的任务状态。 */
  getCollectionOperation(sid: UUID, opid: UUID): Promise<CollectionOperationView>;
}

/** 同源浏览HTTP边界；每次最多等待30秒，写意图重放由上层保留原键。 */
async function collectionRequest<T>(path: string, body?: unknown, key?: UUID): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30_000);
  try {
    const response = await fetch(`/api/v1${path}`, {
      method: body === undefined ? "GET" : "POST", credentials: "include", signal: controller.signal,
      headers: { Accept: "application/json", ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(key === undefined ? {} : { "Idempotency-Key": key }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) {
      let envelope: ErrorEnvelope | null = null;
      try { const value = await response.json() as ErrorEnvelope; if (value?.error?.code) envelope = value; } catch { /* 空或非法响应使用安全通用错误。 */ }
      throw new ApiClientError(response.status, envelope);
    }
    return await response.json() as T;
  } finally { clearTimeout(timer); }
}

export const collectionApi: CollectionApiClient = {
  getCollections: (sid) => collectionRequest<CollectionOverview>(`/sessions/${encodeURIComponent(sid)}/collections`),
  getCollectionRecords: (sid, name, batch, page = 1) => collectionRequest<CollectionRecordsPage>(
    `/sessions/${encodeURIComponent(sid)}/collections/${encodeURIComponent(name)}/records?batch_id=${encodeURIComponent(batch)}&page=${page}`),
  loadCollectionPage: (sid, command, key) => collectionRequest<OperationHandle>(`/sessions/${encodeURIComponent(sid)}/collections/pages`, command, key),
  refreshCollectionTool: (sid, command, key) => collectionRequest<OperationHandle>(`/sessions/${encodeURIComponent(sid)}/collections/refresh`, command, key),
  getCollectionOperation: (sid, opid) => collectionRequest<CollectionOperationView>(`/sessions/${encodeURIComponent(sid)}/collection-operations/${encodeURIComponent(opid)}`),
};
