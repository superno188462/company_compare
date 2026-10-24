# COLLECTION-WIRING-1：测试装配补充提案

日期：2026-10-24；状态：用户已确认“确认装配补充，继续测试”，不修改已确认业务行为。构造签名和SQLite适配器已按本稿加入占位，未实现数据库读写或依赖装配逻辑。

编写可执行测试时发现：已批准的类型声明定义了存储Protocol和CollectionService操作，但没有具体持久化适配器类及依赖装配入口。若不补齐，只能测试接口占位或Mock被测服务，不能证明真实缓存复用、重启保留和并发正确性。

拟增加以下可导入骨架，函数体仍只有NotImplementedError，不提前实现：

1. `SqliteCollectionStore`（adapters/collection_sqlite.py），实现已确认CollectionStorePort六个方法，签名不变；构造函数`__init__(self, database_path: Path, *, clock: Callable[[], datetime] = utc_now) -> None`。时钟用于60秒协调租约；原API资料无过期时间。`utc_now() -> datetime`也为未实现骨架。
2. `CollectionService.__init__(self, *, session_service: SessionService, company_data: CompanyDataPort | None, store: CollectionStorePort, scope_id: str, clock: Callable[[], datetime] = utc_now, task_submitter: Callable[[Callable[[], None]], None] | None = None) -> None`。生产组合根装配真实依赖；测试替换外部提供方、时钟和任务执行器，仍执行真实服务与真实临时数据库。
3. `ScreeningService.__init__`增加可选关键字`collection_service: CollectionService | None = None`；缺省保持原流程。非空时接入已确认的公共采集流程。旧方法和原测试不改，新增测试显式注入新服务。
4. `create_app`增加可选关键字`collection_service: CollectionService | None = None`。HTTP专项注入已装配服务；尚未实现前只修改签名，不填装配逻辑。原服务缺省行为保持。

SQLite不需要新增第三方依赖。临时数据库测试与现有正式服务隔离，不触碰用户当前会话或真实API额度。

影响：后端SDD COL-IF-02/DEP-01的装配映射、上述类构造签名、两处已有构造签名的可选增补、骨架检查及类型评审记录。其余输入/输出Schema、前端契约、无TTL/分页/报告隔离规则和原测试断言不变。

本提案确认后只补类型/骨架，再继续完成服务/存储/HTTP可执行契约测试；测试集还需独立评审后才能填充业务实现。当前可先独立编写Schema和提供方适配器测试。
