# C-08 — Harness 可用性（HarnessAvailability）🔌 插件 API（插件提供）

**面向**：🔌 插件公开契约　**类型定义**：P-A（`packages/desktop-platform/contracts`，core）　**实现**：Harness 插件（**本期不做**）　**消费方**：P-A（渲染）
**状态**：冻结

## 目的

UI 必须显示每个 Harness 的**真实可用性**（FR-050）。但品牌差异属 Harness 适配层（`plugin-layout` §4），**宿主不得内置品牌逻辑**。故此契约是"**插件提供、宿主消费**"方向——与 C-03/C-04 相反。

> ⚠️ 易错点：做成"宿主 `which pi`"就是把品牌逻辑塞进宿主，违反 constitution 1 与 `plugin-layout` §4。**禁止**。

## 1. API

```ts
import type { HarnessAvailability, HarnessState, HarnessReport } from '@ordessa/contracts'

type HarnessState =
  | 'available'      // 已安装且可用
  | 'not-installed'  // 未安装
  | 'not-logged-in'  // 已装但未登录/未认证
  | 'unsupported'    // 该品牌不支持所需能力
  | 'failed'         // 适配器/启动失败
  | 'unknown'        // 无法确定（不得冒充 available）

interface HarnessAvailability {
  /** 返回全部已知 Harness 的可用性报告。永不抛异常。 */
  inspect(): Promise<readonly HarnessReport[]>
  /** 单个查询 */
  inspectOne(brand: string): Promise<HarnessReport>
  /** 订阅变化（安装/登录状态改变） */
  subscribe(listener: (report: readonly HarnessReport[]) => void): () => void
}

interface HarnessReport {
  readonly brand: string          // canonical id（沿用既有 launch descriptor 命名）
  readonly state: HarnessState
  readonly reason?: string        // 人话原因（state !== 'available' 时必填）
  readonly remedy?: string        // 可执行下一步
  readonly version?: string       // 已装版本（未知则缺省，不编造）
  readonly observedAt: string     // ISO-8601，观测时间
}
```

**不变量**：`HarnessReport` 不可变；`state` 与 `reason` 必须一致（`available` 时 `reason` 缺省；非 `available` 时 `reason` 必填）。

## 2. 语义约束

| 规则 | 说明 |
| --- | --- |
| **不假绿** | 无法确定 → `unknown`，**绝不**返回 `available` |
| **不编造版本** | 未知则 `version` 缺省 |
| **观测而非猜测** | 只报告实际观测事实（安装、登录、启动），**不**由表单推断（`plugin-layout` §3「可用性依据 Harness 实际能力，不由表单猜测」） |
| **品牌内聚** | 品牌差异、原生配置应用、重启/resume 归 Harness 适配层 |
| **有界** | `inspect()` 有超时（默认 3 秒/品牌），超时 → `unknown` + `reason: "inspect-timeout"` |

## 3. 宿主渲染规则

- 显示 `state` + `reason`（人话）+ `remedy`（若有）。
- `not-installed` / `not-logged-in` / `failed` → **诚实不可用**，UI 相应入口禁用并说明原因。
- `unknown` → 显示"状态未知"，**不**显示为可用、**不**显示为失败。
- **禁止**：空列表冒充"没有 Harness"；空白状态；把 `unknown` 显示成绿色。

## 4. 缺席与未就绪

- Harness 插件未安装/未加载 → 宿主显示"未提供 Harness 可用性信息"，**不**假定全部可用。
- 宿主未就绪 → `inspect()` 返回各品牌 `unknown` + `reason: "host-not-ready"`。

> **本期范围（013 = core，零插件改动）**：core 只提供**类型**与**缺席语义**（无提供者时按本节显示"未提供 Harness 可用性信息"）。Harness 插件对 `HarnessAvailability` 的**实现**属后续插件线；本期**不**改 `plugins/harness/**`。

## 5. 与发行门的关系

F2 要求"未安装/未登录/适配器失败时诚实不可用；桥握手或 fake-only 不算真实可用"。本契约只提供**可用性事实**；真实可用性验收（真实启动/两轮对话/重启恢复）属后续品牌线，**本期不做**。

## 6. 反例清单（必须先红后绿）

1. 品牌未安装 → `not-installed` + 原因，**不**返回 `available`。
2. 已装未登录 → `not-logged-in` + 原因。
3. 探测超时 → `unknown` + `inspect-timeout`，**不**冒充 `available`。
4. 宿主无 Harness 插件 → 显示"未提供信息"，**不**显示假可用。
5. `state='available'` 但 `reason` 非空（或反之）→ 不变量断言失败（反例）。
6. 边界反例：宿主源码出现品牌名（`pi`/`codex`/`claude`）→ 边界测试判别为违规。
