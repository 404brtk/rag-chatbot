import logging
from dataclasses import dataclass, replace
from typing import Any

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

from .llm_config import (
    LLMConfig,
    GenerationResult,
    StreamEvent,
    ChatServiceError,
    InvalidInputError,
    MissingApiKeyError,
    TemporaryProviderError,
    PermanentProviderError,
)
from .provider_gateway import ProviderGateway
from .compaction_service import CompactionService
from .document_service import DocumentService
from .token_counter import TokenCounter
from .models import Conversation, UserApiKey
from .repositories import AsyncDjangoMessageRepository, StoredMessage

logger = logging.getLogger(__name__)


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
    ):
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
                        "score": r.score,
                    }
                    for i, r in enumerate(search_results, 1)
                ]

        api_key = await self._resolve_api_key(user, config.provider)
        compaction_api_key = await self._resolve_api_key(
            user, config.compaction_provider
        )

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
                compaction_api_key=compaction_api_key,
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
                    provider=config.compaction_provider,
                    model=config.compaction_model,
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
                    f"Compaction summarization produced no output - fell back to chunk_truncate (kept {len(history)}/{original_count})",
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

        user_msg, assistant_msg = await self.repository.append_message_pair(
            session_id=session_id,
            user_content=prep.user_message,
            assistant_content=result.text,
            provider=result.provider,
            model=result.model,
            usage=result.usage,
            user_raw_question=prep.clean_user_text,
            user_context=prep.context_chunks,
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

            await self.repository.append_message(
                session=session,
                role="user",
                content=prep.user_message,
                provider=config.provider,
                model=config.model,
                raw_question=prep.clean_user_text,
                context=prep.context_chunks,
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
                sent_messages=[
                    {"role": m.role, "content": m.content} for m in prep.messages
                ],
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
