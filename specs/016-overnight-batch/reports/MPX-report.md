# 016 · MPX model-provider-params 报告

**结果:四类请求级参数键的投影面落地——两格真投影(codex 推理强度、pi 预算)、pi retry 声明+受目标签发闸门、其余格诚实拒绝带钉源理由;零新包/零新 facet;`runtime-preferences` 目录零触碰。执行方式:qoder 失败、zcode 代打**(§2)。

## 1. 任务对照(spec.md §MPX 行 + tasks.md MPX-5;不删行)

| 任务 | 态 | 证据 |
| --- | --- | --- |
| 推理强度键投影 | ✅(codex 格) | `adapters/.../codex.py`:`model_reasoning_effort`(钉源 `ordessa_harness/codex/remote.py` `_EFFORTS`+请求拼写),词表 {low,medium,high,xhigh,max},deepseek 族子集 {low,high,max};pi/claude 格=诚实拒绝(§2 矩阵) |
| 预算键投影 | ✅(pi 格) | `pi.py`:maxTokens 黄金对象重写(钉源 `deploy/pi/models.json` 模型条目 + `production.py gate_models_document`),从 `before` 现样重写保兄弟条目;codex/claude 格=拒绝(MAX_PROMPT_BYTES 是校验界非配置键/无 first-hand) |
| 超时键投影 | ✅(诚实拒绝格) | 三品牌均无 facet 内授权超时键:唯一 first-hand `timeoutMs` 在 harness 部署描述符(`{pi,codex,claude}/production.py`),越面;拒绝理由+AR-6 登记转 harness 域 |
| 请求级 retry 投影 | ✅(pi 声明+闸门格) | pi:settings.json retry 块 first-hand(`deploy/pi/settings.json`),descriptor 增 `pi.settings.json`("retry",) 声明;宿主未签发该 target 时 bridge 以 `CAPABILITY_UNSUPPORTED` 拒绝(`UnauthorizedTargetError` 路径),绝不写形似句柄;codex/claude 格=拒绝 |
| MPX-5 z3 账本 5 项甄别 | ✅ | §5 甄别表(R0/R1/R2 勾,R3/R4 卡点) |

## 2. qoder 调用记录(次数/退出码/失败处置)

| # | 时刻 | 结果 | 处置 |
| --- | --- | --- | --- |
| 1 | 09-29 02:04 `run-qoder.sh …/son-mpx-model-provider …/MPX-model-provider-params.md`(5400s) | 02:22 退出码 **0 但自宣告 BLOCKED**:无人值守下一切变更动作(Write/Edit/venv/pytest)被会话权限模式自动拒绝,零产出落盘(日志 `logs/son-mpx-model-provider-qoder-20260929-020444.log`;qoder 自述 "every mutating action is being auto-denied") | 与 PE1 同一确定性强失败(同命令必现),按父文档失败路径**「qoder 失败、zcode 代打」**;qoder 会话内已完成的设计不落盘即失,以 dispatch+仓内钉源重建 |

## 3. 三态逐格表(四族 × 三品牌;格值=投影行为,全部带 first-hand 指针)

| 族 | pi | codex | claude-code |
| --- | --- | --- | --- |
| 推理强度 | **拒绝**:first-hand 在授权面外(PiConfig.thinking/`--thinking` 属 launch 描述符;models.json `samplingParams.thinking` 钉样仅 {"type":"disabled"},无档位词表) | **投影** `model_reasoning_effort`(remote.py 词表;deepseek 子集;顶层 TOML 写→restart-resume 升级) | **拒绝**:settings.json 钉面仅 ANTHROPIC_BASE_URL |
| 预算 | **投影** maxTokens(黄金对象重写,`before` 无现样/条目不在→拒绝) | **拒绝**(MAX_PROMPT_BYTES=校验界) | **拒绝**(无 first-hand) |
| 超时 | **拒绝**(timeoutMs 属 harness 部署描述符,越面→AR-6) | 同 pi | 同 pi |
| retry | **投影(带闸门)** settings.json retry 块;未签发 target→类型化拒绝 | **拒绝**(树内无 first-hand retry 键;官方文档=线索非钉源) | **拒绝**(同左) |

缺省语义:`requestParams` 缺省或全 None ⇒ 与 MPX 前逐字节同行为(回归钉 `test_absent_params_keep_the_pre_mpx_compile_behavior`)。

## 4. 测试证据(真跑,命令+计数)

```
cd plugins/assets/model-provider/adapters
  PYTHONPATH=<adapters|harness-api|harness|pacthold|server|server-plugin-api 的 src>
  python -m pytest tests -q
  → 本包改动前基线 48 passed → 现在 63 passed(新增 tests/test_request_params.py 15 项;
    首轮红 5 项全部为测试自身期望/假体错误,逐项修复,零删断言)
cd plugins/assets/model-provider/server(未触碰,回归)
  → 128 passed
```

**未在本环境复跑(既有环境缺口,非本包造成,如实登记)**:profile-contribution
pytest(工作树与 venv 均无 `ordessa_profile`,import 即错)、chat-contribution/desktop
vitest 与 contracts tsc(无 node_modules/JS 工具链)。四者本包零触碰;z3 基线数字
(13/21/10/tsc exit 0)在 `specs/011-z3-model-provider/report.md` §1 在案。

## 5. MPX-5 · z3 账本 5 项甄别(016 三档口径;R0–R4)

