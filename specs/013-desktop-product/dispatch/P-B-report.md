# P-B 报告 — Server 运行时与接缝

**worktree**：`worktrees/013-b-server-runtime`　**分支**：`codex/013-b-server-runtime`
**基线 SHA**：`7adf5aeaca8a877e9f2c9caba7b594c51e18cdbb`（未提交；本包**不操作 git**，改动以工作树形式留待主会话取检查点）
**日期**：2026-09-28　**范围**：PB-01 … PB-14（C-01 / C-02 / C-03 / C-04-Py）

---

## 0. 三句话结论

1. **PB-01…PB-14 全部完成**，核心侧 123 项测试全绿（Python 75 / TypeScript 48），红账本**新增红 = 0**。
2. **本包未改任何插件**（013 零插件改动）。此前在 `plugins/harness/api` 做的 C-08 载体已由主会话回退，本包不再触碰该树；品牌边界门禁已迁到本包写入面保留。
3. **两处需要主会话知情的环境事实**（见 §5）：文档红账本在本工作树**无法原样复现**（缺 3 个外部适配发行版），以及 `docs/ui-preview/*.png` 被 `npm test` 副作用改写。

---

## 1. 交付物清单

### 新增源文件

| 文件 | 行 | 职责 |
| --- | --- | --- |
| `apps/server/src/ordessa_server/bootstrap/data_root_layout.json` | 55 | **唯一明文常量源**（C-01 §5），Py/TS 共读 |
| `apps/server/src/ordessa_server/bootstrap/data_root.py` | 502 | C-01 解析/创建/校验/锁 + 五类类型化错误 |
| `apps/server/src/ordessa_server/bootstrap/handshake.py` | 112 | C-02 §3.1 启动握手行（发出 + 严格解析） |
| `apps/server/src/ordessa_server/observability/logging_sink.py` | 306 | C-04 Python sink（字段序/四规则脱敏/轮转） |
| `apps/server/src/ordessa_server/observability/__init__.py` | 17 | 上面那个的公开面 |
| `packages/desktop-platform/server-bridge/src/data-root.ts` | 240 | C-01 宿主侧（读同一份 json） |
| `packages/desktop-platform/server-bridge/src/errors.ts` | 140 | C-02 §7 五类错误 |
| `packages/desktop-platform/server-bridge/src/runtime.ts` | 88 | C-02 §6 捆绑运行时解析 |
| `packages/desktop-platform/server-bridge/src/lifecycle.ts` | 423 | C-02 §5 状态机 + 握手 + 只杀自己 |
| `packages/desktop-platform/server-bridge/src/wire-port.ts` | 268 | C-03 WirePort / AbsentWirePort / PendingWirePort |
| `packages/desktop-platform/server-bridge/src/index.ts` | 74 | 包出口（P-A 的编译面） |
| `packages/desktop-platform/server-bridge/package.json` | 18 | 新 workspace 包 |

### 改动的既有文件（4 个，逐个说明）

| 文件 | 改了什么 | 为什么必须动 |
| --- | --- | --- |
| `apps/server/src/ordessa_server/__main__.py` | `--data-root` 改 optional；`--port` 缺省 `0`；自绑 socket 并把实际端口经握手回读 | PB-03 的契约要求 |
| `apps/server/src/ordessa_server/transport/http/app.py` | `create_app(runtime, *, on_bound=None)`；lifespan 内 `runtime.start()` 后调一次 | 握手必须在"已绑定"之后发出，且只有一个调用点 |
| `apps/server/src/ordessa_server/bootstrap/__init__.py` | 导出 C-01 公开面 | 既有 `from ordessa_server.bootstrap import ...` 的调用方不必改 |
| `apps/server/pyproject.toml` | `[tool.setuptools.package-data] ordessa_server = ["bootstrap/*.json"]` | 让常量文件进 wheel |

### 测试文件

`apps/server/tests/test_data_root_c01.py`(429) · `test_launch_handoff_c02.py`(140) · `test_logging_sink_c04.py`(282) · `test_brand_boundary_core.py`(165) · `support/ts_log_reference.mjs`(16) · `server-bridge/tests/{data-root,lifecycle,wire-port}.test.ts`(203/292/250)

