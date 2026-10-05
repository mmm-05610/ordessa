# Zen gateway 配置变更后的离线复验


本回执 HEAD 是复验前检查点，源码 SHA-256 才绑定本次未提交待提交的实现。全套 211 passed；构建最新 wheel 后 67 场景逐项通过；T60 离线入口永远不调用模型，真实 PARTIAL 另见 Jev 证据。固定基线与当前 57 个核心 ID 均 pass，完整 Server/Harness 继承红项未重跑。


首次直接跑完整套件为 210 passed/1 failed：T63 检测到旧 wheel 与新 provider 源码不一致。保留失败，使用离线入口正常重建 wheel 后完整 211 passed；没有删断言或 skip。


| 场景 | 状态 | 执行摘要 | 证据 |
| --- | --- | --- | --- |
| T01 | PASSED | 6 passed in 0.28s | [T01](T01.txt) |
| T02 | PASSED | 2 passed in 0.23s | [T02](T02.txt) |
| T03 | PASSED | 4 passed in 0.22s | [T03](T03.txt) |
| T04 | PASSED | 2 passed in 0.18s | [T04](T04.txt) |
| T05 | PASSED | 3 passed in 0.25s | [T05](T05.txt) |
| T06 | PASSED | 3 passed in 0.12s | [T06](T06.txt) |
| T07 | PASSED | 1 passed in 0.04s | [T07](T07.txt) |
| T08 | PASSED | 1 passed in 0.02s | [T08](T08.txt) |
| T09 | PASSED | 1 passed in 0.04s | [T09](T09.txt) |
| T10 | PASSED | 2 passed in 0.19s | [T10](T10.txt) |
| T11 | PASSED | 1 passed in 0.07s | [T11](T11.txt) |
| T12 | PASSED | 1 passed in 0.08s | [T12](T12.txt) |
| T13 | PASSED | 1 passed in 0.07s | [T13](T13.txt) |
| T14 | PASSED | 4 passed in 0.27s | [T14](T14.txt) |
| T15 | PASSED | 1 passed in 0.08s | [T15](T15.txt) |
| T16 | PASSED | 4 passed in 0.24s | [T16](T16.txt) |
| T17 | PASSED | 1 passed in 0.04s | [T17](T17.txt) |
| T18 | PASSED | 1 passed in 0.04s | [T18](T18.txt) |
| T19 | PASSED | 2 passed in 0.23s | [T19](T19.txt) |
| T20 | PASSED | 2 passed in 0.22s | [T20](T20.txt) |
| T21 | PASSED | 7 passed in 0.27s | [T21](T21.txt) |
| T22 | PASSED | 12 passed in 0.78s | [T22](T22.txt) |
| T23 | PASSED | 1 passed in 0.07s | [T23](T23.txt) |
| T24 | PASSED | 8 passed in 0.59s | [T24](T24.txt) |
| T25 | PASSED | 15 passed in 0.13s | [T25](T25.txt) |
| T26 | PASSED | 6 passed in 0.10s | [T26](T26.txt) |
| T27 | PASSED | 6 passed in 0.55s | [T27](T27.txt) |
| T28 | PASSED | 3 passed in 0.14s | [T28](T28.txt) |
| T29 | PASSED | 4 passed in 0.08s | [T29](T29.txt) |
| T30 | PASSED | 3 passed in 0.22s | [T30](T30.txt) |
| T31 | PASSED | 10 passed in 0.04s | [T31](T31.txt) |
| T32 | PASSED | 5 passed in 0.06s | [T32](T32.txt) |
| T33 | PASSED | 8 passed in 0.27s | [T33](T33.txt) |
| T34 | PASSED | 5 passed in 0.18s | [T34](T34.txt) |
| T35 | PASSED | 12 passed in 0.20s | [T35](T35.txt) |
| T36 | PASSED | 17 passed in 0.21s | [T36](T36.txt) |
| T37 | PASSED | 9 passed in 0.23s | [T37](T37.txt) |
| T38 | PASSED | 3 passed in 0.23s | [T38](T38.txt) |
| T39 | PASSED | 2 passed in 0.18s | [T39](T39.txt) |
| T40 | PASSED | 2 passed in 0.18s | [T40](T40.txt) |
| T41 | PASSED | 1 passed in 0.17s | [T41](T41.txt) |
| T42 | PASSED | 1 passed in 0.17s | [T42](T42.txt) |
| T43 | PASSED | 4 passed in 0.09s | [T43](T43.txt) |
| T44 | PASSED | 1 passed in 0.08s | [T44](T44.txt) |
| T45 | PASSED | 5 passed in 0.09s | [T45](T45.txt) |
| T46 | PASSED | 3 passed in 0.08s | [T46](T46.txt) |
| T47 | PASSED | 1 passed in 0.08s | [T47](T47.txt) |
| T48 | PASSED | 2 passed in 0.09s | [T48](T48.txt) |
| T49 | PASSED | 14 passed in 0.40s | [T49](T49.txt) |
| T50 | PASSED | 8 passed in 0.10s | [T50](T50.txt) |
| T51 | PASSED | 6 passed in 0.09s | [T51](T51.txt) |
| T52 | PASSED | 1 passed in 0.08s | [T52](T52.txt) |
| T53 | PASSED | 4 passed in 0.09s | [T53](T53.txt) |
| T54 | PASSED | 6 passed in 0.31s | [T54](T54.txt) |
| T55 | PASSED | 4 passed in 0.33s | [T55](T55.txt) |
| T56 | PASSED | 1 passed in 0.13s | [T56](T56.txt) |
| T57 | PASSED | 8 passed in 0.15s | [T57](T57.txt) |
| T58 | PASSED | 11 passed in 0.29s | [T58](T58.txt) |
| T59 | PASSED | 8 passed in 0.36s | [T59](T59.txt) |
| T60 | NOT_RUN | separate live authorization, credential and cost scope required | [真实单独回执](../jev-zen-20261005/README.md) |
| T61 | PASSED | 2 passed in 0.19s | [T61](T61.txt) |
| T62 | PASSED | 2 passed in 0.19s | [T62](T62.txt) |
| T63 | PASSED | 1 passed in 0.21s | [T63](T63.txt) |
| T64 | PASSED | 1 passed in 0.01s | [T64](T64.txt) |
| T65 | PASSED | 7 passed in 0.14s | [T65](T65.txt) |
| T66 | PASSED | 3 passed in 0.32s | [T66](T66.txt) |
| T67 | PASSED | 3 passed in 0.20s | [T67](T67.txt) |
| T68 | PASSED | 4 passed in 0.25s | [T68](T68.txt) |

[机器回执](receipt.json) · [完整套件](full-suite.txt) · [首次旧 wheel 失败](first-stale-wheel-suite.txt) · [固定基线](baseline-core.txt) · [当前核心](current-core.txt)。
限制沿用 implementation-20261005：Python 3.12 实测，协作式取消，本地 POSIX 崩溃窗，临时真实核心与 fake owner、实际效果 0。

导出首次旧 wheel 失败文本仅移除了行末空格；原运行日志仍在 .decision-tmp/zen-full-suite.txt。
