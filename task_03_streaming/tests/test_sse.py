import random

import pytest

from task_03_streaming.sse import Event, SSEParser, StreamFormatError


@pytest.mark.parametrize("newline", ["\n", "\r", "\r\n"])
def test_sse_multiline_comments_and_utf8_at_every_split(newline):
    wire = ("\ufeff: comment" + newline + "id: hidden@example.test" + newline + "event: message" + newline +
            "data: first café" + newline + "data: second" + newline + newline).encode()
    for split in range(len(wire) + 1):
        parser = SSEParser()
        events = list(parser.feed(wire[:split])) + list(parser.feed(wire[split:]))
        parser.finish()
        assert events == [Event("first café\nsecond")]


def test_many_frames_randomized_splits():
    wire = b'data: one\n\ndata: two\r\n\r\ndata: [DONE]\n\n'
    for seed in range(30):
        rng = random.Random(seed)
        parser = SSEParser()
        result = []
        offset = 0
        while offset < len(wire):
            width = rng.randint(1, 7)
            result.extend(parser.feed(wire[offset:offset + width]))
            offset += width
        parser.finish()
        assert result == [Event("one"), Event("two"), Event("[DONE]")]


@pytest.mark.parametrize("wire", [b'data: missing blank line', b'data: unfinished\n', b'\xff', b'\xc3'])
def test_malformed_or_truncated_frames(wire):
    parser = SSEParser()
    with pytest.raises(StreamFormatError):
        list(parser.feed(wire))
        parser.finish()


def test_oversize_event_and_comments_are_bounded():
    for wire in [b'data: ' + b'x' * 100, b': ' + b'x' * 100]:
        parser = SSEParser(max_event_chars=32)
        with pytest.raises(StreamFormatError):
            list(parser.feed(wire))
        assert parser.max_pending <= 32
