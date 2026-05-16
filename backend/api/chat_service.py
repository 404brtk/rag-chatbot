import logging
from dataclasses import dataclass, replace
from typing import Any, Literal

import openai
import tiktoken
from asgiref.sync import sync_to_async
from openai import AsyncOpenAI

from django.utils import timezone

from .document_service import DocumentService
from .models import Conversation, UserApiKey
from .repositories import AsyncDjangoMessageRepository, StoredMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LLMConfig:
    provider: Literal["openai"]
    model: str
    system_prompt: str
    max_input_tokens: int = 12_000  # TODO: adjust
    max_output_tokens: int = 1_024  # TODO: adjust
    temperature: float = 0.2
    history_limit: int = 500  # TODO: adjust


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
    type: Literal["token", "done", "error"]
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


class TokenCounter:
    @staticmethod
    def _encoding_for_model(model: str):
        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            return tiktoken.get_encoding("cl100k_base")

    def estimate_text_tokens(self, text: str, model: str) -> int:
        enc = self._encoding_for_model(model)
        return len(enc.encode(text))

    def estimate_message_tokens(self, message: StoredMessage, model: str) -> int:
        return 3 + self.estimate_text_tokens(message.content, model)

    def estimate_system_tokens(self, system_prompt: str, model: str) -> int:
        if not system_prompt.strip():
            return 0
        return 3 + self.estimate_text_tokens(system_prompt, model)

    def truncate_text_to_max_tokens(
        self, text: str, model: str, max_tokens: int
    ) -> str:
        if max_tokens <= 0:
            return ""
        enc = self._encoding_for_model(model)
        ids = enc.encode(text)
        if len(ids) <= max_tokens:
            return text
        return enc.decode(ids[:max_tokens]).strip()


class HistoryWindow:
    def normalize(self, messages: list[StoredMessage]) -> list[StoredMessage]:
        normalized: list[StoredMessage] = []

        for msg in messages:
            content = (msg.content or "").strip()
            if not content:
                continue

            if normalized and normalized[-1].role == msg.role:
                prev = normalized[-1]
                normalized[-1] = StoredMessage(
                    role=prev.role,
                    content=f"{prev.content}\n\n{content}",
                    created_at=msg.created_at,
                    meta=prev.meta,
                )
            else:
                normalized.append(
                    StoredMessage(
                        role=msg.role,
                        content=content,
                        created_at=msg.created_at,
                        meta=msg.meta or {},
                    )
                )

        return normalized

    def fit_to_token_limit(
        self,
        *,
        system_prompt: str,
        messages: list[StoredMessage],
        model: str,
        max_input_tokens: int,
        counter: TokenCounter,
    ) -> list[StoredMessage]:
        normalized = self.normalize(messages)
        if not normalized:
            raise InvalidInputError("Empty message history.")

        running = counter.estimate_system_tokens(system_prompt, model) + 24
        kept_rev: list[StoredMessage] = []

        for msg in reversed(normalized):
            cost = counter.estimate_message_tokens(msg, model)
            if running + cost <= max_input_tokens:
                kept_rev.append(msg)
                running += cost
                continue

            if not kept_rev:
                remain = max_input_tokens - running - 6
                truncated = counter.truncate_text_to_max_tokens(
                    msg.content,
                    model=model,
                    max_tokens=max(0, remain),
                )
                if truncated:
                    kept_rev.append(
                        StoredMessage(
                            role=msg.role,
                            content=truncated,
                            created_at=msg.created_at,
                            meta={**(msg.meta or {}), "truncated_for_model": True},
                        )
                    )
            break

        kept = list(reversed(kept_rev))

        while kept and kept[0].role != "user":
            kept.pop(0)

        kept = self.normalize(kept)

        if not kept:
            raise InvalidInputError("No valid user-first history after trimming.")

        # TODO: implement compaction (summarize session instead of deleting messages from context)
        return kept


