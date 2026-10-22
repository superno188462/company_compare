# 骨架映射与评审记录

日期：2026-10-22；行为基线：CONTRACT-1.0；骨架状态：结构自查完成，待开发者评审。

用户明确回复“好先生成骨架吧”，授权从已交付 SDD 进入骨架阶段，随后提供目标 GitHub 仓库并要求提交。本记录不将提交 GitHub 视为骨架或契约测试已获评审通过。

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

- `src/` 与 `backend/` 内的31个函数/方法，除 docstring 外均只有 `raise NotImplementedError()`。
- Pydantic 只声明类型、必填、长度、枚举、模式与基础模型配置，没有自定义业务校验器、数据库、模型客户端或网络请求。
- 前端只有类型和接口，未实现页面、fetch、自动确认、共享、复制或官网导航行为。
- 开发工具 `scripts/generate_contracts.py` 和 `scripts/check_skeleton.py` 包含离线生成/检查逻辑，不是应用业务逻辑。
- 测试目录只保留下一阶段位置，正式契约测试尚未编写。

## 类型投影的边界

JSON Schema 为权威，Pydantic/TS 是声明投影。生成工具展开原有来源和分类条件，但不实现主体匹配、聚合、幂等、权限、期限、唯一性、报告版本等业务规则；输出跨字段条件及 URI 完整格式仍以原 Schema/SDD 为准，不能仅以 Pydantic 实例化或 TS 编译通过声称已满足。

本轮只修改 Schema 的文档标题与审批状态等元信息，未改变字段、枚举、约束或已确认行为。

## 检查记录

| 检查 | 实际结果 |
| --- | --- |
| `uv run mypy` | 严格模式通过，12个应用/后端源文件 |
| `uv run python scripts/check_skeleton.py` | 31个未实现函数、13个服务签名、3个端口签名、13个路由、模型字段/必填性及 Schema 往返检查通过 |
| `npm --prefix frontend run typecheck` | TypeScript 严格检查通过，无 emit |
| 导入检查 | 模型、应用服务、端口、异常和 HTTP 模块可导入，不启动真实服务 |

实际业务、真实提供方、LLM、浏览器、权限/存储/清理尚未实现或验证。上述检查不能替代后续契约测试。

## 待开发者评审

- 模型字段、签名和层次是否与 SDD 一致。
- 单候选人工确认、草稿/证据分离、共享准入和报告版本是否有对应声明。
- 是否允许进入契约测试编写阶段。

开发者结论：待确认。确认后再锁定骨架，编写并评审正式契约测试；本阶段不自行填充业务实现。
