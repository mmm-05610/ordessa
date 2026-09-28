# Requirements / Acceptance Checklist

## 设计审核

- [x] 前后端/Profile/提供者/Harness/Pacthold/Server 职责分别定义。
- [x] 两级导航、机制设置、实例编辑、会话入口与状态完整。
- [x] 覆盖、默认/清除、归档、CAS、秘密与缺席语义明确。
- [x] 外部副作用与存储事务分开，拒绝以 DB 回读冒充真实生效。
- [x] 开源参考的事实/推论/源码证据/许可未核实分别登记。
- [ ] 用户批准新增产品决策。
- [ ] 平台实际 API/应用隔离端口/迁移类型与范围授权绑定。

## 实施验收（全部尚未执行）

| ID | 必须证实 | 能抓到的反例 |
| --- | --- | --- |
| G01 | 零facet、无Chat仍管理；新facet仅注册即可 | Profile 硬编码模型/品牌；无Chat整个Profile启动失败 |
| G02 | 两级Harness/Profile与服务域隔离 | 同名Profile/原生session跨服务串路由、离线列表被清空 |
| G03 | 机制启用不赋予运行权限 | 关闭facet清数据、启用即自动批准工具、客户端伪造policy |
| G04 | 禁止新override写仍能查看/清既有覆盖 | UI禁用而API照写；禁用静默删override |
| G05 | Profile CAS/item patch保存 | 旧窗口覆盖新修订、隐藏facet随保存丢失 |
| G06 | 两会话逐item覆盖与全局更新 | 整facet遮盖、反写Profile、Provider变化后偷偷换用户模型 |
| G07 | 成功切换才清覆盖，无提示；失败不清 | DB先清、Harness失败、同Profile点击意外清全部 |
| G08 | A→B移除字段确实reset | 只写B已有字段、A权限/Skill残留、未知默认当空值 |
| G09 | 准入fence覆盖配置应用与发送 | 当前轮被更改、C选择后晚B覆盖、apply间隙发出错配置消息 |
| G10 | 部分失败阻发送，证明完整才恢复 | 补偿请求已发就声称成功；unknown自动重发用户消息 |
| G11 | crash/external-confirmed/local-failed可reconcile | DB readback造运行证据、丢journal、错误execution复活 |
| G12 | 重启恢复同conversation/新generation正确 | 新会话假冒恢复、跨进程全局配置污染旁边会话 |
| G13 | 卸载隐藏项保留值，必需未知不假绿 | 过滤未知存值使diff消失；卸载销毁运行中应用实现 |
| G14 | UI字段与实际运行权限分别校验 | prompt约束标成强制sandbox、Profile选择绕过审批 |
| G15 | schema/secret refs与脱敏日志 | 秘密换key绕过过滤、credential内容入profile导出或UI |
| G16 | 两真实业务glue+第三未知facet组合 | 提供者必须import Profile store、双向循环依赖、whole-registry注入 |
| G17 | 旧数据/ID/修订可迁移且可核查 | 升级就重建库、session冲突猜映射、原地改旧修订 |
| G18 | 浏览器与可访问性 | 200%缩放保存键消失、失焦丢数据、异步A数据覆盖B |
| G19 | 提供者可独立注册Profile设置区与预设编辑器 | 新提供者需改Profile页面、设置写入错误预设、卸载删设置、跨服务晚到保存 |
| G20 | 普通两级选择器，选择与下一次提交分离 | 常驻复杂状态标记、选择或输出结束即重启、打断当前输出、失败偷偷用旧配置发送 |

缺资源或未执行不能 PASS；不要求真实模型调用证明存储/UI，受控运行要实际走服务和adapter接口而非只调用ProfileDB。真实Harness验证单列品牌/版本/字段/应用方式，未经用户授权不运行付费模型。
