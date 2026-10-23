# 企业公开线索工作台前端 SDD

## 1. 文档头

| 项目 | 内容 |
| --- | --- |
| 标识 / 文档版本 | SDD-FE-WORKSPACE / v1.6 |
| 行为契约 | CONTRACT-1.0，SDD 已确认；骨架尚待评审 |
| 基线 | [PRD-1.0](../common/prd.md)、[UI-1.0](../common/ui_notes.md) |
| 后端/共享定义 | [后端 SDD](../backend/screening.spec.md)、[共享契约](../common/global_schema.md) |
| 责任人 / 评审人 | 项目开发者（用户本人） |
| 日期 / 状态 | 2026-10-24 / SDD 已通过；会话、搜索、确认、轮询、结果展示、失败类别重试、私人草稿及提交接纳已接通 |

| 日期 | 版本 | 内容 | 评审 |
| --- | --- | --- | --- |
| 2026-10-22 | v0.1 | 细化已确认 UI 的组件、状态和 HTTP 能力映射 | 待开发者确认，AI 自查不等于通过 |
| 2026-10-22 | v1.0 | 确认 CONTRACT-1.0，进入骨架阶段 | 用户明确回复“好先生成骨架吧” |
| 2026-10-22 | v1.1 | 追加类型/组件 Props 骨架及严格类型检查记录，行为契约不变 | 骨架待用户评审，见 skeleton-review.md |
| 2026-10-22 | v1.2 | 按用户指定采用 React + TypeScript + Vite，增加可启动的初始外壳；CONTRACT-1.0 不变 | 用户要求“前端请使用reacet，帮我重构一下”；本次不代表业务测试或实现获批 |
| 2026-10-23 | v1.3 | 引用用户确认的TEXT-1.1通用字段错误键input_invalid | 用户明确选择“新增通用提示（推荐）”；ValidationMessageKey继续从字典推导，React构建通过，业务交互尚未接通 |
| 2026-10-23 | v1.4 | 记录已按既有契约接通的 React 主线与浏览器验证；不改变 CONTRACT-1.0 | 用户继续开发；同源会话、搜索、确认、轮询、展示及草稿已接通，接纳/共享/重试仍待后端实现 |
| 2026-10-23 | v1.5 | 接通私人线索提交、字段错误、原幂等键恢复及分析阶段展示；不改变契约 | 用户确认30项接纳测试后逐函数实现；隔离合成提供方下Chrome联调通过，真实模型与共享未开放 |
| 2026-10-24 | v1.6 | 接通既有CoveragePanel.onRetry及retryQueries，失败类别显示“重新查询”；契约与Schema不变 | 用户明确确认QUERY-RETRY-TEST-1并要求补齐按钮；等待时禁用、网络结果不确定时复用原幂等键，保留本地编辑；隔离浏览器联调通过 |

## 2. 目标与范围

### FE-SCOPE-01

覆盖 UI-01～08、REQ-01～14。首版采用 React + TypeScript，使用 Vite 启动和构建，仍为中文浏览器工作台，遵循 UI-1.0 的桌面双列与窄屏单列。框架选型不改变本契约。不定义数据库或后端内部业务计算，不新增聊天页、内嵌官网或自动企业选择。

本规格描述可观察 UI、组件边界和请求映射。Schema、主体归属、共享准入与期限以服务端结果为准，前端只做提前反馈，不替代最终校验。

## 3. 外部依赖

### FE-DEP-01

依赖同源后端 `/api/v1`、浏览器新标签页/剪贴板/键盘能力与 [text-dict.json](../../contracts/text-dict.json)。后端类型以其模型表和 JSON Schema 为权威，前端类型从这些定义映射；不得猜字段、解析任意错误文字或直接持有天眼查/LLM 密钥。

React 负责视图组合；工作台状态仍按 FE-DATA-01 归属，API Client 仍按 FE-IF-01 定义。现有 Props 与组件实现沿用同一类型定义，不复制或改写字段。`App.tsx` 负责编排会话、搜索、人工确认、任务轮询、完整结果替换和草稿修订保护；Vite 只代理同源应用 API，不提供官网抓取代理。

Clipboard 写入只用于用户主动复制官网地址；不读取剪贴板。官网以用户点击的新标签页导航打开，禁止 iframe、抓取代理、网页请求、DOM、截图/OCR 和跨页面内容回传。浏览器弹窗限制时提供可选中文本地址，不能把失败当作官网无信息。

