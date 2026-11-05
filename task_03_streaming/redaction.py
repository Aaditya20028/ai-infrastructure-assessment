"""Hold ambiguous lexical candidates, never a whole generation.

This is deterministic pattern detection, not a general semantic PII classifier.
"""

import re

MARKER = "[REDACTED]"
EMAIL_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.!#$%&'*+/=?^_`{|}~@-")
EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}")
SSN = re.compile(r"(?<![0-9])(?:[0-9]{3}-[0-9]{2}-[0-9]{4}|[0-9]{9})(?![0-9])")
# Intentionally redact longer runs too: do not leak a card embedded in a longer
# ambiguous numeric run. No Luhn check is used to excuse a possible disclosure.
CARD = re.compile(r"(?:[0-9][ \t-]*){12,}[0-9]")


class RedactionLimitError(ValueError):
    pass


class Redactor:
    def __init__(self, email_limit=512, numeric_limit=128):
        if email_limit < 1 or numeric_limit < 1:
            raise ValueError("Candidate limits must be positive")
        self.email_limit = email_limit
        self.numeric_limit = numeric_limit
        self.email = ""
        self.numeric = ""
        self.max_pending = 0

    @property
    def pending(self):
        return len(self.email) + len(self.numeric)

    def _numbers(self, text):
        output = []
        for char in text:
            if "0" <= char <= "9" or (self.numeric and char in " \t-"):
                self.numeric += char
                if len(self.numeric) > self.numeric_limit:
                    raise RedactionLimitError("Numeric candidate limit exceeded")
            else:
                if self.numeric:
                    output.append(self._flush_numbers())
                output.append(char)
            self.max_pending = max(self.max_pending, self.pending)
        return "".join(output)

    def _flush_numbers(self):
        text, self.numeric = self.numeric, ""
        return SSN.sub(MARKER, CARD.sub(MARKER, text))

    def feed(self, text: str) -> str:
        output = []
        for char in text:
            if char in EMAIL_CHARS:
                self.email += char
                if len(self.email) > self.email_limit:
                    raise RedactionLimitError("Email candidate limit exceeded")
            else:
                if self.email:
                    token, self.email = self.email, ""
                    output.append(self._numbers(EMAIL.sub(MARKER, token)))
                output.append(self._numbers(char))
            self.max_pending = max(self.max_pending, self.pending)
        return "".join(output)

    def finish(self) -> str:
        token, self.email = self.email, ""
        return self._numbers(EMAIL.sub(MARKER, token)) + self._flush_numbers()
