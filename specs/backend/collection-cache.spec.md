# 企业API缓存与线索分页 后端SDD

## 1. 文档头

| 项目 | 内容 |
| --- | --- |
| 标识 / 修订 | SDD-COLLECTION-BE / v1.1（COLLECTION-1.0行为不变，已确认装配补充） |
| 行为基线 / 状态 | COLLECTION-1.0 / SDD、类型、装配及COLLECTION-TEST-1已确认，已实现；专项边界见验收记录 |
| 需求/UI | [方案v0.3](../common/collection-browser.proposal.md)，已确认COLLECTION-UI-1.0；[PRD](../common/prd.md) REQ-04/05及本次增补 |
| 关联契约 | CONTRACT-1.0、DIAG-1.0、QUERY-WINDOW-1.0；[前端SDD](../frontend/collection-browser.spec.md) |
| 共享定义 | 本稿第4节是已确认的行为定义；类型阶段已建立contracts/collection-schema.json并离线生成浏览DTO，旧输入/输出Schema不变；详见COLLECTION-TYPE-1 |
| 责任人 / 评审人 / 日期 | 项目开发者（用户本人）/ 用户本人 / 2026-10-24（Asia/Shanghai） |

| 修订 | 阶段 | 内容 | 评审记录 |
| --- | --- | --- | --- |
| v0.1 | SDD草稿 | 跨用户API缓存、司法分页、独立浏览任务、来源/时间/报告隔离及兼容规则 | 需求/UI已确认；本SDD、类型和测试未获批准，不填实现通过记录 |
| v1.0 | SDD确认 | 锁定COLLECTION-1.0，进入类型/骨架；条款正文不变 | 用户明确选择“确认SDD，进入类型/骨架”；未授权提前填充业务实现 |
| v1.0（评审日志） | 类型/骨架待评审 | 形成[COLLECTION-TYPE-1](../common/collection-type-review.md)，行为基线不变 | 246项原回归、类型、骨架及前端构建通过；不代表新增业务已实现或类型已获批准 |
| v1.1（行为基线不变） | 类型确认及装配补充 | 明确COL-IF-02构造装配，新增167项测试待评审 | 用户依次选择“确认类型和骨架，继续测试”“确认装配补充，继续测试”；详情见COLLECTION-TEST-1，不代表实现已获批准 |
| v1.1（当前实现记录） | 测试确认后实施 | 用户选择“确认测试，开始实现”；夹具纠错另获确认，行为条款不变 | 413项通过；类型/构建/结构通过；实际交互和外部能力范围见[专项验收](../common/collection-browser-acceptance.md) |

本稿经确认后只覆盖明确列出的新增/变更条款。旧实现与旧契约在新功能落地前仍有效，不将当前服务退回骨架。

## 2. 目标与范围

### COL-SCOPE-01 资源与用户流程

人工确认主体后，复用同一信用代码及服务端数据源作用域内已校验的API资料；缺失项按原计划查询。支持司法六个子工具逐页取得、保存和浏览，支持主动更新单个工具。查询失败提供可定位的人工复核动作。

三个资源相互独立：公共API采集批次可长期复用；工作区绑定哪些批次只属于该会话；报告证据包仍是原WorkflowPayload.evidence_list。缓存不是个人历史、用户线索共享库或官方原文库。

### COL-SCOPE-02 不包含

不接入新供应商、不购买会员、不抓取官网、不增加LLM工具调用或全量分批分析；不实现用户手工快照共享发布、个人查询历史、跨进程私有会话恢复或生产高可用。本批增量翻页只开放司法六工具，其他类别仍要求完整取得，不开放任意tool_name或任意参数代理。

## 3. 外部依赖

### COL-DEP-01 能力边界

| 依赖 | 契约能力 | 失败与验证 |
| --- | --- | --- |
| CompanyDataPort / 天眼查Shared Core | 原搜索及fetch_category保留；新增第5节的单工具完整采集和司法单页采集；固定工具映射沿用当前计划 | 单次8秒，瞬时超时/连接/5xx最多重试1次；鉴权/限额/非法内容不自动重试；适配器假HTTP与最小真实连通专项 |
| CollectionStorePort | 持久化已校验规范化材料；原子保存批次/页、选择最近成功批次、同页并发协调 | 不可用报STORAGE_UNAVAILABLE；不得假称已共享保存；重启/并发/故障集成验证 |
| SessionService、可信ActorContext、时钟 | 现有所有权、主体代次、24小时会话与同源要求 | 私有会话规则不因公共缓存改变；确定性时钟及所有权测试 |
| ReportModelPort | 原subject/evidence_list/api_status输入，无新查询能力 | 未配置模型仍保留证据并显示原报告失败状态；本批不接真实模型 |

