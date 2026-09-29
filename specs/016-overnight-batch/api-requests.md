# 016 · api-requests（夜批消费台账）

| AR | 所有者 → 调用方 | 消费面 | 可用性 |
| --- | --- | --- | --- |
| AR-1 | apps/server(core) → PE1/PE2 | C4 admission 消费 authority/evidence DTO | **main 实测**（acp_admission.py:94-140 permits 在案；DTO 对齐归 core 的 INT 项，夜批只交冻结形状） |
| AR-2 | harness(C2) → EXT/LSP | `harness.configuration-adapters` 注册 + apply | main 实测可用 |
| AR-3 | harness → EXT | hooks slot 投影通路（内容→slot 装配） | **实测（EXT 016，两半）**：①注册面可用（AR-2 同点，adapter 已按 v1 构造）；②运行时 **target 供给缺失**——`hooks_target`/`hooks_key` 仅被 registry 解析（registry/schema.py:90-104），`plugins/harness/src` 内零消费、无 hooks target 供给；③**原生 hook 条目值 schema 在库不完整**（source-index.json:196-203 codex 仅键族无叶、:552 claude 仅裸键）。→ 按预案降级「定义就绪、投影待通」：compile 产出类型化拒绝，不猜 schema、不越界改 harness。待办归 harness 侧：describe_targets 供给 hooks file target + 钉版源码级 schema 核读 |
| AR-4 | prompts 域 → 015-B/其他 | instruction facet 合并规则 | PX 夜批产出（015-B 已按"缺失则报回"处理，不阻塞） |
| AR-5 | permissions/harness 既有存储 → PE1/PE2 | 规则/审批存储、access-entry/provenance | main/harness 支在案 |
| AR-6 | harness → PX(prompts) | instruction slot 投影通路（registry 声明 + runtime target 供给） | **实测（PX 016）**：registry 只声明 `instruction` slot、**无任何 target**——registry/schema.py:64 无 instruction_target/instruction_key 字段，harnesses.toml 零条 instruction target 声明（对比 skill_target/mcp_target/hooks_target 均在）；追加/替换路线为 vendor-doc（docs/design/prompts/harness-adapters.md §2）。→ 三品牌 adapter 按「定义就绪、投影待通」交付：compile 类型化拒绝，assess 永不高估为 compile 兑现不了的 status。待办归 harness 侧：registry 增设 instruction target 声明 + 钉版源码级路线核读（pi 加载器/codex 桥传递/claude ACP adapter options 面） |

失败反例（通用）：AR-1 缺 DTO 任一冻结字段 → core 无法对齐，报告必须列全字段；
AR-3 通路缺失时 HK 投影降级为"定义就绪、投影待通"，不得绕过 slot 直写 harness
内部文件。AR-6 同口径：无 registry 声明即无 claim，不得向未声明 target 写入。
