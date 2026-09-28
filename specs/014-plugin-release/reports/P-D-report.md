# P-D 报告 — claude 附件通路（harness）

**分支**: `codex/014-d-harness-claude`（基线 = main；plugins/harness 已在 main，无合并）
**日期**: 2026-09-28 · **派单**: [dispatch/P-D-claude-attachments.md](../dispatch/P-D-claude-attachments.md)
**状态**: DONE（受控证据级；L2 假端点，非 L3 产品链，边界见 §8）
**交付 SHA**: 即本报告所在的分支头提交（`codex/014-d-harness-claude`）；不 push、不外并。

**一句话结论**：旧负证据（"claude 真实握手 promptCapabilities 为空"）被钉版 0.81.2 的
第一手受控探针**推翻**；`attach` 如实翻绿（已观测）；claude 通路附件投递接通——
图片=真实附件块（哈希往返一致）、非图片=URI 链接文本、audio 类型化拒绝不投递。

---

## 1. R0 基线（PD-1）

环境（python3.12 venv，逐条命令）：

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r apps/server/lockfiles/server-linux-py312.txt
.venv/bin/pip install -e 'packages/pacthold[dev]' -e packages/server-plugin-api \
  -e plugins/harness/api -e 'apps/server[dev]' -e 'plugins/harness[dev]' \
  -e plugins/workspace -e plugins/server-compat -e plugins/runtime-compat
# products/server 依赖链需要补齐（baseline.md 清单内、文档缺 `-e` 明细的兄弟包）：
.venv/bin/pip install -e plugins/assets/sandbox/api -e plugins/permissions/api \
  -e plugins/permissions/backend
.venv/bin/pip install -e plugins/assets/sandbox/backend -e plugins/assets/sandbox/adapters \
  -e plugins/permissions/adapters
.venv/bin/pip install -e products/server
cd plugins/harness/packaging/claude && npm ci   # 离线闭包，锁文件核对 @agentclientprotocol/claude-agent-acp 0.81.2
```

- 未补齐 products/server 依赖链时套件出现 36 个 `SERVER_PRODUCT_MISSING` 环境性红，
  补齐后消失——非代码红，不进红账本。
- **改动前基线计数**：`pytest plugins/harness` → **2 failed / 456 passed / 3 skipped**
  （2 红为登记在案的继承 npm-closure 红：`tests/install/test_acp_schema_drift_target.py`
  两条，与 docs/baseline.md "harness carries 2 inherited npm-closure failures" 一致）。
- Node：v22.22.1；既有探针基线：`test:session-provider` 2 pass / 0 fail，
  `test:provider-routing` GREEN（A=1, B=2, C=1）。
- 消费 SHA：connectors 附件 DTO 形状按 main（PC-9 基准：`AcpPreparedAttachment` 含
  `preparedId`，`plugins/connectors/acp/src/attachments.ts:10-12`）只读对齐，零改动。

## 2. PD-2 重探针（第一手）

**架式**：`plugins/harness/packaging/claude/attachment-probe.mjs`（新增，
`npm run test:attachments`）。复用既有受控架式（同 `provider-routing-smoke.mjs`）：
`npm ci` 离线闭包拉起钉版 adapter（`dist/index.js`）+ loopback 假 Anthropic SSE 端点 +
临时 `CLAUDE_CONFIG_DIR` + 假 token（`controlled-local-token`）。**零真实模型、零真实
凭据**；探针断言全在 wire 上，不是源码直读。

| 探针项 | 实测结果（第一手） |
| --- | --- |
| initialize 转录 | `agentCapabilities.promptCapabilities = {image: true, embeddedContext: true}`（protocolVersion 1；完整 agentCapabilities 见转录） |
| image 端到端（正向） | ACP prompt image 块 → 假端点收到 Anthropic `image.source.base64` 块；base64 内容 **sha256 一致**：sent = wire = `c54abcd1a08540c7d1c91e0fe81cef8e9cb40cc39c78918006ed9e25cccb30ce` |
| resource_link（https） | 以**原文文本**下发：`https://example.org/notes.md` 逐字出现在 wire 文本块（`formatUriAsLink` 非 file/zed 直传） |
| resource_link（file://） | 以 markdown 链接文本下发：`[@notes.md](file:///workspace/notes.md)` |
| audio | **静默丢弃**（探针实测：audio base64 未出现在 wire，轮内文本照常送达；`promptCapabilities` 无 audio） |
| 输出图片（反向） | 实测分叉：纯 image assistant 响应 → 适配器该轮内部错误（`[ede_diagnostic] result_type=assistant last_content_type=image`）；text+image 混合响应 → image 以 `agent_message_chunk`（`content.type=image`）送达、base64 sha256 一致。反向通路**存在但有前置文本块约束**，如实记录不夸大 |

