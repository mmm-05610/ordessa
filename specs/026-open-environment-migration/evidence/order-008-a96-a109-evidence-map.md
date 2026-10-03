# 008-S6 证据映射 — A96–A103/A109 定向正反例（T008-20）

2026-10-04。S/I 层证据由下列真实测试承载（全部实际运行，无 skip/无删断言）；U 层（A108 等
真实 Electron/IME）保持待验，不报 fullDone。

| case | 层 | 成功条件 | 承载测试（真实文件） | 反例点 |
| --- | --- | --- | --- | --- |
| A96 | I | owner 更新后两消费者同快照、未变化引用稳定 | ui-components/tests/f5-state-store.test.ts（identity-stable/deep-freeze/no-op）+ f5-counter/tests/test.mjs（两消费者同引用） | 消费者写嵌套值拒（deep-freeze throws）；reader 无 update 面 |
| A97 | I | 无关字段零通知、批量只见完整快照、重入有界 | f5-state-store.test.ts（updateBatched 单通知）+ f5-counter batch 用例 + selectors 用例 | selector 相等抑制（无每键重置） |
| A98 | I | 卸载退订、旧 dispose 不撤新 owner | ui-components/tests/f5-react-binding.test.tsx（卸载计数/旧代次） | 重复 render 不堆订阅 |
| A99 | I | gap 重同步、撤权停投递 | ui-components/tests/f5-query-tasks.test.ts（projection 帧：resync-required/revoked） | 无订阅者丢弃不 crash（U 切片 5 测试同钉）；buffer 溢出诚实 gap |
| A100 | I | 同 key 共享 read、分页失效有界、代次隔离 | f5-query-tasks.test.ts（合并单飞行/跨授权隔离/LRU 逐出/invalidate） | 非幂等 effectful 拒（QueryEffectMismatchError）；撤权清缓存 |
| A101 | I | A 晚到不覆盖 B、关页只释放等待 | f5-query-tasks.test.ts（stale barrier/cancelWait=cancelled-wait/unknown 保关联） | cancel 不伪称停止（文本断言无 stopped 字样）；unknown 单次尝试 |
| A102 | I | 非 Chat 编辑消费 mask/CAS、dirty 更新保本地 | ui-components/tests/f5-editing-uistorage.test.ts（ABA 双例/冲突保本地/单次尝试） | 秘密 plaintext 拒；迟到成功不清新编辑 |
| A103 | I | fixture 跨会话恢复安全 UI 项、namespace/版本隔离 | f5-editing-uistorage.test.ts（条件写/隔离/未知 schema 拒/migrate 仅向前） | 未知 schema 不覆盖；secret 形状拒存；session-only 显式不许诺恢复 |
| A109 | I | 按钮/菜单/快捷键同源、翻译/图标回退 | workbench/tests/f5-interactions.test.ts（ContextKeyRegistry 同源 evaluate/scope 隔离）+ ui/tests/f5-display-tools.test.ts（可见 key 回退/图标稳定 fallback/高对比） | when 不授执行权（仅展示）；secret 键拒；缺 label 可达性归 A108 GUI |

生命周期/依赖回归：workbench 77 绿（layering 守卫：只经共享载体取 f5）、ui-components 77 绿、
ui 30 绿、typecheck 绿、聚合 44 套件含两 fixture（真实包出口）。

缺项（U 待验，如实）：A108/A110/A111 属 012 真实 GUI/多窗口/重启恢复；A96–A103 的 React
呈现层（Workbench overlay 绑定）在 S6 后由 S5 机制+S2 绑定覆盖，若 A99/A109 需更多真实 UI 面
证据，009 桥面切片补。
