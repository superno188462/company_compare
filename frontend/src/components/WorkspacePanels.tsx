import dictionary from "../../../contracts/text-dict.json";
import type {
  CandidateListProps, CoveragePanelProps, EvidenceCardProps, ManualEvidenceFormProps,
  OfficialLinksProps, ReportPanelProps, SearchPanelProps, SubjectHeaderProps,
} from "./props.js";
import type { Category } from "../contracts/generated.js";

const CATEGORY_ORDER: Category[] = ["basic", "abnormal", "penalty", "judicial", "asset"];

function shown(value: string | null): string {
  return value ?? dictionary.labels.not_provided;
}

function safeHttpUrl(value: string | null): string | null {
  if (value === null) return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

export function SearchPanel({ queryText, busy, onQueryChange, onSearch }: SearchPanelProps) {
  return (
    <section className="panel search-panel" aria-labelledby="search-title">
      <div className="section-heading">
        <h2 id="search-title">搜索企业</h2>
        <span className="muted">01 / 确认主体</span>
      </div>
      <label htmlFor="company-name">{dictionary.labels.company_name}</label>
      <form className="search-controls" onSubmit={(event) => { event.preventDefault(); onSearch(); }}>
        <input
          id="company-name"
          type="search"
          value={queryText}
          maxLength={200}
          placeholder="输入企业全称或关键词"
          disabled={busy}
          onChange={(event) => onQueryChange(event.target.value)}
        />
        <button className="primary-button" type="submit" disabled={busy || !queryText.trim()}>
          {busy ? "正在搜索…" : dictionary.actions.search}
        </button>
      </form>
      <p className="field-note">搜索结果只用于列出候选；即使只有一家，也需要你明确确认。</p>
    </section>
  );
}

export function CandidateList({ result, busy, onConfirm }: CandidateListProps) {
  return (
    <section className="panel candidate-panel" aria-labelledby="candidate-title">
      <div className="section-heading">
        <h2 id="candidate-title">{dictionary.labels.search_results}</h2>
        <span className="muted">共 {result.total ?? result.items.length} 条</span>
      </div>
      {result.items.length === 0 ? (
        <p className="empty-line">{dictionary.hints.SEARCH_EMPTY.text}</p>
      ) : (
        <div className="candidate-list">
          {result.items.map((candidate) => (
            <article className="candidate-card" key={candidate.candidate_id}>
              <div>
                <h3>{candidate.name}</h3>
                <dl className="compact-facts">
                  <div><dt>信用代码</dt><dd>{shown(candidate.credit_code)}</dd></div>
                  <div><dt>法定代表人</dt><dd>{shown(candidate.legal_representative)}</dd></div>
                  <div><dt>成立日期</dt><dd>{shown(candidate.established_on)}</dd></div>
                  <div><dt>注册地区</dt><dd>{shown(candidate.registered_region)}</dd></div>
                </dl>
              </div>
              <button
                className="secondary-button"
                type="button"
                disabled={busy || !candidate.selectable}
                onClick={() => onConfirm(candidate.candidate_id)}
              >
                {candidate.selectable ? dictionary.actions.confirm_subject : dictionary.validation.no_candidate_code}
              </button>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

export function SubjectHeader({ subject }: SubjectHeaderProps) {
  if (subject === null) return null;
  return (
    <section className="panel subject-panel" aria-labelledby="subject-title">
      <div className="section-heading">
        <h2 id="subject-title">{dictionary.labels.current_subject}</h2>
        <span className="status-chip">已人工确认</span>
      </div>
      <h3 className="subject-name">{subject.name}</h3>
      <dl className="subject-facts">
        <div><dt>{dictionary.labels.credit_code}</dt><dd>{subject.credit_code}</dd></div>
        <div><dt>{dictionary.labels.registered_region}</dt><dd>{shown(subject.registered_region)}</dd></div>
        <div><dt>{dictionary.labels.legal_representative}</dt><dd>{shown(subject.legal_representative)}</dd></div>
        <div><dt>{dictionary.labels.established_on}</dt><dd>{shown(subject.established_on)}</dd></div>
      </dl>
    </section>
  );
}

export function CoveragePanel({ coverage, busy, onRetry, diagnostics }: CoveragePanelProps) {
  const copy = dictionary.query_diagnostics;
  return (
    <section className="panel coverage-panel" aria-labelledby="coverage-title">
      <div className="section-heading">
        <h2 id="coverage-title">{dictionary.labels.coverage}</h2>
        <span className={`status-chip status-${coverage.tianyan_status}`}>
          {dictionary.tianyan_status_labels[coverage.tianyan_status]}
        </span>
      </div>
      <div className="coverage-list">
        {CATEGORY_ORDER.map((category) => {
          const result = coverage.categories[category];
          const diagnostic = diagnostics?.[category];
          const countUnit = diagnostic?.reason_code === "CONTENT_LIMIT_EXCEEDED"
            ? copy.labels.characters : copy.labels.records;
          return (
            <article className="coverage-row" key={category}>
              <div className="coverage-row-main">
                <div>
                  <strong>{dictionary.category_labels[category]}</strong>
                  <p>{result.scope_description}</p>
                </div>
                <div className="coverage-result">
                  <span className={`status-text status-${result.status}`}>
                    {dictionary.category_status_labels[result.status]}
                  </span>
                  {result.error_code !== null && <small>{result.error_code}</small>}
                  {result.record_count > 0 && <small>{result.record_count} 条</small>}
                  {result.status === "error" && coverage.planned_categories.includes(category) && (
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={busy}
                      aria-label={`${dictionary.actions.retry_category}：${dictionary.category_labels[category]}`}
                      onClick={() => onRetry([category])}
                    >
                      {dictionary.actions.retry_category}
                    </button>
                  )}
                </div>
              </div>
              {result.status === "error" && (
                <details className="query-diagnostic">
                  <summary aria-label={`${copy.show}：${dictionary.category_labels[category]}`}>{copy.show}</summary>
                  <div className="diagnostic-content">
                    {busy && <p className="diagnostic-note">{copy.previous_result}</p>}
                    {diagnostic === undefined ? <p>{copy.legacy}</p> : (
                      <>
                        <p className="diagnostic-reason">{copy.reasons[diagnostic.reason_code]}</p>
                        <dl className="diagnostic-facts">
                          <div><dt>{copy.labels.tool}</dt><dd>
                            {diagnostic.tool_name === null ? copy.not_recorded : (
                              <>{copy.tools[diagnostic.tool_name]}<code>{diagnostic.tool_name}</code></>
                            )}
                          </dd></div>
                          <div><dt>{copy.labels.phase}</dt><dd>{copy.phases[diagnostic.phase]}</dd></div>
                          <div><dt>{copy.labels.http_status}</dt><dd>{diagnostic.http_status ?? copy.not_recorded}</dd></div>
                          <div><dt>{copy.labels.field}</dt><dd>
                            {diagnostic.field === null ? copy.not_recorded : copy.fields[diagnostic.field]}
                          </dd></div>
                          <div><dt>{copy.labels.actual_count}</dt><dd>
                            {diagnostic.actual_count === null ? copy.not_recorded : `${diagnostic.actual_count} ${countUnit}`}
                          </dd></div>
                          <div><dt>{copy.labels.limit_count}</dt><dd>
                            {diagnostic.limit_count === null ? copy.not_recorded : `${diagnostic.limit_count} ${countUnit}`}
                          </dd></div>
                          <div><dt>{copy.labels.queried_at}</dt><dd>
                            {result.queried_at === null ? copy.not_recorded : new Date(result.queried_at).toLocaleString(
                              "zh-CN", { timeZone: "Asia/Shanghai", hour12: false },
                            )}
                          </dd></div>
                          <div><dt>{copy.labels.diagnostic_id}</dt><dd><code>{diagnostic.diagnostic_id}</code></dd></div>
                        </dl>
                        <p className="diagnostic-note">{copy.first_failure}</p>
                      </>
                    )}
                  </div>
                </details>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function EvidenceCard({ evidence }: EvidenceCardProps) {
  const sourceUrl = safeHttpUrl(evidence.source_url);
  return (
    <article className={`evidence-card source-${evidence.source}`}>
      <div className="evidence-meta">
        <span>{dictionary.source_labels[evidence.source]}</span>
        <code>{evidence.evidence_id}</code>
      </div>
      <p>{evidence.content}</p>
      <dl className="compact-facts">
        <div><dt>{dictionary.labels.event_time}</dt><dd>{shown(evidence.event_time)}</dd></div>
        <div><dt>{dictionary.labels.source_publisher}</dt><dd>{shown(evidence.source_publisher)}</dd></div>
      </dl>
      {sourceUrl !== null && (
        <a href={sourceUrl} target="_blank" rel="noopener noreferrer">查看来源定位 ↗</a>
      )}
      <small>{dictionary.labels.original_not_verified}</small>
    </article>
  );
}

export function ReportPanel({ summaryText, status }: ReportPanelProps) {
  return (
    <section className="panel report-panel" aria-labelledby="report-title">
      <div className="section-heading">
        <h2 id="report-title">{dictionary.labels.report}</h2>
        <span className="muted">{dictionary.llm_status_labels[status.llm_status]}</span>
      </div>
      {summaryText ? (
        <div className="report-text">{summaryText}</div>
      ) : (
        <div className="empty-content compact-empty">
          <span className="empty-symbol" aria-hidden="true">⌁</span>
          <h3>{dictionary.labels.no_successful_report}</h3>
          <p>当前材料不足或模型节点尚未成功完成。</p>
        </div>
      )}
    </section>
  );
}

export function ManualEvidenceForm({
  draft, fromSnapshot, snapshotAcknowledged, busy, fieldErrors, onChange, onSaveDraft,
  onSubmit, onClear, onAcknowledge,
}: ManualEvidenceFormProps) {
  return (
    <section className="panel manual-panel" aria-labelledby="manual-title">
      <div className="section-heading">
        <h2 id="manual-title">{dictionary.labels.manual_entry}</h2>
        <span className="muted">{fromSnapshot ? dictionary.labels.snapshot_prefill : dictionary.labels.draft_only}</span>
      </div>
      <div className={`form-grid ${fromSnapshot ? "snapshot-prefill" : ""}`}>
        <label>
          <span>{dictionary.labels.record_credit_code}</span>
          <input
            value={draft.record_credit_code ?? ""}
            maxLength={64}
            onChange={(event) => onChange({ ...draft, record_credit_code: event.target.value || null })}
          />
          {fieldErrors.record_credit_code && <small>{dictionary.validation[fieldErrors.record_credit_code]}</small>}
        </label>
        <label>
          <span>线索类别</span>
          <select
            value={draft.category}
            onChange={(event) => onChange({ ...draft, category: event.target.value as Category | "other" })}
          >
            {([...CATEGORY_ORDER, "other"] as const).map((category) => (
              <option key={category} value={category}>{dictionary.category_labels[category]}</option>
            ))}
          </select>
        </label>
        <label className="full-field">
          <span>{dictionary.labels.content}</span>
          <textarea
            value={draft.content}
            maxLength={4000}
            rows={6}
            onChange={(event) => onChange({ ...draft, content: event.target.value })}
          />
          <small>{draft.content.length} / 4000</small>
          {fieldErrors.content && <small role="alert">{dictionary.validation[fieldErrors.content]}</small>}
        </label>
        <label>
          <span>{dictionary.labels.source_url}</span>
          <input
            type="url"
            value={draft.source_url ?? ""}
            placeholder="https://"
            onChange={(event) => onChange({ ...draft, source_url: event.target.value || null })}
          />
          {fieldErrors.source_url && <small role="alert">{dictionary.validation[fieldErrors.source_url]}</small>}
        </label>
        <label>
          <span>{dictionary.labels.observed_at}</span>
          <input
            type="text"
            value={draft.observed_at ?? ""}
            placeholder="例如 2026-10-23T10:00:00+08:00；未知可留空"
            maxLength={64}
            onChange={(event) => onChange({ ...draft, observed_at: event.target.value || null })}
          />
          {fieldErrors.observed_at && <small role="alert">{dictionary.validation[fieldErrors.observed_at]}</small>}
        </label>
        <label className="full-field">
          <span>{dictionary.labels.event_time_optional}</span>
          <input
            value={draft.event_time ?? ""}
            maxLength={256}
            onChange={(event) => onChange({ ...draft, event_time: event.target.value || null })}
          />
        </label>
      </div>
      {fromSnapshot && (
        <label className="acknowledgement">
          <input type="checkbox" checked={snapshotAcknowledged} disabled={busy}
            onChange={(event) => onAcknowledge(event.target.checked)} />
          <span>{dictionary.labels.snapshot_acknowledgement}</span>
        </label>
      )}
      <div className="form-actions">
        <button className="primary-button" type="button"
          disabled={busy || !draft.content.trim() || (fromSnapshot && !snapshotAcknowledged)}
          onClick={onSubmit}>
          {dictionary.actions.submit_evidence}
        </button>
        <button className="secondary-button" type="button" disabled={busy} onClick={onSaveDraft}>
          {dictionary.actions.save_draft}
        </button>
        <button className="text-button" type="button" disabled={busy} onClick={onClear}>
          清空草稿
        </button>
      </div>
      <p className="field-note">保存草稿后仍可修改；提交后才进入本次会话的证据包。当前不开放共享。</p>
    </section>
  );
}

export function OfficialLinks({ sites, onCopy }: OfficialLinksProps) {
  return (
    <section id="official-sites" className="panel official-panel" aria-labelledby="official-title">
      <div className="section-heading">
        <h2 id="official-title">{dictionary.labels.official_sites}</h2>
        <span className="muted">自行核对原始公示</span>
      </div>
      <p className="field-note">{dictionary.hints.OPEN_OFFICIAL_MANUALLY.text}</p>
      <ul className="official-list">
        {sites.map((site) => (
          <li key={site.url}>
            <a href={site.url} target="_blank" rel="noopener noreferrer">
              <span>{site.label}</span><span aria-hidden="true">↗</span>
            </a>
            <button className="copy-button" type="button" onClick={() => onCopy(site.url)}>
              {dictionary.actions.copy_official_url}
            </button>
            <span className="site-address">{site.url}</span>
          </li>
        ))}
      </ul>
      <p className="field-note">{dictionary.labels.official_copy_fallback}</p>
    </section>
  );
}
