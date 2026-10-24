/** COLLECTION-1.0：材料浏览状态、异步任务与原报告/草稿互相隔离。 */
import { useEffect, useRef, useState } from "react";
import dictionary from "../../../contracts/text-dict.json";
import { collectionApi } from "../api/collection-client.js";
import { ApiClientError } from "../api/client.js";
import { CollectionBrowser, CollectionRuntime, CollectionToolPanel } from "../components/CollectionBrowser.js";
import { EvidenceCard } from "../components/WorkspacePanels.js";
import type { ErrorInfo, OperationHandle, WorkspaceState } from "../contracts/boundary.js";
import type {
  Category, CollectionOverview, CollectionRecordsPage, CollectionToolView,
  JudicialToolName, LoadCollectionPageCommand, RefreshCollectionToolCommand,
} from "../contracts/generated.js";

type Pending = ({ kind: "load"; command: LoadCollectionPageCommand } | { kind: "refresh"; command: RefreshCollectionToolCommand }) & {
  key: string; handle: OperationHandle | null; tool: string;
};
type PageState = { state: "idle" | "loading" | "ready" | "error"; error: ErrorInfo | null; page: CollectionRecordsPage | null };
const FALLBACK: ErrorInfo = { code: "INTERNAL_ERROR", hint_id: "INTERNAL_ERROR", fields: [], retryable: false };

