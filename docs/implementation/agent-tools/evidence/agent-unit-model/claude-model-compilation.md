# AU003 Claude 纯模型配置能力迁移

执行基线 `3c83819e23ce36beda9c34be79d56b8c2e4bef88`，clean。主会话唯一共享源码/Git/测试/账本写者；Claude/Codex代理只读盘点与复核，无写入或测试。上一轮实际检查点属于progress，本轮从原配置语义迁移继续，不以新增拒绝替代正向能力。

## 所有权与复用依据

旧Claude `configuration/model.py` 是stdlib＋纯common/types的模型/endpoint/SecretRef编译器；迁到独立 `ordessa_harness_claude_code.acp_model_configuration`，旧文件删除无alias/shim。旧bridge和原测试直接消费独立实现。原全部DTO class bodies原样迁到已有公共 `ordessa_harness_api.model_compilation`，删除旧types.py；原generic parse_version同体迁入公共模块。公共包无新registry/授权/Store，不发布另一AgentUnit协议，DTO不授予权限。共享载体复用已有API，不新增包；Pi/Codex纯compiler只改DTO来源，其成熟语义保留。

Claude旧ACP dialect/version/target事实归独立acp_model_facts；旧model/common导入同一事实。历史>=0.81<0.82指ACP adapter（受控pin0.81.2），不是当前SDK0.2.163兼容证明；不将其映射为provider当前supported methods。旧claude/native.py及native_materialization还保留其他历史事实/消费者，这里不声称全品牌facts唯一。

独立Claude pyproject显式依赖既有harness-api，旧Harness pyproject显式依赖独立Claude以消费pure compiler；无独立→旧Harness依赖。Claude安装测试补齐第五个自有wheel、pip check、无Server/Plugin API/SDK/产品/大Harness，并在python -I实际正向编译及版本轴拒绝。原attachments6测试/metadata/独立provider默认缺start仍保留。共享安装exercise现在七包13命令（多一个公共API构建），继续显式新证据/失败回执/不覆盖。

## 实际正向能力及修补

保留instance范围、model-only session-local、endpoint→env/ANTHROPIC_BASE_URL、SecretRef→BindSecret、restart-resume及同session读回事实。新增反例证实旧实现会遗漏credential-only变更、endpoint+model同时改漏model，缺session/model或bool/int混同仍可match。修补后credential-only保ref且不触endpoint；endpoint变更同时保desired model；缺ref、非bool变更事实、非法endpoint/target/ref拒绝；未观察model/native identity保持unknown。

SDK原有_native_identity函数字节逻辑不变迁到native_identity.py，两消费者复用，拒default选择器、控制字符、非UTF8。只读末端复核通过。源码收据 `claude-model-migration-source.json` 区分初次class/function AST等价与之后安全修补，原DTO class AST仍相等，final SHA与SDK函数AST实际核验，不能把初次等价声称final compiler无改动。

verify成功只证model/same native session，证据层仍session-readback；完整endpoint/credential/restoration生效需原operation、scope、capture、receipt和真实owner确认，本切片未新增routing readback协议，也未接入production apply。仅pure compilation成功不发布applied/ready。

## 实际串行命令与结果

解释器 `$PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`；源码环境`PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:plugins/harness/api/src:packages/backend/harness-transport/src`（最初pure组合仅Claude/API两路径）。

| 场景/命令 | 退出码、数量、耗时 |
| --- | --- |
| `$PY -m pytest plugins/harness/tests/configuration_model/test_adapters_conformance.py plugins/harness/tests/configuration_model/test_request_params.py plugins/harness/api/tests -q` 初迁 | exit1、76P4F＋37subtests、0.30s：pure导入门尚禁公共DTO/仍期旧compiler路径 |
| 同组迁门后 | exit0、80P＋37subtests、0.35s |
| `$PY -m pytest plugins/harness/claude-code/tests/test_acp_model_configuration.py -q --tb=short` 初13 | exit1、2P11F、0.18s：证实旧能力漏项/身份错误确认 |
| 新13＋原pure/API组合 | exit0、93P＋37subtests、0.25s |
| `$PY -m pytest plugins/harness/tests/test_agent_unit_source_ownership.py plugins/harness/tests/test_brand_organization_gates.py plugins/harness/claude-code/tests/test_acp_attachments_distribution.py -q --tb=short` | exit1、20P1F、6.54s：唯一原旧batch发布正例，断言保留；fresh五包安装成功 |
| `$PY -m pytest plugins/harness/claude-code/tests -q` 中间快照 | exit0、175P、13.47s：新13，后续校验尚未纳入 |
| 新29边界扩展未补校验 | exit1、15P14F、0.23s：default/control身份、ref/endpoint类型、外family及bool变更事实 |
| 新29＋SDK＋原pure/API | exit0、142P＋37subtests、0.40s |
| `$PY -m pytest plugins/harness/claude-code/tests -q` 末端 | exit0、194P、13.47s：新32纯编译门＋原162；包含最终fresh五wheel和pip check |
| `$PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration -q --tb=short` | exit1、311P1F、16.84s：仍原strict冷代次目标，未放宽 |
| 新model＋SDK＋原pure/API＋source ownership＋installer faults最终组合 | exit0、159P＋37subtests、0.94s |

最终组合完整参数为：
`$PY -m pytest plugins/harness/claude-code/tests/test_acp_model_configuration.py plugins/harness/claude-code/tests/test_sdk.py plugins/harness/tests/configuration_model/test_adapters_conformance.py plugins/harness/tests/configuration_model/test_request_params.py plugins/harness/api/tests plugins/harness/tests/test_agent_unit_source_ownership.py packages/backend/harness-transport/tests/test_acceptance_evidence.py -q`。

原pure import gate只允许确切`ordessa_harness_api.model_compilation`，未放开私有Harness/Server/产品；旧bridge allowed compiler改为独立Claude具体模块。品牌组织原expected file指向实际新owner，原旧batch发布期待不删除。新增32模型测试＋1ownership门，增强原发行1和迁移原导入断言，不累计快照。既有旧C4 27setup错误、本轮未重跑；原Core三红/旧ServerPi红仍登记，未报全Server/Core绿。

实际七包安装命令：`$PY packages/backend/harness-transport/tests/acceptance_install.py --evidence docs/implementation/agent-tools/evidence/agent-unit-model/au003-claude-model-install-3c8381.json`：13命令全部exit0、七wheel摘要、临时清理true、M0/productReady=false。该初回执早于最后target校验及公共模块说明修订；最终源码另写final新回执，不覆盖它。最终值在status记录。

## 未完成范围

本切片C＋自有安装子进程，不是native Harness P或真实模型M。生产准备材料/Directory/Invocation/Secret解析/Session和receipt owner、三家完整配置/生命周期/旧Model/sidecar迁移、coldgeneration裁定、tasks/results/connect/stop/release、Skill真实Agent评估及A18纵向仍PARTIAL，资源ABSENT不算绿。M0、费用unknown。未第三方安装更新、登录、用户DB/凭据/全局配置、用户服务操作、push或主树合并。所有测试句柄terminal后显式stage已读文件检查点继续。
