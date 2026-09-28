# 派单简报 — P-B Server 运行时与接缝

**worktree**: `worktrees/013-b-server-runtime`　**分支**: `codex/013-b-server-runtime`
**日期**: 2026-09-28　**主责契约**: C-01 / C-02 / C-03 / C-04(Py)

---

## 1. 你的目标（一句话）

把 Server 侧的"数据根、进程生命周期、wire 传输口"补成**可交付的接缝**，让 Desktop 宿主能零手填地拉起 Server、让插件能安全地调 wire 方法。

> 关键背景：`plugins/connectors/ordessa/src/target.ts` 的拒绝语义已经把责任写死——*"the desktop host must pass the loopback origin of the Server it started"*。**接口已冻结，缺的只是实现。**

## 2. 只读输入（先读，不改）

```text
specs/013-desktop-product/
├── spec.md                  FR-020..033 / FR-050..051 / FR-013
├── plan.md                  你的写入面与纪律
├── data-model.md            数据根布局与实体
├── contracts/
│   ├── README.md            全局语义（三态/缺席/脱敏/边界/证据）必读
│   ├── C-01-data-root.md                ★ 你定义并实现
│   ├── C-02-launch-handoff.md           ★ 你定义并实现
│   ├── C-03-wire-port.md                ★ 你定义并实现
│   ├── C-04-logging.md                  ★ 你实现 Python 侧（TS 侧归 P-A）
│   └── C-08-harness-availability.md     你**只读**（类型已归 P-A，实现留待插件线）
└── tasks.md                 PB-01 … PB-14
```

也读：`docs/architecture.md`、`docs/baseline.md`、`.specify/memory/constitution.md`。
**必看既有实现**：`apps/server/src/ordessa_server/bootstrap/runtime.py::_ensure_token`、`transport/http/app.py`（`/live`、`/wire/v1/{method}`、Bearer）、`plugins/connectors/ordessa/src/target.ts`、`plugins/connectors/acp/src/native.ts`。

## 3. 写入面（越界即违规）

```text
✅ 可写
├── apps/server/**
├── packages/server-plugin-api/**
├── packages/desktop-platform/server-bridge/**    ★ 新包（C-01/02/03 的 TS 实现）
└── specs/013-desktop-product/dispatch/P-B-report.md   （你的报告）

❌ 禁写
├── specs/013-desktop-product/contracts/**   （冻结）
├── apps/desktop/**、packages/workbench/**   （归 P-A）
├── packages/desktop-platform/{contracts,ui,ui-components,extension-*,native-bridge}/**（归 P-A）
├── plugins/**（**全部只读**，013 零插件改动）
├── packaging/**、scripts/**、tooling/**     （归 P-C）
├── 根 package.json / package-lock.json      （归 P-C）
└── 其他 worktree
```

> `packages/desktop-platform/server-bridge` 是**新包**，只属你；它与 P-A 的 `contracts` 单向依赖（你 → 他）。

## 4. 任务清单

见 [tasks.md](../tasks.md) **PB-01 … PB-14**，按阶段 1→3 顺序。关键顺序约束：

```text
PB-01..06  数据根（C-01）        ← 最先：其他都建立在数据根规范上
  ├─ PB-07..10  生命周期（C-02）   server-bridge 新包
  ├─ PB-11..12  wire 口（C-03）
  └─ PB-13..14  日志 Python 侧（同构 + 一致性）
```

## 5. 与其他包的接口（唯一耦合点）

- **P-A 消费你的 `@ordessa/server-bridge`**。请尽早把**包骨架 + 类型导出**立起来（哪怕实现还是 TODO），让 P-A 能编译。
- P-A 会用受控 fixture 先行开发；你交付真实现后由主会话统一切换复跑。
- 契约已冻结，**只消费类型**，不改定义。

## 6. 必须抓到的反例（先红后绿，逐条留档）

| 项 | 反例 |
| --- | --- |
| 数据根 | 符号链接 → **读取前**拒绝；`chmod 0500` → 拒绝；他进程持锁 → `DATA_ROOT_LOCKED`（**不**报磁盘错误） |
| 数据根 | 二次启动 → 复用且 `secrets/http-token` 字节**不变** |
| 一致性 | `ORDESSA_DATA_ROOT` 覆盖 → **两入口一致**；布局常量逐字相同 |
| 旧根 | 无迁移提供者 → 拒绝且原 DB 字节**不变**（金丝雀比对） |
| 生命周期 | 缺 `bin/acp` → **早期** `BUNDLED_RUNTIME_MISSING`，不进半可用 |
| 生命周期 | 子进程 3 秒即退 → `SERVER_EXITED_EARLY`（附退出码 + 日志尾部） |
| 生命周期 | 宿主退出 → **只**杀自己 spawn 的 pid；无关进程存活 |
| wire | 宿主未起 → `Unknown/host-not-ready`；传输中断 → `Unknown/result-unknown` 且**不**自动重发 |
| wire | 无产品装配 → `AbsentWirePort`，`call()` 恒 `Unknown/port-absent` |
| 凭据 | **金丝雀**：插件可见对象、日志、诊断中令牌**零命中** |
| 同构 | 同一条日志 TS/Py 写出，字段集与顺序**一致** |
| Harness | 未安装 → `not-installed`；探测超时 → `unknown`（**不**冒充 `available`）；`state/reason` 不变量 |
| 边界 | 宿主源码出现品牌名（`pi`/`codex`/`claude`）→ 判红 |

## 7. 证据要求

- 每条任务：**SHA + 文件 + 命令 + 真实退出码**；先红后绿留原始日志哈希。
- 红账本逐 ID 不得变（Server 67 条 / acp_orchestration 18 条继承红），新增红 **= 0**。
- **未测范围诚实登记**；受控 fixture 明确标注，不冒充真实。

## 8. 禁令

1. **不操作 git**（不提交/合并/push/动其他 worktree）。
2. **不修改契约** `contracts/**`；确需变更 → 上报并停受影响任务。
3. **不 kill/restart 用户服务**（`docs/known-issues.md` §services）。
4. **零真实模型调用**。
5. **不复活兼容链**去救继承红（`tests/acp_orchestration` 的 worker-entry 退役裁定）。
6. 不新增框架、不扩大宿主接口；小阻塞自行解决，改变契约/数据/安全语义才上报。
7. 保持既有磁盘格式、持久化 ID、协议标识、env 变量拼写**不变**。

## 9. 交付

- 代码 + 测试（正例/反例/金丝雀/一致性/同构）
- `specs/013-desktop-product/dispatch/P-B-report.md`：完成 / 阻塞 / 未测**三类事实**，逐条附证据
- 完成后**停止**，报待审
