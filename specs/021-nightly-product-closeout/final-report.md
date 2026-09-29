# Ordessa Nightly Final Report

（2026-09-30 07:5x 冻结。夜间中段会话暂停约 4.5h，wall clock 损失导致 Phase 3+ 未展开；本报告如实记录已达/未达。）

## Candidate

- Branch: `nightly/021-ordessa-product-closeout`（NIGHTLY_TRUNK）
- Commit: `418c5cfbee`（产品代码冻结点；其后仅 specs 控制面提交 `6a8d798dc0` + 本报告）
- Main baseline: `b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0`（main 全程未动、零 push）
- Deb: `packaging/.out/ordessa_0.1.0_amd64.deb`（205,709,240 B，build-id `20260929-418c5cfbe`，由 trunk `418c5cfbee` 构建）
- SHA256: `70be619868f70f495d6cfdd225573bc086a9f48697acd8bacf9ea291e33a3d05`

## Release

- Build: PASS —— npm ci→build（17 扩展）→build:deb 全绿；桥可复现（`714044a5…`，与 baseline 钉值差异为已登记漂移）
- Deb: PASS —— deb-contract 45/45；打包完整性抽验过（bundled python 导入闭包、`bin/acp`、desktop entry、图标、update-pubkey）
- Install: PASS —— Layer① clean-machine-accept（userns chroot 真实 `dpkg -i`）：**CLEAN-MACHINE ACCEPTANCE: PASS / EXIT=0**（`/tmp/re2-layer1.log`）
- Launch: PASS(带登记债务) —— Layer② 解包树 xvfb 真实启动：`ready:true/settled:true/rootMounted:true`、bundled server `event:listening`、`wireReady:true` + 真 scope（`http://127.0.0.1:34323|server_476b…`）、**17 扩展全部发现、failures:[]**、截图 `evidence-assets/re2-launch.png`（RE2_RESULT JSON 全文见 `/tmp/re2-launch2.log`）
- Restart: PASS(弱证据) —— 第二次启动用独立 data-root（`/tmp/re2-data2`）成功 listening；同根重启周期未及系统化取证（RE-2 会话被取消）

## Core Product

- Project: 未验证（Phase 3 未达）
- Session: 未验证（Phase 3 未达）
- Harness A/B: 未验证。已备而未战：pi（本机已装）、opencode（未装）；I-002 native argv 通道被取消未落地
- Streaming: 未验证
- Tool Calls: 未验证
- Permission: 未验证（后端组合+admission 已接线为 SC-1 确认；前端三件套装配未做）
- Profile: 未验证（W-017：profile-chat 无 default export，启动 alert 已登记）
- Skill: 部分 —— `ordessa.skills` 已装配并随产品分发；装机激活报 `No provider for: ordessa.wirePort.v1`（B-006）
- MCP: 部分 —— `ordessa.asset-mcp` 同上；server 侧 `SkillsServerPlugin/McpServerPlugin` 未进默认组合（B-004 未做）
- Persistence: 部分 —— 装机两根启动成功；应用内 Project/Session 持久化未验证

## Additional Existing Capabilities

- Prompts / Memory / Subagents / Runtime-preferences：server 插件在树、未进默认组合（B-004 待做）
- Model Provider：桌面扩展已装配（I-001），同 B-006 激活告警
- Hooks / LSP / Command-templates：未动（020 波 2 / 缺 seam，按计划不属今晚）
- agent-shell 测试对齐现实（W-019 在分支未收编，见 Cleanup）

## Automated Gates

- `npm test` 聚合：24/39 绿（RE-1 基线）；失败全部预存在（mcp C-mcp-fe、examples @assistant-ui/react、electron 系=主进程崩溃已修后的陈旧断言、rig 退役 import），零新增未解释
- server-bridge：**57/57 含 live 真往返**（JSON-RPC 信封修复后真 server 200/400/超时三态）
- apps/desktop vitest：131/131（含 B-003 三布局、B-005 marker 断言）
- test:packaging：45/45（含 6 条新 deb-contract 断言）
- pytest：`-k data_root` 40/40；harness/边界套件守卫绿（pytest 9 passed）
- typecheck：30 条（较基线 31 净 -1，全部预存在登记）
- FR-009 平台纯度：5/5（含白名单豁免 `7b8223d38e`，W-027 登记债）

