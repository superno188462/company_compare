# COLLECTION-TYPE-1：类型与骨架评审包

日期：2026-10-24（Asia/Shanghai）；状态：用户已确认类型/骨架。确认依据：“确认类型和骨架，继续测试”。原COLLECTION-1.0行为不变；后续用户明确确认[COLLECTION-WIRING-1装配补充](collection-test-wiring.proposal.md)，已增加构造与SQLite适配器占位。本确认不包含业务实现授权。

## 1. 产出与条款映射

| SDD条款 | 产出 | 本阶段内容 |
| --- | --- | --- |
| COL-DATA-01..04 | [collection-schema.json](../../contracts/collection-schema.json) | 14项工具、8项非司法工具；9个公共模型及其字段/声明式约束；Schema条件约束保留 |
| COL-DATA-02/03 | [生成Python](../../src/company_screening/contracts/generated.py)、[生成TS](../../frontend/src/contracts/generated.ts) | 离线生成ProviderToolSnapshot、ProviderJudicialPage、CollectedRecord、CollectionToolView、CollectionOverview、CollectionRecordsPage、两类命令、CollectionOperationView；不手改生成文件 |
| COL-IF-02 | [collection_storage.py](../../src/company_screening/contracts/collection_storage.py) | 5个服务端模型：缓存身份、批次、页、取数身份、租约及其原时间/版本；不包含TTL、用户材料或诊断 |
| COL-IF-02 | [ports.py](../../src/company_screening/ports.py) | CompanyDataPort新增2个能力；CollectionStorePort新增6个能力；原方法与默认值保留 |
| COL-IF-02 | [collections.py](../../src/company_screening/collections.py) | CollectionService的overview/records/load_page/refresh_tool/operation，全部仅NotImplementedError |
| COL-IF-02 | [tianyan_mcp.py](../../src/company_screening/adapters/tianyan_mcp.py) | 新增两个提供方方法占位；原查询函数体不变 |
| COL-ERR-01 | [errors.py](../../src/company_screening/errors.py) | StorageError、CollectionConflictError异常声明；不提前写映射逻辑 |
| COL-IF-01 | [collection_routes.py](../../backend/collection_routes.py) | 5个独立路由及依赖占位，全部未实现；不挂载到现有app，避免当前用户调用未实现功能 |
| COL-FE-IF-01 | [collection-client.ts](../../frontend/src/api/collection-client.ts) | 5个新增HTTP客户端方法的接口声明；保留原客户端与页面实现 |
| COL-FE-DATA-02 | [collection-props.ts](../../frontend/src/components/collection-props.ts)、[props.ts](../../frontend/src/components/props.ts) | 三组Props及组件声明；CoveragePanel增加可选onSupplement；EvidenceCard仍保留原签名，折叠行为留待实现 |
| COL-DATA-04 | [text-dict.json](../../contracts/text-dict.json) v1.3.0 | 新增collection分组9条已列明固定文案，原键不变 |

公共模型细节：所有字段依SDD必填，nullable明确null；未知总数不默认0；司法上游/展示页大小固定20；已收集数量不受200限制，报告纳入数量仍<=200。Private模型使用原ProviderRecord约束，单页/模式/归属等跨字段业务校验未实现。

## 2. 共同模型的来源与生成

BoundaryErrorInfo、BoundaryFieldIssue、BoundaryProviderRecord、BoundaryOperationHandle是原boundary.py模型的派生Schema/生成声明，字段不是新增契约。生成器每次从原模型导出并检查与浏览Schema完全一致；原边界类仍是它们的字段权威，不能在collection-schema里另改一套。

新生成类和原边界类不是同一个Python运行时类；后续适配器通过受控字段/JSON投影交换，不能把类型名称相似当作可直接互传。此阶段没有提前写转换或校验逻辑。Category、JudicialToolName、QueryDiagnostic、HintCode仍引用原Schema定义。

生成工具只允许已登记本地文件的$ref，禁止联网取Schema；脚本的修改属于开发工具，不是业务实现。跨字段条件保留在权威JSON Schema，Pydantic声明投影不提前加入校验器；实际业务必须在测试评审后实现并通过Schema/业务双层检查。

## 3. 未接入内容与兼容

- 新路由只有可导入的独立router，未include到当前app；现有13个运行路由不变。
- 新CollectionService、提供方方法、存储端口均占位；没有连接或创建数据库，没有发起真实API请求。
- React只新增声明、类型和可选Props；未渲染折叠/分页UI，未调用新增接口；现有页面行为保持。
- 原input-schema.json与output-schema.json完全不变，旧47个生成类AST不变；仅离线开发用GeneratedContractBundle增加可选collection入口。
- 原246项测试文件和断言未修改。新增行为契约测试尚未编写；新功能不能以原测试通过作为已经完成的依据。

## 4. 实际检查结果

| 命令或专项 | 结果 |
| --- | --- |
| uv run python scripts/generate_contracts.py | Python/TS生成成功；Boundary派生声明无漂移 |
| uv run python scripts/check_skeleton.py | 57个原已实现函数；28个未实现函数；18个服务签名、11个端口签名；13个运行路由+5个未挂载新路由；字段/必填/字典/Schema往返通过 |
| uv run mypy | 18个源文件通过 |
| uv run pytest -q | 原246项全部通过；保留既有Starlette/httpx弃用警告 |
| npm --prefix frontend run build | TS检查与Vite生产构建通过 |
| 既有声明比对 | 47个既有生成类AST不变；原输入/输出Schema语义相同；旧测试无差异 |

本阶段没有数据库迁移、服务重启或浏览器功能验收；真实翻页、缓存并发和持久化尚未实现。未修改依赖，uv.lock不变。

## 5. 下一阶段及装配补充

本包已确认，进入绑定COLLECTION-1.0条款的可执行契约测试和覆盖矩阵编写。补充的SqliteCollectionStore构造与六方法、CollectionService构造、utc_now全部未实现；ScreeningService/create_app仅增加可选collection_service签名，不提前接入。补充后mypy20文件和骨架37占位通过。测试结果见[COLLECTION-TEST-1](collection-test-review.md)，类型确认不等于提前批准测试或业务实现。
