# 配置更新未解析秘密引用：窄幅拒绝门

前置检查点7ff3021d7b。沿原AU002及已冻结配置合同继续；完整材料授权路由尚缺，不在本批发明资源选择或秘密解析协议。主会话只指导、读审、串行运行和账本/Git，多个Luna承担源代码、测试与独立审阅。

## 写权、依赖及验收

- luna_core_impl唯一写management.py：沿现有required材料拒绝／optional skipped规则，识别递归secretRef。其他源及schema、wire、CLI只读。不改mode非None的无作用验证行为。
- luna_core_review唯一写本目录test_configuration_unresolved_secrets.py：真实临时SQLite及受控owner，验证必需嵌套引用发前拒绝（零operation/step/fence/作用），可选引用逐项rejected且owner不收到该声明；whole Profile入口及原resourceRefs不退化。
- luna_wire_impl只读合同与模式审阅。不自主执行测试、Git、原生进程或模型。作者ready后冻结，主会话串行测试，失败原样留账。

依据：029 interfaces秘密解析须授权、AU contracts配置条款；assembly已有递归拒绝未装配secretRef/resourceRefs，但management仅检查顶层resourceRefs。合法opaque SecretRef是身份引用，可以依原合同进入请求身份，绝不假装秘密已经解析。缺SecretPort/可信授权按既有required拒绝、optional跳过，不解析、不借用、不转调另一CoreDispatch、不新建registry/执行账。已有inspect/describe读回调不是作用，零作用不能错误要求零读回调。两项待裁定提案仍独立待答。

资源缺席：本批所有SecretRef均视为尚未装配，不能把不可用记绿；测试使用合法原SecretRef形状以防入口格式拒绝冒充该门。mode无变化验证不调用配置作用，保持现有行为。没有新增秘密原文、任意引用过滤或凭据读取。

## 验证账

待作者冻结后由主会话记录实际命令、退出码、数量、失败和未验证范围。单测/契约受控证据不代原生P或模型M；本批P0/M0。

## 独立边界审阅与后续接缝

wire Luna只读确认：有效apply_profile差异沿apply/reserve通过本门，mode=no-change-verification仍仅只读核实并保守记unknown/refused，不签发配置作用；Profile restore是目录metadata修改，不应新增SecretRef解析前提。此次opaque引用仍保留摘要身份，不是明文秘密。测试作者不得把描述性inspection误判作用。

core Luna只读核实access接缝：schema已有acquireAccess参数、provider已有describe_access/connect，但无统一AccessLease DTO/端口及签发来源、期限/续期、撤权传播、disconnect持有/回收和connect未知结果核实语义。InvocationContext是单步骤作用许可，Usage是持久使用关系，两者都不能冒充持续连接租约；C1资源Lease属另一ExecutionPlan账，不能直接套用。当前CAPABILITY_UNSUPPORTED/typed缺席保留。后续须先按028“撤权后旧连接立即拒写、disconnect不stop/release”冻结合同，不能从有schema广告为可用。完整材料路由同样仍缺资源选择与原Operation步骤的接缝；本窄修不意味着它完成。

统一运行器：`PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src:plugins/harness/records/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml`。

首轮该运行器＋本目录`test_configuration_unresolved_secrets.py test_management.py test_apply_profile.py test_core_profile_semantics.py test_core_harness_independence.py`（实际命令每个路径均带`docs/implementation/agent-tools/evidence/agent-unit-model/`前缀）＋`-q --tb=short`，**82P/1F exit1、6.17s**，句柄33684已terminal。唯一红：apply_profile夹具新清单遗漏原model声明，原omission门先抛ConfigurationOmissionRefused，尚未到SecretRef gate。这是测试夹具不满足完整清单合同，不能改源码或泛捕获异常冒绿；已仅释放测试作者修正完整清单、保留期待ConfigurationUnsupported及零副作用断言。其余6项新增反例通过。

仅修改whole Profile夹具沿原model声明（id/kind/schema/requirement保持，payload改为合法SecretRef），再次冻结并同五文件同命令：**83P/0F exit0、6.28s**，句柄1502已terminal；新增7项，其余76既有回归。原异常类型及全部零副作用断言保留。两个嵌套形状optional混合正常model声明，owner只收到正常model，具名secret项rejected，原请求重放效果次数保持1；原opaque引用仍在原请求身份。未假装SecretPort/材料路由可用。

独立终审：SecretRef四字段和值符合原公开DTO格式，credential只含secretRef，故原校验通过不是凭据形状非法的替代拒绝；optional真实记录owner只收正常model，原opaque身份不抹除。新文件未直接测含SecretRef的no-change；仅静态核对mode guard以及原无变化回归，不把该特定场景算已验证。Profile metadata restore同样仅核原源码边界，未追加含SecretRef新场景。完整授权材料获取、access租约签发/撤销、生产writer及结果依然未验证。

全部源/测试冻结后，统一运行器＋`products/agent-tools/tests -q --tb=short`：**788P/0F exit0、215.85s**，句柄71668已terminal。该集不包含本目录新增7项，不相加或宣称完整PJ验收。`git diff --check` exit0。真实临时SQLite/受控owner契约C，新增P0/M0，无skip、原生调用、第三方安装、用户数据/凭据/服务/全局配置操作、push/主树合并。

回归期间用户已逐项裁定两原提案：采用派发前确定拒绝的原子终结＋恢复上次基准，采用仅本principal且双读权的操作metadata读取。裁定已单独写回两提案，下一批先准备源/测试独占写域，当前检查点不声称两项已实现。
