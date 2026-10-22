import dictionary from "../../contracts/text-dict.json";

/** React 工程的初始外壳；没有会话、数据查询、模拟报告或业务状态转换。 */
export function App() {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace">跳到工作区</a>
      <header className="app-header">
        <a className="brand" href="#workspace" aria-label={dictionary.app_name}>
          <span className="brand-mark" aria-hidden="true">企</span>
          <span>{dictionary.app_name}</span>
        </a>
        <a className="official-shortcut" href="#official-sites">
          {dictionary.labels.official_sites} <span aria-hidden="true">↗</span>
        </a>
      </header>

      <main id="workspace">
        <section className="introduction" aria-labelledby="page-title">
          <span className="preview-tag">前端骨架预览</span>
          <h1 id="page-title">先确认主体，再看证据。</h1>
          <p>从公开线索出发，核对来源、比较矛盾，了解材料能支持什么结论。</p>
        </section>

        <div className="notice">{dictionary.hints.DISCLOSURE_LIMITED.text}</div>

        <section className="panel search-panel" aria-labelledby="search-title">
          <div className="section-heading">
            <h2 id="search-title">搜索企业</h2>
            <span className="muted">01 / 确认主体</span>
          </div>
          <label htmlFor="company-name">{dictionary.labels.company_name}</label>
          <div className="search-controls">
            <input id="company-name" type="search" placeholder="输入企业全称或关键词"
              disabled aria-describedby="preview-status" />
            <button type="button" disabled>{dictionary.actions.search}</button>
          </div>
          <p id="preview-status" className="field-note">
            React 工程已就绪，搜索与分析尚未接入。当前页面没有企业数据。
          </p>
          <ol className="workflow" aria-label="筛查流程">
            <li><span>1</span>搜索企业</li>
            <li><span>2</span>人工确认主体</li>
            <li><span>3</span>查看证据与分析</li>
            <li><span>4</span>补充线索并刷新</li>
          </ol>
        </section>

        <div className="workspace-grid">
          <section className="panel empty-panel" aria-labelledby="evidence-title">
            <div className="section-heading">
              <h2 id="evidence-title">{dictionary.labels.evidence}</h2>
              <span className="muted">02 / 核对材料</span>
            </div>
            <div className="empty-content">
              <span className="empty-symbol" aria-hidden="true">≡</span>
              <h3>等待确认企业主体</h3>
              <p>确认后，在这里查看资料覆盖、来源和逐条证据。</p>
            </div>
          </section>

          <section className="panel empty-panel" aria-labelledby="report-title">
            <div className="section-heading">
              <h2 id="report-title">{dictionary.labels.report}</h2>
              <span className="muted">03 / 交叉分析</span>
            </div>
            <div className="empty-content">
              <span className="empty-symbol" aria-hidden="true">⌁</span>
              <h3>{dictionary.labels.no_successful_report}</h3>
              <p>取得有效证据后生成，呈现支持材料、矛盾与信息缺口。</p>
            </div>
          </section>
        </div>

        <section id="official-sites" className="panel official-panel" aria-labelledby="official-title">
          <div className="section-heading">
            <h2 id="official-title">{dictionary.labels.official_sites}</h2>
            <span className="muted">自行核对原始公示</span>
          </div>
          <p className="field-note">{dictionary.hints.OPEN_OFFICIAL_MANUALLY.text}</p>
          <ul className="official-list">
            {dictionary.official_sites.map((site) => (
              <li key={site.url}>
                <a href={site.url} target="_blank" rel="noopener noreferrer">
                  <span>{site.label}</span><span aria-hidden="true">↗</span>
                </a>
                <span className="site-address">{site.url}</span>
              </li>
            ))}
          </ul>
          <p className="field-note">{dictionary.labels.official_copy_fallback}</p>
        </section>
      </main>
      <footer className="app-footer">公开材料有边界，分析结论须有出处。</footer>
    </div>
  );
}
