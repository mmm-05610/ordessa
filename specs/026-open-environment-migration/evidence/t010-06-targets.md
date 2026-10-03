# T010-06 target/binding/generation 四子项 → 钉面映射

| 子项 | 钉面 | 状态 |
| --- | --- | --- |
| 稳定 target/binding/native generation 适用性 | `turn-application-dispatch.test.tsx`（新）generation-stale 反例：isCurrent=false 后 queue/submitTurn 全拒 TARGET_STALE、owner revision 不动、零 wire 调用；既有 TARGET_STALE/M06/fresh-identity 拒绝钉 | 新钉+既有 |
| 跨窗口同 owner | `local-owner-port.test.ts`：跨端口同 registry 第二注册 AUTHORITY_CONFLICT typed-unavailable；缺 wiring 时 createAbsentAgentOwnerPort 全面 unavailable（R7 合同"缺跨窗口实现拒共享写保证"的落实形态：共享 owner 由装配注入单一端口，缺位即拒）；`selection-owner.test.ts` 双 store 同 owner 单真值 | 既有 |
| selected 只投影 | T010-03 后 queued/current 全为 useSyncExternalStore 投影（无 setter）；`picker-model` selectedOptionValue 为纯投影函数；AgentSessions snapshot 的 selectedConnectionId/selectedSessionId 为 owner 侧快照 | 既有 |
| binding 替换旧 queued 操作 stale 且不自动 rebase | glue prepare() 捕获 binding.ref 全程使用（替换不追改）；applyOnSubmit"captured binding is not a new user pick"；bound 模式 reconcile 仅观察（MP-07 从不 apply/retry）；M11 在飞 pick 归下一轮 | 既有 |

复核：`npx vitest run --root plugins/model-provider/chat-contribution` → 119F。
