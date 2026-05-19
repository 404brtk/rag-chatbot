from dataclasses import dataclass
from typing import Any, Literal

from .repositories import StoredMessage


@dataclass(frozen=True, slots=True)
class LLMConfig:
    provider: Literal["openai", "llamacpp"]
    model: str
    system_prompt: str
    max_input_tokens: int = 12_000  # TODO: adjust
    max_output_tokens: int = 1_024  # TODO: adjust
    temperature: float = 0.2
    history_limit: int = 500  # TODO: adjust
    compaction_threshold: float = 0.8
    compaction_model: str = "gpt-5.4-mini"


SUPPORTED_PROVIDERS = {"openai", "llamacpp"}


def validate_llm_config(data: dict) -> dict | None:
    provider = data.get("provider", "openai")
    if provider not in SUPPORTED_PROVIDERS:
        return {
            "error": f"Unsupported provider: {provider}. Supported: {', '.join(sorted(SUPPORTED_PROVIDERS))}.",
            "code": "invalid_config",
        }

    model = data.get("model", "gpt-5.4-mini")
    if not isinstance(model, str) or not model.strip():
        return {
            "error": "model must be a non-empty string.",
            "code": "invalid_config",
        }

    compaction_model = data.get("compaction_model")
    if compaction_model is not None and (
        not isinstance(compaction_model, str) or not compaction_model.strip()
    ):
        return {
            "error": "compaction_model must be a non-empty string if provided.",
            "code": "invalid_config",
        }

    max_input_tokens = data.get("max_input_tokens", 12_000)
    if (
        not isinstance(max_input_tokens, int)
        or isinstance(max_input_tokens, bool)
        or max_input_tokens < 100
        or max_input_tokens > 200_000
    ):
        return {
            "error": "max_input_tokens must be an integer between 100 and 200,000.",
            "code": "invalid_config",
        }

    compaction_threshold = data.get("compaction_threshold", 0.8)
    if (
        not isinstance(compaction_threshold, (int, float))
        or isinstance(compaction_threshold, bool)
        or compaction_threshold < 0.0
        or compaction_threshold > 1.0
    ):
        return {
            "error": "compaction_threshold must be a number between 0.0 and 1.0.",
            "code": "invalid_config",
        }

    return None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    usage: dict[str, Any]
    model_input: list[StoredMessage]
    user_message_id: str | None = None
    assistant_message_id: str | None = None


@dataclass(frozen=True, slots=True)
class StreamEvent:
    type: Literal["token", "done", "error", "compaction_done"]
    content: str | None = None
    message_id: str | None = None
    title: str | None = None
    usage: dict[str, Any] | None = None
    provider: str | None = None
    model: str | None = None
    error_message: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderChunk:
    text: str | None = None
    usage: dict[str, Any] | None = None


class ChatServiceError(Exception):
    pass


class InvalidInputError(ChatServiceError):
    pass


class MissingApiKeyError(ChatServiceError):
    pass


class TemporaryProviderError(ChatServiceError):
    pass


class PermanentProviderError(ChatServiceError):
    pass
