import random

import pytest

from task_03_streaming.redaction import Redactor, RedactionLimitError


@pytest.mark.parametrize("source,expected", [
    ("alice@example.com", "[REDACTED]"),
    ("Mail alice+tag@example.co.uk, please.", "Mail [REDACTED], please."),
    ("123-45-6789", "[REDACTED]"), ("123456789", "[REDACTED]"),
    ("4111111111111111", "[REDACTED]"), ("4111 1111 1111 1111", "[REDACTED]"),
    ("3782-822463-10005", "[REDACTED]"),
    ("a@example.test; 123-45-6789; 4111-1111-1111-1111!", "[REDACTED]; [REDACTED]; [REDACTED]!"),
    ("Hello! Normal text, café. Order 1234; phone 202-555-0199.\n", "Hello! Normal text, café. Order 1234; phone 202-555-0199.\n"),
    ("", ""),
])
def test_patterns_and_normal_text_at_every_boundary(source, expected):
    for boundary in range(len(source) + 1):
        redactor = Redactor()
        actual = redactor.feed(source[:boundary]) + redactor.feed(source[boundary:]) + redactor.finish()
        assert actual == expected
        assert redactor.pending == 0


def test_randomized_arbitrary_splits_and_multiple_values():
    source = "Before alice@example.test; SSN 123-45-6789; card 4111 1111 1111 1111. After."
    expected = "Before [REDACTED]; SSN [REDACTED]; card [REDACTED]. After."
    for seed in range(100):
        rng = random.Random(seed)
        redactor = Redactor()
        output = []
        offset = 0
        while offset < len(source):
            width = rng.randint(1, 9)
            output.append(redactor.feed(source[offset:offset + width]))
            offset += width
        output.append(redactor.finish())
        assert "".join(output) == expected


def test_potential_email_and_number_prefixes_are_never_released():
    for value in ["alice@example.test", "123-45-6789", "4111 1111 1111 1111"]:
        redactor = Redactor()
        emitted = ""
        for char in value:
            emitted += redactor.feed(char)
            assert emitted == ""
        assert redactor.finish() == "[REDACTED]"


@pytest.mark.parametrize("value", ["a" * 513, "1 " * 65])
def test_oversize_candidates_fail_closed(value):
    redactor = Redactor()
    emitted = ""
    with pytest.raises(RedactionLimitError):
        for char in value:
            emitted += redactor.feed(char)
    assert emitted == ""


def test_long_stream_does_not_accumulate_history():
    redactor = Redactor()
    block = "Ordinary words, order 1234. " * 8
    emitted_chars = 0
    for _ in range(5000):
        emitted_chars += len(redactor.feed(block))
        assert redactor.pending <= 640
    emitted_chars += len(redactor.finish())
    assert emitted_chars == len(block) * 5000
    assert redactor.max_pending <= 640


def test_ambiguous_long_numeric_run_is_conservatively_redacted():
    redactor = Redactor()
    assert redactor.feed("123456789012345678901234 ") + redactor.finish() == "[REDACTED] "
