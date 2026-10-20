"""ordessa_lsp_api — LSP 资产域的定义模型与规范转录（016 LSP-2/LSP-5）。

只含纯数据与纯函数：定义、选择、校验、字节稳定序列化。零依赖、零 I/O；
可执行文件探测与品牌投影决策在 ``ordessa_lsp_adapters``。
"""
from .definitions import (
    FormatterDefinition,
    LspDefinitionError,
    LspSelection,
    LspServerDefinition,
    SCOPE_PROFILE,
    SCOPE_SESSION,
)
from .transcription import canonical_json_bytes, canonical_json_text

__all__ = [
    "FormatterDefinition",
    "LspDefinitionError",
    "LspSelection",
    "LspServerDefinition",
    "SCOPE_PROFILE",
    "SCOPE_SESSION",
    "canonical_json_bytes",
    "canonical_json_text",
]
