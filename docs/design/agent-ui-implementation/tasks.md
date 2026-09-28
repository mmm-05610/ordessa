# Tasks：Agent UI 默认实现

输入：本目录 spec/research/plan/data-model 与相邻 12 项契约。所有测试为必做。`[P]` 表示公共 API 冻结后文件不重叠，可由获授权的实施会话并行派发；不表示当前已派代理。

## Phase 1：Setup / reuse proof

- [ ] T001 在实施树记录 BASE_SHA/C7_SHA、干净状态、既有门禁；校验 C7 公开 API 与本批语义，创建 `plugins/agent-ui` 骨架，不动根分支。
- [ ] T002 获取固定 ZCode SHA，核对 research 所列符号；安装指定包前核对 peer/exports/license；写 `upstream-manifest.json` 和 notices/许可证。
- [ ] T003 在 `src/rendering/` 做 Streamdown 流式、中文、代码与样式隔离 proof；危险文本、远程图片、内建下载零越权；证明 build 离线可运行。
- [ ] T004 在 `tests/contracts/` 做 API 入口不加载默认实现/CSS 的反例与真实构建 singleton proof；禁止只跑 Vitest alias。

## Phase 2：Foundation

- [ ] T005 按 data-model 补齐 `api/*.ts` 的 12 项类型/key，统一旧草图，加入类型反例并记录契约差异审阅。
- [ ] T006 实现 `src/primitives/` 与局部主题映射：优先现有公开平台控件，否则原生/Radix薄封装；配置统一 labels；禁止新增全局 UI 框架。
- [ ] T007 建立 `dev/` gallery + 受控 business action recorder；全部经真实 registry/Outlet；无业务服务、无网络/真实模型。

## Phase 3：US1（FR-001/002/003/004/007）

- [ ] T008 [US1] `tests/behavior/conversation`：滚动不抢、显式历史、unknown、不支持块、会话 ID 切换；`composer`：IME、建议优先、双击、草稿保留；`tool`：六态及空/0/false。
- [ ] T009 [US1] `src/conversation/` 移植指定消息/思考/滚动逻辑；共享安全 Markdown；外部块经消费者 slot。
- [ ] T010 [US1] `src/conversation/composer` 移植 textarea 键盘处理，受控附件/建议/工具栏；删除上游 controller/upload。
- [ ] T011 [US1] `src/interaction/tool` 移植卡片结构，领域状态适配与显式完整结果动作。

## Phase 4：US2（FR-004/005/006）

- [ ] T012 [P] [US2] `tests/behavior/interaction`：所有非 pending 审批拒绝；原始选项 ID；多题受控答案；无默认提交；错误可见。
- [ ] T013 [US2] `src/interaction/approval` 移植布局+自有状态 wrapper；`question` 用基础控件实现受控表单，不抄历史 renderer 当交互组件。

## Phase 5：US3（FR-002/004/005/007）

- [ ] T014 [P] [US3] `tests/behavior/configuration`：来源×生效状态、不可用选中项、过滤不清值、卸载配置区零删除、显式重试、只读。
- [ ] T015 [US3] `src/configuration/` 实现 Selector/Section/State；同一接口用模型/Profile/Skill 三套 fixture，不导入它们业务类型。

## Phase 6：US4（FR-005/008/009）

- [ ] T016 [P] [US4] `tests/behavior/review`：远程资源不请求、HTML危险协议、rename-only/多文件/超长/损坏 diff、明确截断与完整查看。
- [ ] T017 [US4] `src/review/` 移植附件布局与轻量 diff闭包；复用 rendering，不带入 Pierre/文件系统/patch应用。
- [ ] T018 [P] [US4] `tests/behavior/work`：未知/失败/取消、用量缺失与 0、展开不改变执行状态、操作仅来自 props。
- [ ] T019 [US4] `src/work/` 移植 Task/Plan 展示，自写 RunSummary 薄组合，不定义工单格式与策略。

## Phase 7：Integration / Polish（FR-006/007/010）

- [ ] T020 `src/entry.ts` 12 项原子注册、作用域清理；`tests/integration/` 实证独立替换、缺席、重激活、旧回调拒绝、相邻块存活；零业务取消/释放。
- [ ] T021 在 `tests/browser/` 执行 quickstart 几何/键盘/滚动/网络矩阵，留截图与断言日志；provider/consumer实际构建加载，无源码 alias。
- [ ] T022 产品装配只登记必要扩展/选择/shared API；包内 API 导入边界、全量新增测试、typecheck/build/相关既有回归；不改 Chat 消费。
- [ ] T023 analyze：逐项对照 spec FR/SC→task→测试→原始日志，审查来源/许可证/依赖和 API 无运行时泄漏；更新完成报告。

## Dependencies / checkpoints

T001–004 → T005–007 → US1–4 → T020–023。各 US 在独立 gallery 中可验收，但本批完成要求四个故事全部完成。共享 rendering/primitives 由一个所有者维护，其他实现不得复制它们。每阶段提交只是检查点，绿且无新契约争议则继续下一阶段；不能以“等用户看一下”代替剩余已授权任务。

没有固定“必须 82 个测试”之类数字；必须证明场景和反例，收集失败算失败。未跑 browser、缺 key、缺许可证、C7未接线，任一项均不得报全部完成。
