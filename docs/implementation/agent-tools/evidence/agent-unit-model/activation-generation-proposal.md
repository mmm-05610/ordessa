# 冷重开激活代次：待裁定初始化边界

观察基线478643a80a；当前未提交独立Server wrapper实测三家可通过现有CoreBinding共享Registry，但冷重开完整providerRef重用generation=1。`Environment._activation_generations`为实例dict（environment.py:377/506）。026要求旧generation不冒认新activation，未定义冷持久分配与历史seed。新反例保留，不把受控单轮注册通过当冷恢复完成。

## 提案

沿唯一Environment、原DomainStorePort与DomainWrite CAS持久保存环境＋owner的激活代次高水位。Registry仍是唯一贡献权威，高水位只分配身份，不成为第二激活/生命周期账。所有已有Ref和owner/provider ID保持。

在Registry发布前，用明确核心内部请求身份预留下一代并确认持久提交；发布失败可耗代，高水位不得回退。预留结果未知不发布，也不自动重发；冲突不能挪用另一请求的代次。高水位record严格校验schema/环境/owner/整数类型；无存储或比较保证不得冒冷恢复可靠。

初始化必须来自部署对“全新Environment”的可信证明：自有独占root创建新持久EnvironmentId时，原Store同事务写初始化依据，此依据只允许从未激活过的owner首次分配。该证明不是请求参数/插件声明。重开读取同依据与已分配高水位；安装/enable内存为空不证明fresh。现有数据库缺初始化依据或高水位，不从现存Node/Unit最大代次猜测，也不seed1，显式拒绝，等待独立完整迁移证明。

本轮仅初始化本产品自有临时新root；不接触任何用户数据库、不做历史数据迁移。非持久Environment可保持明确的进程内模式，不宣称冷恢复能力。授权边界与所有现有目录、调用、writer和请求键机制不变。

## 必测验收

冷重开不复用ownerRef；两实例CAS仅一个取得每一代；stage/发布失败耗代但无贡献残留；提交后丢回执不发布；counter bool/float/schema/owner损坏拒绝；历史缺依据拒绝不写；旧绑定不授新代写权；同owner/provider贡献冲突仍由CoreRegistry判定。保持原失败断言，不skip或放宽为相同代次。

待用户确认的只有fresh初始化证明与历史缺证据拒绝口径；算法必须复用原Store，不能新增Registry、猜代或改持久ID。此文档不是已发布协议或通过证据。
