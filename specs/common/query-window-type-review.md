# WINDOW-TYPE-1 类型与骨架评审包

日期：2026-10-24。依据：[QUERY-WINDOW-1.0](../backend/query-bounded-results.spec.md)，用户已明确批准局部UI/SDD。本类型包已经确认，不声称司法业务已完成。

评审记录：用户明确选择“确认类型，继续编写测试（推荐）”，本类型包已通过；WINDOW-TEST-1随后获确认并完成实现。类型中说明的1项兼容回归已修复，原断言未修改。以下阶段记录保留类型评审时的初始状态。

## 变更范围

| 产物 | 内容 |
| --- | --- |
| input-schema.json v1.1 | CategoryResult新增partial；ToolCoverage的5字段、司法6工具白名单、子范围可选数组默认[]；partial要求实际查询时间 |
| output-schema.json v1.2 | 复用输入覆盖类型，五个顶层字段不变；诊断不加入输入 |
| Python/TS生成类型 | 从两个本地权威Schema生成，未手改生成文件；JudicialToolName与诊断工具名枚举分别命名 |
| ProviderCategoryBatch | 兼容缺省completeness=complete、tool_coverage=[]；error_code/diagnostic均为可选服务端传递字段，对应已批准的部分失败诊断语义 |
| CompanyDataPort/TianyanMcpAdapter | fetch_category新增keyword-only record_limit=200；原调用仍合法，司法执行方法只留NotImplementedError骨架 |
| CoveragePanel | 继续接收QueryCoverage，不新增HTTP；回调契约说明error/partial重查同一范围；字典声明“部分取得” |
| 结构检查 | 保留原13路由/13服务签名检查，并新增可选关键字默认值与ToolCoverage字段映射核对 |

## 阶段验证与已知未实现项

严格类型检查15文件、React类型与生产构建、骨架结构检查均通过（56个已实现函数、8个占位）。司法窗口方法仅有docstring与NotImplementedError，没有提前填业务。

既有205项测试中204项通过，1项发现新增可选tool_coverage默认[]参与序列化后，原比较逻辑把“字段省略”和“空数组”误判为覆盖变化，导致仅诊断变化也递增分析版本。原测试与断言不修改；必须在后续实现阶段对覆盖作等值规范化，恢复该测试。不是以类型检查通过代替行为验收。

工商来源定位修复已经在真实接口下取得3条唯一记录；46项原适配器/诊断测试通过。该修复不依赖司法窗口业务。

## 待下一阶段准备

类型评审通过后，编写绑定WINDOW条款的适配器、服务、HTTP/Schema用例，提交具体测试代码与覆盖矩阵。需要调整旧测试替身的fetch_category签名以接收record_limit；需要定向更新原司法完整分页预期，原处罚等非司法200条拒绝断言不变。上述测试调整先形成明确清单并评审，不为使结果变绿而删测试。

类型阶段未重启8000后端。实现和全部验证完成后已重启正式后端并刷新工作台，详情见SDD验收记录。
