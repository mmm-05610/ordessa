# Harness 单包收口 — 2026-09-24

工作树：`worktrees/harness-desktop-002/bc-native`，起点 `e996e9d2`。
用户范围：五个 Harness 包合成 `agent-box-harness`，暂不改上层。

## 结果

- 仅保留 `plugins/agent-box-harness/` 一个目录、一份 pyproject、一套实现。
- 原 harnesses 的品牌模块、registry 数据、runtime、deploy、third_party 和测试迁入。
- dsh/qwen/kilo 的真实实现迁到 `src/agent_box_harness/<brand>/`。
  三家 deploy 重复文件逐字节相等后只保留一份；修正 production.py 的资源根层级。
- 历史 Python 名称只剩兼容入口，映射到同一个 canonical 模块，不复制类或注册表。
  全模块、双导入顺序及 canonical spec 保持有测试。
- 六个既有插件注册项统一由新 distribution 提供，没有新增品牌注册或能力。
- 更新 root pyproject 依赖名、CI、构建/启动脚本和测试中的路径；
  `git diff -- src` 为空，上层产品逻辑没有修改。
- 未修改 registry TOML 字节，保留原摘要；其中旧路径注释属于历史证据。
- 原先四个未提交文件（snapshot_seams.test.mjs、vendor PATCHES.md、SOURCE.json、
  bridge/src/acp-client.js）随目录移动保留，本次未编辑它们。
- 不动其他 runtime/sandbox 等插件；不扩 Profile/provider、不发模型请求、
  不读取凭据、不启停现有服务、不 push、不合并 main。

## 验证

1. `pytest plugins/agent-box-harness/tests`：267 passed / 1 failed / 3 skipped。
   唯一失败 `test_skill_projection::test_all_five_registry_targets_are_lossless_and_read_only`：
   测试硬编码 `/runtime/home/skills/review`，Claude 实际为
   `/runtime/home/.claude/skills/review`。未改该行为或放宽断言。
   从 `git archive e996e9d2` 提取 src/plugins/scripts/pyproject 到隔离目录复跑原两套：
   262 passed / 同一项 failed / 3 skipped。新增 5 个单包测试通过，无新增失败。
2. `node --test plugins/agent-box-harness/tests/harness_remote/*.test.mjs`：43/43。
3. Server 九套接线回归：184 passed / 6 skipped（缺本机工具/工件），没有失败。
   套件：test_native_execution_seam_hd002、test_native_cli_hd002、test_harness_sidecar、
   test_sidecar_native_driver、test_sidecar_upstream_cause_150、test_harness_capability_integration、
   test_hermes_production_chain、test_native_materialization_093、test_native_materialization_093_stage3。
4. 新 wheel 构建成功；隔离安装后六个 entrypoints 可加载、8 个 registry 声明可读，
   旧名称与 canonical 对象相同。仅证明 Python wheel；ACP 二进制、npm runtime
   仍沿用原有独立工件构建方式，未声称 wheel 自动带齐真实 Agent 环境。
5. `git diff --check` 通过。未跑真实模型对话。

Python 测试用临时 uv 环境；Server 回归使用 FastAPI 0.115.14 + httpx。
初次新环境缺 HTTP 测试客户端造成收集错误，补足测试依赖后才获得上述结果。

## 启动路径变化

原命令的其他参数不变，只将插件根换成：

```sh
--plugin-root "$PWD/plugins/agent-box-harness"
```

源码兼容不等于旧安装元数据自动更新。现有已安装环境如需迁移，应先卸载旧四个
distribution 再安装新包，避免重复 entrypoints；本次没有改用户安装环境。
旧包壳和重复别名文件已移除，完整历史可从起点提交恢复。改动保留在此工作树待检视。

---

# 追加：内部目录按"接入运行 / 可选安装打包"分区 — 2026-09-24（同轮第二步）

在同一批未提交改动上继续，仍不改上层产品逻辑、不动其他插件。

## 迁移对照

