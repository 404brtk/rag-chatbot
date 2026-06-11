from dataclasses import dataclass
from typing import Any, Literal

from .repositories import StoredMessage


@dataclass(frozen=True, slots=True)
class LLMConfig:
    provider: Literal["openai", "llamacpp"]
    model: str
    system_prompt: str
    compaction_provider: Literal["openai", "llamacpp"]
    compaction_model: str
    max_input_tokens: int = 12_000  # TODO: adjust
    max_output_tokens: int = 4_096  # TODO: adjust
    temperature: float = 0.2
    history_limit: int = 500  # TODO: adjust
    compaction_threshold: float = 0.8

    def __post_init__(self):
        object.__setattr__(self, "provider", self.provider.strip())
        object.__setattr__(self, "model", self.model.strip())
        object.__setattr__(self, "system_prompt", self.system_prompt.strip())
        object.__setattr__(
            self, "compaction_provider", self.compaction_provider.strip()
        )
        object.__setattr__(self, "compaction_model", self.compaction_model.strip())


SUPPORTED_PROVIDERS = {"openai", "llamacpp"}


def validate_llm_config(data: dict) -> dict | None:
    if "provider" not in data or data["provider"] is None:
        return {
            "error": "provider is required.",
            "code": "invalid_config",
        }
    provider = data["provider"]
    if not isinstance(provider, str):
        return {
            "error": "provider must be a string.",
            "code": "invalid_config",
        }
    provider = provider.strip()
    if not provider:
        return {
            "error": "provider cannot be empty.",
            "code": "invalid_config",
        }
    if provider not in SUPPORTED_PROVIDERS:
        return {
            "error": f"Unsupported provider: {provider}. Supported: {', '.join(sorted(SUPPORTED_PROVIDERS))}.",
            "code": "invalid_config",
        }

    if "model" not in data or data["model"] is None:
        return {
            "error": "model is required.",
            "code": "invalid_config",
        }
    model = data["model"]
    if not isinstance(model, str):
        return {
            "error": "model must be a string.",
            "code": "invalid_config",
        }
    if not model.strip():
        return {
            "error": "model cannot be empty.",
            "code": "invalid_config",
        }

    if "compaction_model" in data and data["compaction_model"] is not None:
        compaction_model = data["compaction_model"]
        if not isinstance(compaction_model, str):
            return {
                "error": "compaction_model must be a string.",
                "code": "invalid_config",
            }

    if "compaction_provider" in data and data["compaction_provider"] is not None:
        compaction_provider = data["compaction_provider"]
        if not isinstance(compaction_provider, str):
            return {
                "error": "compaction_provider must be a string.",
                "code": "invalid_config",
            }
        compaction_provider = compaction_provider.strip()
        if compaction_provider and compaction_provider not in SUPPORTED_PROVIDERS:
            return {
                "error": f"Unsupported compaction provider: {compaction_provider}. Supported: {', '.join(sorted(SUPPORTED_PROVIDERS))}.",
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
    sent_messages: list[dict[str, Any]] | None = None


@dataclass(frozen=True, slots=True)
class ProviderChunk:
    text: str | None = None
    usage: dict[str, Any] | None = None
    provider: str | None = None
    model: str | None = None


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
