# COLLECTION-TEST-1：契约测试评审包

日期：2026-10-24（Asia/Shanghai）；状态：用户已确认“确认测试，开始实现”；实现完成，当前413项全部通过。主体夹具纠错另获COLLECTION-TEST-FIX-1确认，未改变断言。

已确认依据：COLLECTION-SDD-1 → “确认SDD，进入类型/骨架”；COLLECTION-TYPE-1 → “确认类型和骨架，继续测试”；装配补充COLLECTION-WIRING-1 → “确认装配补充，继续测试”。本次不重新审批这些已确定事项。

## 1. 可执行测试：新增167项

| 文件 | 项数 | 当前结果 | 绑定条款与覆盖 |
| --- | --- | --- | --- |
| [test_collection_schema.py](../../tests/contracts/test_collection_schema.py) | 59 | 59通过 | COL-DATA-01..04、RULE-01：14工具、严格整数/UUID/额外字段、nullable必填、未知总数、无TTL字段、来源/正文/URL、浏览200以上合法、报告200上限、任务终态、9模型必填映射及本地20条分页 |
| [test_collection_adapter.py](../../tests/contracts/test_collection_adapter.py) | 26 | 26通过 | COL-IF-02/04、DEP-01、ERR-01：6司法工具指定第二页、仅所选工具、固定20、最终/未知总数、错页/错主体/重复/超长/矛盾元数据整页拒绝、鉴权/额度/5xx重试边界、安全诊断、非司法完整分页及200上限、评分/联系方式过滤 |
| [test_collection_store.py](../../tests/contracts/test_collection_store.py) | 21 | 21通过 | COL-IF-02/03/06、NFR-01/02/04/06：真实SQLite、跨实例保存、长期无TTL、身份维度隔离、最近成功批次稳定排序、旧批次保留、空结果、真实线程竞争claim、60秒精确边界/接管/迟到提交、修订冲突回滚、StorageError |
| [test_collection_service.py](../../tests/contracts/test_collection_service.py) | 44 | 44通过 | COL-IF-01..06、ERR-01、NFR/RULE：真实服务+SQLite，A/B/C复用、缺失/失败/空的差别、浏览和报告分离、草稿/私人接纳隔离、幂等/冲突/跨页去重及变化、更新失败/新批次、230条浏览、原报告重试范围、3/0剩余容量、互斥、同页两用户只取一次、代次/24h失效、超时、写入/读取失败 |
| [test_collection_http.py](../../tests/contracts/test_collection_http.py) | 17 | 17通过 | COL-IF-01、ERR-01、NFR-02/07：真实路由/服务，422脱敏格式、202任务/终态/幂等，GET不取上游，所有权404、结束410、未确认409、同源与幂等头 |
| 合计 | 167 | 167通过 | 没有skip/xfail，没有断言“抛未实现就是正确行为” |

声明测试使用权威JSON Schema的本地注册表，不复用骨架检查脚本冒充测试。HTTP格式测试的None依赖仅用于不应进入业务的非法输入路径；正常HTTP用例使用真实CollectionService，不Mock被测服务或路由。

[collection_support.py](../../tests/contracts/collection_support.py)仅提供合成提供方、时钟、任务队列及真实对象装配；不实现缓存命中/去重/分页编排。被测存储使用tmp_path下真实数据库，正式数据库/服务不受影响；没有发起真实付费查询。

## 2. 评审前结果与实现记录

评审前完整运行`uv run pytest -q --tb=no`：**314通过、99失败，共413项**。其中原246项全部通过、文件与断言未改；新增68项通过。所有99项失败当时均为实际构造/方法的NotImplementedError，没有导入错误、fixture装配错误或跳过项。

这些失败是实现前的预期红灯，不代表其后所有断言已经验证正确。实现时必须运行每个函数对应测试，若发现测试自身与已锁定SDD不一致，先提交具体纠错评审，不能直接删断言、放宽条件或跳过。

实现后完整运行`uv run pytest -q --tb=short`：413通过，原246项文件与断言不变。Python严格类型检查20文件通过；结构检查93个已实现函数/方法、15个占位（协议和未交付的旧能力）；13个原路由+5个采集路由通过。React类型与生产构建通过。默认装配已启用真实SQLite、单工具分页及折叠浏览。

## 3. 条款覆盖矩阵与专项

| SDD验收/条款 | 自动化定位 | 必须补充的专项 |
| --- | --- | --- |
| COL-AC-01 / DATA-01/02 | schema固定枚举/格式/来源、adapter6工具及非法页 | I05真实第二页；不支持的工具明确失败 |
| COL-AC-02 / IF-03、NFR-01 | store身份/长期保存/空缓存；service第二用户/多年/作用域 | I01跨进程重启；B06原时间展示 |
| COL-AC-03 / DATA-03/04、IF-01/04 | schema任务/分页；adapter错页；service追加/去重/未知/变化；HTTP | B02/03/04/05/17存量/查询按钮及计数 |
| COL-AC-04 / IF-05/06、NFR-04/05 | store线程/租约/迟到；service两用户/幂等/更新/互斥/60秒 | I02真实后台期限；B07/12/13旧工作台与晚到 |
| COL-AC-05 / IF-03/04、RULE-01 | service230条/3或0剩余/原重试/模型结构不变 | B08报告范围与原文；实际模型仍未接入，不声称已做真实生成 |
| COL-AC-06 / ERR-01、NFR-02/07 | HTTP状态/同源/幂等/所有权；service私人接纳/24h/存储故障 | I04数据库/日志安全审计；B09/10/11无权益及官方入口；原手工共享7天规则本批不改、不新增发布实现 |
| COL-AC-07 / COMPAT-01、NFR-06 | store新实例/服务重装配；原246回归不变 | I01真实进程、I03存储资源故障、I06运行配置 |
| COL-FE-DATA/IF/STATE/ERR/NFR/RULE全部 | 共享DTO及HTTP契约+现有TS构建 | [18项浏览器专项B01..18与6项依赖专项I01..06](collection-browser-acceptance.md)，实际结果及未覆盖范围见专项记录 |

前端已实现。采用隔离8001合成后端、真实SQLite和实际页面验证折叠、键盘、360px、分页计数、更新失败保留及跨进程缓存；另以真实32秒延迟验证30秒中止与原幂等键恢复。专项清楚区分已验证项与尚未完成的组合场景，不以构建代替交互。

## 4. 实现顺序（获本包确认后才执行）

1. 逐函数完成UTC时钟及SQLite构造、只读、claim/commit/finish；运行对应持久化/故障测试。
2. 逐函数实现提供方单工具及指定页接口；运行假HTTP测试，必要最小真实核验。
3. 逐函数完成CollectionService和原查询接入，再接HTTP；运行服务/并发/预算/隐私及原回归。
4. 实现共享客户端、折叠组件、加载/更新/官方复核交互；逐项完成浏览器专项。
5. 全量测试、类型、骨架、构建和隔离集成验收。实现期间出现契约缺口先形成受影响条款补充，不边改业务边追认规格。

此顺序不授权批量填充函数，不修改已锁定原测试。原CompanyDataPort.fetch_category保持旧规则供旧测试验证，新流程通过新增端口实现固定20条与报告窗口差异。

评审结论：用户确认本167项断言和专项范围，已逐函数实施。COLLECTION-TEST-FIX-1仅修正新适配器文件主体夹具；断言、页码、条数及所选工具范围不变。当前阶段结果及限制见collection-browser-acceptance.md。
