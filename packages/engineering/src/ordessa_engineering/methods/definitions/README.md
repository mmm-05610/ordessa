# Method definitions — implementation candidate

用户已大致审过此前 models；本轮按明确授权调整解析职责与 schemas/errors 目录。修改后的数据组合与实现仍为候选，待用户代码审阅；技术通过不替代用户验收。独立来源、逐文件 SHA256、删除清单与验证边界见 `docs/verification/methods-parser-boundary-20261009.json`。前轮记录保留历史事实。

| 目录/文件 | 实际职责 |
| --- | --- |
| `models/identity.py` | 身份与精确 ResourceRef/BlobRef。 |
| `models/sources.py` | ResourceBytes、CapturedResource、SourceBundle；ParsedContent、ParsedResource、ParsedSourceBundle、SourceResourceView。只做结构、不可变转换、捕获绑定等自身不变量与摘要/长度派生；不解析文本。 |
| `models/loaded.py` | LoadedMethod(source, source_bundle, parsed_source, verification)。便利属性只转取已构建结果，缓存不是信任凭证。 |
| `models/verification.py` | 可选 lock/golden 各为 ParsedContent，包含捕获 bytes 与不可变派生结果，不分设竞争 bytes/Mapping 参数。 |
| `defaults.py` | 模型与外部格式共用默认值的唯一 owner；compiled 与 schemas 引用同一对象。 |
| `models/compiled.py` | 现代完整类型化、深度不可变 CompiledProgram，外部canonical/encoding与派生视图统一由 compilation/encoding.py 处理，模型无反向导入。CompiledMethod 同时携带唯一源捕获及其绑定视图。历史 StoredProgram/HistoricalBoundProgram 责任独立。 |
| `models/snapshot.py` | StoredSourceBundle 只保存 blob 引用；StoredSnapshot 是纯 codec 结果，MethodSnapshot 是 store 显式验证后的方法快照。无 parser 对象或回调。 |
| `schemas/v1.py` | V1 manifest/resource/workflow/standard/question-set 的格式数据声明及纯构造片段；不执行校验，不加载外部 schema。 |
| `errors/diagnostics.py` | MethodError、Diagnostic 数据。 |
| `errors/failures.py`、`results.py` | MethodFailure 数据携带异常；MethodResult 与成功/失败互斥自身不变量，无日志、重试、HTTP 或外部处理。 |
| 各 `__init__.py` | 指向唯一实际 owner 的聚合导出；无上层转发或 parser/validator 注册。 |

## 源内容与派生视图

SourceBundle 只保存 manifest ResourceBytes、tuple[CapturedResource] 与 LoadLimits；ResourceBytes 只保存 logical_path/media_type/data，digest 与 byte_length 派生，没有 value/_parsed 或隐式解析。ParsedContent(captured, value_tree) 做纯递归冻结：mapping 与数组成为只读对象和元组，只允许字符串键及支持的 JSON 值，公开 value 是防御性副本。它的构造不证明 bytes 与内容一致，也不自动解析无效 bytes。

ParsedSourceBundle(source_bundle, manifest_content, resources) 检查每个解析结果引用的捕获内容及资源集合；LoadedMethod/CompiledMethod 检查所组合的原始源与视图绑定同一 SourceBundle。identity、manifest、resource declaration/value 从已生成视图派生，bytes/digest 从捕获源派生。LoadedMethod 只有 source、source_bundle、parsed_source、verification 四个构造字段，不能另外传 manifest/resources/identity/digest。

loading/loader 使用唯一严格 parser 从各份 bytes 一次构建视图。受信边界继续显式重建：application 公共 compile 的 verify_loaded_method 从原 bytes 解析并比较整份视图；freeze 同样比较 compiled.parsed_source，并验证类型化程序与源的对应。伪造缓存即使捕获引用、摘要或身份标记看似合法，也被拒绝。store 不接收持久化 parser/cache，读取真实 blobs、重建源视图、核验当前或显式历史程序后 materialize。阶段间重验并非第二个 parser 实现。

解析 bytes/depth 限额继续由原 LoadLimits 与阶段预算实施；不能把任意用户构造的 ParsedContent 当作已经受限或可信。没有增加新的格式版本、授权凭证、schema 默认注入或业务语言。

## 依赖与入口切换

唯一严格 JSON/YAML parser 与 YAML duplicate-key、anchor/alias、merge、深度预检查归 `loading/parsing.py`。原格式验证函数归 `validation/structure.py`，JSON-compatible/depth 纯检查归 `validation/values.py`。这两个基础验证模块只依赖 definitions/纯标准库/jsonschema，不导 loading；loading 导它们，避免 loading↔validation 循环。外部 document schema、graph、引用与宿主兼容检查仍归原 validation 模块。compiler 不在 definitions 中执行。

definitions 无 loading/validation/compilation/domain/application/adapters/plugin 依赖，也无 yaml/jsonschema 执行器或文本 decode_json。schemas → defaults；models.compiled → defaults/sources/identity/capabilities/errors，模型不反向导 schemas。旧 schemas.py/errors.py 已删除，同名包保持公共导入位置；parse_document/validate_* 不在 definitions 留 shim。旧 ResourceBytes parser 缓存已退役。

## 保留与验证边界

现代 CompiledProgram 仍以明确类型化语义字段为内容权威；purpose、已知 workflow 可选字段、缺省/显式默认与精确引用保持。开放 FrozenObject 仅用于契约允许的 config/check bindings/JSON Schema 内容。canonical/domain digest、snapshot wire、golden、历史 program1 缺失现代字段拒绝规则、事务发布和授权边界保持。旧解析/格式函数移动保留代码与错误顺序；测试只切换真实 owner 和新阶段数据组合，不删旧拒绝断言。

施工树受控 methods、snapshot codec/store、method content 回归覆盖本模块；完整 Engineering/发行/产品及审阅树运行未验证。审阅树仅同步独立允许清单，公共根入口、其余 validation/common/infrastructure、source pins/config/锁等未据此视为闭合。审阅树既有 methods 根 README 与施工树不同，保留其用户内容，不整棵覆盖。

本轮 U04 新 owner：`contracts/sources.py` 是 ResourceReader 唯一 owner；`contracts/validation.py` 是 ValidationPhase/ValidationReport 唯一 owner；`models/identity.py` 的 method_digest 是摘要纯派生 helper。序列化方法不留模型包装、getter 或延迟 import。此施工阶段等待主协调者整合和复验，本文不新增测试成功声明。
