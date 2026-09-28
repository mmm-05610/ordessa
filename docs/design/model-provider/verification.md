# Verification：可执行验收矩阵与证据等级

证据等级：D=设计/官方资料，E0=契约/静态检查，E1=内存假适配器，E2=固定真实 Harness/ACP adapter+受控 fake endpoint，E3=真实模型调用（本包未获授权）。**E1 不可汇报成 E2**。现有旧实施树报告 `PARTIAL`，数字来自其自身工作树，不是主树终验。

| FR | 任务 | 必须先红后绿的正/反门 | 最低完成证据 |
| --- | --- | --- | --- |
| MP-01 | T01,T04,T05 | 不同 Server/Provider 同名模型不串；建成会话改 harness 必拒 | E1+集成 |
| MP-02 | T01,T02 | 使用既有登录与 API 引用同一列表但权限不同；明文传 UI/日志即失败 | E1 |
| MP-03 | T01,T02 | 目录失败报 error、能力未知不可被默认为 supported | E1；三品牌 E2 |
| MP-04 | T01,T03 | 页面渲染零 outbound；保存/可达不能当 ready；手动 probe 有界且阻重定向/私网/超时 | E1 |
| MP-05 | T04,T05,T06 | 输出中点选不打断；P 更新一项而会话覆盖模型后另一项仍跟新 P；成功切 P 清覆盖；提交前 apply+verify 且 prompt 一次 | E2 |
| MP-06 | T02,T06 | A 改 provider B 仍原路由；全局 HOME 字节不变；原生 session ID 经 restart-resume 不变；`session/new` 代替 resume 必红 | 三品牌逐个 E2，缺者不报 ready |
| MP-07 | T05,T06 | 配置拒绝/回执丢失/版本漂移：草稿原样、零 prompt；未知必须 query/reconcile、不能重复发；失败清理无孤儿实例 | E2 |
| MP-08 | T01,T04,T07 | stale version/同 key 不同 payload 拒绝；引用存在或引用端口缺失不能归档；卸载后数据仍在 | E1+装配 |
| MP-09 | T03,T04,T05,T07 | 只装设置、只装 Chat+Harness、卸载 UI provider 三种组合分别可用/不破；Settings 误依赖 Chat 必红 | 桌面集成 |
| MP-10 | T01,T02,T07 | 凭据哨兵扫描 wire/日志/TurnFact/错误/导出零命中，缺引用拒绝；密钥只进受控单次应用 | E1+E2 |
| MP-11 | T02,T06 | C2 重叠 native 字段冲突、未注册 action/未经授权 target 拒绝；ACP 控制只有原 owner，第二 client 必红 | E2 |
| MP-12 | T00,T01,T07 | 六旧 wire 同形状同错误/ID/迁移，重复 owner 启动失败，旧测试红 ID 零新增未解释 | 主树/干净 clone |

验收命令由 T00 按集成 SHA 固定；至少复跑新插件 Python/TS suites、Server/Harness/ACP/desktop 既有账本、typecheck/build/Electron smoke、旧数据迁移回放、E2 三品牌控制样本。结果写退出码与失败 ID，不用通过数代替 ID；继承红保留原始日志。E2 包含 `initialize→session/new→prompt(fake)→换 Provider/Model→必要时 resume(同 native ID)→下一 prompt(fake)`，双会话交错并验证下游实际路由；只看配置文件/option ack 不足。Windows/真实模型、未知品牌单列未测。

最终宣布 `DONE` 的必要条件：三品牌 E2、T07 唯一 owner/数据迁移、T05 真提交闸门、E1/UI 全门、负例、回滚/unknown 都过。若上游接缝没落地，状态 `PARTIAL` 并列明哪个 FR 缺真实证据；不得以设计稿、fake 或历史轮证据补绿。