export function CollectionWorkspace({ workspace, busy, onBusyChange, onSupplement, onExpired }: {
  workspace: WorkspaceState; busy: boolean; onBusyChange(value: boolean): void;
  onSupplement(category: Category): void; onExpired(): void;
}) {
  const copy = dictionary.collection_labels;
  const [view, setView] = useState<CollectionOverview | null>(null);
  const [error, setError] = useState<ErrorInfo | null>(null);
  const [pages, setPages] = useState<Record<string, PageState>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const current = useRef(view);
  const pending = useRef<Pending | null>(null);
  const working = useRef(false);
  const alive = useRef(true);
  const requests = useRef<Record<string, number>>({});
  const inFlight = useRef(new Set<string>());
  const overviewRequest = useRef(0);
  const identity = `${workspace.session_id}:${workspace.session_generation}`;
  const identityRef = useRef(identity);
  identityRef.current = identity;

  const accept = (value: CollectionOverview) => {
    if (!alive.current || identityRef.current !== identity) return;
    if (current.current !== null && value.collection_revision < current.current.collection_revision) return;
    current.current = value;
    setView(value); setError(null);
    setPages((previous) => Object.fromEntries(Object.entries(previous).filter(([name, item]) =>
      item.page === null || value.tools.some((tool) => tool.tool_name === name && tool.batch_id === item.page?.batch_id))));
  };

  const reload = async () => {
    const sequence = ++overviewRequest.current;
    try {
      const value = await collectionApi.getCollections(workspace.session_id);
      if (sequence === overviewRequest.current) accept(value);
    } catch (caught) {
      if (!alive.current || identityRef.current !== identity || sequence !== overviewRequest.current) return;
      if (caught instanceof ApiClientError && caught.status === 410) { onExpired(); return; }
      setError(caught instanceof ApiClientError ? caught.info : FALLBACK);
    }
  };

  const read = async (tool: CollectionToolView, page: number) => {
    if (tool.batch_id === null) return;
    const name = tool.tool_name;
    const requestKey = `${name}:${tool.batch_id}:${page}`;
    if (inFlight.current.has(requestKey)) return;
    inFlight.current.add(requestKey);
    const sequence = (requests.current[name] ?? 0) + 1;
    requests.current[name] = sequence;
    setPages((previous) => ({ ...previous, [name]: { state: "loading", error: null, page: previous[name]?.page ?? null } }));
    try {
      const value = await collectionApi.getCollectionRecords(workspace.session_id, name, tool.batch_id, page);
      if (!alive.current || identityRef.current !== identity || requests.current[name] !== sequence
        || current.current?.tools.find((item) => item.tool_name === name)?.batch_id !== value.batch_id) return;
      setPages((previous) => ({ ...previous, [name]: { state: "ready", error: null, page: value } }));
    } catch (caught) {
      if (!alive.current || identityRef.current !== identity || requests.current[name] !== sequence) return;
      if (caught instanceof ApiClientError && caught.status === 410) { onExpired(); return; }
      setPages((previous) => ({ ...previous, [name]: { state: "error", error: caught instanceof ApiClientError ? caught.info : FALLBACK, page: previous[name]?.page ?? null } }));
    } finally {
      inFlight.current.delete(requestKey);
    }
  };

  const run = async (kind: "load" | "refresh", tool: CollectionToolView) => {
    if (working.current || (pending.current === null && busy)) return;
    const latest = current.current;
    if (latest === null) return;
    let intent = pending.current;
    if (intent === null) {
      const common = { expected_generation: latest.session_generation, expected_collection_revision: latest.collection_revision };
      if (kind === "load") {
        if (tool.next_upstream_page === null || tool.batch_id === null) return;
        intent = { kind, key: crypto.randomUUID(), handle: null, tool: tool.tool_name,
          command: { ...common, tool_name: tool.tool_name as JudicialToolName, batch_id: tool.batch_id, page_number: tool.next_upstream_page } };
      } else {
        intent = { kind, key: crypto.randomUUID(), handle: null, tool: tool.tool_name,
          command: { ...common, tool_name: tool.tool_name, expected_batch_id: tool.batch_id } };
      }
      pending.current = intent;
    }
    working.current = true; setRunning(true); setUncertain(false); onBusyChange(true); setMessage(copy.working);
    try {
      if (intent.handle === null) {
        intent.handle = intent.kind === "load"
          ? await collectionApi.loadCollectionPage(workspace.session_id, intent.command, intent.key)
          : await collectionApi.refreshCollectionTool(workspace.session_id, intent.command, intent.key);
      }
      while (alive.current && identityRef.current === identity) {
        const result = await collectionApi.getCollectionOperation(workspace.session_id, intent.handle.operation_id);
        if (!alive.current || identityRef.current !== identity) return;
        if (result.state === "queued" || result.state === "running") {
          await new Promise<void>((resolve) => setTimeout(resolve, 2000));
          continue;
        }
        pending.current = null;
        if (result.result !== null) {
          accept(result.result);
          setMessage(copy.done);
          const updated = result.result.tools.find((item) => item.tool_name === intent.tool);
          if (updated !== undefined && updated.batch_id !== null) await read(updated, intent.kind === "refresh" ? 1 : pages[intent.tool]?.page?.page ?? 1);
        } else {
          await reload();
          setMessage(result.error === null ? copy.failure : dictionary.hints[result.error.hint_id].text);
        }
        return;
      }
    } catch (caught) {
      if (!alive.current || identityRef.current !== identity) return;
      if (caught instanceof ApiClientError && caught.status === 410) { pending.current = null; onExpired(); return; }
      if (caught instanceof ApiClientError && caught.status < 500) {
        pending.current = null; await reload();
        setMessage(dictionary.hints[caught.info.hint_id].text);
      } else { setUncertain(true); setMessage(copy.pending); }
    } finally {
      if (alive.current && identityRef.current === identity) {
        working.current = false; setRunning(false); onBusyChange(pending.current !== null);
      }
    }
  };

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; onBusyChange(false); };
  }, [identity]);
  useEffect(() => { void reload(); }, [identity, workspace.payload?.api_status.result_revision, workspace.active_operation?.operation_id]);

  const reportIds = new Set(workspace.payload?.evidence_list.filter((item) => item.source === "tianyan")
    .map((item) => `${item.category}:${item.provider_record_id}`) ?? []);
  return <CollectionRuntime.Provider value={{ reportIds, supplement: onSupplement, renderTool: (tool) => {
    const data = pages[tool.tool_name];
    return <CollectionToolPanel tool={tool} records={data?.page ?? null} readState={data?.state ?? "idle"}
      readError={data?.error ?? null} busy={busy || running || uncertain}
      onReadPage={(page) => { void read(tool, page); }}
      onLoadMore={() => { void run("load", tool); }} onRefresh={() => { void run("refresh", tool); }} />;
  } }}>
    {message !== null && <p className="field-note" role="status">{message}</p>}
    {uncertain && <button type="button" className="secondary-button" disabled={running} onClick={() => {
      const intent = pending.current;
      const tool = current.current?.tools.find((item) => item.tool_name === intent?.tool);
      if (intent !== null && tool !== undefined) void run(intent.kind, tool);
    }}>{copy.resume}</button>}
    {view === null && error === null && <p role="status">{copy.loading}</p>}
    <CollectionBrowser overview={view} busy={busy || running} error={error}
      manualEvidence={view === null ? [] : workspace.payload?.evidence_list.filter((item) => item.source !== "tianyan") ?? []}
      onReload={() => { void reload(); }} />
    {view === null && error !== null && <div className="evidence-list">
      {(["basic", "abnormal", "penalty", "judicial", "asset", "other"] as const).map((category) => {
        const items = workspace.payload?.evidence_list.filter((item) => item.category === category) ?? [];
        return items.length === 0 ? null : <details className="collection-category" key={category}>
          <summary>{dictionary.category_labels[category]} · {items.length}</summary>
          {items.map((item) => <EvidenceCard key={item.evidence_id} evidence={item} />)}
        </details>;
      })}
    </div>}
  </CollectionRuntime.Provider>;
}
