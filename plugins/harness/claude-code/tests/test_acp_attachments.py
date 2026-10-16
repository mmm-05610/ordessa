"""Preserved pinned ACP attachment semantics; no SDK/native delivery claim."""
import base64
import hashlib
import pytest

from ordessa_harness_claude_code.acp_attachments import (
    CLAUDE_ATTACH_UNDECLARED,
    CLAUDE_ATTACHMENT_HASH_MISMATCH,
    CLAUDE_ATTACHMENT_LIMIT,
    CLAUDE_ATTACHMENT_REF_INVALID,
    CLAUDE_ATTACHMENT_UNSUPPORTED,
    ClaudeAttachmentRefused,
    ClaudePreparedAttachment,
    assemble_attachment_blocks,
    claude_attachment_capabilities,
)


_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAAFElEQVR4nGP8z8DwnwEPYMInOXwUAADtmwT9ZHTcOAAAAABJRU5ErkJggg=="
)


def _attachment_ref(*, prepared_id="prepared-1", name="shot.png", mime_type="image/png",
                    data=_PNG_BYTES, sha=None):
    return ClaudePreparedAttachment(
        prepared_id=prepared_id, name=name,
        uri="https://ordessa.example/attachments/shot.png", mime_type=mime_type,
        sha256=sha or hashlib.sha256(data).hexdigest(), byte_length=len(data),
    )


def test_the_claude_pathway_assembles_a_real_image_block_with_verifiable_content():
    """image ref + 随行字节 → 真实附件块，base64 内容 sha256 与 ref 自洽（往返可验证）。"""
    ref = _attachment_ref()
    blocks = assemble_attachment_blocks(
        {ref.prepared_id: ref}, attach_declared=True, data_by_prepared_id={ref.prepared_id: _PNG_BYTES})
    assert blocks == (
        {"type": "image", "data": base64.b64encode(_PNG_BYTES).decode("ascii"),
         "mimeType": "image/png"},)
    assert hashlib.sha256(base64.b64decode(blocks[0]["data"])).hexdigest() == ref.sha256


def test_the_claude_pathway_sends_non_image_files_as_resource_link_text_only():
    """非图片 ref → resource_link：只投 URI 链接文本，不携带字节、不宣称上传。"""
    doc = ClaudePreparedAttachment(
        prepared_id="prepared-2", name="notes.md",
        uri="https://ordessa.example/attachments/notes.md", mime_type="text/markdown",
        sha256="a" * 64, byte_length=11)
    blocks = assemble_attachment_blocks({doc.prepared_id: doc}, attach_declared=True)
    assert blocks == ({"type": "resource_link", "uri": doc.uri, "name": "notes.md"},)


def test_the_claude_pathway_refuses_audio_instead_of_the_adapters_silent_drop():
    """audio 必须在通路层类型化拒绝：适配器会静默丢弃 audio 块（探针钉死的事实）。"""
    audio = ClaudePreparedAttachment(
        prepared_id="prepared-3", name="clip.wav",
        uri="https://ordessa.example/attachments/clip.wav", mime_type="audio/wav",
        sha256="b" * 64, byte_length=4)
    with pytest.raises(ClaudeAttachmentRefused) as refused:
        assemble_attachment_blocks({audio.prepared_id: audio}, attach_declared=True)
    assert refused.value.code == CLAUDE_ATTACHMENT_UNSUPPORTED
    assert "silently drops" in refused.value.reason


def test_the_claude_pathway_refuses_everything_when_attach_is_undeclared():
    """能力缺席 = 类型化拒绝（缺席即红），包括形状完全合法的 image ref。"""
    ref = _attachment_ref()
    with pytest.raises(ClaudeAttachmentRefused) as refused:
        assemble_attachment_blocks(
            {ref.prepared_id: ref}, attach_declared=False,
            data_by_prepared_id={ref.prepared_id: _PNG_BYTES})
    assert refused.value.code == CLAUDE_ATTACH_UNDECLARED
    capabilities = claude_attachment_capabilities(attach_declared=False)
    assert capabilities["kind"] == "absent" and capabilities["reason"]


