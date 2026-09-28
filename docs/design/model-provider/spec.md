# Specification：Provider/Model 业务域

## 用户故事与范围

US1：用户按 Harness 浏览已登录配置与自建供应商，保存连接、查看模型、手动探测；保存、可达、当前会话可选分开表达。US2：会话的 Harness 已固定；用户可在下一条输入前切其 Provider/Model，即便需要受控进程替换，也继续**同一原生会话**。US3：Profile 可保存默认选择；会话改模型仅覆盖该原子 item，不反写 Profile；Profile 其他字段继续跟随其最新修订；成功切 Profile 清除所有旧会话覆盖。US4：不安装本插件时原生默认模型 Chat 正常；卸载保留 Provider 数据。

## 功能要求

| ID | 需求 |
| --- | --- |
| MP-01 | 恒定身份 `(serverInstanceId,harnessId,providerConfigId,modelId)`；同名不同 provider/Server 不合并。已建会话不可换 Harness。 |
| MP-02 | ProviderConfig 保存 endpoint、协议、认证**引用**、品牌特有非秘密参数和版本；现有登录来源与用户配置在同一目录，只标只读/可编辑，不造“原生供应商”类别。 |
| MP-03 | 模型目录带来源、能力声明、观察时间和可用性证据。未知事实保持 unknown；目录查询失败不得当作空列表。 |
| MP-04 | 保存/探测/可选/待下轮/已生效/拒绝/未知结果七态不混同；页面渲染不自动探测。 |
| MP-05 | 用户更改 Provider/Model 仅排队到下一次输入；当前输出不停。提交闸门先读 Profile 最新版本、叠加本会话**按 item**覆盖、绑定配置修订并 plan/apply/verify，再发送原 prompt **一次**。 |
| MP-06 | 需重启时 Harness 持有实例级配置 generation 与原生 session id，关闭/重启/`resume`/观察均成功才放行；不允许 `session/new` 冒充。一个会话的重配不得改 sibling 或共享 HOME。 |
| MP-07 | 失败：草稿不丢、零 prompt、旧有效事实不撒谎；响应丢失/结果不可判为 unknown 并禁止自动重试/重复发消息，须 reconcile。 |
| MP-08 | 配置编辑 CAS + 幂等；活动 Profile/会话引用归档保护；插件缺席时数据保留，当前自定义选择下一轮 fail closed。 |
| MP-09 | Settings 独立可用；可选贡献 Profile editor、Profile settings、Chat composer 选择器。后端不得依赖这些 UI 才能管理目录。 |
| MP-10 | 秘密只保存 secret reference，解析仅在 Harness 受控应用/单次探测时；普通 wire、日志、UI、Profile、TurnFact 均不含明文。 |
| MP-11 | 版本化品牌适配器 `harness.configuration-adapters` C2 由本域注册，Harness 独占配置应用/实例/受限控制、readback；不绕过现有 ACP owner。 |
| MP-12 | `providerModels.*` 外部 wire 及磁盘标识迁移保真、单一注册所有者；旧 compat 方法退出后新插件才启用。 |

## 明确不做

不实现通用模型网关、协议转换、自动故障转移或账号接管；不把认证材料复制进 Profile；不做跨 Harness 会话切换；不构建新的 sandbox 依赖，也不以 `CLAUDE_CONFIG_DIR`/`CODEX_HOME` 本身冒充安全 sandbox；不修改 Pacthold/Server/Workbench 以塞品牌 if。推理强度、预算等可扩展字段按独立 facet/item 与模型能力验证，首版不伪装所有模型都有相同参数。

## 已改变的产品裁决

旧稿 R1 的“既有会话不能安全应用就直接拒绝且不自动重启”现在改为：**先按 C2 评估 session-local/reload/restart-resume；有同一 session resume 与隔离/readback 证据时允许受控重启**。这不是用户新开会话。证据不足仍拒绝，拒绝不得退回旧 endpoint 或暗发默认模型。任何正在输出的 turn 都不被配置选择打断。
