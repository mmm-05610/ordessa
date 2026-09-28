# Verification, quickstart and readiness checklist

**以下是待执行测试规格，不是通过报告。** 每条均需正例和反例，失败输出必须证明测到目标缺陷而不是夹具错误；不机械要求修改无缺陷实现来制造红。

## 门禁目录

| ID | 正例 | 必须拒绝/发现的反例 |
| --- | --- | --- |
| G01 | API 独立 wheel 导入全部模块 | 装入假业务包/宿主依赖、导入异常吞掉、源码路径掩盖装包问题 |
| G02 | 两种贡献原子发布 | 重复品牌/别名/版本范围、重复字段 claims、伪 owner、未绑定点 |
| G03 | 卸载自己的贡献，后重装新 generation | busy 卸载、失败 staging 残留、双 disposal 异常覆盖主错误 |
| G04 | 外部受控 adapter 无改 Harness 注册成功 | 不注册也被硬编码接受、全局注册表旁路、运行副作用发生在 stage |
| G05 | 单真源 Python/JS 得到一致身份与 launch | 清单漂移、alias 被当第二品牌、未知版本误报 supported |
| G06 | 原有 start/connect/close 与 core resource 注册 | borrowed 被释放、unknown 被记 dead、重启复活终态 execution |
| G07 | 多 facet 写同文件不重叠字段 | 祖先/子字段冲突、set/reset冲突、数组争用、未知字段静默丢弃 |
| G08 | 私有 generation 完整发布 | 多文件半配置被运行进程读到、symlink/穿越/根替换、删除别人产物 |
| G09 | secret_ref 后端解析，日志/前端无秘密 | 环境/错误/plan/journal 泄漏；全局 HOME 内容被复制或修改 |
| G10 | 同幂等键相同请求恢复同操作 | 同键不同 payload、并发重复 apply、不同键绕过会话串行 |
| G11 | 失败明确补偿或 unknown | 外部已成功本地保存失败后重做、未知状态自动继续 prompt |
| G12 | 取消/崩溃/reconcile 后可确定恢复 | 旧 plan/旧 generation/旧授权/旧 secret 修订仍被接受 |
| G13 | 原 native session 恢复，generation 更新 | session/new 冒充 resume、恢复另一会话、晚到旧帧污染新实例 |
| G14 | 清理全部资源并报告未解决项 | disposal 抛错阻止其余清理、杀错 PID、释放失败丢账 |
| G15 | 三品牌模型/供应商选择确认 | 只 DB 改值算成功、调用 Claude global providers/set、A 切换影响 B |
| G16 | 三品牌 Skill enable/change/remove | 仅复制文件未被原生发现算成功、旧发现根仍加载被移除 Skill |
| G17 | item override 保留、未覆盖项跟全局 | Profile 切换失败清 override、卸载 provider 删除配置、跨 Harness 切换 |
| G18 | 下一次提交前应用，确认后一次发送 | 选择即应用、输出结束自动应用、配置未知自动重试、新选择改已冻结提交 |
| G19 | 同一协议 owner 完成受限控制与发送 | 第二 client 抢应答、伪 permit、秘密穿桌面、prompt 超时自动重发 |
| G20 | 旧库/快照 fixtures 升级和回滚 | 原标识改变、双写 store、旧模块仍可导入、坏内部 import 冒充删除 |
| G21 | 唯一生产链、单向公开依赖 | mock/stub 入生产、宿主 business import、try ImportError 兼容旁路 |
| G22 | 三品牌×两能力走真实 Server/adapter+受控下游 | 仅用内存 fake 服务自证、重复 frame ID 串会话、缺配置仍 offered |
| G23 | 干净 clone 与独立 wheels 可安装/运行 | 本地 editable 泄漏、漏依赖、收集错误被数量门吞掉 |
| G24 | 全量差分和默认产品无模型冒烟 | 相同失败数量但新增 ID、相同 ID 失败原因变了、旧功能消失 |

G22 层级必须标明：L1 纯编译/夹具；L2 固定原生 adapter+受控原生端点；L3 实际 Ordessa 通道与提交路径+受控端点；L4 真实外部模型（本批不授权、不要求）。L1/L2 不能充当 L3。Skills 的有效性需要固定原生加载器/发现结果，不能仅测 materializer 输出文件存在。

## 执行记录要求

T00 后把实际命令写入仓内 `implementation-baseline.md`：每个 Python 包安装方式、锁文件、node/go pin、测试目录和隔离环境路径。禁止照抄历史绝对 venv 路径或把别的工作树 editable 指向改掉。新增 API 包必须单独构建并在空 venv 安装验证。

已存在可复用的受控 Claude 命令（仅在实施 worktree 内独立安装依赖后）：

```bash
npm --prefix plugins/harness/packaging/claude ci
npm --prefix plugins/harness/packaging/claude run test:session-provider
npm --prefix plugins/harness/packaging/claude run test:provider-routing
```

这三条不是全包验收。目标基线四套件至少包括 `packages/pacthold`、`plugins/harness`、`apps/server`、`tests/acp_orchestration`，用 `python -m pytest`，逐套件全文日志+JUnit；各变更前端 workspace 单独 test，根 npm test 不能替代未聚合的插件测试。构建/类型检查/产品 smoke 命令以冻结后的 scripts 为准。

每轮记录 exit code、collected/passed/failed/errors/skipped、失败 ID 集合及同因判断；测试被移家保留 old→new ID 映射，缺少旧 ID 不能记作“红消失”。原始日志保存至 worktree 外受控 evidence 根，摘要/摘要哈希入库，禁止凭据。不能只打印 tail，也不能 grep 一个 GREEN 字符串判通过。

## 设计与开工清单

- [x] 职责/注册点/数据/应用时机/失败语义/迁移/验收已写明。
- [x] 上游最新能力与本仓实际 pin 明确区分。
- [x] 指定复用来源，禁止执行者泛搜后自由换架构。
- [ ] B1 平台公开组合接口与最终集成 SHA 已绑定。
- [ ] B2 唯一协议 owner、秘密留后端的具体 DTO/符号映射已冻结。
- [ ] B3 数据迁移范围已核查；需要用户数据变更时已获授权。
- [ ] B4 三品牌六格 pin/入口/恢复与隔离证据计划已核定。
- [ ] 当前方案经用户审定并授权实施。

## 完工清单

- [ ] T00–T18 全部有证据；G01–G24 所有必需正反例通过。
- [ ] 源码删除账/消费者迁移/打包边界全部闭环，没有成功空桩或同名第二实现。
- [ ] 生产提交入口已接通，不再写“等其他插件对接”同时声称本批完成。
- [ ] 集成后基线差分通过；旧品牌可用能力无未解释损失。
- [ ] 真实模型、平台差异、用户数据未测项如实登记。
- [ ] 审核通过后才申请合并；不自行 push、关其他工作树或停止服务。
