# Plan：实施与集成顺序

## 模块及所有权

目标域 `plugins/assets/model-provider/` 可包含 server Python 包、轻量 TS contracts、desktop 设置、chat glue、profile glue、`adapters/{pi,codex,claude}`。**目录迁移不等于立即重写**：优先从 `worktrees/plugin-model-provider-impl/plugins/model-provider/** @ 9305563` 评审后移植，记录每个文件来源 SHA；legacy `plugins/server-compat/.../model_configs/**` 做行为 oracle。最终发行包拆分由可独立卸载性决定：core 服务不依赖 Chat/Profile，glue 依赖对应公开契约。Pacthold/Server/Workbench 不加 provider 分支。

## 顺序与停点

0. **T00 对齐**：main vs 旧 worktrees vs Harness/Profile/Chat 实际导出、锁定版本/许可、wire/DB 兼容表，记录缺口。`harness-v2` C2 若仍是文档，先等负责核心的工作树落地并验收；不能用本插件自行私建 registry。核旧 R1 被新裁决替换。
1. 迁 ProviderConfig/校验/安全 probe，完整保留 `providerModels.*` 与磁盘 ID。先让 Compat 六方法退出，产品装配新所有者，禁止双 writer；可用临时集成分支评审，主树不并行写共享清单。
2. Settings 独立装配：无 Chat/Profile 的 CRUD、手动探测、缺席对照。版本冲突/引用保护/秘密零泄漏。
3. C2 三品牌 adapter 与 Harness 应用接缝；Pi/Codex/Claude 逐品牌固定版本受控 E2，不共享成功结论。先基线默认模型，再同 provider 换模型，再跨 provider restart-resume，并验证原生 session ID 不变与 sibling 不动。
4. Profile facet 与 Chat 选择器在真实公开贡献点接线；提交闸门生产接线须覆盖全部 prompt 路径。既有 fake seam 替换为真实同 channel owner；没有接通就报告 `PARTIAL`，不冒充端到端。
5. 产品装配、迁移回放、隔离/崩溃恢复、桌面 GUI 与逐 ID 回归。只有全门绿可宣称三品牌受控原型完成；真实模型 E3 另批授权。

## 跨树合同与所有权

Harness C1/C2/专用 target/readback/restart-resume、Profile facet/apply、ACP session control/submit permit、Chat contribution、products 装配分别由对应所有者实现；本包只定义消费语义与本域适配器。若上游接口不存在，T00 输出精确缺口、对方所有者、最小 DTO 和阻断测试，再继续本域独立部分。不得把 TODO 变成假绿，也不能为赶进度扩展 apps/server 的品牌 if。

单独 worktree 实施，main 根保持 main；共享产品清单/wire 退役在集成 worktree 串行。回滚为恢复产品清单到旧唯一 owner；数据库只做可读向前迁移，不丢配置。执行前记录 old/new 注册方法清单、迁移和引用快照；切换失败仍能按旧 owner 启动，不能留两个进程都写同一张表。
