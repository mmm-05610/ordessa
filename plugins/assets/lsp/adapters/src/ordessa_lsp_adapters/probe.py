"""可用性诚实检查（016 LSP-4）。

``resolve_executable`` 只回答"这个可执行引用在当前 PATH 上能否解析"：
* 默认查找用 ``shutil.which``——只读 PATH，不 spawn、不读网络；
* ``lookup`` 可注入（测试用受控假 PATH，反例不依赖机器环境）；
* 缺席返回 ``present=False`` 与原因字符串，调用方必须把缺席落成该格
  ``unsupported`` 决策（``executable.present=false`` + 原因）——**不产假配
  置**（tasks.md LSP-4 红线）。

LSP 面全部依赖机器已装可执行程序（harnesses.md 逐格共同注记），所以探测
先于任何投影：探测缺席的品牌格没有"配置先写上再说"的路径。
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Callable

__all__ = ["ExecutablePresence", "resolve_executable"]

#: 可执行查找函数形态：输入可执行引用，输出解析路径或 None。
PathLookup = Callable[[str], "str | None"]


@dataclass(frozen=True)
class ExecutablePresence:
    """一次探测的事实记录（可序列化、可比较、不携带环境全量）。"""

    command: str
    present: bool
    resolved_path: str | None
    reason: str

    def to_jsonable(self) -> dict:
        return {"command": self.command, "present": self.present,
                "reason": self.reason, "resolved_path": self.resolved_path}


def resolve_executable(command: str,
                       lookup: PathLookup | None = None) -> ExecutablePresence:
    """解析可执行引用；缺席是事实不是错误，理由如实带出。"""
    finder = shutil.which if lookup is None else lookup
    found = finder(command)
    if isinstance(found, str) and found:
        return ExecutablePresence(
            command=command, present=True, resolved_path=found,
            reason=f"resolved on PATH: {found}")
    return ExecutablePresence(
        command=command, present=False, resolved_path=None,
        reason=f"executable {command!r} not found on PATH; "
               "the cell stays unsupported, no config is invented")
