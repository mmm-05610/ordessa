# 串行逐场景验收回执

源码基线 `e4714eba00a78ba04c5b53318830a0d409e76bbe`；验证时 HEAD `9da63a6e5f1b53359bc5be3033146db8658a06e5`，decision 源码 `sha256:5af8d3c6a1b793ecb22ea5522b7af14d6505fe2b14f0693c771d242d1c6c2920`。

67 个离线场景逐项实际执行，T60 NOT_RUN。每行链接保存精确测试 ID、计数与退出码；同一测试覆盖多个场景时会分别执行，不能把计数相加当唯一测试数。最终完整套件 209 passed。

| 场景 | 状态 | 实际摘要 | 证据 |
| --- | --- | --- | --- |
| T01 | PASSED | 6 passed in 0.30s | [T01](T01.txt) |
| T02 | PASSED | 2 passed in 0.24s | [T02](T02.txt) |
| T03 | PASSED | 4 passed in 0.27s | [T03](T03.txt) |
| T04 | PASSED | 2 passed in 0.27s | [T04](T04.txt) |
| T05 | PASSED | 3 passed in 0.26s | [T05](T05.txt) |
| T06 | PASSED | 3 passed in 0.13s | [T06](T06.txt) |
| T07 | PASSED | 1 passed in 0.04s | [T07](T07.txt) |
| T08 | PASSED | 1 passed in 0.04s | [T08](T08.txt) |
| T09 | PASSED | 1 passed in 0.04s | [T09](T09.txt) |
| T10 | PASSED | 2 passed in 0.24s | [T10](T10.txt) |
| T11 | PASSED | 1 passed in 0.07s | [T11](T11.txt) |
| T12 | PASSED | 1 passed in 0.08s | [T12](T12.txt) |
| T13 | PASSED | 1 passed in 0.07s | [T13](T13.txt) |
| T14 | PASSED | 4 passed in 0.28s | [T14](T14.txt) |
| T15 | PASSED | 1 passed in 0.05s | [T15](T15.txt) |
| T16 | PASSED | 4 passed in 0.25s | [T16](T16.txt) |
| T17 | PASSED | 1 passed in 0.04s | [T17](T17.txt) |
| T18 | PASSED | 1 passed in 0.04s | [T18](T18.txt) |
| T19 | PASSED | 2 passed in 0.26s | [T19](T19.txt) |
| T20 | PASSED | 2 passed in 0.24s | [T20](T20.txt) |
| T21 | PASSED | 7 passed in 0.28s | [T21](T21.txt) |
| T22 | PASSED | 12 passed in 0.81s | [T22](T22.txt) |
| T23 | PASSED | 1 passed in 0.07s | [T23](T23.txt) |
| T24 | PASSED | 8 passed in 0.60s | [T24](T24.txt) |
| T25 | PASSED | 15 passed in 0.13s | [T25](T25.txt) |
| T26 | PASSED | 6 passed in 0.10s | [T26](T26.txt) |
| T27 | PASSED | 6 passed in 0.56s | [T27](T27.txt) |
| T28 | PASSED | 3 passed in 0.14s | [T28](T28.txt) |
| T29 | PASSED | 4 passed in 0.07s | [T29](T29.txt) |
| T30 | PASSED | 3 passed in 0.25s | [T30](T30.txt) |
| T31 | PASSED | 10 passed in 0.07s | [T31](T31.txt) |
| T32 | PASSED | 5 passed in 0.06s | [T32](T32.txt) |
| T33 | PASSED | 7 passed in 0.29s | [T33](T33.txt) |
| T34 | PASSED | 5 passed in 0.21s | [T34](T34.txt) |
| T35 | PASSED | 11 passed in 0.21s | [T35](T35.txt) |
| T36 | PASSED | 17 passed in 0.21s | [T36](T36.txt) |
| T37 | PASSED | 9 passed in 0.23s | [T37](T37.txt) |
| T38 | PASSED | 3 passed in 0.23s | [T38](T38.txt) |
| T39 | PASSED | 2 passed in 0.18s | [T39](T39.txt) |
| T40 | PASSED | 1 passed in 0.18s | [T40](T40.txt) |
| T41 | PASSED | 1 passed in 0.18s | [T41](T41.txt) |
| T42 | PASSED | 1 passed in 0.17s | [T42](T42.txt) |
| T43 | PASSED | 4 passed in 0.06s | [T43](T43.txt) |
| T44 | PASSED | 1 passed in 0.08s | [T44](T44.txt) |
| T45 | PASSED | 5 passed in 0.09s | [T45](T45.txt) |
| T46 | PASSED | 3 passed in 0.08s | [T46](T46.txt) |
| T47 | PASSED | 1 passed in 0.08s | [T47](T47.txt) |
| T48 | PASSED | 2 passed in 0.09s | [T48](T48.txt) |
| T49 | PASSED | 14 passed in 0.43s | [T49](T49.txt) |
| T50 | PASSED | 8 passed in 0.10s | [T50](T50.txt) |
| T51 | PASSED | 6 passed in 0.09s | [T51](T51.txt) |
| T52 | PASSED | 1 passed in 0.08s | [T52](T52.txt) |
| T53 | PASSED | 4 passed in 0.09s | [T53](T53.txt) |
| T54 | PASSED | 6 passed in 0.35s | [T54](T54.txt) |
| T55 | PASSED | 4 passed in 0.39s | [T55](T55.txt) |
| T56 | PASSED | 1 passed in 0.13s | [T56](T56.txt) |
| T57 | PASSED | 8 passed in 0.15s | [T57](T57.txt) |
| T58 | PASSED | 11 passed in 0.32s | [T58](T58.txt) |
| T59 | PASSED | 8 passed in 0.39s | [T59](T59.txt) |
| T60 | NOT_RUN | separate live authorization, credential and cost scope required | 未调用 |
| T61 | PASSED | 2 passed in 0.20s | [T61](T61.txt) |
| T62 | PASSED | 2 passed in 0.15s | [T62](T62.txt) |
| T63 | PASSED | 1 passed in 0.20s | [T63](T63.txt) |
| T64 | PASSED | 1 passed in 0.02s | [T64](T64.txt) |
| T65 | PASSED | 7 passed in 0.16s | [T65](T65.txt) |
| T66 | PASSED | 3 passed in 0.37s | [T66](T66.txt) |
| T67 | PASSED | 3 passed in 0.22s | [T67](T67.txt) |
| T68 | PASSED | 4 passed in 0.28s | [T68](T68.txt) |

[结构化回执](receipt.json) · [完整套件](final-suite.txt) · [固定基线](baseline-core.txt) · [当前核心](current-core.txt) · [预编译评测](evaluation-prepared.json)

固定基线/当前核心仅比对 40 个 direction/public surface ID，均 passed；完整 Server/Harness 注册红项未重跑、未清除，也未因这里通过而提升。

首次场景入口因包相对路径使用错误而无测试，退出 4；[失败原文](first-run-path-error.txt) 保留。修正后本表全部来自实际执行。复查初次 206 passed/1 failed 是重复 precondition 已前移到 DTO 构造拒绝、旧断言仍期待选择阶段拒绝；修正断言后 209 passed。

限制：fake HTTP 不证明中文判断质量；临时真实核心使用 fake owner，原生效果 0；真实 Pi/Codex/Claude 配置家族仍 opt-out/unsupported；Python 3.10 语义支持但仅 3.12.14 执行；取消是协作式；本地 POSIX 崩溃窗不证明断电或远程文件系统持久性。

凭据读取、真实模型/Harness 请求、服务重启、用户数据迁移、merge/push 均 0。忽略的 venv/cache 保留用于离线复验，未写其他工作树。