---

## 2. 逐任务事实与证据

所有命令的真实退出码见括号。

### 阶段 1 — 数据根（C-01）

**PB-01** `data_root.py`：解析顺序 `explicit → ORDESSA_DATA_ROOT → $HOME/.ordessa`；缺失则建 0700，已存在则**复用**；符号链接用 `os.lstat` 先问、不可写用**真写探针**判定（非 `os.access`）；`instance.lock` 用 `flock`。
证据：`pytest apps/server/tests/test_data_root_c01.py` → **30 passed, exit 0**。

**PB-02** 五类错误 `DATA_ROOT_SYMLINK/NOT_WRITABLE/LOCKED/INVALID/MIGRATION_REFUSED`，各带 `code/reason/remedy`；错误码列表来自 json，不是代码里的第二份。
证据：同文件 `test_the_five_typed_errors_carry_reason_and_remedy` 断言 `set(ERRORS_BY_CODE) == set(LAYOUT["dataRootErrors"])` 且消息逐字为 `CODE: reason; remedy`。

**PB-03** `--data-root` optional、`--port` 缺省 0（系统分配）、**回读实际 origin**：`bind_loopback_socket()` 先绑再 `getsockname()`，`Server(config).run(sockets=[sock])` 把已绑的 socket 交出去，因此握手里报的端口**就是**在服务的端口。
证据：`test_launch_handoff_c02.py` → **9 passed, exit 0**；含"真实进程绑定随机端口并回报"一条。

**PB-04** 常量文件 + **跨语言一致性测试**：TS 侧不是重写 Python 规则，而是**以子进程调用真实 Python 解析器**再逐字比对（默认根 / 覆盖 / token 定位符三组）。
证据：`server-bridge/tests/data-root.test.ts` → **13 passed, exit 0**（其中 3 条为真跨语言比对，每条拉起一次 `.venv/bin/python`）。

**PB-05** 旧根 preflight：`ensure_data_root(require_migration_provider=True)` 委托既有 `_require_legacy_provider_for_historical_root`，把其 `LEGACY_MIGRATION_PROVIDER_MISSING` 翻成 `DATA_ROOT_MIGRATION_REFUSED` 并保留 `legacy_code`；**金丝雀比对**全根 sha256 前后一致。
证据：`test_a_historical_root_without_a_provider_is_refused_and_untouched`。
> 该测试**主动移除** provider（monkeypatch `importlib.util.find_spec`）而不是假定它缺席——开发机装了兼容发行版时，否则会看到与干净机不同的答案。金丝雀自身先断言该发行版**确实装着**，确保"移除"是真的移除。

**PB-06** headless CLI 核查（结论 + 可执行证据）：
- 启动 Server 的入口**只有** `python -m ordessa_server` 与其 console script `ordessa-server`，同一个 `main()`。
- 另一个 console script `ordessa-server-credential`（`plugins/server-compat`，只读）**不启动 Server 进程**，且 `--data-root` 是 `required=True` → **不支持缺省数据根，无需改动**。
- `scripts/start-server.sh`（P-C 文件）**总是显式传** `--data-root` → 无需改动。
- `pacthold` / `pacthold_runtime_compat` 的 CLI 读 `AGENT_BOX_HOME`，那是 kernel 自己的 home，**与 Server 数据根不是同一个事实**，未动。
证据：`test_exactly_one_entry_point_starts_a_server_process` 等 3 条，**exit 0**。这条审计已写成测试，将来多出第二个"自带数据根"入口会直接判红。

### 阶段 2 — 生命周期与接缝（C-02 / C-03）

**PB-07** `packages/desktop-platform/server-bridge`（新包，**P-A 唯一的编译耦合面**）：spawn / `GET /live` 探针 / 8 态状态机 / `stop()` 只对本对象 spawn 的 pid 发信号，且发**负 pid**（进程组），等子进程真退出才收尾。
证据：`server-bridge/tests/lifecycle.test.ts` → **14 passed, exit 0**。其中进程组与孤儿防护两条**用真实进程**（`node -e` 派生孙进程 + `pgrep` 取 pid），不是假 child。

