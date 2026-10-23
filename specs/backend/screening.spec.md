# 企业公开线索筛查后端 SDD

## 1. 文档头

| 项目 | 内容 |
| --- | --- |
| 标识 / 文档版本 | SDD-BE-SCREENING / v2.4 |
| 行为契约 | CONTRACT-1.0，SDD与首批测试已确认；逐函数实现中 |
| PRD / UI 基线 | [PRD-1.0](../common/prd.md)、[UI-1.0](../common/ui_notes.md) |
| 共享定义 | [global_schema.md](../common/global_schema.md)、[输入 Schema](../../contracts/input-schema.json)、[输出 Schema](../../contracts/output-schema.json) |
| 责任人 / 评审人 | 项目开发者（用户本人） |
| 日期 / 状态 | 2026-10-24 / 已接通会话、搜索、人工确认、五类查询、失败类别重试、任务轮询、草稿和私人线索接纳；共享与模型待实现 |

| 日期 | 版本 | 变更 | 评审记录 |
| --- | --- | --- | --- |
| 2026-10-22 | v0.1 | 基于已确认需求定义服务能力、状态、模型、错误与验收 | AI 自查不等于开发者批准；本版待评审 |
| 2026-10-22 | v1.0 | 确认 CONTRACT-1.0，进入骨架阶段 | 用户明确回复“好先生成骨架吧” |
| 2026-10-22 | v1.1 | 追加骨架映射与导入/类型检查记录，行为契约不变 | 骨架结构检查通过；骨架本身待用户评审，见 skeleton-review.md |
| 2026-10-23 | v1.2 | 追加首批50个可执行契约用例与实际结果，CONTRACT-1.0不变 | 用户回复“可以继续吧”授权继续准备测试；42通过/8占位失败，测试待评审，见 tests/test-cases.md |
| 2026-10-23 | v1.3 | 首批测试确认后逐函数实现会话create/restore/reset，行为契约不变 | 用户回复“继续，第一步是开发什么？”；50用例中46通过/4占位失败；进程内存切片，完整存储与HTTP待实现 |
| 2026-10-23 | v1.4 | BE-ERR-01增加通用字段校验文案键input_invalid，接通HTTP应用装配及统一错误包 | 用户明确选择“新增通用提示（推荐）”；业务字段/方法签名不变，文案基线TEXT-1.1，测试与实现记录见tests/test-cases.md |
| 2026-10-23 | v1.5 | 核验天眼查当前MCP Shared Core搜索协议并实现CompanyDataPort搜索适配器；CONTRACT-1.0不变 | 用户提供天眼AI页面及MCP API Key继续真实接入；鉴权健康检查与一次最小搜索通过，适配器测试见tests/test-cases.md |
| 2026-10-23 | v1.6 | 实现签名匿名Cookie、会话HTTP边界与ScreeningService.search，将天眼查适配器接入搜索路由；CONTRACT-1.0不变 | 用户回复“继续”；新增会话/搜索契约用例并完成对应垂直切片，执行记录见tests/test-cases.md |
| 2026-10-23 | v1.7 | 实现人工确认候选、主体代次切换、查询任务句柄及confirm HTTP路由；CONTRACT-1.0不变 | 用户再次回复“继续”；新增确认主体契约用例，执行记录见tests/test-cases.md |
| 2026-10-23 | v1.8 | 实现固定五类串行查询编排、分类覆盖聚合、证据规范化、迟到写回保护及任务轮询；CONTRACT-1.0不变 | 用户再次回复“继续”；新增任务状态与查询终态契约用例，执行记录见tests/test-cases.md |
| 2026-10-23 | v1.9 | 实现天眼查五类详情适配、固定子工具计划、完整分页和记录规范化；CONTRACT-1.0不变 | 用户再次回复“继续”；先核验官方目录与当前Key权限，再新增适配器契约用例，执行记录见tests/test-cases.md |
| 2026-10-23 | v2.0 | 实现私有手工草稿保存、清空、问题标记和HTTP边界；CONTRACT-1.0不变 | 详情适配推送后继续后端下一切片；新增草稿服务及HTTP契约用例，执行记录见tests/test-cases.md |
| 2026-10-23 | v2.1 | 准备自行录入线索接纳的30项服务/HTTP契约测试；CONTRACT-1.0不变 | 初始111通过/27占位失败；用户明确选择“确认，按这批测试实现（推荐）”，批准SUBMIT-TEST-1范围 |
| 2026-10-23 | v2.2 | 逐函数实现私人线索原子接纳、幂等、任务终态与HTTP接线；接通页面提交；CONTRACT-1.0不变 | 已确认30项接纳测试全部通过，全量138通过；模型未配置明确报告失败并保留证据；共享发布尚未装配 |
| 2026-10-24 | v2.3 | 准备失败类别重试的17项服务/HTTP测试QUERY-RETRY-TEST-1；沿用BE-IF-03/05/06和DATA-02/05 | 用户明确选择“确认，补齐重试按钮和后端（推荐）”，批准本批17项测试并进入逐函数实现；初次17项占位失败，既有138项测试或Schema不变 |
| 2026-10-24 | v2.4 | 逐函数实现失败类别重试、保留式结果合并、任务释放及HTTP接线；CONTRACT-1.0不变 | 已批准17项重试测试全部通过，全量155通过；隔离合成提供方下浏览器验证按钮、等待/再次失败/成功恢复和草稿保留；未再次调用真实收费接口 |

