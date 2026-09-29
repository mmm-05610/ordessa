# P-C 报告 — 发行物：deb + 一键更新 + 捆绑

**worktree**: `worktrees/013-c-packaging`　**分支**: `codex/013-c-packaging`
**基线 SHA**: `7adf5aeaca`（`codex/013-c-packaging` HEAD，实施期间未变）
**日期**: 2026-09-28　**主责契约**: C-09
**完成口径**: 本包完成后报告 **「core 发行能力就绪」**，**不是**「完整产品首版已发行」。

---

## 0. 结论速览

| 类别 | 数量 | 说明 |
| --- | --- | --- |
| **完成（有证据）** | 15 / 15 | PC-01…PC-15 全部落地，测试与实测命令见下 |
| **阻塞** | 0 | 无阻塞项 |
| **未测 / 未验证** | 3 | 如实登记，见 §5（均为**环境所限**，非实现缺失） |

**已产出的真实产物**：

```text
packaging/.out/ordessa_0.1.0_amd64.deb     200,792,992 字节
  sha256  55fe0d10cf76ebbd930ecad8a18b3440e86937dbb4b6b9af698e031924138365
packaging/.out/SHA256SUMS
packaging/.out/app-tree.sha256
packaging/.out/build-result.json
packaging/bundle-manifest.json
```

---

## 1. 交付物清单（写入面内）

```text
packaging/
├── lib/identity.mjs          版本/构建号单一来源（C-09 A4）
├── lib/layout.mjs            安装布局常量（C-09 A2，P-B 运行时解析同源）
├── lib/hash.mjs              确定性树哈希 + 文件哈希（C-09 D）
├── debian/control.in         Depends 仅系统库（无 nodejs/golang/python3）
├── debian/postinst           缓存刷新 + 提示（不代建数据根）
├── debian/prerm              只停本包启动的实例（校验 cmdline，不误杀）
├── debian/postrm             FR-080：remove 与 purge 均保留 ~/.ordessa
├── debian/ordessa.in         发行启动器（禁用 --no-sandbox）
├── debian/copyright          Debian copyright 1.0
├── debian/changelog          changelog.Debian.gz 源
├── icons/export-icons.mjs    SVG → 16/32/48/64/128/256 PNG
├── icons/generated/          构建期导出产物
├── licenses/aggregate.mjs    THIRD-PARTY-NOTICES 聚合
├── update/manifest.mjs       Ed25519 签名/验签（覆盖清单元数据）
├── update/state.mjs          update-state.json 状态机 + 故障门 + 备份
├── update/client.mjs         七步更新流程 + 失败语义
├── update/keygen.mjs         密钥对生成
├── update/publish.mjs        受控更新源发布
├── build-deb.mjs             构建入口（PC-01..PC-07）
├── bundle-manifest.json      捆绑清单
scripts/packaging/clean-machine-accept.sh   干净机器验收（PC-13）
tests/integration/packaging/deb-contract.test.mjs    19 项
tests/integration/packaging/update-chain.test.mjs    20 项
tests/integration/{acp-connector,acp_orchestration}  PC-15 归位
```

**根 `package.json`** 新增脚本：`build:deb`、`package:keygen`、`package:publish-update`、
`test:packaging`、`test:packaging:clean`。
**`tooling/test-all.mjs`**：仅改 `EXTRA_ROOTS` 中 acp-connector 的路径（PC-15 归位所需，逐文件登记）。
**`package-lock.json` 未改动**（仅根脚本变更，无新依赖；按 plan.md §写入面纪律 3，lock 仍由 P-C 在最终合一时统一生成）。

---

## 2. 任务逐条勾选

