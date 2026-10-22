# 企业公开线索筛查

固定工作流：搜索企业 → 用户确认主体 → 取得公开线索 → 接纳人工补充 → 基于证据生成有限分析。官网只通过新标签页由用户浏览，应用不抓取网页，模型不自行检索或选择企业。

当前处于 **SDD 已确认、骨架待评审** 阶段。Python 业务函数均为 `raise NotImplementedError()`；前端只有类型、API 能力和组件 Props 声明。没有可运行的业务页面，也未连接真实天眼查或模型服务。

## 项目目录

```text
specs/common/                 PRD、UI、共享语义与骨架评审映射
specs/backend/                后端 SDD
specs/frontend/               前端 SDD
src/company_screening/       模型、服务签名、异常与外部端口
backend/                     HTTP 路由与装配占位
frontend/src/                共享类型、API Client 接口、状态与组件 Props
scripts/                     离线类型生成与骨架检查工具
input-schema.json            LLM 输入权威 Schema
output-schema.json           工作流结果权威 Schema
skill.md                     企业分析方法论
llm-system-prompt.txt         固定分析提示词
text-dict.json               固定提示与 UI 文案
test-cases.md                验收场景规划，正式契约测试尚未编写
```

## 准备环境

Python 版本、环境与依赖由 `uv` 管理，开发解释器使用 `.python-version` 中的 Python 3.13；生成源码目标为 Python 3.12。前端工具使用 Node.js 与 npm。安装版本分别由 `uv.lock` 和 `frontend/package-lock.json` 锁定。

```powershell
uv sync --locked
npm --prefix frontend ci
```

当前没有真实外部服务的启动指令。`backend.app.create_app()` 也是未实现占位，不能将类型检查通过视为系统可用。

## 生成与检查骨架

```powershell
uv run python scripts/generate_contracts.py
uv run mypy
uv run python scripts/check_skeleton.py
npm --prefix frontend run typecheck
```

两个 JSON Schema 是权威定义。生成器只读取本地文件，展开已有来源/分类分支，生成 Python 和 TypeScript 声明，不修改原 Schema，不允许远程引用。不要直接修改 `generated.py` 或 `generated.ts`。

类型投影不实现所有跨字段行为：主体匹配、查询聚合、唯一性、权限、有效期、报告版本与条件空值等仍按原 Schema 和 SDD 约束，等待契约测试评审后实现。工具脚本中的生成/检查逻辑不属于应用业务实现。

## 评审与后续阶段

骨架和 SDD 的对应关系见 [骨架评审记录](specs/common/skeleton-review.md)。骨架评审通过后，再编写并评审绑定条款的正式契约测试，之后逐函数填充实现。

真实提供方接口/权限、模型接入、浏览器官网入口、持久化与清理尚未验证；合成检查材料不能作为真实企业信息或真实连通性证明。
