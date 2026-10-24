# 查询失败诊断 SDD

## 1. 文档头

| 项目 | 内容 |
| --- | --- |
| 标识 / 版本 | SDD-QUERY-DIAGNOSTICS / v1.2（行为基线DIAG-1.0不变） |
| 行为扩展 | DIAG-1.0，基于 CONTRACT-1.0；SDD/UI、类型与50项测试依次确认，已实现并通过本地集成验证 |
| 日期 / 责任人 | 2026-10-24（Asia/Shanghai）/ 项目开发者（用户本人） |
| 需求依据 | 用户要求“修改SDD并修改代码”，补齐分类查询失败的具体原因 |
| 关联基线 | [后端 SDD](screening.spec.md)、[前端 SDD](../frontend/workspace.spec.md)、[UI 增补](../common/ui_notes.md) |
| 变更记录 | v0.1：定义诊断契约；v1.0：用户明确选择“确认本版 SDD/UI（推荐）”，批准v0.1所列DIAG-1.0全部字段、交互及边界，进入类型和测试阶段；未批准的业务实现不提前填充 |

类型评审包 DIAG-TYPE-1：输出Schema已声明QueryDiagnostic的8个字段、五类别可选映射及WorkflowStatus.query_diagnostics缺省空对象；Pydantic与TypeScript由同一Schema生成；ProviderError仅增加可选diagnostic属性；CoveragePanel仅声明可选diagnostics属性，尚无诊断采集或页面业务。生成工具对新可选映射作等价内联，避免RootModel默认字典的类型不匹配，未手改生成类型。旧155项测试、mypy、骨架检查和前端严格类型检查通过。用户明确选择“确认类型，继续测试（推荐）”，批准该类型版本，进入契约测试编写。

测试评审包 DIAG-TEST-1：新增test_query_diagnostics_adapter.py（30项）与test_query_diagnostics_service.py（20项），原155项不变。初次50项中11项声明式兼容/Schema断言通过，39项由于诊断尚未采集/保存而失败，无skip/xfail或导入错误；全量166通过/39待实现失败。用户明确选择“确认测试，开始实现（推荐）”，据此锁定本批测试并进入逐函数实现，测试矩阵与浏览器专项见tests/test-cases.md。

v1.2实现记录：逐函数完成受控错误构造、HTTP/分页/记录/集合诊断及会话结果保存；后接通CoveragePanel折叠区及1.2.0文案字典。50项本批测试与原155项全部通过，mypy/结构检查/React构建通过。隔离合成HTTP下，浏览器验证已知原因、无原文泄露、键盘展开、展开无新API请求、重试更新与清除、草稿保留、旧记录提示和窄屏无溢出；不将合成结果视为真实天眼查故障已解决。无数据库迁移或新增环境变量；回滚需前后端及生成类型一起回到前一版本，内存结果不跨重启迁移。

## 2. 目标与范围（DIAG-SCOPE-01）

用户在“资料取得情况”中看到类别失败后，展开“查看原因”，获知失败子接口、失败环节、HTTP状态及确定的中文原因。保留现有错误码、查询计划、完整性规则、重试、证据接纳、报告和草稿行为。首版仅覆盖五类详情查询；搜索错误、模型诊断、后台管理和历史诊断检索不在本次范围。

## 3. 外部依赖（DIAG-DEP-01）

复用 CompanyDataPort、天眼查 MCP Shared Core、既有会话/任务与同源API。诊断不新增任何外部请求，不为取得原因自动重查收费接口。测试使用假HTTP传输或提供方替身；真实上游权限变化不作为本功能通过依据。

## 4. 数据模型与 Schema（DIAG-DATA-01）

权威机器定义已按评审结果增补至 `contracts/output-schema.json`。`input-schema.json`、CategoryResult、现有API路径、请求体及公共服务签名不变。

`WorkflowStatus`增加可选 `query_diagnostics: QueryDiagnostics`，缺省为空对象。QueryDiagnostics仅允许basic/abnormal/penalty/judicial/asset这五个可选键，每个值为QueryDiagnostic，不用数组保存历史。旧payload缺少此字段仍合法；新服务输出该字段。诊断不是企业事实或证据，禁止加入LLM输入的QueryCoverage。

