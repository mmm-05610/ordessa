# P-D 简报 — claude 附件通路（harness）

**工作目录**: `worktrees/014-d-harness-claude`（分支 `codex/014-d-harness-claude`，基线 = main，plugins/harness 已在 main，无需合并）

**必读输入**（按序）: 本目录 [spec.md](../spec.md)（US3/US5）、[plan.md](../plan.md)（事实 F4、纪律、P-D 行）、[seams.md](../seams.md) S-05/S-07、`plugins/harness/packaging/claude/PROVIDER-SESSION-PROBE.md`（既有探针架式）、`plugins/harness/T02-CAPABILITY-EVIDENCE.md`、根 `AGENTS.md`。

**目标一句话**: 用钉版 `@agentclientprotocol/claude-agent-acp@0.81.2` 的第一手受控探针，推翻（或确认）"真实握手 promptCapabilities 为空"的 0.77 时代遗留负证据，把 `attach` 能力如实翻绿，并把 claude 通路附件投递接通。

**背景事实（主会话 2026-09-28 源码实证，R0 复核）**：
- 0.81.2 `dist/acp-agent.js:1108` initialize 声明 `promptCapabilities:{image:true, embeddedContext:true}`；
- `:7364` 用户 image 块 → Claude base64 图片；`:7682` 输出图片 → ACP image chunk；`:7341` `resource_link` → URI 链接文本（不丢弃）；audio 未声明；
- 旧负证据（`harnesses.toml:86-89` 注释）随拆库提交 974e643a10 进来，`PROVIDER-SESSION-PROBE.md` 记有"former 0.77.0"——升 0.81.2 后无人重探附件；FAMILY_MATRIX 测试只对照 toml 与文档、不对照 adapter 实况，故未抓到漂移。
- 用户裁定（2026-09-28）：**必须解决，不接受缺席**。

## 写入面（只许这些）

`plugins/harness/packaging/claude/**`（新增探针脚本/测试；node_modules 装机产物不算跟踪改动）、`plugins/harness/src/ordessa_harness/harnesses.toml`、`plugins/harness/src/ordessa_harness/claude/**`、`plugins/harness/tests/test_capability_declarations.py`、`docs/server-round1/fullstack/claude-production-packaging.md`（证据更新）、`specs/014-plugin-release/**`（勾选 PD-*、写 `reports/P-D-report.md`、回填 S-07）。

**禁区**: `plugins/connectors/**`（只读消费其附件 DTO——以 P-C PC-9 冻结形状为准，未冻结前按 main 现状+preparedId 预留）、`plugins/chat/**`（P-C 域）、`plugins/harness/adapters/acp-adapter/**`（Go 桥，本包不动）、其他 plugins/、products/、tooling/、packages/、apps/、根锁、兄弟树。

## 任务（详账 tasks.md PD-1..PD-5）

### PD-2 重探针（本包核心）
1. 复用 `packaging/claude` 既有架式（`npm ci` + fake Anthropic loopback endpoint + 临时 Claude config + fake token；**零真实模型、零真实凭据**）受控拉起钉版 adapter。
2. 转录 initialize 响应的 `agentCapabilities.promptCapabilities`（对照源码预期）；探针输出（JSON 转录）与哈希进 report。
3. image 端到端：prompt 携带 image 块 → adapter → fake 端点断言收到对应 base64 图片内容（哈希一致）；反向如有输出图片路径一并测。
4. resource_link 语义实测：传入非图片 resource_link，断言 adapter 以 URI 链接文本下发（记录实际行为，不夸大）。
5. 给旧负证据一个明确来历结论（0.77 时代观测 / 探针读取位置错误 / 其他），写进 report——**推翻旧证据必须连根说明，不许只写"现在是绿的"**。

### PD-3 能力翻绿
`harnesses.toml` claude-code 行 capabilities 恢复 `attach`；注释改为引用新探针证据（含旧证据推翻说明）；FAMILY_MATRIX 测试同步（claude 行从 `["start","observe","finish","stream","native_continuation"]` 变为含 `attach`，测试的 golden/断言随之更新）；`claude-production-packaging.md` 增补证据段。**语义分层如实**：图片=真实附件块；非图片文件=URI 链接；audio=未声明、不宣称。

### PD-4 通路接线
claude 家族通道（`src/ordessa_harness/claude/**`）接受附件投递：从 connectors 附件 DTO 形状（对齐 PC-9 冻结件；未冻结前按 main 现状+`preparedId` 预留）到 `session/prompt` 的 image 块 / resource_link 组装；受控往返测试断言内容哈希一致；能力缺席/超限时的类型化拒绝（反例）。**不实现 prepare 的存储语义**（那是 P-C/S-05 的插件业务面），本包只保证"通道收到 refs 后能正确组装并投递、且投递结果可验证"。

## 门与反例（终态前必须全过）

| 门 | 断言 | 反例 |
| --- | --- | --- |
| 探针第一手 | initialize 转录 + image 往返 + resource_link 行为，带哈希 | 只引用源码不实测 = 不算绿 |
| 证据闭环 | 旧负证据来历有结论；FAMILY_MATRIX 与 toml 与文档三方一致 | 只改 toml 不改测试/文档 = 红 |
| 通路 | 受控往返哈希一致；超限/缺席类型化拒绝 | 静默丢附件/降级不报 = 红 |
| 诚实 | 语义分层表如实（图片/链接/audio 三层）；不宣称 audio | 把 URI 链接说成"文件已上传" = 假绿 |
| 回归 | plugins/harness 既有套件计数不回退 | 新增红未登记 = 不许收口 |

## DoD

实现 + 门 + `reports/P-D-report.md`（探针转录与哈希、旧证据来历结论、能力 diff、语义分层、S-07 回填）+ tasks.md PD-* 勾选一致 + 交付 SHA。git：本分支正常提交，不 push 不外并；子代理规矩同 P-A。**零真实模型调用、零真实凭据；不动 Go 桥。**
