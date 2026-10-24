/** COLLECTION-1.0：只展示已收集材料，浏览数据与报告证据包分别标注。 */
import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import dictionary from "../../../contracts/text-dict.json";
import type { CollectionBrowserProps, CollectionToolPanelProps, CollectedRecordCardProps } from "./collection-props.js";
import type { CollectionToolView } from "../contracts/generated.js";
import { EvidenceCard } from "./WorkspacePanels.js";
import { OfficialRecovery } from "./OfficialRecovery.js";

const copy = dictionary.collection_labels;
export const CollectionRuntime = createContext<{
  renderTool(tool: CollectionToolView): ReactNode;
  reportIds: Set<string>;
  supplement(category: import("../contracts/generated.js").Category): void;
} | null>(null);

function displayTime(value: string | null): string {
  return value === null ? dictionary.labels.not_provided : new Date(value).toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai", hour12: false,
  });
}

export function CollectedRecordCard({ record, reportIncluded }: CollectedRecordCardProps) {
  return (
    <details className="evidence-card source-tianyan">
      <summary className="evidence-meta">
        <strong>{copy.record}</strong><span>{dictionary.source_labels.tianyan}</span>
        <span>{displayTime(record.snapshot_time)}</span>
      </summary>
      <p>{record.content}</p>
      <dl className="compact-facts">
        <div><dt>{dictionary.labels.event_time}</dt><dd>{record.event_time ?? copy.unknown}</dd></div>
        <div><dt>{dictionary.labels.source_publisher}</dt><dd>{record.source_publisher ?? copy.unknown}</dd></div>
      </dl>
      {record.source_url?.startsWith("https://") || record.source_url?.startsWith("http://") ?
        <a href={record.source_url} target="_blank" rel="noopener noreferrer">{dictionary.labels.source_url} ↗</a> : null}
      {reportIncluded === true && <small>{copy.in_report}</small>}
      <small>{dictionary.labels.original_not_verified}</small>
    </details>
  );
}

