# 两项整合阻塞：来源、最小方案与验收边界

这是诊断与待裁定方案，不是设计批准或完成验收。来源逐文件哈希和 AST
证据见 `blocker-diagnosis.json`，实际导入/入口诊断见
`blocker-dynamic-diagnostic.json`。main 未移动，未启动服务或调用模型。

## Engineering：保留了较新的业务源码，但其下层协议已改变

比较基准是已保全的 **nightly 实际工作树**，不是 nightly HEAD。
当前 Engineering 的 118 个 application、72 个 domain Python 文件全部与该
基准逐字节相同。当前 manifest、Decision client、source reviewer 也与基准
相同。d797 和 a23 都没有该较新 source reviewer；不能把这种旧基线缺项
描述成已证实的主动删除，更不能以其缺项裁掉 nightly 功能。

| 边界 | 保全 nightly | a23 / 已接入的新下层 | 实际影响 |
|---|---|---|---|
| Decision 发行版 | `decision-runtime==0.1.0`，Graph/TrustedFlow API | `0.2.0`，Job/DecisionRunner API；f6d 接入 | Engineering 旧导入不再存在；改版本号不能修复 |
| Schema | Engineering、Interfaces 都用 `jsonschema==4.19.2` | Interfaces `>=4.20,<5` | 新旧约束交集为空；不是原 nightly 内部冲突 |
| Graph | nightly Engineering/Decision 声明 `pydantic-graph==2.54.0` | a23 Decision 不再依赖；a23 Engineering 也移除 | 本机缺少该外部依赖是既有测试限制；单独安装也不能补回 0.2 删除的 API |
| Server 依赖 | Server 同时依赖 Engineering 与 Decision 0.1 | 未提交 Server manifest 依赖 Engineering 与 Decision 0.2 | 与冻结 Engineering pin 直接冲突；应修边界，不能删依赖掩盖功能 |

具体消费者：

- `adapters/decision/client.py:7,31,47`：旧 request/flow/services、内存证据。
  a23 有 rules-only 替代实现，仍调用 Engineering 原 `ReviewPolicy`；可作为
  窄适配候选，但返回证据由旧 run/answer 改为 job/summary，仍需等价验证。
- `adapters/decision/source_reviewer.py:21,200,228,268,531,608`：原始运行
  manifest、开始/结束事件、request/flow/provider 绑定、durable reader、
  request version/fence 与 BlobStore 收据。0.2 的 summary API 不是这些接口。
- `adapters/profile_flow.py:9,13,32`：旧 TrustedFlow/GraphBuilder 与 durable
  services；`adapters/execution_profiles.py:14,20`：TaskBrief、旧 Profile
  revision API、在线 UnitManager/UnitSpec。不能仅替换 Decision import。
- `adapters/profile_method.py` 的 Unit 创建接缝也需要接到当前 Agent owner。
- `adapters/registry/source_integrity.py:36`：运行时（非仅工具）校验
  DecisionRequest、Graph 版本和旧 Decision 文件清单；普通 import 成功并不
  表示可用。实际调用 `implementation_facts()` 拒绝
  `operation_registry_dependency_unavailable`。

实际纯导入诊断：client、source reviewer、profile_flow 均在 BusinessOutcome
导入处失败，execution_profiles 在 TaskBrief 处失败。未运行任何审查业务。

**最小可保留语义方案（待裁定）**：允许上述 adapters、registry 源闭包声明/
生成物及 Engineering manifest 做窄适配，domain/application 不改。local
selector 用原 ReviewPolicy 的 rules job；Profile/审查问答接新 Job/provider
和真实 Agent owner。保留原 SQLite 请求、批准绑定、角色分离、BlobStore、
预算/未知结果和历史读取；禁止另建兼容在线 runtime 或伪造旧 run manifest。

其中本地 rules 适配不必改变审批语义；source reviewer 的证据投影版本、旧
收据读法及新 Decision 原始证据能力需要明确映射。若新公开 API不足，应在
Decision owner 增补真实可校验的证据接口，而不是在 Engineering 伪造原始
事件。旧 v2 每份 source 可达 256 KiB，新 Decision canonical 值上限
512 KiB（默认 job 值上限更小）；完整双文档与元数据必须实际测试，不能截断
源文档或悄悄收窄受理范围。

