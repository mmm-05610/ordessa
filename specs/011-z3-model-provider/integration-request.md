# Z3 integration-request（交 C0 集成主控的唯一 owner 替换清单）

本线全部提交（`96fef2db47..HEAD`）只写 `plugins/assets/model-provider/**` 与
`specs/011-z3-model-provider/**`（已用 `git log --name-only` 核对为零越界）。以下为集成期
需要 C0 完成的公共收尾；每项含旧面、新 owner、迁移与门。

## IR-1 server-compat `providerModels.*` 六方法退役 → 新唯一 owner

- 旧面（待删/待退）：`plugins/server-compat/src/ordessa_server_compat/`
  - `core_wire.py`：`_PARAM_SHAPES` 六行（`providerModels.list/create/update/archive/probeModels/probeConnection`，
    238–276 区段）与 `_COMPAT_METHODS` 对应 handler 映射（339–365 区段）、`SLOT_TABLE="providerModels"`。
  - `model_configs/**`（service/repository/probe/provider_protocols/reasoning_knobs）：运行时业务实现。
- 新 owner：`plugins/assets/model-provider/server`（插件 id `ordessa.model-provider`，已注册同六方法 +
  七个 `modelProvider.*` 新方法；形状逐项冻结于 `tests/test_plugin_registration.py`）。
- 顺序与门：**先退 compat 行，再装配本插件**（两者同时激活=宿主 `DuplicateMethodError`，G2 反例门；
  顺序反了产品起不来）。切换前用 `model_configs/**` 做行为 oracle 回放：旧记录读/写/归档同输入同输出、
  字节/ID 不变（本线 MIGRATION.md + 旧测试即回放基线）。
- 数据：无 schema 变更（同表 `server_provider_models`、同 `opaque_id("provider")`、同幂等 scope），
  无迁移脚本需求；expand/compare/switch/contract 里 expand 步已由"新插件只读同表"实现。

## IR-2 harness 品牌渲染 → 本域 adapters 的所有权转移

- 旧面：`plugins/harness/src/ordessa_harness/native_materialization.py` 的品牌渲染入口
  （`render_codex_provider_section`/`render_pi_provider`/`render_claude_env`）与
  `{pi,codex,claude}/native.py` 的 `DIALECTS`/`NATIVE_TARGET` 品牌事实。
- 新 owner：`plugins/assets/model-provider/adapters`（golden 转录 + 字节稳定渲染，
  provenance 见其 README；`tests/test_adapters_conformance.py` 钉死与 96fef2db47 行为一致）。
- 门：转移前后 byte/behavior 对照（本线 golden fixtures 即对照基线）；禁两处互调。
  harness 侧通用 codec/target/应用保留，品牌函数退役由 C0 在 harness-api 集成提交中删除。

## IR-3 产品装配（products/**，C0 独占）

- Server 侧：产品组合装配 `ordessa.model-provider`，注入六宿主端口 +
  `harness_config_port`（C2 消费视图，等 harness-api）/`reference_port`（legacy profiles 引用检查重绑，
  见 IR-4）/`secret_store`。
- 桌面侧：装配 `ordessa.model-provider`（设置分区，绑定 Server wire transport——REQ-Z3-5）与
  `ordessa.model-provider-chat`（composer.footer，等 Z2 chat-api——REQ-Z3-4）。
- 缺席对照（US-4/MP-09）：只装设置/只装 Chat+Harness/卸载 model-provider 三组合的对照在集成树跑；
  卸载后记录保留、自定义选择下轮 fail-closed。

## IR-4 legacy profiles/sessions 的引用与事实绑定

- legacy profiles 的活动引用检查 → 绑到 `ordessa.model_provider_profile.ProfileViewReferencePort`
  （端口面 `model_provider.catalog`/`model_provider.choices` 已 provided_ports 导出）。
- TurnFact 持久化：核心 `NextTurnSelector` 状态为进程内；会话域持久化归会话所有者（C0 集成），
  不由本域私建第二状态库。

## IR-5 根锁与共享文件

- 本线对根 `package.json`/`package-lock.json`/`tooling/**` **零改动**（git 已核对）；
  TS 测试经根 hoisted vitest/jsdom/react 运行（frozen lock 277 packages 足够）。
- Python 三包 editable 安装（server/adapters/profile-contribution），无需新 wheel/lock 记录。

## IR-6 集成树复跑清单（C0）

1. `python -m pytest plugins/assets/model-provider`（三 Python 包，163 例）
2. `node_modules/.bin/vitest run`（desktop 10 + chat 16，包目录内）
3. compat 退役门：退行后启动，无 `providerModels.*` 双 owner；旧消费者形状门（迁移测试）绿。
4. 检查点消费：foundation/harness-api/profile-api/chat-api 固定 SHA 合入后复跑本线全套
   （结果按消费 SHA 回填 report.md）。
