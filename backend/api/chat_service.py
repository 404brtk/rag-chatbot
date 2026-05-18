import logging
import time
from dataclasses import dataclass, replace
from typing import Any, Literal

import httpx
import openai
import tiktoken
from asgiref.sync import sync_to_async
from openai import AsyncOpenAI

from django.conf import settings
from django.utils import timezone

from .document_service import DocumentService
from .models import Conversation, UserApiKey
from .repositories import AsyncDjangoMessageRepository, StoredMessage

logger = logging.getLogger(__name__)


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
    ) -> GenerationResult:
        client = self._build_client(api_key=api_key, provider=config.provider)
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
    ) -> GenerationResult:
        if config.provider in {"openai", "llamacpp"}:
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
        client = self._build_client(api_key=api_key, provider=config.provider)
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
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base}/props")
            resp.raise_for_status()
            n_ctx = resp.json()["default_generation_settings"]["n_ctx"]

        ProviderGateway._llamacpp_context = n_ctx
        ProviderGateway._llamacpp_context_fetched_at = now
        logger.info(f"Discovered llama.cpp context window: {n_ctx} tokens")
        return n_ctx

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
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base}/v1/models")
            resp.raise_for_status()
            data = resp.json().get("data", [])

        ProviderGateway._llamacpp_models = data
        ProviderGateway._llamacpp_models_fetched_at = now
        logger.info(f"Discovered {len(data)} llama.cpp model(s)")
        return data


@dataclass(frozen=True, slots=True)
class _GenerationPrep:
    clean_user_text: str
    user_message: str
    context_chunks: list[dict[str, Any]] | None
    api_key: str
    messages: list[StoredMessage]
    session: Conversation
    compaction_summary: str | None = None
    compaction_message_id: str | None = None
    compaction_tokens: list[str] | None = None
    compaction_usage: dict[str, Any] | None = None


