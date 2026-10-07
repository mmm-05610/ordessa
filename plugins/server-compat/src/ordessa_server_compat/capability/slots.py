"""组件槽位（语义三元组）与具体能力面的关系，以及 id 形状守卫。

runtime_composition 的协调器用三个**组件级**能力 id 选择槽位实现者
（host / sandbox / terminal，见 ``coordinator.py`` 的三元组循环）；被选中的
实现者再用**具体**能力 id 声明它在这个方向上真正提供了什么、以什么参数声明。
两层词汇的分工是本模块登记的全部内容：

* 槽位 id（``isolation.wrap@1``、``process.spawn.typed@1``、``terminal.run@1``）：
  回答"哪一个组件提供这个机制"，只出现在协调器的组件需求里；
* 具体能力 id（``filesystem.readonly@1`` 等）：回答"该组件在这个方向上提供了
  什么、以什么 target 参数"，出现在逐执行的声明文档与 demand/grant 集里。

:data:`COMPONENT_SLOT_CAPABILITIES` 把每个槽位登记到它**当前可声明**的具体能力
全集。守卫（:func:`slot_of_capability`）只接受登记过的 id：一个拼出来的、
不属于任何槽位族的能力 id 会返回 ``None``，调用方的测试因此失败，而不是静默
进入声明或需求集。新增具体能力时必须同时更新登记表与声明方（有测试锁一致性）。

已知未收敛项（记录，不在本单修）：terminal 组件今天用非版本化的短名能力
（``"pty"``、``"scrollback"`` 等，见 ``agent_box_terminal_session.tmux``），
不符合 ``name@N`` 形状；其版本化收敛留给后续工单，本单的守卫只锁声明/需求
侧已登记的具体能力。
"""
from __future__ import annotations

from .ids import require_capability_id

#: 槽位 id → 该槽位实现者当前可声明的具体能力全集。
#: ``isolation.wrap@1`` 组与 ``agent_box_sandbox_bwrap.provider`` 的跨模板并集
#: 逐项相等（测试锁定）；per-execution 声明是该集的子集（按执行构造）。
COMPONENT_SLOT_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "isolation.wrap@1": (
        "filesystem.mounts@1",
        "filesystem.readonly@1",
        "filesystem.writable@1",
        "filesystem.tmpfs@1",
        "filesystem.symlink-safe@1",
        "network.none@1",
        "network.inherit@1",
        "env.bounded@1",
        "home.workspace@1",
        "digest.read-back@1",
    ),
    "process.spawn.typed@1": (
        "argv.safe@1",
        "cwd.token@1",
        "env.token@1",
        "staging.path-token@1",
        "identity.drift@1",
        "transport.local-exec@1",
        "wsl.distro-affinity@1",
    ),
    # 终端组暂空：见模块 docstring 的已知未收敛项。
    "terminal.run@1": (),
}

#: 登记表里允许出现的能力 id（构建期校验一次，形状错误即启动失败）。
for _slot, _capabilities in COMPONENT_SLOT_CAPABILITIES.items():
    require_capability_id(_slot)
    for _capability in _capabilities:
        require_capability_id(_capability)


def slot_of_capability(capability_id: str) -> str | None:
    """返回登记该具体能力的槽位；未登记（拼出来的）id 返回 ``None``。"""
    for slot, capabilities in COMPONENT_SLOT_CAPABILITIES.items():
        if capability_id in capabilities:
            return slot
    return None


__all__ = ["COMPONENT_SLOT_CAPABILITIES", "slot_of_capability"]
