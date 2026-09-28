# Verification checklist：反例、证据和完成门

状态：待实施；下面均是**预期门禁**，不是已执行结果。用与已集成主线同一个基线锁定真实红 ID，不能只比总数或调整测试让新增红消失。

| FR | 任务 | 必有正例 + 反例 | 层级 |
| --- | --- | --- | --- |
| FR-01,03,10 | T01,T08 | Profile allow 在管理员 deny 之下仍 deny；旧 last-match 只当用户意图迁移，迁移歧义不得 silently allow | L1+迁移 |
| FR-02,04 | T02,T03,T07 | ACP 实际工具执行前 ask/deny；缺 authorizer、未知工具、伪造 requestId、跨 session/execution、旧 policy revision 零副作用 | L1+L2 |
| FR-04,09 | T02,T07 | 同决定重放幂等、相反决定拒绝、执行终结审批失效；断连/超时/native receipt 未知不转 allow、不重做工具 | L2 |
| FR-05,06 | T04,T05 | Codex/Claude 原生配置受控写入/回读/行为探针；Pi 缺 sandbox extension 直接 unsupported；Bash-only 无法满足“所有工具隔离” | L1+L2 |
| FR-06,07 | T05,T07 | A/B 同品牌会话异配置不串；运行中 Profile 切换等下一用户输入；提交中管理员上限收紧导致重新拒绝 | L2 |
| FR-08 | T06 | 无业务 UI 仍拒绝；卸载隐藏配置项但数据不丢；晚到保存/审批点击不能落到新 scope | UI+L2 |
| FR-09 | T08,T09 | 权限服务或 sandbox adapter 失效报稳定诊断；错误不写秘密；卸载 busy 与恢复后重验 | L1+L2 |

## 额外核心边界门

1. `apps/server`, `packages/pacthold`, `packages/workbench` 的业务名导入为 0；功能变更都在对应插件及公开契约，产品仅装配。
2. 安装 Permissions 不要求 Sandbox，安装 Sandbox 不要求 Permissions；Profile/Chat 不被任一域变为硬依赖。可在仅装核心包环境正常启动裸宿主。
3. 同一个原生配置字段声明被两个 adapter 写入时组合期拒绝；审批的 authorizer 与 native owner 不能双路竞争。
4. 管理员上限/工具类别缺证据时 fail closed；默认无新增策略的既有原生行为不能被误记为“Ordessa 已强制审核”。
5. 运行中 adapter 卸载须 busy/deferred；批准、写文件和消息发送各自证明，不能用一条绿断言代替三条。
6. 成功/拒绝/未知为不同结果；验证覆盖不确定时显示 unknown 且禁止受约束的副作用。常见反例：UI 点击允许但后端失联、Pi extension 加载失败、Claude Bash-only 沙盒被要求罩 MCP、Codex 管理禁用 danger-full-access。
7. 受控测试可用假 peer/临时目录/无模型协议回环；不得真模型花费或读取用户 `~/.codex`/`~/.claude`/`~/.pi` 数据。原始 stdout/junit/版本 pin 证据落在实施批次允许的审计位置，敏感内容脱敏。

## 交付矩阵

每个品牌 × 权限审批、原生 sandbox 各一行：官网证据、固定 pin 源码、受控测试 ID、当前产品 L2/L3、支持工具集合、OS、scope、失败语义。只读官方文档 = D，不自动升级 L2。若当前 ACP 链不支持某种 pre-effect 请求，标 **not yet supported** 并阻断此策略的用户选项，不把取消或补救说成执行前授权。
