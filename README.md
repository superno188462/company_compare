# 企业公开线索筛查

这是一个固定流程的企业公开线索筛查工具，帮助用户核对材料、比较矛盾线索，并了解当前信息能支持什么结论。

## 只看这条主线

输入公司名称 → 人工确认主体 → 查看公开证据 → 自动生成分析 → 手工补充后刷新分析。

即使搜索只有一个候选，也由用户确认。人工补充只有匹配当前主体的材料才能进入分析。官网通过“在新标签页打开官网”按钮供用户核对。

分析重点是：不同材料是否支持同一判断、是否来自同一原始来源、有无反证或其他解释、还缺什么信息。每条结论能追溯到证据；材料不足就说明不足。

## 现在做到哪里

**前端采用 React + TypeScript + Vite，已能启动工作台外壳。** 页面提供布局预览与官网外链；搜索、证据处理和报告生成尚未接入页面。后端已经接通匿名签名 Cookie、会话管理、天眼查 MCP 候选搜索、人工确认主体、五类串行查询编排、详情适配、任务轮询，以及手工线索草稿保存和清空。查询结果会按类别记录成功、空或失败，部分失败不会冒充全空；草稿尚未接纳为证据，模型服务尚未实现。

首批50个契约用例经用户确认后开始逐函数实现；补充HTTP、Cookie会话、搜索、人工确认、查询任务、天眼查适配器和草稿用例后，当前108项全部通过。明细见[验收场景](tests/test-cases.md)。当前会话、搜索结果、任务状态、草稿和幂等记录只保存在单进程内存中，重启会丢失，持久化、自动清理和多实例一致性尚未完成。

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

接口文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。当前可查看13个HTTP接口契约；会话、候选搜索、人工确认和 `GET /api/v1/sessions/{sid}/operations/{opid}` 已可调用。确认后后台依次执行 `basic / abnormal / penalty / judicial / asset`，轮询只在终态返回完整 payload。搜索和详情查询要求服务端 `.env` 配置有效的 `TYC_AUTHORIZATION`。详情适配器按固定子工具清单完整分页；同类任一子查询失败时整类报错，不返回部分记录，也不会使用合成数据兜底。当前本机Key实测只有工商登记 L1 权限，股东、处罚、异常、司法、资产等已探测的 L2 工具返回无权限，因此按现有严格范围运行时五类都会记录 `UPSTREAM_AUTH`；需要在天眼查侧开通相应明细工具后才能取得完整类别证据。

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

上述命令检查契约结构与类型，不能证明全流程可用。契约测试单独执行：`uv run python -X utf8 -m pytest -q --tb=line`，当前108项通过。天眼查适配器可单独验证：`uv run pytest -q tests/contracts/test_tianyan_mcp_adapter.py`，当前16项通过；它使用假 HTTP 传输，不消耗真实查询额度。会话到任务终态切片可运行：`uv run pytest -q tests/contracts/test_session_http.py tests/contracts/test_search_service.py tests/contracts/test_search_http.py tests/contracts/test_confirm_service.py tests/contracts/test_confirm_http.py tests/contracts/test_operation_service.py tests/contracts/test_operation_http.py tests/contracts/test_query_operation.py`，当前26项通过。草稿切片可运行：`uv run pytest -q tests/contracts/test_draft_service.py tests/contracts/test_draft_http.py`，当前7项通过。
