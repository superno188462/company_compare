# 骨架映射与评审记录

日期：2026-10-24；行为基线：CONTRACT-1.0 + DIAG-1.0；当前状态：主线、私人录入、失败重试及脱敏诊断已接通，未覆盖项另列。

用户明确回复“好先生成骨架吧”，授权从已交付 SDD 进入骨架阶段，随后提供目标 GitHub 仓库并要求提交。本记录不将提交 GitHub 视为骨架或契约测试已获评审通过。

目录整理：六项材料已按用途移入 `contracts/`、`specs/analysis/` 和 `tests/`，README 为统一阅读入口。仅调整路径、引用和导航；材料内容、Schema 标识、接口签名及 CONTRACT-1.0 行为保持不变。本次整理未进入业务实现阶段。

## 条款与骨架映射

| 规格 | 骨架产出 | 说明 |
| --- | --- | --- |
| 输入/输出 JSON Schema、BE-DATA-01 | [Python 共享模型](../../src/company_screening/contracts/generated.py)、[TypeScript 共享类型](../../frontend/src/contracts/generated.ts) | 由本地 Schema 生成，不手改生成文件 |
| BE-DATA-02、BE-IF-07 | [边界模型](../../src/company_screening/contracts/boundary.py)、[前端边界类型](../../frontend/src/contracts/boundary.ts) | 请求、候选、草稿、任务、回执和错误类型 |
| BE-IF-02 | [services.py](../../src/company_screening/services.py) | 13个应用服务方法，签名与规格对齐 |
| BE-IF-07 | [ports.py](../../src/company_screening/ports.py)、[errors.py](../../src/company_screening/errors.py) | 3个外部方法、应用/提供方/模型异常声明 |
| BE-IF-01 | [routes.py](../../backend/routes.py) | 13个 HTTP 路由声明，含请求/返回类型与幂等头 |
| BE-NFR-03 / DATA-05 | [dependencies.py](../../backend/dependencies.py) | 签名匿名Cookie建立所有者上下文，不相信客户端 actor_id |
| 组合根/配置边界 | [app.py](../../backend/app.py) | 装配会话与候选搜索服务；导入不联网、不启动服务 |
| FE-IF-01 | [client.ts](../../frontend/src/api/client.ts) | 13个既有API Client签名及同源HTTP调用实现 |
| FE-DATA-01 | [state.ts](../../frontend/src/workspace/state.ts) | 工作台状态类型，无状态转换实现 |
| FE-DATA-02 | [props.ts](../../frontend/src/components/props.ts) | 9组组件 Props 与回调，无页面实现 |

辅助类型 CreditCode、Timestamp、各来源分支、分类状态分支和 GeneratedContractBundle 是生成器的类型表达，不增加应用字段或接口。GeneratedContractBundle 仅用于代码生成入口，不是 HTTP/LLM 输入输出。

## 本阶段实现边界

- `src/` 与 `backend/` 内会话管理、候选搜索、人工确认、五类查询编排、失败类别重试与诊断、终态写回、任务轮询、私有草稿保存/清空、私人线索原子接纳、签名Cookie依赖、11个已接通路由、create_app、4个错误处理/中间件函数，以及天眼查适配器的构造、搜索、五类详情与脱敏错误构造已实现。总计56个已实现、7个占位；检查工具按明确清单区分，公共服务与端口签名检查保持不变。
- Pydantic 继续只声明类型、必填、长度、枚举、模式与基础模型配置。天眼查网络请求封装在 `TianyanMcpAdapter` 的候选搜索和固定五类详情方法中，测试通过注入假 HTTP 客户端隔离；模块导入和适配器构造均不会联网。
- 前端已按用户指定采用 React + TypeScript + Vite，并接通匿名会话创建/恢复、候选搜索、人工确认、任务轮询、完整结果展示、固定官网新标签页/复制、私有草稿保存/清空及提交接纳。单候选仍需点击确认；页面不自动选择、不读取官网，未提交草稿不作为证据。失败类别重试按钮已开放；共享与模型重试仍待后续切片。
- 开发工具 `scripts/generate_contracts.py` 和 `scripts/check_skeleton.py` 包含离线生成/检查逻辑，不是应用业务逻辑。
- 2026-10-23 首批50个契约用例已确认并进入实现；先接通HTTP、查询与草稿至108项通过，再经用户确认30项私人接纳、17项查询重试及50项诊断扩展测试并实现，当前全量205项通过，详见 [执行记录](../../tests/test-cases.md)。

