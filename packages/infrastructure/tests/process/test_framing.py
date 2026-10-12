import pytest

from ordessa_infrastructure.process import MAX_FRAME_BYTES, ChannelFailure, FrameReader, FramingError, Message


def test_split_multibyte_utf8_and_multiple_frames_preserve_payload():
    reader = FrameReader()
    assert reader.feed(b'\xe4') == []
    assert reader.feed(b'\xb8\xad\r\nnext\npartial') == ['中', 'next']
    assert reader.feed(b'\n\n') == ['partial', '']
    reader.close()


def test_size_bound_counts_bytes_and_excludes_lf():
    reader = FrameReader(max_frame_bytes=3)
    assert reader.feed('中'.encode() + b'\n') == ['中']
    with pytest.raises(FramingError, match='exceeded 3 bytes'):
        reader.feed(b'abcd\n')


@pytest.mark.parametrize('chunks', [(b'abcd',), (b'ab', b'cd'), (b'abc', b'd\n')])
def test_oversize_rejected_with_or_without_delimiter(chunks):
    reader = FrameReader(max_frame_bytes=3)
    with pytest.raises(FramingError):
        for chunk in chunks:
            reader.feed(chunk)


@pytest.mark.parametrize('raw', [b'\xff\n', b'\xe4\n', b'\x80\n'])
def test_invalid_utf8_cannot_borrow_from_next_frame(raw):
    with pytest.raises(FramingError, match='invalid UTF-8') as caught:
        FrameReader().feed(raw)
    assert isinstance(caught.value, ChannelFailure)
    assert caught.value.code == 'FRAMING_ERROR'
    assert isinstance(caught.value.__cause__, UnicodeDecodeError)


def test_eof_rejects_truncated_frame():
    reader = FrameReader()
    reader.feed(b'complete\ntruncated')
    with pytest.raises(FramingError, match='truncated frame at EOF'):
        reader.close()


def test_eight_mib_protocol_limit_remains_distinct():
    assert MAX_FRAME_BYTES == 8 * 1024 * 1024
    assert FrameReader().feed(b'x' * MAX_FRAME_BYTES + b'\n') == ['x' * MAX_FRAME_BYTES]
    with pytest.raises(FramingError):
        FrameReader().feed(b'x' * (MAX_FRAME_BYTES + 1))


@pytest.mark.parametrize('raw,kind,method,identifier', [
    ({'method': 'call', 'id': 0, 'unknown': [1]}, 'request', 'call', 0),
    ({'method': 'notice'}, 'notification', 'notice', None),
    ({'result': None, 'id': 'r'}, 'response', None, 'r'),
    ({'method': 12, 'id': None}, 'request', None, None),
])
def test_message_preserves_raw_and_classifies_by_field_presence(raw, kind, method, identifier):
    message = Message(raw)
    assert message.raw is raw
    assert (message.kind, message.method, message.id) == (kind, method, identifier)