| 原路径 | 新路径 |
| --- | --- |
| `runtime-claude/{package.json,package-lock.json}` | `packaging/claude/` |
| `runtime-dsh/…` | `packaging/dsh/` |
| `runtime-kilo/…` | `packaging/kilo/` |
| `runtime-qwen/…` | `packaging/qwen/` |
| `runtime/package.json`（共用 Codex/Pi 依赖钉版） | `packaging/codex-pi/package.json`（第三步已按品牌拆开，见文末） |
| `runtime/package-lock.json` | `packaging/codex-pi/package-lock.json`（同上） |
| `runtime/vendor/*.tgz` | `packaging/codex-pi/vendor/`（同上） |
| `runtime/artifacts/SBOM.json` | `packaging/codex-pi/artifacts/`（同上） |
| `deploy/codex/codex-deepseek-setup.sh`、`official-script.json` | `packaging/codex/`（第三步起在 `packaging/codex/provenance/`） |
| `deploy/opencode/driver-native.mjs` | `runtime/drivers/opencode-native.mjs` |
| `runtime/{worker-entry,native-driver,profile_extensions,subagent-bridge}.mjs`、`capability_declarations.json` | 原地不动 |
| `deploy/<品牌>/*.yaml|json|toml` 配置模板 | 原地不动（运行链读取） |
| 旧隔离 guard（7 个） | 原地不动，`deploy/README.md` 标为兼容资产 |

`runtime/package.json` 重建为只含 sidecar 视图 ESM 包根信息（`name/private/
version/type/engines`），不再携带 `dependencies`/`overrides` 钉版。

同步改的消费方：`opencode/production.py`、`codex/production.py`；
`build-{codex,pi,claude,dsh,kilo,qwen}-runtime-artifact.mjs` 的 npm 根；
`harness-install-set.py` 的 `npm ci` 目录（初版只按品牌同名拼接，
`pi`/`claude-code` 因此仍指向不存在的目录——已见下文"收口补漏"）；
`artifact_presence.py` 的
`acp-npm-closure` 路径与准备缺口文案；插件测试 6 个文件；
`tests/server/test_sidecar_native_driver.py` 的 driver 路径。

## 运行链 / 打包链边界

运行链读的只有：`runtime/**`、`deploy/<品牌>` 模板、
`third_party/harness_remote/**`，以及部署文档里显式给出的
`adapter.command/args/driver` 与 `projectionFiles[].source`。
`packaging/**` 在运行链里零引用：没有任何代码读它、没有安装管理器、
缺 `node_modules` 也不会触发自动 `npm ci`。这条以 grep 复核：
`grep -rn packaging src/agent_box plugins/agent-box-harness/src` 只剩注释/文档
指路，无一条读路径。搬进 `packaging/codex/` 的官方脚本对
（`codex-deepseek-setup.sh` + `official-script.json`）是**取证资产**：
`OFFICIAL_SCRIPT` 只被 `tests/test_codex_production_template.py` 读，
`official_script_metadata()` 无任何部署期调用方，因此它既不进投影、
也不进启动路径。

## 两处必须报告的既有契约（本轮未自行扩大改动）

1. **`src/agent_box/server/execution/sidecar.py:263` 硬编码 `runtime/package.json`。**
   这是 E-INC1a 留下的"冻结兼容壳"（注释：这些 view-layout 字面量属 Harness，
   待 INC1b 的 closure 声明落地才移除），而生产入口
   `bootstrap/runtime.py:955` 正是走 `closure=None` 这条壳。因此
   `runtime/` 必须继续存在一个 `package.json`，不能把它整个搬进
   `packaging/codex-pi/`。本轮做法：钉版数据搬进 `packaging/codex-pi/`，
   `runtime/package.json` 降级为纯视图包根（无依赖声明），运行链因此不再
   携带安装期数据。**最小彻底处理方案**（需上层授权，二选一）：
   (a) 由 Harness 侧产出 `closure=[(source,target),…]` 声明、
   `runtime.py:955` 显式传入，壳随之删除；(b) 把壳里这一行改成显式常量。
   两者都改 `src/agent_box`，且 (a) 会牵动 `test_e_inc1a_matrix_pins.py`
   对该壳的字面量计数。
2. **`deploy/hermes/bootstrap.py` 与 `sitecustomize.py` 归属无法确定，保留原位。**
   见 `deploy/README.md` §4：内容是 guest 里执行的代码，唯一读取方是打包器，
   且工件清单会写死 `source: "deploy/hermes/<file>"`
   （`build-hermes-runtime-artifact.mjs:1053`）、
   `hermes-production-chain-gate.py:693` 断言该前缀。搬迁必然改动记录或
   说谎，不属于"纯移动"。曾实际试搬，确认上述两点后已原样回退。