def test_the_claude_pathway_refuses_over_limit_and_malformed_input():
    """超限（数量/大小）与形状非法都类型化拒绝，不静默放行也不静默截断。"""
    ref = _attachment_ref()
    oversized = _attachment_ref(prepared_id="prepared-big", name="big.png",
                                data=b"x" * (5 * 1024 * 1024 + 1))
    with pytest.raises(ClaudeAttachmentRefused) as count_refused:
        assemble_attachment_blocks(
            {f"prepared-{i}": _attachment_ref(prepared_id=f"prepared-{i}")
             for i in range(9)}, attach_declared=True)
    assert count_refused.value.code == CLAUDE_ATTACHMENT_LIMIT
    with pytest.raises(ClaudeAttachmentRefused) as size_refused:
        assemble_attachment_blocks(
            {oversized.prepared_id: oversized}, attach_declared=True,
            data_by_prepared_id={oversized.prepared_id: b"x" * (5 * 1024 * 1024 + 1)})
    assert size_refused.value.code == CLAUDE_ATTACHMENT_LIMIT
    with pytest.raises(ClaudeAttachmentRefused) as hash_refused:
        assemble_attachment_blocks(
            {ref.prepared_id: ref}, attach_declared=True,
            data_by_prepared_id={ref.prepared_id: _PNG_BYTES + b"x"})
    assert hash_refused.value.code == CLAUDE_ATTACHMENT_HASH_MISMATCH
    with pytest.raises(ClaudeAttachmentRefused) as missing_refused:
        assemble_attachment_blocks({ref.prepared_id: ref}, attach_declared=True)
    assert missing_refused.value.code == CLAUDE_ATTACHMENT_REF_INVALID
    with pytest.raises(ClaudeAttachmentRefused) as invalid_refused:
        ClaudePreparedAttachment.from_mapping({"name": "x", "uri": "file:///etc/passwd",
                                               "mimeType": "image/png", "sha256": "z" * 64,
                                               "byteLength": 1, "preparedId": "p"})
    assert invalid_refused.value.code == CLAUDE_ATTACHMENT_REF_INVALID


def test_the_claude_attachment_capability_statement_does_not_overclaim():
    """能力语句如实：只 png 过端到端验证；audio 明示拒绝；limit 是通道策略非适配器声明。"""
    capabilities = claude_attachment_capabilities(attach_declared=True)
    assert capabilities["kind"] == "available"
    assert capabilities["mimeTypes"] == ["image/*"]
    assert "audio" not in capabilities["mimeTypes"]
    assert capabilities["semantics"]["endToEndVerifiedMime"] == "image/png"
    assert "refused" in capabilities["semantics"]["audio"]
    assert capabilities["maxCount"] == 8 and capabilities["maxBytes"] > 0


def test_same_length_wrong_content_cannot_pass_digest_validation():
    ref = _attachment_ref(data=b'correct-bytes')
    with pytest.raises(ClaudeAttachmentRefused) as refused:
        assemble_attachment_blocks({ref.prepared_id: ref}, attach_declared=True,
            data_by_prepared_id={ref.prepared_id: b'changed-bytes'})
    assert refused.value.code == CLAUDE_ATTACHMENT_HASH_MISMATCH


def test_prepared_mapping_key_cannot_reidentify_attachment():
    ref = _attachment_ref()
    with pytest.raises(ClaudeAttachmentRefused) as refused:
        assemble_attachment_blocks({'different-prepared-id': ref}, attach_declared=True,
            data_by_prepared_id={ref.prepared_id: _PNG_BYTES})
    assert refused.value.code == CLAUDE_ATTACHMENT_REF_INVALID


@pytest.mark.parametrize('size', [True, 1.0, 0, -1])
def test_byte_length_remains_exact_positive_integer(size):
    with pytest.raises(ClaudeAttachmentRefused) as refused:
        ClaudePreparedAttachment.from_mapping({'preparedId': 'prepared', 'name': 'picture',
            'uri': 'https://ordessa.example/attachment', 'mimeType': 'image/png',
            'sha256': 'a' * 64, 'byteLength': size})
    assert refused.value.code == CLAUDE_ATTACHMENT_REF_INVALID
