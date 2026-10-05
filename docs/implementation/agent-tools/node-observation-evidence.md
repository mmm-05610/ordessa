# AU004 Node 发布记录只读接缝

2026-10-05；前置 `b61d4dd8ce`。主会话持有共享 Core/Server/CLI/测试/Git/账本写权；三个已有审阅代理均 completed，Codex 本轮只读终审。上一工厂检查点已提交，未丢弃独立三家修复。整体仍 PARTIAL。

## 核心与网络映射

AU 合同已有 nodes list/inspect 命令目标；Core schema 已有 `agents.nodes.list/read`，此前 Server 虽生成 descriptor，但未绑定业务或在 supportedMethods 宣告。此次补原 `NodePublication.list/read` 的薄投影，不发明节点状态或查询 provider 的额外路线。

由核心 schema 发布 results.nodesList（`nodes`）和 nodeRead（`node`）的唯一 wrapper；read 未找到保持原 None，wire 返回 null。nodeRecord/nodeBinding 的 required 字段沿原 NodePublication 发布记录。Server 使用原同 Environment/Store/Policy 的只读核验与 safe_json 深度投影，不缓存记录、不创建 registry、没有原生调用或 operation/query 写入。Node list 先核 wildcard 读，再逐节点核读，任一拒绝仍整次拒绝，不静默丢项报空列表。存储能力缺席 CAPABILITY_UNSUPPORTED，不冒认空列表。

supportedMethods 宣告这两个实际绑定的方法，不以 nodePreparation=false 或 configurationManagement=false 挡纯读，也不改变 nodes/managedInput 的未就绪标志。历史发布记录在 provider 退役或冷 Environment 没有 runtime 注册时仍可读取，沿已有核心 read 语义；它不能证明当前 activation、原生进程、执行授权或配置实际值。

只改 agent-assembly/2 schema，build-time generator 生成新管理镜像与 digest；v1 与 provider 镜像内容未改变。旧 v2 镜像遇新 digest 按既有严格协商拒绝，不静默解释新结构。运行时 CLI 不导入 Core/Server/Harness。

## CLI

```sh
ordessa-agent nodes list --config service.json --service local --json
ordessa-agent nodes inspect @node-ref.json --config service.json --service local --json
```

inspect 完整 NodeRef，包括同服务环境与正整数 generation，bool/float/多余 principal 均拒。CLI 使用公开 read，无 nodes.get 或 provider private import。客户端按核心镜像验证 wrapper/record/binding、原 lineage、完整 scoped owner/source 引用、Usage/管理/访问引用；opaque leaf 身份不另造 schema。引用比较用类型敏感 canonical JSON，防 True/1/1.0 混认。拒额外 ready/state、重复 Node 列表、私有输出/配置/token。没有复制原生配置、会话事实或 durable ledger。

evidence=nodePublicationObserved/runtimeVerified=false，仅表明观察到核心发布记录。inspect null 返回 NODE_NOT_FOUND/exit4，不能算产品可用；有真实存储但零发布记录的 list 可返回空数组。缺方法、读权限、存储保证拒绝；unknown 不重发、无 fallback。

## 实际验证

`<PY>` = `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`。主会话串行测试；代理未运行测试/Git。计数是各次快照，不累加。

1. `<PY> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_node_observation_wire.py -q --tb=short`

   实现前 3P/6F exit1、0.27s，失败确认未宣告/绑定及无核心 result wrapper。薄绑定初版 7P/2F exit1、0.28s：主会话错把原 safe_json 用于 tuple 根而非 Mapping；改为原 wrapper 根，不改变 read/list 或宽化测试。修后9P exit0、0.27s。

2. 补退役 provider、缺 store、逐节点权限及冷 Environment 正反例：上一命令再加 `products/agent-tools/tests/integration/test_node_publication.py`。

   39P/0F exit0、0.68s（新14 wire + 原25 publication）。每条读前后原 SQLite iterdump 不变，证明未重激活、未写操作；受控 publication owner 并非生产 native proof。

