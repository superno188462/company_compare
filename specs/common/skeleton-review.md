# 骨架映射与评审记录

日期：2026-10-23；行为基线：CONTRACT-1.0；当前状态：首批测试已确认，会话服务逐函数实现中。

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
| BE-NFR-03 / DATA-05 | [dependencies.py](../../backend/dependencies.py) | 所有者验证占位，只接收框架请求，不相信客户端 actor_id |
| 组合根/配置边界 | [app.py](../../backend/app.py) | 工厂为占位，导入不调用工厂、不启动服务 |
| FE-IF-01 | [client.ts](../../frontend/src/api/client.ts) | 13个 API Client 方法签名，无请求实现 |
| FE-DATA-01 | [state.ts](../../frontend/src/workspace/state.ts) | 工作台状态类型，无状态转换实现 |
| FE-DATA-02 | [props.ts](../../frontend/src/components/props.ts) | 9组组件 Props 与回调，无页面实现 |

辅助类型 CreditCode、Timestamp、各来源分支、分类状态分支和 GeneratedContractBundle 是生成器的类型表达，不增加应用字段或接口。GeneratedContractBundle 仅用于代码生成入口，不是 HTTP/LLM 输入输出。

## 本阶段实现边界

- `src/` 与 `backend/` 内原31个函数/方法中，会话create/restore/reset及create_app已实现；另增加4个错误处理/中间件函数。总计8个已实现、27个占位；检查工具按明确清单区分，公共签名检查保持不变。
- Pydantic 只声明类型、必填、长度、枚举、模式与基础模型配置，没有自定义业务校验器、数据库、模型客户端或网络请求。
- 前端已按用户指定采用 React + TypeScript + Vite，可预览初始外壳与固定官网新标签页链接；既有组件 Props 绑定到 React 类型，业务状态、fetch、自动确认、共享和复制仍未实现。页面没有企业数据，搜索禁用。
- 开发工具 `scripts/generate_contracts.py` 和 `scripts/check_skeleton.py` 包含离线生成/检查逻辑，不是应用业务逻辑。
- 2026-10-23 已增加首批50个可执行契约用例，42通过、8项因应用/服务占位失败；完整业务场景尚未覆盖，测试未锁定，详见 [执行记录](../../tests/test-cases.md)。

## 类型投影的边界

JSON Schema 为权威，Pydantic/TS 是声明投影。生成工具展开原有来源和分类条件，但不实现主体匹配、聚合、幂等、权限、期限、唯一性、报告版本等业务规则；输出跨字段条件及 URI 完整格式仍以原 Schema/SDD 为准，不能仅以 Pydantic 实例化或 TS 编译通过声称已满足。

本轮只修改 Schema 的文档标题与审批状态等元信息，未改变字段、枚举、约束或已确认行为。

## 检查记录

| 检查 | 实际结果 |
| --- | --- |
| `uv run mypy` | 严格模式通过，13个应用/后端源文件 |
| `uv run python scripts/check_skeleton.py` | 8个已实现函数/方法、27个占位、13个服务签名、3个端口签名、13个路由、模型字段/必填性及 Schema 往返检查通过 |
| `npm --prefix frontend run typecheck` | TypeScript / React TSX 严格检查通过，无 emit |
| `npm --prefix frontend run build` | Vite 生产构建通过，生成 `frontend/dist/` |
| React 外壳浏览器检查 | 本机 Chrome 无头模式检查开发服务及生产预览：1440px/360px 布局、无横向溢出、禁用搜索、3个安全官网外链与键盘跳转通过；无浏览器报错、无主动外部请求 |
| 导入检查 | 模型、应用服务、端口、异常和 HTTP 模块可导入，不启动真实服务 |

实际业务、真实提供方、LLM、权限/存储/清理尚未实现或验证；官网站点实际可用性、业务交互和其他浏览器兼容尚未验证。上述外壳检查不能替代后续契约测试。

React 工程调整：新增 `main.tsx` 挂载入口、`App.tsx` 初始外壳、样式和 Vite 配置；9 组组件 Props 通过 `components/registry.ts` 引用原定义。API Client、Schema、后端签名及业务基线未变。前端增加 `dev / build / preview` 命令，实际检查结果见上表。页面内新增的说明属于开发外壳预览，不将其视为正式产品文案或已完成的业务组件。

## 待开发者评审

- 模型字段、签名和层次是否与 SDD 一致。
- 单候选人工确认、草稿/证据分离、共享准入和报告版本是否有对应声明。
- 已准备的首批契约测试是否准确反映对应条款。

开发者结论：用户在首批测试交付后回复“继续，第一步是开发什么？”，确认该批并进入实现；后明确批准新增通用提示input_invalid（TEXT-1.1），同步扩展类型及9个HTTP用例。首批50个测试文件及核心Schema未变。当前整体57通过/2占位失败；其余未覆盖范围继续按测试流程推进。