分析Skill只提供既有报告规则，不是新增运行时接口。官网入口只供用户浏览，不作为服务端数据依赖。

## 4. 数据模型与Schema

### COL-DATA-01 公共约定与作用域

新增模型禁止额外字段；严格整数不接收bool，UUID用标准UUID字符串；时间是带时区RFC3339，服务端记录实际取得时刻，前端转北京时间。未知为null，空集合表示已知无条目，字段缺省仅用于明确规定的兼容项。正文、URL、来源脱敏沿用ProviderRecord/Evidence原约束，不存上游原始响应。

缓存身份包含：provider标识、仅服务端持有的凭据/权益作用域、规范化版本、信用代码、tool_name、固定查询参数以及分页规格。作用域由组合根配置，不接受客户端指定；换凭据/端点/数据规范版本不得复用旧作用域。若服务端得知同一凭据权限边界变化，必须更新作用域；本批不承诺自动感知第三方账号后台变化。作用域及密钥不进响应、日志正文或LLM。

工具集合共14项，类别映射固定：

| category | tool_name |
| --- | --- |
| basic | get_company_registration_info、get_shareholder_info |
| abnormal | get_business_exception |
| penalty | get_administrative_penalty |
| judicial | get_dishonest_info、get_judgment_debtor_info、get_high_consumption_restriction、get_judicial_case、get_judicial_documents、get_court_notice |
| asset | get_equity_freeze、get_judicial_assistance、get_chattel_mortgage_info、get_land_mortgage_info |

### COL-DATA-02 规范化采集结果（服务端）

`ProviderToolSnapshot`：非司法单工具完整结果；字段全必填：binding_credit_code:CreditCode、tool_name:非司法工具枚举、queried_at:Timestamp、records:ProviderRecord[0..200]。必须是完整结果，未完成分页/超过200条报原提供方错误，不能裁剪后记成功。

`ProviderJudicialPage`：字段全必填：binding_credit_code:CreditCode、tool_name:司法枚举、page_number:int>=1、page_size:literal20、queried_at:Timestamp、records:ProviderRecord[0..20]、total_count:int>=0|null、has_more:bool|null。page_number必须与请求匹配；未知总数不能填0；截断信号不证明完整，不能强填has_more=false。已知total=0却有记录、页元数据与请求不符或has_more声明与可核对的总数/页范围矛盾时拒绝该页，不修造计数。

公开浏览材料`CollectedRecord`沿用ProviderRecord全部字段及约束，另含：record_key:非空<=256字符的稳定应用定位、subject_credit_code:CreditCode、category:Category、tool_name:上述枚举、source:literal tianyan、snapshot_time:Timestamp、verification_status:literal original_not_verified。record_key只标识材料，不是报告引用ID；正文不带用户或会话信息。无需编造标题，前端使用固定“线索记录”。

### COL-DATA-03 工具视图与概览（只给当前工作台）

`CollectionToolView`全部字段必填，nullable字段必须显式null：

| 字段 | 类型与约束 | 语义 |
| --- | --- | --- |
| tool_name / category | 固定映射枚举 | 不从content或record_id猜测工具 |
| batch_id | UUID或null | 当前工作台绑定的成功批次；尚无成功结果为null |
| batch_revision | int>=1或null | 已接纳页面变化时递增；无批次为null |
| state | complete / empty / partial / error / not_requested | 成功材料覆盖状态；保留旧成功资料时不被新失败改为empty/error |
| collected_count | int>=0 | 该批次已取得的去重材料数，不限于200 |
| total_count | int>=0或null | 此批次最近一次有效页的上游声明总数，不等于独立事件数 |
| has_more | bool或null | 上游是否还有页；未知不等于没有 |
| next_upstream_page | int>=2或null | 司法已成功连续取得页之后的下一页；非司法/无成功首页/可证完整/未知总数且已遇空页时null；null本身不证明完整 |
| first_fetched_at / last_fetched_at | Timestamp或null | 页实际取得时间的最早/最晚值；无成功结果为null |
| obtained_from | cache / live / none | 工作台最近一次绑定此批次的取得方式；不是原始官方来源 |
| report_batch_id | UUID或null | 当前报告证据包使用的批次，允许与浏览批次不同 |
| report_included_count | int 0..200 | 当前报告证据包实际纳入本工具的数量 |
| last_error | ErrorInfo或null | 本会话此工具最近一次采集失败；不写公共缓存 |
| diagnostic | QueryDiagnostic或null | 同一失败的安全诊断；不写公共缓存或LLM |
| total_changed | bool | 后续页声明总数与该批次先前有效页不同；未知到已知不算变化 |