## 4. 模型与状态归属

### FE-DATA-01

`Subject / Evidence / WorkflowPayload / WorkflowStatus / SnapshotDraft / SubmissionReceipt` 引用 JSON Schema；`WorkspaceState / Candidate / SearchResult / EditableDraft / ManualDraft / OperationHandle / OperationView / ErrorInfo / ShareReceipt` 引用后端 BE-DATA-02。时间含时区输入，显示 Asia/Shanghai；未知为“未提供/尚不清楚”，不补造。

前端仅增加展示模型：

| 模型/字段 | 类型与含义 |
| --- | --- |
| `WorkspaceViewModel.server` | `WorkspaceState`，后端确认后的当前状态唯一来源 |
| `queryText` | `string[0..200]`，当前搜索框内容；不等于已确认企业 |
| `searchResult` | `SearchResult或null`，属于当前搜索请求 |
| `localDraft` | `EditableDraft或null`，用户未保存编辑的唯一来源；有编辑时服务端旧草稿不能覆盖 |
| `draftEditRevision` | 非负整数，每次本地修改递增，用于识别旧保存响应 |
| `snapshotAcknowledged / shareConsent` | 布尔，默认 false；均不代表已经提交或官方核验 |
| `activeOperation` | `OperationHandle或null`；只跟踪当前代次任务 |
| `phase` | initial/searching/candidates/querying/insufficient/snapshot_review/generating/ready/error/expired |
| `fieldErrors` | 字段名到字典校验键的映射；不得展示提供方原始错误 |
| `isWaiting` | 布尔，仅控制轮询/等待；关闭不宣称服务端已取消 |

模型生成不允许使用 `any` 隐藏契约不一致。服务器状态不复制进多个 Store；页面本地编辑与已提交草稿通过明确提交边界区分。

### FE-DATA-02 组件 Props

| 组件 | 公共 Props / 事件契约 |
| --- | --- |
| `SearchPanel` | queryText:string、busy:boolean；onQueryChange(value:string):void、onSearch():void |
| `CandidateList` | result:SearchResult、busy:boolean；onConfirm(candidateId:string):void；仅 selectable=true 启用确认 |
| `SubjectHeader` | subject:Subject或null；清晰展示名称/代码及其他已知字段，不由搜索词替换 |
| `CoveragePanel` | coverage:QueryCoverage、busy:boolean；onRetry(categories:Category[]):void，只有 error 类别可重试 |
| `EvidenceCard` | evidence:Evidence；显示来源、日期、缺项、origin/derived 提示；只有存在合法 URL 才显示外链 |
| `ReportPanel` | summaryText:string、status:WorkflowStatus；onRetry():void；旧版/当前版按版本明确标识 |
| `ManualEvidenceForm` | draft:EditableDraft、fromSnapshot:boolean、snapshotAcknowledged:boolean、shareConsent:boolean、busy:boolean、fieldErrors；onChange、onSaveDraft、onSubmit、onClear、onAcknowledge、onShareChange 事件 |
| `OfficialLinks` | sites:text-dict官方入口数组；onCopy(url:string):void，仅用户主动导航/复制 |
| `ShareReceiptList` | receipts:ShareReceipt[]；onWithdraw(receiptId:string):void，仅本所有者回执 |

所有回调只提交对应用户动作，不在组件初始化、默认选项变化或渲染时自动确认企业、勾选同意或运行分析。

## 5. 页面、交互与请求映射

### FE-IF-01 API Client 公共签名

以下均返回 `Promise<...>`；`sid/key/opid/receiptId` 为 UUID 字符串，方法内部不改变契约字段。客户端自动携带同源身份 Cookie，但不读取 HttpOnly 凭据。

