# Ordessa Nightly Final Report

**2026-10-01，ZCode 主会话收口。** 本报告取代 2026-09-30 那版（那版描述的候选 `418c5cfbee` /
deb `70be6198…` 已作废，其"Phase 3 未展开"的结论也已被后续多轮推翻）。
逐 ID 判定见 `takeover-progress.md` 的 **CP-N1** 节；本文件是交回摘要，不重复逐条依据。

## 总判定：PARTIAL —— 不是 COMPLETE_VERIFIED

合同 `overnight-acceptance.md` 共 **117** 个 ID（A24+B14+C22+D24+P16+S5+F12）。
台账 ID 集合与合同**完全一致、无缺无余**（`comm` 双向差集均为空）。

| 组 | PASS | 总数 | 说明 |
| --- | --- | --- | --- |
| A 原生进程/接管 | 21 | 24 | L1+L2 立住；A22 仓内零接缝、A23 等 sudo |
| B 供应商切换 | 10 | 14 | B10 真实失败、B11 未跑，均卡同一 sudo |
| C Profile/凭据 | 16 | 22 | C02/C03/C08/C10 缺合同要求的 L3/L4；C22 判 FAIL |
| D UI 验收 | 16 | 24 | L4 已由 Xvfb 跑出，但绑定装机候选的仍缺（D24 FAIL） |
| P 发行/装配 | 9 | 16 | **P07/P08 是真实装配缺口**，非仅证据缺口 |
| S 既有资源 | 1 | 5 | **S03 FAIL（结构性）**；S01 FAIL；S02 PARTIAL |
| F 最终验证 | 12 | 12 | F11 **两次独立复审均判 PASS**（零阻塞）；复审查出的两处（一处由 P1 修复自身引入的严格性回退、一处"缺席 pid 误判为复用"）均已修并变异验证 |

合计 **85 / 117 PASS**（逐行取自台账实际状态，非人工誊抄；由脚本按 `| <ID> | <STATUS>` 重算）。

## Candidate

- Branch: `nightly/021-harness-rollout-opencode-hermes-dsh-kilo`
- 冻结点: **`9979c651c8`**（F11 修掉 P1、P2 后顺延，复审要求收紧 `assertUsableRollout` 后二次顺延，
  再修"缺席 pid 被误判为复用"后三次顺延）
  - 该冻结点上**全部记录在案的门已重跑为绿**：native-profile **83/83**、`plugins/profile`+`model-provider` **473**、
    `plugins/assets/skills` **433**、harness 配置/恢复三路径 **166**、`npm run test:packaging` **45/45 / 12 suites**。
- Main baseline: `b4bf7cd90951`（**全程未动、零 push**）
- Deb: `packaging/.out/ordessa_0.1.0_amd64.deb`，209,583,328 B
- SHA256: `e31e270c0e20021c5868a5aad1461654c91a8f37d9b626abe137f9efe4acbac5`
- Build identity: `0.1.0 20261001-16bf0a204`

## 门禁（全部在冻结候选上实跑）

| 门 | 结果 |
| --- | --- |
| `node --test plugins/harness/packaging/native-profile/*.test.mjs` | **83/83** |
| `pytest plugins/profile plugins/assets/model-provider` | **473 passed** |
| `pytest plugins/harness/tests/configuration_model + test_provider_restoration_service + test_pi_provider_registration_service` | **166 passed** |
| `pytest plugins/assets/skills` | **433 passed** |
| `npm run test:packaging` | **45 pass / 0 fail / 12 suites** |
| 根 `npm test`（补齐环境前提） | **38/39 green**；唯一红 `ui-preview` 与 main 逐字节相同、预存在 |

两次根聚合的差异**全部归因环境前提**：`.venv` 不能 `import ordessa_profile`
（补 `ORDESSA_WIRE_LIVE_PYTHON` 后 server-bridge **68/68**）；7 个 Electron 门缺
`ORDESSA_BUNDLED_ROOT` 全红（补后 **6 个 exit 0**）。两个环境的数都留档，不挑好看的那个。
**每个数都连命令一起记** —— 复审指出 F06 曾只写数字不写命令，导致 166/247 对不上。

## L4 实测（本轮新增）

| 探针 | 服务端组合 | 结果 |
| --- | --- | --- |
| `probe-native-installed.mjs` | `native_runtime`（开发启动器强制注入） | `ready:true rootMounted:true errors:[]` pages `[Chat, Skills, Sessions]` |
| `probe-default-installed.mjs`（新增） | `default_plugins`（**安装后 deb 的真实组合**） | `ready:true` 但 `skills.list`/`skills.resolve` **`is not a wire/1 method`** |

## 本轮定位/修掉的真实缺陷

