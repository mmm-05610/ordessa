# C-09 — 打包布局与更新（Packaging & Update）对内

**面向**：对内（非插件 API）　**定义方**：P-C　**消费方**：P-A / P-B
**状态**：冻结

## A. deb 打包（FR-070/073）

### A1. 包标识

| 项 | 值 |
| --- | --- |
| 包名 | `ordessa` |
| 架构 | `amd64` |
| 版本 | 单一来源（FR-001），形如 `0.1.0`；构建号另存 |
| Section | `utils` |
| Priority | `optional` |
| Maintainer / Homepage / License | 来自 `apps/desktop/package.json`（P-A 拥有该文件） |

### A2. 安装布局（P-B 消费此布局解析运行时）

```text
/opt/ordessa/
├── python/                  固定版本 CPython（python-build-standalone 3.12.x）
│   └── lib/python3.12/site-packages/     Server 依赖（server-linux-py312.txt 预装）
├── bin/
│   ├── ordessa              启动器（不带 --no-sandbox，FR-072）
│   └── acp                  ACP 桥（Go，构建期生成）
├── harnesses/               品牌制品（pi/codex/claude/…）
├── app/                     Electron 应用（dist + products/desktop/dist）
└── licenses/
    ├── LICENSE
    └── THIRD-PARTY-NOTICES   全局聚合（FR-078）

/usr/share/applications/ordessa.desktop
/usr/share/icons/hicolor/{16,32,48,64,128,256}x{…}/apps/ordessa.png
/usr/share/doc/ordessa/{copyright,changelog.Debian.gz}
```

### A3. 依赖与脚本

- `Depends`: 仅系统级必要项（如 `libc6`, `libgtk-3-0`, `libnss3`, `libasound2` 等 Electron 运行时库）；**不**依赖 `nodejs`/`golang`/`python3`。
- `postinst`：`update-desktop-database`、`gtk-update-icon-cache`、创建/校验用户级数据根的**提示**（**不**代用户创建）。
- `prerm`：停止运行中的实例（若由本包启动）。
- `postrm`：清理系统级文件与图标缓存；`purge` 时**仍不**删除 `~/.ordessa`（FR-080）。

### A4. 版本与构建号注入

- 版本**单一来源**，构建期注入到：`package.json`、关于面板、诊断 `meta.json`、更新清单。
- 构建号 = 构建时间 + 短 SHA，同样注入。
- **一致性测试**：三处读到的版本必须相等。

---

## B. 运行时捆绑（FR-071）

构建期（非运行时）准备清单 `packaging/bundle-manifest.json`：

| 内容 | 来源 | 去向 |
| --- | --- | --- |
| Desktop dist | `apps/desktop/dist` + `products/desktop/dist` | `/opt/ordessa/app/` |
| Python 运行时 | python-build-standalone 3.12.x（固定 SHA-256） | `/opt/ordessa/python/` |
| Server 依赖 | `apps/server/lockfiles/server-linux-py312.txt` | `…/site-packages/` |
| ACP 桥 | `plugins/harness/packaging/acp-adapter` 构建脚本 | `/opt/ordessa/bin/acp` |
| Harness 运行时 | **仅** core 与默认装配实际需要的组件 | `/opt/ordessa/harnesses/` |
| 许可证 | 各包声明聚合 | `/opt/ordessa/licenses/` |

- 所有捆绑物记录**版本 + SHA-256**；`bundle-manifest.json` 随包并纳入产物哈希清单。
- **禁止**在用户机器上执行 pip/npm/go build。
- **捆绑范围以 core 自身为限**：只证明 013 自身与默认装配实际需要的组件能在干净机器运行。**不**强制捆绑全部品牌制品；**尤其不得**把再分发条件尚未确认的 Claude 制品当作 core 打包前置。品牌包留给后续插件发行线。

---

## C. 一键更新（FR-074–077）

### C1. 更新源格式（`update-manifest.json`，静态 HTTPS）

```json
{
  "schemaVersion": 1,
  "channel": "stable",
  "latest": {
    "version": "0.2.0",
    "build": "20260928-78afe8c",
    "deb": { "url": "https://…/ordessa_0.2.0_amd64.deb",
             "size": 123456789,
             "sha256": "…",
             "signature": "base64(ed25519(sha256))" },
    "notes": "…",
    "minDataSchema": 3
  }
}
```