class CompactionService:
    def __init__(self, counter: TokenCounter, gateway: ProviderGateway) -> None:
        self.counter = counter
        self.gateway = gateway

    def _format_history_for_summary(self, history: list[StoredMessage]) -> str:
        lines = []
        for msg in history:
            label = "User" if msg.role == "user" else "Assistant"
            lines.append(f"{label}: {msg.content}")
        return "\n\n".join(lines)

    def _build_summarization_prompt(self, history: list[StoredMessage]) -> str:
        formatted_history = self._format_history_for_summary(history)
        return (
            f"Recent conversation:\n{formatted_history}\n\n"
            "Create a concise but comprehensive summary of this conversation. "
            "Preserve all key facts, decisions, user requirements, and important context. "
            "The summary should be complete enough that someone reading it would understand "
            "everything that was discussed and decided."
        )

    def _build_summary_config(self, model: str, provider: str) -> LLMConfig:
        return LLMConfig(
            provider=provider,
            model=model,
            system_prompt="You are a conversation summarizer.",
            max_output_tokens=1_024,
        )

    async def _call_summarizer(
        self,
        history: list[StoredMessage],
        model: str,
        api_key: str,
        provider: str,
    ) -> str | None:
        chunks: list[str] = []
        async for chunk in self._call_summarizer_stream(
            history, model, api_key, provider
        ):
            if chunk.text:
                chunks.append(chunk.text)
        return "".join(chunks).strip()

    async def _call_summarizer_stream(
        self,
        history: list[StoredMessage],
        model: str,
        api_key: str,
        provider: str,
    ):
        summarization_prompt = self._build_summarization_prompt(history)
        summary_config = self._build_summary_config(model, provider)

        async for chunk in self.gateway.generate_stream(
            api_key=api_key,
            config=summary_config,
            messages=[StoredMessage(role="user", content=summarization_prompt)],
        ):
            yield chunk

    @staticmethod
    def _dedup_models(config: LLMConfig) -> list[str]:
        models = []
        for m in (config.compaction_model, config.model):
            if m not in models:
                models.append(m)
        return models

    async def _summarize_with_llm(
        self,
        history: list[StoredMessage],
        config: LLMConfig,
        api_key: str,
    ) -> str | None:
        models = CompactionService._dedup_models(config)
        for model in models:
            try:
                summary = await self._call_summarizer(
                    history, model, api_key, config.provider
                )
                if summary:
                    return summary
            except (TemporaryProviderError, PermanentProviderError) as e:
                logger.warning(f"Compaction summarizer failed for model {model}: {e}")
                continue
        return None

    async def compact(
        self,
        history: list[StoredMessage],
        config: LLMConfig,
        api_key: str,
    ) -> str | None:
        return await self._summarize_with_llm(history, config, api_key)

    async def compact_stream(
        self,
        history: list[StoredMessage],
        config: LLMConfig,
        api_key: str,
    ):
        models = self._dedup_models(config)
        for model in models:
            collected: list[ProviderChunk] = []
            try:
                async for chunk in self._call_summarizer_stream(
                    history, model, api_key, config.provider
                ):
                    collected.append(chunk)
            except (TemporaryProviderError, PermanentProviderError) as e:
                logger.warning(f"Compaction summarizer failed for model {model}: {e}")
                continue
            for chunk in collected:
                yield chunk
            return

    def should_compact(
        self,
        system_prompt: str,
        history: list[StoredMessage],
        new_message: StoredMessage,
        config: LLMConfig,
    ) -> bool:
        system_tokens = self.counter.estimate_system_tokens(system_prompt, config.model)
        history_tokens = sum(
            self.counter.estimate_message_tokens(m, config.model) for m in history
        )
        new_tokens = self.counter.estimate_message_tokens(new_message, config.model)
        total = system_tokens + history_tokens + new_tokens + 24
        threshold = int(config.max_input_tokens * config.compaction_threshold)
        return total > threshold

    def chunk_truncate(
        self,
        *,
        history: list[StoredMessage],
        new_message: StoredMessage,
        system_prompt: str,
        config: LLMConfig,
    ) -> list[StoredMessage]:
        while len(history) > 1 and self.should_compact(
            system_prompt=system_prompt,
            history=history,
            new_message=new_message,
            config=config,
        ):
            history = history[len(history) // 2 :]
        return history


class ChatService:
    def __init__(self, repository: AsyncDjangoMessageRepository | None = None) -> None:
        self.repository = repository or AsyncDjangoMessageRepository()
        self.counter = TokenCounter()
        self.gateway = ProviderGateway()
        self.document_service = DocumentService()
        self.compaction = CompactionService(self.counter, self.gateway)

    async def _resolve_api_key(self, user, provider: str) -> str:
        if provider == "llamacpp":
            return "llamacpp"
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

        if config.provider == "llamacpp":
            n_ctx = await ProviderGateway.discover_llamacpp_context()
            if config.max_input_tokens > n_ctx:
                config = replace(config, max_input_tokens=n_ctx)

        session = await Conversation.objects.aget(id=session_id)

        history = await self.repository.list_messages(
            session_id=session_id, limit=config.history_limit, exclude_compacted=True
        )
        new_msg = StoredMessage(role="user", content=user_message)

        compaction_summary = None
        compaction_msg_id = None
        compaction_tokens = None
        compaction_usage = None

        if self.compaction.should_compact(
            system_prompt=config.system_prompt,
            history=history,
            new_message=new_msg,
            config=config,
        ):
            logger.debug(
                f"Compaction triggered - max_input_tokens={config.max_input_tokens} threshold={config.compaction_threshold:.2f} history_len={len(history)}"
            )
            tokens: list[str] = []
            summary_usage = None
            full_text = ""
            async for chunk in self.compaction.compact_stream(
                history=history,
                config=config,
                api_key=api_key,
            ):
                if chunk.text:
                    tokens.append(chunk.text)
                    full_text += chunk.text
                if chunk.usage:
                    summary_usage = chunk.usage
            summary = full_text.strip()
            if summary:
                compaction_msg = await self.repository.apply_compaction(
                    session=session,
                    summary=summary,
                    provider=config.provider,
                    model=config.model,
                    usage=summary_usage,
                )
                compaction_summary = summary
                compaction_msg_id = str(compaction_msg.id)
                compaction_tokens = tokens
                compaction_usage = summary_usage
                history = await self.repository.list_messages(
                    session_id=session_id,
                    limit=config.history_limit,
                    exclude_compacted=True,
                )
                logger.debug(
                    f"Compaction completed - summary_len={len(summary)} tokens={len(tokens)}"
                )
            else:
                original_count = len(history)
                history = self.compaction.chunk_truncate(
                    history=history,
                    new_message=new_msg,
                    system_prompt=config.system_prompt,
                    config=config,
                )
                logger.warning(
                    "Compaction summarization produced no output — fell back to chunk_truncate (kept %d/%d)",
                    len(history),
                    original_count,
                )

        return _GenerationPrep(
            clean_user_text=clean_user_text,
            user_message=user_message,
            context_chunks=context_chunks,
            api_key=api_key,
            messages=[*history, new_msg],
            session=session,
            compaction_summary=compaction_summary,
            compaction_message_id=compaction_msg_id,
            compaction_tokens=compaction_tokens,
            compaction_usage=compaction_usage,
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
                api_key=prep.api_key, config=config, messages=prep.messages
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

            if prep.compaction_tokens:
                for token in prep.compaction_tokens:
                    yield StreamEvent(type="token", content=token)
                yield StreamEvent(
                    type="compaction_done",
                    message_id=prep.compaction_message_id,
                    usage=prep.compaction_usage,
                )

            session = prep.session

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
                api_key=prep.api_key, config=config, messages=prep.messages
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
                        for m in prep.messages
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
                    "model_input_message_count": len(prep.messages),
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

    @staticmethod
    async def get_available_models() -> dict[str, list[str]]:
        openai_models = list(getattr(settings, "OPENAI_MODELS", []))
        llamacpp_models: list[str] = []
        try:
            raw = await ProviderGateway.discover_llamacpp_models()
            llamacpp_models = [m["id"] for m in raw]
        except Exception:
            logger.warning("Failed to discover llama.cpp models")
        return {"openai": openai_models, "llamacpp": llamacpp_models}