| 方法签名 | 后端能力 |
| --- | --- |
| `createSession(key): Promise<WorkspaceState>` | POST sessions |
| `restoreSession(sid): Promise<WorkspaceState>` | GET sessions/{sid} |
| `notifyActivity(sid): Promise<SessionExpiry>` | POST activity，不能由后台轮询触发 |
| `resetSession(sid,key): Promise<void>` | DELETE sessions/{sid} |
| `search(sid,command:SearchCommand,key): Promise<SearchResult>` | POST search |
| `confirmSubject(sid,command:ConfirmSubjectCommand,key): Promise<OperationHandle>` | POST confirm |
| `saveDraft(sid,draft:EditableDraft,key): Promise<ManualDraft>` | PUT draft |
| `clearDraft(sid,key): Promise<void>` | DELETE draft |
| `submitEvidence(sid,command:SubmitEvidenceCommand,key): Promise<OperationHandle>` | POST evidence |
| `retryAnalysis(sid,command:RetryAnalysisCommand,key): Promise<OperationHandle>` | POST analysis/retry |
| `retryQueries(sid,command:RetryQueryCommand,key): Promise<OperationHandle>` | POST queries/retry |
| `getOperation(sid,opid): Promise<OperationView>` | GET operations/{opid} |
| `withdrawShare(receiptId,key): Promise<WithdrawalResult>` | POST shares/{receiptId}/withdraw |

HTTP 非成功转成保留 code/hint_id/fields/retryable 的统一客户端错误，不靠 message 字符串判分支；不得自动重试修改请求并生成新幂等键。传输重发沿用同键；用户明确发起新的重试才生成新键。

### FE-STATE-01 主要状态转换

| 当前状态 / 用户事件 | 可观察结果与请求 |
| --- | --- |
| initial + 搜索合法名称 | 创建/使用有效会话并搜索；有加载反馈；不替换既有已确认主体 |
| searching + 单/多候选返回 | candidates，展示字段和每张卡片确认按钮；不调用 confirm |
| searching + 空结果/错误 | 对应字典提示、保留搜索词；不说明企业不存在 |
| candidates + 点击确认 | 有未提交草稿时先确认清除；同意后发送准确候选标识，进入 querying |
| querying + 有证据 | 跟踪当前任务 phase，结束后一次接收完整结果进入 ready 或业务失败提示 |
| querying + 全空有快照 | snapshot_review，显示待确认内容；不调用模型、不自动提交 |
| querying + 无证据/全失败 | insufficient，展示分类状态、失败重试与自行录入，不渲染“无风险” |
| ready/snapshot_review + 保存草稿 | 保存但不分析；不丢本地编辑，不把归属问题升级为企业风险 |
| ready/snapshot_review + 合法提交 | 保存草稿后按其最新 draft_id 提交；进入 generating，无自由问题输入 |
| generating + 终态 | 原子替换匹配代次/修订的完整 payload，显示保存/共享/生成各自结果 |
| 任意 + 会话到期 | expired，移除私人内容与自动轮询；显式创建新会话才重启 |

`OperationView.state=succeeded` 仅表示任务已组装结果；报告是否成功仍按 payload.api_status.llm_status。失败任务显示脱敏错误，不能把保留旧报告标成当前成功。

### FE-ACTION-01 表单与知情确认

提交前检验正文非空、代码格式和当前主体匹配、时间不在未来、URL 格式。共享关闭时允许来源信息缺项；开启时完整且满足期限才可提交。后端拒绝时保留草稿及选择，不隐式取消用户共享请求后直接提交。

来自快照的表单标注浅色/斜体与文字标签，确认默认 false。修改内容后仍保留快照关联，不能通过改 source 字段消除确认要求；用户明确清空后才转自行录入。知情确认与共享同意独立。

提交处理期间禁用重复提交；允许编辑下一条本地草稿但不能开启第二个修改任务。保存响应只有在对应本地编辑修订仍匹配时更新表单；上一条提交完成不能清空用户后来输入的内容。

### FE-ACTION-02 官网、复制与外链

常驻官方入口只显示固定列表的名称与地址。用户点击时使用隔离 opener 的新标签页导航；不自动传入当前信用代码或把官网查询结果带回。复制动作只写固定地址，失败保留可选中地址。证据来源链接另标“用户提供/第三方定位”，不因官方域名显示核验标章。

### FE-ACTION-03 结果版本与恢复

只接收当前 session_id、session_generation 且 result_revision 不小于已显示修订的结果。旧搜索响应不覆盖新搜索；旧任务不覆盖新主体；同版本分析失败也如实显示本次失败。

