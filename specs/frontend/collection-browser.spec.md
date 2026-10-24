# 线索折叠、共享缓存与分页浏览 前端SDD

## 1. 文档头

| 项目 | 内容 |
| --- | --- |
| 标识 / 修订 | SDD-COLLECTION-FE / v1.0（行为条款同评审v0.1） |
| 行为基线 / 状态 | COLLECTION-1.0 / SDD、类型、装配及COLLECTION-TEST-1已确认，已实现；专项边界见验收记录 |
| 已批准需求/UI | [方案v0.3](../common/collection-browser.proposal.md)，COLLECTION-UI-1.0；用户明确选择“确认其余交互，进入SDD” |
| 关联规格 | [缓存与分页后端SDD](../backend/collection-cache.spec.md) v1.0（行为同评审v0.1）；原workspace.spec.md、DIAG-1.0、QUERY-WINDOW-1.0 |
| 共享Schema | COL-DATA-01..04已确认；类型阶段新增collection-schema.json及生成投影，原输入/输出Schema不改 |
| 责任人 / 评审人 / 日期 | 项目开发者（用户本人）/ 用户本人 / 2026-10-24（Asia/Shanghai） |

| 修订 | 阶段 | 内容 | 记录 |
| --- | --- | --- | --- |
| v0.1 | SDD草稿 | 现有工作台上增加折叠、存量分页、增量查询、更新和官方复核 | UI已确认，本SDD、类型及测试尚未确认，不表示页面已实现 |
| v1.0 | SDD确认 | 锁定COLLECTION-1.0，进入类型/骨架，条款正文不变 | 用户明确选择“确认SDD，进入类型/骨架”；尚未授权业务实现 |
| v1.0（评审日志） | 类型/骨架待评审 | 客户端/Props/声明组件已列入[COLLECTION-TYPE-1](../common/collection-type-review.md)，行为不变 | React类型/构建通过；尚未渲染或接入新能力 |
| v1.0（评审日志增补） | 类型已确认 | 前端行为不变，后端装配补充不改前端字段 | 用户明确选择“确认类型和骨架，继续测试”；浏览器专项见COLLECTION-TEST-1，页面尚未实现 |
| v1.0（当前实现记录） | 测试确认后实施 | 用户选择“确认测试，开始实现”；夹具纠错另获确认，行为条款不变 | 413项通过；类型/构建/结构通过；实际交互和外部能力范围见[专项验收](../common/collection-browser-acceptance.md) |

## 2. 目标与范围

### COL-FE-SCOPE-01

沿用React工作台、来源颜色、主体确认、报告、手工表单、查询覆盖及诊断区，不增加路由或聊天框。用户能区分：同公司API资料已收集多少、各自何时取得、当前报告证据包包含多少，以及哪些项还需人工复核。

新增“证据与线索”分类折叠与单条折叠。API材料从独立浏览接口读取；当前用户/他人已确认接纳的手工线索仍从原payload读取。没有证据重复展示为两个独立来源。

不实现个人历史、前端公共缓存数据库、自动全量分析、用户任意切换tool参数或嵌入官网。数据库、提供方调用和跨用户复用由后端负责。

## 3. 外部依赖

| 条款 | 依赖 | 失败行为 / 验证 |
| --- | --- | --- |
| COL-FE-DEP-01 | 原共享API Client与第5节新增API；DTO引用后端COL-DATA | 原工作台保留，浏览错误就地显示，不把404/503理解成公司无记录；假HTTP及集成 |
| COL-FE-DEP-02 | text-dict.json固定文案、工具中文名、官方地址 | 不解析上游错误字符串推断会员；字典类型/构建检查 |
| COL-FE-DEP-03 | 浏览器原生折叠、窗口链接和剪贴板 | 键盘可操作；新标签被阻拦可复制官方地址；浏览器专项 |

## 4. 展示模型与状态归属

### COL-FE-DATA-01 共享类型

后端COL-DATA-01..04是CollectionOverview、CollectionToolView、CollectedRecord、CollectionRecordsPage、两种命令与CollectionOperationView的唯一定义。生成TS投影后使用，不在组件中维护冲突副本，不从content或provider_record_id解析工具、金额、案号或企业结论。

API浏览数据仅存在当前页面状态，不写localStorage/IndexedDB。原会话恢复定位沿用现状；公共数据长期保存由后端承担。收到新代次或结束会话后丢弃本页面原主体所有页/展开状态；私人表单遵守原规则。