## Checkpoints

C0 ✓（控制面）→ **C1 ✓**（deb builds，`aa3918092c`）→ **C2 ✓(带债)**（install PASS + installed launch ready，deb `70be6198…`，产品冻结点 `418c5cfbee`）→ C3–C6 未达 → C-MC1 ✗ → C-FINAL（本报告 + 本 deb）

## P0 Remaining

无（B-001/002/003/005 全部关闭，均有 RV PASS + 组合门证据）

## P1 Remaining

- **B-006（新，P1）**：装机模式资产扩展激活告警仍在（profile-chat W-017 + agent-server/acp no-origin ×2 + skills/asset-mcp/model-provider `No provider for: ordessa.wirePort.v1` ×3）。事实：`wireReady:true` 且 scope 已就位，告警仍现 → 判定为"扩展激活时序早于 wire 事实/无重试"的宿主装配时序问题。证据：RE2_RESULT alerts（装机、非 dev 特有）
- I-002（native harness argv 通道）：agent 被取消未落地 → C3 真实 Harness E2E 无启动通道
- B-004（server 组合增补 skills/mcp/prompts/memory/subagents/runtime-preferences）：未开工
- permissions 前端三件套装配 + chat 渲染出口（SC-1 §2）：未开工

## P2/P3 Remaining

W-012/013/014(已修)/015/017/021/022-026/028/029 详见 ledger；多数为 backlog/收口批量

## External Blockers

- 会话暂停 ~4.5h（wall clock 03:10→07:50），Phase 3+（真实 Harness E2E/Profile/Skill/MCP 运行时验证）时间窗口被吞
- sudo 不可用（已按 D-021-6 三层策略绕过，Layer①② 均取证）
- DeepSeek E2E key 已验证可用（HTTP 200）但未消耗——真实模型链路未进入

## Architecture Improvements Landed

- HttpWirePort 对齐 server JSON-RPC wire/1（修掉"每调必 400"的隐性断链）+ live 覆盖
- 数据根"创建即立契"所有权模型（python+宿主双侧）
- deb server 产品闭包 16 包（AST 推导 + 独立复核）+ `/opt/ordessa/harnesses` landing + pythonBin 修复
- 装机/dev 双布局统一解析（`resolveProductLayout`）
- EA-1 裁决入档 D-021-7（wire seam 复用 C-03；native 启动桌面 argv 原则）

## Architecture Debt Deferred

W-027（FR-009 白名单）、sandbox 拒绝码 server 侧丢失、`Accepted` 非对象结果语义、C-03 冻结文本勘误、server 请求级 principal 注入、多 harness launch 描述符终态、020 波 2 搬家 epic

## Temporary Branch/Worktree Cleanup

- 已删：b001/b003/b002/b005/i001 五个 task branch+worktree（成果均已 cherry-pick 入 trunk）
- **保留 1 个例外**：`nightly/021-w019-agent-shell` @ worktree `worktree/tasks/w019-agent-shell`，commit `2b050e2467`（agent-shell 断言对齐，worker 自证 0/0×2+破坏性自检红）——RV-4 未及派出即冻结；按"不删未审成果"原则保留待白天 review，未收编进 candidate
- I-002 / RE-2 两个 agent 在会话恢复时被取消；RE-2 部分证据已抢救入档（E-P2-5）

## Final Verdict

MORNING_CANDIDATE = NO

- Best Green Checkpoint: **C2**（trunk `418c5cfbee`，deb `70be619868f70f495d6cfdd225573bc086a9f48697acd8bacf9ea291e33a3d05`）：可构建、可打包、可真实安装（chroot dpkg -i PASS）、可启动（17 扩展发现、bundled server listening、wire live）
- Missing Requirements: C3–C6 全链（真实 Harness E2E/streaming/tool call/approval/Profile/Skill/MCP 运行时验证）未进入；B-006（装机资产扩展激活时序）未修；B-004 server 组合缺口未接
- Recommended Next Step: ①修 B-006（宿主 wire 事实就绪前延迟/重试资产扩展激活）②收编 W-019 ③I-002 native 通道 ④B-004 组合增补 ⑤以 DeepSeek key 跑 pi/opencode 双 Harness E2E 冲 C3–C6 → Morning Candidate
