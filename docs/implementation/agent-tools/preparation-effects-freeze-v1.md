# A 路装配冻结：精确效果计划与原分阶段接合（FROZEN 2026-10-07）

总协调者冻结，A 路正式编码唯一依据。基线 `c47696b74b11863a9ee2fd1542033e72ce9b513b`。
`staged-operation/1`（append+seal）已实现已验证，不重冻；
`agent-control-boundary.md:23` 明确“具体 DTO 尚待下一工单冻结”，本文件即该 DTO。
Assembly 现状（`assembly.py:148-159` `_plan` 取 provider plan、仅持久 planDigest；
`reserve` 固定 prepare/start 两步）保持，不得改动其 fail-closed 语义。

## 1. 效果计划 DTO（`PreparationEffects`，新 frozen DTO，放 `agents/preparation_effects.py`）

- 候选计划由领域（配置 provider `plan_preparation` 式输出或材料核实后的装配输入）
  以 `PreparationEffectPlan` 提交，字段：
  `(plan_id, declaration_digest, provider_pin, material_refs: tuple[immutableMaterialRef+contentDigest, ...],
    target, scope, before_revision, directory_binding_ref, management_epoch,
    steps: tuple[EffectStep, ...])`。
  `EffectStep = (action_id, input_digest, material_ref?, depends_on: tuple[action_id, ...],
    recovery_correlation)`。全部闭合 camelCase `to_dict/from_dict`、frozen、
  有界（steps ≤64、depends 无环、material_refs ≤256）。
- 核心固定的精确效果范围 `FixedEffectScope`：
  `(plan_id, effect_digest, action_ids 顺序固定, input_digests, material_refs,
    target, scope, before_revision, directory/epoch, recovery_correlations)`。
  `effect_digest = sha256(safe_json(FixedEffectScope))`，与 staged phase 的
  `context_facts` 绑定（见 §2），不是第二 planDigest。
- “调用方传入事实 → 原 Step/receipt/Usage”逐字段核实表（发前拒，typed）：
  1. `target/scope/before_revision/directory/epoch` == 原 Operation intent 对应字段，
     不一致 → `IdentityMismatchError`。
  2. `provider_pin` == 原 Step `pinned_provider_ref`（逐字段，复用 `_pin_equal` 模式），
     不一致 → 拒绝（provider 已换）。
  3. 每个 `material_ref` 必须在 C 路已核实材料集合中（`immutableMaterialRef+contentDigest`
     精确命中；root 材料 unknown → 不得 append，沿夜派 A:29）。
  4. `declaration_digest` == 本次声明摘要；`action_id` 不在批准集合或顺序被改 →
     发前拒（计划插入未批准动作或倒序）。
  5. `recovery_correlation` 与原 Step `recovery_correlation` 一致；新 key 不得复用旧关联。
- unknown 语义：任一核实项 unknown → 保 unknown 占用，不越关、不封存、不调用。

## 2. staged 接合（复用 `staged-operation/1`，不重建 Store/phase 账）

- 流程：`reserve_staged_operation`（root = prepare 阶段，沿既有两步）→
  材料核实（C 路 §1-§3）→ 核心固定 `FixedEffectScope` →
  `append_staged_operation_phase`（phase.steps = 效果步骤映射的 `StepIntent`，
  `invocationBindings` = 调用 binding，`contextFacts` 含 `effectDigest` 顶层新键，
  沿 staged contract §“context_facts 只新顶层键”规则）→ seal →
  原 claim/query/发布（沿 Assembly 既有 `_observe/publish`，旧授权在 phase 封存后失效，
  沿控制边界 §21）。
- 约束：unsealed 不 publish（沿 staged:28）；全部 root step concluded 才可 append
  （沿 staged:26）；unknown 不越关（沿 staged:3）；封存后旧 context 失效
  （沿 staged:28）；同 key 查询不再 prepare/start（沿既有 reserve 重放语义）。
- 回执丢失保原占用（沿夜派 A:29）；原生成功但原账持久失败 → unknown 保占用，
  不补成功。

## 3. 核心控制面（沿控制边界 §7/§21，不发明新执行账）

- 核心决定：required/optional、顺序、claim/query 与发布（沿夜派 A:21）。
  Harness 不自行推进（沿 `agent-control-boundary.md:9`）。
- 先交纯效果计划校验及原阶段接合，再接实际材料；没有真实受权材料入口时
  仅交控制接缝 C 证据，纵向装配 PARTIAL（沿夜派 A:29）。
- 核心不认识品牌：效果步骤只含 `action_id/input_digest/material_ref`，
  无品牌 codec、无原生命令翻译。

## 4. 与 B/C 的依赖接口（冻结切面，不跨路写）

- B：`provider_pin` 形状沿 B 冻结 §2 关联核验（definition 精确相等、
  `assess_configuration` 门）；A 不碰 Registry，只消费 pin DTO。
- C：`material_refs` 合法性 = C 冻结 §1 交接已核实集合成员资格；
  C 缺席时 A 只做到 §1 纯校验 + §2 空 phase 拒绝（root 材料 unknown 不能 append）。
- D：A 不碰 wire/CLI；装配结论经 D 的 operations.read 六字段可查（status/revision），
  不新增查询面。

## 5. 写权与测试归属（本轮特批）

- A 独占：`pacthold/agents/preparation_effects.py`（新建，仅 §1 两 DTO +
  核实表函数）、`pacthold/agents/staged_assembly.py`（新建，接合编排：
  reserve→核实→append→seal→原 claim/publish 调用，不复制 Store 逻辑）、
  `pacthold/agents/assembly.py`（仅新增委托入口，不得改 `_plan/reserve/prepare`
  既有语义）、`pacthold/agents/management.py`（仅整单需要时动，否则不动）、
  新测试 `products/agent-tools/tests/integration/test_preparation_effect_intent.py`、
  `test_staged_agent_assembly.py`。
  不得写 `environment.py`、`core/registration.py`、材料源、SQLite、schema、
  `public.py`（沿夜派 A:24；public 导出由总协调者复核改）。
- 管理整单若本批不需要则不动（沿夜派 A:24）。

## 6. 验收门

1. 改目标/版本/声明/材料摘要或增加动作 → 发前拒（§1 核实表逐项反例）。
2. root 材料 unknown → 不能 append（phase 拒绝，保 unknown 占用）。
3. 封存后旧 context 失效（旧 `operationIntentDigest` 的 issue 拒）；
   同 key 查询不再 prepare/start（重放只读）。
4. 回执丢失保原占用；原生成功+原账失败 → unknown，不补成功。
5. 核心不认识品牌（效果步骤无品牌字段扫描断言）。
6. 无真实受权材料入口时仅控制接缝 C 证据，纵向 PARTIAL（明确标注，不冒绿）。
