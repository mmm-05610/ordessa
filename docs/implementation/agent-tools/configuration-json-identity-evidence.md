# 配置确认 JSON 身份防线（PARTIAL）

日期2026-10-05；前置03dfe83233。本轮主会话唯一共享作者/测试/Git，Codex仅只读审阅。上一CLI apply/query检查点后继续，未改AU合同。

## 真实问题与修正

新CLI防线发现核心ConfigurationChangeResult与AgentConfiguration仍用Python mapping相等比较原owner引用。原完整引用中True/1或1.0/1会被视为相同，错来源confirmation可能被发布为applied。新增4项DTO反例和4项真实原SQLite管理反例，首次全部失败（0P/8F exit1、0.60s），前者未抛错、后者确实published而非unknown。

DTO确认与snapshot比较改用既有safe_json。管理模块所有mapping身份比较使用_same：原safe_json包value，None/缺值也能比较，但不等于预期完整引用；涵盖当前provider、Unit/configurationTarget、snapshot、原scope fence、DirectoryBinding、原query Node/provider、applied confirmation/confirmedSnapshot和原观察去重。不新增leaf schema、引用字段、registry、操作表或配置缓存。标量DTO已严格类型的字段保持原校验。序列化保持JSONbool/int/float差异，非有限/非JSON仍拒绝。

真实管理反例已核Invocation consumption并发生一次受控owner effect，随后错确认必须保unknown、step unknown、result None，不能把后来拒绝报告成从未作用。另6项当前Unit/provider/target类型错配在inspect及apply前拒，原Operation/Step缺席、effect/query0。没有原生Harness作用或模型；本轮C分别是结构DTO和真实临时SQLite/Core+受控owner，不算P/M。

## 主会话串行命令及结果

PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python；测试句柄最终terminal。新增14项C，组合快照不累加。

- `PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src PY -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_configuration_contract.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py -k 'preserves_json_types or cannot_change_reference_json_types' -q --tb=short`：修复前0P/8F、69 deselected，exit1、0.60s。保留所有断言，没有skip/删除。
- 同两个文件去掉-k：修复后77P/0F exit0、2.69s；补当前owner6反例后83P/0F exit0、2.93s。后述末端apply额外断言仅改测试，源码未再变。
- `PY -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py -k current_unit_owner_reference_types -q --tb=short`：6P/0F、35 deselected，exit0、0.36s。实际额外调用apply并核Operation/Step仍None，不能只用inspect推断apply发前拒绝。
- 下列完整集成：563P/0F exit0、29.72s。该集成新增纳入configuration_contract42项，management比原多10项；原511+42+10=563，未将原重复回归当新增。

```sh
PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:packages/backend/harness-transport/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_provider_discovery.py docs/implementation/agent-tools/evidence/agent-unit-model/test_preparation_holds.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py docs/implementation/agent-tools/evidence/agent-unit-model/test_configuration_contract.py docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_continuation.py docs/implementation/agent-tools/evidence/agent-unit-model/test_sessionless_input.py docs/implementation/agent-tools/evidence/agent-unit-model/test_input_session_association.py docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_publication.py docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_journal_publication.py docs/implementation/agent-tools/evidence/agent-unit-model/test_prepared_input_claim.py docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_configuration_barrier.py -q --tb=short
```

核心全回归 `PY -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q --tb=short`：269P/3F exit1、7.89s。三个失败仍packages/backend/pacthold/tests/platform/test_n4r1_kernel_direction.py的test_kernel_tree_has_no_import_of_server_harness_or_product、test_tripwire_planted_server_import_turns_the_guard_red、test_tripwire_from_import_form_is_detected_too。唯一扫描命中仍既有test_closeout_environment_dispatch.py导入ordessa_persistence_sqlite；没有移走失败或绕扫描。资源报告worker/sidecar/claude/acp closure仍ABSENT、SKIPPED_TOTAL0；不当绿。

## 限制与继续项

本修正只覆盖配置DTO/manager的精确来源判断，不声称整个Core所有opaque引用比较已审完。生产权限、材料SecretRef解析、capture/receipt/effect/Session/writer、冷恢复与完整生命周期、nodes wire/按请求键查询未知操作、三Skill/旧装配迁移/真实三家P及任务M仍缺。总目标与AU002–005均PARTIAL。M0，未安装更新第三方、登录或改用户数据/凭据/全局配置/用户服务；无push/主树合并，费用unknown。检查点后继续。

调用方末端回归 `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_configuration_cli.py products/agent-tools/tests/test_distribution.py -q --tb=short`：71P/0F exit0、42.66s。含fresh wheel独立CLI对原Core/SQLite受控owner的describe/inspect/apply/query；不证明生产授权或真实Harness。五工单strict exit0、diff-check exit0，全部句柄terminal。
