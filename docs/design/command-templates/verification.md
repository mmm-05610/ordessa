# Verification、反例与完成门

此表是**未来必须执行**的验收规格，不是当前绿灯。证据 L1=纯单元/类型，L2=固定原生加载器/受控进程，L3=真实 Ordessa Server→Harness→ACP→受控对端，L4=真实付费模型（本包未获授权）。三品牌必达 Chat 路径要求 L3；native 投影只有 offered 时须 L2+L3。

| Gate | 正例 | 反例 |
| --- | --- | --- |
| G00 | 冻结 API 和 SHA/红账本，可编译真实贡献 | 仅设计 `addInputSource` 被误当发布 API、相邻 worktree 未提交代码被消费 |
| G01 | 空环境仅装模板域可 CRUD | 借加载 Profile/Chat 才能初始化；旧 asset kind 被动到 |
| G02 | 同 ID 版本不可变，摘要/正文吻合 | 超长/无效 UTF-8/损坏摘要仍发布，修订原地改写 |
| G03 | 内容发布与全局/项目/Profile 启用互不影响 | 发布即自动启用、更新自动移动 pinned revision |
| G04 | CAS/幂等一次提交 | 双写覆盖、同 key 异 payload 复用成功、归档删历史 |
| G05 | 参数类型与展开字节 golden 吻合 | 未声明/缺失参数、enum 越界、整数溢出、输出超限 |
| G06 | 字面 `{{`/`}}` 可表达，替换一次 | 参数里又含 `{{other}}` 被二次展开、`$()`/`!`命令被执行 |
| G07 | Unicode/换行/引号按预览字节发送 | Markdown 渲染重编码正文、输入注入角色标记后获得系统权限 |
| G08 | `/` 与 `+` 同源目录，显来源 | 同名内建/Skill/extension 被遮蔽，菜单按加载顺序选赢家 |
| G09 | 明确参数预览→只插当前草稿 | 点击选择即发送、丢选区外文本、取消创建通道 |
| G10 | 三品牌受控对端见用户消息原文，含正文首字为 `/` 的字面文本 | 插入显示文本与真实 ACP payload 不同、发送时把模板正文二次解析成命令、私自再开客户端 |
| G11 | 旧目标/光标/代次结果拒插且不清草稿 | 会话/服务/项目切换后晚到展开写进新草稿；提供者卸载后仍动作 |
| G12 | 授权全局/项目/品牌/Profile 的三态解释可见 | 客户端伪 projectId、A 的专用模板给 B、禁用被当 inherit |
| G13 | Profile 固定修订；切换仅按其规范下轮生效 | 改全局 Profile 反写当前草稿；输出中直接改模型/会话配置 |
| G14 | Profile/Chat 缺席时内容库可用，UI 贡献卸载仅隐藏 | 卸载配置项删正文，缺 facet 仍应用旧数据 |
| G15 | 固定 Pi/Codex/Claude 版本与语义矩阵 | 官网新版能力误用于当前 pin，unknown 当 supported |
| G16 | 原生额外发现/同名检测与单 owner | Claude command+Skill 双载入、Pi extension 命令抢占未报告 |
| G17 | offered native 投影有独立 load/resume/撤销证据 | 仅文件存在就标 loaded、Codex deprecated 路径被当稳定能力 |
| G18 | 下一次输入前应用，单一 owner，必要时同 session 恢复 | 输出中 reload、resume 变 session/new、失败仍自动发 prompt |
| G19 | Settings/参数 UI 键盘、IME、焦点/错误态可用 | Enter 组合输入误插/发送、缺后端显示空库、窄窗遮按钮 |
| G20 | 业务依赖方向与唯一服务注册 | Server/Pacthold/Workbench 出现模板分支，旧新服务双注册 |
| G21 | 明确导入只读且不可无损项拒绝 | 扫 HOME 自动导入/执行 dynamic include、写回原生源文件 |
| G22 | 干净安装/build/electron 和 suite 全文日志 | 只看尾行/数量假绿、lock 手改、仅根 npm test 漏插件套件 |
| G23 | 逐失败 ID/同因对照与数据恢复成功 | 收集错误计绿、skip/xfail 掩红、恢复后摘要不一致 |

## 执行证据

T00 写 implementation-baseline.md：主树/各业务包 SHA、Node/Python/native pin、真实命令、基线 IDs，不能复制往期数字。Python 用隔离 editable/wheel 安装与 `python -m pytest`；前端各 workspace 自测、typecheck、产品 build、Electron smoke；JUnit 与全文日志存工作树外证据目录，并附每命令 exit code、collected/passed/failed/errors/skipped、红 ID 与原因 diff。严禁通过删断言/skip/只计数漂绿。

受控 L3 用 fake 模型/ACP 对端验证 Pi/Codex/Claude 途径的纯用户文本、相同 digest、零额外通道；不发送真实模型请求。真实付费测试需要用户另行授权范围/成本。可选 native adapter 没有证据就让能力矩阵 unsupported/unknown，不能靠 L1 mock 记 loaded。

## 方案审核/交付清单

- [x] 本包有需求、复用表、数据/接缝、品牌能力门、FR→T→G 和正反例。
- [x] 当前 Chat 输入契约只属设计，且 Claude 命令与 Skills 重合、Codex custom prompts 已废弃，均明确处理。
- [ ] 用户复核 README 的三个默认值并授权实施。
- [ ] T00 已冻结真实集成 SHA/API 和 brand pin，缺失公开接缝已交所有者。
- [ ] T01–T15/G00–G23 全部必需项有日志/反例/独立审阅；可选 native 项逐格诚实标注。
- [ ] 数据恢复与回滚演示，许可/复制清单审计；批准后才合并/push。
