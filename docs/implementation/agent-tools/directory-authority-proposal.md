# 下一接缝：DirectoryBinding授权来源（待裁定）

## 已核实的缺口

028 contracts.md §10要求DirectoryBindingRef包含ProjectRef、运行宿主与filesystem/native realm、受控目录身份、read/write/execute授权、authority revision、expiry及revalidate；这些是行为设计，未规定许可的签发者或授权来源。固定基线Workspace只有normalizedPath、connection_state投影，executableForRole=null；现有PolicyPort返回bool，没有revision/expiry。普通Bearer认证或OS当前进程能读写目录不能证明调用者有执行许可。

## 建议的最小实施口径

由现有Workspace领域签发和重核DirectoryBinding，不在CLI或Pacthold维护第二项目库。新增可选DirectoryAuthorityPort由部署显式注入，提供当前principal针对ProjectRef和用途集合的许可、authorityRevision和expiry；每次使用重核，缺席或撤销即拒绝。第一版只支持真实本地宿主；远程realm能力缺席明确unsupported，不把同一路径文字当等价。

ProjectRef从现有Workspace记录的id/version加同Environment命名空间取得，不改变旧on-disk identifiers。绑定固定项目revision、可信host/filesystem realm、规范目录身份与用途，Harness在实际宿主再次验证；CLI只能传完整绑定引用，不能传任意宿主路径替代。路径、stat/os.access仅为目标事实，不为授权证明。命名和完整DTO待此授权来源裁定后冻结在公开核心消费合同，由Workspace公开面发布schema。

## 不依赖此裁定的已完成工作

Profile纯数据CRUD/CAS/历史/replay，核心薄wire，stdlib CLI，局部Skills与安装包，隔离Server Profile验证均可独立验收。该切片不启用nodes/managedInput；没有真实模型调用。后续具名持久step、core节点与Usage原子发布、Harness unit/session目标、InvocationContext/queryStep、原生lease fence另按028实现，不能用旧协调器替代。

## 反例与缺席行为

Bearer有效但无execute许可应拒绝；项目revision/authorityRevision变化应拒绝旧binding；授权过期不自动延长；跨host同path、symlink/bind-mount共享目标不能伪装成独立配置目标；缺AuthorityPort返回能力不足而非空许可。所有测试只用临时项目/目录与显式fixture authority，用户目录和配置不动。

## R-0004 已获准及冻结的实施合同

用户明确选择建议的Workspace＋显式授权端口方向。第一版本地接缝如下，属于028行为设计的实施展开；不启用未具备的prepare或wire节点方法。

- core公共DirectoryBindingRef：environmentNamespace/bindingId/bindingRevision/contentDigest，四字段严格完整；绑定id由Workspace签发，revision为不可变记录版本；digest固定绑定内容，不授予权限。
- Workspace公共ProjectRef：environmentNamespace/projectId/projectRevision；id/version来自现有WorkspaceRecords.get，不改旧字段/存储。目录不能由调用者另传。
- Workspace公开DirectoryGrant：principalScope/projectRef/purposes/authorityRevision/expiresAt（UTC epoch有限数值）。DirectoryAuthorityPort.authorize(principal,projectRef,purposes)与revalidate(principal,projectRef,grant)返回当前grant或None；均纯只读、资源有界，授权来源由部署明确提供。
- trusted LocalDirectoryRealm：hostId/filesystemRealm/nativeRealm由部署传入（非CLI声明）。实际canonical目录及stat device/inode由Workspace获取；env_kind必须local且部署host证据匹配。单绑定不承诺配置文件隔离，Harness仍须证明target/字段组排他。
- DirectoryBindingService构造显式注入environment_namespace、principal_scope、同Environment的DomainStorePort/ProtectedFingerprintPort、原WorkspaceRecords、authority_port、realm；部署负责唯一同Store接线，服务不打开DB、不生成Environment、不import Server私有实现。缺authority/fingerprint拒issue，不静默授予许可。
- issue(request:RequestKey, project_ref:ProjectRef, purposes:tuple)返回DirectoryBindingRef；三元request身份沿R-0002，指纹绑定调用者完整输入/realm/操作类型。签发记录和request结果同事务，重放核验历史身份/内容并重新授权。principal必须与构造trusted realm匹配。
- revalidate(ref, principal, purposes)返回只读DirectoryBindingEvidence（绑定ref、固定projectRef、host/filesystem/native realm、canonical path/device/inode、grant）。重核当前project版本/归档状态、实际目录身份、当前用途授权、authority revision与有效期；不会续租或签发新绑定。过期、撤销或changed拒绝，缺资源明确不足。使用OS访问检查仅增加事实约束，不取代grant。
- 本单服务暂未在宿主发布，必须在已有贡献生命周期按可信owner接纳后才能用于节点。测试fixture注入同store不等于生产接纳已完成。