3. `<PY> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_nodes_cli.py -q --tb=short`

   首24P/1F exit1、13.38s。测试误写wire FORBIDDEN为CLI error code；原客户端统一映射 AUTHORIZATION_REFUSED/3，修严格期待，不改客户端映射或扩错误集合。新增25 CLI门，正list/inspect/@file、缺席、wrapper/ready/bool/float/foreign/wrongidentity/owner/source/lineage/access/management/private/token、重复列表、缺方法/权限/unknown、发前引用拒绝。

4. 上一命令增加 `products/agent-tools/tests/test_distribution.py`：

   27P/0F exit0、19.21s。原fresh source/wheel/fresh venv/no-index/no-deps发行2项加强；独立安装 CLI 进程实际对 Core/SQLite＋受控HTTP完成nodes list/inspect及原配置describe/inspect/apply/query。18个HTTP请求，配置唯一作用1、queryCalls0；Node观察不调用native owner。自有wheel安装不是第三方安装，也不是Uvicorn/native进程P。

5. `<PY> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_configuration_cli.py products/agent-tools/tests/test_nodes_cli.py products/agent-tools/tests/test_provider_cli.py products/agent-tools/tests/test_profile_cli.py products/agent-tools/tests/test_discovery.py products/agent-tools/tests/contracts/test_profile_wire.py products/agent-tools/tests/test_distribution.py products/agent-tools/tests/test_bundle.py -q --tb=short`

   184P/0F exit0、85.32s。原159组合＋新25CLI；包括版本冲突/授权/重复/unknown原操作、安装/排除品牌实现回归。

6. `PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src <PY> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration docs/implementation/agent-tools/evidence/agent-unit-model -q --tb=short`

   首586P/1F exit1、34.95s。旧 test_uncomposed_node_operation_is_typed_unsupported 仍以现已绑定的list作缺席反例；将同一门转向仍未装配stop，保留typed unsupported/无owner作用断言，并加强无query、无原operation以及不宣告stop。未删除、skip门或恢复旧行为。修后全587P/0F exit0、34.32s；未新增计数，仅更新已被实施取代的期待。全部现存16 evidence测试模块及集成目录实际跑完。

7. `<PY> -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q --tb=short`

   269P/3F exit1、7.62s，0skip。原已登记 `test_n4r1_kernel_direction.py` 的 test_kernel_tree_has_no_import_of_server_harness_or_product、test_tripwire_planted_server_import_turns_the_guard_red、test_tripwire_from_import_form_is_detected_too 仍因既有 `tests/environment/test_closeout_environment_dispatch.py` 导入具体 ordessa_persistence_sqlite 失败，无新增红来源。本轮未修改或移走该测试/边界门。worker/sidecar/acp closure/claude等资源仍ABSENT，不能算绿。

8. `<PY> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_profile_service.py -k 'v2' -q --tb=short`

   最终2P/2 deselected，exit0、2.20s。新增真实隔离Uvicorn/Server进程负例：v2宣告Node方法，但该部署仍只授Profile/registry读；Bearer＋方法发现不授Node读，list/inspect均AUTHORIZATION_REFUSED3、不回退/不假报空成功。进程仅在测试临时root启动并按原协议停止；不触碰用户服务。这里是Server进程P证据，没有native Harness P、生产Node正向或任务M。此1项加入在587组合之后，不声称588完整组合已跑。

五工单strict、schema生成/核验、git diff --check均exit0，仅资料/格式门；测试全部终态。新增40项（14wire＋25CLI＋1真实Server门），原发行2项加强，不累加快照。

## 尚未完成

此处只有已有发布记录的观察，不新增 prepare、connect、任务/result、recover/stop/release、按请求键恢复丢 operationRef 的操作查找。真实 Directory/Invocation/lease/capture/receipt/effect/Session/material owner、三家完整生命周期/冷恢复及旧 model/Server 装配迁移仍未完成，三Skill仍须最终更新。C证据不能冒充原生P或任务M；M0，缺资源ABSENT。历史Core3红按原登记单独记账。无用户数据库/凭据/全局配置/登录/用户服务操作、第三方安装更新、模型调用、push/主树合并；成本unknown。
