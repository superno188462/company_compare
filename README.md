# 企业公开线索筛查

这是一个固定流程的企业公开线索筛查工具，帮助用户核对材料、比较矛盾线索，并了解当前信息能支持什么结论。

## 只看这条主线

输入公司名称 → 人工确认主体 → 查看公开证据 → 自动生成分析 → 手工补充后刷新分析。

即使搜索只有一个候选，也由用户确认。人工补充只有匹配当前主体的材料才能进入分析。官网通过“在新标签页打开官网”按钮供用户核对。

分析重点是：不同材料是否支持同一判断、是否来自同一原始来源、有无反证或其他解释、还缺什么信息。每条结论能追溯到证据；材料不足就说明不足。

## 现在做到哪里

**前端采用 React + TypeScript + Vite，已能启动工作台外壳。** 页面提供布局预览与官网外链；搜索、证据处理和报告生成尚未接入页面。后端已实现会话创建、恢复和结束3个服务方法，并完成天眼查 MCP 的鉴权与候选搜索适配器；应用服务和 HTTP 路由尚未把该适配器接到前端，模型服务也未接入。

首批50个契约用例经用户确认后开始逐函数实现；补充HTTP错误和天眼查适配器用例后，当前67通过、2项因搜索/确认应用服务占位而失败。明细见[验收场景](tests/test-cases.md)。HTTP应用入口和统一错误包已接通；会话鉴权、业务路由与前端接线仍待完成。当前会话仅使用进程内存，重启会丢失，持久化和自动清理尚未完成。

天眼查接入采用官方 MCP Shared Core，不使用旧版搜索 URL。把 `.env.example` 复制为 `.env`，在 `TYC_AUTHORIZATION` 中填写天眼 AI 页面生成的 MCP API Key。`.env` 已被 Git 忽略，密钥不得写入前端、日志、测试或提交记录。

## 文件怎么找

日常从本页开始；需要修改哪部分，再打开对应材料。

| 要看什么 | 入口 |
| --- | --- |
| 企业交叉分析方法 | [分析规则](specs/analysis/skill.md)、[模型提示词](specs/analysis/llm-system-prompt.txt) |
| 产品范围与页面流程 | [需求](specs/common/prd.md)、[页面说明](specs/common/ui_notes.md) |
| 模型输入、页面输出和固定文案 | [输入](contracts/input-schema.json)、[输出](contracts/output-schema.json)、[文案](contracts/text-dict.json) |
| 开发时核对接口与约束 | [后端规格](specs/backend/screening.spec.md)、[前端规格](specs/frontend/workspace.spec.md) |
| 验收与当前骨架状态 | [验收场景](tests/test-cases.md)、[骨架检查记录](specs/common/skeleton-review.md) |

代码目录：

```text
src/company_screening/   企业筛查业务：模型、服务、外部依赖接口
backend/                 HTTP 接口与应用装配
frontend/src/            React 页面外壳、组件契约、状态与 API 调用接口
contracts/               输入输出 Schema 与固定文案
specs/                   分析方法、需求与开发规格
tests/                   验收场景及后续测试
scripts/                 类型生成与骨架检查工具
```

## 启动前端

```powershell
npm --prefix frontend ci
npm --prefix frontend run dev
```

打开终端显示的本地地址（默认 `http://127.0.0.1:5173`）。当前为骨架预览，搜索按钮禁用，不发起业务请求。页面入口为 `frontend/src/App.tsx`；既有组件 Props 通过 `components/registry.ts` 绑定 React 组件类型，后续实现沿用同一套契约。

生产构建使用 `npm --prefix frontend run build`，产物位于 `frontend/dist/`；`npm --prefix frontend run preview` 可本地预览构建结果。部署目录为 `dist/`，前端不放置天眼查或模型密钥。

## 启动后端开发服务

```powershell
uv sync --locked
uv run uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8000
```

接口文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。当前可查看13个HTTP接口契约；实际会话鉴权和业务路由仍未实现，调用这些占位会收到脱敏500错误包。测试中的身份替身仅在测试环境使用，不等于真实鉴权完成。这是开发服务，尚不提供真实企业查询。

## 开发检查

使用 `uv` 管理 Python，开发解释器为 Python 3.13，源码目标为 Python 3.12；前端工具使用 Node.js 与 npm。安装依赖后运行检查：

```powershell
uv sync --locked
npm --prefix frontend ci
uv run mypy
uv run python scripts/check_skeleton.py
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

`contracts/` 中两个 JSON Schema 是字段定义的权威来源；生成类型由 `uv run python scripts/generate_contracts.py` 更新，不手改 `generated.py` 或 `generated.ts`。共享行为语义见 [global_schema.md](specs/common/global_schema.md)。

上述命令检查契约结构与类型，不能证明全流程可用。契约测试单独执行：`uv run python -X utf8 -m pytest -q --tb=line`，目前预期返回非零退出码（剩余占位导致2项失败）。天眼查搜索适配器可单独验证：`uv run pytest -q tests/contracts/test_tianyan_mcp_adapter.py`，当前10项通过；它使用假 HTTP 传输，不消耗真实查询额度。HTTP错误处理可单独验证：`uv run pytest -q tests/contracts/test_http_validation.py tests/contracts/test_app_errors.py`，当前19项通过。
