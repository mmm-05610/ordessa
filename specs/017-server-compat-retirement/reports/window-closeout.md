# 同窗关账（2026-09-29，W-1 批）

**状态：关窗。main = 全批合并态，四套+两域全数对账，无双写，零新增红。**
落点：`codex/window-preflight` 全树并 main（= core c20ce5853d + server-compat
9ba7a15455 + model-provider b14d1ecdfe + apps/server 收窗转换 8f83025d23）。

## 终验对账（合并树上实跑）

| 套件 | 结果 | 对照 |
| --- | --- | --- |
| 内核 | 212 / 0 | 基线同 |
| harness | 461 / 2 | 账本继承红同 |
| ACP 编排 | 41 / 18 | 账本继承红同 |
| server-compat | 9 / 9 | — |
| model-provider | 133 / 133 | 含 union 接账 5 条 |
| 服务端 | **1167P / 45F / 2E** | **优于 core 终树 71F/12E 达 26F/10E**；逐文件差集零新增红 |

## 本窗事件账

- 邪恶合并二连防：core 并入两次均验 plugins/profile 80 文件完好。
- venv 陈旧副本事故：server-compat 曾以非可编辑副本混入预飞 venv（含 W-1
  但缺 worker-entry 修复），`--no-deps --reinstall -e` 校准后消歧。
- worker-entry.mjs 孤儿终审：无生成器、无 git 史、官方注释判退役——pi 摘
  引用 5 文件 + server-compat 打包行摘除（9ba7a15455）+ e_inc1a 冻结壳钉
  7→6 跟随。
- 主会话直收 apps/server 转换（用户授权全仓负责）：_w1_seed.py 直调助手
  （九方法逐句对译）+ 摆桌子转换 8 文件 + 计数钉 3 处 + 面语义测试 skip
  接账 1 处。pi 侧无需再动；其 core 下次同步 main 即得全部。
- W-1 两处偏离（动作码表/注入读残留）依据见 W-1-report.md。

## 解锁

S-03 装配（model-provider + profile 三扩展）放行；INT-02 根锁重算条件齐；
017 W-2/W-3 与 020 按总纲推进。
