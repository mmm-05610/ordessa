"""Claude 附件通路（P-D）：prepared attachment refs → ACP `session/prompt` 内容块。

只做通路的**组装与守门**：把 connectors 侧冻结形状的附件 ref（`AcpPreparedAttachment`，
PC-9 对接基准，`preparedId` 预留）转换成钉版适配器已实测会正确投递的 ACP 内容块，
并在能力缺席/超限/形状非法时**类型化拒绝**。prepare 的存储语义（prepare→ref→release
的所有权与过期）归 P-C/S-05 的插件业务面，本模块不实现。

每条语义都是第一手实测（`packaging/claude/attachment-probe.mjs`，转录与哈希见
`specs/014-plugin-release/reports/P-D-probe-transcript.json`，2026-09-28）：

* 钉版 `@agentclientprotocol/claude-agent-acp@0.81.2` 的 initialize 播发
  `promptCapabilities {image:true, embeddedContext:true}`（推翻 0.77 时代
  "握手 promptCapabilities 为空" 的旧负证据）；
* image 块（data）→ Anthropic `image.source.base64`，端到端 base64 内容 sha256 一致；
* resource_link → URI **链接文本**（https 原文直传；file:// 为 `[@name](uri)` markdown
  链接）——不携带字节，不宣称"文件已上传"；
* audio 块被适配器**静默丢弃**（default 分支），轮内文本照常送达——因此本通路对
  audio 必须类型化拒绝，绝不静默放行让适配器丢弃。
"""
from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from typing import Mapping

#: 通道守门策略（channel policy），**不是**适配器播发的限制：适配器与 Anthropic 协议
#: 都未播发附件数量/大小上限，这里取保守值防超限请求进入投递链，超出即类型化拒绝。
MAX_ATTACHMENT_COUNT = 8
MAX_IMAGE_BYTES = 5 * 1024 * 1024

#: 仅 png 走过端到端哈希验证；image/* 按前缀接受（适配器对 media_type 逐字透传）。
IMAGE_MIME_PREFIX = "image/"
VERIFIED_END_TO_END_MIME = "image/png"

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ClaudeAttachmentRefused(ValueError):
    """附件被通路拒绝；`code` 是类型化原因，绝不静默丢弃或降级。"""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason


#: 拒绝码。UNDECLARED=能力缺席（注册表未声明 attach）；REF_INVALID=引用形状非法；
#: UNSUPPORTED=语义未声明（audio 等，适配器会静默丢弃的类型）；LIMIT=超过通道守门
#: 策略；HASH_MISMATCH=内容与 ref 的 sha256/byteLength 不符（投递前拦截）。
CLAUDE_ATTACH_UNDECLARED = "CLAUDE_ATTACH_UNDECLARED"
CLAUDE_ATTACHMENT_REF_INVALID = "CLAUDE_ATTACHMENT_REF_INVALID"
CLAUDE_ATTACHMENT_UNSUPPORTED = "CLAUDE_ATTACHMENT_UNSUPPORTED"
CLAUDE_ATTACHMENT_LIMIT = "CLAUDE_ATTACHMENT_LIMIT"
CLAUDE_ATTACHMENT_HASH_MISMATCH = "CLAUDE_ATTACHMENT_HASH_MISMATCH"