## 验证（本步骤实跑）

1. `pytest plugins/agent-box-harness/tests`：**267 passed / 1 failed / 3 skipped**，
   与迁移前逐项一致。唯一失败仍是已登记的
   `test_skill_projection::test_all_five_registry_targets_are_lossless_and_read_only`
   （硬编码 `/runtime/home/skills/review` vs Claude 实际
   `/runtime/home/.claude/skills/review`），断言原样保留，未为变绿改行为。
2. `node --test plugins/agent-box-harness/tests/harness_remote/*.test.mjs`：**43/43**。
3. `node --test plugins/agent-box-harness/tests/*.test.mjs`（含 6 个改过 driver
   路径的 opencode 测试）：**45/45**。
4. Server 九套接线回归：**184 passed / 6 skipped**，与迁移前记录一致
   （首轮 2 个 `test_native_cli_hd002` 失败是临时环境缺 `uvicorn`，补齐依赖后通过；
   非本改动引入）。
5. `python3 scripts/server-round1/artifact_presence.py`：`sidecar-entry=present`，
   `acp-npm-closure=ABSENT plugins/agent-box-harness/packaging/claude/node_modules/…`
   —— 新路径生效，缺工件仍按既有"缺工件不为绿"处理。
6. 未验证项（如实列出）：六个 `*-production-chain-gate.py` 与
   `build-*-runtime-artifact.mjs` 的真实构建**未执行**——需要真实
   `node_modules` 闭包/真实 Agent CLI/bwrap 内的 Worker，本树没有这些工件。
   这些脚本里被改到的字符串只经 grep 与静态检查确认。
7. `node --test scripts/server-round1/build-pi-runtime-artifact.test.mjs
   scripts/server-round1/build-opencode-authorization.test.mjs`：
   **18 passed / 1 failed / 1 skipped**。该失败是既有/环境性的，非本改动引入：
   `build-opencode-authorization.test.mjs:139` 期望
   `OPENCODE_SOURCE_NOT_RESOLVED` 实得 `OPENCODE_SOURCE_SYMLINK`，判的是
   `authorizeBinary` 对符号链接真实路径的分类，与本目录树中被移动的路径无关
   （该文件唯一含 "runtime" 的断言是 guest 路径
   `/runtime/bin/opencode`）。未为变绿改动它。


## 收口补漏（用户指出两处路径遗漏后，同日第二轮）

结构方向不变，只补两处路径遗漏，不重做架构。

1. **`harness-install-set.py` 的 npm 根映射改成一处显式表 `NPM_ROOTS`。**
   上一版按"家族名 == 目录名"拼接，`pi` 落到不存在的 `packaging/pi/`、
   `claude-code` 落到不存在的 `packaging/claude-code/`；`npm ci` 的外层条件
   是 `is_dir()`，于是这两家**静默跳过依赖安装**，再由 builder 报适配器缺失。
   迁移前同样如此（`runtime-pi/`、`runtime-claude-code/` 都不存在），属旧映射
   遗留。现按真实归属写死：`codex`+`pi` → `codex-pi/`（锁未拆）、
   `claude-code` → `claude/`、`dsh`/`qwen`/`kilo` 各自一份；
   `hermes`、`opencode` 登记为"无 npm 根"（`build-hermes-runtime-artifact.mjs`
   里 `node_modules` 零命中，opencode 钉单文件二进制）。表与 6 个 builder 的
   `DEFAULT_SOURCE` 逐条对齐，`packaging/README.md` 也写明"家族 id ≠ 目录名"。
2. **两个验证脚本改读安装位置。** `harness-handshake-40c.mjs:26` 与
   `model-validation-42d.mjs:19` 原来都从 `runtime/node_modules` 找适配器，
   安装位置迁走后必然误报缺失。40c 里该常量的 4 处用法全是 `node_modules`
   根（无一处指向 `runtime/` 的桥代码），故整枚常量更名 `npmRoot` 并指向
   `packaging/codex-pi/`；42d 只有 `piAdapter` 一条依赖它，同改。
   全仓再扫：代码里已无 `runtime/node_modules`、也无
   `runtime-<品牌>` 引用，剩余命中只在 `docs/**` 的历史记录中。

