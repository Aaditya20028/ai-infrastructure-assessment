"""Bounded UTF-8 SSE parser: CR, LF, CRLF, comments and multiline data."""

import codecs
from dataclasses import dataclass
import json


class StreamFormatError(ValueError):
    pass


@dataclass(frozen=True)
class Event:
    data: str
    event: str = "message"


class SSEParser:
    def __init__(self, max_event_chars=32768):
        self.limit = max_event_chars
        self.decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
        self.line = []
        self.data = []
        self.event = "message"
        self.after_cr = False
        self.size = 0
        self.max_pending = 0

    def _line_end(self):
        line = "".join(self.line)
        self.line.clear()
        if not line:
            event = Event("\n".join(self.data), self.event) if self.data else None
            self.data.clear()
            self.event = "message"
            self.size = 0
            return event
        if line.startswith(":"):
            return None
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "data":
            self.data.append(value)
        elif field == "event":
            self.event = value or "message"
        # id/retry/unknown fields are never forwarded: they can contain PII.
        return None

    def feed(self, chunk: bytes):
        try:
            text = self.decoder.decode(chunk)
        except UnicodeError:
            raise StreamFormatError("Invalid UTF-8") from None
        for char in text:
            if self.after_cr:
                self.after_cr = False
                if char == "\n":
                    continue
            self.size += 1
            if self.size > self.limit:
                raise StreamFormatError("SSE event limit exceeded")
            self.max_pending = max(self.max_pending, self.size)
            if char in "\r\n":
                self.after_cr = char == "\r"
                event = self._line_end()
                if event is not None:
                    yield event
            else:
                self.line.append(char)

    def finish(self):
        try:
            self.decoder.decode(b"", final=True)
        except UnicodeError:
            raise StreamFormatError("Incomplete UTF-8") from None
        if self.line or self.data or self.size:
            raise StreamFormatError("Incomplete SSE event")


def delta_frame(text: str) -> bytes:
    payload = {"choices": [{"delta": {"content": text}}]}
    return ("data: " + json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n\n").encode()


DONE = b"data: [DONE]\n\n"
ERROR = b'event: error\ndata: {"error":{"code":"stream_failed","message":"Upstream stream could not be safely completed"}}\n\n'