状态一致性：无批次时count=0、时间/total/has_more/revision均null，state只能error或not_requested；empty要求有效成功批次、count=0、total=0且has_more=false。complete需可证完整且count>0；只取得部分或无法证明完整均partial。成功部分结果后追加页失败：保留partial及旧页，last_error非空。不同工具的total不得相加宣称独立事件总数。

`CollectionOverview`：session_id:UUID、session_generation:int>=1、subject_credit_code:CreditCode、collection_revision:int>=1、tools:CollectionToolView[恰好14项且唯一]、report_evidence_version:int>=0|null、report_evidence_count:int 0..200。最后两项来自当前payload，无payload为null/0。司法记录增加不增加报告版本。collection_revision是工作台浏览视图的单调版本；绑定、追加或观察到同批次已提交新页时递增，重复读取不变。GET不得偷偷绑定其他人的新批次。

`CollectionRecordsPage`：session_id、session_generation、subject_credit_code、tool_name、batch_id、batch_revision、collection_revision（类型同上）；page:int>=1、page_size:literal20、items:CollectedRecord[0..20]、next_page:int>=2|null。这里page是本地已存材料的展示页，与上游page_number不是同一字段。只读本地已有材料，不触发上游取数；超过已存页数返回200空items/next_page=null。空批次第1页也如此。

### COL-DATA-04 写命令与任务

`LoadCollectionPageCommand`：expected_generation:int>=1、expected_collection_revision:int>=1、tool_name:司法六项枚举、batch_id:UUID、page_number:int>=2；全必填。只允许服务端视图指出的下一页或已经保存的页重放，不允许跳页。

`RefreshCollectionToolCommand`：expected_generation、expected_collection_revision同上，tool_name:14项枚举、expected_batch_id:UUID|null；全必填。已知失败且无批次时null。只更新一个工具，非司法按原完整性边界，司法仅新批次首页20条。

复用原`OperationHandle`三个UUID/代次字段。新增`CollectionOperationView`：原句柄字段 + kind:load_page/refresh_tool、state:queued/running/succeeded/failed、result:CollectionOverview|null、error:ErrorInfo|null。终态成功必须result非空/error为空；失败error非空/result为空；非终态两者为空。任务详情仅属于发起会话，公共页可被其他合法会话读取不代表可读取他人任务。

固定文案拟在类型阶段加入text-dict.collection分组，不新增企业风险等级：cache_used=“使用已保存的API资料”；collected_at=“资料取得时间”；not_live=“资料按标注时间取得，可主动更新”；load_more=“继续查询下一页20条”；read_next=“查看已收集下一页”；refresh=“更新本项资料”；browse_only=“新增浏览材料未纳入当前报告证据包”；refresh_failed=“更新失败，保留上次资料”；total_changed=“上游声明总数发生变化，跨页结果不代表同一时刻快照”。未知计数、错误和官方复核沿用既有字典。

## 5. 接口定义与可观察行为

### COL-IF-01 HTTP接口

所有路径在`/api/v1`下，要求可信所有者Cookie、有效会话、已经人工确认的主体；写操作要求同源及UUID格式Idempotency-Key。不接收任意信用代码绕过主体确认。GET不续期，明确用户写操作按原规则续期。