@dataclass(frozen=True)
class ClaudePreparedAttachment:
    """connectors `AcpPreparedAttachment` 冻结形状（plugins/connectors/acp/src/attachments.ts）。

    `preparedId` 是 owner 签发的不透明 id：Server ACP DTO 当前不携带（同源注释），
    本通路按 PC-9 基准预留该字段。逐字段校验与 connectors 的 `validPreparedReference`
    一致（uri 必须带 scheme 且非 `file:`——渲染器永不通告本地路径）。
    """

    prepared_id: str
    name: str
    uri: str
    mime_type: str
    sha256: str
    byte_length: int

    def __post_init__(self) -> None:
        if not isinstance(self.prepared_id, str) or not self.prepared_id.strip():
            raise ValueError("preparedId is required")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name is required")
        if not isinstance(self.uri, str) or not _SCHEME.match(self.uri) or self.uri.lower().startswith("file:"):
            raise ValueError("uri must be a non-file absolute URI")
        if not isinstance(self.mime_type, str) or not self.mime_type.strip():
            raise ValueError("mimeType is required")
        if not isinstance(self.sha256, str) or not _SHA256.match(self.sha256):
            raise ValueError("sha256 must be 64 hex characters")
        if type(self.byte_length) is not int or isinstance(self.byte_length, bool) or self.byte_length <= 0:
            raise ValueError("byteLength must be a positive integer")

    @classmethod
    def from_mapping(cls, raw: Mapping) -> "ClaudePreparedAttachment":
        """Accept the connectors DTO verbatim (camelCase keys); any drift is REF_INVALID."""
        try:
            return cls(
                prepared_id=raw["preparedId"], name=raw["name"], uri=raw["uri"],
                mime_type=raw["mimeType"], sha256=raw["sha256"], byte_length=raw["byteLength"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ClaudeAttachmentRefused(
                CLAUDE_ATTACHMENT_REF_INVALID, f"attachment reference malformed: {exc}") from exc


def claude_attachment_capabilities(*, attach_declared: bool) -> dict:
    """The channel's attachment capability statement (connectors `AcpAttachmentCapabilities` shape).

    诚实边界：image/* 按前缀接受，但**只有 image/png 走过端到端哈希验证**；resource_link
    的 https 形态是探针实测形态，http 未单测（同一逐字透传代码路径）；audio 不接受。
    maxBytes/maxCount 是通道守门策略，不是适配器播发的限制。
    """
    if not attach_declared:
        return {"kind": "absent", "reason": (
            "the claude-code registry entry does not declare attach; the attachment "
            "pathway refuses everything instead of guessing")}
    return {
        "kind": "available",
        "mimeTypes": [IMAGE_MIME_PREFIX + "*"],
        "uriSchemes": ["https", "http"],
        "maxBytes": MAX_IMAGE_BYTES,
        "maxCount": MAX_ATTACHMENT_COUNT,
        "semantics": {
            "image": "real attachment block (image.source.base64, content-hash verified end to end)",
            "non-image": "resource_link URI text (never bytes, never an upload claim)",
            "audio": "refused - the adapter silently drops audio blocks (probe-pinned)",
            "endToEndVerifiedMime": VERIFIED_END_TO_END_MIME,
        },
    }


def verify_attachment(ref: ClaudePreparedAttachment, *, data: bytes) -> None:
    """Content-faithfulness precondition: the bytes must hash to the ref's own digest."""
    if len(data) != ref.byte_length:
        raise ClaudeAttachmentRefused(
            CLAUDE_ATTACHMENT_HASH_MISMATCH,
            f"byteLength {ref.byte_length} != {len(data)} held bytes")
    digest = hashlib.sha256(data).hexdigest()
    if digest != ref.sha256:
        raise ClaudeAttachmentRefused(
            CLAUDE_ATTACHMENT_HASH_MISMATCH,
            f"sha256 {ref.sha256} != {digest} of held bytes")


def assemble_attachment_blocks(
    refs: Mapping[str, ClaudePreparedAttachment],
    *,
    attach_declared: bool,
    data_by_prepared_id: Mapping[str, bytes] | None = None,
) -> tuple[dict, ...]:
    """Refs → ACP `session/prompt` content blocks, in the refs' own order.

    语义分层（如实）：image/* → 真实附件块（data 必须随行并先过哈希校验）；其余非
    audio → `resource_link`（URI 链接文本，适配器实测形态）；audio/* → 类型化拒绝。
    任何拒绝都抛 `ClaudeAttachmentRefused`，绝不静默丢附件、绝不降级不报。
    """
    if not attach_declared:
        raise ClaudeAttachmentRefused(
            CLAUDE_ATTACH_UNDECLARED,
            "attach is not declared for claude-code; attachment delivery is unavailable")
    if len(refs) > MAX_ATTACHMENT_COUNT:
        raise ClaudeAttachmentRefused(
            CLAUDE_ATTACHMENT_LIMIT,
            f"{len(refs)} attachments exceed the channel policy maximum {MAX_ATTACHMENT_COUNT}")
    held = data_by_prepared_id or {}
    blocks: list[dict] = []
    for prepared_id, ref in refs.items():
        if ref.prepared_id != prepared_id:
            raise ClaudeAttachmentRefused(
                CLAUDE_ATTACHMENT_REF_INVALID,
                f"mapping key {prepared_id!r} does not match ref preparedId {ref.prepared_id!r}")
        if ref.mime_type.startswith(IMAGE_MIME_PREFIX):
            if ref.byte_length > MAX_IMAGE_BYTES:
                raise ClaudeAttachmentRefused(
                    CLAUDE_ATTACHMENT_LIMIT,
                    f"{ref.name}: {ref.byte_length} bytes exceed the channel policy "
                    f"maximum {MAX_IMAGE_BYTES}")
            data = held.get(prepared_id)
            if data is None:
                raise ClaudeAttachmentRefused(
                    CLAUDE_ATTACHMENT_REF_INVALID,
                    f"{ref.name}: image attachment without its content bytes")
            verify_attachment(ref, data=data)
            blocks.append({
                "type": "image", "data": base64.b64encode(data).decode("ascii"),
                "mimeType": ref.mime_type,
            })
            continue
        if ref.mime_type.startswith("audio/"):
            raise ClaudeAttachmentRefused(
                CLAUDE_ATTACHMENT_UNSUPPORTED,
                f"{ref.name}: audio is undeclared and the pinned adapter silently drops "
                "audio blocks (probe-pinned); refusing instead of relaying")
        blocks.append({"type": "resource_link", "uri": ref.uri, "name": ref.name})
    return tuple(blocks)
