"""LSP 域定义模型（016 LSP-2）。

三条域内硬规则，全部是数据校验而不是调用约定：

* **引用制**：``command`` 是可执行引用（名字或绝对路径字符串）。可执行本体
  绝不入仓——模型根本没有承载二进制的字段，校验拒绝把命令写成"会携带内容"
  的形状（空串、含 NUL、路径分隔符出现在名字首位等只按"非法引用"拒绝，
  不解释语义；在场性由 adapters 的探测回答，这里不猜）。
* **语言映射非空**：一台服务器/格式化器必须声明它服务哪些语言（语言标识用
  LSP 的 LanguageId 词汇，域内不解释大小写差异，按原样保留并查重）。
* **作用域显式**：``LspSelection.scope`` 只接受 ``session``/``profile``
  两个字面量；没有隐式默认作用域——缺席就是校验错误。

命名规则：``name`` 用小写字母开头的 [a-z0-9.-]，长度 1..64。域内标识符
（definition 名、会话键、品牌键）都以它为准，保证转录字节稳定可复现。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

__all__ = [
    "SCOPE_SESSION",
    "SCOPE_PROFILE",
    "LspDefinitionError",
    "LspServerDefinition",
    "FormatterDefinition",
    "LspSelection",
]

#: 作用域字面量。二者是穷尽集合：选择必须显式携带其一。
SCOPE_SESSION = "session"
SCOPE_PROFILE = "profile"
_SCOPES = (SCOPE_SESSION, SCOPE_PROFILE)

_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]{0,63}$")

_SERVER_KIND = "lsp-server"
_FORMATTER_KIND = "formatter"


class LspDefinitionError(ValueError):
    """定义/选择校验失败。理由随异常给出，不静默修正。"""


def _check_name(name: object) -> str:
    if not isinstance(name, str) or not _NAME.match(name):
        raise LspDefinitionError(
            f"definition name {name!r} must match [a-z0-9][a-z0-9.-]{{0,63}}")
    return name


def _check_command(command: object) -> str:
    if not isinstance(command, str) or not command.strip():
        raise LspDefinitionError("command must be a non-empty executable reference")
    if "\x00" in command:
        raise LspDefinitionError("command must not carry NUL bytes")
    if command != command.strip():
        raise LspDefinitionError("command must not carry surrounding whitespace")
    return command


def _check_args(args: object) -> tuple[str, ...]:
    if not isinstance(args, (tuple, list)) or any(
            not isinstance(a, str) for a in args):
        raise LspDefinitionError("args must be a sequence of strings")
    return tuple(args)


def _check_languages(languages: object) -> tuple[str, ...]:
    if not isinstance(languages, (tuple, list)) or not languages:
        raise LspDefinitionError(
            "languages must be a non-empty sequence of LSP language ids")
    seen: set[str] = set()
    out: list[str] = []
    for lang in languages:
        if not isinstance(lang, str) or not lang.strip() or lang != lang.strip():
            raise LspDefinitionError(
                f"language id {lang!r} must be a non-empty, untrimmed-free string")
        if lang in seen:
            raise LspDefinitionError(f"duplicate language id {lang!r}")
        seen.add(lang)
        out.append(lang)
    return tuple(out)


@dataclass(frozen=True)
class LspServerDefinition:
    """一台语言服务器的引用式定义。"""

    name: str
    command: str
    languages: tuple[str, ...]
    args: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        _check_name(self.name)
        _check_command(self.command)
        object.__setattr__(self, "args", _check_args(self.args))
        object.__setattr__(self, "languages", _check_languages(self.languages))

    @property
    def kind(self) -> str:
        return _SERVER_KIND

    def to_jsonable(self) -> dict:
        return {"args": list(self.args), "command": self.command,
                "kind": self.kind, "languages": list(self.languages),
                "name": self.name}


@dataclass(frozen=True)
class FormatterDefinition:
    """一个格式化器的引用式定义（与 server 同形，kind 不同）。"""

    name: str
    command: str
    languages: tuple[str, ...]
    args: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        _check_name(self.name)
        _check_command(self.command)
        object.__setattr__(self, "args", _check_args(self.args))
        object.__setattr__(self, "languages", _check_languages(self.languages))

    @property
    def kind(self) -> str:
        return _FORMATTER_KIND

    def to_jsonable(self) -> dict:
        return {"args": list(self.args), "command": self.command,
                "kind": self.kind, "languages": list(self.languages),
                "name": self.name}


@dataclass(frozen=True)
class LspSelection:
    """一次启用选择：定义集合 + 显式作用域。

    定义按 name 查重；server 与 formatter 共用一个名字空间（同一选择内
    重名即校验错误——投影决策记录以 name 为主键）。
    """

    scope: str
    servers: tuple[LspServerDefinition, ...] = field(default=())
    formatters: tuple[FormatterDefinition, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.scope not in _SCOPES:
            raise LspDefinitionError(
                f"scope must be one of {_SCOPES}, got {self.scope!r}")
        object.__setattr__(self, "servers", tuple(self.servers))
        object.__setattr__(self, "formatters", tuple(self.formatters))
        names: set[str] = set()
        for definition in (*self.servers, *self.formatters):
            if definition.name in names:
                raise LspDefinitionError(
                    f"duplicate definition name {definition.name!r} in selection")
            names.add(definition.name)

    def definitions(self) -> Iterable[LspServerDefinition | FormatterDefinition]:
        return (*self.servers, *self.formatters)

    def to_jsonable(self) -> dict:
        return {
            "formatters": [d.to_jsonable() for d in self.formatters],
            "scope": self.scope,
            "servers": [d.to_jsonable() for d in self.servers],
        }
