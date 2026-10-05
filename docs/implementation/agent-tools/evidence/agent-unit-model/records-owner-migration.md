# 原 Harness记录owner独立分发

基线 `b2e4a1ab368de15e25d06cc467612012d7cb29f2`，clean。前轮Pi源码/生产依赖检查点属progress；本轮主会话唯一共享源码/测试/Git/账本写者。Codex先审迁移路径与所有消费者，Claude只读末端审阅，无测试/写/Git。合同只读，未创建另一共享执行者。

## 提取依据与边界

原三家独立provider都要求deployment注入同一个journal/UnitRecords，生产工厂尚缺；真实类却在monolith/application。两原实现仅stdlib＋既有Harness API/environment-api，journal以固定表名/JSON/asdict持久化、不存Python模块名。搬到已有transport会混入SQLite/owner职责，搬到API会混入实现与写入，因此在AU003允许的plugins/harness域建立 `records` 独立library分发，非plugin/registry/core/daemon；复用整个原实现，不复制三份、不另建库。

`operation_journal.py`483行、`unit_records.py`970行原字节迁 `plugins/harness/records/src/ordessa_harness_records`，最终与HEAD原bytes/SHA重核相等，见records-migration-source.json。相对UnitRecords→OperationJournal引用不改，保唯一class。原SQLite path由部署显式provision，原表/codec/事务/scope/CAS/unknown/ticket及legacy admission guard都不改。新包依赖仅原public API/environment API；import不打开数据库、不注册、不执行native、不授权限。缺authority仍拒。

old application两个文件物理删除无shim；scope内source/测试/证据及两个Pi packaging probes改同新class。application根既有服务exports/reexport仍消费同一新类，保七家原应用服务消费者，不产生第二实现。monolith显式新增own records依赖；独立三家仍duck现有ports，不被动依赖旧Harness或假装生产已装owner。

## Consumer覆盖与明确缺口

改旧application/configuration_service/native_evidence/action_execution、server_acp/native_action_executor、model/live_service、Pi配置service、application根；所有UnitRecords/confirmation/configuration/input关联/Codex证据/Claude unit测试与packaging函数内import均核对。provider-import-isolation新进程SEARCH补records/API源码路径，无skip、不依赖环境editable偶然可见。测试边界仅增加真实public records owner与已有stdlib hashlib，保原禁止Server/permissions/private实现规则。

全树活跃旧module引用剩 `plugins/profile/tests/test_harness_real_service.py:127`，不在本包任何工单write_paths。未修改它或复活shim；原完整六测试实跑2P4F exit1：前三confirmed/retry被SESSION_NEEDS_RECOVERY阻，lost-ack原activate_count1断言得到0，旧import发生在effect前。原断言保留，这些是本次迁移引入的跨域consumer债，不报继承失败。scope内一行补丁 `profile-records-consumer.patch`已准备、target未改，异步请求准确范围确认；等待答复期间独立发行/回归继续。不能用这4F说全树consumer闭合。

## 实际命令与结果

`PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`。
源码环境：`PYTHONPATH=plugins/harness/records/src:plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:plugins/harness/api/src:packages/backend/harness-transport/src`。

| 命令/场景 | 实际结果 |
| --- | --- |
| `$PY -m pytest plugins/harness/tests/test_operation_journal.py plugins/harness/tests/test_unit_records.py plugins/harness/tests/test_unit_configuration_records.py plugins/harness/tests/test_native_unit_confirmation.py plugins/harness/tests/test_action_execution_controlled.py plugins/harness/tests/test_native_evidence_boundaries.py plugins/harness/tests/test_native_evidence_controlled.py -q --tb=short` 初迁 | exit1、165P2F、2.56s；API gate缺原hashlib、native evidence gate缺新public records |
| 同组＋`plugins/harness/tests/test_agent_unit_source_ownership.py` 窄迁门后 | exit0、181P、3.05s、0skip |
| `$PY -m pytest plugins/harness/records/tests docs/implementation/agent-tools/evidence/agent-unit-model/test_input_session_association.py docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_journal_publication.py docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_configuration_barrier.py docs/implementation/agent-tools/evidence/agent-unit-model/test_provider_import_isolation.py -q --tb=short` | exit0、76P、13.88s、0skip |
| `$PY -m pytest plugins/profile/tests/test_harness_real_service.py -q --tb=short` | exit1、2P4F、0.89s，原outside consumer未改 |
| `$PY packages/backend/harness-transport/tests/acceptance_install.py --evidence docs/implementation/agent-tools/evidence/agent-unit-model/au003-records-install-final-b2e4a1.json` | exit0、8own wheel hashes、14 commands全0、pipcheck/cleaned/M0/productReady=false |
| `$PY -m pytest plugins/harness/claude-code/tests -q --tb=short` | exit0、194P、13.50s，含原real SQLite Unit lifecycle与fresh standalone发行 |
| `$PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration -q --tb=short` | exit1、311P1F、16.69s，仍strict coldgeneration目标未改 |
| strict五工单/diff/SHA/8wheel14receipt核验 | exit0，仅资料/来源及发行核验 |

新增records fresh发行1、ownership1；快照不累计。八包helper在原七包闭包加own records，保持失败/timeout receipt与不覆盖。新records三包fresh-wheel在净HOME/Python-I中实际验证无旧Harness/Server/Pacthold/产品/品牌包，patch sqlite3.connect证import无IO，创建唯一临时原journal实际reserve→unknown→同key replay→异key busy→reopen/query/reconcile保持unknown，缺UnitRecords authority typed拒。此为SQLite受控C和own安装进程；不声称native process P或模型M。

所有测试串行先收终态再下一个，句柄全terminal。两审未发现scope内新增阻断；末端原文件SHA与安装全部退出码实核。不从review文字推断测试通过。

## 生产仍缺

可分发记录实现已具备，不代表生产owner factory/InvocationIssuer装配完成。必须原Environment OperationStore＋显式authority/current-state，同scope/epoch/native evidence/lease/receipt owner，再家族projection/provider；缺可信来源不以test Records/配置文件/路径存在代替。旧live_service每次创建journal仍待唯一owner注入，原legacy guard不能放宽。冷activation generation提案仍待裁定；原Core三红、旧ServerPi/C2债、worker/sidecar/native安装资源ABSENT保留，Core/全Server/旧C2本轮未全回归。

M0、费用unknown，无第三方安装/更新/登录、用户DB/凭据/全局配置/用户服务/push/主树合并。整单AU003、其他AU production/lifecycle/tasks/results/Skill/A18仍PARTIAL。通用baseline/整个Server发行清单待整合，八own wheel绿不能关闭。显式检查点后继续真实owner/issuer接线，不标DONE。
