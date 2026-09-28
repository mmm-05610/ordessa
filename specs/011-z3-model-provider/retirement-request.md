# Retirement request — server-compat `model_configs` writer（S-08①，B 线交付）

日期：2026-09-28。包 B（model-provider 真实应用链）按派单 PB-7 交付的**逐行
退役清单与顺序确认**。本文件只裁定、只列清单、只核消费者；**任何删除都不在
本包执行**——实际退役归集成波次（seams S-08：新 owner 就位 + core 装配排期后）。

## 0. 行号漂移声明

派单引 `core_wire.py:238-276`（派单撰写时快照）。本树实测该区间现为
`_PARAM_SHAPES` 声明行；writer 主体分布在下表所列现行行号。**以本清单的
现行行号为准**（git 可复核），派单旧行号只作历史线索。

## 1. 逐行退役清单（`plugins/server-compat/src/ordessa_server_compat/core_wire.py`）

新 owner：`plugins/assets/model-provider/server`（`ordessa.model-provider`
插件，六个 legacy `providerModels.*` 方法逐字保真 + 七个 `modelProvider.*`
增量；MP-12 形状门 + 137→192 测试账在 owner 侧持续守护）。

| # | 现行位置 | 内容 | 退役动作 |
| --- | --- | --- | --- |
| W1 | `:252-265` | `_PARAM_SHAPES` 六行 `providerModels.*` 声明 | 删除（声明面随 handler 一起退；order-097 的形状/方法对齐门 `:339-345` 在删除两侧后自然平衡） |
| W2 | `:354-359` | `_COMPAT_METHODS` 六行 `providerModels.*` → handler 映射 | 删除（同上，`_require_declared` 对称） |
| W3 | `:128-136` 内 | `_BINDING_ACTIONS` 的 `CREDENTIAL_*`/`PROVIDER_MODEL_*`/`MODEL_UNAVAILABLE`/`PROFILE_CONFIGURATION_INVALID` 行 | 删除（这些码的消费面只服务 providerModels 提交闸门；新 owner 的 13 码已经 `wire.error-families` 自发布，recovery 语义归新 owner 投影） |
| W4 | `:419`+`:444` | ctor `model_configs=None` 参数与 `self.model_configs` 绑定 | 删除（注入点随域退） |
| W5 | `:529-552`,`:580`,`:621`,`:636` | freeze/usage 路径对 `self.model_configs` 的引用（freeze_execution_configuration 说明、records.get、credentials.get、secret_store） | 改写或随域退（execution 冻结面是**唯一跨域消费者**，见 §2 消费者核查——必须先给 execution 侧替代供给或确认其同步退役） |
| W6 | `:1389-1394` | `provider_models_list` | 删除 |
| W7 | `:1396-1402` | `provider_models_create` | 删除 |
| W8 | `:1485-1491` | `provider_models_probe_models` | 删除 |
| W9 | `:1493-1499` | `provider_models_probe_connection` | 删除 |
| W10 | `:1501-1518` | `provider_models_update`（CAS/`RECORD_VERSION_CONFLICT` 投影） | 删除（新 owner `plugin.py:264-276` 同语义在位） |
| W11 | `:1520-1538` | `provider_models_archive`（引用冲突 rides details） | 删除（新 owner 在位；REFERENCE_STATE_UNKNOWN fail-closed 已由 reference_port 供） |
| W12 | `:1553-1578` | `_provenance` 类助手 | 删除（新 owner `plugin.py:367-390` 同枚举同语义） |
| W13 | `:1581-1594` | `_provider_model_body` 助手 | 删除（新 owner `plugin.py:351-365` 同语义） |
| W14 | `:1597-1600` | `_require_model_configs` 门 | 删除 |
| W15 | `:144-157` | `SLOT_TABLE`/`_model_reference_list`（config_describe slots 投影用） | **谨慎**：`config_describe`（`:1603+`）是 config 域投影，非 providerModels writer 本体；其 model-slot 引用投影需在 config_describe 自身退役时一并处理（不在本清单强制窗口内，登记给 012 config 域退役批次） |

