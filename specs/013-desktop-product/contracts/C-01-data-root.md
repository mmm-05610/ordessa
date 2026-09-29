# C-01 — 数据根规范（DataRoot）

**面向**：对内（非插件 API）　**定义方**：P-B　**消费方**：P-A / P-C
**状态**：冻结

## 目的

给"用户数据放在哪、怎么安全地建/用"一个**唯一明文规范**，Server CLI 与 Desktop 宿主共同遵守（handoff 明确要求"两入口须有同一个明文规范和一致性测试"）。

## 1. 解析顺序（唯一）

```text
1. 显式覆盖      ORDESSA_DATA_ROOT 环境变量（开发/高级入口）
2. 默认          $HOME/.ordessa
```

- 两者都不看仓库内目录、不看临时目录（handoff 硬要求）。
- 解析结果必须是**绝对路径**、无 `..`。**符号链接检查必须在任何跟随之前**：先以 **no-follow** 语义（`lstat` / `O_NOFOLLOW`）判定，**禁止**先 `resolve()`/`stat()` 跟随链接再判断。

## 2. 布局

```text
$DATA_ROOT/
├── secrets/
│   └── http-token          0600  48 字节 urlsafe + "\n"（既有 _ensure_token 语义）
├── logs/                                   ← C-04 落点
│   ├── desktop.log  desktop.log.1 …        按大小轮转，保留 N 份
│   └── server.log   server.log.1 …
├── backups/                                ← C-09 更新前备份落点
├── instance.lock                           0600  单实例/并发识别
└── …（既有数据根内容，标识与磁盘格式不变）
```

## 3. 创建与校验（安全语义）

| 情形 | 行为 |
| --- | --- |
| 不存在 | 创建，目录 **0700**；`secrets/` **0700**；`secrets/http-token` **0600** |
| 已存在 | **复用**，不重建、不改写既有数据、不改变既有权限以外的内容 |
| 是符号链接 | **拒绝**（以 no-follow 语义判定，**不**跟随链接、**不**读取目标内容），类型化错误 `DATA_ROOT_SYMLINK` |
| 不可写 / 无权限 | **拒绝**，类型化错误 `DATA_ROOT_NOT_WRITABLE` |
| 被另一实例锁住 | **拒绝**，类型化错误 `DATA_ROOT_LOCKED`（语义=已有实例在运行，**不是**磁盘错误） |
| 磁盘满 / 写失败 | **拒绝**并保留原始原因；清理异常**不**覆盖主因 |

## 4. 旧根与升级

- **绝不**自动从旧根导入（handoff 硬要求）。
- 升级/迁移必须：先备份 → 兼容检查 → 不兼容则**明确失败并保留备份**（FR-077）。
- 无注册迁移提供者的历史根 → **拒绝并保留原字节**（沿用既有 `80603a81dc` 的 preflight 语义：在 marker/lock/token/schema 写入之前拒绝）。

## 5. 明文规范的唯一性（一致性测试）

必须有一条测试证明：
- Server CLI（Python）解析出的默认根 **===** Desktop 宿主（TS）解析出的默认根；
- 两者的布局常量（`secrets/http-token`、`logs/`、`backups/`、`instance.lock`）**逐字相同**；
- 覆盖行为一致（`ORDESSA_DATA_ROOT` 生效于两者）。

建议实现：Python 侧 `bootstrap/data_root.py` 为权威，TS 侧实现 + 一条**跨语言一致性测试**读取同一份 JSON 常量（常量文件由 P-B 提供，P-A/P-C 只读）。

## 6. 类型化错误

```text
DATA_ROOT_SYMLINK          路径是符号链接
DATA_ROOT_NOT_WRITABLE     不可写或无权限
DATA_ROOT_LOCKED           已有实例持有锁
DATA_ROOT_INVALID          解析结果非法（相对/含 ..）
DATA_ROOT_MIGRATION_REFUSED 无迁移提供者的历史根
```

每个错误必须携带 `reason` + `remedy`（人话修复办法），**不**携带令牌字节。

## 7. 反例清单（必须先红后绿）

1. 指向符号链接 → 拒绝，且**在读取前**（不泄漏内容）。
2. `chmod 0500` → 拒绝 `DATA_ROOT_NOT_WRITABLE`。
3. 另一进程持锁 → 拒绝 `DATA_ROOT_LOCKED`，且**不**报磁盘错误。
4. 二次启动 → 复用，`secrets/http-token` 字节**不变**。
5. `ORDESSA_DATA_ROOT=/tmp/x` → 两入口一致使用该值。
6. 历史根无迁移提供者 → 拒绝，原 DB 字节**不变**（金丝雀比对）。
