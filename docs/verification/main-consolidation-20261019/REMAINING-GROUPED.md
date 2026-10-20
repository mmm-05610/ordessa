# 剩余 31 路径按共同原因分组

此清单记录 ecd7b97ec8 时的待核对项；源争议关闭不等于功能或发行验收。

## A CLI 拆分/部署/发行归属（8）

已有实现，可机械适配；bundle/candidate generator 需修真实路径和已删除声明源，不能采用 a23 的 blanket build refusal。

当前 CLI/channel/client 源候选与 AgentTools owner 已在工作区；拆分 wheel 和原断言需验证后共同提交。

- `apps/cli/deployment/__init__.py`
- `apps/cli/deployment/composition.py`
- `apps/cli/deployment/configuration.py`
- `apps/cli/packaging/build_bundle.py`
- `apps/cli/pyproject.toml`
- `apps/cli/src/ordessa_agent_tools/cli.py`
- `apps/cli/src/ordessa_agent_tools/client.py`
- `apps/cli/src/ordessa_agent_tools/native_clients/__init__.py`

## B 原断言迁移（4）

原先已存在的未完成断言迁移，不是四项可删除的测试。

三个测试在 nightly 已有实际独立 owner；harness discovery 的旧 sandbox resolution 已被 SDK 删除。保留断言并明确等价接口缺口。

- `apps/cli/tests/integration/test_bca_longitudinal.py`
- `apps/cli/tests/integration/test_directory_binding.py`
- `apps/cli/tests/integration/test_staged_agent_assembly.py`
- `packages/execution/agents/tests/test_harness_discovery_consumer.py`

## C 当前 Product/Agent owner 已落盘验证（3）

现已提交、已有实际验证，清单滞后于 owner 整合。

ecd7b97ec8 的真实 HTTP/Product/root/foreground 9 PASS 覆盖当前 product/owner，两个 distribution wheel 已构建；全部安装闭包另计。

- `apps/server/deployment/default-product/pyproject.toml`
- `apps/server/deployment/default-product/src/ordessa_server_product/agent_owner.py`
- `apps/server/deployment/default-product/src/ordessa_server_product/composition.py`

## D UI seed probe 归属（1）

已有当前 seed 实现，可机械迁移。

实际 owner 是 tooling/checks/server_product；当前 consumer 两项通过，提交依赖于当前 CLI/client owner。

- `apps/server/deployment/default-product/scripts/seed-profile-ui-probe.py`

## E 原 native configuration 消费链（8）

a23 已未完成的新 SDK 消费适配；直接拷贝会撤掉较新 nightly 的 native 功能。

backend/bridge 应保留 nightly 的 selected public ports；configuration/readers/turn 不可用 stub 代替旧作用链。需逐项区分历史读取与当前 SDK effect，保留原断言。没有发现需要改变审批业务规则的理由。

- `apps/server/deployment/default-product/src/ordessa_server_product/acp_channel/profile_owner.py`
- `apps/server/deployment/default-product/src/ordessa_server_product/harness_adapters/application/__init__.py`
- `apps/server/deployment/default-product/src/ordessa_server_product/harness_adapters/application/configuration_service.py`
- `apps/server/deployment/default-product/src/ordessa_server_product/harness_adapters/application/native_evidence.py`
- `apps/server/deployment/default-product/src/ordessa_server_product/harness_adapters/configuration/model/backend.py`
- `apps/server/deployment/default-product/src/ordessa_server_product/harness_adapters/configuration/model/bridge.py`
- `apps/server/deployment/default-product/src/ordessa_server_product/harness_adapters/configuration/model/live_service.py`
- `apps/server/deployment/default-product/src/ordessa_server_product/turn_application.py`

## F Server namespace 接缝（5）

已有明确物理 owner，多数为机械接缝或拒绝恢复旧 facade。

decision bindings 属 composition；bootstrap 保持纯导入；Engineering context 属 interfaces/system-access/bindings；HTTP 属中立 transport/server。当前 HTTP 18 PASS 已验证实际服务入口。

- `apps/server/src/ordessa_server/adapters/decision/__init__.py`
- `apps/server/src/ordessa_server/bootstrap/__init__.py`
- `apps/server/src/ordessa_server/system_access/context.py`
- `apps/server/src/ordessa_server/transport/http/__init__.py`
- `apps/server/src/ordessa_server/transport/http/app.py`

## G Server 发行依赖冲突（1）

新下层与冻结/现解冻的上层接口版本冲突。

Engineering 0.1 pin 与当前 Decision 0.2 不相容；jsonschema 约束无交集。只能随真实适配更新，不作 pin-only 兼容声明。

- `apps/server/pyproject.toml`

## H 编码断言的物理 owner（1）

已有实现，可机械更新测试到实际 Infrastructure/历史 Unit owner。

保留原 canonical equality、持久化与 namespace 键断言；不得把 Unit 在线执行器重新导入到当前入口。

- `tests/contracts/test_canonical_encoding.py`

## 两个跨组契约边界