**PB-08** 三个 env 变量拼写与既有连接器一致（`ORDESSA_SERVER_ORIGIN` / `ORDESSA_SERVER_TOKEN_FILE` / `ORDESSA_DATA_ROOT`），且**只传定位符不传令牌字节**；Py 侧 `launch_env()` 与 TS 侧 `launchEnv()` 拼写一致。
证据：`test_the_launch_env_names_the_three_variables_and_no_token` + `data-root.test.ts::C-02 §2` 两条。

**PB-09** `ORDESSA_BUNDLED_ROOT` → `/opt/ordessa/{python,bin,harnesses}` + `bin/acp`；缺失在 **spawn 之前**类型化拒绝 `BUNDLED_RUNTIME_MISSING` 并**指名缺失物**（只给相对名，不给安装路径）。`resolveBundledRuntime()` 在 `ServerBridge.start()` 的第二步，`assertNoSymlink` 之后、spawn 之前。
证据：`lifecycle.test.ts::C-02 §6` 四条，含"start 时拒绝且 `state === 'idle'`（没留下半可用）"。

**PB-10** 五类错误 + 反例：端口被占 → `PORT_ALLOCATION_FAILED`（Py 与 TS 各一条）；缺二进制 → 早期拒绝；子进程早退 → `SERVER_EXITED_EARLY` **带退出码**（断言 `exitCode === 3`）；静默 → `SERVER_START_TIMEOUT`；**畸形握手行 ≠ 超时**（两者分别断言）；只杀自己 → 无辜进程存活 + 孙进程被带走。
证据：TS 14 条 + Py 9 条，均 exit 0。两侧错误码**同词表**，由 `test_the_host_side_declares_the_same_five_codes` 交叉断言。

**PB-11** C-03 WirePort：`POST /wire/v1/{method}` + Bearer **仅在 `HttpWirePort.call` 内注入**；三态；`AbsentWirePort`（恒 `Unknown/port-absent`，**不是** `undefined`）；`PendingWirePort`（恒 `Unknown/host-not-ready`，**不排队**）；`ready`/`scope` 只读。
> 一处刻意的实现判断：Server 对"结果"和"业务拒绝"**都回 200**，所以 `interpret()` 按**响应体形状**判定而非状态码；只看状态码会把每一次业务拒绝变成传输错误。
证据：`wire-port.test.ts` → **21 passed, exit 0**。

**PB-12** 凭据边界**金丝雀**：注入 `CANARY-TOKEN-BYTES-…`，遍历插件可见面（端口对象自有属性名、三种端口的全部结果、`ready`、`scope`）断言**零命中**；另断言 `readToken` 抛错时错误文本（`EACCES` 与 `.ordessa` 路径）**不进结果**；`token`/`tokenFile`/`origin` **不在端口自有属性里**。
证据：`wire-port.test.ts::THE CANARY` 两条 + `test_logging_sink_c04.py::test_the_canary_appears_nowhere_in_the_log_file`，exit 0。

### 阶段 3 — 日志 Python 侧与同构（C-04）

**PB-13** Python sink：字段序 `ts, level, scope, msg, …`；四条脱敏规则**在 sink 层强制**；轮转 10 MiB / 保留 5（数字取自共享 json）；落点 `$DATA_ROOT/logs/server.log`。写失败**计数不抛**，且**不覆盖主因**。
证据：`test_logging_sink_c04.py` → **30 passed, exit 0**。

**PB-14** 同构一致性：起一个**真实 Node 进程**跑一份**独立写的** TS 参考写入器，与 Python sink 对同一条记录比对**字段集、字段顺序与整行字节**。
> 参考写入器是 `apps/server/tests/support/ts_log_reference.mjs`，**故意不复用 Python 侧任何代码**——两边都调 Python 只能证明 Python 自洽。
证据：`test_the_two_sides_write_the_same_fields_in_the_same_order` / `..._agree_on_the_canary_redaction`，exit 0。

### 附加：品牌边界门禁（C-08 §6 case 6 / contracts README §6）