| HTTP | 路径 | 输入 / 输出 | 副作用 |
| --- | --- | --- | --- |
| GET | /sessions/{sid}/collections | CollectionOverview / 200 | 读取固定批次及已提交页的概览，不取上游、不生成报告 |
| GET | /sessions/{sid}/collections/{tool_name}/records | batch_id:UUID、page:int>=1默认1 / CollectionRecordsPage 200 | 每页固定20；必须是该工作台当前绑定批次，只读本地 |
| POST | /sessions/{sid}/collections/pages | LoadCollectionPageCommand / OperationHandle 202 | 缺页时取所选司法工具下一页，否则本地复用；只影响浏览 |
| POST | /sessions/{sid}/collections/refresh | RefreshCollectionToolCommand / OperationHandle 202 | 绕过缓存取得所选工具新批次；只影响浏览 |
| GET | /sessions/{sid}/collection-operations/{opid} | CollectionOperationView / 200 | 轮询不续期，任务终态独立于原报告任务 |

模型/接口均由下一阶段生成骨架，本阶段不新增路由函数体。

### COL-IF-02 公共应用能力与依赖签名

装配补充COLLECTION-WIRING-1已获用户单独确认：`SqliteCollectionStore(database_path: Path, *, clock: Callable[[], datetime] = utc_now)`实现下述六个存储方法；`CollectionService(*, session_service: SessionService, company_data: CompanyDataPort | None, store: CollectionStorePort, scope_id: str, clock: Callable[[], datetime] = utc_now, task_submitter: Callable[[Callable[[], None]], None] | None = None)`由组合根装配。`ScreeningService.__init__`及`create_app`均增加可选关键字`collection_service: CollectionService | None = None`，旧调用不变；本阶段只增签名。完整确认稿见[装配补充](../common/collection-test-wiring.proposal.md)，默认时钟`utc_now() -> datetime`同为占位，测试可注入外部时钟。其余公共方法签名、字段及行为不变。

计划新增`CollectionService`（src/company_screening/collections.py），同步方法：

```python
overview(self, actor: ActorContext, sid: UUID) -> CollectionOverview
records(self, actor: ActorContext, sid: UUID, tool_name: CollectionToolName,
        batch_id: UUID, *, page: int = 1) -> CollectionRecordsPage
load_page(self, actor: ActorContext, sid: UUID,
          command: LoadCollectionPageCommand, key: UUID) -> OperationHandle
refresh_tool(self, actor: ActorContext, sid: UUID,
             command: RefreshCollectionToolCommand, key: UUID) -> OperationHandle
operation(self, actor: ActorContext, sid: UUID, opid: UUID) -> CollectionOperationView
```

`CompanyDataPort`保留原方法，新增同步：`fetch_tool_snapshot(self, subject: Subject, tool_name: SnapshotToolName) -> ProviderToolSnapshot`及`fetch_judicial_page(self, subject: Subject, tool_name: JudicialToolName, *, page_number: int, page_size: Literal[20] = 20) -> ProviderJudicialPage`。不得把缓存键、当前用户或报告规则放进提供方请求。

持久化端口在`ports.py`新增：`latest(key: CollectionCacheKey) -> StoredCollectionBatch | None`、`get_batch(key: CollectionCacheKey, batch_id: UUID) -> StoredCollectionBatch | None`、`get_page(key: CollectionCacheKey, batch_id: UUID, page_number: int) -> StoredCollectionPage | None`、`commit(batch: StoredCollectionBatch, page: StoredCollectionPage, *, claim_id: UUID, expected_revision: int | None) -> StoredCollectionBatch`、`claim(request: CollectionFetchKey) -> CollectionFetchClaim`、`finish(claim_id: UUID) -> None`。以下字段仅服务端：

- CollectionCacheKey：第4.1节各身份维度，分页规格司法固定20、非司法完整采集；固定参数用规范化JSON字符串，不接受客户端传入。
- StoredCollectionBatch：key、batch_id、revision、first/last_fetched_at、total_count、has_more、total_changed、collected_count；StoredCollectionPage：batch_id、page_number、queried_at、规范化ProviderRecord列表。非司法完整结果作为一次成功快照提交，其本地浏览分页不是上游分页。
- CollectionFetchKey：key、batch_id或null、目标page_number、模式initial/load_page/refresh_tool；刷新键含服务端产生的采集轮次UUID，旧幂等请求重放原轮次，不用永久键阻止未来更新。
- CollectionFetchClaim：claim_id:UUID、state:acquired/pending、lease_until:Timestamp。租约60秒，续占/失败恢复与原子提交规则见NFR；pending调用方不能发相同上游请求。

