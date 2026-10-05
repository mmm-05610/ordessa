# 迁移与归组
## 先接纳现有工作
本树3086825a61之后已有未提交核心和三家修复。AU001记录真实HEAD、dirty逐项来源、运行子代理写权和当前测试基线；不得reset/stash/覆盖，不以材料观察SHA强迫回退。
与旧AT009/010/011共用文件时，本执行者在阶段边界统一接纳，以本包语义为准，不启动第二共享写者。

## 目标组织
packages/backend/pacthold/src/pacthold/agents：Profile/装配/Node/输入接纳/管理协调公开面。
公共注册、授权、持久操作和生命周期继续原地使用。
plugins/harness/pi、codex、claude-code：分别独立包/注册提供者，拥有native配置与通道。
plugins/harness作为纯目录组，不再是三家的统一运行时插件。
公共运输仅在确有重复且测试证明可复用后提取到公共包；不默认新增harness-api。
products/agent-tools：薄CLI、通用服务/入口客户端、三个Skill、可选deployment、打包测试。
大Harness插件中其他七家保留在暂存迁移范围，不冒充已拆完。可以保留只服务未迁家族的原包，必须排除三家运行时注册；这是明确过渡，不是三家兼容shim。

## 分离步骤
先接口冻结→补核心协调→逐家包/入口/资源提取→产品只选独立三家→去除三家的旧注册/旁路→薄CLI及Skill→打包验收。
共享文件、生产composition、公共transport与生成schema主执行者独占。
家族子代理只写自己的包及测试，不改调用方，不写Git。
优先复用旧Go bridge或官方实现；是否选择ACP按能力/维护/许可/升级成本记录。新Python客户端不直接机械搬家后称完成，先判断复用与去重。
默认产品不在失败时fallback，不能同时两路创建同一native会话。

## 标识与持久化
包目录和distribution可拆，但已有provider/family/extension/data-root/DB/部署ID不得因新包名改变。
需要改用户数据或标识必须提供迁移说明并等待用户确认；可继续不受影响项。
旧配置scope与native session绑定沿用可验证映射；不能用文件夹存在当归属证明。
移除旧导入前核对所有消费者；不恢复legacy兼容链。临时过渡路线必须列退出条件，不能长期双写。

## 产品命令目标
ordessa-agent providers list/describe；
profiles保留现有操作；
nodes prepare/list/inspect、configuration describe/inspect/apply/query、apply-profile、connect、recover、stop、release。
最终命名AU001统一冻结，Skill/CLI/help/schema必须一致。
没有生产接线的命令明确拒绝且capabilities=false；不让native_clients可导入冒充可用。
