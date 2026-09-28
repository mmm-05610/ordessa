# Verification / completion checklist

以下是待实施验收规格，不是已运行结果。每门同时有正例与反例，且主链的 L3 不允许被文件存在/单测绿替代。

| G | 正例 | 反例 |
| --- | --- | --- |
| 01 | 锁 native/adapter 版本及文档/受控探针 | 官网最新版功能误宣告为仓内 pin 已支持 |
| 02 | Claude/Codex/Pi 三格分别标 native/extension-backed/unknown | 把 Pi 示例扩展称内建，或由 agent 文案证明调用 |
| 03 | 对每品牌每字段记录支持/不支持/未知和证据 | Claude plugin-scope 被忽略的权限/MCP 字段被报有效 |
| 04 | revision 不可变、内容摘要与审批来源可追 | 新版写回旧版，编辑无批准自动应用 |
| 05 | 导入安全预览并固定来源 | symlink 穿越、递归 include、URL fetch、导入即执行 |
| 06 | CAS/幂等、归档旧引用仍可读 | 同 key 异 payload 成功、归档破坏已冻结会话 |
| 07 | 用户全局/项目/品牌/Profile/会话确定性解析 | 同项目外泄、客户端伪 projectId、层次碰撞随机胜出 |
| 08 | Profile 专用只归本人且引用固定版 | Profile 复制把专用定义公开或升级自动移动绑定 |
| 09 | 资源引用逐属主授权，强制边界有效 | 定义里写 `Bash`、MCP 或 bypass 即提升工具权限 |
| 10 | 旧纯定义 dry-run/恢复字节/ID 一致 | 旧 grant edges/`run_subagent` 逻辑误迁进本域 |
| 11 | Claude 当前 pin 定义加载/移除受控可证 | 文件生成即记 loaded、被忽略字段虚报生效 |
| 12 | Codex 当前 pin TOML 加载/移除受控可证 | ACP 路径不识别却因 CLI 独立测试绿而宣告通过 |
| 13 | A/B 定义/配置实例隔离且原生同名诊断 | 同一 HOME/项目目录互相覆写、靠原生优先级选胜 |
| 14 | Pi 经已审 extension-backed 入口可用或明确缺席 | 插件偷偷安装扩展/直接调用示例派工工具 |
| 15 | Settings 空/错/归档/版本 diff/键盘可达 | 错误清草稿、另服务晚响应覆盖、权限项视觉假绿 |
| 16 | Profile 修改不立刻影响输出，下一次提交用新快照 | 选中即重启、中断当前输出、失败清旧覆盖 |
| 17 | Chat 仅对证实可调用项出 action，禁用/卸载消失 | 普通用户消息伪调用、旧 generation 菜单串会话 |
| 18 | apply Confirmed 后原消息发送一次 | 配置 Unknown 仍发送/自动重试 prompt |
| 19 | reset/重启恢复同 native session | 重启后 `session/new` 空会话冒充恢复 |
| 20 | 当前实例 busy 卸载受阻、晚到计划 stale | 先卸 adapter 再发现 reset/reconcile 无 owner |
| 21 | 干净安装/独立插件测试/typecheck/build/electron smoke | editable 指向邻树、lock 手改、只跑根 npm test 漏插件 |
| 22 | 三品牌 L3 实际产品链按支持矩阵记录 | 只有文件/格式单测就报“原生子代理已接入” |
| 23 | 受影响套件逐 ID 同因对比含收集阶段 | 只看 passed 数量/日志尾行、skip/xfail 藏新红 |
| 24 | 备份恢复与隔离环境复证、独立审阅 | 用户 HOME/原生项目定义被改而报告称零副作用 |

证据级别：L1 领域/纯 adapter 单测；L2 当前 pin 的目标 CLI/解析器或受控子进程；L3 默认产品 Server→Harness→ACP owner→受控下游的真实装载/调用链；L4 真实模型，**未获授权不执行**。若某品牌没有可靠受控调用观察，`loaded/invokable/used` 分开标 Unknown，不能从“能在菜单看见”推断 `used`。

T00/T01 填入当前分支真实构建命令、测试收集数量、工具链、红 ID、产物目录和参考 SHA。后续每轮存全文日志和 JUnit 在仓外证据根，记录命令、exit code、collected/passed/failed/errors/skipped、逐 ID/原因 diff。收集错误即 FAIL；预先登记红同因可承认继承，但新红或原因漂移不合格。实际用户目录内容不作为夹具，也不做真实模型调用。

## 设计与实施门

- [x] 此包给出所有权、数据/权限/运行边界、品牌条件和逐模块复用候选。
- [x] Pi 扩展示例、旧 Profile 派工工具与本域定义明确分离。
- [x] FR→T→G、每门正反例、卸载/恢复/同会话时机已经写明。
- [ ] 平台/Profile/Harness 最终集成 SHA、实际 DTO、许可与三品牌 pin 已冻结。
- [ ] 用户审核此包的范围/默认值并授权实施。
- [ ] T00–T15 与 G01–G24 按实际品牌可用性完成；有条件格不虚报。
- [ ] L3、逐 ID 回归、数据恢复、独立审阅完成后才可申请合并。
