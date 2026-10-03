# 范围变更记录 — specs/011 checkpoint 更新（007 期间）

牵连路径：specs/011-plugin-rollout/checkpoints/harness-api.json（不在 007 write_paths）。
理由：002 冻结 + T007-01 切片向 plugins/harness/api 增量新增 participant.py（用户批准的合同
增量），触发 C0 时期 harness-api 行程树钉（test_c3_seam 比对 implementationSha 与 HEAD 的
api 子树）。重验证已执行：受约束的 C3 导出面测试 14 绿（publicExports 逐符号核对未变），仅
树增可加模块。处置：更新 checkpoint.implementationSha 至重验证时点提交，同步测试常量；
不删断言不放宽比较。后续 008–012 若再增 harness api 模块，同法重验证重钉（该钉是 tripwire
设计，不是冻结终态）。
