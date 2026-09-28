# 派单简报 — P-C 发行物：deb + 一键更新 + 捆绑

**worktree**: `worktrees/013-c-packaging`　**分支**: `codex/013-c-packaging`
**日期**: 2026-09-28　**主责契约**: C-09

---

## 1. 你的目标（一句话）

产出**能装、能升、能卸、干净机器能跑**的 `ordessa_*_amd64.deb`，并带应用内一键更新；所有运行时随包，用户机器上零构建、零手填。

## 2. 只读输入（先读，不改）

```text
specs/013-desktop-product/
├── spec.md                  FR-070..080 与 SC-005/006/008
├── plan.md                  你的写入面与纪律
├── data-model.md            BundleManifest / UpdateManifest 实体
├── contracts/
│   ├── README.md            全局语义必读
│   ├── C-01-data-root.md        只读（备份落点 backups/）
│   ├── C-04-logging.md          只读（日志落点，诊断收集源）
│   ├── C-06-settings-diagnostics.md  只读（更新分区/诊断入口）
│   └── C-09-packaging-update.md ★ 你定义并实现
└── tasks.md                 PC-01 … PC-15
```

也读：`docs/baseline.md`（工具链固定版本与可复现桥构建）、`docs/architecture.md`、`.specify/memory/constitution.md`、`docs/release/first-release-handoff.md`（发行门 F1–F5）。

**必看既有资产**：
- `apps/server/lockfiles/server-linux-py312.txt` — Server 依赖闭包（已验证）
- `plugins/harness/packaging/acp-adapter/build-acp-adapter-round-h.sh` — 可复现桥构建
- `plugins/harness/packaging/{pi,codex,claude,claude-legacy,qwen,kilo,dsh}` — 品牌制品准备（**仅参考**；core 打包**不**强制捆绑，Claude 再分发条件未确认，**不得**作为打包前置）
- `products/desktop/extensions.lock.json` — 逐文件哈希（**不改**）
- `apps/desktop/package.json` — 产品元数据（**只读**，P-A 拥有）

## 3. 写入面（越界即违规）

```text
✅ 可写
├── packaging/**                        ★ 新目录（debian/、捆绑、更新、许可证、图标导出器）
├── scripts/**                          打包/构建入口
├── tooling/**                          构建工具
├── package.json                        根（打包脚本）
├── package-lock.json                   根（★ 最后统一生成）
├── tests/integration/**                归位（PC-15）
└── specs/013-desktop-product/dispatch/P-C-report.md   （你的报告）

⚠️ 申报改动（须逐文件登记）
└── docs/baseline.md                    若需登记新构建命令

❌ 禁写
├── specs/013-desktop-product/contracts/**   （冻结）
├── apps/**                             （归 P-A / P-B）
├── packages/**                         （归 P-A / P-B）
├── plugins/**                          （归 P-B）
└── 其他 worktree
```

> **`apps/desktop/package.json` 只读**。electron-builder 配置写在 `packaging/electron-builder.yml`，用 `--config` 指定，**不**写回该文件。

## 4. 任务清单

见 [tasks.md](../tasks.md) **PC-01 … PC-15**。关键顺序约束：

```text
PC-01..07  deb + 捆绑 + 哈希 + 许可证   ← 先有可安装的包
  ├─ PC-08..11  一键更新（依赖包能产出）
  └─ PC-12..15  验收（依赖前两阶段）
```

## 5. 与其他包的接口

| 你从谁拿 | 拿什么 | 何时可得 |
| --- | --- | --- |
| P-A | `apps/desktop/package.json` 产品元数据、`apps/desktop/dist` | 元数据在 PA-02 |
| 用户 | **`assets/brand/icon.svg`** 图标设计稿（单一事实位置） | **后续提供**；占位期间用内置占位，**不**阻塞主线 |
| P-B | 运行时解析约定（`ORDESSA_BUNDLED_ROOT` → `/opt/ordessa/{python,bin,harnesses}`） | C-02 §6 已冻结，**现在就能做** |
| 既有 | lockfiles、桥构建脚本、品牌制品、`extensions.lock.json` | 现在就有 |