存储端口失败抛不含原文的StorageError，由应用映射STORAGE_UNAVAILABLE。commit必须验证claim仍有效且绑定本次key/批次/页，再比较修订号；新批次expected_revision=null，追加已有批次为其预期修订。冲突抛CollectionConflictError，应用可读取同页已提交结果完成复用，否则映射OPERATION_CONFLICT；所有失败原子拒绝且不部分插入。claim/finish只协调服务端取数，不给用户使用。这些签名与模型随骨架阶段逐项评审，不在此规定表结构或锁算法。

### COL-IF-03 首查、缓存及报告窗口

1. 原confirm人工确认主体后才使用缓存；按固定计划逐工具选择同作用域最近成功批次，按批次首个有效响应取得时间倒序，同时间按batch_id字符串倒序稳定选取，追加旧批次页面不改变默认批次排序。缓存无TTL，不因年龄自动更新。无缓存才查询计划项，成功空结果也可复用。成功资料不包含他人诊断、会话或草稿。
2. 非司法工具只缓存其完整结果；某子工具失败不删除其他工具缓存，但该类别进入报告仍遵守原“全部计划子项完整”规则。司法成功首页逐工具保存，单项失败继续其他项。零报告容量保持原规则，不自动发起司法首查，已有缓存仍可浏览。
3. 有司法报告容量时，上游/缓存页统一20条，报告按原固定工具顺序纳入最多min(20,剩余容量)条完整记录，首轮仍最多120条；未纳入部分显式列为浏览材料。此处是预先声明的报告范围投影，不裁剪任何记录正文，也不对超限的已组装LLM输入静默截断。与旧窗口按剩余容量缩小上游pageSize的行为差异见迁移表。
4. 报告CategoryResult/ToolCoverage.accepted_count只数实际进入evidence_list的记录；浏览collected_count另算。即使缓存已保存多页，首轮报告也只取各工具首页范围。少于可用记录时has_more=true且partial；未知总数仍partial。首查从缓存纳入的Evidence.snapshot_time为各页原queried_at，captured_at是当前会话接纳时间；类别queried_at取该类别报告所使用的成功工具响应（含空响应）的最早实际取得时间，完全失败时为本次尝试时间。混合时间以逐条时间为准，不能伪造今日查询。
5. 原200条、4000字符/条和256 KiB分析输入预算不变。非司法整类纳入会超过200时沿用原容量失败/保留旧材料语义，已成功缓存仍可浏览；原诊断明确应用上限，不能说是提供方权限不足。无证据不调用模型。
6. 缓存总数、未覆盖范围与原分类状态一致向模型传达，但CollectionOverview、批次密钥、浏览任务、诊断不进模型。缓存命中或单纯浏览变化不修改报告原文。

### COL-IF-04 加载下一页

验证会话、代次、浏览修订、工具/主体/批次及连续页。只加载所选工具；先读同批次已提交页，存在则复用。另一用户已提交同页时不重取；若正取则等待公共页完成，不能访问其私有任务。单页先整体校验归属、长度、记录ID及页元数据，再原子保存并绑定到当前视图。

页内重复按原DUPLICATE_RECORDS拒绝；跨页同record_id且规范化内容完全相同不重复插入，仍记录该页取得时间和分页进度；同ID不同内容视为上游变化，拒绝该页并提示重新更新，不能覆盖旧记录。total变化时可保留有效页但置total_changed=true，不能声明同一时刻完整快照；total小于已保存去重数或空页却声明尚有数据时拒绝该页。未知总数但非空页允许继续，未知总数的空页不能直接证明整体无记录，只结束当前可取得范围并保留partial/未知提示，不无限自动翻页。

只增浏览版本/批次修订，不改变原payload的evidence_list、api_status.categories、evidence_version、summary_text或手工草稿，不调用LLM。失败留住已接纳页并记录当前会话last_error。上游页数/计数不承诺等于独立案件数。

### COL-IF-05 主动更新与原重查

refresh_tool仅针对所选工具绕过缓存，司法取首页20条，非司法按完整结果规则。首个成功响应（含可证空）原子建立新批次并成为后续新工作台默认；失败不改变当前成功批次、时间及公共默认。新旧批次页面不拼接，旧批次继续长期保存供已绑定会话使用。

本次浏览更新不自动改报告证据包；report_batch_id可与batch_id不同，页面必须说明。原类别retry-queries仍可在error/partial时使用，重取原首轮范围并更新报告证据，不使用缓存伪装重查；不自动重取浏览过程中新增的所有页。成功清除该操作范围的旧诊断，失败沿用旧材料规则。

