# Tasks：按依赖执行的可派发单元

| 任务 | 唯一文件域/责任人 | 完成物与停点 | FR |
| --- | --- | --- | --- |
| T00 现状冻结 | lead，只改本方案/集成账本 | 实际 main、两旧树 SHA/dirty、C1/C2/Profile/Chat 导出、wire 形状/DB 标识、Pi/Codex/Claude 版本与许可清单；旧 R1→新 restart-resume 差异表。缺任一真实接缝必须注明 `BLOCKED_INTEGRATION`，不造 stub 假充。 | 全部 |
| T01 记录/探测迁移 | `plugins/assets/model-provider/server/**` | 先红后绿同输入行为对照、CAS/KEEP/null、SSRF、安全手动探测、secretRef；不得改 Compat 与主机文件。 | 02–04,08,10,12 |
| T02 品牌适配 | `plugins/assets/model-provider/adapters/**` | C2 Pi/Codex/Claude assess/compile/verify 各自可追溯版本/字段/入口；unknown/unsupported/冲突反例；不读写 HOME。 | 01,03,06,11 |
| T03 设置 UI | `plugins/assets/model-provider/desktop/**` | 无 Chat/Profile 装配的管理页、手动 probe、keyboard/narrow viewport、缺席对照。 | 03,04,09,10 |
| T04 Profile glue | `plugins/assets/model-provider/profile-contribution/**` | 原子 facet、引用保护、字段覆盖、切 Profile 清覆盖；无 Profile 的 core 仍可用。 | 01,05,08,09 |
| T05 Chat glue/submit 消费 | `plugins/assets/model-provider/chat-contribution/**` | Provider/Model 两级、零 Harness 切换、pending-next-turn、草稿零丢失、晚到结果拒绝；**依赖真实 submit permit**。 | 01,04–07,09 |
| T06 ACP/Harness 集成 | 各核心所有者的独立任务/集成树，非本域代理擅改 | 同 controller control/readback、C1 专用 target、resume ID、provider/model 事实；每品牌 E2 受控真进程，A/B 会话隔离。 | 05–07,11 |
| T07 旧 owner 退役/产品装配 | 集成主控独占 Compat/产品清单 | 六方法无双 owner、legacy 数据保真、迁移/回滚、默认模型对照；主工作树经审批才合并。 | 08,09,12 |
| T08 终验与报告 | lead | FR→门禁实测矩阵、逐失败 ID 差分、证据 E0/E1/E2/E3 明标、未测范围；全部必须达标准才报完成。 | 全部 |

依赖：T00 → T01/T02/T03（互不写同文件，可并行）→ T04/T05（公共契约已冻结）→ T06/T07 串行集成 → T08。任何子代理单包所有权，不能写其它包/宿主/产品清单。跨包问题先形成精确接口请求，不自行设计第二个替代 API。检查点不是完成声明；阻断仅限有关能力，能继续独立测试/文档/对照时继续推进。严禁真实模型调用，除非另获 scope+cost 授权。
