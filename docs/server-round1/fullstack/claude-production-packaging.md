# Claude Code 生产封装（Work Order 43）

状态：**CLAUDE_PRODUCTION_CHAIN_PREPARED / MODEL_NOT_VERIFIED（封装轮）**；
真实模型结论见文末「真实模型门」一节（跑完后补记，未跑则显式写明理由）。

这是 Work Order 43 接入的第二家（优先级 2）。许可证核查完成在先，接入卡与
六件套照抄已接入五家（Pi/Hermes/OpenCode/Codex/dsh）的全部做法。

## §1 许可证核查（本家第一优先，2026-09-16 只读盘点）

- `@anthropic-ai/claude-code` 2.1.272 与 `@anthropic-ai/claude-agent-sdk` 0.3.270：
  license 字段 "SEE LICENSE IN README.md"，tarball 内 LICENSE.md 逐字为
  *"© Anthropic PBC. All rights reserved. Use is subject to the Legal Agreements
  outlined here: https://code.claude.com/docs/en/legal-and-compliance."* —— **专有**，
  使用受 Anthropic Commercial ToS 约束（要点：不得修改二进制；每一终端用户以自己的
  API key / 订阅凭据 / 第三方推理凭据认证；不得代终端用户转售/中转）。
- `@agentclientprotocol/claude-agent-acp` 0.77.0：**Apache-2.0**（Zed Industries，
  registry 带 SLSA provenance）；运行时闭包 = `@agentclientprotocol/sdk` 1.4.0 +
  `zod` + 上述专有 SDK 及其平台二进制包。
- **工程结论**：内部集成、不修改二进制、用户自带凭据（本部署用用户自己的 DeepSeek
  key 走 DeepSeek 官方 anthropic 兼容端点）、不对外再分发 ⇒ 未发现工程层面阻断。
  义务两条已记账：**不修改二进制**（工件摘要固定、只读挂载）；**凭据自带**。
  法律判断不在本卡范围。

## §2 接入卡（动手前完成；全部来自官方只读探测与第一手 ACP 探测）

```
harness:            Claude Code（经官方 ACP 适配器 @agentclientprotocol/
                    claude-agent-acp 0.77.0；内嵌 @anthropic-ai/claude-agent-sdk
                    0.3.270 + 平台二进制 claude 2.1.272 级；node>=22）
来源与许可:          适配器 Apache-2.0；SDK/二进制 Anthropic 专有（§1）
安装与钉版:          独立 runtime-claude 根 package-lock（113 条目）；dist.integrity
                    逐包锁定；双构建摘要一致 sha256:3e28ead4…（105 包 / 3422 条目 /
                    241 118 070 字节；libc 过滤排除 musl 与他平台二进制）
入口形态:            ACP v1 stdio（适配器 = 官方 ACP 服务器；内嵌专有 CLI 由 SDK 派生）
配置入口:            CLAUDE_CONFIG_DIR 指向隔离根；settings.json 的 env 段实测把
                    ANTHROPIC_BASE_URL 应用到会话（第一手探测：假端点收到请求）
凭据变量:            ANTHROPIC_AUTH_TOKEN（环境注入；**绝不**写进 settings 文件）
模型配置:            settings.json model 字段 + 适配器 `model` 配置项（自定义 id 以
                    "Custom model" 行播发）；线上的 model 值精确等于产品模型
会话与续接:          $CLAUDE_CONFIG_DIR/projects/<派生目录>/<uuid>.jsonl；
                    ACP 面实测重开走非重放 session/resume（钉死断言）
流式与终态:          ACP sessionUpdate（agent_message_chunk 实测）；stopReason
                    end_turn；后台另有 title/topic 生成调用（单 user 消息、
                    无阶段标记——门内单列记录，不混入主线断言）
审批/附件:           permission mode 配置面存在；本链条未观测到任何运行时权限裁决
                    ⇒ 不声明 permissions；promptCapabilities 实测为空 ⇒ 不声明 attach
状态目录:            settings.json、projects/（transcript）、todos/ 等；生产投影只把
                    projects/ 作为有界 RW state，settings.json 只读
形态判定:            走 ACP 模板；与四家同构，无品牌分支（唯一家族特定处是
                    LD_PRELOAD 守卫到达原生二进制，NODE_OPTIONS 钩子做不到）
未知项:              (a) 专有 SDK 内部遥测开关未逐一确证——门内以守卫实测并拦截；
                    (b) 平台二进制升级节奏随 npm 包——pin + 双构建摘要约束
```

## §3 注册表与能力声明

- `harnesses.toml` 的 `claude-code` 条目由静态预声明更新为生产形态：
  capabilities 从 `[start, observe, finish, attach, native_continuation]` 改为
  `[start, observe, finish, stream, native_continuation]`——**移除 attach**（握手播发
  promptCapabilities 为空，比 Pi 的 image 播发还弱，无任何附件投递证据）、**加入
  stream**（适配器实测流式 chunk）。launch 面收敛为 `acp`（stdio）。
