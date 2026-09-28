# 015 · integration-request（并合后组合验证，归集成会话）

单包不做跨插件组合；以下为两包与 model-provider/prompts 并合进 1+x 后的验收请求，
每项附执行者留下的证据指针。

- [ ] IR-1 端到端受控链（假端点）：会话轮次 → 捕获 → 抽取调用形状（假 OpenAI 兼容
      端点留痕）→ pgvector 存储 → 下次会话注入块出现。证据：P-B report.md MB-5/MB-8。
- [ ] IR-2 两 profile 记忆命名空间隔离 + 两会话四组参数互不影响（P-A RA-7、P-B MB-8
      用例在组合分支重跑）。
- [ ] IR-3 标注可见性：设置页/诊断/记忆查看/THIRD-PARTY-NOTICES 四处含
      "mem0（Apache-2.0）· 本地自托管"且遥测关闭声明一致。
- [ ] IR-4 facet 共存：model-provider、runtime-preferences、memory 三 facet 同时注册
      无冲突；P-A RA-6 的 C4 apply 样例在组合分支仍绿。
- [ ] IR-5 known-issues 复核：Docker 前置、bundled provider 限制、`POST /configure`
      实测结论、AR-3/AR-4 落实情况全部登记且与 report 一致。