| QueryDiagnostic字段 | 类型 / 约束与语义 |
| --- | --- |
| diagnostic_id | 必填UUID，定位本次类别失败；同一终态或幂等回放保持不变，不是读取凭据 |
| tool_name | 必填、可null；天眼查现有固定工具清单中的名称；无法确定时null，不猜是哪一个子接口 |
| phase | 必填枚举：configuration / request / response / pagination / record / aggregate / unknown |
| reason_code | 必填枚举，见DIAG-ERR-01；由程序确定，中文来自固定字典 |
| http_status | 必填int[100..599]或null；实际取得时记录真实值，无HTTP响应或未获知时null，不能统一补成200 |
| field | 必填白名单字段名或null；仅tool_name/content/sources/items/total/pageNum/pageSize/record_id/record_count/record_credit_code/source_url/event_time/source_publisher，禁止填原始值 |
| actual_count | 必填int>=0或null；仅确定的条数/字符数，不回显正文 |
| limit_count | 必填int>=1或null；已触发的应用上限，不能把分页pageSize当作授权额度 |

ProviderError新增可选公共属性`diagnostic: QueryDiagnostic | None = None`；code/retryable与原语义不变。未提供诊断的旧适配器或测试替身仍可工作，由应用生成UNCLASSIFIED_FAILURE，工具/HTTP/字段/数量均未知。统一异常文字保持脱敏，不携带上游原文。

## 5. 接口与业务分支（DIAG-IF-01）

既有任务终态、会话恢复的完整payload携带诊断，不增加“查看原因”的请求。所有权、过期、代次和迟到写回校验沿用DATA-05。

1. 初次查询：每个error类别保存本次确定的诊断；一个类别遇到第一个失败即结束，明确是“本类别首次失败”，不能声称列出了所有失败子接口。
2. 成功、empty、not_requested类别不得携带当前失败诊断。成功重试删除对应旧诊断；再次失败以新诊断替换该类别旧诊断，其他类别诊断完全保留。
3. 排队/执行中仍展示上次完整结果与上次诊断，明确任务处理中；不把旧原因标成新任务已失败。终态一次性替换，不推送半成品。
4. 仅诊断编号或内容变化不构成LLM分析输入变化，不单独增加evidence_version或触发分析；工作台result_revision仍可递增。证据/覆盖变化继续按原规则处理。
5. 手工录入、草稿保存、会话刷新不得丢失当前诊断。结束/过期后随私人结果不可读；不新建跨会话诊断池或持久日志。

## 6. 错误原因契约（DIAG-ERR-01）

| reason_code | 确定条件 / 中文含义 |
| --- | --- |
| PROVIDER_NOT_CONFIGURED | 服务端未配置提供方，未发起HTTP请求 |
| AUTH_REQUIRED | 实际401/403，无法进一步确定是密钥还是工具权益；不等同额度不足 |
| TOOL_ENTITLEMENT_REQUIRED | 实际403且上游机器错误码明确为insufficient_entitlement；仅提示该工具缺少调用权益，不推断购买何种套餐 |
| RATE_OR_QUOTA_LIMIT | 实际429；仅说明请求受频率或额度限制，无法区分时不得说余额耗尽 |
| REQUEST_TIMEOUT | HTTP调用超时，没有可靠HTTP状态则null |
| NETWORK_ERROR | HTTP网络连接失败，没有可靠HTTP状态则null |
| REQUEST_REJECTED | 其他4xx或异常HTTP状态，请求未被上游正常接受；实际状态可见 |
| SERVICE_UNAVAILABLE | 实际5xx，上游服务未正常响应 |
| RESPONSE_INVALID | 返回外壳、内容或类别不符合当前解析约定；不直接断言上游数据错误 |
| PAGINATION_INVALID | items/total/pageNum/pageSize格式、页码或数量声明不合法 |
| PAGINATION_CHANGED | 翻页过程中声明的总数发生变化 |
| PAGINATION_INCOMPLETE | 返回数量与总数不符，或仍声明有下一页却返回空页 |
| RECORD_LIMIT_EXCEEDED | 单工具/类别/总证据超过200条；明确应用上限，显示已知实际数量和200 |
| CONTENT_LIMIT_EXCEEDED | 单条规范化正文超过4000字符；显示实际字符数和4000，不静默截断 |
| UPSTREAM_WARNING | 返回非空_warnings，当前无法确认完整取得；不直接展示warning原文 |
| RECORD_INVALID | 记录字段或长度不符合当前契约，显示能确定的白名单字段 |
| SUBJECT_MISMATCH | 返回的企业代码与当前主体不一致；不回显其他主体原始记录 |
| DUPLICATE_RECORDS | 同一批次记录定位重复，不能当完整新集合接纳 |
| UNCLASSIFIED_FAILURE | 旧适配器无诊断或未归类内部异常；明确“具体原因未记录”，不能从error_code猜子接口 |

