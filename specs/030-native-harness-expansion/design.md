# 接入结构与不变边界

## 1. 谁接入什么

```text
任意调用者
  └─ products/agent-tools：CLI＋Skill、消费者原生协议客户端
       ├─ Ordessa公开管理接口 → 同一Pacthold.agents
       └─ 授权使用入口 → Harness管理的原生工作单元
                           ├─ 原生app-server / Wire / RPC / HTTP
                           └─ 官方SDK或官方ACP（记录实际覆盖）
```

Pacthold协调Profile材料、引用、持久操作和节点；不认识供应商品牌、native方法名或会话格式。Harness准备原生实例、持有原生配置owner、发布使用/管理入口、维护原生事实和退出证据。CLI是消费者，不主持装配、不另建实例/任务库。

## 2. 通道选择不按品牌拍脑袋

优先比较上游支持的直接运行接口：原生服务协议、官方SDK、官方ACP，再考虑经过审查的第三方桥。一家可有多个候选通道，但产品运行必须明确实际选了哪个版本/通道，不悄悄fallback。

SDK只是直接调用原生引擎的入口时可以使用；不可自己重写模型/工具loop。ACP若是上游主入口可以选择；若经过第三方转换，明确其扩展损失和升级耦合，不宣传完整原生功能。一次性CLI是有限能力，不冒充持续可管理节点；PTY/模拟按键不是默认接法。

保留原生payload和未知扩展的语义，不通过逐功能白名单把整个Harness砍成sendMessage。但原生完整入口只能授予确实覆盖它全部副作用的调用者。没有可验证子集限制时不得把完整入口冒充只读observe。

## 3. 路径归属

下列是落点规则，不要求创建空目录。N001先盘点现有驱动位置，沿其正确公开边界扩充，禁止再造平行注册器：

- Harness家族的安装知识、启动/配置/恢复、管理owner在 `plugins/harness` 的现有家族模块；新家族也归此。
- 共享frame/stdio/HTTP/ACP运输实现在现有Harness通道内收敛。只有实际复用才抽取，不再加global singleton。
- CLI原生消费者可在 `products/agent-tools/src/ordessa_agent_tools/native_clients/` 按协议/家族组织；使用公开SDK或协议，不导入Harness私有模块。
- 家族配置schema、支持面和身份在Harness唯一目录发布；CLI通过已有构建生成镜像，不硬编码第二个家族列表。
- 消费者测试在products；驱动/配置owner测试在Harness；跨边界测试由主执行者整合，核心只能补已批准的通用接缝。
- Skill给通用使用规则；不得为每家又维护独立Profile状态。

## 4. 一家必须交付的内容

通道报告须包含：上游与许可、固定release/commit/二进制或SDK摘要、协议schema来源、启动参数、隔离目录和状态位置、默认网络行为、认证引用方式、真实session创建/恢复、配置能力、双向回调、取消/结束、发现未知能力与升级兼容边界。

实现至少包含可调用的原生入口和真实管理绑定，而不是仅descriptor/CLI名称。原生会话未建立可保留prepare中间状态，不伪造sessionId。配置编译归家族owner，Profile保留原kind/材料引用；不把CLI参数静态当运行时已生效事实。

每项能力记录declared/implemented/observed及独立测试层次。unsupported与unknown分开：源码证据明确缺失可unsupported，未实测不能默认false或true。禁止无证据宣称全能力/完全隔离/任意升级零改动。

## 5. 必须保持的安全及状态语义

- 原生effects前使用现有InvocationContext、step claim和DirectoryBinding，能力不足拒绝，不靠可访问目录或Bearer扩权。
- 管理和使用权可分，但共享底层物理配置/会话仍统一scope/epoch。符号链接/公共home/跨channel同资源纳入冲突判定。
- 已发送后失去回执为unknown；原生JSON-RPC id不是上游幂等保证，不自动重发/重建。只读核实不驱动新turn。
- 反向审批/文件/terminal请求保留原生身份，advertise仅自己真能处理的能力。无审批者就pending/refused，不auto-approve。
- 未验证transport fence不发新写lease；SDK自动重试、恢复、下载等默认行为必须审查和禁用/限制。
- detach只有受控持有者与callback所有权实证才发布。前台客户端退出不等于原生任务停止。
- borrowed进程仅断开/释放自身连接；owned子进程只按持久归属与PID/实例证据清理，不按名字pkill。
- 升级钉版本、测试兼容；上游新增普通method/event在授权原生通道中可用，核心无需增加业务字段；schema不兼容不能偷降级。

## 6. 前置缺口如何推进

N001必须核实029的节点准备、公开管理入口、原生session reservation和InputAttempt是否已落地。没有就继续原队列已批准工单，或把本夜运行接入标依赖阻塞。不得今晚另造core/ledger绕开它。

十家资料研究、许可/version核对、纯协议/配置编译反例可以继续。没有生产接纳链时称“适配实现/协议验证”，不能对用户发布runtimeReady=true。核心新语义、持久化迁移、新增授权机制先记录待决项，不擅改。

