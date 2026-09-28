# Contracts — Ordessa Desktop 产品化（冻结接口）

日期：2026-09-28。状态：**冻结输入**。三个实施包只消费本目录，**不得**修改契约；确需变更必须上报主会话并停受影响任务（constitution「改变契约/数据/安全语义上报」）。

上游：[spec.md](../spec.md) · [research.md](../research.md) · [plan.md](../plan.md)

---

## 索引

| 契约 | 名称 | 面向 | 定义方 | 消费方 | 文件 |
| --- | --- | --- | --- | --- | --- |
| **C-01** | 数据根规范 | 对内 | P-B | P-A / P-C | [C-01-data-root.md](C-01-data-root.md) |
| **C-02** | 启动交接与进程生命周期 | 对内 | P-B | P-A | [C-02-launch-handoff.md](C-02-launch-handoff.md) |
| **C-03** | wire 传输口 | 🔌 **插件** | P-B | 插件 / P-A | [C-03-wire-port.md](C-03-wire-port.md) |
| **C-04** | 日志 | 🔌 **插件** | P-A（TS）/ P-B（Py） | 插件 / P-C | [C-04-logging.md](C-04-logging.md) |
| **C-05** | 主题 | 🔌 **插件** | P-A | 插件 | [C-05-theme.md](C-05-theme.md) |
| **C-06** | 设置分区与诊断贡献 | 🔌 **插件** | P-A | 插件 | [C-06-settings-diagnostics.md](C-06-settings-diagnostics.md) |
| **C-07** | 命令与快捷键 | 🔌 **插件** | P-A | 插件 | [C-07-commands-keybindings.md](C-07-commands-keybindings.md) |
| **C-08** | Harness 可用性 | 🔌 **插件（提供）** | P-B（契约）/ Harness 插件（实现） | P-A（渲染） | [C-08-harness-availability.md](C-08-harness-availability.md) |
| **C-09** | 打包布局与更新 | 对内 | P-C | P-A / P-B | [C-09-packaging-update.md](C-09-packaging-update.md) |

**面向图例**：🔌 插件 API = 插件可 import 的公开契约；对内 = 仅 core 内部约定，不进插件公开面。

---

## 全局语义（所有契约共用）

### 1. 缺席与失败：三态，不得假绿

所有面向插件的契约在无法确定结果时**必须**返回类型化三态，**禁止**抛裸异常、静默回退或返回伪造成功：

```text
Accepted  操作已被确认接受（有明确证据）
Refused   被明确拒绝（有 reason，可重试与否由 reason 决定）
Unknown   无法确定（宿主未就绪 / 证据不足 / 依赖缺席）
```

> ⚠️ constitution 4「证据不假绿」：**Unknown 不得冒充 Accepted**。旧数据缺证据时投影 Unknown 并保持 Unknown，不得自动提升。

### 2. 宿主未就绪

插件调用某机制而该机制宿主未就绪时，返回 `Unknown` + `reason: "host-not-ready"`，**不**排队假装成功、**不**阻塞 UI。

### 3. 卸载与缺席

- 提供者卸载 → 其贡献的入口**隐藏**，已存配置**保留**，**不**展示故障占位。
- 未知片段（提供者缺席）→ **不**下发、**不**报错崩，标记 `unknown` 并保持数据。
- 重新加载后 → 校验通过才使用（`plugin-layout` §3）。

### 4. 密钥与脱敏

- 令牌字节**只**存在于主进程与 Server 侧；渲染进程、插件、日志、诊断包**一律不得**包含。
- 脱敏在 **sink 层强制**（C-04 §4），不依赖调用方。
- 拒绝信息**永不**携带令牌字节或完整定位符（最多显示 basename）。

### 5. 命名与稳定标识

- 环境变量、路径、扩展 id、持久化标识**保持既有拼写**（`docs/naming.md` 除外）；改名需迁移记录 + 用户确认。
- 契约类型一律**不可变**（frozen dataclass / `readonly` / `as const`），嵌套结构同样不可变。

### 6. 边界纪律

- 插件 **只** import `packages/desktop-platform/contracts`、`packages/desktop-platform/extension-api`、`packages/server-plugin-api` 等公开面；**禁止** import 宿主内部（`apps/*` 实现、`packages/*/src` 内部模块）。
- 宿主 **不**得出现品牌名、Profile 字段、模型字段（constitution 1）。
- 边界测试必须有**反例**：注入越界 import，断言被判别（沿用既有 boundary_check 模式）。

### 7. 证据要求

每条契约的实现必须配：
1. **正例**：按契约走通。
2. **反例**：缺席/失败/越权/篡改至少各一条，且**先红后绿**留档。
3. **金丝雀**（涉及密钥的）：注入已知令牌字节，断言零命中。

---

## 与既有实现的对应（冻结点）

本目录的契约**不新造 API**，而是把既有已验证接缝冻结下来：

| 契约 | 既有来源（保留语义） |
| --- | --- |
| C-01 | `apps/server/src/ordessa_server/bootstrap/runtime.py::_ensure_token`（`secrets/http-token`）+ handoff 对 `~/.ordessa` 的要求 |
| C-02 | `plugins/connectors/ordessa/src/target.ts` 的 env 拒绝语义 + `plugins/connectors/acp/src/native.ts` |
| C-03 | `apps/server/src/ordessa_server/transport/http/app.py` 的 `POST /wire/v1/{method}` + Bearer |
| C-04 | Z3 `test_no_credential_leak` 的金丝雀方法 |
| C-05 | 收敛 `packages/workbench/src/styles.ts` 与 `plugins/chat/frontend/src/theme.ts` |
| C-06 | `packages/workbench` 既有「设置贡献点」 |
| C-07 | `packages/desktop-platform/contracts` 既有 commands source |
| C-08 | `plugins/harness` 既有 launch descriptor（8 个 canonical id）+ `plugin-layout` §4 |
| C-09 | `products/desktop/extensions.lock.json` 逐文件哈希 + `apps/server/lockfiles/*` |