## 2. 消费者核查（全部第一手 grep 实测，2026-09-28，本树）

| 消费者 | 位置 | 核查结论 |
| --- | --- | --- |
| 产品装配 | `products/server/src/ordessa_server_product/composition.py`（`compatibility_plugins`→`ServerCompatPlugin`；`model_configs=` 注入 `:410-444`） | 装配参数在 **products/**（core 禁区）：退役时由 core 同步移除注入参数——这正是"先退 compat、再装配 model-provider"顺序的原因 |
| handler 声明面 | `apps/server/src/ordessa_server/wire/handlers.py:14`（文档字符串指向 core_wire 冻结清单） | 文档性引用，随 W1/W2 删除自然失效，无需改 host 代码 |
| 边界测试 | `apps/server/tests/test_server_compat_boundary.py:35-36,159,196,223` | 断言 providerModels 六方法属于 compat 面 + `ordessa_server.model_configs` leaf 白名单：退役批次必须**同步改这些断言**（预期红→删），否则边界门把新 owner 拦在门外 |
| 兼容回归 | `apps/server/tests/test_provenance_wire_098.py`、`test_union_semantics_126.py`、`test_provider_compatibility_092.py`、`test_config_describe_slots_125.py` | 语义冻结测试（provenance/CAS/形状）：退役后由新 owner 的等价测试（`test_next_choice_wire.py`/`test_plugin_registration.py`）接账；逐条核对归集成波次，本清单列名为其入口 |
| desktop TS | 无（providerModels 经 Server wire 通用 invoke，无宿主特化消费） | 无动作 |
| 新 owner 侧 | `plugins/assets/model-provider/server`（本包） | 已就位：六方法逐字 + MP-12 AST 比对一致 + 192 测试 |

## 3. 顺序确认（S-08① 的硬约束，双方已确认）

1. **先退 compat writer**（本清单 §1 执行，同一集成批次内完成 W1-W14 与
   边界断言更新）——旧 writer 与新 owner 声明同 13 个 wire 方法，宿主
   `DuplicateMethodError` 单 owner 门会拒绝共存；
2. **再装配 model-provider**（core 在 products/server 组合中启用
   `ordessa.model-provider` 及其可选伴生 `ordessa.model-provider.adapters`/
   `ordessa.model-provider.profile`，接缝 S-03）；
3. W5（execution 冻结面对 model_configs 的引用）在步骤 1 内一并裁决：
   execution 冻结改读新 owner 的 `model_provider.catalog` provided port 或
   保持 model_configs 只读残留到 config 域退役批次——由集成波次按当时
   execution 域状态定，**不许在两步之间留下双写窗口**。

## 4. S-08② 承接方证据（PB-7 第 1 项，conformance 在案）

`plugins/assets/model-provider/adapters/tests/test_adapters_conformance.py`
金样一致性门（本提交扩展）：

- `test_codex_provider_section_matches_the_harness_golden_byte_for_byte`——
  adapters `common.render_codex_provider_section` ≡ harness
  `native_materialization.render_codex_provider_section`（两协议逐字节）；
- `test_pi_provider_object_matches_the_harness_golden` /
  `test_claude_env_matches_the_harness_golden`——pi provider 对象与 claude
  env 块与 harness 金样逐键相等（pi 的 provider 对象即本提交 PB-5 前夜的
  单 intent 形状来源）；
- `test_pinned_dialects_equal_the_harness_family_facts`——**注册路径**：
  adapters `DIALECTS` 每一 (brand, protocol) 钉值 ≡ harness
  `_FAMILY_DIALECTS`（描述符承载的方言事实是转录非独立猜测）；
- `test_registered_descriptor_native_targets_match_the_harness_pins`——
  注册路径：三品牌描述符的 file claim 目标 ≡ harness `_NATIVE_TARGET`。

harness 侧品牌渲染（`native_materialization.py` 的 render_* + 家族方言表）
退役时，以上门即承接方证据：C2 面的字节事实已在新 owner 持续守护。
