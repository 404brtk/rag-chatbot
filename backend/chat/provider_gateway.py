import base64
import logging
import os
import time
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError
import httpx
import openai
from django.conf import settings
from openai import AsyncOpenAI

from core.exceptions import TemporaryProviderError, PermanentProviderError
from .llm_config import (
    GenerationResult,
    LLMConfig,
    ProviderChunk,
)
from .repositories import StoredMessage
from .attachments import is_safe_attachment_path, load_text_attachment

logger = logging.getLogger(__name__)


def _build_openai_messages(messages: list[StoredMessage]) -> list[dict[str, Any]]:
    result = []
    for m in messages:
        if not m.attachments:
            content: str | list[dict[str, Any]] = m.content
        else:
            parts: list[dict[str, Any]] = [{"type": "text", "text": m.content}]
            for att in m.attachments:
                filename = att.get("id", "")
                if not is_safe_attachment_path(filename):
                    continue
                mime = att.get("mimeType", "")
                if mime.startswith("image/"):
                    local_path = os.path.join(
                        settings.MEDIA_ROOT, "attachments", filename
                    )
                    if os.path.exists(local_path):
                        with open(local_path, "rb") as image_file:
                            encoded_string = base64.b64encode(image_file.read()).decode(
                                "utf-8"
                            )
                        data_url = f"data:{mime};base64,{encoded_string}"
                    else:
                        data_url = f"{settings.MEDIA_URL}attachments/{filename}"
                    parts.append({"type": "image_url", "image_url": {"url": data_url}})
                else:
                    file_content = load_text_attachment(filename)
                    if file_content:
                        parts.append(
                            {
                                "type": "text",
                                "text": f"--- File: {att['name']} ---\n{file_content}\n----------------",
                            }
                        )
                    else:
                        parts.append(
                            {
                                "type": "text",
                                "text": f"--- File: {att['name']} ---\nSize: {att['size']} bytes\n----------------",
                            }
                        )
            content = parts
        result.append({"role": m.role, "content": content})
    return result


def _build_gemini_messages(messages: list[StoredMessage]) -> list[dict[str, Any]]:
    contents = []
    for m in messages:
        role = "model" if m.role == "ai" else "user"
        parts: list[dict[str, Any]] = [{"text": m.content}]
        for att in m.attachments or []:
            filename = att.get("id", "")
            if not is_safe_attachment_path(filename):
                continue
            mime = att.get("mimeType", "")
            if mime.startswith("image/"):
                local_path = os.path.join(settings.MEDIA_ROOT, "attachments", filename)
                if os.path.exists(local_path):
                    with open(local_path, "rb") as image_file:
                        parts.append(
                            {
                                "inline_data": {
                                    "mime_type": mime,
                                    "data": image_file.read(),
                                }
                            }
                        )
            else:
                file_content = load_text_attachment(filename)
                if file_content:
                    parts.append(
                        {
                            "text": f"--- File: {att['name']} ---\n{file_content}\n----------------"
                        }
                    )
                else:
                    parts.append(
                        {
                            "text": f"--- File: {att['name']} ---\nSize: {att['size']} bytes\n----------------"
                        }
                    )
        contents.append({"role": role, "parts": parts})
    return contents


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
                "messages": [
                    {"role": "system", "content": config.system_prompt},
                    *_build_openai_messages(messages),
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

    async def _generate_gemini(
        self,
        *,
        api_key: str,
        config: LLMConfig,
        messages: list[StoredMessage],
        response_format: dict[str, Any] | None = None,
    ) -> GenerationResult:
        client = genai.Client(api_key=api_key)
        contents = _build_gemini_messages(messages)

        gen_config = types.GenerateContentConfig(
            system_instruction=config.system_prompt,
            temperature=config.temperature,
            max_output_tokens=config.max_output_tokens,
        )
        if response_format:
            gen_config.response_mime_type = "application/json"
            if (
                "json_schema" in response_format
                and "schema" in response_format["json_schema"]
            ):
                gen_config.response_schema = response_format["json_schema"]["schema"]

        try:
            response = await client.aio.models.generate_content(
                model=config.model,
                contents=contents,
                config=gen_config,
            )
        except Exception as e:
            if isinstance(e, ClientError):
                raise PermanentProviderError(str(e)) from e
            if isinstance(e, APIError):
                raise TemporaryProviderError(str(e)) from e
            raise TemporaryProviderError(str(e)) from e

        usage_dict = {}
        input_tokens = None
        output_tokens = None
        if response.usage_metadata:
            usage_dict = {
                "prompt_tokens": response.usage_metadata.prompt_token_count,
                "completion_tokens": response.usage_metadata.candidates_token_count,
                "total_tokens": response.usage_metadata.total_token_count,
            }
            input_tokens = response.usage_metadata.prompt_token_count
            output_tokens = response.usage_metadata.candidates_token_count

        return GenerationResult(
            text=response.text or "",
            provider=config.provider,
            model=config.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
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
        if config.provider == "gemini":
            return await self._generate_gemini(
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
                "messages": [
                    {"role": "system", "content": config.system_prompt},
                    *_build_openai_messages(messages),
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

    async def _generate_gemini_stream(
        self,
        *,
        api_key: str,
        config: LLMConfig,
        messages: list[StoredMessage],
    ):
        client = genai.Client(api_key=api_key)
        contents = _build_gemini_messages(messages)

        gen_config = types.GenerateContentConfig(
            system_instruction=config.system_prompt,
            temperature=config.temperature,
            max_output_tokens=config.max_output_tokens,
        )

        try:
            response_stream = await client.aio.models.generate_content_stream(
                model=config.model,
                contents=contents,
                config=gen_config,
            )
            async for chunk in response_stream:
                if chunk.usage_metadata:
                    yield ProviderChunk(
                        usage={
                            "prompt_tokens": chunk.usage_metadata.prompt_token_count,
                            "completion_tokens": chunk.usage_metadata.candidates_token_count,
                            "total_tokens": chunk.usage_metadata.total_token_count,
                        }
                    )
                text = chunk.text
                if text is not None:
                    yield ProviderChunk(text=text)
        except Exception as e:
            if isinstance(e, ClientError):
                raise PermanentProviderError(str(e)) from e
            if isinstance(e, APIError):
                raise TemporaryProviderError(str(e)) from e
            raise TemporaryProviderError(str(e)) from e

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
        if config.provider == "gemini":
            async for chunk in self._generate_gemini_stream(
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