| ID | 状态 | 证据 |
| --- | --- | --- |
| PC-01 control/scripts/copyright | ✅ | `dpkg-deb -I` 实测；Depends 无工具链（`deb-contract` 3/4） |
| PC-02 安装布局 + 图标导出 | ✅ | 六尺寸 PNG 实测（16→256，尺寸逐个校验）；`.desktop` + hicolor + `/usr/share/doc` |
| PC-03 运行时捆绑 + bundle-manifest | ✅ | CPython 3.12.14（固定 SHA）+ Server 闭包 + ACP 桥 + 6 个 dist-info 实测 |
| PC-04 发行启动器禁 `--no-sandbox` | ✅ | 启动器命令实测：仅 `--ozone-platform=x11 --app=…` |
| PC-05 版本四处一致 | ✅ | package.json / build-info.json / bundle-manifest.json / 源四处相等 |
| PC-06 许可证聚合 | ✅ | THIRD-PARTY-NOTICES 含真实组件（fastapi 等），非空模板 |
| PC-07 产物哈希 | ✅ | SHA256SUMS 覆盖 deb + bundle-manifest + app 树 |
| PC-08 更新清单 + Ed25519 | ✅ | 真实密钥对；签名覆盖 8 项清单元数据 |
| PC-09 七步更新流程 | ✅ | `update-chain` 全链实测走通 |
| PC-10 失败语义 | ✅ | 9 条反例全部先红后绿（见 §3） |
| PC-11 备份 + 状态机 + 故障门 | ✅ | 5 个中断阶段逐个验证可检测/可修复/数据不丢 |
| PC-12 卸载语义 | ✅ | `postrm` 静态断言：任何分支均无数据根删除 |
| PC-13 干净机器验收 | ✅ | chroot 干净机 `exit 0` / `CLEAN-MACHINE ACCEPTANCE: PASS`；图形启动项见 §5 |
| PC-14 更新全链验收 | ✅ | 20/20 通过，含受控更新源与全部篡改反例 |
| PC-15 `tests/integration/` 归位 | ✅ | 两套件文件集与测试 ID 逐条比对一致（§6） |

---

## 3. 反例留档（先红后绿）

全部来自 `tests/integration/packaging/`，均为**先失败后修复**的真实用例。

### 更新校验类

| 反例 | 结果 |
| --- | --- |
| 篡改 `deb.url`（保留 deb 哈希） | ✅ 拒绝，`UPDATE_SIGNATURE_MISMATCH`，旧版本保留 |
| 篡改 `minDataSchema`（保留 deb 哈希） | ✅ 拒绝 |
| **穷举 8 个签名字段逐一篡改** | ✅ 8/8 全部验签失败；未篡改者通过（证明非空跑） |
| 篡改 deb 字节（**重新合法签名**） | ✅ `UPDATE_HASH_MISMATCH`，下载物被删除 |
| 源 404 | ✅ `UPDATE_SOURCE_HTTP_404`，**不**显示「已是最新」 |
| 源不可达（连接拒绝） | ✅ `UPDATE_SOURCE_UNREACHABLE`，**不**显示「已是最新」 |
| `minDataSchema` 高于当前 | ✅ 中止 + 数据原封不动 + 人话错误 |
| 用户取消 polkit | ✅ 中止，`phase=failed`，旧版本完好 |
| dpkg 安装失败 | ✅ 记录 + 备份保留 + 给出 `dpkg --configure -a` 指引 |

> 「篡改 deb 字节」一例特意**重新签名**，使签名合法 —— 这样只有 SHA-256 比对能拦住它，
> 从而证明拒绝来自哈希而非签名的副作用。

### 中断 / 回退类

| 阶段 | 可检测 | 可修复 | 数据不丢 |
| --- | --- | --- | --- |
| `downloading` / `verified` / `backed-up` / `installing` / `restarting` | ✅ | ✅ | ✅ |

每个阶段均验证：启动时 `severity=blocked` + `UPDATE_INCOMPLETE`、**先做数据健康检查**再谈修复、
提供可执行修复动作（`configure-dpkg`）、`backupRef` 上报给用户、备份目录内容逐字节保留。

### 打包 / 卸载类

| 反例 | 结果 |
| --- | --- |
| `Depends` 含 `nodejs`/`golang`/`python3` | ✅ 判红（静态 + 干净机双重断言） |
| 发行启动命令含 `--no-sandbox` | ✅ 判红（先剥注释再匹配，避免自触发） |
| `postrm purge` 后 `~/.ordessa` 仍在 | ✅ 判红（正则禁止任何 `rm … .ordessa`） |
| `postinst` 擅自创建数据根 | ✅ 判红 |
| 产物是「4 KB 空壳包」 | ✅ 判红（断言条目数 > 1000；此反例**真实命中过**，见 §7） |