### COL-FE-DATA-02 组件契约（下一阶段声明签名，无业务实现）

| 组件 / Props | 字段及含义 |
| --- | --- |
| CollectionBrowserProps | overview:CollectionOverview\|null；busy:boolean；error:ErrorInfo\|null；onReload():void；用户线索通过manualEvidence:Evidence[]提供，仅允许user_self/user_other |
| CollectionToolPanelProps | tool:CollectionToolView；records:CollectionRecordsPage\|null；readState:idle/loading/ready/error；readError:ErrorInfo\|null；busy:boolean；onReadPage(page:number):void；onLoadMore():void；onRefresh():void |
| CollectedRecordCardProps | record:CollectedRecord；reportIncluded:boolean\|null；null表示旧结果缺少可核验映射；无未定义回调；reportIncluded按后端报告证据ID映射关系判定，不因内容相似推断 |
| EvidenceCardProps | 保留evidence:Evidence；改为默认折叠，完整正文/来源字段展开后显示 |
| CoveragePanelProps增补 | 原字段保留；onSupplement?(category:Category):void；官方复核地址只来自固定字典，不由记录正文提供 |

reportIncluded映射：原Evidence.provider_record_id与CollectedRecord.record_id同义；只有subject/category/tool批次与原报告绑定一致且记录ID匹配时才为true。若旧数据缺少可核验批次映射则不显示逐条“已纳入”，只显示后端已知的整体数量，不猜测。

### COL-FE-DATA-03 状态与计数

一个浏览概览是状态权威，collection_revision用于拒绝旧响应；每个读取页的键包含session_id、generation、subject_credit_code、tool_name、batch_id、batch_revision、展示page。展开状态仅页面本地维护，不影响报告。后台轮询不得续期会话。

分类头显示各工具已收集材料数之和，注明“材料条目数，同一事件可能有多份材料”；不能称独立案件数或风险数。上游总数只在所属工具头展示，未知用“未提供”，不把未知显示为0。

工具显示原取得时间；多页时间不一则显示最早至最晚取得区间，单条仍显示所属页时间。缓存使用“使用已保存的API资料”，不显示到期倒计时、不称实时或最新。接口返回失败诊断的查询时间与材料取得时间分别标注。

## 5. 页面、请求与交互契约

### COL-FE-IF-01 初始加载与兼容

1. 用户确认主体、原查询任务结束后，通过GET /collections读取当前批次概览。没有主动确认主体前不调用浏览接口；首查进行中保留原状态，不将未完成分类显示为无记录。
2. 分类按basic、abnormal、penalty、judicial、asset顺序展示；本次手工线索另为一组，来源颜色保持三类区分。类别、工具和每条线索默认折叠，已知失败/未查全标识在折叠头可见。原“资料取得情况”及诊断入口保持。
3. 展开API工具时可读取本应用已存材料第1页，最多20条；工具下的单条展开只显示已取得正文，不请求后端或上游。折叠不查询上游、不触发模型。
4. 分类/单条默认折叠不是隐藏错误：类别头显示存在受限、未查全或更新失败，详情可展开。司法工具顺序沿用后端固定计划。
5. 首次读取概览失败时，若已有有效工作台payload，仍可折叠展示其中报告证据，但标明“材料浏览暂不可用，以下仅为当前报告证据包”，不宣称这是全部公共材料。单个404不据以猜测旧服务或企业无记录；按错误区显示资源不可用。后续读取失败保留最近成功浏览页并标明更新失败，503/网络错误不显示“无更多”。410按会话结束清理私人状态。

共享客户端拟新增签名：getCollections(sid:UUID):Promise<CollectionOverview>；getCollectionRecords(sid:UUID, toolName:CollectionToolName, batchId:UUID, page?:number):Promise<CollectionRecordsPage>（page省略为1）；loadCollectionPage(sid:UUID, command:LoadCollectionPageCommand, key:UUID):Promise<OperationHandle>；refreshCollectionTool(sid:UUID, command:RefreshCollectionToolCommand, key:UUID):Promise<OperationHandle>；getCollectionOperation(sid:UUID, opid:UUID):Promise<CollectionOperationView>。保留现有客户端全部签名，HTTP路径与后端COL-IF-01一一对应。

### COL-FE-IF-02 两类“下一页”