- `runtime/capability_declarations.json` 同步；`FAMILY_MATRIX` 增加 claude-code 行，
  observed 五项均以 2026-09-16 门报告为证据回填。
- 注册胶水 `runtime/profile_extensions.mjs` 新增 AgentBox 自有 `claude-code` profile
  （上游 `claude` 条目走 npx，托管离线链不可用；`permissionMode: "deny"`）。
- 模型别名：恒等映射（产品 id 原样透传），无需别名条目；`production.py` 的
  `NATIVE_MODEL_VALUE` 即产品 id，由模板测试锁定。

## §4 生产模块与部署模板（非秘密）

- `src/agent_box_harnesses/claude/production.py`（加入既有 claude 家族包，该包原有的
  composition/provider 模块属于本地 CLI 驱动，互不隶属）：官方根
  `https://api.deepseek.com/anthropic`、产品模型 `deepseek-flash`、
  `credentialKind=api-key`/`credentialEnvironment=ANTHROPIC_AUTH_TOKEN`、
  `CLAUDE_CONFIG_DIR=/runtime/home/.claude`、state 只投影 `projects/`。
- `deploy/claude/settings.json`：`env.ANTHROPIC_BASE_URL`（官方根）+ `model`（产品
  模型）。凭据只走环境变量，绝不入 settings 文件（测试断言）。
- `deploy/claude/egress-guard.c`：评审过的仅-loopback 守卫（opencode 同源），门内
  编译为 .so 后以 **LD_PRELOAD** 预载——这是到达原生 CLI 二进制的唯一通道
  （NODE_OPTIONS 钩子只覆盖 node 适配器进程）。
- loopback 假端点变体 = 同一 settings 文档仅替换 `env.ANTHROPIC_BASE_URL` 一个字段
  （`documented_differences` 断言）。

## §5 工件构建（双构建一致）与生产门

- `scripts/server-round1/build-claude-runtime-artifact.mjs`：dsh/Pi 构建器的克隆 +
  两个结构性新增：`EXECUTABLE_FILES`（原生二进制发布为 0555——只读树里没有执行位
  就是一棵完整但不可运行的树）与 `libcMatches()`（SDK 同时声明 glibc/musl 同平台
  包，os/cpu 匹配会复制两份 ~224MB 二进制；以构建机 libc 择一，与 npm 规则一致）。
  双构建摘要一致：`sha256:3e28ead421e59213c0659f15e78681fcd084cc167b87fdefdb27c07bde8bdda0`
  （105 包 / 3422 条目 / 241 118 070 字节）；source lock digest
  `sha256:91670424da83b4db6caf6fb40490c029384b1078f09fb40ba13b49b0dc602007`。
- `scripts/server-round1/claude-production-chain-gate.py`：dsh 门的克隆 + 两处家族
  特有改动（假端点讲 **Anthropic Messages SSE** 协议；守卫经 LD_PRELOAD 到达原生
  二进制）。门默认用本工作树重建的 release Worker
  （`sha256:b4b58db16159b4e3518f33dff9745effd5f7f5f80e61e8373055a7499de4a37a`，
  wireVersion=1；与 42 记录的 c8 摘要不同源的是构建工具链，Worker 源码同源，
  如实记录不冒充 c8）。
- **门结果（2026-09-16，exit 0，`CLAUDE_PRODUCTION_CHAIN_GATE_OK`）**：
  - 主链两轮：第一轮 completed（deltaSeq [4] < completedSeq 7）、第二轮 completed
    （[11] < 14）、`checkpointNativeIdStable=true`；checkpoint schema v2、
    `resumable=true`、transcript jsonl 单文件回投（139 371 字节）。
  - **续接在线上证明**：含 round2 提示标记的请求必同时携带首轮 nonce 与已存
    assistant 轮（`round2RequestCarriedRound1Context=true`）。
  - **后台模型调用如实单列**：实测每会话 1 次 title/topic 生成调用（单 user 消息、
    无阶段标记、模型同为 deepseek-flash），单列于 `backgroundRequests`，不混入
    主线断言。
  - **未知模型**：`deepseek-unknown` 在任何 provider 请求前被桥的模型可用性检查拒绝
    （turn failed、`providerRequestsAfter=0`）——与四家同不变式；"Claude Code 接受
    任意 model id" 的文档语义指端点侧 id，不适配器播发面（第一手实测后钉死断言）。
  - **重开相位**：实测 `reopenMethod=session/resume`（非重放；出现重放即门失败），
    同 native id、第二轮请求带首轮上下文。
  - **egress 守卫**：guardLoaded=true；实测拦截 4 次 claude 二进制对
    `api.anthropic.com` 的**解析尝试**（厂商遥测/配置面，非模型流量、全部被阻断、
    零接触）——该域名的 resolve 拒绝记为预期观测（`expectedVendorResolveDenies`），
    任何其他目的地或任何 connect 级尝试仍类型化失败。
  - 凭据：注入 token 恰好到达假端点（`injectedTokenReachedProvider=true`、
    `unauthorizedRequests=0`）；events / 可报告状态 / native state 扫描零命中。
  - 清理：临时根 removed=true、worker 投影/adapter 进程/gate token 全清。
