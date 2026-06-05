import logging
import time
from typing import Any

import httpx
import openai
from django.conf import settings
from openai import AsyncOpenAI

from .attachments import parse_content
from .llm_config import (
    GenerationResult,
    LLMConfig,
    PermanentProviderError,
    ProviderChunk,
    TemporaryProviderError,
)
from .repositories import StoredMessage

logger = logging.getLogger(__name__)


def _parse_message_multimodal(content: str) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []

    for segment in parse_content(content):
        if segment.text is not None:
            text = segment.text.strip()
            if text:
                parts.append({"type": "text", "text": text})
        elif segment.attachment is not None:
            att = segment.attachment
            if att.mime.startswith("image/"):
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": att.content.strip()},
                    }
                )
            else:
                parts.append(
                    {
                        "type": "text",
                        "text": f"--- File: {att.name} ---\n{att.content}\n----------------",
                    }
                )

    if not parts:
        return [{"type": "text", "text": content}]

    merged_parts = []
    for part in parts:
        if part["type"] == "text":
            if merged_parts and merged_parts[-1]["type"] == "text":
                merged_parts[-1]["text"] += "\n\n" + part["text"]
            else:
                merged_parts.append(part)
        else:
            merged_parts.append(part)

    return merged_parts


def _format_message_content(content: str, provider: str) -> str | list[dict[str, Any]]:
    parts = _parse_message_multimodal(content)

    if provider == "llamacpp":
        text_runs = []
        for part in parts:
            if part["type"] == "text":
                text_runs.append(part["text"])
            elif part["type"] == "image_url":
                text_runs.append("[Image Attachment]")
        return "\n\n".join(text_runs)

    has_image = any(part["type"] == "image_url" for part in parts)
    if not has_image:
        return content

    return parts


