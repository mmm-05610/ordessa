# T04-adapters（L1）：Codex/Claude native lane 纯函数与自有 intent DTO

批次：Q4 T04 不依赖 harness-api 的 L1 部分（harness-api 未发布；发布后按
contracts.md:70「名称不吻合用薄适配」对接 C2 类型）。
基线 HEAD：`964bea3937`。运行环境：仓库根 `.venv/bin/python` = Python 3.12.14。
纪律：零 git 写操作、零既有文件改动（本次全部为新增文件；`git status` 仅见
`??` 条目，并行写包的 `backend/migration.py`、`tests/migration/**` 非本包产物）。

## 1. 产物与符号（file:line）

根：`plugins/assets/mcp/`

### backend/native_intents.py（共享 intent DTO，确定性序列化）

| 符号 | 位置 |
| --- | --- |
| `DESTINATION_INSTANCE_CONFIG` / `DESTINATION_SESSION_OVERRIDE` / `DESTINATION_KINDS` | native_intents.py:38-40 |
| `InstanceConfigTarget`（实例配置路径形状；构造即校验：canonical 绝对路径、无模板花括号、后缀配 format；等价 registry schema.py:80-87 界，不 import host） | :71-96 |
| `SessionOverrideTarget`（会话覆盖形状，无路径） | :99-119 |
| `CredentialAttestation.is_valid`（模式=`authorized-instant-resolution`、resolver∈{harness,managed}、必须带 revision） | :129-151 |
| `CredentialProvenance` Protocol（注入缝） | :154-159 |
| T04 新登记码（errors.py 冻结不动，先例=secret.py:52-54）：`MCP_NATIVE_NAME_CONFLICT`、`MCP_CREDENTIAL_PROVENANCE_UNPROVEN`、`MCP_NATIVE_TARGET_UNSUPPORTED`、`MCP_PERMISSION_ENFORCEMENT_UNPROVEN` | :174-177 |
| `SlotValue`（只有 literal / secretRef+ref+revision 两形；**无明文字段可写**） | :192-205 |
| `NativeServerIntent`（含 lane/owner/enforcement/markers/endpointFingerprint 绑定字段） | :208-251 |
| `NativeIntentSet`（**完整有效集合一次成 set**，无 append API；`to_canonical/serialize/compute_plan_digest`，digest 复用 `definition_digest` sha256 规则） | :254-300 |
| 观察词汇 `LOAD_STATE_*`（runtime-loaded / config-bytes-match / absent / load-failed）与 `FACT_*`（loaded/projected/catalog-changed/unknown） | :305-317 |
| `ObservedServer` / `NativeObservation`（观察者注入，Q4 不自造 HOME 读取） | :321-356 |
| `VerifiedServerFact` / `VerifyResult` | :359-399 |
| `AssessResult` 与三值词汇 | :402-418 |

### adapters/（assess/compile/verify 纯函数）

| 符号 | 位置 |
| --- | --- |
| `BrandAdapter`（品牌声明：config_key/format、允许 destination 形状、blocked 形状、只读投影冲突目标、supported_transports、`proven_routes=∅`→L1 恒不可 supported） | common.py:74-95 |
| `assess_native` | common.py:113-175 |
| `revision_transport_kind` / `endpoint_fingerprint`（stdio=command+args，remote=url；供双启动互斥占用比对） | common.py:178-191 |
| `_compile_slot`（secretRef 无有效 attestation→拒；intent 只带 ref+revision） | common.py:194-212 |
| `compile_native`（完整集合规划 + 全部拒绝对） | common.py:223-357 |
| `_build_intent` | common.py:360-382 |
| `verify_native` / `_verify_entry`（projected/loaded 分离、catalog 比对、instance identity 降级） | common.py:385-446 |
| Codex 品牌件：`CODEX`（mcp_servers/toml；instance-config 被 R-Q4-3 结构性封禁；默认 session-override→unknown）、`assess/compile/verify` | codex.py:38-75 |
| Claude 品牌件：`CLAUDE`（mcpServers/json；086 后槽位不撞投影但两路均无运行实证→unknown）、`assess/compile/verify` | claude.py:39-76 |

### tests/adapters/

`conftest.py`（封 `os.open`，`os.openat` 存在才封——本解释器无该符号；socket/subprocess
由父 conftest 全包封禁）、`native_helpers.py`（内存 DTO 工厂 + 真 digest）、
`test_native_intents_dto.py`(9)、`test_assess.py`(15)、`test_compile.py`(21)、
`test_verify.py`(11)、`test_purity.py`(7)。

## 2. 需求落点与裁定对齐

1. **DTO**：两形状 destination 全部由调用方注入（`Destination = (InstanceConfigTarget |
   SessionOverrideTarget)`，`compile_native` 对异物形状 `MCP_NATIVE_TARGET_UNSUPPORTED`）；
   无任何文件系统/HOME 读取（AST 守卫 + 运行时 os.open 封禁双证，见 §4）。
   两品牌都保留两种 destination 形状（R-Q4 裁定），差异只在品牌 policy 声明。
