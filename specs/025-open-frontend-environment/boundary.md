# 能力边界

设计边界：平台机制与业务语义分开，证据来自 inventory。

|责任|唯一负责方|不允许|资源缺席时|
|---|---|---|---|
|发现/依赖/激活/停用|现有loader+Lumino host|Workbench第二加载器|required能力拒绝，基础壳保留|
|界面组织/布局/弹层/设置展示|Workbench|app和插件各建全局设置弹层|空工作台和平台设置可用|
|可替换呈现|ui-components|替换组件实例化新领域owner|显示缺provider及原因|
|领域事实/业务操作|领域插件共享owner|核心储存全部领域对象、控件维护实际配置|absent/unavailable，不造空事实|
|身份、操作关联和接入|通用domain access|解释品牌配置、后端执行账|不宣称一致性|
|连接状态/传输|connections、bridges、connector|pending Profile/model副本|断连/stale/unknown|
|原生差异|Harness及领域公共adapter|renderer品牌if/桥路径装配|能力协商失败，原文降级|
|平台权限/秘密/进程|main能力代理|pluginId自报即授权|缺lease拒绝|
|输入草稿|composer DraftOwner|把输入或选择label当confirmed|保留错误/未知输入|
|产品启用/默认装配|products/desktop|app.tsx业务imports|明确空enabled尊重|

只读源码、设计写入025；不能写024、生产代码、其他spec、用户数据；禁止联网下载/安装、窗口/服务/真实模型/Git写操作。离线脚本仅标准库与本目录夹具。后续packages/frontend划分是提案，不自行建立生产目录。

D1 本地待应用操作优先覆盖其声明字段，不覆盖原生已确认事实；D2 隔离第三方为默认、同renderer现有插件为明确受信模式。用户后续要求自行选择设计；并不批准真实资源授权。

安全边界反例：trusted sender+main frame可拒外部页面，却不能区分同renderer内的两个JS插件。ResourceScope、Token、React边界、CSP都不能隔离同进程恶意代码。默认隔离必须有独立来源/进程与能力代理；机制不存在时第三方执行路径不可开放。明确受信模式只对已批准的整个renderer信任域负责。