class ProviderGateway:
    async def _generate_openai(
        self,
        *,
        api_key: str,
        config: LLMConfig,
        messages: list[StoredMessage],
    ) -> GenerationResult:
        client = AsyncOpenAI(api_key=api_key, timeout=30.0, max_retries=2)
        try:
            response = await client.chat.completions.create(
                model=config.model,
                messages=[{"role": "system", "content": config.system_prompt}]
                + [{"role": m.role, "content": m.content} for m in messages],
                max_completion_tokens=config.max_output_tokens,
                temperature=config.temperature,
            )
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
            provider="openai",
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
    ) -> GenerationResult:
        if config.provider == "openai":
            return await self._generate_openai(
                api_key=api_key, config=config, messages=messages
            )
        raise PermanentProviderError(f"Unsupported provider: {config.provider}")

    async def _generate_openai_stream(
        self,
        *,
        api_key: str,
        config: LLMConfig,
        messages: list[StoredMessage],
    ):
        client = AsyncOpenAI(api_key=api_key, timeout=30.0, max_retries=2)
        try:
            stream = await client.chat.completions.create(
                model=config.model,
                messages=[{"role": "system", "content": config.system_prompt}]
                + [{"role": m.role, "content": m.content} for m in messages],
                max_completion_tokens=config.max_output_tokens,
                temperature=config.temperature,
                stream=True,
                stream_options={"include_usage": True},
            )
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
        if config.provider == "openai":
            async for chunk in self._generate_openai_stream(
                api_key=api_key, config=config, messages=messages
            ):
                yield chunk
            return
        raise PermanentProviderError(f"Unsupported provider: {config.provider}")


@dataclass(frozen=True, slots=True)
class _GenerationPrep:
    clean_user_text: str
    user_message: str
    context_chunks: list[dict[str, Any]] | None
    api_key: str
    trimmed_messages: list[StoredMessage]


