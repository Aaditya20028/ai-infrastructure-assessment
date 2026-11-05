"""The mock contract is one UTF-8 byte per accounted token unit."""

from .models import CompletionRequest, ProviderResult, Usage


def input_tokens(prompt: str) -> int:
    return len(prompt.encode("utf-8"))


def reservation_tokens(request: CompletionRequest) -> int:
    return input_tokens(request.prompt) + request.max_output_tokens


def actual_usage(request: CompletionRequest, response: ProviderResult) -> Usage:
    measured = Usage(input_tokens=input_tokens(request.prompt), output_tokens=len(response.text.encode("utf-8")))
    if measured.output_tokens > request.max_output_tokens:
        raise ValueError("Provider exceeded its output contract")
    if response.usage is not None and response.usage != measured:
        raise ValueError("Provider usage did not match the local token contract")
    return measured
