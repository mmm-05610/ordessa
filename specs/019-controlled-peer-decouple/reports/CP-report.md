# 019 CP · 受控对端解耦 报告

- 线：CP（worktrees/019-cp，分支 `codex/plugin-harness`，基=main@`f81218c51f`）
- 写入面自查：仅 `plugins/harness/**` 与本报告；`specs/019.../spec.md`、
  `tasks.md`、`dispatch/` 未动（勾选留给主会话）。
- 状态：CP-1…CP-5 全部落地，相关测试面全绿（数字见 §4）。

## 1. 逐项对照

| ID | 状态 | 落点与证据 |
| --- | --- | --- |
| CP-1 白名单改摘要制 | **完成** | `runtime/controlled-peers.mjs`（新）：`BUILTIN_CONTROLLED_PEERS` 以构建期常量钉两条 sha256；`access-entry.mjs` 的受控对端分支改为 `selectControlledPeerLaunch()`——读取候选文件实算 sha256 比对。条目结构 `{sha256, file?, harness?}`：`sha256` 判定，`file` 仅诊断（拒绝详情里点名哪份内容、绑哪个品牌），`harness` 品牌绑定（无此字段=任意已发现品牌，与旧行为同）。摘要清单生成方式与更新流程写入 `plugins/harness/README.md` §受控对端白名单（sha256sum 命令 + "只改 fixture 不改表必红"的守卫说明）。 |
| CP-2 注入端口 | **完成** | 环境变量 `AGENTBOX_CONTROLLED_PEER_ALLOWLIST`（`controlled-peers.mjs` 导出常量名）：JSON 数组、条目 schema 同内置表（`sha256` 必填，`file`/`harness` 可选，**无 command/args/driver 字段**——名单条目仍是文件描述，不构成命令面）。注入**整表替换**内置（优先），空数组=合法的"什么都不允许"；解析失败/条目非法 fail-closed：放行集为空 + `CONTROLLED_PEER_ALLOWLIST_INVALID` 拒绝，绝不静默回退内置表。默认（未注入/空串）=内置摘要表。 |
| CP-3 三测试跟随 | **完成** | ① `tests/access/access_launch_route.test.mjs`：别名测试重写为摘要语义（正例：别名+搬家副本→过；负例：一字节篡改→拒且 OS 侧无进程证据）；新增注入端口行为测试（注入生效/整表替换/坏声明 INVALID/空数组拒绝一切）。② `tests/access_entry_staging.test.mjs`：staged 工件里源码树 peer 改为**按内容接受**（staged 闭包外路径、`launch.source=="controlled-test-peer"`、released:true）+ 一字节篡改副本→`CONTROLLED_PEER_MISMATCH`。③ `tests/test_server_acp_controlled_entry.py`（2→4 测）与 `tests/test_server_acp_native_observation.py`（registry 级全链骑在搬家副本上）：含任务点名的两个负例方向——**内容篡改→拒**（`test_tampered_peer_content_is_refused`，且无 spawn 证据）、**路径搬家→过**（`test_moved_peer_with_identical_content_connects`）。 |
| CP-4 边界守卫（本侧版） | **完成** | `tests/controlled_peer_allowlist.test.mjs` 第一测：扫 `runtime/ harnesses/ src/ api/src`（排除 `__pycache__`/`node_modules`），regex 用 core 建议的任意形态模式 `tests[/"'.  ]*(acp_orchestration|acp-connector|integration)`，违例逐文件：行列出。配套清理：`src/ordessa_harness/server_acp/__init__.py` docstring 里唯一一处 `tests/acp_orchestration` 提及改为不带路径的表述——守卫在产线上抓到的唯一命中就是它。 |
| CP-5 report | **完成** | 本报告。 |

## 2. 行为等价证据（红线："A/B 并存期行为不弱于现状"）

不变式逐条（全部有测试钉住）：