- **探针输出**：`reports/P-D-probe-transcript.json`（initialize 转录 + 每轮哈希与 wire
  原文 + updates 台账），文件 sha256
  `45101ea76ac99cb73ea064bfdddf15072ec676c961bcefbe631a5537f01ba106`。
- 运行结果：`GREEN_FAKE_ENDPOINT`，exit 0。
- **顺带观察（PC-10 相关，只记不接线）**：本会话内适配器自发播发
  `available_commands_update` × 2（`updatesSeen` 台账在转录内）。这是 S-07 "命令目录
  未探针" 的第一手正向信号；接线与否归 P-C PC-10，本包零消费、零改动。

### 旧负证据来历结论（连根说明）

1. **观测本身当时为真**：0.77.0 时代（2026-09-16 生产门）真实握手播发的
   `promptCapabilities` 确为空——记录见 `harnesses.toml` claude-code 注释、
   `claude-production-packaging.md` §2（"promptCapabilities 实测为空 ⇒ 不声明 attach"）。
2. **升版未重探**：commit `7089c0fd5d`（2026-09-27）把 pin 0.77.0 → 0.81.2（只为
   session-provider 路由探针），**没有**重探附件面；0.81.2 的
   `dist/acp-agent.js:1108` 已声明 `promptCapabilities:{image:true,embeddedContext:true}`。
3. **遗留机制**：旧负证据随拆库提交 `974e643a10`（2026-09-25）进入本仓的 toml 注释与
   FAMILY_MATRIX；FAMILY_MATRIX 只对照 toml 与文档、不对照 adapter 实况，升版后无人
   重探，漂移未被抓到。
4. **结论**：0.77 时代观测 + 升版未重探的遗留（非"探针读取位置错误"）。推翻依据是
   本次第一手受控探针（§2 表），不是仅引用源码。

## 3. PD-3 能力翻绿

| 文件 | 变更 |
| --- | --- |
| `src/ordessa_harness/harnesses.toml` | claude-code 行 `capabilities`：`["start","observe","finish","stream","native_continuation"]` → **加回 `"attach"`**；注释改为引用新探针证据 + 旧证据推翻说明 + 语义分层 |
| `runtime/capability_declarations.json` | claude-code 投影同步加 `"attach"`（机械派生件，测试钉住相等） |
| `tests/test_capability_declarations.py` | FAMILY_MATRIX claude-code `attach` → `(True, OBSERVED, 证据…)`；矩阵汇总 golden 同步 |
| `tests/test_claude_production_template.py` | `test_capability_claims_derive_from_the_registry` 的 golden `"attach": False → True`（**写入面注记**：该文件不在派单写入面清单内，但它是注册表派生声明的第四投影，"只改 toml 不改测试 = 红"的证据闭环门要求其一字同步；改动仅此一处，带注释） |
| `docs/server-round1/fullstack/claude-production-packaging.md` | **新建入库**：§1–7 为 Work Order 43 历史记录原样恢复（旧库 3efa48a6a5，main 上 docs/server-round1 从未跟踪），§8 为本次 P-D 证据段（含"历史结论已被推翻"的显式标注） |

production 模板能力声明是派生件（`capability_claims()` ← 注册表），零改动自动跟随。

## 4. PD-4 通路接线

**新增** `src/ordessa_harness/claude/attachments.py`（导出于 `claude/__init__.py`）：

- `ClaudePreparedAttachment`：connectors 冻结形状逐字段镜像（`preparedId/name/uri/
  mimeType/sha256/byteLength`，`preparedId` 预留；uri 必须非 `file:` scheme——与
  connectors `validPreparedReference` 一致）；`from_mapping` 接收 DTO 原文，漂移即
  `CLAUDE_ATTACHMENT_REF_INVALID`。
- `claude_attachment_capabilities(attach_declared=…)`：connectors
  `AcpAttachmentCapabilities` 形状的能力语句；缺席时 `{"kind":"absent","reason":…}`；
  可用时限额标注为**通道守门策略**（maxCount=8、maxBytes=5 MiB，非适配器播发限制），
  并如实标注"仅 image/png 走过端到端哈希验证"。