刷新使用同一有效所有者/会话恢复服务端状态；不把私人表单写进跨用户共享缓存。用户编辑活动通过限频 activity 通知续期，后台定时轮询、模型运行和自动刷新不续期。停止等待后可通过恢复接口查看实际结果，不声称成本已取消。

## 6. 异常与错误契约

### FE-ERR-01

| 错误/状态 | UI 行为 |
| --- | --- |
| 422 字段或归属错误 | 就近显示字典校验文案/归属提示，保留输入；代码不匹配不分析不共享 |
| SNAPSHOT_CONFIRM_REQUIRED | 聚焦知情确认说明，禁止提交 |
| SNAPSHOT_UNAVAILABLE | 保留草稿，说明快照不可继续接纳；不篡改查看时间 |
| 409 版本/任务/幂等冲突 | 恢复最新状态并保留本地未提交内容，由用户明确重试 |
| 410 会话结束 | 清空私人展示，提示重新开始，不能从客户端旧缓存复活 |
| 404 非本所有者或不存在 | 通用不可用提示，不披露其他用户会话/共享内容 |
| 分类 error/未查询 | 单独显示取得失败/未覆盖；不当作无记录 |
| 保存成功且共享失败 | 展示 SHARE_FAILED，当前证据仍可用于报告 |
| 报告失败/不合格 | 展示对应提示和当前版本重试，旧报告标实际版本 |
| 网络/超时不确定是否成功 | 保留同一幂等键，先恢复原操作状态，不能盲目生成新键重复提交 |

## 7. 非功能规格

### FE-NFR-01 交互反馈与轮询

合法操作后立即显示待处理状态；1 秒内可见 loading，按钮避免重复提交。任务轮询默认 2 秒一次，停止等待、会话过期或终态后停止；网络失败不无限自动启动新任务。后台轮询不调用 activity。

### FE-NFR-02 可访问性与安全渲染

桌面采用 UI-1.0 双列，窄屏单列，主要动作在 360px 宽下不需横向滚动。控件有标签并可键盘操作；错误、来源、未核验及加载均有文字/可感知通知，不单靠颜色。

报告使用安全纯文本或受限 Markdown 渲染，禁用原始 HTML、脚本、自动媒体和任意嵌入。显示字符与原文一致，不改写风险措辞或补免责声明；字典提示在报告外展示。来源链接只在用户点击后导航，采用安全协议和 opener 隔离。

### FE-NFR-03 私人状态与敏感信息

不保存提供方密钥或读取所有者 HttpOnly Cookie。不把表单、报告和会话数据写进共享前端缓存。恢复基于服务端权限；会话到期或重置清空相应私人视图。共享回执只是定位 ID，界面禁用不代替服务端所有权校验。

## 8. 业务硬规则

### FE-RULE-01

不自动确认候选、不默认勾选知情或共享、不因空记录显示“安全”、不把来源颜色做风险灯、不让模型输出驱动权限/来源类别、不读取官网内容。仅服务端已接纳材料展示为证据，草稿与共享预填充值有清楚边界。

### FE-RULE-02

前端不定义后端风险规则、共享准入例外或资本计算，不新增 PRD 外的业务字段。报告原文与全局提示分开，不能用前端追加的句子冒充模型原文。

## 9. 验收与追踪

| 条款 | PRD/UI 与计划用例 | 验证归属 |
| --- | --- | --- |
| IF-01、STATE-01 | AC-01～05、UI-01/02；TC-01～07 | API Client/组件交互契约 |
| ACTION-01、DATA-01/02 | AC-06～11、UI-03～05；TC-08～17 | 表单与服务错误映射 |
| ACTION-02、NFR-02 | AC-15、16；TC-27、30、31 | 真浏览器新标签页/剪贴板/可访问性专项 |
| ACTION-03、ERR-01 | AC-11、14、17、UI-06～08；TC-23～26、29 | 并发、恢复、版本与过期交互 |
| RULE-01/02 | AC-12、13、16；TC-18～22、27 | 报告安全渲染及真实模型人工抽查 |

验收规划见 [test-cases.md](../../tests/test-cases.md)。工程和浏览器检查见 [骨架评审记录](../common/skeleton-review.md)。已用真实Chrome与隔离合成提供方验证搜索、单候选人工确认、主体错配拒绝、修正提交、证据/报告失败展示、刷新恢复和360px无横向溢出；共享/重试及真实模型仍待对应切片验证。