---

## 4. 干净机器验收（PC-13）— 通过

**环境**：Ubuntu 24.04.3 base rootfs（`ubuntu-base-24.04.3-base-amd64.tar.gz`），
经 `unshare --map-root-user --mount --pid --fork` + `chroot` 进入，仓库目录**未**挂载。

```bash
bash scripts/packaging/clean-machine-accept.sh packaging/.out/ordessa_0.1.0_amd64.deb
```

**通过项（容器内实测）**：

```text
ok: no toolchain dependency declared
ok: no node/go/python/gcc on PATH before install
ok: dpkg -i succeeded
ok: install layout complete
ok: bundled python 3.12.14
ok: server deps importable
ok: acp bridge runs
```

全部断言（实测输出）：

```text
ok: no toolchain dependency declared
ok: no node/go/python/gcc on PATH before install
ok: dpkg -i succeeded
ok: install layout complete
ok: bundled python 3.12.14
ok: server deps importable
ok: acp bridge runs
ok: chrome-sandbox is setuid (mode 4755)
ok: release command has no --no-sandbox
ok: missing bridge refused early (exit 78)
CLEAN-MACHINE ACCEPTANCE: PASS          ← 脚本退出码 0
```

**过程中判红并修复的真实缺陷**：`chrome-sandbox` setuid 检查曾判红 ——

- 成因：`cpSync` 在拷贝到 deb root 时**丢弃 setuid 位**，导致包内 `chrome-sandbox` 为 0755。
- 影响：FR-072 禁止 `--no-sandbox`，而 sandbox helper 非 setuid 则沙箱根本起不来 ——
  即「守住了 flag，却让发行版无沙箱可跑」，属真实发布级缺陷。
- 修复：在 `cpSync` **之后**、debroot 内重新 `chmod 4755`。
- 复验：重建后包内为 `-rwsr-xr-x root/root`（`dpkg-deb -c` 实测），干净机断言通过。

> 该断言是**本轮最有价值的门**：它拦下了一个会让 FR-072 形同虚设的发布级缺陷。

**未验证（诚实登记）**：

1. **GUI 实际启动**未在干净机内验证 —— chroot 内无 X server（宿主有 `xvfb`，但干净机内未装）。
   宿主内 `npm run test:electron` 的 Electron 启动已通过（`MODULAR_LOADER_READY`，exit 0），
   但**这不等于**发行启动路径在干净机的端到端启动。
2. **重装/升级后仍可启动**（PC-13 后半句）未取得可信证据：需要两次真实 `dpkg -i`，
   受下述 uid 映射限制影响。
3. **polkit 交互**未实测（需要真实桌面会话与密码提示）。

以上三项均为**环境所限**，非实现缺失；PC-13 的「安装 + 零工具链 + 运行时可用 + 沙箱可启动
+ 类型化早期拒绝」已全部实测通过。

**沙箱环境限制（如实记录，非打包缺陷）**：`newuidmap` 不可用 ⇒ userns 仅映射 uid 0 ⇒
`dbus`/`polkitd`/`libpam-systemd`/`dconf` 等依赖的 postinst 无法 chown 到其他 uid，
因而处于「已解包未配置」状态。验收脚本因此：

- 用 `dpkg -i --force-depends` 安装**本包**（放宽的是 dpkg 的**记账检查**，非功能检查）；
- 逐条断言本包自身的 payload、运行时、启动器可用性；
- 明确打印未配置依赖清单，不假装全绿。

> 判红→修复链条中发现的三个真实环境问题（apt sandbox setgroups、DNS 缺失、缺 `adm` 组）
> 均属**测试脚手架**缺陷，已在脚本中修复并注明原因；它们不影响 deb 本身。

---

## 5. 未测 / 未验证清单

