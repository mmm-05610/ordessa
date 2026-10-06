# 核心未发送拒绝与只读查询批

前置01fd4442d5，tracked clean，仅.env未跟踪、不读取。用户2026-10-06逐项明确采用两提案语义，提案裁定段已在该检查点保存。继续核心优先；主会话指导、读审、串行测试、账本和Git，三名Luna承担源与反例。

## 写权与依赖

- core_impl：environment-api新增带独立版本标识的可选未claim原子拒绝能力及export，persistence-sqlite/operation_records.py同Store实现，agents/management.py固定预留前来源并调用。原OperationStorePort不修改签名/版本，旧Store缺能力时fail closed，不用两次独立写事务。
- core_review：仅新test_pre_dispatch_refusal.py，临时SQLite原操作步骤、配置fence及授权反例；既有fixture只读。
- wire_impl：仅agents新operations_read.py、agents/public.py组合、独立test_operation_read.py；不扩wire/CLI/schema。最小只读白名单、当前principal及双read权限，复用唯一索引/Store及NodePublication，不调用任何provider/issuer或改变状态。

前者必须精确reserved/revision/digest且任何step不存在；DomainWrite与终态同原事务，CAS失败全回滚，重放不能改写别的scope；旧intent无可信回滚依据保留占用，已claim/unknown不得冒成未发送。发前授权/目录/epoch拒绝包括issuer重核路径，不只显式配置版本检查；安全phase/reason不保存异常/native正文。

后者只返回operationRef/kind/revision/status/nodeRef/hasResult，禁止intent/context/result/steps/evidence。缺索引明确notfound；损坏不可核；双ACL先拒、跨principal不泄漏是否存在；历史provider退役/无active Usage不阻断合法历史。prepare尚未publish的目标是已知审阅点：NodePublication.read先核读权后无记录返回None；须核既有合法未发布Operation目标契约，不把None自动当损坏或私自放宽其他需要已发布目标的操作。

## 验收与资源缺席

拒绝：预留后owner版本/epoch/目录/授权变化；零发、终态及基础恢复；原id回放、新id重新授权；任何claim/unknown保留；事务故障/CAS冲突全回滚；可选port/旧回滚facts缺席不可假绿。读取：跨principal/双ACL拒，损坏索引，正文canary白名单，unknown重复读零动作，provider离线/Usage退出后的历史，真实持久事实前后不变。

所有源/test作者ready后冻结，由主会话串行记录命令、退出码、数量和失败。缺能力不能空成功；不运行真实模型、原生进程、用户服务，不使用其他执行账。单测/契约和原生P/M分开，整体仍PARTIAL。资料检查不算产品验收。

## 验证账

实施中，未运行该批验证。生产writer、材料路由、access租约、CLI/Skill未因这两核心切片完成。

统一运行器与前两批相同完整PYTHONPATH/兄弟树py312 venv：`-m pytest -c products/agent-tools/pyproject.toml`＋本目录 `test_pre_dispatch_refusal.py test_operation_read.py test_management.py test_apply_profile.py test_core_profile_semantics.py test_core_harness_independence.py`（实命令每个文件均带本目录完整相对前缀）＋`-q --tb=short`。首轮**82P/17F/1E exit1、8.87s**，句柄99427terminal；错误完整保留分类：读取错把真实SQLite含record_id返回当损坏（连带多个读权/历史正反例）；canary context缺environmentNamespace；预留后失效夹具反复在fresh请求撤销；CAS注入早于管理fence预检未进入事务；缺能力fixture删除继承类属性错误且teardown报错；3个既有management/wire反例因首次拒绝不再抛原typed exception。根要求保留原公开错误合同，持久拒绝成功后抛原异常；同key随后仍读原terminal receipt，已claim保持unknown。原测试未改。全可选跳过的逐项rejected分支在根静态审阅时已恢复原行为，不扩此次权限/版本拒绝裁定范围。

