import { useEffect, useRef, useState } from "react";

import dictionary from "../../contracts/text-dict.json";
import { ApiClientError, screeningApi } from "./api/client.js";
import {
  CandidateList, CoveragePanel, EvidenceCard, ManualEvidenceForm, OfficialLinks,
  ReportPanel, SearchPanel, SubjectHeader,
} from "./components/WorkspacePanels.js";
import type {
  EditableDraft, ManualDraft, OperationHandle, OperationView, SearchResult, SubmitEvidenceCommand,
  UUID, WorkspaceState,
} from "./contracts/boundary.js";
import type { FieldErrors } from "./workspace/state.js";

const SESSION_STORAGE_KEY = "company-screening-session-id";
let workspaceInitialization: Promise<WorkspaceState> | null = null;

type Notice = { tone: "info" | "warning" | "error" | "success"; text: string };

function newKey(): UUID {
  return crypto.randomUUID();
}

function editableDraft(draft: ManualDraft): EditableDraft {
  return {
    record_credit_code: draft.record_credit_code,
    content: draft.content,
    source_url: draft.source_url,
    observed_at: draft.observed_at,
    event_time: draft.event_time,
    category: draft.category,
  };
}

function emptyDraft(creditCode: string): EditableDraft {
  return {
    record_credit_code: creditCode,
    content: "",
    source_url: null,
    observed_at: null,
    event_time: null,
    category: "other",
  };
}

function errorNotice(error: unknown): Notice {
  if (error instanceof ApiClientError) {
    return { tone: "error", text: dictionary.hints[error.info.hint_id].text };
  }
  return { tone: "error", text: dictionary.hints.INTERNAL_ERROR.text };
}

function hasDraftContent(draft: EditableDraft | null): boolean {
  return draft !== null && Boolean(
    draft.content.trim() || draft.source_url || draft.observed_at || draft.event_time,
  );
}

async function initializeWorkspace(): Promise<WorkspaceState> {
  if (workspaceInitialization !== null) return workspaceInitialization;
  workspaceInitialization = (async () => {
    const storedSid = sessionStorage.getItem(SESSION_STORAGE_KEY);
    let server: WorkspaceState;
    if (storedSid !== null) {
      try {
        server = await screeningApi.restoreSession(storedSid);
      } catch (error) {
        if (!(error instanceof ApiClientError) || ![404, 410].includes(error.status)) throw error;
        sessionStorage.removeItem(SESSION_STORAGE_KEY);
        server = await screeningApi.createSession(newKey());
      }
    } else {
      server = await screeningApi.createSession(newKey());
    }
    sessionStorage.setItem(SESSION_STORAGE_KEY, server.session_id);
    return server;
  })();
  return workspaceInitialization;
}

