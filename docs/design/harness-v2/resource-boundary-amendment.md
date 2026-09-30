# 资源业务与原生配置适配的所有权修订

2026-09-30，用户批准实施。本文覆盖本方案及 ModelProvider/Skills 等旧方案中“资源插件实现品牌适配”的旧裁定；不覆盖未改变的 Profile、数据、安全和结果语义。

## 不变的边界

- 资源插件拥有内容/版本/目录/存储/UI、Profile 配置项、业务校验与选择引用解析。不知道原生配置文件位置、不猜原生选项标识、不管理进程。
- Profile 保存配置蓝图与会话临时覆盖；会话内修改不回写全局。切换 Profile 清除临时覆盖；忙碌时不打断输出，下一次提交才应用。
- Harness 对外暴露统一配置能力；品牌支持、版本与当前实例能力判定、原生字段/选项映射、reload/restart/resume 及独立读回全部内部实现。
- 普通配置应用不依赖 Permissions 签发外部审批凭证；精确 target/generation/action 范围、提交互斥、幂等日志和结果确认照旧。工具权限资源的业务规则另按对应契约处理。
- Pacthold/Server/desktop host 不新增资源业务分支。Harness 不反向导入资源插件的存储、管理或 UI 实现。

## 组织与复用

使用已有 pi/codex/claude 品牌目录，每品牌有 configuration/ 能力模块与 registration.py 汇聚实际贡献。共享 configuration/model 保留纯模型编译词汇与 C2 转换；application/ 与贡献注册机制保持唯一。不为新资源增加另一套应用器，不把配置适配器实例当原生进程实例。

品牌提供者显式注册实现；每次构造获得新对象，实例运行身份/配置根/generation 来自已有运行设施，不保存在品牌全局变量。未实现能力不建空模块、不注册占位。不设计强迫所有品牌实现所有资源的万能 adapter。

本轮直接复用 22fcf53806 中 ordessa_model_provider_adapters 的三品牌实现、类型、golden tests 与 C2 转换，保留来源注释和原语义；这次搬迁不把 session-local SetField 变成真实原生 setter，也不声称模型切换已完成。

## 外部标识与迁移

- 保留 facet assets.model-provider、adapter assets.model-provider.pi/codex/claude 及贡献所有者 ordessa.model-provider.adapters 的既有标识。最后一项现在是 Harness 自有注册入口的历史稳定 ID，不再表示 Python 发行包归属，不修改操作账本。
- 唯一源码入口变为 ordessa_harness.<brand>.configuration.model；共享转换与注册入口为 ordessa_harness.configuration.model。旧 ordessa_model_provider_adapters 源包及 pyproject 删除，受控调用者同批迁移，禁止 shim/fallback。
- 旧本地 editable metadata/bytecode 不作为源码实现，不在本批删除其它环境内容；部署闭包不再选旧发行包。源码退役检查与新解释器查找分别验证。
- 本轮不自动增加默认产品启用项：迁移的是实现所有权与已有受控调用者，不借重构扩大支持声明。产品实际模型操作接线仍是固定 TODO 的后续项。

## 新资源接入流程

1. 资源域定义业务 schema 与内容引用，提供管理功能与可选 Profile/Settings 贡献。
2. 对所需品牌在 Harness 增加原生配置模块，经品牌 registration 注册到现有 C2 点；只实现并宣告有证据的能力。
3. 编译为现有 typed intent，统一合成与应用，原生动作/配置文件单写者，独立读回确认。不另建资源专属进程管理器。
4. 现有契约无法表达的新原生操作才演进 Harness API；先定义支持/拒绝/unknown、身份与生命周期边界，不用任意字典绕过。
5. 提供注册冲突、缺席、实例隔离、busy、未知结果和卸载反例。新资源是否独立使用或由 Profile 选择，不改变原生应用所有权。

## 本轮验收与后续

原 66 个适配一致性/参数测试保真迁移；ModelProvider 的真实 Harness 受控矩阵与引用解析回归不弱化；品牌工厂/依赖方向/旧源码退役补反例。模型目录业务与 UI 不迁移，未触及用户配置或真实模型。

尚待实际产品接线：Pi live model action、其它资源适配收归、canonical Profile wire、Chat next-submit、Codex/Claude provider 切换和恢复。这些不由本轮目录与注册迁移验收替代。