原 Server ID 来自 `composition/runtime.py:_server_id`，在注入的 DatabasePort 上读写原 `server_bootstrap(singleton=1)` 行；原 token 来自 `_ensure_token`，新运行不应建立第二 ID/token owner。旧 authority 使用 `grants=()` 与 legacy-principal 映射；旧 Agent owner 通过显式 policy/owner_ports/fresh Unit factory 注入，零参产品工厂没有当前 SDK owner 配置来源。保留 ID/认证机制可以机械迁移；不能把旧 Unit/legacy 授权自动提升成当前 Agent grant。

新 Decision 的 `DecisionsCapability.run` 真实地先 `claim_run`，再调用 runner，最后以原 scope `complete_run`；原 scoped store 提供 `get` 和已记录结果。`DecisionRunner` 保存答案 digest、provider receipt、usage、result digest，但不提供旧 run.started/call.intent/call.response/terminal 或旧 manifest reader。新运行可以绑定真实 job/result/summary；旧历史读取需要独立只读 codec/reader。尚未证明二者能满足 source reviewer 的原全部验证，不会补造旧事件或把新 summary 标成旧 manifest。

源适配不能改变批准绑定、作者/reviewer 分离、预算和 UNKNOWN 不重发。main 仍暂停。

本批核验后，C（3）、F（5）、H（1）九个源归属争议已关闭，见
`grouped-owner-resolution.json`。当前剩余 22：CLI/发行 8、原断言 4、
UI seed 1、旧 native configuration 消费适配 8、Server/Engineering 依赖 1。
历史 reader 和新 job 原结果读取另有 35 PASS，详见 `decision-read-compatibility.json`；
source reviewer 的 MethodControl/BlobStore 适配还未完成。


本轮并行实施检查点：CLI A8 与 seed D1 归属已提交并有离线三 wheel 安装证据，当前源争议 **210/223 已处理、13 待处理**。Native E8 虽已加入真实 SDK freeze/apply/query 适配，原品牌端口与队列绑定未等价，继续待处理；B4 原断言及 G1 依赖闭包同样未关闭。新证据与实际失败见 `parallel-adaptation-checkpoint.json`。保留未迁移 CLI commands/mechanism 和原 native profile restoration 源，未接受其提前删除。

2026-10-19 当前检查点（`f166a17cdc`）：**212/223 源争议已处理、11 待处理**。
B4 中 Workspace 原断言已通过原 SQLite writer lifecycle 修复与新身份 fixture 收口；
新 fixture 不再夺取现存 writer，原 CAS/namespace 断言保留。最后完整 Workspace XML 为
20 PASS、0 error，shared writer + Workspace 联合批次为31 PASS。
Sandbox discovery 的原选择函数 AST 和全部7 assert、2 raises 已迁到 Environment owner，
root 独立复跑3 PASS。先前将该选择器误判为 HarnessCatalog 缺口的说法作废。
B 现余 BCA/staged 两项，E8、G1 保持未关闭。

真实固定 Profile→Agent lifecycle 34 PASS，显式 Decision host limits 75 PASS；
现有 Agent 证据适配已提交。新增 SourceReviewer job 与 Agent dispatch 版本适配仍在工作区，
不计作完整验收。用户已明确选择新增 Agent 契约版本及对应方法版本，原版本保留历史读取；
当前实现目标为 v2 descriptor 和基于原2.7.2的 actions-v1 2.7.3 candidate。
原 candidate 不是已发布可执行 workflow，不作该声明。

发行复核见 `final-distribution-gates.json`：53个项目元数据归属一致，但 Engineering 和
system-access-bindings 均仍 pin Decision0.1；本地为0.2；jsonschema约束仍无交集。
现有 release ZIP 的三 wheel 另已直接离线安装到新隔离 venv，pip check 通过、23包文件
字节一致，原 installed acceptance 1 PASS、18次受控HTTP请求，见
`release-installed-receipt.json`。这只关闭三 wheel CLI 发行缺口。
完整 Server/Engineering 安装、Unit物理退役、原在线消费者迁移、main推进均未完成。


2026-10-19 current-job and Agent contract checkpoint: registry126→127 committed c3dc16add9, 69 focused tests passed without skips. Real historicalR1 vector and originaltool byte locks retained. AgentWork dispatchv2 committed4296fe32cc (73passed); tagged Agent reviewer roles committed39592534ef (32passed). Counts overlap with earlier component cohorts and are not additive acceptance totals. Latest user decision explicitly selects new Agent contracts/method versions and old versions for historical reads.

Current53project/99active local dependency edges have zero declared local version conflicts after the pending Engineering/bindings metadata corrections; current installed13wheel rebuild is pending. Prior installedentry1passed audited57/57/82 owner imports and zero Interfaces/contracts member overlap, while pipcheck remained red. External SecretStorage availability is still blocked; no externalpip retry. FullG1 is open.

Static retirement snapshot:1360production Python files,0parse errors,116modules with legacy findings (28host),7selected entrypoints have0direct findings. This is RETIREMENT_INCOMPLETE and does not prove transitive absence. Remaining source-conflict targets stay11, resolved212/223. AgentSubmission/report/rework/continuation, default trusted root composition, originalC/material assertions, nativequeue and nonACP bootstrap remain pending.