2. **assess**：codex→`unknown`（reason `codex-session-override-runtime-unproven`，
   研究 §3.1：session-override 路只有 codex-acp 1.1.14 dist 静态一手证据，未运行实证）；
   claude→`unknown`（`claude-native-load-and-permission-unproven`）。
   codex+instance-config→typed `unsupported`
   （`codex-instance-config-slot-conflict` + `instance-config-target-is-read-only-projection`，
   ASSET_SLOT_CONFLICT 钉在 086 测试）；无 mcp_target/key（pi 形）→`no-mcp-config-slot`；
   slots 缺 `mcp`→`missing-mcp-slot`；`mcp_key` 与品牌槽不符→`slot-key-mismatch`；
   snapshot 含 remote native 定义（本树无已证 remote renderer）→`remote-rendering-unsupported`。
   `supported` 仅当 `(brand, destination) ∈ proven_routes` —— 两品牌该集合恒空，
   参数化测试穷举品牌×两 destination 断言永不为 supported（不假绿）。
3. **compile**：纯函数。secretRef 无「授权瞬时解析由 Harness/托管面处理」证明
   →`MCP_CREDENTIAL_PROVENANCE_UNPROVEN`（模式/resolver/revision 三项任一不合也拒）；
   lane=managed 不出 native intent（仅 exclusion record：id+revision+fingerprint，
   **不含 managed 的 nativeName**）；managed 与 native 同 endpoint→`MCP_OWNER_CONFLICT`
   （harness-adapters「避免双启动的机械约束」）；`laneByDefinition` 缺绑定/非法值→
   `MCP_OWNER_CONFLICT`；nativeName 重复→`MCP_NATIVE_NAME_CONFLICT`；同 endpoint 异名→
   `MCP_OWNER_CONFLICT`（无 last-wins）；revision digest 与快照绑定漂移→`MCP_CAS_CONFLICT`；
   `enforcement:"unproven"` 且快照要求 allowNames 限缩→条目与 set 均打
   `permission-enforcement-unproven` 标记（data-model.md:38 降格条款），`strict=True`
   拒 `MCP_PERMISSION_ENFORCEMENT_UNPROVEN`（contracts.md:37）。
   **明文不可能性**：`SlotValue` 无明文承载字段；哨兵测试断言含 canary 的凭据服务面
   读出值与 canary 命令位均不出现在 `serialize()` 字节与拒错消息中。
4. **verify**：`NativeObservation`（instance/session/generation、server name、
   transport、load_state、catalog_digest）全部注入；逐 server 比对：
   session/generation 不符→全体 `unknown(instance-identity-mismatch)`；
   `config-bytes-match` 至多 `projected`，**永不产 loaded**（loaded 只允许
   观察者明报 `runtime-loaded` 时中继）；期望 catalog digest 与观察不等→
   `catalog-changed`；期望存在而观察缺→`unknown(catalog-not-observed)`；未观察到→
   `unknown(not-observed)`；观察多出的 server→`native_discovered` 只读登记
   （harness-adapters:17「原生发现」不并账）。

L1 边界如实声明：allowNames 限缩信号取自快照**全局** `allowed_tool_names`
（resolve 快照不携 per-definition selection），非按定义归属，保守标记；
`expected_catalog_digests` 为注入参数，尚未接 probe/T05 catalog 真值。

## 3. C2 / harness-api 期望类型映射表（G2 收紧素材）

