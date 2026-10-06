# 本次剩余工作：夜间五路派工方案

本文件替代将整个仓库分成11领域的夜间派工理解；11领域图只作所有权参考。用户当前要的是剩余工作如何派工，本轮只准备方案，不启动夜间执行者、创建工作树或后台任务。

## 固定起点与今晚目标

实施树：/home/maoqh/.codex/worktrees/agent-tools-product/ordessa。固定起点77068e16b2475e50ceef4a51b814cff93ed221c4；新配置纯合同48/组合108、core307、产品900P，最后产品220.65s exit0。当前tracked clean，仅.env未跟踪不读。

今晚目标是完成可独立验证的核心接缝，优先让核心掌握精确控制、配置贡献经原Registry接纳、材料能受权交给指定消费方；并补原操作的公开最小查询和安装验收。不承诺一夜完成真实配置装配/Secret/三寿命/所有Harness/任务结果。没有新增模型调用授权；真实服务只自有隔离服务，禁止碰用户服务。

建议1名总协调者＋5名执行者。默认本实施树按文件独占写权；不因本方案自动获得其他树写权。每路可指导Luna完成源码/测试，主协调者唯一合同/共享导出/Git/账本/最终runner。不要按品牌把核心切成三份。

## 开夜班前必须完成的共同准备（总协调者）

1. 将下面三接缝的精确合同及对应工单冻结：核心效果计划/分阶段接合；ConfigurationProvider贡献与准入；材料读取/消费的授权目标和回执。明确字段、摘要、版本、拒绝/unknown及允许的方法形状；当前只有描述/引用纯DTO，不能把它当完整作用协议。准备引用交付必须遵守agent-control-boundary.md：核心决定动作，Harness不自行推进。
2. 最小operation read已获用户批准的语义可固定网络绑定：沿wire/1及原核心owner，操作身份为唯一参数；只当前principal、操作和目标双read ACL、六字段投影，不正文/恢复/重发。方法名/能力广告/schema版本由总协调者明确，不留执行者发明。
3. 发布一个固定合同检查点SHA及文件所有权表；5路从同一检查点读，任何改约由总协调者先更新合同后通知。没有冻结之前：B可依020准备metadata准入；D可做既有协议拒绝反例；E可复验当前安装；A/C只准备模型/反例，不编码新作用路径。不得把这些prepared任务标成ready全部派码。

## A路：Agent控制与分阶段装配（最高优先）

**交付**：把领域提供的准备计划作为候选，核心校验并固定精确效果范围，再用原staged Operation在材料核实后补入步骤；核心控制required/optional、顺序、claim/query与发布。先交纯效果计划校验及原阶段接合，再接实际材料，不跨缺口编造引用内容。

**唯一源写域**：pacthold/agents/assembly.py、management.py以及新增preparation_effects.py、staged_assembly.py。管理整单若本批不需要则不动。不得写environment.py、core/registration.py、材料源、SQLite、schema、public.py或Harness。

**唯一测试**：products/agent-tools/tests/integration/test_preparation_effect_intent.py、test_staged_agent_assembly.py（新文件）。复用已验证staged-operation/1，不重建Store/phase账。

**前置**：冻结效果计划合同；完整装配依B的可信配置路线和C的核实材料。可先完成原已核实材料输入的核心组合，但必须把调用方传入事实同原Step/receipt/Usage核实，不能信任裸引用。

**验收**：改目标/版本/声明/材料摘要或增加动作即发前拒；root材料unknown不能append；封存后旧context失效；同key查询不再prepare/start；回执丢失保原占用；核心不认识品牌。没有真实受权材料入口时仅交控制接缝C证据，纵向装配PARTIAL。

## B路：配置贡献的原Registry准入与发现

**交付**：将020独立ConfigurationProvider贡献纳入现唯一Registry；可信activation、descriptor及明确方法支持固定快照；按kind/schema/action/definition确定无歧义候选，同时固定与Runtime认可端口的关联。对外给安全metadata，缺provider为unsupported/unknown，不补空依赖。

**唯一源写域**：pacthold/core/registration.py、core/configuration_admission.py、environment.py、agents/runtime.py、新agents/configuration_providers.py。只此路可写Environment/Registry。public.py出口提交接口清单给总协调者集成。

**唯一测试**：products/agent-tools/tests/integration/test_configuration_provider_admission.py。原C1 contribution冻结三字段保持，通过原Agent additive贡献扩展；旧Registry/Runtime/material准入不改义。

**前置**：020DTO已固定；贡献声明与Runtime认可关联的确切表示须开工前冻结。没有完整compile返回合同时只接准入/发现/引用提取已冻结端口，不广告compile可执行。

**验收**：Host身份伪造、generation变化、descriptor篡改、重叠claim/歧义路线、声明方法缺实现、缺Runtime认可关联均拒；退役pin不能用于新作用；metadata无callable、输入输出副本不改内部；core原方向guard保绿。没有Runtime认可证据不放宽为信任自报。

## C路：受权材料交接与消费证据