- **Ed25519 签名**，公钥随包（`/opt/ordessa/app/update-pubkey`）。
- **签名覆盖清单的关键元数据**，而非只签 deb 哈希：签名载荷 = 按稳定键序序列化的 `{schemaVersion, channel, version, build, deb.url, deb.size, deb.sha256, minDataSchema}`。其中**任一项被改动即签名校验失败**（防止"改下载地址/改最低数据版本但保留 deb 哈希"的降级攻击）。
- `minDataSchema` 用于数据兼容检查（FR-077）。

### C2. 更新流程（严格顺序，任一步失败即中止并保留旧版本）

```text
1 检查     GET manifest → 校验签名 → 比较版本（用户确认，不自动下载）
2 下载     到 $DATA_ROOT/backups/pending/，校验 SHA-256 + 签名
3 备份     数据根关键内容 + 当前版本信息 → $DATA_ROOT/backups/<ts>/
4 兼容     检查 minDataSchema ≤ 当前数据 schema；不兼容 → 中止并保留备份
5 安装     pkexec dpkg -i <deb>（polkit 提权）
6 重启     退出并重新拉起应用
7 验证     新版本自检（版本一致 + /live 就绪）；失败 → 记录 + 提示回退
```

### C3. 失败与回退语义

| 情形 | 行为 |
| --- | --- |
| 更新源不可达 | **报错**"无法连接更新源"，**不**静默当作最新（FR-075） |
| 签名/哈希不符 | **拒绝安装**，删除下载物，保留旧版本 |
| 用户取消 polkit | 中止，旧版本完好，状态明确 |
| 安装中断/断电 | **不假定原子**：由下方 **C4 更新故障门**检测，恢复到可启动状态且**数据不丢**（FR-076） |
| 新版自检失败 | 记录 + 提示用保留的旧 deb 重装（备份路径告知） |
| 数据不兼容 | **中止并保留备份**，给出人话错误（FR-077） |

**回退 = 保留旧 deb 副本 + 数据根备份**；不做双版本并存切换（research R2）。

### C4. 更新故障门（可检测、可修复、数据不丢）

**不假定** `dpkg` 覆盖安装在任意中断下都是原子的。改为**可检测 + 可修复 + 数据不丢**：

```text
$DATA_ROOT/backups/update-state.json      0600，写临时文件后 rename 原子发布
{
  "phase": "idle|downloading|verified|backed-up|installing|restarting|done|failed",
  "from": {"version":"…","build":"…"},
  "to":   {"version":"…","build":"…"},
  "backupRef": "backups/<ts>",
  "debRef": "backups/pending/<file>.deb",
  "startedAt": "…", "updatedAt": "…",
  "failure": null | {"reason":"…","remedy":"…"}
}
```

- 每阶段推进前更新 `phase`；启动时读到 `phase=installing`/`restarting` 且非 `done` → **判定为未完成更新**。
- 未完成更新的处置（按序，数据优先）：
  1. **数据优先**：校验数据根可读可写；损坏 → 引导用户用 `backupRef` 恢复，**不**自动覆盖。
  2. **可用性**：给出恢复到可启动状态的可执行入口（如 `dpkg --configure -a` 的人话指引 + 一键执行）。
  3. **明确状态**：UI 显示"上次更新未完成"+ 当前版本 + 备份路径 + 修复按钮；**不**假装已是最新。
- **成功判据**：新版本自检（版本一致 + `/live` 就绪）通过后才置 `phase=done` 并清 `debRef`；否则保持 `failed` 并给出回退指引。
- **数据不丢是硬门**：任何恢复动作**不得**删除或覆盖 `backupRef`；清理备份只能由用户显式触发。

---

## D. 产物哈希与许可证（FR-078/079）

- 产物级 `SHA256SUMS`：deb、`bundle-manifest.json`、`app/` 目录树哈希。
- 扩展层沿用 `products/desktop/extensions.lock.json` 逐文件哈希（**不**改）。
- `THIRD-PARTY-NOTICES`：构建期从各 `package.json` / `pyproject.toml` 声明的第三方来源聚合；关于面板可达。

---

## E. 反例清单（必须先红后绿）

1. 篡改 manifest 签名 → 拒绝安装 + 明确错误，旧版本保留。
2. 篡改 deb 字节 → SHA-256 不符，拒绝安装。
3. 更新源 404/超时 → "无法连接更新源"，**不**显示"已是最新"。
4. `minDataSchema` 高于当前 → 中止 + 保留备份 + 人话错误。
5. 安装后启动自检失败 → 记录 + 明确回退指引。
6. 三处版本号不一致 → 一致性测试判红。
7. `postrm purge` 后 `~/.ordessa` **仍在**（FR-080）。
8. 发行启动命令含 `--no-sandbox` → 判红（FR-072）。