| # | 缺陷 | 严重度 | 验证 |
| --- | --- | --- | --- |
| 1 | `codex-process.mjs::assertUsableRollout` 的 `if (read < buffer.length)` 对普通文件恒不成立 ⇒ **>64 KB 的合法 rollout 与"仍在写入"的 rollout 一律被拒**，打断**同会话 Profile/model 替换**这条旗舰路径 | **P1（复审查出）** | 修前 130 KB 合法记录、截断尾 **均抛**；修后二者 PASS，空/垃圾/**完整但损坏** 仍抛；变异回退 ⇒ 新用例 fail |
| 2 | `ownedProcessSet` 只排除被复用的 pid **本身**，其**子树**仍被 pgid 扫描收进 owned 集 ⇒ 误杀非本进程进程且永不确认退出 | P2（复审查出） | 修前返回 `[200,300]`；修后 `[]`，对照（确属本进程）仍 `[100,200,300]`；变异回退 ⇒ fail |
| 3 | `build-deb.mjs` `cpSync` 缺 `verbatimSymlinks`，1049 条解释器符号链接被改写成绝对构建机路径，**装出不能用的 Python** | 发行阻断 | 重建后 worktree 链接 1049 → **0**；解包解释器 `3.12.14` 实跑并导入 `pydantic`/`starlette`/`cryptography` |
| 4 | `run_counterexamples.sh` 把 `ModuleNotFoundError` 算作"判别成功"，**12/12 假绿** | 验收诚信 | 敌意环境 exit 1 并 `REFUSING`；真实环境 12/12 且每条带真实失败数 |
| 5 | 发行默认链**不含 Skills、不含 MCP**，而 dev 启动器总注入 native 模式，**掩盖了该缺口** | 真实产品缺陷 | L4 对照实测（见上表）；已登记 known-issues |
| 6 | `ordessa-asset-op.py` 回执回显候选自述值，发布后不复验 | 验收诚信 | 已加发布前三项全等比对 + 发布后对落地树复验同一钉死 verifier |

**三处自我更正已如实记录：** ①P09 的"陈旧产物"结论曾判错，真因是 `cpSync` 缺 `verbatimSymlinks`，
是**真构建 deb 才复现**的；②台账曾把 T8 记为"本机条件不具备"，实为把 `LockedHint=yes`
（会话状态）误当能力缺失，Xvfb 一直在；③台账曾写"130 个 ID"，实为 **117**；
④F06 曾只写门禁数字不写命令，致 166/247 对不上。

## 阻塞与待裁定（**全部需用户动作，我一律未自行决定**）

**一条命令、一次口令**（解锁 T5.3/T5.4/T7/P05/P13/A23 + 部署修好的发布器 + 装机做 L5）：

```
bash /home/maoqh/projects/ordessa/worktree/021-ordessa-product-closeout/.cleanup-evidence/publish-fixed-codex-managed.sh
```

> **这条命令本轮已修好并做过非 root 全量演练，此前那版备件是会失败的。** 原先备好的请求指向
> 00:17 构建的资产，实测其中 `assertUsableRollout` 仍是修前的 `read < buffer.length`（P1 原样）、
> P2 标记为 0，**且候选目录形状不符合 helper 约定**（缺 `codex-runtime/` 与内层 manifest），会在
> `checked_manifest` 被拒——即使装成功，装进去的也是打断旗舰路径的那份代码。现已重建为
> `codex-publishable-1790885666`（含复审后的两处修正），并在脚本开头先跑三段
> 演练（helper 自身前置函数 5/5、树摘要与 manifest 三方一致、verifier 全部非属主断言）才发布。
> **演练不过就在花掉口令之前退出。**

**五项裁定：**

1. **dsh/kilo 信任根入口形状** —— 钉死的 `native-artifact-policy.mjs` 只认
   `node_modules/<pkg>/dist/{index.js|ordessa-profile.mjs}`，而 dsh/kilo 是 bin-only CLI 包。
   建议 (a) 增加镜像 codex `native{entrypoint}` 的**钉死可执行路径变体**；(b) 改为 manifest 声明 + 只校验形状。
   **当前后果：这两个品牌的资产无法安装，阻塞 rollout。**
2. **kilo 产物内含 `bin/bwrap`**（112664 B，static-pie stripped ELF），`bin/kilo` 并不引用它 —— 发行安全面裁定。
3. **Python 闭包锁文件零 `--hash`** —— P01/P04 的"锁漂移"反例对 Python 侧是否必须真正成立。
4. **P08（deb 零品牌 runtime）/ D04（model selector 不在冻结的 chat-api 合同内、该包缺 `manifest.json`/`build.mjs`、不在 `extensions.json`）** —— 处置方式。
5. **发行默认链是否装配 Skills/MCP** —— 把 `ProductSkillsPlugin` 加进 `default_plugins` 会撞上
   `products/server/tests/test_q5_first_stage.py:30-34` 钉死的 `EXPECTED_PLUGIN_IDS`，属架构裁定。
   **该断言未被放宽。**

## 未做而非做不完

- **A22**：仓内 `execution` 零命中、无接缝可验。合同 §A22 要求"报告阻塞，不擅自设计 pacthold 模型"，故只登记。
- **S03**：不是"未跑"而是**当前架构下不可能过** —— MCP 在任何组合里都没有实例化，没有承载体。
- **D19 / C02 / C03 / C08 / C10 / D24**：需要**装机候选**上的真实 L3/L4 会话，在那次 sudo 之后。
- 未合并、未 push、未启停任何既有用户服务、未在无授权情况下消耗真实模型调用。