| 项 | 档 | 处置/证据 |
| --- | --- | --- |
| R0 冻结输入 | 已实现已验→勾 | z3 report §1:R0 提交 `1660f66920`,t00-freeze.md §1–9(树/接缝/wire/钉版全冻结) |
| R1 接口请求+checkpoint SHA | 已实现已验→勾 | api-requests.md CONSUMED 记录;消费 chat-api `54ad26c15d`、foundation `8844c475bc`(ancestor 核实+合并后复跑,z3 report §1/§3) |
| R2 原包任务实现/验收/归属、假接口为零 | 已实现已验→勾 | 五包落地 137+10+21 绿、探测全走假传输/loopback(§3"完成"节);T06/T07 生产缝有 owner 有请求(REQ-Z3-1/2),归属明确即满足"依赖归属" |
| R3 检查点/清单/账/报告齐+**全链门通过** | 已实现未验(后半)→不勾 | 前半齐(report/integration-request IR-1..6/api-requests);"全链门"差 E2 受控真桥与生产闸门——卡点:上游 C0 检查点(REQ-Z3-1 C2 注册点、REQ-Z3-2 plan/apply+submit permit),016 不代做 |
| R4 analyze/converge 查漏+clean ready 发布 | 未做(部分)→不勾 | 查漏部分=本甄别表即补;"ready 发布"按 016「只提交不并回」归明早用户验收——卡点:验收流程 |

## 6. 复用了什么 / 自建了什么(红线 7)

复用(机制零重造):既有 facet `assets.model-provider` 与 `model-provider.choice.v1`
载荷(仅加可选 `requestParams` 闭形对象)、既有三品牌 assess/compile/verify 骨架与
黄金对象写入路径、`ValueSchema`/`FieldClaim`/`SetField`/`ErrorCode` 契约、
conformance 门(自动覆盖新键)、harness 侧 first-hand 钉源(deploy 模板/remote.py/
production.py——只读引用不改动)。

自建:`RequestParams` 冻结 DTO(四族、闭形、严格 from_record)、codex effort 投影
与 deepseek 子集、pi maxTokens 黄金重写与 retry 目标路由、`UnauthorizedTargetError`
未签发目标闸门、payload schema 的 requestParams 段、两组 descriptor 声明增量、
15 项测试。自建占比超三成理由:qoder 失败代打为父文档指定路径;参数投影面此前
不存在,无可复用实现。

## 7. 划界与红线对照

- **F12/015 划界**:本包只收请求级四族键;会话/运行级偏好(压缩、记忆、shell 等)
  一概未收,`runtime-preferences`(015-A)目录零触碰;seam 注记:请求级归
  model-provider(本包),会话级归 015-A,互不双收。
- **写入面**:全部改动在 `plugins/assets/model-provider/adapters/**` 与本 reports
  目录(git status 核对);禁真实模型/外网,测试全走受控假端点/纯函数。
- **qwen**:本包无 qwen 行(z3 线本就三品牌 pi/codex/claude)。

## 8. 卡点清单

1. timeout 族与 pi retry 的宿主侧:timeoutMs 归 harness 部署描述符(转 harness 域
   裁定是否开facet 授权面);pi settings target 需宿主签发 `pi.settings.json` 才生效
   (api-requests AR-6 已列)。
2. reasoning effort 的 pi/claude 格与 codex/claude 的 budget/retry 格:待有 first-hand
   钉源(升级 L3 文档线索需钉 commit)再投影,拒绝理由已带升级路径。
3. 本环境四套件未复跑(§4);z3 的 REQ-Z3-1/2 生产缝归 C0。

## 9. 审阅记录

- **封装审阅(`run-review.sh`)**:exit 126(分支相对 main 的 diff 超出 argv 单参数上限,`/usr/bin/timeout: 参数列表过长`)——脚本自身无法运行的环境约束,按父文档降级条款改裸调。
- **裸调审阅(pi + mimo-v2.6-pro,模型白名单遵守;留痕 `主仓 reports/son-mpx-model-provider-review-fallback-*.md`)**:以工作树 diff+新文件全文(40KB)直喂,指令与封装逐字一致。**结论:有保留**,三条发现:
  1. pi maxTokens 黄金重写会静默吞掉同批端点/协议变更,且整树写回被指越界 → **已修**:重写对象叠加 choice 自身 baseUrl/api(钉源方言),样例字段保留是为保住 models 数组(facet 本就声明整个 providers 子树,黄金整写是既有通路);补回归测试 `test_an_endpoint_change_is_never_dropped_by_the_budget_rewrite`。
  2. 非法 requestParams 抛裸 ValueError + schema/from_record 键口径不一 → **已修**:bridge 两处(assess→unknown、compile→`INVALID_FRAGMENT`)类型化作答;schema retry 增 required,与 DTO 恰三键口径一致;补两测试钉口径。
  3. pi.settings.json 声明"扩大写入面靠兜底" → **设计裁定保留**:retry 族唯一 first-hand 目标就是该文件;声明(inert until issued)+未签发即类型化拒绝是本包最诚实的通路,完全对齐"扩既有声明面"授权;理由与闸门测试在案(`test_an_unissued_param_target_*`)。
  - 附带修复:回归测试 docstring "byte-for-byte" 降为如实表述(行为等价断言);codex 死 `assert` 移除;审阅者提示的 specs 目录 cat 报错系喂入脚本对目录的无害报错,任务↔代码一致性以本报告 §1/§3 对照表为准。
  - 修复后复跑:adapters **66 passed**(基线 48+本包 18)、server **128 passed**(回归)。