| 操作 | 启用与请求 | 成功/失败 |
| --- | --- | --- |
| 查看已收集下一页 | 当前CollectionRecordsPage.next_page非null；GET /collections/{tool}/records，传当前batch_id和展示page | 不调用上游；替换该工具当前展示页，提供上一页；其他分组状态不变 |
| 继续查询下一页20条 | 司法tool.next_upstream_page非null且无冲突任务；POST /collections/pages，正文含预期代次/修订/批次及所选工具/上游页号 | 202后轮询对应collection-operation；成功刷新概览/当前页，显示新增数量；失败保留当前页、报告与草稿 |

先引导用户查看已经保存但未浏览的页面，再查询缺失上游页；服务器仍负责最终去重与复用，不能靠前端判断避免并发重复取数。新增上游页可能跨页去重，不能假定其材料恰好占据一个新展示页；成功后停留当前页并显示新增数量及可用“查看已收集下一页”，不自动跳错页。

有界已存页不使用一键全量展开/全量查询；has_more=false时不显示继续查询。has_more=null但next_upstream_page可用时说明“上游总数未提供，可继续查询”；未知空页结束可取范围时next_upstream_page=null，说明“当前可取得范围已结束，完整性未知”，保留partial，不说没有更多风险。

### COL-FE-IF-03 主动更新与原失败重查

“更新本项资料”允许已成功或失败工具主动取得新批次，POST /collections/refresh，只传该工具；显示加载并保留旧材料。成功绑定新浏览批次，原工具展示页重置第1页、原单条展开状态清空；其他分类和草稿保留。失败显示last_error及原取得时间，仍可看旧页。

加载更多和更新本项只更新浏览区，原报告证据包不变。持续显示“已收集材料”与“当前报告证据包”两个数量；无成功报告时明确是“证据包”，不声称模型已经分析。batch_id与report_batch_id不同或浏览存在未纳入材料时显示固定说明，不把新材料冒充旧报告引用。

原覆盖区error/partial的“重新查询”仍走原queries/retry，重取原报告查询范围，终态按既有行为更新payload与报告状态；不是重取已浏览的全部页。不能将“更新本项资料”标成“重新分析”，本批不增加任意选择全部材料入报告的按钮。

### COL-FE-IF-04 权益受限与人工补充

已知TOOL_ENTITLEMENT_REQUIRED就近显示“该数据项当前账号未获调用权益”，提供“打开官方复核入口”“补充线索”，另保留“权益更新后重新查询”。未知401/403沿用鉴权待核对说明，不猜余额/套餐。无权益不会自动打开官网、调用其他工具或自动重试。

股权冻结/司法协助/股权出质固定入口gsxt.gov.cn；动产/权利担保入口zhongdengwang.org.cn；执行入口zxgk.court.gov.cn；其他工商/异常/处罚可用公示系统/信用中国固定入口。不动产仅显示需向属地登记机构按条件申请，不编造全国全量入口。链接target=_blank并隔离opener，保留复制地址回退；不抓取、解析、代理或检测网页。

“补充线索”滚动并聚焦现有表单，只有空且未修改草稿可以预选当前类别，不自动填正文、来源链接或信用代码声明；已有草稿不被覆盖。用户自行录入和提交，仍按原匹配/校验/知情确认/共享同意规则执行。

### COL-FE-STATE-01 生命周期

| 当前态 / 事件 | 后续态与反馈 |
| --- | --- |
| 尚未确认主体 | 不展示空的工具结论；搜索与人工确认可用 |
| 初读概览/本地页 | 显示局部加载；保留已有报告/草稿；同页重复读取不发并行请求 |
| 完整/空/部分/未查询 | 使用后端state与数量；空显示该时间未返回记录；部分始终说明未查全 |
| 发起加载更多/主动更新 | 禁用本会话冲突写按钮，显示所选工具处理中；展开/阅读已有页仍可用 |
| 成功终态 | 接纳同主体/代次且不低于当前修订的结果；按需重读概览/当前页，不改报告版本 |
| 失败/本地30秒HTTP超时 | 保留材料和草稿；若已有任务句柄继续通过该句柄查状态，不另造幂等键重发；无法取得句柄时用原键重放 |
| 任务服务端60秒终止 | 显示任务失败，可主动重试同一意图；新一次尝试使用新键；不自动付费循环 |
| 409版本/并发冲突 | 显示提示并重新读取概览；不自动重发用户写操作，不清空草稿 |
| 切换主体/结束会话 | 取消页面等待并清空旧浏览状态；迟到响应不写新主体；公共已提交页不因此删除 |
| 页面刷新 | 按原规则恢复有效会话再读概览；重启丢失私有会话时重新确认主体后仍能复用公共缓存 |

