# Tasks

任务均未执行。[P] 只表示冻结 API 后可独立推进，非已经派发。每项完成附 SHA、实际文件、测试命令和证据；对不可用能力保持真实未完成状态。

## Phase 0：事实和基线

- [ ] T00 固定平台/Profile/Harness/Chat 集成 SHA、对外 API、各品牌 native+adapter pin 和项目身份接缝。输出 implementation-baseline.md；不能消费相邻工作树的未提交文件。
- [ ] T01 冻结旧 Assets-Skill 数据表、发布 ID、目录摘要、Profile 固定版、旧 wire 行与各套件失败 ID/原因，清点非 Skill `server_assets` kind 的所有者。
- [ ] T02 对 Pi/Codex/Claude 固定版本补受控发现/加载/重载/禁用/显式调用矩阵；区分官网支持与当前 Ordessa 通路。

## Phase 1：内容和分配

- [ ] T03 从现有实现迁格式/树扫描、修订仓和受限预览，保留 digest/目录布局，删除本域重复实现（G01/G02）。
- [ ] T04 迁分块导入/版本审批/差异及来源，安装更新不动绑定（G03/G04）。
- [ ] T05 新增用户全局/项目通用与品牌特定分配表、CAS/幂等、确定性解释器，解析来源和诊断（G05/G06）。
- [ ] T06 Workspace 项目身份鉴权、内容归属授权与“另项目/Profile 专用不能引用”反例（G07）。
- [ ] T07 迁 Profile 旧固定版本绑定为三态 facet + 编辑器 DTO，接会话 item 覆盖，做用户数据 dry-run/回退证据（G08/G09）。

## Phase 2：装载与 UI

- [ ] T08 [P] 品牌 Skills adapters；名字冲突、原生发现、目标声明、reset/reload/resume、版本 fail closed（G10–G13）；依赖 T00/T02/T03。
- [ ] T09 [P] Settings 内容库及默认/项目分配视图，复用现有桌面列表/预览+平台控件；键盘/错误/权限（G14）；依赖 T05/T06。
- [ ] T10 Profile 编辑器三态、固定版更新、专用导入与双源状态说明；旧贡献卸载只摘 UI（G15）；依赖 T07/T09。
- [ ] T11 将旧 projection/ledger 分解到 Harness 应用与 Skills 只读事实；stored/selected/projected/loaded/used 分证据，不靠摘要冒称 loaded（G16）。
- [ ] T12 Chat `/`/`+` 贡献与可浏览/可显式调用区分；旧 generation 异步结果防串会话（G17）。缺公共贡献接口向 Chat 所有者提出具体接缝，禁私有 import。

## Phase 3：产品联调、删除和交付

- [ ] T13 下次用户提交冻结集合，Harness 先应用再发送；A/B 不串、失败不清 Profile 覆盖、终态 execution 不复活（G18）。
- [ ] T14 三品牌受控原生加载启用/更新/移除与同名/原生目录冲突，全真实 Ordessa 通路；不发付费模型请求（G19）。
- [ ] T15 更新产品装配/工作区包清单/锁；移除旧 Assets-Skill 服务与旧 Profile glue 重复入口，保留其他 asset kind 数据及兼容 wire 语义（G20）。
- [ ] T16 干净检出/隔离 wheel+前端构建、受影响套件逐 ID/原因 diff、UI smoke、最小数据恢复演示（G21/G22）。
- [ ] T17 完整报告逐模块复用/未测矩阵/删除账/证据摘要，独立审阅前状态 REVIEW_READY，不擅自合并/push。

## 需求—验证映射

| FR | T | G |
| --- | --- | --- |
| 01–03/07 | 03–04/06–07 | 01–04/07–09 |
| 04–06/08–09 | 05–07/13 | 05–09/18 |
| 10–13/16 | 08/11/14 | 10–13/16/19 |
| 14–15 | 09–12/15 | 14–17/20 |

如实备注：T16/G21–G22 的数量/退出码必须在 T01 固定当前集成基线后填写；本设计文档不预填旧环境的历史数字。