### 第二轮实跑

- 逐家打印 `NPM_ROOTS` 解析结果：6 个有 npm 根的家族全部指向**存在**的目录，
  `hermes` 正确落在"无 npm 根"。
- `node --check scripts/server-round1/harness-handshake-40c.mjs` 通过；
  两个脚本里 `runtime` 标识符零残留（防漏改造成 ReferenceError）。
- `node --test scripts/server-round1/model-validation-42d.test.mjs`：
  **2 passed / 2 failed**。两个失败是 `pi`、`hermes` 的
  `outputLimitTokens`/`maxTokens` 期望 64 实得 8192 —— 已提交的 Order 108
  生产默认与 42d 干跑形状之间的既有张力。`git diff HEAD` 显示该脚本本轮
  只改了 3 行路径，8192 是 HEAD 既有内容，失败与本改动无关；
  与已登记的 Skill 路径失败同类，保留断言、未为变绿改行为。
  （此前未跑过这套，故未记入上一节，记于此。）
- 重跑 `pytest plugins/agent-box-harness/tests`：**267 passed / 1 failed /
  3 skipped**，与上表逐项一致。
- `git diff --check` 干净；仍不夹带提交，全部改动留在工作树待检视。

## 第三步：按品牌真正拆开 Codex/Pi 的 npm 根

用户给出目标布局后执行。只动打包链，不动上层、不动协议/会话/审批/Profile。

### 现况目录

```text
packaging/
  codex/{package.json,package-lock.json}     codex/vendor/*.tgz
                                             codex/artifacts/SBOM.json
                                             codex/provenance/{codex-deepseek-setup.sh,
                                                              official-script.json}
  pi/{package.json,package-lock.json}        pi/vendor/*.tgz  pi/artifacts/SBOM.json
  claude/ dsh/ kilo/ qwen/                   （各家清单+锁，未动）
```

`packaging/codex-pi/` 已不存在。

### 拆法：剪已评审的子树，不重新解析

直接从**已评审的那把共用锁**里按 npm 的"最近 `node_modules` 优先"解析规则
（与两个 builder 用的是同一条规则）算出各家可达集，逐条**原样搬**：
保留条目的 `version`/`resolved`/sha512 `integrity` 一个字节都不改。

| 家 | 锁条目 | 直接依赖（未变） | vendor | SBOM |
| --- | --- | --- | --- | --- |
| codex | 25 | `@agentclientprotocol/codex-acp` 1.1.14 | codex-acp 1.1.14.tgz | 25 条 |
| pi | 325 | `@automatalabs/pi-acp` 0.5.0 | pi-acp 0.5.0.tgz | 325 条 |

25 + 325 = 349 + 1，共用锁条目总数 349，交集恰好只有 `node_modules/zod@4.6.4`
一条，两家各留一份同版本。`overrides` 里两家都保留
`@agentclientprotocol/sdk` 1.3.0：共用锁中两个适配器各自的嵌套 sdk 就是被它钉住的。

### 传递依赖变化的核对（这是关键证据）

1. `npm ci` 接受两把新锁（dry-run 与真装都过），且 **`npm ci` 未改写锁**
   （装完 `diff -q` 与签入字节相同）。
2. 用两把新锁并集**反向重建**共用锁：349 条、无键冲突，`npm ci` 装出 336 包
   （平台可选包按本机过滤），说明两把锁能无损还原成拆前那把。
3. **工件树摘要逐字节相同**：同一台机器上分别用拆后根与重建的共用根跑真实
   builder——
   `codex`：`sha256:9051b844…209f2ca1`（两边一致，20 包）
   `pi`：`sha256:afe238d3…afa8420f`（两边一致，317 包）
   即拆锁**没有改变任何交付内容**，唯一差别是清单里的审计字段
   `excluded.codexOnlyPackages` 从 19 条变 0 条（Codex 的包根本不在 Pi 的根里了）
   和 `sourceLockDigest` 随锁内容变化。

### 因此需要改的 builder 逻辑（一处）

`build-pi-runtime-artifact.mjs` 原来从同一个根里算 Codex 闭包来证明"Pi 工件不
带 Codex 的包"，拆根后该闭包不存在会直接 `PI_CLOSURE_ENTRY_MISSING`。改成与
Codex 构建器早已有的对称处理：闭包缺失即不可能泄漏，返回空并继续；
按名字排除的 `EXCLUDED_PACKAGES` 断言照旧无条件执行。Codex 侧无需改
（它本来就容忍 Pi 缺失）。

