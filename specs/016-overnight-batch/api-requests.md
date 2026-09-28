# 016 · api-requests（夜批消费台账）

| AR | 所有者 → 调用方 | 消费面 | 可用性 |
| --- | --- | --- | --- |
| AR-1 | apps/server(core) → PE1/PE2 | C4 admission 消费 authority/evidence DTO | **main 实测**（acp_admission.py:94-140 permits 在案；DTO 对齐归 core 的 INT 项，夜批只交冻结形状） |
| AR-2 | harness(C2) → HK/LSP/SR | `harness.configuration-adapters` 注册 + apply | main 实测可用 |
| AR-3 | harness → HK | hooks slot 投影通路（内容→slot 装配） | **未知**——执行者实测；缺失则登记报回，不改 harness |
| AR-4 | prompts 域 → 015-B/其他 | instruction facet 合并规则 | PX 夜批产出（015-B 已按"缺失则报回"处理，不阻塞） |
| AR-5 | permissions/harness 既有存储 → PE1/PE2 | 规则/审批存储、access-entry/provenance | main/harness 支在案 |

失败反例（通用）：AR-1 缺 DTO 任一冻结字段 → core 无法对齐，报告必须列全字段；
AR-3 通路缺失时 HK 投影降级为"定义就绪、投影待通"，不得绕过 slot 直写 harness
内部文件。
