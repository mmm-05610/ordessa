# Verification and readiness

以下是必须执行的测试规格，不是当前运行结果。每条含正反例；源文件存在、投影目录摘要、原生发现/装载、实际 Skill 调用是不同层次。

| ID | 正例 | 反例 |
| --- | --- | --- |
| G01 | 旧 Skill ID/修订/摘要逐字节一致 | 格式模块迁移后前置内容/附件误改、非 Skill 行被修改 |
| G02 | 不可变树安全预览，script manifest 可见 | symlink/穿越、过量包、导入即执行脚本、preview 读任意文件 |
| G03 | 分块导入预览后批准一次 | 内容漂移、断块、重复 commit、超时残留永久不清 |
| G04 | 发布新版但现有绑定/会话仍在旧版 | 自动移动 latest、远端 tag 改动影响运行、旧版提早 GC |
| G05 | 六层分配确定性解析并显示来源 | 同层重复、项目禁用影响其他项目、品牌通用范围被错判 |
| G06 | 后层三态正确覆盖并固定 revision | inherit 被当 disable、启用未批准版、管理员强制规则被覆盖 |
| G07 | 授权项目/专用 Skill 可选 | 客户端伪 projectId、A 专用内容给 B、未授权跨 Server 引用 |
| G08 | 老 Profile 绑定迁 enable(revision)，结果相同 | 固定版变追最新、已禁用项变启用、迁移重跑双写 |
| G09 | Profile 会话覆盖下一次提交生效 | 输出中即时装载、失败清覆盖、Profile 专用内容被公开 |
| G10 | Pi/Codex/Claude 固定版本装载机制有据 | 官网新版能力误用于当前 pin、品牌不支持却 offered |
| G11 | 受管目标与原生发现信息分列 | 用户/项目原生目录被修改，原生项被误报“已禁用” |
| G12 | 装配前拒绝本库及原生项重名 | 依目录顺序随机生效、Unicode/大小写规则与原生不符 |
| G13 | 同会话更新确认或重启恢复 | 另一会话被改、resume 变 session/new、拒绝后仍发 prompt |
| G14 | Settings 空/错/加载/归档/导入/范围视图 | 请求失败清草稿、CAS 被覆盖、窄屏不可操作或焦点丢失 |
| G15 | Profile 三态、版本 diff、专用内容选择 | 选择即修改内容实体、取消删除已导入资产、旧贡献残留 UI |
| G16 | projected 只记投放，loaded 经独立观察 | 调 digest-verify 即记 loaded、模型口头声称 used 即记 used |
| G17 | 菜单仅提供当前 generation 可调用项 | 自动型伪造按钮、斜杠系统命令被覆盖、旧响应串到新会话 |
| G18 | 提交时冻结集合，先应用再发送一次 | 输出结束自动应用、超时重发 prompt、配置 unknown 冒充成功 |
| G19 | 三品牌启用/更新/移除受控全链 | 只有 unit fake/文件拷贝被当 native load；跨 session 串配置 |
| G20 | 产品只有唯一 Skills 服务，其他 kind 数据仍可访问 | 旧/新双注册、shim 兜底、旧历史 wire ID 被误删 |
| G21 | 空环境装包及桌面构建/electron smoke | editable 指向另一树、lock 手工改、只跑根 npm test 漏插件 |
| G22 | 受影响套件逐 ID 同因，数据备份恢复一致 | 只对数量/尾行判绿、收集错误假绿、断言删除/skip 藏回归 |

品牌矩阵字段：native version、adapter version、发现根、项目/用户额外发现、隔离方法、reload/reset/resume、显式调用方式、loaded 证据、正反测试 ID。无独立证据的格子填 unknown，不能从其它品牌猜。

证据级别：L1 内容库+纯适配测试；L2 固定原生加载器/受控子进程；L3 实际 Ordessa Server→Harness→ACP 会话路径与受控对端；L4 真实外部模型（本批未授权）。G19 要求 L3，不以 L1/L2 替代；`used` 无独立事件就保持 unknown，不要求花钱问模型。

## 执行和报告

T00/T01 把真实安装、测试、构建脚本与工具链版本写入 implementation-baseline.md。Python 套件用各自隔离安装/`python -m pytest`，桌面每个插件自身 workspace 单测加类型检查、产品 build/electron smoke。日志与 JUnit 全文保存在工作树外证据根；报告每个命令、exit code、collected/passed/failed/error/skipped、逐 ID/原因差分和环境 pin。不能用单一 `GREEN` 字符串判成功。

## 方案审核与交付清单

- [x] 用户已讨论内容/范围/Profile/Harness 的边界，本包给出分配解析、固定版本与来源证据设计。
- [x] 复用清单逐模块指定具体文件与测试；只新增范围解析及品牌差异。
- [x] 原生项目/个人 Skills 的额外发现和不能屏蔽情形明确列出。
- [ ] 最终平台/业务包 SHA、旧 wire/DB 迁移表和固定版本三品牌矩阵已冻结。
- [ ] 用户审核本包新增具体默认规则，授权实施。
- [ ] T00–T17、G01–G22 必需门闭环，三品牌 L3 与旧品牌回归证据到位。
- [ ] 独立审核无新债；数据迁移与产品回滚可演示，然后按授权合并。