验证条件：原 local selector/固定 Profile/source-review v1/v2 断言等价；
篡改 request/fence/provider/manifest/Blob 拒绝；作者与 reviewer 分离；
批准仍绑定原 target/digest；预算、cancel/UNKNOWN 不重发；原 SQLite/Blob
历史证据仍可验证；只在真实发送前 reservation/guard，不持锁等待响应。
Schema 必须保留原 Draft202012 与引用/格式边界。外部安装仍受原拒绝限制。

这不是必须修改业务批准规则的问题，但也不是可自动放行的 pin-only 改动。
需要裁定是否解除这些**适配边界**的冻结，以及证据版本兼容方式；没有理由
因此暂停或删除整个 Engineering 功能。降级 Decision、并行恢复旧在线运行时、
删除 source reviewer 或断言均不作为机械合并方案。

## Server：保留 HTTP 启动与新增单次 CLI 可以共存

保全 nightly `__main__.py`（sha256 `b3e27f30…`）提供 transport grammar：
`--data-root` / `ORDESSA_DATA_ROOT` / 默认目录、`--port 0`，先绑定 loopback
socket，启动一个 ASGI worker，真正启动后输出唯一的
`{event:listening,origin,serverId,pid}` 握手，长期服务并在停止时释放资源。
`/live` 是桌面的 readiness probe；token 路径仍由共享 layout 声明。

桌面 `server-bridge/src/runtime.ts:92` 调用 `python -m ordessa_server`；
`lifecycle.ts:217` 正常通过环境传入 data root，读取 stdout 握手后 probe。
显式 `--data-root --port` 是现有 live test 的调用方式，两者都应保留。

a23 的 `__main__.py`（sha256 `aa24f23b…`，本轮尚未提交）直接调用
`entrypoints.cli.main`。它要求 `--state` / `ORDESSA_STATE`，执行一次环境
registry 命令退出，不监听 HTTP、不发握手。实际以旧参数调用返回 2：
`ordessa: --state or ORDESSA_STATE is required`。因此这是本轮照搬较旧 a23
入口会引入的桌面回归，不是“冻结 Engineering”带来的必要结果。

**建议最小范围（待裁定，未实施）**：

1. `python -m ordessa_server`、`ordessa-server` 保持 HTTP 启动入口；另有
   `ordessa = entrypoints.cli:main` 保持新单次 CLI。无需修改桌面启动协议。
2. 新增 `entrypoints/http.py` 承载原 transport grammar/socket/握手；保留
   `bootstrap/data_root.py`、`handshake.py` 和共享 JSON layout。
3. HTTP 的长生命周期装配接当前 `RegistryRuntime` / CapabilityHost /
   Agent owner。保留原 token、server identity、root proof 的 owner 和
   context mapping；不能把 LocalForegroundAuthority 安装到网络端。
4. 通过现有 `ordessa_interfaces.http.create_app(HttpHostView)` 的最小
   lifecycle/wire port 适配保留 transport 表面，或扩展 registry transport
   达到相同服务协议。后者不能只补 `/live` 就声称旧 HTTP 全部兼容。

不能原样恢复旧 main：其 `plan_server_cli/build_runtime` 会进入当前仍保留的
`composition/runtime.py` → UnitRuntimeOwner；新的 product 只提供
`require_agent_inputs/assemble_owner/build_capabilities`。入口分离是机械修复，
实际 host composition/port 对接是必要适配，不需要撤回 capability 迁移。
当前 `build_product_registry_runtime` 已能持有真正 owner/root 生命周期，
但默认 product 没有自动提供 Profile/catalog/endpoint/authority 等可信输入。
应接回原应用提供的真实配置与授权，不得以测试 owner、环境自动授权或通用
unsupported 代替默认可用性。

验证条件：安装态两入口各自工作；旧模块/env/flags 启动到实际 loopback；
握手只在 ready 后出现一次；`/live`、认证前拒绝、当前 server.hello 与
operations.call 正常；停止释放 lock/owner；重复启动和异常清理保留原断言；
桌面 lifecycle 与真实受控 HTTP/CLI 联测。全程测试临时根，不迁移真实 DB。

保留原 HTTP 可用性本身不需要重新批准业务设计。需要裁定的是允许完成上述
host 接缝适配，以及明确默认部署如何取得原可信 inputs；未作该裁定前保留
所有源码与未提交改动，不关闭功能，也不推进 main。

补充实测：原桌面 bridge lifecycle 16 项在允许的本地测试执行中全部通过。
受限执行的 11 PASS / 5 子进程输出超时原结果仍保留。这 16 项使用测试
自有 fake child，不代表实际默认 Server 已恢复 HTTP 服务，也未修改断言。
