# 企业公开线索筛查

这是一个固定流程的企业公开线索筛查工具，帮助用户核对材料、比较矛盾线索，并了解当前信息能支持什么结论。

## 只看这条主线

输入公司名称 → 人工确认主体 → 查看公开证据 → 自动生成分析 → 手工补充后刷新分析。

即使搜索只有一个候选，也由用户确认。人工补充只有匹配当前主体的材料才能进入分析。官网通过“在新标签页打开官网”按钮供用户核对。

分析重点是：不同材料是否支持同一判断、是否来自同一原始来源、有无反证或其他解释、还缺什么信息。每条结论能追溯到证据；材料不足就说明不足。

## 现在做到哪里

**前端采用 React + TypeScript + Vite，已接通当前后端主线。** 页面会创建或恢复匿名会话，可搜索候选、要求用户点击确认主体、轮询五类查询任务、展示覆盖情况/证据/报告，并保存、清空或提交私有手工草稿。失败类别旁有“重新查询”按钮，只重试该类别，保留已有证据和草稿，查询期间禁止重复点击。“查看原因”可展开已知的失败子接口、HTTP状态、失败环节、相关字段和处理上限；未知信息标为未记录，旧结果需重新查询后才能取得新诊断。提交时核对主体、来源与版本，合法线索才进入证据包，重复请求只接纳一次；官网通过新标签页打开。共享发布和模型重试仍待实现。模型服务尚未接入，因此接纳后的完整结果明确显示报告失败，已经保存的证据保留，不生成合成报告。

已实现范围的246项契约用例全部通过；本批41项司法窗口用例及对应SDD/类型已获用户分别确认，明细见[验收场景](tests/test-cases.md)。股东多来源同值ID已修复；司法固定六项各取首批最多20条，有数据但未查全时显示“部分取得”，展开“查看取得范围”可核对每项接纳数、上游总数及剩余情况。重查同一范围，不自动追加下一页或跑完数千条。诊断不保存上游原文、凭据或企业正文，不进入LLM证据包；无需新密钥或新增依赖。当前会话、搜索结果、任务状态、草稿、诊断和幂等记录只保存在单进程内存中，重启会丢失，持久化、自动清理和多实例一致性尚未完成。

天眼查接入采用官方 MCP Shared Core，不使用旧版搜索 URL。把 `.env.example` 复制为 `.env`，在 `TYC_AUTHORIZATION` 中填写天眼 AI 页面生成的 MCP API Key。`.env` 已被 Git 忽略，密钥不得写入前端、日志、测试或提交记录。

## 文件怎么找

日常从本页开始；需要修改哪部分，再打开对应材料。

| 要看什么 | 入口 |
| --- | --- |
| 企业交叉分析方法 | [分析规则](specs/analysis/skill.md)、[模型提示词](specs/analysis/llm-system-prompt.txt) |
| Skill所需信息有哪些API | [API覆盖核对（2026-10-24）](specs/research/api-coverage.md) |
| 产品范围与页面流程 | [需求](specs/common/prd.md)、[页面说明](specs/common/ui_notes.md) |
| 模型输入、页面输出和固定文案 | [输入](contracts/input-schema.json)、[输出](contracts/output-schema.json)、[文案](contracts/text-dict.json) |
| 开发时核对接口与约束 | [后端规格](specs/backend/screening.spec.md)、[前端规格](specs/frontend/workspace.spec.md) |
| 查询失败原因字段与安全边界 | [诊断规格DIAG-1.0](specs/backend/query-diagnostics.spec.md) |
| 司法首批结果与会员/官网替代途径 | [司法窗口规格](specs/backend/query-bounded-results.spec.md)、[MCP实时核验与官方复核入口](specs/research/mcp-live-audit.md) |
| 验收与当前骨架状态 | [验收场景](tests/test-cases.md)、[骨架检查记录](specs/common/skeleton-review.md) |

代码目录：

```text
src/company_screening/   企业筛查业务：模型、服务、外部依赖接口
backend/                 HTTP 接口与应用装配
frontend/src/            React 工作台、组件契约、状态与同源 API Client
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

先按下节启动后端，再打开终端显示的前端地址（默认 `http://127.0.0.1:5173`）。Vite 将同源 `/api` 请求转发到 `http://127.0.0.1:8000`；页面入口为 `frontend/src/App.tsx`。若后端或天眼查上游不可用，页面保留用户输入并显示固定错误文案，不生成候选兜底。

生产构建使用 `npm --prefix frontend run build`，产物位于 `frontend/dist/`；`npm --prefix frontend run preview` 可本地预览构建结果。部署目录为 `dist/`，前端不放置天眼查或模型密钥。

## 启动后端开发服务

```powershell
uv sync --locked
uv run uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8000
```

接口文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。当前可查看13个HTTP接口契约；会话、候选搜索、人工确认和 `GET /api/v1/sessions/{sid}/operations/{opid}` 已可调用。确认后后台依次执行 `basic / abnormal / penalty / judicial / asset`，轮询只在终态返回完整 payload。搜索和详情查询要求服务端 `.env` 配置有效的 `TYC_AUTHORIZATION`。除司法窗口外，各类别仍要求固定子工具和分页完整；司法允许明确标注的有界部分结果，不使用合成数据兜底。2026-10-24当前Key被实时目录识别为VIP，真实工商验证取得3条，司法首批取得60条（案件20/5564、文书20/439、公告20/330），只能说明该次样例成功，不保证所有公司/工具覆盖。资产此前403不能改写为无记录；不购买SVIP时，可在工作台官方入口人工复核股权公示、中登网动产担保及执行线索，再手工录入。土地/房屋登记按属地查询条件办理，不能承诺公开查全。

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

上述命令检查契约结构与类型，不能证明全流程可用。契约测试单独执行：`uv run python -X utf8 -m pytest -q --tb=line`，当前246项通过。司法窗口41项可运行 `uv run pytest -q tests/contracts/test_query_window_adapter.py tests/contracts/test_query_window_service.py`。诊断测试单独运行：`uv run pytest -q tests/contracts/test_query_diagnostics_adapter.py tests/contracts/test_query_diagnostics_service.py`，当前50项通过。重试测试单独运行：`uv run pytest -q tests/contracts/test_query_retry.py`，当前17项通过。接纳测试单独运行：`uv run pytest -q tests/contracts/test_submission_service.py tests/contracts/test_submission_http.py`，当前30项通过。天眼查适配器可单独验证：`uv run pytest -q tests/contracts/test_tianyan_mcp_adapter.py`，当前16项通过；它使用假 HTTP 传输，不消耗真实查询额度。会话到任务终态切片可运行：`uv run pytest -q tests/contracts/test_session_http.py tests/contracts/test_search_service.py tests/contracts/test_search_http.py tests/contracts/test_confirm_service.py tests/contracts/test_confirm_http.py tests/contracts/test_operation_service.py tests/contracts/test_operation_http.py tests/contracts/test_query_operation.py`，当前26项通过。草稿切片可运行：`uv run pytest -q tests/contracts/test_draft_service.py tests/contracts/test_draft_http.py`，当前7项通过。
