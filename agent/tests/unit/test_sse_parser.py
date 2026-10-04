"""WP-05 unit tests — incremental SSE parser (§10.3 rule 5).

Required behaviours: `data:` lines, `[DONE]`, comment lines, partial UTF-8
across chunk boundaries, and `\\r\\n` line endings.
"""

import pytest

from localmesh_agent.adapters.backends.openai_compat import SSEParser
from localmesh_agent.core.errors import MeshError


def test_single_data_line() -> None:
    parser = SSEParser()
    events = parser.feed(b'data: {"a": 1}\n\n')
    assert len(events) == 1
    assert events[0].data == '{"a": 1}'


def test_crlf_line_endings() -> None:
    parser = SSEParser()
    events = parser.feed(b"data: one\r\n\r\ndata: two\r\n\r\n")
    assert [e.data for e in events] == ["one", "two"]


def test_comment_lines_dropped() -> None:
    """Keepalive comments (`: ping`) never surface as events (§13.7)."""
    parser = SSEParser()
    events = parser.feed(b": ping\n\ndata: x\n\n: localmesh-fake\n")
    assert [e.data for e in events] == ["x"]


def test_multi_line_data_joined_with_newline() -> None:
    parser = SSEParser()
    events = parser.feed(b"data: l1\ndata: l2\n\n")
    assert events[0].data == "l1\nl2"


def test_done_sentinel_passthrough() -> None:
    parser = SSEParser()
    events = parser.feed(b"data: [DONE]\n\n")
    assert events[0].data == "[DONE]"


def test_partial_events_buffered() -> None:
    """Partial data values across feeds assemble into one event."""
    parser = SSEParser()
    assert parser.feed(b"data: hel") == []  # incomplete line: buffered
    assert [e.data for e in parser.feed(b"lo\n\n")] == ["hello"]
    # Also: data line terminated, event held until the blank line arrives.
    parser2 = SSEParser()
    assert parser2.feed(b"data: hel\n") == []
    assert [e.data for e in parser2.feed(b"\n")] == ["hel"]


def test_partial_utf8_across_chunks() -> None:
    """A multi-byte UTF-8 char split across feeds must decode correctly."""
    parser = SSEParser()
    full = 'data: {"t": "üé你好"}\n\n'.encode()
    cut = full.index("好".encode())  # split inside a 3-byte char
    assert parser.feed(full[:cut]) == []  # buffered, not mis-decoded
    events = parser.feed(full[cut:])
    assert events[0].data == '{"t": "üé你好"}'


def test_invalid_utf8_is_protocol_error() -> None:
    parser = SSEParser()
    with pytest.raises(MeshError) as excinfo:
        parser.feed(b"data: \xff\xfe\n\n")
    assert excinfo.value.code == "BACKEND_PROTOCOL"


def test_finish_drops_unterminated_event() -> None:
    """Per SSE semantics an event without its terminating blank line is
    incomplete and is dropped; the adapter treats the truncated stream as a
    protocol error regardless (§10.7)."""
    parser = SSEParser()
    assert parser.feed(b"data: tail") == []
    assert parser.finish() == []
    # A dispatched-but-unflushed decoder tail still yields complete events:
    parser2 = SSEParser()
    assert parser2.feed(b"data: ok\n\n") != []


def test_data_line_optional_space_stripped() -> None:
    parser = SSEParser()
    events = parser.feed(b"data:spaced\n\ndata: spaced2\n\n")
    assert [e.data for e in events] == ["spaced", "spaced2"]
