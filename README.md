# 企业公开线索筛查

这是一个固定流程的企业公开线索筛查工具，帮助用户核对材料、比较矛盾线索，并了解当前信息能支持什么结论。

## 只看这条主线

输入公司名称 → 人工确认主体 → 查看公开证据 → 自动生成分析 → 手工补充后刷新分析。

即使搜索只有一个候选，也由用户确认。人工补充只有匹配当前主体的材料才能进入分析。官网通过“在新标签页打开官网”按钮供用户核对。

分析重点是：不同材料是否支持同一判断、是否来自同一原始来源、有无反证或其他解释、还缺什么信息。每条结论能追溯到证据；材料不足就说明不足。

## 现在做到哪里

共享API资料库与分页浏览已实现，完整413项测试通过（新增167项，原246项文件及断言不变）。需求/UI、SDD、类型、装配、契约测试及主体夹具纠错均已获用户确认；详见[测试评审与实施记录](specs/common/collection-test-review.md)和[实际验收范围](specs/common/collection-browser-acceptance.md)。

**前端采用 React + TypeScript + Vite，已接通当前后端主线。** 页面会创建或恢复匿名会话，可搜索候选、要求用户点击确认主体、轮询五类查询任务、展示覆盖情况/证据/报告，并保存、清空或提交私有手工草稿。失败类别旁有“重新查询”按钮，只重试该类别，保留已有证据和草稿，查询期间禁止重复点击。“查看原因”可展开已知的失败子接口、HTTP状态、失败环节、相关字段和处理上限；未知信息标为未记录，旧结果需重新查询后才能取得新诊断。提交时核对主体、来源与版本，合法线索才进入证据包，重复请求只接纳一次；官网通过新标签页打开。共享发布和模型重试仍待实现。模型服务尚未接入，因此接纳后的完整结果明确显示报告失败，已经保存的证据保留，不生成合成报告。

线索按类别、工具、单条默认折叠。司法固定六项先各取最多20条；有更多时可对所选工具点击“继续查询下一页20条”，已保存的下一页只读本地，不重复请求上游。初次出现60条只是三个工具各返回20条，不是浏览总上限。页面分别标注已收集条数、上游总数、未查全范围和报告证据包数量；浏览更多材料或主动更新不会偷偷改写报告。报告输入仍限200条及256 KiB。

同公司API资料以SQLite保存，跨用户复用、不自动过期，始终保留原取得时间。新工作台选择最近成功批次；已打开的工作台保持自己的批次。主动更新成功创建新批次，失败保留旧资料。私人草稿、已接纳手工线索、报告、诊断及密钥不进入公共资料库。私人会话、搜索、任务及草稿仍在单进程内存中，重启需重新搜索并确认主体；公共API资料保留。会话闲置24小时失效，不把它当作公共资料的有效期。当前适用于单后端进程；多实例私有会话一致性及完整定时清理仍未交付。

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
| API共享资料库、分页与更新 | [后端规格](specs/backend/collection-cache.spec.md)、[前端规格](specs/frontend/collection-browser.spec.md)、[浏览Schema](contracts/collection-schema.json) |
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

接口文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。当前18项HTTP操作：原13项及5项材料概览/本地分页/司法下一页/单项更新/独立任务轮询。确认主体后后台依次取得五类资料，成功缓存优先复用，轮询在终态返回完整payload。搜索及新取资料要求服务端配置有效的 `TYC_AUTHORIZATION`。非司法工具仍要求完整取得；司法允许明确标范围的部分结果。真实接口已最小核实司法案件第2页取得20条、上游总数5564；其余五项第二页仅经过合成契约测试，不能保证每家企业或每项权限可用。

确定无权益的数据项会显示说明，并提供官方复核入口、复制地址和手工补充；未知403不猜测是余额还是套餐。不购买SVIP仍可人工核对股权公示、中登网担保及执行线索；土地/房屋登记按属地条件办理，不能承诺查全。应用不抓取、读取或代理官网。

## 资料保存与配置

默认数据库为项目内 `.local/collections.sqlite3`，目录已被Git忽略。可在服务端配置 `COLLECTION_DATABASE_PATH` 指向可写的持久目录；首次启动自动建立新表，不迁移或删除旧会话。公共缓存键区分主体、工具、分页参数、规范化版本及凭据作用域；更换Key会隔离缓存，同一Key权益范围变化可递增 `COLLECTION_SCOPE_VERSION`。实际Key不写入数据库。

需要备份或更改路径时先停止后端，再复制完整数据库；保留原文件便于恢复。回滚代码不自动删除缓存，旧版本不会读取新增资料库。存储故障明确报错，更新失败不以空结果替换旧资料；无自动过期不等于内容实时准确，使用前核对标注时间并按需更新。

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

`contracts/` 中输入/输出 JSON Schema 定义既有报告字段，新增 `collection-schema.json` 定义浏览字段；生成类型由 `uv run python scripts/generate_contracts.py` 离线更新，不手改 `generated.py` 或 `generated.ts`。浏览Schema中的Boundary前缀定义是既有边界模型的派生投影，生成器检查与原类型一致，不能独立改字段。共享行为语义见 [global_schema.md](specs/common/global_schema.md)。

上述命令检查契约结构与类型，不能证明全流程可用。契约测试单独执行：`uv run pytest -q --tb=short`，当前413项通过，无skip/xfail，保留一项既有Starlette/httpx弃用警告。仅运行本批：`uv run pytest -q tests/contracts/test_collection_schema.py tests/contracts/test_collection_adapter.py tests/contracts/test_collection_store.py tests/contracts/test_collection_service.py tests/contracts/test_collection_http.py`，167项通过。测试使用临时数据库及合成提供方，不消耗真实查询额度；真实API、真实时钟和浏览器专项另见验收记录。