export function CollectionToolPanel({ tool, records, readState, readError, busy, onReadPage, onLoadMore, onRefresh }: CollectionToolPanelProps) {
  const runtime = useContext(CollectionRuntime);
  const unknown = copy.unknown;
  const error = tool.last_error ?? readError;
  return (
    <details className="collection-tool" onToggle={(event) => {
      if (event.currentTarget.open && readState === "idle" && tool.batch_id !== null) onReadPage(1);
    }}>
      <summary>
        <strong>{dictionary.query_diagnostics.tools[tool.tool_name]}</strong>
        <span>{tool.collected_count} / {tool.total_count ?? unknown}</span>
        <span>{tool.state === "partial" ? copy.partial : tool.state === "error" ? dictionary.category_status_labels.error
          : tool.state === "not_requested" ? dictionary.category_status_labels.not_requested : tool.state === "empty" ? dictionary.category_status_labels.empty : copy.complete}</span>
        {error !== null && <span className="status-text status-error">{dictionary.collection.refresh_failed}</span>}
      </summary>
      <div className="collection-tool-body">
        {tool.batch_id !== null && <p className="field-note">
          {tool.obtained_from === "cache" ? dictionary.collection.cache_used : dictionary.collection.collected_at}：{displayTime(tool.first_fetched_at)}
          {tool.last_fetched_at !== tool.first_fetched_at && <> — {displayTime(tool.last_fetched_at)}</>}
          <br />{dictionary.collection.not_live}
        </p>}
        <p className="field-note">{copy.collected} {tool.collected_count} · {copy.report_count} {tool.report_included_count}</p>
        {(tool.collected_count > tool.report_included_count || tool.batch_id !== tool.report_batch_id) && <p className="window-notice">{dictionary.collection.browse_only}</p>}
        {tool.total_changed && <p className="window-notice">{dictionary.collection.total_changed}</p>}
        {readState === "loading" && <p role="status">{copy.loading}</p>}
        {error !== null && <p className="status-text status-error" role="status">
          {tool.diagnostic?.reason_code === "TOOL_ENTITLEMENT_REQUIRED" ? copy.no_entitlement : tool.diagnostic !== null
            ? dictionary.query_diagnostics.reasons[tool.diagnostic.reason_code] : copy.failure}
          <small> {error.code}</small>
        </p>}
        {records?.items.map((record) => <CollectedRecordCard key={record.record_key} record={record}
          reportIncluded={tool.batch_id === tool.report_batch_id && runtime !== null
            ? runtime.reportIds.has(`${record.category}:${record.record_id}`) : false} />)}
        {tool.state === "empty" && <p>{copy.no_records}</p>}
        {tool.state === "not_requested" && <p>{copy.not_requested}</p>}
        {tool.state === "partial" && tool.has_more === null && tool.next_upstream_page === null && <p>{copy.ended_unknown}</p>}
        <div className="collection-actions">
          {records !== null && records.page > 1 && <button type="button" className="secondary-button" disabled={readState === "loading"} onClick={() => onReadPage(records.page - 1)}>{copy.previous}</button>}
          {records?.next_page !== null && records?.next_page !== undefined && <button type="button" className="secondary-button" disabled={readState === "loading"} onClick={() => onReadPage(records.next_page!)}>{dictionary.collection.read_next}</button>}
          {records !== null && <small>{copy.page} {records.page}</small>}
          {tool.next_upstream_page !== null && records !== null && records.next_page === null && <button type="button" className="secondary-button" disabled={busy || readState === "loading"} onClick={onLoadMore}>{dictionary.collection.load_more}</button>}
          <button type="button" className="secondary-button" disabled={busy} onClick={onRefresh}>{tool.diagnostic?.reason_code === "TOOL_ENTITLEMENT_REQUIRED" ? copy.entitlement_retry : dictionary.collection.refresh}</button>
        </div>
        {error !== null && <OfficialRecovery toolName={tool.tool_name} onSupplement={() => runtime?.supplement(tool.category)} />}
      </div>
    </details>
  );
}

export function CollectionBrowser({ overview, busy, error, manualEvidence, onReload }: CollectionBrowserProps) {
  const runtime = useContext(CollectionRuntime);
  return (
    <div className="collection-browser">
      {error !== null && <div className="feedback feedback-warning" role="status">{copy.browser_unavailable}
        <button className="secondary-button" type="button" disabled={busy} onClick={onReload}>{copy.reload}</button>
      </div>}
      {overview !== null && <>
        <p className="field-note">{copy.collected} {overview.tools.reduce((sum, item) => sum + item.collected_count, 0)} · {copy.report_count} {overview.report_evidence_count}</p>
        <p className="field-note">{copy.count_note}</p>
        {(["basic", "abnormal", "penalty", "judicial", "asset"] as const).map((category) => {
          const tools = overview.tools.filter((tool) => tool.category === category);
          return <details className="collection-category" key={category}>
            <summary><strong>{dictionary.category_labels[category]}</strong>
              <span>{tools.reduce((sum, item) => sum + item.collected_count, 0)}</span>
              {tools.some((item) => item.state === "partial") && <span>{copy.partial}</span>}
              {tools.some((item) => item.state === "error" || item.last_error !== null) && <span className="status-text status-error">{dictionary.category_status_labels.error}</span>}
            </summary>
            {tools.map((tool) => <div key={`${tool.tool_name}:${tool.batch_id}`}>{runtime?.renderTool(tool)}</div>)}
          </details>;
        })}
      </>}
      {manualEvidence.length > 0 && <details className="collection-category">
        <summary><strong>{copy.manual}</strong><span>{manualEvidence.length}</span></summary>
        <div className="evidence-list">{manualEvidence.map((evidence) => <EvidenceCard key={evidence.evidence_id} evidence={evidence} />)}</div>
      </details>}
    </div>
  );
}