### COL-IF-06 幂等、并发、失效

写操作同所有者/会话/操作类型下同键同体重放同句柄，同键异体409。重放已登记任务先于浏览修订冲突判断，不因首次成功使重放变409。不同会话同批次同页缺失合并为一次本应用采集；首查同缓存键缺失也合并。独立主动更新是用户明确的新轮次，可以各取新批次，不承诺合并两次独立更新。

同一会话所有报告任务和浏览写任务共享互斥边界，冲突409；草稿编辑/保存遵守原规则，不被任务结果覆盖。其他用户提交同批次新页可在后续读取中被观察；其他用户新批次不自动替换当前绑定。会话结束/切换后迟到结果不得写回或恢复会话；已安全取得的公共API页可留存给后续合法会话，但不保存失效会话的任务/身份。

## 6. 异常/错误契约

### COL-ERR-01 沿用ErrorEnvelope

| 触发 | HTTP / code / hint_id | 恢复与保留 |
| --- | --- | --- |
| 非法UUID/页/工具/额外字段 | 422 INPUT_INVALID / 既有格式提示 | 不查询上游；同类别下未知工具不自动映射 |
| 未人工确认主体 | 409 SUBJECT_UNCONFIRMED / CONFIRM_SUBJECT | 先确认；不直接按body代码查库 |
| 他人会话/批次不属于当前绑定/未知任务 | 404 RESOURCE_NOT_FOUND / 原映射 | 不泄露资源存在性，不接受直接猜批次访问 |
| 结束/闲置24小时 | 410 SESSION_EXPIRED / SESSION_EXPIRED | 重新创建会话；公共缓存保留 |
| 修订/代次/下一页冲突、任务互斥 | 409 OPERATION_CONFLICT / OPERATION_CONFLICT | 刷新概览；草稿和已保存页保留 |
| 同键异体 | 409 IDEMPOTENCY_CONFLICT / 原映射 | 新意图使用新键 |
| 持久化读写/协调不可用 | 503 STORAGE_UNAVAILABLE / INTERNAL_ERROR | 失败但不删除原页；不得降级为“无缓存/无记录”再重复计费查询 |
| 任务内上游超时/限额/鉴权/非法返回 | 任务state=failed，ErrorInfo沿用UPSTREAM_*，轮询HTTP200 | 由last_error/diagnostic展示确定原因；原材料不变 |
| 未分类异常 | 500 INTERNAL_ERROR | 脱敏；不泄露业务响应、堆栈或密钥 |

只有确定的TOOL_ENTITLEMENT_REQUIRED才说明无权益；401/403未知原因不猜会员或额度。明细接口失败不因能力目录声称无记录而改empty。

## 7. 非功能规格

| 条款 | 可验证要求 | 验证归属 |
| --- | --- | --- |
| COL-NFR-01 持久化 | 已提交页、规范化版本/作用域和原取得时间在服务重启后可读取；API批次无自动过期、无按时间清理；新报告仍需新会话人工确认 | 临时数据库跨实例/重启集成；超过7天/多年时钟测试 |
| COL-NFR-02 隔离 | 公共存储只含规范化API材料及采集元信息，不存个人线索、Cookie、Actor、原始报错、诊断或报告；结束私有会话不删除公共批次 | 存储内容审计及所有权测试 |
| COL-NFR-03 有界请求 | 浏览每页20，新增司法单次取一页；不自动查完全部页，不一次返回整库正文；单页规范化正文仍各<=4000字符 | HTTP/适配器/大材料专项；不承诺全量数据大小无物理上限 |
| COL-NFR-04 原子/协调 | 提交页与更新批次修订是原子效果；同页失效claim租约60秒后允许恢复，租约内只一个持有者请求；旧持有者迟到提交不得覆盖新claim结果 | 并发、崩溃后接管、写失败故障测试 |
| COL-NFR-05 任务期限 | 浏览任务最长60秒，超时终止并保留旧页；单次提供方8秒、至多1次瞬时重试；公共pending超时不重开并行查询 | 假时钟/延迟依赖测试；网络断开不承诺外部绝对只计次一次 |
| COL-NFR-06 部署边界 | 本批持久化仅承诺单台单服务实例重启保留；不承诺多机共享、私有会话/任务跨重启恢复或磁盘故障备份。容量不足明确STORAGE_UNAVAILABLE，不自动删长期缓存腾空间 | 启动/磁盘故障集成；当前内存会话依旧会丢 |
| COL-NFR-07 安全 | 固定官方链接、无网页抓取/代理；服务端凭据，不允许任意tool代理；所有写操作同源检查 | HTTP安全回归及浏览器人工专项 |