- `--live`：**未执行**（按工单 §5.4 最后统一串行；见 §6）。

## §6 真实模型门（--live，2026-09-16 执行）

- **结果：exit 0，`CLAUDE_PRODUCTION_CHAIN_GATE_OK`（mode=live）**。官方
  anthropic 兼容根（模板原样）、授权 locator 只读注入、不装载 guard。
- 两轮真实答复：首轮答出 nonce，次轮真模型召回；同 native id；未知模型发包前
  拒绝；授权 locator 未被删。
- 重开相位实测 `session/resume`（非重放），live 上下文证据 = 模型召回（第一手
  观测：claude 的 delta 为逐字符碎片，单条不含完整 nonce，按拼接全文检查）。
- **费用分账**：live 尝试 3 次（前 2 次失败均为本门重开相位 live 断言缺陷——
  引用 live 下不存在的假端点 + 单 delta 碎片检查；非 Harness 缺陷，已修）；确认
  真实请求 12 次（每次尝试 2 主链 + 2 重开），另有假端点门实测的每会话 1 次后台
  title 调用（live 下未逐次观测）；tokens 上界每请求 <2K → 估计费用 **< ¥0.03**。
- 机制证据（§5）与真实模型证据分账、不互替。

## §7 阻塞账

| harness | 卡在哪一步 | 命令 | 退出码 | 脱敏错误/现象 | 已排除的可能 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| （暂无） | | | | | | |

## §8 P-D 附件通路重探针（2026-09-28，钉版 0.81.2 第一手）

> 本节由 014 P-D 包增补。§2–§7 是 Work Order 43（0.77.0 时代）的历史记录，原样保留；
> 其中"promptCapabilities 实测为空 ⇒ 不声明 attach"的结论**已被下述重探针推翻**。

- **旧负证据来历结论**：0.77.0 时代（2026-09-16 门）的真实观测，当年成立；0.81.2 升版
  （commit 7089c0fd5d，2026-09-27）只换了 pin、未重探附件，负证据随 toml 注释遗留至今
  （随拆库提交 974e643a10 进入本仓）；FAMILY_MATRIX 只对照 toml 与文档、不对照 adapter
  实况，故未抓到漂移。推翻依据是**第一手受控探针**，不是源码直读。
- **探针**：`plugins/harness/packaging/claude/attachment-probe.mjs`
  （`npm run test:attachments`）。既有架式原样复用：`npm ci` 离线闭包 + loopback 假
  Anthropic SSE 端点 + 临时 `CLAUDE_CONFIG_DIR` + 假 token；**零真实模型、零真实凭据**。
- **initialize 转录**：`agentCapabilities.promptCapabilities = {image:true,
  embeddedContext:true}`（协议版本 1；完整 agentCapabilities 见转录 JSON）——推翻旧记录
  的"播发为空（{}）"。
- **image 端到端**：ACP prompt image 块（data）→ 假端点收到 Anthropic
  `image.source.base64` 块，base64 内容 **sha256 一致**（sent = wire =
  `c54abcd1a08540c7d1c91e0fe81cef8e9cb40cc39c78918006ed9e25cccb30ce`，转录内含本轮全部哈希）。
- **resource_link 语义**：https URI → 适配器以**原文文本**下发（`https://example.org/notes.md`
  逐字出现在 wire 文本块）；file:// URI → `[@notes.md](file:///workspace/notes.md)`
  markdown 链接文本。不携带字节、无任何"文件已上传"语义。
- **audio**：适配器**静默丢弃** audio 块（default 分支；探针实测：audio base64 未出现
  在 wire、轮内文本照常送达）。audio 在 `promptCapabilities` 中**未声明**——通路层
  类型化拒绝，不宣称、不投递。
- **输出图片（反向）**：实测双向分叉——纯 image assistant 响应使适配器以内部错误
  终止该轮（`[ede_diagnostic] result_type=assistant last_content_type=image`）；
  text+image 混合响应则 image 以 `agent_message_chunk`（`content.type=image`）送达客户端、
  base64 sha256 一致。反向通路存在但有前置文本块的约束，语义分层表按实测如实记录。
- **语义分层（如实）**：图片=真实附件块（哈希可验证）；非图片文件=URI 链接文本；
  audio=未声明、不宣称、通路拒绝。
- **产物**：转录 JSON（含全部哈希与本节事实的机器可读形态）入库于
  `specs/014-plugin-release/reports/P-D-probe-transcript.json`
  （sha256 `45101ea76ac99cb73ea064bfdddf15072ec676c961bcefbe631a5537f01ba106`）；
  报告 `specs/014-plugin-release/reports/P-D-report.md`。
- **边界**：受控假端点级证据（L2），不是 Ordessa Server/桌面产品链的 L3 验收；通道
  组装面的类型化拒绝与哈希校验由 `ordessa_harness/claude/attachments.py` 承担，测试在
  `tests/test_capability_declarations.py` §8。
