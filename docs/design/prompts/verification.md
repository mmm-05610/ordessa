# Verification and readiness

本页全部是待执行规格，不是通过报告。核心原则：内容正确保存、原生产物正确生成、实际原生入口采用，是三层不同证据。

## 门禁

| ID | 正例 | 必需反例 |
| --- | --- | --- |
| G01 | 纯 API 独立导入 | import 即注册/读 DB；跨域实现依赖；缺依赖被测试环境掩盖 |
| G02 | 保存新修订、同正文不增修订 | 两客户端 CAS 竞争、事务中断 latest 指向不存在修订 |
| G03 | clone/archive/restore 与旧引用可用 | 归档断引用、copy 跟原对象后续变、重试重复创建、自动硬删 |
| G04 | 用户上传单个 UTF-8 文本再导出 | 非法编码/NUL/空白/过量、目录/绝对路径读取、危险文件名 |
| G05 | 正文在授权编辑器显示 | 日志/错误正文泄漏、HTML/XSS、外链自动请求、任意宿主路径导出 |
| G06 | library/profile scope 正确 | A Profile 专用内容被 B 解析、切 Server 同 ID 串读、客户端伪身份 |
| G07 | 单事务解析多内容 latest，固定 snapshot | 一次快照混入两时刻修订、apply 再追 latest、旧权限仍放行 |
| G08 | 仅 Prompts 业务服务可管理公共库 | 缺 Harness/Profile 导致 CRUD 崩溃、缺授权却创建专用内容 |
| G09 | 三种用途按能力正确映射 | replace 偷换 append/persona、普通 user message 冒充系统配置 |
| G10 | 原生入口不展开外部依赖 | @file/URL/include 造成额外读取、正文触发脚本、未知语法默许 |
| G11 | 按顺序合成一次+完整 reset | 每轮重复 append、删一项误删他人、空文本假装恢复默认 |
| G12 | 项目文件字节不变，优先级可诊断 | 更改 AGENTS/CLAUDE、项目覆盖导致实际没生效仍 confirmed、超限截断 |
| G13 | Profile 三 item 独立覆盖 | 列表元素隐式 merge、Profile 切换失败清覆盖、引用 schema 不校验 |
| G14 | provider 卸载隐藏 UI 保留数据 | apply 忽略缺 provider、旧代次 callback 串写、卸载删除内容 |
| G15 | 页面空/加载/错误/保存/归档状态 | 错误清草稿、公共内容保存影响被隐藏、保存冲突 last-wins |
| G16 | 安全文本/Markdown 预览和键盘 | 图片自动泄漏、raw HTML 执行、编辑器抢全局快捷键、焦点丢失 |
| G17 | 内联明确两步保存，多选键盘排序 | 取消未保存内容仍落库、已保存内容被取消 Profile 偷删、无持久 ID 建专用 |
| G18 | 下次提交先配置确认再发一次 | 输出时打断、idle 自动应用、unknown 自动重试、提交中换正文 |
| G19 | 三品牌真实 Ordessa链+固定加载器/受控下游 | 仅文件存在/DB 变更冒充生效、A 改 B 变、恢复空会话代替旧会话 |
| G20 | 真产品构建，宽窄布局和 overlays | 孤立组件绿但真实加载失败、手改 lock、无键盘排序/关闭路径 |
| G21 | 空环境安装包、干净 clone 完整测试 | editable 指向相邻树、收集失败被忽略、只跑根 npm test 漏插件 |
| G22 | 边界扫描与逐 ID/失败原因差分 | 恒真断言/吞异常、同数量不同红、宿主新增 Prompts 分支 |

G19 三品牌 instruction 为必需；已宣称 supported 的 persona/systemReplacement 也必须跑同级证据。关闭能力必须有版本/入口/原因，不可为了规避失败临时隐藏。真实模型、Windows/远程未测须标注，不计通过。

## Quickstart（实施者填写实际命令）

1. 在批准的实现 worktree 确认 HEAD 与 T00 的集成基线一致；根树保持 main。
2. 按各包 pyproject/npm workspace 在独立环境安装，绝不修改其他树 editable 绑定。记录 interpreter/native/adapter/toolchain 版本。
3. 先跑新增 contracts、content、adapter tests，再跑 Profile/Harness/ACP 受影响测试和前端自身 workspace test。
4. 跑产品 typecheck/build/smoke，使用临时数据根及 fake endpoint；原生受控测试不得接真实账户。
5. 保存每套件命令、退出码、计数、全文/JUnit，独立列 collection errors；根 npm test 不替代插件测试。

本包尚未创建 workspace/package scripts，因此不伪造现在可执行的命令。T00/T03 完成时必须在 implementation-baseline.md 给出精确测试/构建脚本和路径；之后无人值守按该文件执行，不临场猜命令。

## Design checklist

- [x] 用户确认范围与职责已转为需求、数据和注册契约。
- [x] 最新官方机制与当前运行 pin 区分；品牌缺口有明确验收。
- [x] 指定逐模块复用与合法退路，不允许自由搬上游产品。
- [x] 明确正文隐私、隐式展开、scope、并发、归档和覆盖边界。
- [x] 不增 Chat 常驻 UI、不写项目指令、不改核心。
- [ ] 最终平台/Profile/Harness SHA 与实际公开 API 已冻结。
- [ ] 用户审核本包新增具体规则并授权实施。

## Completion checklist

- [ ] T00–T15 完成并有证据；G01–G22 必需门通过。
- [ ] 三品牌 instruction 产品链完成；其他能力逐格 honest supported/unsupported/unknown。
- [ ] Profile 两步保存、正文最新修订和 item 覆盖行为与文案一致。
- [ ] 干净构建/隔离安装/受影响套件通过，基线红逐 ID 同因无未解释新增。
- [ ] 源码/包/清单边界无 stub/shim/第二应用器，原始证据无秘密。
- [ ] 报告列未测项、来源与许可证、数据升级/回退；等待独立审阅再合并。
