# W-1 报告 · 写入链死亡（SC-1/SC-2/③，2026-09-29）

分支 `codex/plugin-server-compat`（基=main `4591aa461b`）。执行：主会话。
**无双写声明：本批删除了全部对外写入口（模型配置 6 方法 + profile 写 8 方法
及其注册表项）；保留面均为只读。**

## SC-1 model_configs writer（W1-W14）

- W6-W11 六个 `provider_models_*` handler、W12-W13 助手（_provenance 家族/
  _provider_model_body）、W14 门 `_require_model_configs`：**已删**。
- W1/W2：`_PARAM_SHAPES`/`_COMPAT_METHODS` 的 providerModels 条目**已对称删**
  （order-097 形状/方法对齐门随之平衡）。
- W15（SLOT_TABLE/_model_reference_list）：**按清单保留**，归 config 域退役批次。
- **偏离一（W3）**：`_BINDING_ACTIONS` 的 CREDENTIAL_*/PROVIDER_MODEL_*/MODEL_
  UNAVAILABLE/PROFILE_CONFIGURATION_INVALID 条目**保留**——它们不只服务已删的
  提交闸门，还是执行冻结只读路径（:698 actions 投影）的活消费面。
- **偏离二（W4/W5，依清单 §3.3 授权）**：ctor `model_configs=` 注入与
  `self.model_configs` **保留为只读残留**（freeze/usage 的 records.get/
  credentials.get/secret_store 探测）；写入侧零残留。归 config 域批次收口。

## SC-2 server_profiles 写面（R10 窗口必死面）

- 事实修正：profile-api r2 是**桌面 TS 面**（Token 消费），与 server-compat
  的 `profiles.*` Server wire 方法**不撞号**；`agent-box.profile@1` 双声明在
  harness 侧（R1-R6，后续波次）。故 R10 的窗口必死面＝与 profile-api 双写的
  **对外写入口**，非全仓库。
- 已删 8 个写 handler（create/update/updateConfig/archive/clone/setPermissions/
  grantSubagent/revokeSubagent）＋两注册表对应条目。保留 4 读（list/
  subagentGrants/memory/_profile 助手）与仓库读（execution/delegation、
  inventory、assets、sessions 内部消费）；**仓库本体与迁移器归 W-3 毕业波**
  （届时各域改读 profile-api 并携迁移记录；server_profiles 表格式与 id 不变，
  AGENTS.md 规则 5）。
- 附注：http 兼容路由（compat_http_routes）仍持有 service/repository 引用，
  属同域旧面，随整域毕业死亡，本批不扩面。

## ③ composition 白名单摘要制（复 core 索要）

- `_CONTROLLED_PEER_SHA256` 钉 `45ebf370…`（与 harness 019 controlled-peers.mjs
  同值，本树夹具实测一致）；受控对端判定改内容摘要制，路径无关；
  保留 harness_id/command/args 形状/符号链接拒绝（行为不弱于现状）。
- 新增负例 `test_tampered_peer_content_is_refused`（一字节篡改→拒）。

## 测试

`pytest plugins/server-compat/tests`：**9 passed / 0 failed**（树内 .venv，
Python 3.12.14，R0 顺序含 products/server）。apps/server 侧兼容回归四件与
边界断言＝pi 同批（AR-1 清单 ar1-handoff.md）；合并后由主会话统跑全套。
