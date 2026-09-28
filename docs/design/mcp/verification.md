# Verification：反例先红，证据逐级上报

## FR → 任务 → 门禁

| FR | 任务 | 验收门 |
| --- | --- | --- |
| FR-01 | T01 | V01 定义与不可变版本/旧数据互证 |
| FR-02 | T03,T10 | V03 probe 边界；V10 实际连接/catalog 分级 |
| FR-03 | T02 | V02 作用域及授权差分 |
| FR-04 | T02,T04,T05 | V02 toolSelection、V04/V05 原生/受管 catalog 漂移 |
| FR-05,FR-06 | T04,T05,T10 | V04/V05 双会话唯一 owner、V10 关闭/重试 |
| FR-07 | T02,T08 | V02 Profile 引用、V08 卸载缺席 |
| FR-08 | T07 | V07 明文/轮换/日志扫描 |
| FR-09 | T06,T10 | V06 最终权限/无人值守负例、V10 生产路径不可绕过 |
| FR-10 | T03,T04,T05,T10 | V03/V04/V05 故障注入、V10 unknown/reconcile |
| FR-11 | T08 | V08 UI 状态/草稿 |
| FR-12 | T01,T09 | V01/V09 迁移与回滚 |

## 必跑正反例

1. 保存 stdio/HTTP 定义不 spawn、不联网、不授予工具；未经批准的新 revision 不改变有效快照。反例：普通字符串伪装 secret、超长 URL、相对可执行路径、未知 transport 在副作用前拒绝。
2. 项目禁用覆盖默认启用，Profile 显式启用已批准修订；会话 A 临时禁用不反写 Profile，B 不受影响。反例：B 的 principal/project/sessionRef 冒领 A 的 lease 或读其 catalog 必拒绝。
3. 两个会话同一个 server 定义但凭据/工具子集不同：独立 client/process/config generation、tools/list 来源正确；A 关闭后 B 可继续，A 的资源/secret 不留存。反例：同 URL 或名字促成无授权池化/两 lane 双启动时类型化拒绝。
4. native lane 对 Codex/Claude 额外用户/项目/plugin MCP 来源进行只读发现：如无法排除或限制影响，不能声称受管集合精确。反例：文件投影成功但运行时未装载、原生同名覆盖、换配置后新建空会话，都不能标 confirmed。
5. Pi managed lane 的 tools/list 变化要使旧 catalogDigest 失效；新增工具即使已发现也不可未经批准调用。反例：Pi extension 直接连 MCP 或携凭据绕过代理，门禁必须抓到。
6. 模型已看见工具但权限拒绝，`tools/call` 不到达服务器；无人值守仅有界预授权可执行。反例：无审批 UI、未知副作用、过期规则、工具名/schema 变化均不可默认放行。
7. stdio probe 超时、异常/大帧、manager 崩溃与 in-flight 调用未知：无孤儿进程/双 lease；无法确认副作用时返回 unknown、先 reconcile，不自动重试工具调用或用户 prompt。
8. 凭据轮换或撤销后旧 plan stale，所有持久数据库、日志、桌面事件、构建产物扫描无明文；probe 无凭据只证明有限握手。
9. 卸载 UI provider 后 Settings/Profile 区消失但定义/选择不删；卸载 backend 有活 lease 时 busy 或可信 drain；故障 cleanup 不遮蔽原异常。

## 证据级别与完成口径

`L0 schema/解析` → `L1 固定版本文件/配置编译` → `L2 受控 MCP fake server initialize + tools/list` → `L3 同一会话 ACP/extension/原生装载、受限工具调用与拒绝、双会话隔离` → `L4 授权真实外部 MCP 服务`。本批无需 L4，也不能把 L2 称为真实外部服务已通过。Codex/Claude/Pi 各至少一个 lane 达 L3 且 V06 权限门在生产路径钉住，才称首版三品牌受控完成；某格只有 L1/L2 则列未完成。真实服务若后续另批开展，需用户明确授权服务、账户、数据和可能费用。

报告需写 command/环境隔离、目标版本/SHA、退出码、JUnit/失败 ID、资源/进程泄漏观测、敏感值扫描、未测项。已有红账本以项目 `docs/known-issues.md` 和落盘基线为准，禁止 skip/删除断言造绿。V00 的接口差分与 V09 的迁移互证不得被任一模拟端口测试替代。