原UPSTREAM_*与SUBJECT_RESPONSE_MISMATCH错误码及重试语义不变。错误码属于分类，reason_code标记本次已知触发原因。与既有边界相同：分类失败任务可正常返回完整payload，不升级为HTTP500。

## 7. 非功能规格（DIAG-NFR-01）

只允许固定枚举、工具白名单、数字和UUID进入诊断；禁止原始响应体、任意上游message、Authorization、密钥、请求头/参数、企业正文、URL查询参数、异常repr/堆栈。即使上游把密钥或恶意HTML放进错误消息，也不进入payload、页面或新增日志。错误原因完全由代码和字典生成，LLM不能参与诊断。首版只沿用单进程会话存储的现有限制，不虚构重启后可追溯性。

## 8. 业务硬规则与页面契约（DIAG-UI-01）

沿用现有CoveragePanel及视觉体系，新增可选`diagnostics?: QueryDiagnostics`属性，原coverage/busy/onRetry保持不变。仅error类别显示“查看原因”的就地折叠区，使用语义化details/summary，支持键盘展开；重试按钮保持独立。展开只影响本地显示，不续期、不联网、不启动重试或LLM。

显示固定中文原因、失败环节、已知工具的中文名称及技术名称、HTTP状态、已知字段/数量上限和诊断编号；时间复用该类别queried_at。未知字段显示“未记录”，不可用破折号暗示有默认原因。旧payload无诊断时仍可展开，明确“这次查询未保存详细原因，请重新查询以记录新的诊断。”重试中提示仍为上次查询记录；再次失败后显示新诊断，成功后入口和旧诊断消失。移动端在对应类别下换行，不能横向撑破页面。

字典增加独立query_diagnostics分组，包含原因、阶段、白名单工具/字段名称及固定说明；不修改HintCode或借用LLM报告文案。

## 9. 验收标准（DIAG-AC-01）

契约/类型和测试须依次评审后实施；既有155项锁定测试保持不变，新增用例绑定本文件条款。

- HTTP401/403、明确权益不足、429、500、超时、连接故障：原因准确，HTTP已知/未知区分。
- 外壳解析失败、分页非法/变动/不完整、warning、记录校验、主体错配、重复记录、200条/4000字符上限：确定工具/环节/字段/数量，不放宽原失败判定。
- 任意错误原文含假密钥、企业正文、HTML：payload及页面不含其内容；不泄露到新增日志。
- 原计划五类中成功/空/失败混合：只失败类别有诊断，完整输出通过Schema。
- 显式重试再次失败替换本类诊断，恢复成功删除本类诊断，其他类别/用户证据/草稿/报告保留。
- 同键回放不生成新诊断、不重复调用；单纯诊断变化不使输入版本递增。
- 会话恢复保留诊断，其他所有者不可读取，过期/结束及旧代次任务不可写回。
- 旧payload/旧ProviderError缺少诊断可兼容；页面显示“未记录”，不猜测原因。
- LLM输入Schema保持不变，剥离工作流诊断后构造标准QueryCoverage；无诊断数据成为企业证据。
- 浏览器验证：展开/收起不产生请求，键盘可用，等待状态和重试后内容更新正确；桌面/窄屏不溢出；不以合成数据证明真实上游原因。
