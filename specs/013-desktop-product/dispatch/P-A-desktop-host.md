# 派单简报 — P-A Desktop 宿主与平台 UI

**worktree**: `worktrees/013-a-desktop-host`　**分支**: `codex/013-a-desktop-host`
**日期**: 2026-09-28　**主责契约**: C-04(TS) / C-05 / C-06 / C-07 / C-08（类型与缺席语义）

---

## 1. 你的目标（一句话）

把 Desktop 宿主从"能开窗的开发壳"补成**产品**：产品身份、统一日志（强制脱敏）、生命周期可靠性、故障 UI、设置页、诊断导出、统一主题、命令与快捷键——**并把这些机制以公开契约发布给插件**。

## 2. 只读输入（先读，不改）

```text
specs/013-desktop-product/
├── spec.md                  FR-001..080 与 SC-001..010
├── plan.md                  你的写入面与纪律
├── data-model.md            实体与持久化位置
├── contracts/               ★ 冻结接口，绝不修改
│   ├── README.md            全局语义（三态/缺席/脱敏/边界/证据）必读
│   ├── C-03-wire-port.md    你消费（类型 + 注入）
│   ├── C-04-logging.md      ★ 你定义并实现（TS 侧）
│   ├── C-05-theme.md        ★ 你定义并实现
│   ├── C-06-settings-diagnostics.md  ★ 你定义并实现
│   ├── C-07-commands-keybindings.md  ★ 你定义并实现
│   └── C-08-harness-availability.md  ★ 你定义类型 + 缺席语义（本期**不改插件**）
└── tasks.md                 PA-01 … PA-25
```

也读：`docs/architecture.md`、`.specify/memory/constitution.md`、`apps/desktop/AGENTS.md`。

## 3. 写入面（越界即违规）

```text
✅ 可写
├── apps/desktop/**
├── packages/desktop-platform/contracts/**
├── packages/desktop-platform/ui/**
├── packages/desktop-platform/ui-components/**
├── packages/desktop-platform/extension-api/**
├── packages/desktop-platform/extension-loader/**
├── packages/desktop-platform/extension-host/**
├── packages/desktop-platform/native-bridge/**
├── packages/workbench/**
└── specs/013-desktop-product/dispatch/P-A-report.md   （你的报告）

🔒 插件改动：**无**（013 = core 阶段，`plugins/**` 一律只读）
└── 确需改插件 → **停止该项**，上报主会话并取得用户裁定，批准后逐文件登记再动

❌ 禁写
├── specs/013-desktop-product/contracts/**   （冻结）
├── apps/server/**、packages/server-plugin-api/**
├── packages/desktop-platform/server-bridge/**   （归 P-B）
├── plugins/**（**全部只读**，013 零插件改动）
├── packaging/**、scripts/**、tooling/**        （归 P-C）
├── 根 package.json / package-lock.json         （归 P-C）
└── 其他 worktree
```

## 4. 任务清单

见 [tasks.md](../tasks.md) **PA-01 … PA-25**，按阶段 1→5 顺序做。关键顺序约束：

```text
PA-01（契约类型）  ← 必须最先，其余任务都依赖
  ├─ PA-02..04  产品身份（图标只做**接线与占位**，设计稿由用户后续换上 `assets/brand/icon.svg`）
  ├─ PA-05..11  日志 + 可靠性 + 代码卫生
  ├─ PA-12..15  故障 UI / 设置 / 诊断
  ├─ PA-16..20  主题 / 命令 / 键盘（`plugins/chat` **不改**，主题收敛只到 workbench）
  └─ PA-21..25  接线 / 边界 / C-08 缺席渲染（依赖 P-B 的 server-bridge，见 §5）
```

## 5. 与其他包的接口（唯一耦合点）

你需要 `@ordessa/server-bridge`（P-B 提供）实现 C-01/C-02/C-03：

- **P-B 未就绪时**：用**受控 fixture** 实现开发与测试（明确标注 fixture，**不**冒充真实现），并在报告登记切换点。
- **P-B 就绪后**：切换到真实现并复跑。
- 契约已冻结，你**只消费类型**，不改其定义。

**另一个接口：P-C 的更新引擎（评审明确的接线缺口）**

- **更新引擎归 P-C**（清单 / 签名 / 下载 / 校验 / 备份 / 故障门 / `pkexec dpkg -i`）；**设置页「检查更新」UI 与主进程接线归你（P-A）**。这是 plan.md §跨包集成归属表指定的分工，**不**要自行实现更新引擎（避免两套）。
- 对接面：P-C 交付**可调用的更新客户端入口** + `$DATA_ROOT/backups/update-state.json` 状态机（见 C-09 §C4）。你负责 UI（检查 / 进度 / 失败原因 / 更新后重启）与主进程生命周期接线。
- P-C 未就绪时同样用**受控 fixture** 开发与测试（明确标注），登记切换点；P-C 交付后切换复跑。

## 6. 必须抓到的反例（先红后绿，逐条留档）

| 项 | 反例 |
| --- | --- |
| 日志脱敏 | **金丝雀**三路：字段名 `token`、换名 `myKey`+令牌值、消息正文含令牌 → 文件**零命中** |
| 诊断导出 | **金丝雀**：注入令牌 → zip 内**零命中**；`secrets/` 文件**永不**入包 |
| 故障 UI | 5 类故障（无目录/端口冲突/缺二进制/根被锁/更新源不可达）各一条，**零**空白窗口 |
| 设置分区 | 卸载提供者 → 分区隐藏但配置保留；未知片段 → 不下发不崩 |
| 主题 | 切 dark → 宿主 + fixture 插件**同时**变色无残留；tokens `Object.isFrozen` |
| 命令 | 同快捷键二次注册 → 拒绝并报冲突；命令抛异常 → UI 报错且应用继续可用 |
| 边界 | fixture 插件 import 宿主内部 → 判别为违规；宿主源码出现品牌名 → 判红 |
| 安全 | `sandbox/contextIsolation/nodeIntegration` 保持 `true/true/false`；令牌不进渲染进程 |

## 7. 证据要求

- 每条任务：**SHA + 文件 + 命令 + 真实退出码**；先红后绿留原始日志哈希。
- 红账本逐 ID 不得变（新增红 **= 0**）。
- **未测范围诚实登记**，不以局部测试冒充整线通过。

## 8. 禁令

1. **不操作 git**：不提交、不合并、不 push、不动其他 worktree（git 检查点归主会话）。
2. **不修改契约** `contracts/**`；确需变更 → 上报主会话并**停受影响任务**。
3. **不 kill/restart 用户服务**（`docs/known-issues.md` §services）。
4. **零真实模型调用**；受控 fixture 明确标注，不假绿。
5. 不新增框架、不扩大宿主接口、不复制服务绕过阻塞；小阻塞自行解决，改变契约/数据/安全语义才上报。
6. 不写品牌名、Profile 字段、模型字段进宿主。

## 9. 交付

- 代码 + 测试（正例/反例/金丝雀/边界）
- `specs/013-desktop-product/dispatch/P-A-report.md`：完成 / 阻塞 / 未测**三类事实**，逐条附证据；**插件改动应为「无」**，若确有须逐文件列明并附用户裁定记录
- 完成后**停止**，报待审；不自动合并、不无限空转；本包完成后报告 **「core 发行能力就绪」**，**不是**「完整产品首版已发行」