### 同步改的消费方

`build-codex-runtime-artifact.mjs`/`build-pi-runtime-artifact.mjs` 的
`DEFAULT_SOURCE`；`harness-install-set.py` 的 `NPM_ROOTS`
（`codex`→`codex`、`pi`→`pi`，注释删掉"锁未拆"）；
`harness-handshake-40c.mjs` 改成按家取根（`npmRoots.codex` / `npmRoots.pi`）；
`model-validation-42d.mjs` 的 `piAdapter` 取 `packaging/pi/`；
`codex/production.py` 的 `OFFICIAL_SCRIPT(_METADATA)` 指到
`packaging/codex/provenance/`；文档 `packaging/README.md`（重写）、
`deploy/README.md` §3、插件 `README.md`。

移动过的 4 个二进制/证据文件 sha256 逐个比对：拆前拆后一致。

### 第三步实跑

- builder 单测：`node --test build-{codex,pi}-runtime-artifact.test.mjs` **20/20**
  （合成夹具仍装着 Codex，故 `available` 分支与
  `excluded.codexOnlyPackages` 断言照样命中）。
- 用签入字节端到端：两把锁各自 `npm ci` → 两个真实 builder 通过，
  摘要见上；`codex` 工件 529 条目、`pi` 工件 15458 条目。
- `pytest plugins/agent-box-harness/tests`：**267 passed / 1 failed / 3 skipped**
  （唯一失败仍是已登记的 Skill 路径断言）。
- `node --test plugins/agent-box-harness/tests/*.test.mjs` **45/45**；
  `tests/harness_remote/*.test.mjs` **43/43**。
- Server 九套接线回归：**184 passed / 6 skipped**，与基线逐项一致。
- `node --test scripts/server-round1/model-validation-42d.test.mjs`：
  **2 passed / 2 failed**，与拆锁前完全相同（Order 108 默认输出上限 8192
  vs 该测试的 64，与路径无关）。
- `artifact_presence.py`：`sidecar-entry=present`，
  `acp-npm-closure=ABSENT plugins/agent-box-harness/packaging/claude/…`。
- `NPM_ROOTS` 逐家解析：6 家有根的全部指到存在目录，hermes 仍为"无 npm 根"。
- 代码里已无 `codex-pi` 字样；`git diff --check` 干净。

### 仍未验证

`harness-install-set.py` 的完整一次跑（还要 Worker bundle、Rust 侧与
`--artifact` 复用路径）与六个 `*-production-chain-gate.py` 仍未执行——
本树没有那些工件，也无需真实模型调用。`npm ci` 走的是锁里记录的
`registry.npmmirror.com` URL；拆锁没有改动任何 `resolved`/`integrity`。

## 补记（2026-10-01，specs/021）— 上文的两处常量已变

上文「表与 6 个 builder 的 `DEFAULT_SOURCE` 逐条对齐」与「
`build-codex-runtime-artifact.mjs`/`build-pi-runtime-artifact.mjs` 的
`DEFAULT_SOURCE`」记录的是 **2026-09-24 当时**的状态，正文按历史保留不改。
截至 2026-10-01 的实际状态，两处需要更正，避免后来者去找已不存在的常量：

- `build-hermes-runtime-artifact.mjs` 的 `DEFAULT_SOURCE` **已删除**。它当时
  指向 `/home/maoqh/.local/lib/python3.12/site-packages`，即把某台机器的家目录
  写进了仓库。现在改为 `SOURCE_ENVIRONMENT_VARIABLE`（`ORDESSA_HERMES_SOURCE`），
  未声明时是 `HERMES_SOURCE_UNSET` 拒绝，不做任何路径或 `PATH` 猜测。
- `model-validation-42d.mjs` 与 `build-opencode-authorization.mjs` 里同类的
  `/home/maoqh/...` 硬编码同样已改为按 family 声明、缺失即拒绝。

其余 builder（codex / pi / claude / dsh / kilo / qwen）的 `DEFAULT_SOURCE`
是 `path.join(REPO, "packaging", "<family>")`，仓库相对路径，本来就正确，未改。
