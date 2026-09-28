# Q2 主代理审阅账（回工项与验收判定）

只记**已对照源码/契约核实**的条目，附文件与行号。每条在被修复前不得视为通过。

## command-templates — `expansion/`（FR-05、G05–G07 复核）

已核实为正确的行为（无需回工，留作验收依据）：
- 转义集合封闭：`parser.py:72` 仅认 `\{{` 与 `\}}`，其余反斜杠按字面文本；越界条件 `i + 2 < n` 对结尾串（`"\{{"`、`"a\}}"`）成立。
- 单次替换、不二次展开：`renderer.py:127-141` 逐 segment 拼接，值内的 `{{other}}`/`$`/`/`/换行不回扫。
- 越权路径拦截：`renderer.py:150-163` 绝对路径、`NUL`、`..` 分段在进 resolver **之前**拒绝；resolver 缺失时抛 `UnresolvedParameterError` 而非猜造（FR-08）。
- 输出上限在返回前检查：`renderer.py:143-145`。

回工项：

- **CT-R1（对 `data-model.md:23` 的覆盖缺口）** 语法要求「无未声明占位符、**无未使用必需参数**」。
  `expansion/renderer.py:check_coverage`（95–112）只做了：占位符必须已声明、required 参数必须被提供、
  参数不得多余传入。但**声明了却在本体中没有任何占位符引用的参数**不被拒绝：
  作者写 `parameters=[{name:"focus", required:true}]` 而正文不含 `{{focus}}` 时，
  当前实现反而强制调用方传一个永不生效的参数。
  期望：在发布修订/渲染前置校验中按原文明确拒绝（错误族 `PARAMETER_INVALID` 或 `INVALID_CONTENT` 之一，
  与 `api/errors.py` 既有族对齐），并补正反例（该参数被声明且正文无引用 → 拒绝；正文引用 → 通过）。
- **CT-R2（占位符名校验归属）** 已核实**不是缺口**：`api/schema.py:23` 定义 `_PARAM_NAME = ^[A-Za-z_][A-Za-z0-9_]{0,63}\Z`，
  `schema.py:56-59` 的 `validate_param_name` 在声明参数时强制；`parser.py:85-88` 记录原始 token，
  未声明名（含 `{{ focus }}` 这种带空格的）经 `check_coverage` 走 `UnknownParameterError`。
  仍需验收的是**反例覆盖**：空名、含空格、非 ASCII、超 64 字符各须有失败用例并给定位信息（对应 `dto.py` 的声明路径）。
- **CT-R3（字节级 golden 与 digest）** `renderer.py:146-147` 在函数内 import `rendered_digest`；
  功能可接受，但要求 golden corpus 明确覆盖 LF/CRLF、BOM、NFC 策略、引号与 Unicode，
  并断言「同输入同修订 → 同字节同 digest」是逐条固定向量而非一次随机对照。
- **CT-R4（文档/注释密度）** 该包 docstring 明显长于本仓惯例（单段说明即可）。
  合并前压缩到「一行意图 + 必要时一段非显然约束」，不保留任务叙事式注释。
  属风格项，不阻断功能验收。

## 环境/证据一致性回工项

- **X-R1（解释器版本）** command-templates 道在 `plugins/assets/command-templates/src/**/__pycache__/*.cpython-314.pyc`
  留下字节码，说明其测试跑在系统 `python3` = **3.14.4**，而非 `docs/baseline.md` 钉的 3.12.14。
  字节码与 egg-info 已被 `.gitignore`（`__pycache__/`、`*.egg-info/`）挡住，不会污染提交；
  但**验收复跑一律用本树 `.venv`（3.12.14）**，两域须各自给出在 3.12 下的完整计数与退出码，
  3.14 的结果只作开发过程记录，不作为门证据。
- **X-R2（基线唯一基准）** 自 `2c0c8bd209` 起，本线 `apps/server` 既有红基准为
  **43F / 25E / 10S（78 条逐 ID，含 skip）**，与 prompts 道独立采集集合**完全相等**。
  任何后续报告若引用 90F/158E 或未装 `products/server` 的数字，视为环境缺口误读，按 ID 重判。

## prompts — `backend/storage.py` + `backend/records.py`（G02/G03/G06/G07 复核）

核实为**符合要求**的设计（留作验收依据）：
- 修订不可变与「不硬删」下沉到**数据库触发器**（`storage.py:56-70` 三条 `BEFORE UPDATE/DELETE … RAISE(ABORT)`），
  不是仅靠服务层自律；新 schema 版本打开时类型化拒绝、不降级（`storage.py:126-132`）。
- 幂等回执与业务写入在**同一事务**（`records.py:320-336`：先查 `prompt_idempotency`，
  同 key 异 digest 抛 `IdempotencyConflictError`，同 digest 返回 `replay` 且不再执行业务），
  因此中断事务既不留半成品修订也不留回执。
- `update` 的 CAS 在事务内重读真实头版本比对，不符即 `RevisionConflictError` 并回传当前版本（无 last-wins）；
  正文与 latest 相同时**不新增修订**、仅元数据 bump（`records.py:207-229`），归档记录拒绝一切改写（`:191-193`）。
- `resolve_latest` 在**单个读事务**里逐条按 `revision=m.latest_revision` 解析（`:340-356`），满足「一次快照不混两时刻」。
- `clone` 复制当时字节并新建实体，不共享可变行（`:252-280`）。
- 检索用 `LIKE … ESCAPE '\'` 且对 `\ % _` 预转义（`:90-93`），分页 `LIMIT n+1` 探 `has_more`，参数顺序正确。

回工项：

- **PR-R1（不变量须被钉住）** `PromptsStore.read()`/`immediate()` 直接 `BEGIN`，而 `_write_lock` 非重入，
  因此**业务回调内部再调用任何走 `read()` 的仓储方法**会得到
  `sqlite3.OperationalError: cannot start a transaction within a transaction`。
  当前实现路径没有触发它，但这条不变量没有反例保护。要求补一条显式测试：在 `_write` 的 business 里调用
  `get_record` 必须失败且事务完整回滚（无修订/无回执），以此钉住「事务体内只允许 `steps()`」的约定。
- **PR-R2（响应形状歧义，小）** 仅改元数据的 `update` 响应里 `sha256` 为 `None`（`records.py:232`），
  而调用方无法区分「未触及正文」与「正文摘要丢失」。要求：无正文补丁时回传当前 latest 的既有摘要，
  或在 DTO 契约里显式声明可空语义并补断言。
- **PR-R3（`fault_after` 是测试接缝，须在文档面注明生产路径不注入）** 已在 docstring 说明；
  验收要求看到生产构造（`plugin.py` / 服务装配）不传该参数，且有测试断言默认 `None`。

## 待办（其他域/后续切片）

- prompts 域产出后同样按符号级核对，重点：单事务 latest 解析、CAS 幂等 key 复用异 payload 拒绝、
  归档不断引用、正文不入日志、scope 串读反例。
- 两域 venv 是否用了系统 `python3` 3.14.4 而非基线钉 3.12.14：验收时一律用本树 `.venv`（3.12.14）复跑。
- 两域基线数字须与 `qe2-evidence/q2-baseline/` 的逐 ID 红账按 ID+原因对齐，不同则说明环境差异来源。
