# C-06 — 设置分区与诊断贡献（Settings & Diagnostics）🔌 插件 API

**面向**：🔌 插件公开契约　**定义方**：P-A　**消费方**：插件
**状态**：冻结

## 目的

设置页既要容纳**应用级**设置，也要让插件注册自己的设置分区（Z1/Z3 已按 workbench「设置贡献点」实现，须冻结不新造）。诊断同理：宿主出骨架，插件可选补充。

---

## A. 设置分区

### A1. 插件侧 API

```ts
import type { SettingsContribution, SettingsSection } from '@ordessa/contracts'

interface SettingsContribution {
  /** 注册一个设置分区；返回退订 */
  register(section: SettingsSection): () => void
}

interface SettingsSection {
  readonly id: string            // 稳定 id，如 "ordessa.model-provider"
  readonly title: string
  readonly order?: number        // 排序权重，小在前
  /** 渲染入口：由平台 UI 服务登记（C-05 tokens 可用） */
  readonly component: unknown
  /** 该分区声明的配置项 ID 与 schema（供 Profile/校验使用） */
  readonly items?: readonly SettingsItemDescriptor[]
}

interface SettingsItemDescriptor {
  readonly id: string
  readonly kind: 'string' | 'number' | 'boolean' | 'enum' | 'secret-ref'
  readonly label: string
  readonly description?: string
  readonly default?: unknown
  readonly enumValues?: readonly string[]
}
```

### A2. 应用级设置（宿主内置分区）

| 分区 | 项 |
| --- | --- |
| 通用 | 语言（本期只留选项，不交付翻译）、主题（C-05）、启动行为 |
| 数据 | 数据根位置（**只读**展示 + "打开目录"按钮）、备份目录 |
| 日志 | 级别（C-04 §7）、打开日志目录、导出诊断 |
| 更新 | 更新通道、检查更新、当前版本 |
| 关于 | 版本、构建号、插件版本、第三方许可证、许可证全文 |

### A3. 卸载与缺席语义（全局规则 §3）

- 提供者卸载 → 分区**隐藏**，已存配置**保留**，**不**展示故障占位。
- 未知片段 → **不**下发、**不**崩；标记 `unknown` 并保留数据。
- 重新加载 → 校验通过才使用。
- **会话临时修改不写回 Profile**（`plugin-layout` §3）。

---

## B. 诊断贡献

### B1. 诊断包内容（FR-060，宿主骨架）

```text
ordessa-diagnostics-<version>-<build>.zip
├── meta.json              版本、构建号、构建时间、平台、产品清单 SHA-256
├── environment.json       OS/架构/Electron/内存/磁盘余量（无个人标识）
├── product-manifest.json  products/desktop/extensions.json + extensions.lock.json
├── data-root-state.json   目录存在性/权限/锁状态/**不含**任何 secrets 内容
├── logs/                  $DATA_ROOT/logs/ 全部文件（已经 C-04 脱敏）
└── plugins/               各插件可选贡献的诊断片段（B2）
```

**硬门（FR-061）**：`secrets/` 下文件**永不**收集；全包令牌字节**零命中**（金丝雀）。

### B2. 插件侧 API（可选）

```ts
interface DiagnosticsContribution {
  /** 注册一个诊断片段提供者；返回退订 */
  register(provider: DiagnosticProvider): () => void
}

interface DiagnosticProvider {
  readonly id: string
  /** 返回纯 JSON 可序列化片段；超时/异常 → 记为 unknown，不阻塞导出 */
  collect(): Promise<Readonly<Record<string, unknown>>>
}
```

- `collect()` 有**超时**（默认 3 秒）与异常兜底：失败片段记 `{ id, state: 'unknown', reason }`，**不**让整个导出失败。
- 片段同样经 C-04 脱敏后落盘。

### B3. 导出行为

- 生成 **≤ 5 秒**（SC-009）。
- 输出为单个 zip，默认落用户选择的位置；失败给出可操作错误 + 日志入口。

---

## C. 故障 UI（与 C-02 联动）

启动/运行故障**必须**呈现为可操作错误，**不**空白、**不**假绿（FR-024）：

```text
┌ 故障 ─────────────────────────────────┐
│ 无法启动 Ordessa Server               │
│ 原因：随包运行时缺失（bin/acp）        │
│ 你可以：                              │
│  · 重新安装应用                        │
│  · 查看日志                            │
│  · 导出诊断                            │
└───────────────────────────────────────┘
```

每条故障含 `reason`（人话）+ `remedy`（可执行下一步）+ `logRef` + 导出诊断入口。

---

## D. 反例清单（必须先红后绿）

1. 注册分区后卸载提供者 → 分区消失，已存配置仍在（读回断言）。
2. 未知配置片段 → 不下发、不崩，标记 `unknown`。
3. 诊断片段提供者超时 → 该片段记 `unknown`，导出**仍成功**。
4. **金丝雀**：注入令牌字节到日志与配置 → 诊断包内**零命中**。
5. 故障 UI：5 类故障（无目录/端口冲突/缺二进制/根被锁/更新源不可达）各一条，**零**空白窗口。
6. 分区渲染抛异常 → 该分区显示错误边界，**不**拖垮整个设置页。