| 场景 | 旧行为（路径制） | 新行为（摘要制） | 证据 |
| --- | --- | --- | --- |
| 未开 `--controlled-test-peer` 而请求 fixture | `ADAPTER_LAUNCH_MISMATCH` | 同左，未动 | access_launch_route "explicit controlled entry mode" 前两段 |
| 模式开、命令非本入口 node | `CONTROLLED_PEER_MISMATCH` | 同左 | access_launch_route arbitrary/alias 段；route 注入测试 |
| 内容不在名单（任意路径） | 拒 | 拒（更强：路径无意义） | staging 篡改负例；route 篡改负例；py 篡改负例 |
| 名单内容 + 错品牌（orchestration peer ≠ pi） | 拒 | 拒，拒绝详情点名品牌绑定 | route 测试 codex 段；注入测试 wrongBrand 段 |
| controlled_harness 同内容别名 | 过（请求 realpath 后比较） | 过（摘要相同） | route 正例 |
| orchestration peer 原路径 | 过 | 过 | py `test_explicit_controlled_mode_*`；acp_orchestration 全链 20/20 |
| args 非 1 个、文件缺失/不可读 | 拒 | 拒（读失败=无法出示内容=mismatch） | selectControlledPeerLaunch 单元路径；route 注入段 |

**唯一有意行为差（一条，且是本 spec 的目的）**：orchestration peer 的**别名/
搬家副本**从"拒"翻为"过"。旧代码对该条目 `exactPath:true`（字符串全等），
别名必拒；spec 019 A 案明确以内容为界（CP-3 点名"路径搬家→过"为正例）。
不弱于现状的论证：信任锚是**字节内容本身**——同内容的副本执行起来与原件
无差别，旧 exactPath 拒的只是"同一份字节的另一个路径名字"；而"内容不符"
拒集严格变大（旧制下搬到新路径的原件会被拒——那是被解除的误拒，不是被放
宽的防线）。其余一切拒集不变或更严。

注入端口不放宽任何东西：schema 无命令面、命令仍须是本入口 node、坏声明
fail-closed（route 注入测试钉住"注入生效时内置表不合并回退"与"坏声明连
内置内容也拒"）。

## 3. AR-1（core 装配注入）对接说明

core/products 侧对齐后接线时：

1. **注入面**：给 access-entry 子进程的环境加
   `AGENTBOX_CONTROLLED_PEER_ALLOWLIST=<JSON 数组>`。数组整表替换内置名单，
   因此**注入表必须自带全部需要放行的条目**（不会与内置表合并）。
2. **条目 schema**：`{"sha256": "<64 位小写 hex>", "file": "<诊断标签，可选，≤256 字节无控制符>", "harness": "<品牌绑定，可选>"}`。未知字段、非对象条目、
   非 hex 摘要、超长/带控制符标签都使**整表**作废（fail-closed，空放行集 +
   `CONTROLLED_PEER_ALLOWLIST_INVALID`），装配侧拿到的拒绝详情里有具体原因。
3. **优先级**：注入 > 内置；空串=未注入；空数组=显式"全拒"。
4. **不做的事**：注入不改变命令校验（必须等于入口自身 node）、不引入参数/
   命令字段、不改变 `CONTROLLED_PEER_MISMATCH` 的拒答词汇。Python 侧
   `AccessEntryTransport(controlled_test_peer=True)` 的既有通路不变；AR-1 若
   要透传注入，加一个入参把该环境变量并进 `entry_environment` 即可，无需改
   JS 侧。

## 4. 测试证据（实测，2026-09-29）

