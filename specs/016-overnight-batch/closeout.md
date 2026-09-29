# 016 夜批收口记录（2026-09-29 晨验收）

**状态：用户验收通过；十一包全部落位到各自 plugin 分支；三父十一子工作树与父亲目录已销毁。**
合并方式：儿子直推 plugin 分支（无 main 灌入）；specs 侧产物（报告/审阅轮次/阶段二
设计与侦察/api-requests 回填/qoder 裁定记录）联合入 main。

## 分支终态

| 包 | 分支 @ SHA | 测试 | 审阅 |
| --- | --- | --- | --- |
| PE1 permissions-authority | `codex/plugin-permissions` @ `e30865405c` | api 329/backend 194（继承红 7E/1F 另计） | 3 发现全修后复跑全绿 |
| PE2 harness-native-evidence | `codex/plugin-harness` @ `f81218c51f` | 445 passed/2 继承红 | 有保留（3 项转晨裁/core） |
| MPX 请求级参数 | `codex/plugin-model-provider` @ `00bd342358` | 见 MPX 报告 | 见报告 |
| EXT extensions 全域 | `codex/plugin-extensions` @ `698003036d` | 101 passed | 18 轮落实，末轮无 fake green |
| PX prompts 三品牌 | `codex/plugin-prompts` @ `c56104fcb2` | 见 PX 报告 | 6 轮 |
| CMP-skills / subagents | `ab402f4f7b` / `e321a966c2` | 见各报告（pytest 留痕在 main reports） | 3/2 轮 |
| LSP | `codex/plugin-lsp` @ `32be93d8a1` | 42 passed＋golden 钉 | 5 轮，有保留（C-LSP3 晨裁） |
| CMP-mcp | `codex/plugin-mcp` @ `f4fab0488f` | 526 passed/0 fail | 通过（闭环） |
| CMP-profile | `codex/plugin-profile` @ `c00b48a0f0` | 152＋vitest28＋反例12 | 闭环（tsc×3 根锁脱同步归 C0） |
| CMP-chat | `codex/plugin-chat` @ `fae10a8adc` | chat-api 23＋frontend 50 | 闭环（V09/I07 未测登记） |

## 重大事实（夜批实测发现）

1. **qoder 系统性不可用**：`-p`＋`--permission-mode default` 下写/执行被权限墙
   全拒（三父会话独立复现）＋账户额度耗尽＋白名单模型名不匹配（实名
   `Qwen3.8-Flash`）。六包转 zcode 代打，证据链 `reports/father-2/qoder-unavailable-record.md`
   ＋logs。**待裁：qoder 若再入夜批，需预配置非交互写放行与可用模型名。**
2. **AR-3/AR-6 双实证（跨两包独立结论）**：harness 的 slot 投影通路**无 target
   供给**——hooks_target 仅被 registry 解析零消费、instruction 连 registry 声明
   都没有。EXT/PX 均按「定义就绪、投影待通」诚实交付，compile 类型化拒绝。
   **待办归 harness 侧**（describe_targets 供给 + 钉版 schema）。
3. **qwen 除名落地**（PE2：8→7 段＋RETIRED_NPM_ROOTS 记账不删数据）；下游
   server 侧 11 文件同步红实测在案，**转 core**。
4. 015 状态：A 已提交完成（`1fd7cc07ad`）；B 仍在跑（基线态＋5 脏）。

## 晨裁清单（各报告汇拢）

C-LSP3（LSP-3 任务前提证伪处置）；PE2 ①qwen 测试退役 vs 生产模块留存②readback
独立性判据（core 边界）；PI 三项继承红；profile tsc×3 根锁脱同步（C0/INT-02）；
chat V09/I07；EXT/PX 投影待通排期。

## 阶段二产物（已入 main reports/father-{1,2,3}/）

四家（hermes/opencode/dsh/kilo）×13 域设计稿＋mcode/qoder/zcode-tui 三份侦察
（按 information-recon-priority 信任阶梯）＋8 轮阶段二审阅记录。

## 销毁

worktrees/overnight-{1,2,3}（含全部儿子工作树）已删；阶段分支无（儿子直推
plugin 支）。汇报口径出入一条：overnight-2 称全程零 git 写，但 skills/subagents
分支存在包产出提交，已核实内容与报告一致，记为口径出入非 fake green。