**交付**：同原材料提供者向本次指定配置/运行消费方受权读取；核心仅协调引用/证据，不中转正文。沿唯一服务器issuer、原operation/step/Usage，结果不明只查原关联。先非秘密读取/消费确认；释放仅在本片能证明明确寿命规则时接，否则保hold并列剩余。

**唯一源写域**：pacthold/agents/materials.py、material_operations.py、新material_consumption.py，以及core/resource_admission.py中的可选材料能力合同。不得写Environment/Registry/issuer/public/Assembly。需要新Registry查询由B按冻结API提供；需要issuer适配先由总协调者安排有界串行切片，不自行造新authorizer。

**唯一测试**：products/agent-tools/tests/integration/test_authorized_material_consumption.py。受控provider明确内容读取计数；核心持久记录/日志不得出现测试正文canary。

**前置**：用户已批准指定消费方受权读取；精确consumer pin/target/用途/证据、原context action及result DTO尚需开工前冻结。B新可信配置pin缺席时只可沿原可信Runtime消费目标做被批准范围内反例；不能伪造配置消费者已接纳。

**验收**：错consumer/purpose/version/目录/epoch拒；错issuer在claim前拒；原材料回执关系核实；unknown不重新resolve、不因无lease当无资源；读成功不等于已消费，没owner复制完成证据不释放copyComplete。冷恢复原activation仍缺公开接缝，明确NOT_RUN，不私换Store/issuer。

## D路：公开操作查询与CLI消费

**交付**：将已经实现并裁定的最小AgentOperations.read接到薄wire；CLI查询原operation，支持机器输出和明确unknown展示。先这条成熟接缝，不提前开放材料resolve/compile等未有公开合同的方法。

**唯一源写域**：pacthold/agents/schema.py、apps/server/src/ordessa_server/agent_core_wire.py、products/agent-tools/src/ordessa_agent_tools/{client.py,cli.py,新operations.py}；对应生成schema镜像；三产品Skill只补真实存在的查询指令。此路拥有schema/客户端镜像，其他路不得手改镜像。

**唯一测试**：新products/agent-tools/tests/integration/test_operation_read_wire.py、test_operation_read_cli.py、test_configuration_provider_wire_boundary.py。旧测试仅必要兼容夹具修改并保断言。

**前置**：总协调者固定网络合同与广告能力，不依A/B/C完成。冻结前可立即做既有v3未知method/capability/非法DTO参数拒绝反例，不新增自定协议。

**验收**：当前principal/双read ACL、缺/他人operation不泄漏、六字段且无正文/evidence/step、断连/版本错/授权不足、一次查询零owner/claim/恢复。CLI不导入core/Server/Harness，不自动重试或把查询回执当任务完成。无完整任务结果正文属于明确剩余，不能由本路自行扩展。

## E路：独立安装、隔离与反例验收

**交付**：先在固定起点亲自build/install/use，拿第一手账；等待总协调者集成检查点后再跑新增跨域场景和已安装CLI查询。分开纯DTO/契约/隔离服务/真实进程证据，输出验收矩阵与缺口清单。

**唯一写域**：products/agent-tools/acceptance/、新tests/integration/test_night_core_acceptance.py；packaging只检查不改，发现故障由总协调者另派发行切片；现packaging并非本路默认宽写权。专属临时产物只能在本树ignored dist内，不能共享或修改用户data-root/配置/凭据。

**前置**：现有安装工具可先跑。新能力需要固定集成SHA、匹配生成schema与打包资产；无资产明确ABSENT，不允许跳过成绿。

**验收**：客户端新venv仅装本地wheel、无backend imports、init不执行发现的二进制、三个Skill命令存在；自有隔离服务重启可查原操作且不重派；断连/重复/unknown/读拒绝逐场景记命令退出码。不得安装全局Skill、调用真实模型或重启用户服务。资源缺席时交PARTIAL报告，测试不可删断言/skip。

## 并行、集成与晨间交付

开工前合同串行冻结 → A/B/C编码并行，D独立成熟查询接缝，E基线安装验收 → B/C固定接口检查点 → A纵向接合 → 总协调者逐路读审并串行集成/测试 → E固定集成版安装复验。这里是产品开发依赖次序，不是新增Agent DAG能力。

公共agents/public.py与总账/合同/跨路变更由总协调者唯一写。现Core Store能力满足两阶段原子封存，没有已证缺口不得让A/C顺手改SQLite；若发现真实持久缺口，作为协调者安排的独立串行切片。共享测试必须所有作者明确冻结后串行跑；执行者不各自从共享脏树宣称全套通过。不推送、不合并主树；每路提交由总协调者按具名文件保存固定检查点。

每路回报：基线/修改文件/接口交付、命令/退出码/实际数量、首次失败及修复、未验范围与缺资源、当前unknown是否保占用、无模型/用户服务操作。晨间按实现完成/受控已验/真实隔离已验/NOT_RUN分账，不要求用一个总绿覆盖全部缺口。

这五路是待正式工单化的派工方案；当前未新派编码。未冻结的A/C作用合同、B原生认可关联、D网络合同必须由总协调者先完成，不将设计任务冒成ready编码任务。Harness品牌扩展、旧消费者大清理和更多发行特性暂不派，避免抢占核心收尾资源。