| 门 | 命令（cwd=worktree 根，除注明） | 结果 |
| --- | --- | --- |
| 守卫+注入单测 | `node --test plugins/harness/tests/controlled_peer_allowlist.test.mjs` | 6 pass / 0 fail |
| route+staging（mjs） | `node --test plugins/harness/tests/access/access_launch_route.test.mjs plugins/harness/tests/access_entry_staging.test.mjs` | 9 pass / 0 fail（仓库根与 plugins/harness 两个 cwd 都跑过） |
| 全部 mjs 套件 | `node --test tests/access/*.test.mjs tests/*.test.mjs tests/harness_remote/*.test.mjs`（cwd=plugins/harness） | 128 pass / 0 fail |
| harness Python 整包 | 主仓 venv + `PYTHONPATH=plugins/harness/src` `pytest plugins/harness -q` | **461 passed / 2 failed / 3 skipped**；2 失败=继承红（`tests/install/test_acp_schema_drift_target.py` 两测，npm 闭包，基线已登记）。对照主仓同命令：459 passed / 同 2 failed 同 ID——**增量 +2 = 本线新增 Python 负例，零新增红** |
| server-acp 两测试 | `pytest plugins/harness/tests/test_server_acp_controlled_entry.py plugins/harness/tests/test_server_acp_native_observation.py -v` | 7 pass / 0 fail（含 2 个新负例） |
| 写面外 · server-compat | `pytest plugins/server-compat/tests/test_controlled_peer_opt_in.py -q`（PYTHONPATH 指本树） | 8 pass / 0 fail |
| 写面外 · 编排全链 | `pytest tests/acp_orchestration/test_managed_acp_channel.py -q` | 本树 20 pass；主仓对照 20 pass——经真实入口+受控对端的全链逐测一致 |
| 写面外 · fixture 自检 | `pytest tests/acp_orchestration/test_fixture_selfcheck.py -q` | 6 pass / 0 fail |

环境注记：Python 测试用主仓共享 venv（`/home/maoqh/projects/ordessa/.venv`）
+ `PYTHONPATH` 指向本树 `plugins/harness/src`（editable 安装指主仓，PYTHONPATH
前缀遮蔽为受控复验手法，沿 016 批先例；未向主仓 venv 装任何东西）。

## 5. 意外收获与修复

- **`.gitignore` 陷阱（会咬下一个人的那种）**：根 `.gitignore` 的环境例外
  规则 `runtime/`（无前导斜杠，意图是根级运行数据容器）会匹配任意深度，
  `plugins/harness/runtime/` 下**新建**源文件默认被静默忽略——首次提交时
  `controlled-peers.mjs` 就这样漏在库外（既有 runtime 文件因先于规则被跟踪
  而无恙）。已 `git add -f` 补入并 amend；后人往该目录加源文件时须警惕
  `git status` 不显示 ≠ 已提交。
- `tests/access/access_launch_route.test.mjs` 既有缺陷：`orchestrationPeer`
  用 `path.resolve("tests/...")` 相对**进程 cwd** 解析，仓库根起跑能过、
  `plugins/harness` 起跑必 ENOENT（合跑批次暴露）。已锚定到
  `import.meta.url`（128 全绿在两种 cwd 下复验）。这正是 019 关心的"位置
  敏感"在测试自身的一种体现。
- 守卫上线即抓到两处违例并修复：`src/.../server_acp/__init__.py` docstring
  的测试树路径提及（改写为不带路径）；本线新模块注释里的路径（改写为按内
  容描述）。守卫不是摆设的证明。

## 6. 红线自查

- 写面：`git status` 全集 = 7 改 + 1 新增，全部在 `plugins/harness/**` 与本
  报告目录。✓
- 不弱于现状：§2 逐条；唯一行为差是 spec 点名的方向。✓
- 不引入命令执行面：名单条目 schema 无 command/args/driver；命令校验保留
  （须等于入口自身 node）；注入 fail-closed。✓
- 真模型调用：零（全部受控 fixture/离线）。✓

## 7. 未测边界（如实登记）

- Windows 未测（本机 linux；`matchControlledPeer` 用 node 跨平台 API，无
  /proc 依赖，理论可用但无实测）。
- 注入端口的 spawn 级行为在 Linux + node 22.22.1 实测；其他解释器版本未测。
- `acp_orchestration` 其余文件（conftest 直连等）未逐一跑，抽查覆盖了经真
  实入口的最重全链（managed channel 20 测）；该目录历史上另有继承红账，
  本线两树对照口径下无差异。
- staging 正例依赖源码树 fixture 存在（沿旧测试同样的前提）；纯 staged
  工件（无源码树）下的正例由注入端口路径覆盖（route 注入测试用的就是
  staged 闭包外的任意文件），未在纯 staged 目录再跑一遍。
