"""字节稳定的规范转录（016 LSP-5 "golden 转录（字节稳定）" 的基础）。

规则固定为一组、不许调用方挑选：

* ``sort_keys=True`` —— 键序由内容决定，与插入序无关；
* ``separators=(",", ":")`` —— 紧凑；
* ``ensure_ascii=False`` + UTF-8 编码 —— 非 ASCII 原样输出；
* ``allow_nan=False`` —— 非有限数不是合法转录内容，直接失败；
* 末尾一个换行符 —— POSIX 文本文件习惯，golden 文件按字节比较时稳定。

``ensure_ascii=False`` 是刻意的：转录对非 ASCII 语言 id/路径保持原样，
把"编码不一致"留在产出时刻暴露，而不是藏进 \\u 转义。
"""
from __future__ import annotations

import json
from typing import Any

__all__ = ["canonical_json_text", "canonical_json_bytes"]


def canonical_json_text(value: Any) -> str:
    """规范 JSON 文本：排序键、紧凑、非 ASCII 原样、末尾单换行。"""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"


def canonical_json_bytes(value: Any) -> bytes:
    """规范 JSON 的 UTF-8 字节串（golden 文件按字节比较的形态）。"""
    return canonical_json_text(value).encode("utf-8")