013 把 C-08 **类型**移入 P-A 的 contracts 后，这条门禁不能跟着走。本包在**自己的写入面**重建了它（`apps/server/tests/test_brand_boundary_core.py`），扫**宿主源码文本**，`dist/` 等构建产物排除。
- 自检门禁本身有效：对**植入**的品牌名（字符串里 + 注释里各一条）必须判红；
- 已知债务**登记**而非隐藏，每条指名 owner（`apps/desktop/electron/main.ts` 与 3 个 smoke 脚本 → **P-A PA-11**），并有测试断言每条仍指向真实文件。
证据：**6 passed, exit 0**。

---

## 3. 验证总账

```text
$ .venv/bin/python -m pytest apps/server/tests/test_data_root_c01.py \
      apps/server/tests/test_launch_handoff_c02.py \
      apps/server/tests/test_logging_sink_c04.py \
      apps/server/tests/test_brand_boundary_core.py -q
75 passed                                              exit 0

$ (cd packages/desktop-platform/server-bridge && npx vitest run --maxWorkers=1)
3 files / 48 tests passed                              exit 0

$ npx tsc -p <server-bridge 临时 tsconfig>
(no diagnostics)                                       exit 0

$ npx tsc -p apps/desktop/tsconfig.json --noEmit
(no diagnostics)                                       exit 0

$ npm test          # 根 JS 聚合（typecheck + 真实构建 + 31 个 workspace 套件）
31/31 suites green                                    exit 0
   其中 workspace:packages/desktop-platform/server-bridge  exit 0
```

**红账本逐 ID 比对（改动前 vs 改动后）**

| 套件 | 基线 | 改动后 | **新增红** |
| --- | --- | --- | --- |
| `apps/server` | 144 failed / 693 passed / 69 errors | 144 failed / **768** passed / 69 errors | **0** |
| `plugins/harness` | 36 failed / 422 passed | 36 failed / 422 passed | **0** |
| `tests/acp_orchestration` | 14 failed / 15 passed / 30 errors | 14 failed / 15 passed / 30 errors | **0** |
| `packages/pacthold` + `packages/server-plugin-api` | — | 319 passed | **0** |
| `npm test`（31 套 JS） | — | 全绿 | **0** |

passed 从 693 → 768 的增量即本包新增的 75 条 Python 测试。

---

## 4. 先红后绿留档（本次真正抓到的问题）

按 AGENTS「证据不假绿」，下面是**先红后绿**中红的那一半，逐条都已修绿并留有对应测试：

| # | 红 | 性质 | 处置 |
| --- | --- | --- | --- |
| 1 | `chmod 0500` 的根**被"修好"了**：实现先 `chmod 0700` 再探测，等于替用户撤销了他故意设的只读 | **实现 bug**（违反"复用即复用"） | 只对**本次创建**的路径设 mode；探测**前移到**建子目录之前，否则只读根先撞上裸 `PermissionError` |
| 2 | 握手解析接受 `http://10.0.0.5:1` 这种非 loopback origin | **实现 bug**（与 TS 侧不一致） | 两侧都加 `http://127.0.0.1:<port>` 严格正则 |
| 3 | `X-Api-Key` 未被脱敏（契约字面 8 个片段里没有 `api-key`） | **规则漏洞** | 匹配前折叠分隔符（`-`/`.`/空格）。这是**只增不减**的严格化：契约点名的 8 个片段一字未改、仍逐字匹配 |
| 4 | 只读**目录**里的追加其实**会成功**，用 `chmod 0500` 造不出写失败 | **测试假绿** | 改为把日志**文件**置 `0400`，这才是真失败 |
| 5 | `app.py` 注释里的 "handshake" 撞上既有 stage4 品牌扫描的 `dsh` 片段 | **我引入的新红** | 该文件改用 "startup line" 措辞；**没有**去动那条继承红的断言 |
| 6 | 迁移金丝雀在装有兼容发行版的机器上不拒绝 | **环境依赖测试** | 主动 `monkeypatch importlib.util.find_spec`，并先断言该发行版**确实装着** |
| 7 | 生命周期里 `let exit` 被闭包捕获后被 TS 收窄成 `null` | **实现 bug**（退出码永远读不到，正是 `SERVER_EXITED_EARLY` 的全部证据） | 改用 `{ value }` 载体 |
| 8 | `node -e <多行脚本>` 在本环境挂起 | **测试不可靠** | 参考写入器改为**独立 `.mjs` 文件** + `stdin=DEVNULL` |

