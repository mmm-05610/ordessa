# Implementation tasks

全部未执行。每项勾选需附目标 SHA、文件、命令/退出码、原始证据与残余范围。`[P]` 表示冻结接口后可独立并行，不表示已授权创建会话。执行者不能把 blocker 改成“通过”。

## Phase 0 — 冻结实施输入

- [ ] T00：绑定平台集成 SHA；核验公开 carrier/资源 API、custom point 组合入口、busy/unregister、ACP 唯一 owner；完成 blockers B1/B2 的实际符号对照。产物 implementation-baseline.md，禁止使用活跃树未提交文件。
- [ ] T01：展开 migration.md 为逐文件+active caller+数据路径账；冻结四套件与相关前端 workspace 的数量、逐 ID、失败原因/收集错误基线，原始日志/junit 独立保存。
- [ ] T02：固定 Pi/Codex/Claude 原生与 adapter pin，完成六格能力/作用域/reset/resume 实证方案；登记其他品牌原功能基线。发现官方能力不等于当前 adapter 能力时列具体缺口，不猜。

## Phase 1 — API 与注册（US1/US4）

- [ ] T03：实现独立 ordessa-harness-api，C1–C4 DTO/schema/errors、能力和 intent 判别联合、类型反例；独立 wheel 安装无宿主/业务 import（G01）。
- [ ] T04：接既有 carrier 注册两个领域点，重复/版本/范围/claims 拒绝，事务发布、卸载 busy 与回滚（G02/G03）。所有者不可伪造。
- [ ] T05：受控第三方 runtime/config adapter 从包外注册，完成一项配置和卸载（G04）；不靠修改产品内 if/else 演示。

## Phase 2 — Runtime 与 materialization（US3/US5）

- [ ] T06：收敛现有品牌运行模块、统一 launch descriptor，保留 alias 与旧运行链行为；更新 Pacthold/Server 公共接线，不改核心（G05/G06）。
- [ ] T07：实现 target handle/claims、codec、set/reset/content/secret intent 合并；目录安全、版本快照、跨文件安全发布、秘密边界（G07/G08/G09）。
- [ ] T08：实现 operation journal、plan fence、幂等、apply/verify/reconcile；故障注入覆盖外部成功/本地落盘失败与取消（G10/G11/G12）。
- [ ] T09：重启/resume、instance generation、资源回收和 execution 关联；终态不可复活，不按消息创建 execution（G13/G14）。

## Phase 3 — 两个真实消费者（US1/US2）

- [ ] T10 [P]：迁 Model-provider 的三品牌映射，保留业务存储/校验；移除 Harness 中对应转换，原测试保真迁移，供应商/模型读回证据（G15）。依赖 T03/T04/T07。
- [ ] T11 [P]：迁 Skills 的三品牌格式/发现/启停/reset，接现有内容仓，删除旧直接写入链（G16）。依赖同 T10。
- [ ] T12：Profile glue 产出已解析 fragments/显式 reset，Confirmed 才绑定/清覆盖；不支持/缺席拒绝、UI 隐藏但数据保留（G17）。
- [ ] T13：真实 ACP 提交闸门与后端受限控制接缝，同一 owner；补 next-submit、输出中不打断、重启恢复再发原消息、秘密不出后端（G18/G19）。依赖 T08–T12；不能以 fake HarnessConfigPort 算完成。

## Phase 4 — 删除、生产验收与交付

- [ ] T14：迁旧 profile 运行快照/用户预存与其消费者；完成数据兼容审计，按 B3 决定是否需要生产迁移授权（G20）。
- [ ] T15：改产品装配/锁/发布包路径；所有旧入口、重复注册、stub、业务反向依赖移除；禁 alias 兜底（G21）。
- [ ] T16：三品牌六格完整受控链、双会话、重启恢复、卸载、协议关联；原有品牌启动回归（G22）。
- [ ] T17：干净 clone/wheel 隔离安装、完整套件逐 ID+原因差分、前端 build/smoke、无模型 Server 冒烟（G23/G24）；基线红不同因也视为待判定。
- [ ] T18：填写 verification.md 完成清单和 source→destination 删除账、未测项、数据回滚、复用许可证；仅报 IMPLEMENTATION_REVIEW_READY，等审阅再合并。

## 可执行粒度

先 API/运行主体，再冻结出两业务的适配合同；两业务可并行，但不要多任务共写 Harness registry 或产品装配。每次跨包变更必须属于本表已有接缝。小型实现错误自行诊断修复并复跑，不因测试红就请求新架构；真正需改契约/改核心/触碰用户数据则按阻塞表处理。

## 需求追踪

| 需求 | 实施 | 验收 |
| --- | --- | --- |
| FR01–04 | T03–T06 | G01–G06 |
| FR05–06 | T12–T13 | G17–G19 |
| FR07–09 | T07–T09 | G07/G10–G14 |
| FR10–11 | T07/T10/T11 | G07–G09/G15/G16 |
| FR12–14 | T09–T13/T16 | G13/G15–G19/G22 |
| FR15–17 | T04/T08/T09/T13 | G03/G11–G14/G19 |
| FR18–20 | T14–T18 | G20–G24 |