**P-A/P-B 未就绪时**：用**占位/桩产物**把打包链路打通（明确标注），待其交付后替换真实内容复跑；打包**脚本与布局**不依赖它们的实现细节，只依赖 C-09 冻结的布局。

## 6. 必须抓到的反例（先红后绿，逐条留档）

| 项 | 反例 |
| --- | --- |
| 更新校验 | 篡改 manifest **关键元数据**（改下载地址 / 改 `minDataSchema`，仅保留 deb 哈希）→ 签名失败**拒绝安装** + 旧版本保留 |
| 更新校验 | 篡改 deb 字节 → SHA-256 不符，拒绝 |
| 更新源 | 404 / 超时 → "无法连接更新源"，**不**显示"已是最新" |
| 数据兼容 | `minDataSchema` 高于当前 → 中止 + **保留备份** + 人话错误 |
| 中断 | 安装中断电模拟 → **不假定原子**：下次启动由 `update-state.json` 故障门**识别未完成更新**、恢复到可启动、**数据不丢**、备份保留 |
| 回退 | 新版自检失败 → 记录 + 明确回退指引（告知备份路径） |
| 版本 | `package.json` / 关于面板 / 诊断 `meta.json` / 更新清单四处不一致 → 判红 |
| 卸载 | `postrm purge` 后 `~/.ordessa` **仍在** |
| 沙箱 | 发行启动命令含 `--no-sandbox` → **判红**（FR-072） |
| 干净机器 | 依赖 Node/Go/仓库 `.venv`/开发 PATH → **判红** |
| 干净机器 | deb `Depends` 含 `nodejs`/`golang`/`python3` → 判红 |

## 7. 证据要求

- **干净机器验收**（SC-006）：在**无 Node/Go/仓库 `.venv`/开发 PATH** 的 Ubuntu 环境安装并启动；重装/升级后仍可启动。用容器或独立用户环境，写明环境与命令。
- **更新全链**（SC-005）：**受控更新源**发 `v_new`，走完 检查→下载→校验→备份→安装→重启→历史仍在；篡改清单或包被拒；中断后**可检测、可修复、数据不丢**。
- 记录：**构建 SHA、deb 哈希、系统环境、实测命令/截图、通过数与失败 ID**。
- 未执行的门标 **未验证**；受控桩明确标注，**不**冒充真实捆绑物。

## 8. 禁令

1. **不操作 git**（不提交/合并/push/动其他 worktree）。
2. **不修改契约** `contracts/**`。
3. **不 kill/restart 用户服务**（`docs/known-issues.md` §services）。
4. **零真实模型调用**。
5. **不 push、不发布**（`docs/migration/remote-plan.md`：无明确授权不得发布）。
6. **不在用户机器上**执行 pip/npm/go build；所有捆绑在构建期完成。
7. 不改 `products/desktop/extensions.lock.json`、不改既有磁盘格式/持久化 ID/协议标识。
8. **正式发行禁用 `--no-sandbox`**（开发脚本 `run-dev.mjs` 可保留该 flag，但发行启动路径必须干净）。

## 9. 交付

- `packaging/**` 全套（debian 控制与脚本、bundle-manifest、更新工具、许可证聚合、图标导出器：`assets/brand/icon.svg` → `packaging/icons/generated/`）
- 可安装的 `ordessa_<version>_amd64.deb` + `SHA256SUMS`
- 一键更新客户端 + 签名工具 + 本地静态源测试
- `tests/integration/` 归位（逐 ID 不变）
- `specs/013-desktop-product/dispatch/P-C-report.md`：完成 / 阻塞 / 未测**三类事实**，附干净机器与更新全链证据
- 完成后**停止**，报待审；本包完成后报告 **「core 发行能力就绪」**，**不是**「完整产品首版已发行」