## 类型投影的边界

JSON Schema 为权威，Pydantic/TS 是声明投影。生成工具展开原有来源和分类条件，但不实现主体匹配、聚合、幂等、权限、期限、唯一性、报告版本等业务规则；输出跨字段条件及 URI 完整格式仍以原 Schema/SDD 为准，不能仅以 Pydantic 实例化或 TS 编译通过声称已满足。

本轮只修改 Schema 的文档标题与审批状态等元信息，未改变字段、枚举、约束或已确认行为。

## 检查记录

| 检查 | 实际结果 |
| --- | --- |
| `uv run mypy` | 严格模式通过，15个应用/后端源文件 |
| `uv run python scripts/check_skeleton.py` | 56个已实现函数/方法、7个占位、13个服务签名、3个端口签名、13个路由、模型字段/必填性及 Schema 往返、诊断与字典白名单映射通过 |
| `npm --prefix frontend run typecheck` | TypeScript / React TSX 严格检查通过，无 emit |
| `npm --prefix frontend run build` | Vite 生产构建通过，生成 `frontend/dist/` |
| React 工作台浏览器检查 | 本机 Chrome 无头模式检查开发服务：会话创建成功、搜索请求到达后端、上游502时保留查询词并显示固定重试提示；1440px布局、3个安全官网外链及当前空态显示正常 |
| 导入检查 | 模型、应用服务、端口、异常和 HTTP 模块可导入，不启动真实服务 |

真实天眼查 MCP 鉴权与最小搜索已验证；搜索和五类详情适配器已接入应用服务和 HTTP。人工确认后会创建后台任务，固定串行调用五类端口，并通过任务端点返回完整终态；可控提供方下的部分失败、全空、未配置和迟到写回均已验证。当前Key的L2明细权限不足，相关类别如实标错；用户可在开通权限后主动重试失败类别，本地合成成功不等于真实权限已开通。签名匿名Cookie可隔离会话，但同源写校验、持久化、多实例一致性、周期清理和LLM尚未实现或验证。

React 工程调整：`App.tsx` 编排当前已实现的后端主线，`WorkspacePanels.tsx` 实现搜索、候选、主体、覆盖、证据、报告、草稿及官网组件，`client.ts` 按既有13个方法提供同源 HTTP Client，Vite 仅代理 `/api` 到本机后端。Schema、后端签名及业务基线未变。实际检查结果见上表。

## 待开发者评审

2026-10-24 DIAG-TYPE-1（已确认）：依据用户已确认DIAG-1.0，新增QueryDiagnostic / QueryDiagnostics声明、WorkflowStatus可选query_diagnostics、ProviderError可选diagnostic和CoveragePanel可选diagnostics。Python/TS投影从输出Schema生成，LLM输入Schema不变，无诊断采集/页面逻辑；旧155项通过，mypy/前端类型/骨架结构检查通过。用户明确选择“确认类型，继续测试（推荐）”，批准本批类型。具体字段及边界见 [诊断SDD](../backend/query-diagnostics.spec.md)。

2026-10-24 DIAG-TEST-1及实现：用户明确选择“确认测试，开始实现（推荐）”，批准本批50项测试后逐函数实现，当前全量205通过，诊断折叠区和重试后的诊断更新/清除及旧结果提示已完成浏览器验收。DIAG-1.0仅扩展输出运行信息；输入Schema和既有155项测试不变，输出Schema并非保持原字段集合。

- 模型字段、签名和层次是否与 SDD 一致。
- 单候选人工确认、草稿/证据分离、共享准入和报告版本是否有对应声明。
- 已准备的首批契约测试是否准确反映对应条款。

开发者结论：用户在首批测试交付后回复“继续，第一步是开发什么？”，确认该批并进入实现；后明确批准新增通用提示input_invalid（TEXT-1.1），同步扩展类型及9个HTTP用例。用户随后提供天眼 AI 页面及 MCP API Key，授权真实接入；先实现搜索适配器，再在后续“继续”指令下依次接通会话/搜索、人工确认、查询任务、五类详情适配及私有草稿保存/清空。随后用户明确选择“确认，按这批测试实现（推荐）”，批准SUBMIT-TEST-1的30项私人接纳测试，又明确选择“确认，补齐重试按钮和后端（推荐）”，批准QUERY-RETRY-TEST-1的17项查询重试测试；两批均已逐函数实现并接通页面。首批50个测试文件及核心Schema未变。当前整体155项通过；其余未覆盖范围继续按测试流程推进。