第5节60秒租约是取数协调期限，绝不是API缓存有效期。任务超时后的安全公共采集可提交，只有持有有效claim且未被新提交取代时允许；私有任务/会话仍不能复活。

## 8. 业务硬规则与兼容

### COL-RULE-01

主体代码是复用前提；不同批次不拼成同一快照；读缓存不改取得时间；无记录/失败/未查询分开；来源不升级为官方原文；不因数量打分；不从材料中的指令改变工具、缓存键或分析规则。

### COL-COMPAT-01 受影响消费者与迁移

| 原行为 | 本批变更 / 保留 |
| --- | --- |
| 前端全展开evidence_list | 使用独立collections读接口展示全部已收集API材料；用户线索仍从当前payload读取；旧服务未提供新接口时退回原证据视图并明确无法浏览更多 |
| 司法上游pageSize随报告剩余容量缩小 | 新采集固定20以保证后续分页连续；报告可按已声明窗口纳入少于20条，并显式展示浏览/报告数量。原fetch_category签名与独立适配器行为保留，新流程消费新增端口 |
| 查询结果只保存在内存 | 新API批次持久化；旧内存结果不伪造历史批次导入，新功能起取得的合法API材料才入新库 |
| 200条是全部可见材料上限 | 仍是报告证据包上限；浏览分页可超过200；浏览新增不自动进LLM |
| 原WorkflowPayload五个顶层字段与LLM输入 | 保留，不追加collections正文到payload或模型；新浏览响应Schema独立 |
| 原query_diagnostics只记当前类别首次失败 | 原报告诊断保持；新单工具浏览失败仅在当前工作台CollectionToolView，不能公共传播或混成报告生成时的失败 |

计划改动：新增采集共享Schema及生成投影、端口、服务/适配器、持久化装配、路由、字典；现有查询编排接入缓存。原测试断言不提前改，类型/测试评审时列明首查pageSize等差异和必要替身适配。SDD获批后才生成类型，不边实现边补契约。

## 9. 验收标准与追踪

下表为条款追踪；对应167项新增用例已通过。实际文件及专项结果见COLLECTION-TEST-1及专项验收记录。

| 验收 | 条款 | 预期与计划测试归属 |
| --- | --- | --- |
| COL-AC-01 | DATA-01/02、IF-02 | 固定工具映射、字段严格约束、页错配/超长/脱敏/主体错配；adapter+schema契约 |
| COL-AC-02 | IF-03、NFR-01 | A采集B复用；信用代码/作用域/规范版本不同不复用；空结果可缓存；多年仍复用；cache/service集成 |
| COL-AC-03 | DATA-03/04、IF-01/04 | 单工具下一页、已存页只读、连续页校验、未知总数、跨页重复/总数变化、页内原子拒绝；page/service/HTTP契约 |
| COL-AC-04 | IF-05/06、NFR-04/05 | 主动更新新批次、失败不覆盖、第三人选最近成功、已打开工作台保持旧批次、同页合并、租约接管与旧任务失效；并发/故障专项 |
| COL-AC-05 | IF-03/04、RULE-01 | 已收集可超过200；报告仍<=200且全部记录正文完整；未纳入范围可见；加载不改报告/版本/草稿/诊断；LLM隔离 |
| COL-AC-06 | ERR-01、IF-06、NFR-02/07 | 422/404/409/410/503、幂等、所有权、会话24h、原手工快照7天独立、公共数据无私人字段；安全HTTP/存储审计 |
| COL-AC-07 | NFR-01/06、COMPAT-01 | 重启后新会话可复用但旧私有会话不恢复；存储失败不重查或伪装空；旧结果退回、旧246项影响明确；集成/回归 |

SDD、类型/骨架和契约测试已依次确认，当前已实现。真实上游不同司法工具的第二页格式须在适配器专项中核实；未通过的工具不能假装已支持翻页。实际未支持分页时返回UPSTREAM_INCOMPLETE并保留已有材料，不自动改用网页抓取。