class ProviderGateway:
    _llamacpp_context: int | None = None
    _llamacpp_context_fetched_at: float = 0.0
    _llamacpp_models: list[dict] | None = None
    _llamacpp_models_fetched_at: float = 0.0
    CACHE_TTL_SECONDS = 300.0

    @staticmethod
    def _build_client(*, api_key: str, provider: str) -> AsyncOpenAI:
        if provider == "llamacpp":
            return AsyncOpenAI(
                base_url=f"{settings.LLAMACPP_BASE_URL}/v1",
                api_key=api_key,
                timeout=60.0,
                max_retries=2,
            )
        return AsyncOpenAI(api_key=api_key, timeout=30.0, max_retries=2)

    async def _generate_openai(
        self,
        *,
        api_key: str,
        config: LLMConfig,
        messages: list[StoredMessage],
        response_format: dict[str, Any] | None = None,
    ) -> GenerationResult:
        client = self._build_client(api_key=api_key, provider=config.provider)
        try:
            kwargs = {
                "model": config.model,
                "messages": [{"role": "system", "content": config.system_prompt}]
                + [
                    {
                        "role": m.role,
                        "content": _format_message_content(m.content, config.provider),
                    }
                    for m in messages
                ],
                "temperature": config.temperature,
            }
            if config.provider == "llamacpp":
                kwargs["max_tokens"] = config.max_output_tokens
            else:
                kwargs["max_completion_tokens"] = config.max_output_tokens

            if response_format:
                kwargs["response_format"] = response_format

            response = await client.chat.completions.create(**kwargs)
        except (
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.InternalServerError,
        ) as e:
            raise TemporaryProviderError(str(e)) from e
        except openai.AuthenticationError as e:
            raise PermanentProviderError(f"Invalid API key: {e}") from e
        except openai.BadRequestError as e:
            raise PermanentProviderError(str(e)) from e

        usage_dict = response.usage.model_dump() if response.usage else {}

        return GenerationResult(
            text=response.choices[0].message.content.strip(),
            provider=config.provider,
            model=config.model,
            input_tokens=usage_dict.get("prompt_tokens"),
            output_tokens=usage_dict.get("completion_tokens"),
            usage=usage_dict,
            model_input=list(messages),
        )

    async def generate(
        self,
        *,
        api_key: str,
        config: LLMConfig,
        messages: list[StoredMessage],
        response_format: dict[str, Any] | None = None,
    ) -> GenerationResult:
        if config.provider in {"openai", "llamacpp"}:
            return await self._generate_openai(
                api_key=api_key,
                config=config,
                messages=messages,
                response_format=response_format,
            )
        raise PermanentProviderError(f"Unsupported provider: {config.provider}")

    async def _generate_openai_stream(
        self,
        *,
        api_key: str,
        config: LLMConfig,
        messages: list[StoredMessage],
    ):
        client = self._build_client(api_key=api_key, provider=config.provider)
        try:
            kwargs = {
                "model": config.model,
                "messages": [{"role": "system", "content": config.system_prompt}]
                + [
                    {
                        "role": m.role,
                        "content": _format_message_content(m.content, config.provider),
                    }
                    for m in messages
                ],
                "temperature": config.temperature,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if config.provider == "llamacpp":
                kwargs["max_tokens"] = config.max_output_tokens
            else:
                kwargs["max_completion_tokens"] = config.max_output_tokens

            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if chunk.usage:
                    yield ProviderChunk(usage=chunk.usage.model_dump())
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield ProviderChunk(text=delta)
        except (
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.InternalServerError,
        ) as e:
            raise TemporaryProviderError(str(e)) from e
        except openai.AuthenticationError as e:
            raise PermanentProviderError(f"Invalid API key: {e}") from e
        except openai.BadRequestError as e:
            raise PermanentProviderError(str(e)) from e

    async def generate_stream(
        self,
        *,
        api_key: str,
        config: LLMConfig,
        messages: list[StoredMessage],
    ):
        if config.provider in {"openai", "llamacpp"}:
            async for chunk in self._generate_openai_stream(
                api_key=api_key, config=config, messages=messages
            ):
                yield chunk
            return
        raise PermanentProviderError(f"Unsupported provider: {config.provider}")

    @staticmethod
    async def discover_llamacpp_context() -> int:
        now = time.time()
        if (
            ProviderGateway._llamacpp_context is not None
            and (now - ProviderGateway._llamacpp_context_fetched_at)
            < ProviderGateway.CACHE_TTL_SECONDS
        ):
            return ProviderGateway._llamacpp_context

        base = settings.LLAMACPP_BASE_URL
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{base}/props")
                resp.raise_for_status()
                n_ctx = resp.json()["default_generation_settings"]["n_ctx"]

            ProviderGateway._llamacpp_context = n_ctx
            ProviderGateway._llamacpp_context_fetched_at = now
            logger.info(f"Discovered llama.cpp context window: {n_ctx} tokens")
            return n_ctx
        except httpx.HTTPError:
            logger.warning(f"llama.cpp server is offline or unreachable at {base}")
            raise TemporaryProviderError(
                f"llama.cpp server is offline or unreachable at {base}"
            )

    @staticmethod
    async def discover_llamacpp_models() -> list[dict]:
        now = time.time()
        if (
            ProviderGateway._llamacpp_models is not None
            and (now - ProviderGateway._llamacpp_models_fetched_at)
            < ProviderGateway.CACHE_TTL_SECONDS
        ):
            return ProviderGateway._llamacpp_models

        base = settings.LLAMACPP_BASE_URL
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{base}/v1/models")
                resp.raise_for_status()
                data = resp.json().get("data", [])

            ProviderGateway._llamacpp_models = data
            ProviderGateway._llamacpp_models_fetched_at = now
            logger.info(f"Discovered {len(data)} llama.cpp model(s)")
            return data
        except httpx.HTTPError:
            logger.warning(f"llama.cpp server is offline or unreachable at {base}")
            raise TemporaryProviderError(
                f"llama.cpp server is offline or unreachable at {base}"
            )