| 本包符号/字段 | 未来 C2 语义（SetField / InvokeAction / 查询） | 薄适配点（发布后） |
| --- | --- | --- |
| `NativeIntentSet.harnessType/owner` | `harness.configuration-adapters` 注册键 facet=`mcp.servers`；owner=`harness-native:<type>` 唯一 owner 声明 | 名称映射即可 |
| `destination=instance-config{targetPath,configKey,configFormat}` | SetField：Harness 授权的**实例配置 generation** 单键写入（C3 合并、冲突检测，禁止整文件覆写） | `InstanceConfigTarget` ↔ harness-api config-generation handle 描述符 |
| `destination=session-override{configKey}` | InvokeAction：`session/new|resume.mcpServers` 参数（Codex 主路，R-Q4-3；Claude 侧 0.81.2 消费待探针） | 同上；apply 返回的 generation 句柄需回绑 `planDigest` |
| `entries[].nativeName` | 目标 config `mcp_key` 下的 map key；重名/原生同名冲突由 C3 拒（本包已在 compile 期先拒） | 直传 |
| `command/args` | stdio 启动字段 | 直传 |
| `env/headers slot kind=literal` | 普通字符串值 | 直传 |
| `env/headers slot kind=secretRef{credentialRef,credentialRevision}` | **G2 硬条款**：harness-api 须有「类型化凭据槽」字段——只接受 ref+revision，由 Harness 在授权瞬时经凭据服务解析；任何接受明文的 SetField 形状必须拒收（旧 renderer `resolved_env` 路不复现） | 若发布面无类型化槽，本包 intent 直接判 unsupported，不得退化为明文 |
| `allowedToolNames`/`expectedCatalogDigest`/`enforcement`/`markers` | 暴露限缩与逐工具强制证据位：宿主无法证明时按 `permission-enforcement-unproven` 降格显示、strict 拒 | C2 需回传宿主 allow/deny 算法能力（Codex enabled/disabled 后置规则 ≠ Claude，勿假设同构） |
| `lane/excludedManaged[].endpointFingerprint` | `laneByDefinition` 每 definitionId 恰一 lane + 实例级 endpoint 占用比对（apply 前重验） | managed 侧指纹来源=backend/managed lease，同一 `definition_digest` 规则 |
| `planDigest`/`snapshotDigest` | apply/reconcile 的 CAS 绑定（contracts.md §5：plan 绑定 digest 族） | 直传 |
| `NativeObservation` | C3 `verify(handle)->NativeObservation`：Codex `mcpServer/list`（含 tools）/v2 `listMcpServerStatus`（桥未接）、Claude `mcp__<server>__<tool>` 名册（086 同款）——loadState 词汇映射：runtime-loaded←活状态/名册，config-bytes-match←纯文件比对 | 观察者实现归 harness；本包映射函数即 `verify_native` |
| `AssessResult.verdict/reasons` | C2 `assess` 三值 + typed reason 线上词汇（本表 §2.2 的 reason 常量即候选枚举） | 直传 |
| 声明输入 `ProfileSpec.mcp_target/mcp_key/slots` | 读 harness registry 公开符号（research §8 G2-1） | 测试用 duck（native_helpers.FakeProfileSpec）；生产适配读真 `load_builtin_registry().get(t).profile`，边界测试不许 import host internals |
| `revision_provider` | 域内 `McpDefinitionStore.read_revision` 直连 | 无 |
| `CredentialProvenance` | Q5/C0「授权瞬时解析」公开 API 的 attest 面（backend/secret.py CredentialPort 之上的证明层） | 薄封装 |

## 4. 测试与真跑数字（本目录）

| 命令 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest plugins/assets/mcp/tests/adapters -q` | **63 passed**，exit 0（0.10s）；无 skip/xfail（grep 零命中） |
| `pytest plugins/assets/mcp/tests -q --ignore=tests/migration`（并行写包除外） | **326 passed**，exit 0 —— 本包未破任何既有测试 |
| 全量 `plugins/assets/mcp/tests`（含并行包，一次性复跑核对） | 344 passed / 1 failed，失败=并行写包 `tests/migration/test_migrate.py:135` 在途文件，非本包（其 owner 处置；本包不触碰） |
| 变异对照 1：把 verify 的 `config-bytes-match` 状态改名旁路字节相等→loaded 的守卫 | `test_config_bytes_match_never_yields_loaded` 转红（守卫 load-bearing） |
| 变异对照 2：`_compile_slot` 放行未证明 secretRef | `test_unattested_secretref_is_refused` 转红 |

确定性/纯函数覆盖：同输入双 compile 序列化字节与 plan_digest 全等、env dict 插入序无关、
verify 结果字节全等；AST 扫描 5 个实现文件禁
`os/pathlib/socket/subprocess/tempfile/io/builtins/fcntl/time/datetime/random/...`
import、禁 `open/exec/eval` 调用与 `environ/getenv/Popen/expanduser/__file__` 属性，
且全链 assess/compile/verify 在 `os.open`+socket+subprocess 封禁下跑通。

## 5. V04 格位归属（verification.md 必跑例 4 / 证据分级 :33）

**本包达 L1（固定版本文件/配置编译）的格**：
- 完整有效集合一次规划、两 destination 形状、确定性字节；
- 明文入 intent 不可能（类型层 + 哨兵字节断言）＋授权瞬时解析证明门；
- managed/native 互斥（endpoint 占用 + lane 唯一绑定）拒绝对；
- nativeName/同 endpoint 冲突拒（不 last-wins）；
- enforcement-unproven 降格标记与 strict 拒；
- verify 的 projected≠loaded 分类学、instance identity 降级、catalog-changed 判定；
- 双品牌 unknown 判定与 unsupported 结构格（含 codex 投影路封禁）。

**未达格（诚实登记，不得声称）**：任何品牌的运行时装载（L3）= 零；本包 verify 只消费
注入观察，未接真观察者（L2+ 需 harness-api C3 或受控探针）；Codex session-override
与 Claude 两路均停留 `unknown`；「额外原生 user/project/plugin 来源识别」只有
`native_discovered` 数据形状，无真机观察；`--strict-mcp-config` 零证据未建模；
Pi 不在本包（结构 unsupported 归研究 §4）。首版三品牌完成口径不受本报告影响。
