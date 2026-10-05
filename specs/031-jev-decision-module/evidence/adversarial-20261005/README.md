# 继续实施：两轮下游边界攻击与修复

本批修复实际离线反例，不把受控 owner 或传输算作真实家族。所有测试／安装／模型调用由主会话串行执行；仅本工作树修改，无 Harness、服务重启、用户数据迁移或 push。

| 攻击面 | 保留的失败证据 | 修复与复验 |
| --- | --- | --- |
| 资料权限在 owner 回调中撤销，独立来源 provider 退役／换代／descriptor 改变 | adversarial-source-schema-red.txt | 原公共授权读取前后复查，不新增来源 registry |
| must 义务缺版本、错版本、虚构版本互相背书、bool/float 冒充 int | obligation-versions-red.txt、invented-source-red.txt、source-version-types-red.txt | 仅绑定输入来源／descriptor，类型严格一致，不要求每义务覆盖全部不相关资料 |
| task/source/hard-check 摘要错误，task reference revision 自相矛盾 | adversarial-source-schema-red.txt、second-review-red.txt | 已提供摘要／revision 必须一致；未知摘要来源拒绝 |
| 缺席 optional／空数组隐藏 unsupported schema、cycle／过深／超大整数 | adversarial-source-schema-red.txt、second-review-red.txt | 完整声明先审阅，再检查值；unverifiable，未放宽结构支持 |
| 错误 builder 或缺独立映射检查将 benign owner 输入绑定错误 draft | owner-mapping-red.txt | host 必须提供独立纯映射 verifier，义务精确映射；不同合法 wire 格式仍通过 |
| 策略外部别名消除 confirmation；业务吞掉错误问题／未知远端异常重发 | runtime-attacks-red.txt、second-review-red.txt | 策略冻结、技术失败 sticky；远端未知只有一次 dispatch，不恢复预算 |
| 重放 intent/response/finish ACK，正确形状 ACK 却无终态 | runtime-attacks-red.txt、terminal-shaped-ack-red.txt | 精确链摘要／序号绑定，成功也通过公开 reader 核验终态 |
| duplicate start 丢原 writer；锁路径替换冒充退出；旧日志无身份 | evidence-attacks-red.txt | 只清理本次拥有 fd；随机 incarnation 与 inode/device 绑定；旧非终态 unknown，不改写 |
| 跨 run/status/manifest 或无 result 的终态；close EIO 丢其他 fd | evidence-attacks-red.txt | 严格绑定；逐 fd 只 close 一次，EIO 后继续；durable terminal 不反向失败 |
| 已提交归档复制改变 inode 而丢失终态证明 | archive-copy-red.txt | 完整终态 commit 链证明已完成；非终态仍要求原 inode，替换锁攻击仍拒绝 |

初次 runtime 回归因测试 fake ACK／startup reader 不是规范 journal 而 11F/30P，修正 fixture 的真实记录及 terminal-query 阶段，保留所有断言，41P。第一次全套 1F/314P 是旧 wheel 与当前源不一致；正式入口重建并离线安装当前 wheel后通过。不删除历史失败，不用 skip 填绿。

最终证据见 offline/：320 项全套、67 个独立离线场景、固定基线和当前各 57 个核心 ID、独立 wheel 重建和无网安装全部通过。T60 在离线入口明确 NOT_RUN，真实证据另列。完整 Server/Harness 继承失败未重跑；Python3.10、真实断电、远程文件系统未验证。

live-injection/ 是用户已授权的同一免费 Jev 端点／jev-1.13-free 的有限复验，计划先冻结／零凭据预检。实际6请求、重试0、原生效果0，原图 task-gate 六维全部 pass，候选／组合／校验1/1/1，ready/reuse提案，精确持久终态通过。独立 reader 从复制归档复验 hash chain／terminal.commit／manifest／source／plan／FlowRef／计数，未调用模型或读 key。这里只重复单个合成注入样本，不能推广为全面抗注入，也没有真实 owner/Harness 应用。

本批报告6456输入／269输出 tokens，实际费用UNKNOWN。累计214真实请求，已报告170771输入／13958输出，历史3次usage未知；旧英文标签失败与66选项概率和协议错误保持开放。

可直接运行：

```bash
.venv-decision/bin/python packages/backend/decision/checks/offline_acceptance.py
```

纯读映射 verifier 是可信装配，仍需语义审阅；无自动验证任意字段映射的主张。现有原生家族依冻结合同保持 unsupported，JD009／JD010 仍 PARTIAL，全部工作完成标志保持 false。后续家族扩展方案见 ../../downstream-next.md，不能把真实 Jev 授权解释成 Harness／原生 apply 授权。
