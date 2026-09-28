# 派单 T02 — 品牌适配（`plugins/assets/model-provider/adapters/**`）

状态：**QUOTA_REFUSED**（同 T01，2026-09-28 四次派发被拒）→ lead 亲自实现，本文件为工作单 + 审阅清单。

## 唯一写入域
`plugins/assets/model-provider/adapters/**`

## 任务
三品牌 C2 配置适配器（Pi/Codex/Claude Code），E1 级；纯 assess/compile/verify + registration_manifest。

### 只读输入
- 目标契约：`docs/design/harness-v2/contracts.md` C2/C3/C4/C6；`docs/design/model-provider/harness-adapters.md`；spec MP-01/03/06/11
- 品牌语义参考：本树 `plugins/harness/src/ordessa_harness/native_materialization.py`（方言/endpoint 校验，只读，禁 import/安装）；
  `plugins/harness/packaging/claude/provider-{session.test,routing-smoke}.mjs`（假端点证据模式）
- 旧 E1 测试参考：旧树 `tests/test_brand_adapters.py`（只读）
- 钉版（t00-freeze §5）：pi=`@automatalabs/pi-acp@0.5.0`+`@agentclientprotocol/sdk@1.3.0`；
  codex=`@agentclientprotocol/codex-acp@1.1.14`；claude=`@agentclientprotocol/claude-agent-acp@0.81.2`

### 布局
- `adapters/pyproject.toml`：dist `ordessa-model-provider-adapters`，import `ordessa_model_provider_adapters`，stdlib only，src 布局。
- `types.py`（typed assessment/intent/refusal 判别式数据类）、`common.py`（共享校验/冲突检测）、`pi.py`、`codex.py`、`claude.py`、`tests/`。

### 语义
- 纯函数：assess→supported|unsupported|unknown+原因；compile→IntentSet|Refusal；verify→Match|Mismatch|Unknown。
  **禁**读 HOME、网络、spawn、写文件、解析秘密（静态边界测试钉死 import/内建引用）。
- typed intent 对齐 C3：SetField/ResetField/MountContent/RemoveOwnedContent/BindSecret（只传引用）/InvokeAction；
  field_path=结构化 segment；每项带 facet/item 来源与贡献版本。
- 品牌规则：Pi models.json 与 set_model RPC 分开、RPC 成功≠生效、verify 分层；Codex 项目 `.codex/config.toml`
  覆写 `model_provider*` 必须 Refusal、仅 config 写≠会话生效、跨 provider 声明 restart-resume+同 thread resume；
  Claude model 与 ANTHROPIC_BASE_URL 两事、session 级配置+同 native session id resume、`session/new` 冒充必反例。
- `registration_manifest()`：C2 注册条目形状（adapter_id `assets.model-provider.<brand>`、facet_id
  `assets.model-provider`、api v1、harness_id、版本范围、entries、payload schema、claims）；实际注册属 C0，不伪造。
- 冲突语义：`(facet_id, harness_id, entry, version-range)` 重叠或同 native 字段双声明→类型化拒绝；范围无法证明不相交即拒。

### 测试（先红后绿）
每品牌：supported 正例/未知版本 unknown/unsupported 反例；BindSecret 哨兵；verify 分层；
Claude session/new 冒充反例；Codex 项目覆写反例；Pi RPC≠生效反例；manifest 形状；边界扫描；冲突拒绝。

### 审阅清单
- [ ] stdlib-only + 边界扫描绿
- [ ] 三品牌 × 反例矩阵齐
- [ ] golden fixture 有 provenance
- [ ] manifest 形状测试
- [ ] pytest 全绿证据
