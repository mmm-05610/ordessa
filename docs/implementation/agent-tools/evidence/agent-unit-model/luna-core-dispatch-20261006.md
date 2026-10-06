# 核心优先与 Luna 派工回执

2026-10-06，用户要求优先完成核心，核心不认识具体 Harness 但能通过公开契约使用；允许多个 Luna 子代理承担编码、验证，主会话指导、接口决策和整合。架构问题面向用户用自然语言说明行为与取舍。

接管 HEAD `26491dd180744d38dec4edb392fa59795ae476fe`。23 个 tracked dirty 文件、+513/-113 为上一执行者配置语义切片；另有 `.env` 未跟踪，不读取、不提交。没有其他活执行者。保留原成果，不 reset/stash/覆盖；已确认配置语义顺序与 AU 合同不重写。

按用户最新分工授权，在原树内明确单文件唯一写者；主会话不独立承担大部分实现。沿 incremental-work-order 管理写权和证据，不另开树、不创建第二队列或第二核心。测试由主会话统一串行启动收集；子代理写测试，但没有自行启动测试/Git的权限。阶段 A 全员只读，现有产品全套基线 terminal 后才开放阶段 B 写权。

| Luna | 阶段 B 唯一候选写域 | 可判定交付 |
| --- | --- | --- |
| luna_core_impl | pacthold/agents 的 configuration、profiles、assembly、management、nodes、lifecycle.py；新增本 evidence 内 test_core_profile_semantics.py | 新清单可原子准备，独立快照权限，同请求不重复作用，遗漏/转换/版本/未知反例不冒绿 |
| luna_wire_impl | apps/server/src/ordessa_server/agent_core_wire.py；新增本 evidence 内 test_core_profile_wire_v3.py | 仅解码转发，来源互斥、applyProfile 按能力广告和派发、具名遗漏错误；不自行 diff |
| luna_core_review | 初始只读；如追加写权仅独立 evidence 测试文件 | 独立审阅上述两切片，验证无品牌依赖；不同 provider 经同一核心，撤销/缺端口仍拒绝 |

共享 schema、public 导出、派工/状态账/Git 由主会话管控；若需代码变更由主会话串行追加给唯一 Luna 写者，其他代理不得顺手修改。各测试须能抓住相应失败正例，缺资源/权限则拒绝或 PARTIAL。不得删除原断言/skip掩盖失败，不调用模型、第三方安装或用户服务。C/P/M 分账。

核查发现（尚不当测试证据）：inline 快照尚未提交就被 assembly 读取；快照存储/权限类与最近裁定不一致；wire 尚未转发临时清单或 applyProfile，遗漏错误缺具名投影。由指定 Luna 修复与补反例，不先写快照绕过原子性，不新增 registry/dispatcher/实际配置缓存。

下一顺序：保留并验证/提交继承切片 → 核心配置缺陷与 PJ 核心反例 → 公开服务接缝 → 独立核心边界审查与多 provider 验证 → 原输入/任务读取接缝等核心剩余项。CLI/Skill/品牌扩展暂不抢先。此文件为执行分工与证据入口，不代替原规格或完成声明。
