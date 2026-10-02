# 核心职责的小重构提案

状态：用户批准 R1 盘点和 R2 内部整理；R3/R4 公共接口迁移未授权。2026-10-02。
基线检查点：865f3ab45f。完整夜间顺序以 night-proposal-20261002.md 为准。

## 判断

当前图混合目录归属、运行装载和 import，导致“服务器压在内核上”的误读。
功能地位同级不表示 import 无依赖：Server 必须消费 Pacthold 治理能力，
Pacthold 不得认识 HTTP/WS、Ordessa 产品或插件。不能为图的对称制造依赖倒置。

真实源码发现：

- docs/architecture.md 仍写 Profile/Provider 在仓外、旧 baseline 缺插件；已经
  不符合当前树。应先更新事实地图，不能根据旧图大搬目录。
- desktop-platform 已是多个独立 npm 包，不是单一“大平台类”；WorkBench
  也是 packages 下独立包，采用 ordessa.workbench 扩展入口仅为加载方式。
- contracts/foundation/src/contract.ts 聚合再导出 Workbench API，同时
  product/harness-availability.ts 与宿主 runtime 的 harness 注入混入领域契约。
  这是需要收紧的跨边界聚合，不等于整个平台必须拆掉。
- SettingsContribution 平台契约与 WorkbenchComposition.addSettingsSection
  存在两个公开入口；必须审计具体消费者和实例，不能仅凭名称断言当前有两个
  活跃注册表。目标是一个登记事实，不是新增第三个设置协调器。
- Server plugin_host 管方法/路由/端口、Pacthold extensions 管资源/执行贡献。
  它们可能是不同生命周期；现阶段不能直接合并 loader/host 或全搬到 Pacthold。

## 目标职责

| 部件 | 拥有 | 不拥有 |
| --- | --- | --- |
| products | 插件清单、版本、组合选择、薄跨端装配 | 资源业务、品牌配置规则、第二份会话状态 |
| apps/desktop | Electron 窗口/进程/安全 IPC/启动 | 导航页面、配置业务、品牌适配 |
| desktop-platform | 扩展 API/装载/宿主、通用服务、基础控件、组件注册装载 | 工作台布局、Agent/Harness 业务 API |
| workbench | 导航、区域/视图/页、浮层、设置页容器和 UI 贡献注册 | 模型/Profile 状态、配置存储与应用 |
| apps/server | HTTP/WS/wire、后端插件宿主、通用运行启动 | 执行状态机、品牌实现、配置业务 |
| pacthold | execution/resource 生命周期、治理/引用/组合、内核贡献与存储契约 | 网络路由、桌面 UI、Agent 对话细节、产品品牌 |
| server-plugin-api | Server 宿主与插件之间的公开契约 | 实现、数据库、装配、运行时调度 |
| plugins | 领域数据/操作/存储、自己的 UI、Harness 品牌适配 | 反向依赖宿主内部、另造治理内核 |

基础 UI（Card/Panel/表单）继续属于平台；业务组件（chat/diff/model picker）
由插件贡献；Workbench 只决定放在哪里，ui-components 决定装哪个实现。
Connections 留平台的协议无关契约，ACP/Harness/session 是领域，不借“通用”迁入核心。

## 目标组织（保留目录和包身份）

```text
apps/desktop                 # 本机运行壳
apps/server                  # 网络运行壳
packages/desktop-platform/   # 前端基础设施；内部已是独立包
packages/workbench/          # 可装载的应用界面框架，不是普通业务插件
packages/pacthold/           # 后端执行治理内核
packages/server-plugin-api/  # 后端宿主契约
plugins/                     # 领域能力，含可选 Profile 与资源插件
products/                    # 装配这两端，不把业务规则收进组合根
```

画图分两张：职责图把内核/宿主/UI 框架平铺；依赖图标出 import 与注册/装载
不同箭头，Server→Pacthold 是正常使用，不是业务归属。不同语言子系统不要求
一一对称，也不以 packages/app 的物理位置决定“核心地位”。

## 小步实施，避免收尾期扩大风险

R1：更新架构事实、每个包的 belongs/forbidden、定位设置两个入口的实际消费者；
新增正例/反例边界测试。只读盘点先行，不改运行行为。

R2：WorkBench 内部按 layout/navigation/overlays/settings 切模块，保留公共导出、
extension id、token 实例与注册入口，不把基础 ui-components 实现搬进 Workbench。
现有 shell/model 不按行数机械拆分，只拆已有稳定责任。

R3：设置登记事实选定一个 owner。建议 UI 分区 owner 是 Workbench；若平台
旧入口仍有消费者，只能由其转发到同一登记事实，禁止双写。待消费者审计和
用户批准后定迁移策略，不能夜间静默删接口或造永久兼容链。

R4：领域契约从平台聚合导出迁往领域 owner 是中期目标。先做内部服务注入
分类，保持现有 token 身份；实际移动 HarnessAvailability/Workbench carrier
需要完整消费清单及单独迁移批准，不能本夜一次改掉所有导入。

不做：重建 backend-platform、合并两套 host、迁移数据库/数据根、改 execution
语义、换协议、把 Profile 移进内核、继续新 Harness、拆所有文件或全仓重命名。

## 验收

- 反向依赖、平台领域渗入的新反例会红；现有合法 Server→Pacthold 使用会绿。
- 现有 token 单实例/extension id/加载顺序不变，设置只登记一次、卸载只释放一次。
- UI 行为（窗口、导航、弹层关闭、输入、配置选择）及 Profile 可选性不退化。
- 受影响测试与真实隔离装配通过；缺资源/信息标阻塞，不默许跨层导入。
- 无真实用户数据/资产/登录变更。明日真实聊天验收仍由用户完成。

建议顺序：N1/N2 功能收口优先，R1 可只读并行；R2/R3 不与同一 UI 文件修复
同时写，功能验收后再落地。R4 本次不实施。这样小重构不吞掉收尾窗口。