不把取消前端等待当作取消上游计次或删除公共结果。不同工具刷新返回顺序不能覆盖较新本地状态；浏览版本与报告evidence_version分别比较。

## 6. 异常与错误契约

| 条款 / 场景 | 显示、保留及恢复 |
| --- | --- |
| COL-FE-ERR-01 输入非法422 | 固定输入格式提示；不发送任意tool或跳页；保留当前页 |
| COL-FE-ERR-02 所有权404/会话410 | 404按资源不可用；410结束本地工作台并提示重新开始；不泄露其他用户记录 |
| COL-FE-ERR-03 409 | 按后端code提示状态变化/幂等冲突，读取概览，不丢草稿或重放新键 |
| COL-FE-ERR-04 存储503/网络 | 显示浏览/保存失败，保留已有页面和原报告，不声称资料为空或已共享保存 |
| COL-FE-ERR-05 上游失败 | 读取任务ErrorInfo和允许诊断，原文/密钥不展示；单项失败不清除其他项 |
| COL-FE-ERR-06 旧版/未记录 | 无批次映射不编造取得时间与reportIncluded；旧诊断仍按原“未记录”处理 |

## 7. 非功能规格

| 条款 | 可验证要求 | 验证 |
| --- | --- | --- |
| COL-FE-NFR-01 | 新增浏览HTTP请求30秒超时；新浏览任务轮询间隔2秒，不并行轮询同任务；离开页面取消等待，网络错误不自动启动新写任务。现有客户端尚无显式超时，本批只为新增浏览能力引入该要求，原接口及轮询间隔保持 | 客户端假时钟及浏览器专项 |
| COL-FE-NFR-02 | 桌面及360px视口不出现正文撑列；长JSON/URL折行，折叠头可换行；同页最多20条API材料 | 构建及真实浏览器检查 |
| COL-FE-NFR-03 | 折叠按钮可聚焦，Enter/Space操作，展开状态对辅助技术可见；加载及错误区域有状态提示；来源含文字，不只用颜色 | 键盘/可访问性人工专项 |
| COL-FE-NFR-04 | 客户端不保存API密钥、他人任务或私人草稿到公共缓存；链接仅固定白名单官网；材料作为文本显示，不执行HTML/Markdown指令 | 交互/注入测试 |

## 8. 业务硬规则

### COL-FE-RULE-01

保持人工确认主体；不从折叠头生成企业风险结论；数量不等于独立事件数量；第三方API及用户转述不升级为官方证据。缓存标时间、未查全标范围；没有记录不等于无风险。原报告文本按原文显示，不因新增浏览材料偷偷改写或冒充其已覆盖新材料。

所有固定文案进字典；页面“严重/警告”仅表示操作状态，不是公司评级。前端不自行计算公共缓存有效期、权限或完整性，最终判断来自后端。

## 9. 验收标准与追踪

以下为条款追踪；自动化与实际浏览器验证的范围分别记录在COLLECTION-TEST-1及专项验收，不把构建等同于所有场景通过。

| 验收 | 对应条款 | 场景 / 计划归属 |
| --- | --- | --- |
| COL-FE-AC-01 | DATA-02/03、IF-01 | 分类/工具/单条默认折叠；展开类别只读存量、单条不请求；来源/计数/未知/时间正确；组件/浏览器 |
| COL-FE-AC-02 | IF-02 | 存量下一页和查询下一页分开；仅所选司法工具；已有页不重查；重复点击禁用、去重后不跳错展示页；客户端/HTTP/浏览器 |
| COL-FE-AC-03 | IF-03、STATE-01 | 更新新批次、失败保留旧时间/页、报告范围不同标注、草稿保留、原重试范围不扩大；交互/浏览器 |
| COL-FE-AC-04 | IF-04、ERR-05、NFR-04 | 确定权益与未知鉴权区分；官方新标签及复制入口；补充不覆盖草稿；无抓取及泄密；人工专项 |
| COL-FE-AC-05 | STATE-01、ERR-01..06 | 初始/加载/空/错误/取消/过期/旧服务、409、超时重放、切换晚到和修订隔离；状态/客户端契约 |
| COL-FE-AC-06 | NFR-01..04、RULE-01 | 请求有界、键盘/窄屏、注入文本不执行、报告原文不改、来源无评级；构建及浏览器专项 |

SDD、类型/骨架和契约测试已依次确认，界面已实现。原查询、诊断、私人录入、报告版本及窗口246项回归保持；必要的替身/新行为断言变更在测试评审包中单独列明。
