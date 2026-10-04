# 当前公开接缝与待冻结消费wire

固定源码adce；用户R-0002沿用三元RequestKey，操作类型/目标/输入/CAS参与指纹比较。核心公开入口pacthold.agents.public与现有Environment共存，不经插件激活。

## 已确定的实现合同

- 同SqliteStorePort新增可选domain-records/1能力：scoped read/list、read_domain_result、commit_domain_change；data-only多行CAS和env_requests结果原子提交，无外部回调，不扩冻结oe-contract/1必需方法。0=缺席，更新revision递增；未知/legacy已用请求不可再次写。
- ProfileCatalog分catalogRevision与manifestRevision；create/read/list/edit/clone/rename/archive/restore。edit同时核完整baseManifestRef及catalog CAS；历史不可变，不与节点应用连动。
- 请求principal必须匹配可信Environment principal；同Environment policy执行surface及Profile目标写/读授权；写必须有保护指纹及原子domain能力。
- 尚未接可信leaf贡献，所以所有预览unresolved/coverage unknown/ready false，不启用prepare/apply；opaque leaf refs不声明实际支持。

## 既有网络合同

server.hello经POST /wire/v1/server.hello，body jsonrpc=2.0/id/method/params，Bearer必需；params clientVersions=[wire/1],clientPresentationSupports=[]。capabilities是id/supported/reason，不是完整schema。agent.submission.scope/capture.read/submitInput/submission.query已经存在且须复用持久owner。不得将旧profiles.v2当新核心接口。

## 待确认的最小Profile网络绑定提案

新增仅公开DTO的薄映射，不新增传输协议，沿用wire/1认证/错误/registry。需要确认其作用域与权限承载再接消费者；以下尚未注册或实现：

| method | 必需params | 可选params |
| --- | --- | --- |
| agents.capabilities | 无 | 无 |
| agents.profiles.list | 无 | includeArchived |
| agents.profiles.read | profileRef | 无 |
| agents.profiles.readEntry | profileId | 无 |
| agents.profiles.create | profileId,displayName,manifest,requestId | 无 |
| agents.profiles.edit | profileId,manifest,expectedCatalogRevision,baseManifestRef,requestId | 无 |
| agents.profiles.clone | profileRef,profileId,displayName,requestId | 无 |
| agents.profiles.rename | profileId,displayName,expectedCatalogRevision,requestId | 无 |
| agents.profiles.archive | profileId,expectedCatalogRevision,requestId | 无 |
| agents.profiles.restore | profileId,expectedCatalogRevision,requestId | 无 |
| agents.profiles.preview | profileRef | 无 |

Profile返回核心to_dict形态；manifest返回ref+content。principal不接受params，取已认证realm。schema从核心生成并由capabilities发布，不在CLI手写第二权威。capabilities逐项说明Profile数据支持与node/input未支持，不因Profile可用报整个Agent ready。

服务owner应是core bootstrap所属的公开面，既有Server registry承载薄方法；产品可选deployment选用该面，但不伪装Agent Tools插件，也不在Server自定装配步骤。当前宿主把业务wire限定为插件贡献，core内置method接纳/退役需要扩现有唯一registry接缝；没有已冻结实现。

节点wire、DirectoryBinding与现成input target的规范绑定仍缺；不使用旧runtime/private方法凑齐。待网络绑定决策期间可以完成核心数据能力、CLI发现、故障测试与wheel隔离安装。

## 当前实际交付与公开绑定（R-0003/R-0004）

Profile核心导出已在pacthold.agents.public；wire薄绑定为apps/server/agent_core_wire.py，owner=pacthold.agents仅core factory可注册。参数/结果字段、Ref类型与digest由core wire_contract生成，CLI轮询发现后严格协商schemaDigest。客户端轮包零backend依赖，不导入Server/Harness/Core模块。capabilities明示profileCatalog支持条件，nodes=false/managedInput=false；preview仍unresolved/providerUnavailable，不生成fake native session或process证据。

Workspace新公开面ordessa_workspace.public导出ProjectRef、DirectoryGrant、DirectoryAuthorityPort、LocalDirectoryRealm、DirectoryBindingService与DirectoryBindingEvidence；核心仅持完整DirectoryBindingRef。签发域记录与同RequestKey结果同Store事务。绑定是引用不是权限，使用重核current Authority、project revision、realm与实际目录object，fixed purposes不扩权；当前未在Server/Environment贡献生命周期接纳，不能用于准备节点。具体冻结见directory-authority-proposal.md R-0004。

可选operation-records/1为已有Store增量face，不增加第二协调器或Client truth。旧oe-contract/1与RequestKey三元身份保持；阶段status与知识outcome分开。具名子步骤/资源holder CAS仍在实现与验收，不对外新增wire。Harness、叶子材料与原生输入尚未补齐；原生设计缺口不得靠老profiles.v2/legacy agent链替代。

## R-0005 实际实现边界

`pacthold.agents.invocation`提供显式InvocationAuthorityPort/CurrentStatePort及进程内Issuer/受限Verifier。固定binding来自同OperationStore完整request/step，独立当前读授权与受限Cleanup，一资格消费有界且可拒复制/重入。具体冻结口径见invocation-authority-proposal.md，实际53项合同测试、全产品基础240项通过。

此端口未进入wire/schema，也没有生产Authority/CurrentState/provider实现或native dispatch。公开CLI仍只有发现/Profile数据面，capabilities nodes=false/managedInput=false。同owner Unit/Session目标与scope迁移准备见harness-target-migration.md；缺真实owner事实拒作用，不借新DTO制造ready。
