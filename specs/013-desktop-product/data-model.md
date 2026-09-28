# Data Model — Ordessa Desktop 产品化

日期：2026-09-28。状态：设计输出（Phase 1）。与 [contracts/](contracts/README.md) 配套。

> **数据兼容铁律**（constitution 5）：磁盘格式、持久化 ID、协议标识**保持不变**。本期只**新增**数据根下的目录与新文件，**不**改既有结构。

---

## 1. 数据根布局（C-01 落地）

```text
$DATA_ROOT/                              默认 ~/.ordessa，0700
├── secrets/                             0700
│   └── http-token                       0600  既有，不变
├── logs/                                ★ 新增（C-04）
│   ├── desktop.log                      JSON Lines，10 MiB 轮转，保留 5
│   ├── desktop.log.1 … .4
│   ├── server.log
│   └── server.log.1 … .4
├── backups/                             ★ 新增（C-09）
│   ├── <ISO-ts>/                        更新前备份
│   │   ├── data-snapshot/
│   │   └── version.json                 备份时的版本/构建号/数据 schema
│   └── pending/                         下载中的 deb
├── instance.lock                        ★ 新增  0600  单实例/并发识别
└── <既有内容，标识与格式不变>
```

**权限**：目录 0700、敏感文件 0600；创建时强制，已存在时**不**放宽。

---

## 2. 关键实体

### 2.1 DataRoot（C-01）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `path` | absolute path | 解析后（无 `..`、非符号链接） |
| `source` | `'env' \| 'default''` | 来自 `ORDESSA_DATA_ROOT` 或 `$HOME/.ordessa` |
| `created` | boolean | 本次是否新建 |
| `writable` | boolean | 就绪前校验 |
| `locked` | boolean | 是否被其他实例持有 |

### 2.2 ServerInstance（C-02）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `origin` | `http://127.0.0.1:<port>` | 实际 bound，非假定 |
| `tokenLocator` | absolute path | **不含**令牌字节 |
| `pid` | number | 本方 spawn 的 pid |
| `state` | `'idle'\|'spawning'\|'probing'\|'ready'\|'failed'\|'stopping'\|'stopped'\|'crashed'` | |
| `startedAt` | ISO-8601 | |
| `scope` | `origin\|serverId` | 项目选择稳定作用域（既有 `serverInstanceId`） |

### 2.3 LogRecord（C-04）

```json
{ "ts": "2026-09-28T12:34:56.789Z", "level": "info",
  "scope": "plugin.ordessa.chat", "msg": "…", …任意字段（已脱敏） }
```

- 字段顺序固定：`ts, level, scope, msg, …`（TS/Python 同构）。
- 脱敏后落盘；`[redacted]` 为唯一占位符。

### 2.4 HarnessReport（C-08）

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `brand` | string | canonical id（沿用既有 launch descriptor） |
| `state` | 6 值枚举 | `available \| not-installed \| not-logged-in \| unsupported \| failed \| unknown` |
| `reason` | string? | **非 `available` 时必填**；`available` 时缺省 |
| `remedy` | string? | 可执行下一步 |
| `version` | string? | 未知则缺省，**不**编造 |
| `observedAt` | ISO-8601 | 观测时间 |

### 2.5 UpdateManifest（C-09）

```json
{ "schemaVersion": 1, "channel": "stable",
  "latest": { "version": "0.2.0", "build": "…",
    "deb": { "url": "…", "size": 0, "sha256": "…", "signature": "…" },
    "notes": "…", "minDataSchema": 3 } }
```

- `signature` = base64(Ed25519(sha256))；公钥随包。
- `minDataSchema` 与数据根内 schema 版本比较（FR-077）。

### 2.6 BundleManifest（C-09）

| 字段 | 说明 |
| --- | --- |
| `components[]` | `{ kind, source, version, sha256, dest }` |
| `kind` | `desktop \| python-runtime \| server-deps \| acp-bridge \| harness-artifact \| licenses` |
| `createdAt` | 构建时间 |
| `build` | 构建号 |

### 2.7 DiagnosticBundle（C-06）

```text
meta.json            version / build / builtAt / platform / productManifestSha256
environment.json     os / arch / electron / mem / diskFree（无个人标识）
product-manifest.json
data-root-state.json 存在性 / 权限 / 锁状态（**不含** secrets 内容）
logs/                已脱敏日志
plugins/<id>.json    可选诊断片段（失败记 state: unknown）
```

---

## 3. 持久化位置与所有权

| 数据 | 位置 | 所有者 | 生命周期 |
| --- | --- | --- | --- |
| 令牌 | `$DATA_ROOT/secrets/http-token` | Server | 首次创建后**不变** |
| 日志 | `$DATA_ROOT/logs/` | 宿主（C-04） | 轮转保留 5 份 |
| 备份 | `$DATA_ROOT/backups/` | 更新流程（C-09） | 用户可清理 |
| 实例锁 | `$DATA_ROOT/instance.lock` | 宿主 | 进程存活期 |
| 设置 | 数据根内既有设置存储 | 宿主 + 插件分区 | 持久 |
| 窗口状态 | Electron `userData`（**非**数据根） | 宿主 | 持久 |
| 更新公钥 | `/opt/ordessa/app/update-pubkey` | 打包 | 随版本 |

> **窗口状态**放 Electron `userData` 而**非**数据根：它是应用 UI 偏好，不是用户业务数据；卸载/清数据根不应影响它。

---

## 4. 迁移与兼容

- **本期零迁移**：只新增 `logs/`、`backups/`、`instance.lock`，全部是新目录/新文件。
- 既有数据根无这些目录 → 首次使用时创建，**不**触碰既有内容。
- 数据 schema 版本沿用既有；`minDataSchema` 仅用于更新前检查。
- **绝不**自动从旧根导入（C-01 §4）。

---

## 5. 校验与不变量

| 不变量 | 断言方式 |
| --- | --- |
| 令牌永不落日志/诊断 | 金丝雀（注入已知字节，零命中） |
| 目录 0700 / 文件 0600 | `stat` 断言 |
| `HarnessReport.state/reason` 一致 | 不变量断言 |
| 三处版本号相等 | 一致性测试 |
| 日志字段顺序 TS/Py 一致 | 同构测试 |
| 契约对象不可变 | `Object.isFrozen` / `frozen dataclass` |
| 既有磁盘格式未变 | 既有测试红账本逐 ID 不变（SC-010） |
