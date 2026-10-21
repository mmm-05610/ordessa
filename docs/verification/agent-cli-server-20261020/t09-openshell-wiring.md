# T09：Server 接入 OpenShell provider（本机，2026-10-21）

## 改动

`apps/server/src/ordessa_server/composition/environment_owner.py`：

- OpenShell 改为**显式 opt-in**：只有存在 `<data-root>/state/openshell.json` 时才装配；
  文件里是什么就按插件自己的 `read_configuration` + `build_binding` 解释，Server 不复制网关语义。
- 装配失败/插件未安装 → catalog 里是**带原因的 UNAVAILABLE 条目**，绝不静默回退 Local。
- `ServerEnvironmentOwner.close()` 现在先关闭 OpenShell 的网关客户端，再关 store（顺序固定）。

## 前置（已核）

- 本机内核 `7.0.0-38-generic` 有 Landlock（远端 5.10 缺失 → 按用户决定只做本机）；
- `.venv-w1` 装上 `openshell==0.1.3` 后插件可导入；lab 记录本机 gateway/podman rootless 可用。

## 验证

- `python_workspace.py --install` exit 0；
- `apps/cli/tests` + `test_server_full_stack.py` = **93 passed / 0 skip**（未配置 openshell 时行为不变）。

## 未验证（下一步）

真实本机沙箱闭环（create openshell → exec → files → delete + 成果取回）尚未跑：
需要一份 `state/openshell.json`（字段：`endpoint`/`workspace`/`fileRoot`/`gatewayName`/`caPath`/`certPath`/`keyPath`，
见 `assembly._validate`），并确认本机 gateway 的 workspace 与 TLS 路径。若 gateway 不可用，会如实登记为 BLOCKED。

## 实测（2026-10-21 12:0x）：Server 已能列出真实 openshell provider

- 数据根先用 Server 自己创建（避免 `DATA_ROOT_UNOWNED`），再写入
  `<root>/state/openshell.json`（endpoint `127.0.0.1:17670`、workspace `ordessa-lab`、gateway `openshell`、mTLS 三件套路径）。
- 重启（进程环境屏蔽 clash 代理）后：banner `capabilities agents, environments, decisions`；
  `environments providers --json` → **completed**，`[('local', True), ('openshell', True)]`
  （`raw/t09-providers.json`）。
- 网关：`127.0.0.1:17670` LISTEN；workspace 列表 `default`、`ordessa-lab`。

## 尚未跑

`environments create openshell`（远端 provider 的 structured `reference` 形状）→ exec/files/delete + 取回。
下一步按 capability 的 create schema 构造 openshell 引用（沙箱名/镜像/命令），跑完整闭环。

## 实测（2026-10-21 12:0x）：真实沙箱 create 成功

- 用 Server + 真实本机 gateway 创建 OpenShell 环境：
  `environments.create {provider: openshell, reference:{image:"ghcr.io/nvidia/openshell/sandbox:0.1.3",
  policy:{landlock:{compatibility:"best_effort"}}, main_command:["sleep","infinity"]}}`
  → **completed**，identity `environment/d786cd0e…`，`backendId ab3aeb11-e84f-…`，phase `ready`。
  （首次用 `localhost/ordessa-harness-kilo` 失败：网关 gRPC 13 INTERNAL/podman provision；换 gateway sandbox 镜像成功。）
  网关日志确认 CreateSandbox 到达 podman provision。
- `environments.exec`（直接对 remote 环境）→ refused `CONFLICT`：远端 provider 的 exec 需走
  acquire→launch→process 路径，不能像 local 直接 exec（下一步做）。
- `environments.delete` → 网关已开始删除（sandbox 显示 `Deleting`），但客户端先超时返回
  `EFFECT_UNKNOWN`（"Response was not observed before the timeout"）——长操作/超时语义缺口再记一笔。

## 结论

T09 的"真实沙箱创建"已打通；`exec/files/delete` 的**远端路径**（acquire/launch/process + 长操作等待）
尚未完成，不能宣称 T09 闭环通过。

## 远端 exec/files 为何不通（读插件后确认，2026-10-21 12:1x）

`plugins/environments/openshell/.../provider.py` 的 provider 只实现 **生命周期**：

```
operations = frozenset({'start','stop','delete'})
create / inspect / recover_creation / open_use（只 release）/ start / stop / delete
```

**没有** `files`、`process`、`launch` 等接口。因此：
- `environments.exec` 对 openshell 走到 acquire 后需要 launch/process → 被 capability 拒绝为 CONFLICT；
- `environments.files` 同理没有 file 端点。

所以 T09 的"沙箱内执行命令 + 成果取回"**不是接线问题，而是 provider 能力缺口**：
需要在 openshell provider 里实现 gateway 侧的 process/files 能力（或复用 openshell SDK 的
exec/files RPC），这是独立的一片工作，不能靠现有 local provider 语义替代。

## 结论（更新）

- ✅ 真实网关上 create/inspect/stop/delete 生命周期可走通（delete 有长操作超时缺口）。
- ⛔ exec/files（沙箱内开发与成果取回）缺 provider 能力；T09/T10/T11 不通过。