class ChatService:
    def __init__(self, repository: AsyncDjangoMessageRepository | None = None) -> None:
        self.repository = repository or AsyncDjangoMessageRepository()
        self.counter = TokenCounter()
        self.window = HistoryWindow()
        self.gateway = ProviderGateway()
        self.document_service = DocumentService()

    async def _resolve_api_key(self, user, provider: str) -> str:
        try:
            key_record = await UserApiKey.objects.aget(user=user, provider=provider)
        except UserApiKey.DoesNotExist:
            raise MissingApiKeyError(
                f"No API key configured for provider '{provider}'. "
                "Please add one in your settings."
            )
        return key_record.encrypted_key

    @staticmethod
    def _format_rag_context(search_results) -> str:
        chunks = []
        for i, result in enumerate(search_results, 1):
            chunks.append(
                f"[{i}] (source: {result.document_filename}, chunk {result.chunk_index})\n"
                f"{result.chunk_content}"
            )
        return "\n\n".join(chunks)

    async def _prepare_generation(
        self,
        *,
        user,
        session_id: str,
        user_text: str,
        config: LLMConfig,
        document_ids: list[str] | None = None,
    ) -> _GenerationPrep:
        clean_user_text = (user_text or "").strip()
        if not clean_user_text:
            raise InvalidInputError("user_text cannot be empty")

        user_message = clean_user_text
        context_chunks = None

        if document_ids is not None:
            search_results = await sync_to_async(
                self.document_service.search,
                thread_sensitive=True,
            )(user=user, query=clean_user_text, document_ids=document_ids or None)
            if search_results:
                context_block = self._format_rag_context(search_results)
                user_message = f"<CONTEXT>\n{context_block}\n</CONTEXT>\n\n<QUESTION>\n{clean_user_text}\n</QUESTION>"
                context_chunks = [
                    {
                        "index": i,
                        "content": r.chunk_content,
                        "document_id": r.document_id,
                        "document_filename": r.document_filename,
                        "chunk_index": r.chunk_index,
                        "distance": r.distance,
                    }
                    for i, r in enumerate(search_results, 1)
                ]

        api_key = await self._resolve_api_key(user, config.provider)

        history = await self.repository.list_messages(
            session_id=session_id, limit=config.history_limit
        )
        candidate_messages = [
            *history,
            StoredMessage(role="user", content=user_message),
        ]

        trimmed = self.window.fit_to_token_limit(
            system_prompt=config.system_prompt,
            messages=candidate_messages,
            model=config.model,
            max_input_tokens=config.max_input_tokens,
            counter=self.counter,
        )

        return _GenerationPrep(
            clean_user_text=clean_user_text,
            user_message=user_message,
            context_chunks=context_chunks,
            api_key=api_key,
            trimmed_messages=trimmed,
        )

    @staticmethod
    def _build_user_meta(
        clean_user_text: str,
        config: LLMConfig,
        context_chunks: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "raw_question": clean_user_text,
            "provider_selected": config.provider,
            "model_selected": config.model,
        }
        if context_chunks:
            meta["context_chunks"] = context_chunks
        return meta

    @staticmethod
    def _compute_title(user_text: str) -> str:
        stripped = user_text.strip()
        if len(stripped) <= 50:
            return stripped
        truncated = stripped[:50]
        if " " in truncated:
            truncated = truncated.rsplit(" ", 1)[0]
        return truncated + "..."

    async def generate_reply(
        self,
        *,
        user,
        session_id: str,
        user_text: str,
        config: LLMConfig,
        document_ids: list[str] | None = None,
    ) -> GenerationResult:
        prep = await self._prepare_generation(
            user=user,
            session_id=session_id,
            user_text=user_text,
            config=config,
            document_ids=document_ids,
        )

        try:
            result = await self.gateway.generate(
                api_key=prep.api_key, config=config, messages=prep.trimmed_messages
            )
        except ChatServiceError:
            logger.exception(
                "LLM generation failed",
                extra={
                    "session_id": str(session_id),
                    "provider": config.provider,
                    "model": config.model,
                },
            )
            raise

        user_meta = self._build_user_meta(
            prep.clean_user_text, config, prep.context_chunks
        )

        user_msg, assistant_msg = await self.repository.append_message_pair(
            session_id=session_id,
            user_content=prep.user_message,
            assistant_content=result.text,
            provider=result.provider,
            model=result.model,
            usage=result.usage,
            user_meta=user_meta,
            assistant_meta={
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "model_input_message_count": len(result.model_input),
            },
        )

        return replace(
            result,
            user_message_id=str(user_msg.id),
            assistant_message_id=str(assistant_msg.id),
        )

    async def generate_reply_stream(
        self,
        *,
        user,
        session_id: str,
        user_text: str,
        config: LLMConfig,
        document_ids: list[str] | None = None,
    ):
        try:
            prep = await self._prepare_generation(
                user=user,
                session_id=session_id,
                user_text=user_text,
                config=config,
                document_ids=document_ids,
            )

            session = await Conversation.objects.aget(id=session_id)

            user_meta = self._build_user_meta(
                prep.clean_user_text, config, prep.context_chunks
            )

            await self.repository.append_message(
                session=session,
                role="user",
                content=prep.user_message,
                provider=None,
                model=None,
                usage=None,
                meta=user_meta,
            )

            assistant_text = ""
            usage_data = None
            async for chunk in self.gateway.generate_stream(
                api_key=prep.api_key, config=config, messages=prep.trimmed_messages
            ):
                if chunk.text:
                    assistant_text += chunk.text
                    yield StreamEvent(type="token", content=chunk.text)
                if chunk.usage:
                    usage_data = chunk.usage

            if usage_data is None:
                usage_data = {
                    "prompt_tokens": self.counter.estimate_system_tokens(
                        config.system_prompt, config.model
                    )
                    + sum(
                        self.counter.estimate_message_tokens(m, config.model)
                        for m in prep.trimmed_messages
                    ),
                    "completion_tokens": self.counter.estimate_text_tokens(
                        assistant_text, config.model
                    ),
                }

            assistant_msg = await self.repository.append_message(
                session=session,
                role="assistant",
                content=assistant_text,
                provider=config.provider,
                model=config.model,
                usage=usage_data,
                meta={
                    "input_tokens": usage_data.get("prompt_tokens"),
                    "output_tokens": usage_data.get("completion_tokens"),
                    "model_input_message_count": len(prep.trimmed_messages),
                },
            )

            title = None
            if not session.title:
                title = self._compute_title(prep.clean_user_text)
                session.title = title

            session.last_message_at = timezone.now()
            fields = ["last_message_at"]
            if title:
                fields.append("title")
            await session.asave(update_fields=fields)

            yield StreamEvent(
                type="done",
                message_id=str(assistant_msg.id),
                title=title,
                usage=usage_data,
                provider=config.provider,
                model=config.model,
            )

        except ChatServiceError as e:
            code_map = {
                InvalidInputError: "invalid_input",
                MissingApiKeyError: "missing_api_key",
                TemporaryProviderError: "provider_temporary",
                PermanentProviderError: "provider_permanent",
            }
            yield StreamEvent(
                type="error",
                error_message=str(e),
                error_code=code_map.get(type(e), "unknown"),
            )
        except Exception:
            logger.exception("Unexpected error in generate_reply_stream")
            yield StreamEvent(
                type="error",
                error_message="Internal server error",
                error_code="internal_error",
            )