## 2. 目标与范围

### BE-SCOPE-01

覆盖 REQ-01～14：搜索候选、人工确认主体、受控查询、快照草稿、手工录入、共享撤回、证据分析与完整结果。首版面向浏览器工作台，以 Python 应用服务和同源 HTTP 边界表达能力；FastAPI 作为后续传输适配层候选，前端不得直接调用提供方。

本规格只定义可观察行为，不规定数据库表、调度算法、锁实现、SDK 或 LLM 提示拼装内部逻辑。不提供聊天、官网采集、网页代理或模型工具调用。

## 3. 外部依赖

### BE-DEP-01 依赖能力与失败边界

| 能力 | 期望输入/输出 | 失败与替身 |
| --- | --- | --- |
| 企业搜索端口 | 名称、分页 → 候选、游标；不自动选定 | 超时/鉴权/限额/非法响应有明确错误；契约测试使用假提供方 |
| 企业分类查询端口 | 已确认代码、计划类别 → 完整类别记录与实际子范围 | 不完整分页、主体冲突或字段无法映射不得当 empty |
| 分析端口 | 固定提示词 + 满足 input-schema 的 JSON → 报告字符串 | 不提供工具；超时、输入超限、非法输出分别处理 |
| 会话/共享存储 | 主体隔离、原子接纳、版本、幂等和期限能力 | 会话保存失败不启动分析；共享故障可保留已存会话材料 |
| 时钟/标识/匿名所有者验证 | 服务端时间、不可预测公开 ID、验证过的所有者上下文 | 测试替换时钟与身份，不信任客户端时间/所有者 ID |