各作者分别释放唯一写域后再次冻结：reader严格校验真实record_id及holder；fixture合法same-env；拒绝源码保原typed family；失效注入一次；事务CAS在helper预检后真实竞争；缺能力删除实际Mixin方法；旧intent从实际持久记录重新读回。上述均修问题而非放宽断言/skip；当前复跑另记。

同六文件第二轮**97P/2F exit1、8.99s**，句柄28892terminal。CAS fixture竞争UPDATE未commit，导致原Store拒绝nested事务而未进入CAS；只修fixture先提交竞争写，不修改Store事务安全。缺能力fixture实际删除方法，但Python runtime Protocol类型正缓存仍判真，management调用漏AttributeError；实现者补显式getattr/callable核验后，缺方法沿typed AdmissionRefused且零写，而非放宽测试。两者分别独占修复后再次冻结，第三轮另记。

第三轮同六文件**99P/0F exit0、8.89s**，句柄33523terminal，新增23项（拒绝13、读取10），原76项回归。源码及测试再次全冻结，产品全套进行中。Reader跨principal/双ACL/正文canary/unknown重读/未发布prepare/退役历史受控契约通过；首次拒绝原typed family保留并持久恢复base，低层真实CAS与trigger回滚证据通过。C级临时SQLite/受控owner，非原生P/M。

core_review独立只读终审Reader未发现阻断；发现低层拒绝能力direct replay同writes/异writes及concluded步骤直接调用尚只有源码保证，不是直接测试证据。已安排全套terminal后只释放新拒绝测试文件补两例，暂不计入已验证。其余源/test继续freeze；不在全套期间改测试。

全源码/测试冻结时产品全套统一运行器＋`products/agent-tools/tests -q --tb=short`：**788P/0F exit0、216.51s**，句柄60656terminal。不是与99加总的独立场景数，不含evidence新23项。其后只解除新增拒绝测试文件冻结补低层direct两例，生产源码不变；最终证据组合及原契约/Store回归另记，无需为仅证据新增重复同一产品快照。

全套terminal后只补2个direct store测试（生产代码及其它测试不变）：同证据/写集直接replay原receipt与fence不变，异写集IdentityMismatch且零改动；published/concluded直接refusal仍Unknown且所有持久事实不变。最终统一运行器＋16文件（前批公共输入五文件＋核心配置/wire/独立提供者/assembly/apply_profile/management/lifecycle/wire-lifecycle八文件＋本次SecretRef/pre-dispatch/read三个新文件）＋`-q --tb=short`：**293P/0F exit0、23.19s**，句柄19779terminal。包括本批拒绝15、读取10，新25项；其余268为既有及前两切片，不累计快照。

原契约与SQLite回归单独串行：统一运行器＋`packages/backend/environment-api/tests/test_contract_freeze.py packages/backend/persistence-sqlite/tests -q --tb=short`：**76P/0F exit0、1.05s**，句柄51851terminal。原OperationStorePort签名/版本、oe-contract/1和向量未改，可选能力有独立pre-dispatch-refusal/1标识，不将API绿当原生集成。`git diff --check` exit0。

跨作者独立终审：core_review核读取实现与不可变/ACL/离线历史；wire_impl核新事务/安全枚举/重放写摘要/claim后保护，批准窄范围无具体阻断。全optional旧分支、其它不可核实异常、旧intent/缺能力仍有明确边界，不声称它们已获原子恢复。全optional基础另已自然语言问用户并写单独提案，尚未答复。读取仅Python核心公开面，未网络/CLI；生产native输入/完整结果仍无。整体PARTIAL，P新增0/M0。

最终293项组合的完整文件参数（接在统一运行器后，再加`-q --tb=short`）：

```text
docs/implementation/agent-tools/evidence/agent-unit-model/test_public_input_composition.py
products/agent-tools/tests/integration/test_managed_input_reservations.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_sessionless_input.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_publication.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_journal_publication.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_core_profile_semantics.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_core_profile_wire_v3.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_core_harness_independence.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_apply_profile.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_lifecycle.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_wire_lifecycle.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_configuration_unresolved_secrets.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_pre_dispatch_refusal.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_operation_read.py
```