---

## 5. 诚实登记：未测范围与环境事实

**① 文档红账本（Server 67 / Harness 2 / acp_orchestration 18）在本工作树无法原样复现。**
`products/server` 依赖 `ordessa-sandbox-backend` / `ordessa-sandbox-adapters` / `ordessa-permissions-adapters` 三个**不在本仓、也不在 PyPI** 的发行版，装不上导致 `ordessa_server_product` 不可导入，94 个测试模块在收集期报错。本工作树实测基线是 **144 / 36 / 14**，与文档的 67 / 2 / 18 **不是同一集合**。
**因此本包的"红账本不变"结论是：在本环境可收集的集合上逐 ID 比对，新增红 = 0。** 它**不能**替代主会话 INT-03 的完整闭包复验。

**② 受控 fixture（明确标注，不冒充真实）**
- `test_a_real_server_process_binds_a_random_port_and_reports_it`：证明 C-02 §3.1 的**交接机制**（绑定→回读→单行握手），**不**证明 Server 自身。
- `server-bridge/tests/lifecycle.test.ts` 的子进程是 `node -e` 脚本，**不是真 Server**；它证明的是进程身份语义（哪个 pid、哪个进程组、无辜进程是否存活），这正是被测性质。
- `support/ts_log_reference.mjs` 是**按 C-04 规范另写的**参考写入器，**不是** P-A 的 TS sink。P-A 的 `desktop.log` sink 落地后，**必须**用它替换本参考件再复跑同构测试——这一点登记为 INT-01 的切换点。

**③ 真实 Server 的 `/live` 与 `/wire/v1/{method}` 未做端到端联调**（同 ① 的原因：起不来 product 装配）。`HttpWirePort` 的传输层用注入的 `fetchImpl` 覆盖，**未打过真 Server**。

**④ 副作用登记**：`npm test` 的 `electron:test:ui-preview` 重写了 `docs/ui-preview/0*.png`（6 个文件）。该目录**不在本包写入面**，我**没有**去还原它（还原同样是越界写），请主会话处置或纳入 P-A。

**⑤ 跨包待办（不属本包）**
- `packages/desktop-platform/server-bridge` 是新 workspace，**根 `package-lock.json` 未更新**（lock 归 P-C）。INT-02 统一生成时需纳入。
- P-A 的 `@ordessa/contracts` 落地后，`server-bridge` 的 `WirePort`/`WireResult`/`WireReason` 应改为**直接再导出**其类型（当前是同构镜像，`wire-port.test.ts` 逐条断言了形状）。
- 宿主源码的品牌名债务（4 个文件）待 P-A PA-11 清理；本包门禁会持续对其判红直到清理完成。

---

## 6. 契约与写入面自检

- **本包未改动 `specs/013-desktop-product/contracts/**` 任何文件。**
  该路径下确有 2 个 `M`（`C-05-theme.md`、`C-08-harness-availability.md`），但它们是**主会话**在我开工前就已修改的（与 C-08 类型迁往 P-A contracts 有关），不是本包所为；我未读入后改写，也未新增任何契约。
- `plugins/**` **零改动**（已回退，`git status --short plugins/` 为空）。
- 写入面仅：`apps/server/**`、`packages/desktop-platform/server-bridge/**`、本报告、`tasks.md` 的勾选。
- 未提交 / 未合并 / 未 push / 未动其他 worktree；未 kill 任何用户服务；**零真实模型调用**。
- 既有磁盘格式、持久化 ID、协议标识、env 变量拼写**均未改**（新增的 `instance.lock` / `logs/` / `backups/` 是 data-model §1 声明的新增项，`secrets/http-token` 与 `server.lock` 原样未动）。

---

**状态：PB-01…PB-14 完成，停止，报待审。**