提供方原始地址及字段映射属于适配器设计，必须在真实接入前核验。天眼查官方 [tyc-cli](https://github.com/tyc-tech/tyc-cli) 当前说明 MCP 入口为 `https://mcp.tianyancha.com/mcp`，应用使用其无会话 Shared Core `POST /v1/core/tools/call`，搜索工具为 `search_companies`；认证值只放在服务端 `Authorization` 请求头。该搜索返回主体锚定字段，但不返回注册省市，适配器必须将未知地区保留为 null，不能猜测。官方 [catalog.json](https://github.com/tyc-tech/tyc-cli/blob/main/src/catalog.json) 已核验本项目固定子工具计划：basic 使用工商登记、股东；abnormal 使用经营异常；penalty 使用行政处罚；judicial 使用失信、被执行、限高、司法案件、裁判文书、法院公告；asset 使用股权冻结、司法协助、动产抵押、土地抵押。每个明细工具完整分页后才能发布对应类别，任一子工具失败则整类失败。当前Key实测可调用工商登记 L1 工具，其余已探测的 L2 明细工具返回 `insufficient_entitlement`；应用将其映射为 `UPSTREAM_AUTH`，不会把无权限写成无记录。工商登记真实 `sources` 结构已核验，L2成功正文结构目前只由假传输契约覆盖，升级权限后仍需补真实集成验证。已有公开依据的分类能力还包括 [工商基本信息](https://open.tianyancha.com/open/365)、[司法协助](https://open.tianyancha.com/open/756)、[企业年报](https://open.tianyancha.com/open/825)；它们属于另一套 OpenAPI 文档，仅用于能力映射参考，不代表当前 MCP Key 已开通全部工具，也不代表覆盖所有司法或资产线索。

分析方法参照 [skill.md](../analysis/skill.md)，运行时固定提示词为 [llm-system-prompt.txt](../analysis/llm-system-prompt.txt)。Skill 是规则材料，不是具备网络能力的运行时服务。

## 4. 数据模型与 Schema

### BE-DATA-01 权威模型

`Subject / Evidence / QueryCoverage / WorkflowStatus / SnapshotDraft / SubmissionReceipt / WorkflowPayload` 使用共享 Schema，不重复定义字段。业务等值、授权、期限和版本约束使用 DATA-01～06。

### BE-DATA-02 边界命令与返回模型

下表补充 HTTP/服务边界模型；`?` 代表必有字段但值可为 null，写明默认值的请求字段允许省略并采用该值，其余字段必填。未列字段一律拒绝；布尔值必须是真实布尔类型，不接受字符串代替。UUID、时间、代码和 URL 采用共享规则。

| 模型 | 字段与约束 |
| --- | --- |
| `ActorContext` | 仅服务端构建：已验证 `actor_id`；不从 JSON 请求体接收，不发送给 LLM |
| `SearchCommand` | `query: str[1..200]` 去首尾空白；`page_size: int[1..20]=20`；`cursor: str?[1..512]=null` |
| `Candidate` | `candidate_id: UUID`；`name: str[1..200]`；`credit_code: CreditCode?`；`registered_region/legal_representative: str?[1..256]`；`established_on: date?`；`selectable: bool`，由有效代码决定；尚无 confirmed_at |
| `SearchResult` | `search_id: UUID`；`items: Candidate[0..20]`；`next_cursor: str?`；`total: int? >=0`；候选身份与搜索所有者绑定，搜索结果 10 分钟有效 |
| `ConfirmSubjectCommand` | `search_id/candidate_id: UUID`；`expected_generation: int>=0`；`discard_draft: bool`；有未提交内容且未同意丢弃时拒绝切换 |
| `EditableDraft` | `record_credit_code: str?[0..64]`；`content: str[0..4000]`；`source_url: str?[0..2048]`；`observed_at: str?[0..64]`；`event_time: str?[0..256]`；`category: Category或other`；允许待修正草稿，不等于可接纳证据 |
| `ManualDraft` | EditableDraft 全字段；加 `draft_id: UUID`、`from_snapshot_id: UUID?`、`issues: HintCode[]`；来源关联由服务端维护，不能经编辑请求伪造/抹掉 |
| `SubmitEvidenceCommand` | `draft_id: UUID`；`expected_generation: int>=1`；`expected_evidence_version: int>=0`；`snapshot_acknowledged: bool`；`share_consent: bool` |
| `RetryAnalysisCommand` | `expected_generation: int>=1`；`expected_evidence_version: int>=0` |
| `RetryQueryCommand` | `expected_generation: int>=1`；`categories: Category[1..5]`，唯一且属于原计划中 error 的类别 |
| `OperationHandle` | `operation_id/session_id: UUID`；`session_generation: int>=1` |
| `OperationView` | Handle 全字段；`state: queued/running/succeeded/failed`；`phase: query/snapshot/save/share/analyze/assemble/complete`；`result: WorkflowPayload?`；`error: ErrorInfo?`；终态规则见 BE-IF-06 |
| `ShareReceipt` | `receipt_id: UUID`；`subject_credit_code: CreditCode`；`shared_at/expires_at: Timestamp`；`state: active/withdrawn`；仅当前所有者可见 |
| `WorkspaceState` | `session_id: UUID`；`expires_at: Timestamp`；`session_generation: int>=0`；`current_subject: Subject?`；`payload: WorkflowPayload?`；`draft: ManualDraft?`；`active_operation: OperationHandle?`；`share_receipts: ShareReceipt[]`（仅本所有者的尚未到期回执） |
| `WithdrawalResult` | `receipt_id: UUID`；`state` 固定 withdrawn；重复撤回返回相同结果 |
| `FieldIssue` | `field: 请求字段名字符串`；`message_key: text-dict.validation 中已有的键`；不含用户原始值 |
| `ErrorInfo` | `code: 下节错误枚举`；`hint_id: HintCode`；`fields: FieldIssue[]`；`retryable: bool`；不包含正文、密钥、堆栈或提供方原始错误 |
| `ErrorEnvelope` | `error: ErrorInfo`；`operation_id: UUID?` |

可提交正文、名称在去首尾空白后必须非空。草稿中无效代码保留原输入用于修正；转成 Evidence 前必须通过匹配和全部接纳规则。来源时间在转证据时解释为含时区时间，未知转 null；不能自动填成现在。仅来源 URL 的空白输入可规范为 null，不以空字符串代表未知。

## 5. 接口与业务分支

### BE-IF-01 HTTP 能力边界

所有路径前缀 `/api/v1`，JSON UTF-8。身份由受控 Cookie 建立，写操作必须同源；会话 ID 只是定位。含私人数据响应禁用共享缓存。修改操作请求头 `Idempotency-Key` 必须为 UUID，读取和活动通知例外。

| 方法/路径 | 请求 → 返回 | 正常状态与行为 |
| --- | --- | --- |
| POST `/sessions` | 无业务请求体 → WorkspaceState | 201，显式创建会话；首次建立匿名所有者凭据，无主体、无报告 |
| GET `/sessions/{sid}` | 无请求体 → WorkspaceState | 200，恢复当前主体、草稿、结果和本所有者回执；不续期 |
| POST `/sessions/{sid}/activity` | 空对象 → `{expires_at: Timestamp}` | 200，仅明确用户活动通知续期；重复通知不启动任务 |
| DELETE `/sessions/{sid}` | 无请求体 → 无正文 | 204，结束会话并使迟到写回失效；所有者凭据保留供撤回尚有效共享 |
| POST `/sessions/{sid}/search` | SearchCommand → SearchResult | 200，不更换当前主体，不执行详情/分析；搜索失败按错误返回 |
| POST `/sessions/{sid}/confirm` | ConfirmSubjectCommand → OperationHandle | 202，用户选定候选后建立新代次，开始查询串行任务 |
| PUT `/sessions/{sid}/draft` | EditableDraft → ManualDraft | 200，保存待修正草稿，不分析；从快照初始化的草稿保留来源关联 |
| DELETE `/sessions/{sid}/draft` | 无正文 → 无正文 | 204，明确清空内容和快照关联后可自行重录，不默默将原快照升级来源 |
| POST `/sessions/{sid}/evidence` | SubmitEvidenceCommand → OperationHandle | 202，通过归属/确认/共享规则后保存并自动分析 |
| POST `/sessions/{sid}/analysis/retry` | RetryAnalysisCommand → OperationHandle | 202，只分析当前版本，不重复接纳/共享线索；空证据直接返回材料不足终态 |
| POST `/sessions/{sid}/queries/retry` | RetryQueryCommand → OperationHandle | 202，只重试失败类别；数据或覆盖改变时更新输入版本并自动分析 |
| GET `/sessions/{sid}/operations/{opid}` | 无正文 → OperationView | 200，只读进度或终态，不自动续期 |
| POST `/shares/{receipt_id}/withdraw` | 空对象 → WithdrawalResult | 200，验证同一所有者；会话结束不剥夺仍有效回执的撤回权 |

### BE-IF-02 应用服务公共签名

下列为骨架生成的公共边界映射，类型指上表或共享模型；`sid/opid/receipt_id/key` 均为 UUID。同步/异步传输适配不改变返回语义；应用服务签名统一同步返回，长任务返回句柄，不阻塞等待 LLM。

| 服务符号 | 签名（`actor: ActorContext` 为第一参数） | 条款 |
| --- | --- | --- |
| SessionService.create | `(actor) -> WorkspaceState` | IF-01、DATA-05 |
| SessionService.restore | `(actor, sid) -> WorkspaceState` | IF-01、DATA-05 |
| SessionService.activity | `(actor, sid) -> SessionExpiry` | NFR-02 |
| SessionService.reset | `(actor, sid, key) -> None` | DATA-05 |
| ScreeningService.search | `(actor, sid, command: SearchCommand, key) -> SearchResult` | IF-03 |
| ScreeningService.confirm | `(actor, sid, command: ConfirmSubjectCommand, key) -> OperationHandle` | IF-03 |
| ScreeningService.save_draft | `(actor, sid, draft: EditableDraft, key) -> ManualDraft` | IF-04 |
| ScreeningService.clear_draft | `(actor, sid, key) -> None` | IF-04 |
| ScreeningService.submit | `(actor, sid, command: SubmitEvidenceCommand, key) -> OperationHandle` | IF-04 |
| ScreeningService.retry_analysis | `(actor, sid, command: RetryAnalysisCommand, key) -> OperationHandle` | IF-05 |
| ScreeningService.retry_queries | `(actor, sid, command: RetryQueryCommand, key) -> OperationHandle` | IF-03、IF-05 |
| ScreeningService.operation | `(actor, sid, opid) -> OperationView` | IF-06 |
| ShareService.withdraw | `(actor, receipt_id, key) -> WithdrawalResult` | DATA-04、IF-04 |

`SessionExpiry` 仅含必填 `expires_at: Timestamp`。骨架阶段不得为上述服务填业务体。HTTP 错误由统一的 `ApplicationError` 传播，其公共属性为 `info: ErrorInfo`；不把私有数据库操作提升成业务契约。

### BE-IF-07 可替换查询与分析端口

外部适配器不影响业务签名。端口自身的输入输出是确定契约，测试通过下列端口替换真实提供方；存储原子性等实现方案另记，不能通过换存储改变 DATA-04/05 行为。

| 端口方法 | 签名与语义 |
| --- | --- |
| CompanyDataPort.search | `(command: SearchCommand) -> ProviderSearchPage`；只返回规范化候选，不选择主体 |
| CompanyDataPort.fetch_category | `(subject: Subject, category: Category) -> ProviderCategoryBatch`；必须完整取得对应计划子范围，否则抛 ProviderError |
| ReportModelPort.generate | `(input: LlmInput, system_prompt: str) -> str`；输入满足输入 Schema；无工具；超时/上下文拒绝抛 ModelError |

`ProviderCandidate` 仅含 Candidate 的 `name / credit_code / registered_region / legal_representative / established_on` 五字段，类型不变；候选 UUID 和 selectable 由应用建立。`ProviderSearchPage` 含 `items: ProviderCandidate[0..20]`、`next_cursor: str?`、`total: int? >=0`。

`ProviderRecord` 必含 `record_id: str[1..256]`、`content: str[1..4000]`、`record_credit_code: CreditCode?`、`event_time: str?[1..256]`、`source_url: HttpUrl?`、`source_publisher: str?[1..256]`。`ProviderCategoryBatch` 必含 `binding_credit_code: CreditCode`、`category: Category`、`queried_at: Timestamp`、`scope_description: str[1..500]`、`records: ProviderRecord[0..200]`。记录 ID 在同一提供方类别内稳定；适配器不能凭相似名称填绑定代码，必须有可核验的查询绑定映射。正常空批次表示完整成功无记录，不通过异常模拟空结果。

`ProviderError` 公共属性为 `code`（输入 Schema 中分类 error_code 的非空枚举）及 `retryable: bool`；`ModelError.code` 为 MODEL_TIMEOUT / MODEL_CONTEXT_LIMIT / MODEL_AUTH / MODEL_UNAVAILABLE，全部不自动重试。应用将这些端口错误映射成前述工作台状态，不把提供方原始异常暴露给用户或模型。

### BE-IF-03 搜索、确认与查询

候选有效期到达或不属于本次所有者/搜索时拒绝确认；候选缺代码不可确认。确认只能来自明确选择，不存在单候选自动继续路径。`expected_generation` 与当前不一致返回冲突。

确认切换时使旧代次任务结果不可写入新代次。所有查询绑定已选代码；返回记录若明确指向另一代码，整个对应类别失败。无可归属标识的记录仅在提供方明确绑定查询主体且适配器有可验证映射时接纳；不得仅靠相似名称归属。

类别成功需计划内接口和分页全部完整；超过规定预算、返回结构非法、页数/总数不一致均为 error，而不是 empty。首版每类别最多 200 条、总接纳最多 200 条；超出时对应类别报限制错误而非静默选取前几条。旧版该类别证据保留原取得时间，成功重查以新完整集合替换该提供方类别证据，用户证据不删除。新旧相同提供方记录保留稳定定位，不制造重复事件。

只有整体 empty 查询共享快照。已有用户编辑草稿时不覆盖其内容；可用快照提示与当前草稿分开。没有私人内容时预填充快照并维护服务端来源关联。

### BE-IF-04 草稿、接纳与共享

保存草稿与接纳证据不同；提交时重新读取服务端草稿，核对版本、主体、代码及已知正文代码归属。缺代码/不匹配/冲突返回对应错误，草稿保留，不创建任务/证据/共享。

使用他人快照时服务端核对 from_snapshot、当前有效期/撤回状态和知情确认；否则拒绝。共享选择默认关闭；请求共享而字段/时间/主体不合格时，在接纳前拒绝并保留草稿。来源关系和 source 不能由 EditableDraft 指定。

接纳与幂等记录属于同一业务提交；保证同次请求重放不会再次追加。接纳后即使共享或分析失败也不回滚已经明确保存的会话证据。共享故障返回完整结果中的 `last_submission.share_status=error` 和 SHARE_FAILED，不把失败写成已共享。

正常接纳后清空已提交草稿；用户新编辑的下一条草稿不得被上一提交完成的迟到响应清空。撤回即时失效并符合 DATA-04。

### BE-IF-05 分析与报告校验

分析只接收离线校验通过且满足跨字段约束的三字段输入，无证据直接跳过。由服务端加载固定提示词，不接受请求体传入模型工具、system prompt 或自由问题。超限不截断。

成功候选报告须为非空字符串、最多 20000 字符；包含提示词指定的三个独立分段标题且顺序一致，最后一句符合字典免责声明。所有形如 `[E-…]` 的引用都存在于输入证据；每条被逐条复述的输入证据应出现其编号；主体引用使用 `[主体信息]`。不允许 HTML/脚本或工具调用输出。

确定性校验只保证结构、引用存在与明显非法输出；不假称能证明每句语义都被证据支持。编造、事实错置、无依据因果、冒充核验和评分等需通过设计用例及真实模型人工抽查验收，不能仅用关键词过滤证明安全。

有效报告按模型返回字符串原样保存/返回，包括原始空白；校验可以读取文本但不得为凑格式改写原文。不合格标 invalid_output，不发布、不自动重试；用户显式重试可启动新分析。生成失败同理，旧报告按 DATA-03 标版本，不复制到当前版本冒充成功。

### BE-IF-06 任务终态与一致性

任务 queued/running 时返回句柄和 phase，`result=null,error=null`，不返回半段报告。结束后一次返回完整 payload：即使查询部分失败或 LLM 失败，只要能组装真实工作台结果，任务为 succeeded，但业务失败必须保留在 api_status 与提示中。只有会话过期、核心存储故障等无法提供可靠结果时任务 failed，`result=null,error` 非空。

成功终态 result 非空、error 为 null；失败终态反之。同代次状态修订单调递增；所有写回验证 session、generation 和预期版本。会话过期、重置或切换后，后台完成也不能恢复其私有数据或覆盖新工作台。

## 6. 异常与错误契约

### BE-ERR-01

文案扩展基线TEXT-1.1：缺少专用提示的分页、UUID、请求头及其他格式错误使用 `validation.input_invalid`（“输入格式不正确，请核对后重试。”），仍使用 `INPUT_INVALID` 与422，不新增请求/响应字段。已定义的公司名称等专用提示优先保留；字段错误包只给字段定位和文案键，不含原始输入。

| 错误码 | 条件 | HTTP / hint_id | 恢复方式 |
| --- | --- | --- | --- |
| INPUT_INVALID | 名称/正文长度、格式、未来时间等非法 | 422 / LIMIT_EXCEEDED 或相应归属提示，fields 定位字段 | 用户修改，固定校验文案由字典定位 |
| SUBJECT_UNCONFIRMED | 未确认主体就录入或分析 | 409 / CONFIRM_SUBJECT | 先确认候选 |
| CANDIDATE_INVALID | 候选过期、不可选或非本次结果 | 409 / CONFIRM_SUBJECT | 重新搜索并确认 |
| CREDIT_MISSING / CREDIT_MISMATCH / CREDIT_CONFLICT | 归属不成立 | 422 / 同名提示 ID | 保留草稿，不产生分析副作用 |
| SNAPSHOT_CONFIRM_REQUIRED | 缺少他人快照知情确认 | 422 / 同名 ID | 勾选后重新提交 |
| SNAPSHOT_UNAVAILABLE | 快照到期/撤回/越权 | 409 / SNAPSHOT_EXPIRED | 核对后自行重新录入，不伪造新查看时间 |
| SHARE_REQUIREMENTS | 请求共享但字段或有效期限不满足 | 422 / SOURCE_INFO_MISSING | 补全或取消共享；时间错误使用字段校验文案 |
| SESSION_EXPIRED | 自己的会话已结束/到期 | 410 / SESSION_EXPIRED | 显式创建新会话 |
| RESOURCE_NOT_FOUND | 不存在或不属于当前所有者 | 404 / INTERNAL_ERROR | 不暴露其他用户资源是否存在 |
| OPERATION_CONFLICT / IDEMPOTENCY_CONFLICT | 任务/版本冲突，或同键不同请求 | 409 / OPERATION_CONFLICT | 刷新；保留未提交草稿 |
| UPSTREAM_TIMEOUT / UPSTREAM_AUTH / UPSTREAM_LIMIT / UPSTREAM_ERROR / UPSTREAM_INVALID / UPSTREAM_INCOMPLETE / SUBJECT_RESPONSE_MISMATCH | 提供方取得失败 | 搜索为 502/504/503 + SEARCH_FAILED；分类查询写入类别错误，完整任务可正常结束 | 只超时/临时服务错误可重试；鉴权/限额/主体冲突不自动重试 |
| INPUT_TOO_LARGE | 证据条数/输入字节/模型上下文超限 | 提交前 422，接纳后生成阶段写 REPORT_FAILED + LIMIT_EXCEEDED | 不截断；告知实际未生成 |
| STORAGE_UNAVAILABLE | 会话核心保存失败 | 503 / INTERNAL_ERROR | 不声称保存成功、不启动 LLM |
| INTERNAL_ERROR | 未分类内部故障 | 500 / INTERNAL_ERROR | 脱敏，记录诊断 ID，不回显异常 |

报告端口超时和输出不合格作为业务状态写入 payload，不以 HTTP 成功隐去失败。所有错误由应用判定，不让 LLM 生成错误码。消息由 `hint_id`/字段校验键从字典读取，不向前端暴露提供方原始文本。

## 7. 非功能规格

### BE-NFR-01 调用与资源预算

搜索单次总预算 20 秒。每次提供方 HTTP 请求超时 8 秒，瞬时网络故障最多重试 1 次，间隔 0.5 秒；不得超过搜索/类别总预算。每类总预算 20 秒（包括分页和重试），超限视为不完整取得。最多 5 类串行，LLM 总预算 60 秒且自动重试为 0。输入/输出上限遵循 DATA-03 与 Schema。

长任务立即返回句柄；正常本地存储环境的任务接纳接口目标为 1 秒内返回（不含搜索），真实外部服务无可用性承诺。上述预算是应用承诺而非提供方 SLA；集成验证必须测到预算与取消写回行为。

### BE-NFR-02 时间与持久性

所有判断使用服务端 UTC，客户端只负责带时区输入/显示。共享 7 天和会话闲置 24 小时的等号边界、5 分钟物理清理窗口、重置与撤回按 DATA-04/05。进度轮询不续期。活动通知最多每 30 秒一次即可保持编辑活动；主动提交不受此合并间隔影响。

任务和幂等结果需要在当前进程重启后能够识别，不能无提示重新收费调用 LLM；执行状态不能确认的旧任务标 error 并提示用户显式重试，不自动冒充完成或自动重放不确定请求。

### BE-NFR-03 安全与隔离

匿名所有者、Cookie、同源验证与禁止跨会话读取按 DATA-05；正式 HTTPS 不接受非 Secure 凭据。服务端保存密钥，日志仅保留操作/诊断 ID、状态与耗时，不记录提示词中的用户证据正文或任何凭据。没有官网抓取、URL 代理、OCR、DOM 读取、模型联网或任意请求目标能力。

真实运行模式启动时核对非空查询计划、提供方授权配置及模型配置，缺项明确报配置未完成，不能用合成数据代替真实返回。测试替身只能在明确隔离的测试环境使用。首版不自动备份用户正文，避免到期后从未声明的备份复活已删除内容。

## 8. 业务硬规则

### BE-RULE-01

主体未确认不运行详情/报告；代码不匹配仅为草稿；共享预填充未确认不进入分析；整体非 empty 不自动预填充；用户同意和来源字段完整不等于已核验；来源不因确认自动升级；没有证据不生成实质报告。

### BE-RULE-02

不评分、评级、不声称全面检索或核验官方原文。报告字符串不由工作流改写。错误、过期、未查询和成功无记录不互相代替。不得增加自由提问或让 LLM 参与主体选择、缓存准入、权限和错误状态判定。

## 9. 验收与追踪

测试规划及执行结果见 [test-cases.md](../../tests/test-cases.md)。当前138项通过，包含用户确认的30项私人接纳测试；共享、真实模型及存储专项仍待完成，不代表完整系统已通过验收。

| 条款 | 验收条目 / 计划用例 | 验证归属 |
| --- | --- | --- |
| IF-01～03、DATA-01/02 | AC-01～05；TC-01～07、TC-28 | 服务契约、传输与提供方适配器集成 |
| IF-04、DATA-04 | AC-06～11、17；TC-08～17、TC-25 | 服务契约、可替换时钟、权限/存储集成 |
| IF-05、RULE-01/02 | AC-07、12、13；TC-18～22、TC-27 | 输入/输出校验、真实模型人工抽查 |
| IF-06、DATA-03/05 | AC-14、16；TC-23～26、TC-29 | 状态/并发/幂等契约与存储集成 |
| NFR-01～03 | AC-15～17；TC-26、TC-28～32 | 超时、清理、隔离、重启与浏览器专项 |

已核验天眼查 MCP Key 鉴权健康检查、当前搜索工具请求和一次最小真实返回；真实凭据仅保存在被 Git 忽略的本机 `.env`。待核验项仍包括各详情类别的工具/权限映射、模型上下文与接入协议、官网浏览器可用性。搜索适配器尚未接入 `ScreeningService` 与 HTTP 路由，不能据此宣称工作台已可搜索。

本阶段的实际骨架文件、映射与检查结果见 [骨架评审记录](../common/skeleton-review.md)。正式契约测试仍待骨架评审通过后编写。
