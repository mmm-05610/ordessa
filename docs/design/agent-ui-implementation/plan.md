# Implementation Plan

## Technical Context / Constitution Check

React/TypeScript/npm workspaces；使用 C7 的 UI API/React Outlet 与既有 extension 生命周期。遵守 010 constitution 的领域独立、契约先行、空宿主有效、守卫反例、根 main 不切分支等约束。当前只写文档，无代码实施。

## Project Structure

```text
plugins/agent-ui/
├── package.json / manifest / build.mjs   # 沿集成基线真实扩展格式
├── api/
│   ├── index.ts / keys.ts
│   ├── conversation.ts
│   ├── interaction.ts
│   ├── configuration.ts
│   ├── review.ts
│   └── work.ts
├── src/
│   ├── entry.ts                        # 一次原子注册默认 12 项
│   ├── conversation/                   # message、reasoning、composer、scroll
│   ├── interaction/                    # tool、approval、question
│   ├── configuration/                  # selector、section、state
│   ├── review/                         # resource、diff
│   ├── work/                           # progress、summary
│   ├── rendering/                      # 安全 Markdown、code、diff 文本
│   ├── primitives/                     # 私有薄封装；不对外冒充新平台
│   └── styles/                         # scoped CSS、theme mapping
├── tests/
│   ├── contracts/                      # 类型正反例、API 独立加载
│   ├── behavior/                       # 五个家族的行为
│   ├── integration/                    # 真实平台、provider/consumer、替换卸载
│   └── browser/                        # 几何、IME、滚动、焦点、网络断言
├── dev/                                # 受控 gallery；不进入生产菜单
├── licenses/ / THIRD-PARTY-NOTICES.md
└── upstream-manifest.json
```

同一插件的内部模块可互用私有 primitive；独立公共接口之间用消费方渲染插槽组合，不能绕过产品选择绑定具体实现。API 与默认实现是构建隔离边界，不要求 12 个 npm 包。

## 写入范围

- 主要：`plugins/agent-ui/**`。
- 配套：根 npm workspace/lock 与 typecheck 接线，仅在当前配置确有需要时做最小登记。
- 受控集成：优先在本插件 tests/dev 使用实际平台；真实构建 shared API 映射如在产品装配所有，则只改该装配配置，不改宿主行为。
- 默认产品启用：仅在最后一阶段登记提供者和选择表；本批不替换现有业务消费者，未消费 key 不造 required 依赖。
- 禁止：`apps/server`、`packages/pacthold`、前端 host/runtime/Workbench 行为、其他业务插件、真实用户配置/数据。没有必要因为本批去改后端。

## 实施顺序

### A. 先验证取材与接线，不先写大组件

记录 BASE_SHA/C7_SHA；读取 C7 实际 API；取得固定 ZCode 源码并生成 provenance。完成 Streamdown + 样式隔离、key 共享、API 无实现加载的最小 proof。研究版本依赖不是兼容性证明，proof 失败应修适配，不能开写第二套 Markdown/registry。

### B. 冻结 12 项公共类型

把四项草图与完整总览统一，补齐 typecheck 反例：错误 props 对 key、上游 SDK 对象、失效/缺失动作、错误答案种类。公共 API 审核后内部实现可并行；主代理统一编辑 keys/index/package/lock/entry，避免多个子代理抢文件。

### C. 五个内部家族落默认实现

按 research 的逐项配方实施。每个模块先行为反例，再移植或薄适配；源码旁记录保留/删除清单，不把上游不适用的业务判断照抄。独立 fixture 覆盖所有接口，不能只实现 Chat 用到的四项就报全部完成。

### D. 注册、替换与实际构建

用 C7 scope 批量注册 `ordessa.agent-ui.default`。消费测试用独立真实构建扩展，不只用源码 alias；仅替换 ToolActivity 证明其他接口保持；卸载 provider 后旧动作失效、文字保留；重新激活不让旧 generation 恢复。禁止让缺席 UI 调用 release/stop/delete 等业务操作。

### E. 浏览器与集成回归

gallery 要通过真实 UI 服务/Outlet 渲染，不能仅 `import DefaultComponent` 展示。完成 quickstart 的浏览器验收，运行相关现有测试和产品构建；留证报告。只到待审，不自动合并/push/删除其他树。接入 Chat/Profile 是后续业务批次，不混入“组件库完成”的定义。

## 无人值守的决策边界

实施者可以自主解决 import、CSS、类型局部细节、测试夹具；可以修复移植中发现的 falsy 输出、焦点、IME bug并加反例。不得自行更换来源、增加富文本框架、引入业务存储/服务、放宽 C7 状态语义。

外部依赖暂不可取：继续其余独立模块、记录精确包/版本/错误；不得网络无限重试。上游源码某符号不符固定 SHA：核对文件 hash并暂停该模块，禁止改追 main。C7 缺口：提交复现与所需契约差异，继续不受影响工作，不补私有服务 locator。用户不在线不等于授权新增宿主接口。

不得把“有阻塞”变成整晚空等，也不得把 fallback 当全部完成。终态报告必须列完成 task ID、阻塞 ID、剩余验收门。功能性 fallback 只允许本设计已列出的纯文本/不可操作占位，不允许静默降低功能。

## 复用完成判据

每个 S 项提供源文件→目标文件→保留符号/逻辑→适配测试映射；每个 L 项提供 lock/integrity/实际调用点；每个 O 项说明为何必须由 Ordessa 负责。数量、复制行数不作为复用质量指标；不允许拿上游截图然后重新造滚动或 Markdown 引擎。
