"""Pinned cl100k_base token IDs; no byte/character/word-count approximation."""

from functools import lru_cache

ENCODING_NAME = "cl100k_base"
COUNTING_METHOD = "tiktoken_cl100k_base_v1"
LEGACY_METHOD = "legacy_utf8_bytes_v1"


@lru_cache(maxsize=1)
def encoding():
    import tiktoken

    return tiktoken.get_encoding(ENCODING_NAME)


def count_tokens(text: str) -> int:
    # User-controlled special-token spellings are ordinary text, not control IDs.
    return len(encoding().encode_ordinary(text))


def truncate_to_tokens(text: str, maximum: int) -> str:
    if type(maximum) is not int or maximum < 0:
        raise ValueError("Invalid output token limit")
    tokenizer = encoding()
    ids = tokenizer.encode_ordinary(text)
    if len(ids) <= maximum:
        return text
    prefix = ids[:maximum]
    while prefix:
        # A token prefix may end inside a UTF-8 character. Never substitute a
        # replacement character that could change the counted output budget.
        candidate = tokenizer.decode_bytes(prefix).decode("utf-8", errors="ignore")
        if count_tokens(candidate) <= maximum:
            return candidate
        prefix.pop()  # Defensive re-tokenization check after a Unicode boundary.
    return ""