- `assemble_attachment_blocks(refs, *, attach_declared, data_by_prepared_id=…)`：
  refs → ACP `session/prompt` 内容块，序保持。**语义分层如实**：
  - `image/*` → 真实附件块 `{type:"image", data, mimeType}`，随行字节先过
    `verify_attachment`（byteLength + sha256），不符即 `CLAUDE_ATTACHMENT_HASH_MISMATCH`
    （投递前拦截，投递结果可验证）；
  - 其余非 audio → `{type:"resource_link", uri, name}`（URI 链接文本，不携带字节、
    不宣称上传）；
  - `audio/*` → `CLAUDE_ATTACHMENT_UNSUPPORTED`（适配器静默丢弃 audio 是探针钉死的
    事实，通路必须拒绝而不是放行给适配器丢）。
- 类型化拒绝码：`CLAUDE_ATTACH_UNDECLARED`（能力缺席，缺席即红）/
  `CLAUDE_ATTACHMENT_REF_INVALID` / `CLAUDE_ATTACHMENT_UNSUPPORTED` / 
  `CLAUDE_ATTACHMENT_LIMIT`（超数量/超大小）/ `CLAUDE_ATTACHMENT_HASH_MISMATCH`。
  **无任何静默丢附件/降级不报路径。**

**测试**（`tests/test_capability_declarations.py` §8，6 条，先红后绿的反例齐备）：
image 块组装+内容哈希自洽；非图片→resource_link；audio 类型化拒绝；`attach_declared=
False` 全拒（含合法 image ref，且断言家族派生声明默认已随 toml 翻 True）；超数量/
超大小/哈希不符/缺字节/非法 ref 全部类型化拒绝；能力语句不夸大。

**范围边界**：不实现 prepare 的存储语义（P-C/S-05 业务面）；`plugins/connectors/**`、
`plugins/chat/**` 零改动；Go 桥零改动；transport-only 中继语义未动（通道仍逐字转发
客户端帧，本通路提供的是 claude 家族对 ref→块的组装与守门语义）。

**受控往返**：端到端内容哈希一致由 PD-2 探针承载（image 正向 base64 sha256 相等、
反向混合响应 image sha256 相等）；组装层哈希自洽由 §8 测试承载。

## 5. 门自检

| 门 | 结果 | 证据 |
| --- | --- | --- |
| 探针第一手 | ✅ | initialize 转录 + image 往返哈希一致 + resource_link 两种形态 + audio 丢弃，全在 wire 上断言；转录与哈希入库（sha256 `45101ea7…`） |
| 证据闭环 | ✅ | 旧证据来历有结论（§2.4）；toml ↔ capability_declarations.json ↔ production 派生 claims ↔ FAMILY_MATRIX 四投影相等（53+ 测试钉住）；文档 §8 与 toml 注释同源 |
| 通路 | ✅ | 组装+校验+投递链路；哈希往返一致（探针）；缺席/超限/非法全部类型化拒绝（§8 反例） |
| 诚实 | ✅ | 语义分层表如实（图片=附件块 / 非图片=URI 链接 / audio=未声明不宣称不投递）；能力语句标注仅 png 过端到端验证、限额为通道策略；反向通路分叉如实记录 |
| 回归 | ✅ | 改动后全套 `pytest plugins/harness`：**2 failed（同 ID 继承红）/ 462 passed / 3 skipped**——继承红同 ID 同数不增，新增红 = 0；node 三探针全绿 |

## 6. 红账本

- 继承红：`test_acp_schema_drift_target.py` 两条（npm-closure），同 ID 同数，未触碰。
- 新增红：**0**。
- 环境注记：`ordessa-sandbox-backend` 等 products/server 依赖链在本机不可解析
  （`pip install products/server` 直接装失败），按 baseline 清单逐包 `-e` 补齐后消失；
  属安装清单缺明细（S-10 已登记同类），非本包代码问题。

## 7. 子代理

未使用（请求数 0）。

## 8. 诚实边界（未验项，如实登记）

- 本包全部证据为**受控假端点级（L2）**；Ordessa Server/桌面产品链的 L3 附件验收
  （经 admission/submit 全链）未跑，属集成波次。
- image 仅 `image/png` 走过端到端哈希验证；`image/*` 其余类型按前缀接受（适配器对
  media_type 逐字透传）但未逐一实测。
- resource_link 的 https 形态为实测形态；http 未单测（同一逐字透传代码路径）。
- 反向（输出图片）通路存在前置文本块约束（§2 表），已在转录与语义分层中如实记录。
- `tests/test_claude_production_template.py` 的一字同步超出派单写入面清单（§3 注记），
  请审阅确认。

## 9. S-07 回填

见 [seams.md](../seams.md) S-07 行：附件项补记 P-D 完成态（探针、翻绿、通路、SHA）；
命令项维持 PC-10 归属，本报告只登记 `available_commands_update` 的顺带正向观察。