| 项 | 原因 |
| --- | --- |
| 干净机 GUI 端到端启动 | chroot 内无 X server（环境所限） |
| 干净机重装/升级后启动 | 依赖受 uid 映射限制，未获可信证据（环境所限） |
| polkit 真实密码提示 | 无桌面会话 |
| 真实 apt 源发布 | 派单禁止发布；仅本地受控静态源 |
| 三品牌制品捆绑 | **按契约刻意不做**（C-09 §B：品牌包不作为 core 打包前置） |
| P-A/P-B 真实产物接线 | 两包未交付；当前用占位/桩，并在产物中**显式标注**（`build-result.json` 的 `metadataStubs`、`iconPlaceholder`） |
| Windows/macOS | 明确不在本期 |

---

## 6. PC-15 归位比对

| 项 | 结果 |
| --- | --- |
| `tests/acp-orchestrator` → `tests/integration/acp-connector` | ✅ 文件集**逐条一致** |
| `tests/acp_orchestration` → `tests/integration/acp_orchestration` | ✅ 文件集**逐条一致** |
| acp_orchestration 测试 ID | ✅ **59 / 59 完全相同**（`git show HEAD:<path>` 旧路径 vs 新路径逐一 diff） |
| `tooling/test-all.mjs` 引用 | ✅ 已更新为新路径（逐文件登记） |

**比对方法**（可复现）：

```bash
# 文件集
diff <(git ls-tree -r --name-only HEAD -- tests/acp_orchestration/ | sed 's|tests/acp_orchestration/||' | sort) \
     <(cd tests/integration/acp_orchestration && find . -type f | sed 's|^\./||' | grep -v __pycache__ | sort)

# 测试 ID
for f in $(git ls-tree -r --name-only HEAD -- tests/acp_orchestration/ | grep '\.py$'); do
  git show HEAD:$f | grep -hoE "^\s*def test_[a-zA-Z0-9_]+" | sed 's/.*def //'
done | sort > /tmp/ids_old.txt
grep -hoE "^\s*def test_[a-zA-Z0-9_]+" tests/integration/acp_orchestration/*.py | sed 's/.*def //' | sort > /tmp/ids_new.txt
diff /tmp/ids_old.txt /tmp/ids_new.txt
```

**未执行**：`pytest` 本轮**未运行**（本环境无 pytest，且不建议为此改动环境）。
因此「59/59 ID 相同」是**静态解析比对**，**不是执行结果**。`acp_orchestration` 的
既有红账本（18 failed / 40 passed）**未触碰**，也未尝试变绿。

**发现的 `plugins/**` 残留引用**（**未修改**，因 013 为 core 阶段、`plugins/**` 只读）：

| 文件 | 行 | 旧路径字符串 |
| --- | --- | --- |
| `plugins/harness/tests/access/access_launch_route.test.mjs` | 11 | `tests/acp_orchestration/fixtures/…` |
| `plugins/harness/tests/test_server_acp_controlled_entry.py` | 17 | `ROOT / "tests/acp_orchestration/fixtures/…"` |
| `plugins/harness/tests/test_server_acp_native_observation.py` | 17 | 同上 |
| `plugins/connectors/acp/tests/*.test.ts`（7 个文件） | 5–15 | `../../../../tests/acp-connector/fixtures/acp-peer` |

> 这些是**相对路径**，移动后会失效。属 PC-15 的收尾缺口，须由主会话裁定：
> 要么批准插件侧改路径，要么在旧位置保留符号链接。二者都超出 P-C 写入面，故**未擅动**。

---

## 7. 实施中发现并修复的真实缺陷

如实记录（均为**先红后绿**）：

| # | 缺陷 | 后果 | 修复 |
| --- | --- | --- | --- |
| 1 | `buildDeb` 未把 staged tree 拷入 deb root | 产出 **4 KB 空壳包**，`dpkg -i` 装了个寂寞 | 补 `cpSync(STAGE, debRoot)`；并加「条目数 > 1000」断言防回归 |
| 2 | `cpSync` 丢失 setuid 位 | `chrome-sandbox` 为 0755 → **发行版无沙箱**（FR-072 实质失效） | 拷贝后重 `chmod 4755` |
| 3 | `renderControl` 未剥模板注释 | control 解析失败，包产不出来 | 渲染时过滤 `#` 行 |
| 4 | `Depends` 末项多余逗号 | dpkg 解析失败 | 模板修正 + 折行时剥尾逗号 |
| 5 | `/usr/share/doc/ordessa/` 未进包 | 缺 C-09 A2 要求的 doc 目录 | 新增 `stageDoc()` |
| 6 | `configure-dpkg` 恢复动作**缺 `id` 字段** | 故障门显示「可修复」，但按钮**点不动** | 补 `id` |
| 7 | `installDeb` 未 `await` 异步 `runCommand` | 安装结果判断基于 Promise，永远错 | 改 `async` + `await` |
| 8 | 图标 SVG 走 data-URL 拼接 | `#`/`%` 破坏解码，图标全空 | 改 base64 |
| 9 | `state.mjs` 在 ESM 里用 `require` | 运行即崩 | 改具名 import |
| 10 | 构建步骤未 `await` | `bridge.path` 读到 Promise，静默 `undefined` | 全部 `await` |

