"""Reserve and reconcile actual tokenizer-produced token IDs."""

from .models import CompletionRequest, ProviderResult, Usage
from .tokenization import count_tokens


def input_tokens(prompt: str) -> int:
    return count_tokens(prompt)


def reservation_tokens(request: CompletionRequest) -> int:
    return input_tokens(request.prompt) + request.max_output_tokens


def actual_usage(request: CompletionRequest, response: ProviderResult) -> Usage:
    measured = Usage(input_tokens=input_tokens(request.prompt), output_tokens=count_tokens(response.text))
    if measured.output_tokens > request.max_output_tokens:
        raise ValueError("Provider exceeded its output contract")
    if response.usage is not None and response.usage != measured:
        raise ValueError("Provider usage did not match the local token contract")
    return measured