export function App() {
  const draftRevisionRef = useRef(0);
  const pendingSubmissionRef = useRef<{
    command: SubmitEvidenceCommand; key: UUID; revision: number;
  } | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceState | null>(null);
  const [queryText, setQueryText] = useState("");
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null);
  const [localDraft, setLocalDraft] = useState<EditableDraft | null>(null);
  const [activeOperation, setActiveOperation] = useState<OperationHandle | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [actionBusy, setActionBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [snapshotAcknowledged, setSnapshotAcknowledged] = useState(false);
  const [operationPhase, setOperationPhase] = useState<OperationView["phase"]>("query");

  useEffect(() => {
    let cancelled = false;
    void initializeWorkspace()
      .then((server) => {
        if (cancelled) return;
        setWorkspace(server);
        setActiveOperation(server.active_operation);
        if (server.draft !== null) setLocalDraft(editableDraft(server.draft));
        else if (server.current_subject !== null) setLocalDraft(emptyDraft(server.current_subject.credit_code));
      })
      .catch((error: unknown) => {
        if (!cancelled) setNotice(errorNotice(error));
      })
      .finally(() => {
        if (!cancelled) setInitializing(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (workspace === null || activeOperation === null) return;
    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const view = await screeningApi.getOperation(workspace.session_id, activeOperation.operation_id);
        if (cancelled) return;
        if (view.state === "queued" || view.state === "running") {
          setOperationPhase(view.phase);
          setNotice({ tone: "info", text: dictionary.operation_phase_labels[view.phase] });
          timer = window.setTimeout(() => { void poll(); }, 2000);
          return;
        }
        if (view.state === "failed") {
          setActiveOperation(null);
          setNotice(view.error === null
            ? { tone: "error", text: dictionary.hints.INTERNAL_ERROR.text }
            : { tone: "error", text: dictionary.hints[view.error.hint_id].text });
          return;
        }
        const restored = await screeningApi.restoreSession(workspace.session_id);
        if (cancelled) return;
        setWorkspace(restored);
        setActiveOperation(null);
        const result = view.result;
        if (result !== null) {
          const firstHint = result.ui_hint_group.find((hint) => dictionary.hints[hint].severity === "error")
            ?? result.ui_hint_group.find((hint) => dictionary.hints[hint].severity === "warning")
            ?? result.ui_hint_group[0];
          setNotice(firstHint === undefined
            ? { tone: "success", text: "企业资料查询已完成。" }
            : {
              tone: dictionary.hints[firstHint].severity === "error" ? "error"
                : dictionary.hints[firstHint].severity === "warning" ? "warning" : "info",
              text: dictionary.hints[firstHint].text,
            });
        }
      } catch (error) {
        if (!cancelled) {
          setNotice(errorNotice(error));
          timer = window.setTimeout(() => { void poll(); }, 3000);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeOperation, workspace?.session_id]);

  const handleSearch = async () => {
    if (workspace === null) return;
    const query = queryText.trim();
    if (!query) {
      setNotice({ tone: "warning", text: dictionary.validation.company_name_required });
      return;
    }
    setActionBusy(true);
    setNotice({ tone: "info", text: "正在搜索候选企业…" });
    try {
      const result = await screeningApi.search(
        workspace.session_id,
        { query, page_size: 20, cursor: null },
        newKey(),
      );
      setSearchResult(result);
      setNotice(result.items.length === 0
        ? { tone: "warning", text: dictionary.hints.SEARCH_EMPTY.text }
        : { tone: "info", text: dictionary.hints.CONFIRM_SUBJECT.text });
    } catch (error) {
      setNotice(errorNotice(error));
    } finally {
      setActionBusy(false);
    }
  };

  const handleConfirm = async (candidateId: UUID) => {
    if (workspace === null || searchResult === null) return;
    const candidate = searchResult.items.find((item) => item.candidate_id === candidateId);
    if (candidate === undefined || !candidate.selectable || candidate.credit_code === null) return;
    const mustDiscard = workspace.draft !== null || hasDraftContent(localDraft);
    if (mustDiscard && !window.confirm(dictionary.dialogs.switch_subject_body)) return;

    setActionBusy(true);
    setNotice({ tone: "info", text: "正在确认主体并启动资料查询…" });
    try {
      const handle = await screeningApi.confirmSubject(
        workspace.session_id,
        {
          search_id: searchResult.search_id,
          candidate_id: candidateId,
          expected_generation: workspace.session_generation,
          discard_draft: workspace.draft !== null,
        },
        newKey(),
      );
      const restored = await screeningApi.restoreSession(workspace.session_id);
      setWorkspace(restored);
      setSearchResult(null);
      setActiveOperation(handle);
      setOperationPhase("query");
      pendingSubmissionRef.current = null;
      setSnapshotAcknowledged(false);
      setFieldErrors({});
      draftRevisionRef.current += 1;
      setLocalDraft(emptyDraft(candidate.credit_code));
      setNotice({ tone: "info", text: dictionary.operation_phase_labels.query });
    } catch (error) {
      setNotice(errorNotice(error));
    } finally {
      setActionBusy(false);
    }
  };

  const handleDraftChange = (draft: EditableDraft) => {
    draftRevisionRef.current += 1;
    setFieldErrors({});
    setLocalDraft(draft);
  };

  const handleSubmitEvidence = async () => {
    if (workspace === null || workspace.current_subject === null || workspace.payload === null
      || localDraft === null || actionBusy || activeOperation !== null) return;
    let pending = pendingSubmissionRef.current;
    if (pending === null) {
      const errors: FieldErrors = {};
      if (!localDraft.content.trim()) errors.content = "content_required";
      if (!/^[0-9ABCDEFGHJKLMNPQRTUWXY]{18}$/.test(localDraft.record_credit_code?.trim() ?? "")) {
        errors.record_credit_code = "credit_code_format";
      }
      if (Object.keys(errors).length > 0) {
        setFieldErrors(errors);
        setNotice({ tone: "warning", text: dictionary.validation.input_invalid });
        return;
      }
    }
    setActionBusy(true);
    setFieldErrors({});
    try {
      if (pending === null) {
        const revision = draftRevisionRef.current;
        const saved = await screeningApi.saveDraft(workspace.session_id, localDraft, newKey());
        setWorkspace((current) => current === null ? current : { ...current, draft: saved });
        pending = {
          command: {
            draft_id: saved.draft_id,
            expected_generation: workspace.session_generation,
            expected_evidence_version: workspace.payload.api_status.evidence_version,
            snapshot_acknowledged: snapshotAcknowledged,
            share_consent: false,
          },
          key: newKey(), revision,
        };
        pendingSubmissionRef.current = pending;
      }
      // 网络结果不确定时重用原命令和幂等键，不能重复追加证据。
      const handle = await screeningApi.submitEvidence(workspace.session_id, pending.command, pending.key);
      pendingSubmissionRef.current = null;
      setWorkspace((current) => current === null ? current : { ...current, draft: null, active_operation: handle });
      setActiveOperation(handle);
      setOperationPhase("analyze");
      if (draftRevisionRef.current === pending.revision) {
        setLocalDraft(emptyDraft(workspace.current_subject.credit_code));
        setSnapshotAcknowledged(false);
      }
      setNotice({ tone: "info", text: dictionary.operation_phase_labels.analyze });
    } catch (error) {
      if (error instanceof ApiClientError) {
        setFieldErrors(Object.fromEntries(error.info.fields.map((issue) => [issue.field, issue.message_key])));
        if (error.status < 500) pendingSubmissionRef.current = null;
      }
      setNotice(errorNotice(error));
    } finally {
      setActionBusy(false);
    }
  };

  const handleSaveDraft = async () => {
    if (workspace === null || localDraft === null) return;
    const submittedRevision = draftRevisionRef.current;
    setActionBusy(true);
    try {
      const saved = await screeningApi.saveDraft(workspace.session_id, localDraft, newKey());
      setWorkspace((current) => current === null ? current : { ...current, draft: saved });
      if (draftRevisionRef.current === submittedRevision) setLocalDraft(editableDraft(saved));
      setNotice({ tone: "success", text: dictionary.validation.draft_saved });
    } catch (error) {
      setNotice(errorNotice(error));
    } finally {
      setActionBusy(false);
    }
  };

  const handleClearDraft = async () => {
    if (workspace === null || workspace.current_subject === null) return;
    setActionBusy(true);
    try {
      await screeningApi.clearDraft(workspace.session_id, newKey());
      draftRevisionRef.current += 1;
      setLocalDraft(emptyDraft(workspace.current_subject.credit_code));
      setSnapshotAcknowledged(false);
      setFieldErrors({});
      setWorkspace((current) => current === null ? current : { ...current, draft: null });
      setNotice({ tone: "info", text: "草稿已清空。" });
    } catch (error) {
      setNotice(errorNotice(error));
    } finally {
      setActionBusy(false);
    }
  };

  const handleCopy = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      setNotice({ tone: "success", text: "官网地址已复制。" });
    } catch {
      setNotice({ tone: "warning", text: dictionary.validation.clipboard_failed });
    }
  };

  const payload = workspace?.payload ?? null;
  const currentSubject = workspace?.current_subject ?? null;

  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace">跳到工作区</a>
      <header className="app-header">
        <a className="brand" href="#workspace" aria-label={dictionary.app_name}>
          <span className="brand-mark" aria-hidden="true">企</span>
          <span>{dictionary.app_name}</span>
        </a>
        <div className="header-actions">
          <span className={`connection-dot ${workspace === null ? "offline" : "online"}`} aria-hidden="true" />
          <span>{initializing ? "正在连接" : workspace === null ? "连接失败" : "会话已连接"}</span>
          <a className="official-shortcut" href="#official-sites">{dictionary.labels.official_sites} ↗</a>
        </div>
      </header>

      <main id="workspace">
        <section className="introduction" aria-labelledby="page-title">
          <span className="preview-tag">本地开发版</span>
          <h1 id="page-title">先确认主体，再看证据。</h1>
          <p>从公开线索出发，核对来源、比较矛盾，了解材料能支持什么结论。</p>
        </section>

        <div className="notice">{dictionary.hints.DISCLOSURE_LIMITED.text}</div>
        {notice !== null && <div className={`feedback feedback-${notice.tone}`} role="status">{notice.text}</div>}

        <SearchPanel
          queryText={queryText}
          busy={initializing || actionBusy || workspace === null}
          onQueryChange={setQueryText}
          onSearch={() => { void handleSearch(); }}
        />

        {searchResult !== null && (
          <CandidateList result={searchResult} busy={actionBusy} onConfirm={(id) => { void handleConfirm(id); }} />
        )}

        <SubjectHeader subject={currentSubject} />

        {activeOperation !== null && (
          <section className="operation-banner" aria-live="polite">
            <span className="spinner" aria-hidden="true" />
            <div><strong>{dictionary.labels.processing}</strong><p>{dictionary.operation_phase_labels[operationPhase]}</p></div>
          </section>
        )}

        {payload !== null && (
          <CoveragePanel coverage={payload.api_status} busy={activeOperation !== null} onRetry={() => undefined} />
        )}

        <div className="workspace-grid">
          <section className="panel evidence-panel" aria-labelledby="evidence-title">
            <div className="section-heading">
              <h2 id="evidence-title">{dictionary.labels.evidence}</h2>
              <span className="muted">{payload?.evidence_list.length ?? 0} 条</span>
            </div>
            {payload === null || payload.evidence_list.length === 0 ? (
              <div className="empty-content">
                <span className="empty-symbol" aria-hidden="true">≡</span>
                <h3>{currentSubject === null ? "等待确认企业主体" : "当前没有已接纳证据"}</h3>
                <p>{currentSubject === null ? "确认后查看资料覆盖和逐条证据。" : dictionary.hints.NO_EVIDENCE.text}</p>
              </div>
            ) : (
              <div className="evidence-list">
                {payload.evidence_list.map((item) => <EvidenceCard key={item.evidence_id} evidence={item} />)}
              </div>
            )}
          </section>

          {payload === null ? (
            <section className="panel report-panel" aria-labelledby="report-title">
              <div className="section-heading"><h2 id="report-title">{dictionary.labels.report}</h2><span className="muted">03 / 交叉分析</span></div>
              <div className="empty-content"><span className="empty-symbol" aria-hidden="true">⌁</span><h3>{dictionary.labels.no_successful_report}</h3><p>取得有效证据后生成。</p></div>
            </section>
          ) : (
            <ReportPanel summaryText={payload.summary_text} status={payload.api_status} onRetry={() => undefined} />
          )}
        </div>

        {currentSubject !== null && localDraft !== null && (
          <>
            <ManualEvidenceForm
              draft={localDraft}
              fromSnapshot={workspace?.draft?.from_snapshot_id !== null && workspace?.draft?.from_snapshot_id !== undefined}
              snapshotAcknowledged={snapshotAcknowledged}
              shareConsent={false}
              busy={actionBusy || activeOperation !== null}
              fieldErrors={fieldErrors}
              onChange={handleDraftChange}
              onSaveDraft={() => { void handleSaveDraft(); }}
              onSubmit={() => { void handleSubmitEvidence(); }}
              onClear={() => { void handleClearDraft(); }}
              onAcknowledge={setSnapshotAcknowledged}
              onShareChange={() => undefined}
            />
            {workspace?.draft !== null && workspace?.draft !== undefined && workspace.draft.issues.length > 0 && (
              <div className="draft-issues">
                {workspace.draft.issues.map((hint) => <p key={hint}>{dictionary.hints[hint].text}</p>)}
              </div>
            )}
          </>
        )}

        <OfficialLinks sites={dictionary.official_sites} onCopy={(url) => { void handleCopy(url); }} />
      </main>
      <footer className="app-footer">公开材料有边界，分析结论须有出处。</footer>
    </div>
  );
}