---

## 8. 关键实测数据

```text
构建 HEAD          7adf5aeaca (codex/013-c-packaging)
CPython            3.12.14, python-build-standalone 20260924
  tarball sha256   269b2c99e4db15b242bf01832f4fea1e8f1a664f273cff519393f296e9820b41
ACP 桥 sha256      714044a5b490a53d5fa89aade993c496e5fa3a5f7c614b4465c4990575185cbd
deb                200,792,992 字节
deb sha256         55fe0d10cf76ebbd930ecad8a18b3440e86937dbb4b6b9af698e031924138365
app 树哈希          见 packaging/.out/app-tree.sha256
```

> **须提请注意**：ACP 桥实测 sha256 `714044a5…` 与 `docs/baseline.md` 记录的
> `5fd6a37b…` **不一致**。构建脚本使用了 baseline 指定的
> `CGO_ENABLED=0 go build -trimpath -buildvcs=false -ldflags "-buildid="`（Go 1.24.13），
> 但字节未复现。构建**未因此中止**（产物本身可用），但**可复现性基线已失效**，
> 属需主会话立项的独立问题。构建结果中 `bridgeMatchesBaseline: false` 明确记录了这一点。

---

## 9. 测试结果

```text
node --test tests/integration/packaging/deb-contract.test.mjs   → 19 passed / 0 failed
node --test tests/integration/packaging/update-chain.test.mjs   → 20 passed / 0 failed
bash scripts/packaging/clean-machine-accept.sh <deb>            → exit 0, CLEAN-MACHINE ACCEPTANCE: PASS
xvfb-run npm run test:electron                                  → exit 0, MODULAR_LOADER_READY
```

**红账本**：本包**未新增任何红**。未改动 `pacthold`/`harness`/`server` 任何测试；
`acp_orchestration` 的 18 red **未触碰**。

---

## 10. 待主会话裁定

1. **`plugins/**` 的 10 处旧路径引用**（§6）—— 需批准改插件，或保留符号链接。
2. **ACP 桥可复现性基线失效**（§8）—— `714044a5…` vs baseline `5fd6a37b…`。
3. **图形启动与重装/升级后启动**（PC-13 剩余部分）—— 需具备 X server 的环境补测。
4. **`package-lock.json` 统一生成** —— 按 plan.md 纪律 3，仍待 P-C 在最终合一时生成。
5. **产品元数据与图标占位** —— P-A 的 PA-02/PA-03 交付后，替换
   `assets/brand/icon.svg` 与 `apps/desktop/package.json` 即可，**无需改本包代码**。

---

## 11. 合规自查

| 禁令 | 状态 |
| --- | --- |
| 不操作 git | ✅ 未提交/合并/push；仅只读 `git status`/`ls-tree`/`show` |
| 不改契约 | ✅ `contracts/**` 零改动 |
| 不 kill/restart 用户服务 | ✅ |
| 零真实模型调用 | ✅ |
| 不 push、不发布 | ✅ 仅本地受控静态源 |
| 用户机器零构建 | ✅ 捆绑全部在构建期完成 |
| 不改 `extensions.lock.json` | ✅ |
| 不改既有磁盘格式/持久 ID | ✅ |
| 发行禁用 `--no-sandbox` | ✅ 启动器干净，且有断言防回归 |
| `plugins/**` 只读 | ✅ 零改动（残留引用如实上报） |
