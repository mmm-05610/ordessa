# T04-B：`agents.harness` 能力接入（2026-10-21）

## 改动

`agents` 能力组现在同时包含 **Harness catalog 投影**：`build_agent_group(profile_part, harness_part)`。
catalog 是已组装并 pin 的，因此"声明它准入什么"是观察事实，不是承诺；未准入/未安装品牌以数据形式报告。
操作 id 为 `agents.harness.list` / `agents.harness.describe`，归属同一 `agents` capability。

## 实测（安装版 Server + 零配置 CLI）

```
ordessa … agents harness list --json
  → completed，六个品牌：kilo, pi, claude, codex, hermes, dsh
    每个带 definitionRef{environmentNamespace: server, definitionId, revision: 0.1.0}
    与 implementationDigest sha256:…
ordessa … agents harness describe --definition-ref ref.json --json
  → completed（ref = {"environmentNamespace":"server","definitionId":"kilo","revision":"0.1.0"}）
```

先前一次 `describe kilo` 的 INVALID_INPUT 是我传参错误：describe 需要 `--definition-ref <json-file>`，
不是位置参数；已用正确参数验证通过。

## 回归

CLI + packages_convergence 3 文件：98 passed / 0 skip。

## 仍未做

instances/native 仍未接入（缺 endpoint/preparation/lifecycle/interaction 端口）；长操作、工具权限未做。
