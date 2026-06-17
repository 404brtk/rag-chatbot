import asyncio
import logging
from dataclasses import dataclass, replace
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict

from django.conf import settings
from django.utils import timezone
from django.core.files.storage import default_storage

from .attachments import is_safe_attachment_path

from core.exceptions import (
    ChatServiceError,
    InvalidInputError,
    MissingApiKeyError,
    TemporaryProviderError,
    PermanentProviderError,
)
from .llm_config import (
    LLMConfig,
    GenerationResult,
    StreamEvent,
)
from .provider_gateway import ProviderGateway
from .compaction_service import CompactionService
from documents.document_service import DocumentService
from .token_counter import TokenCounter
from .models import Conversation
from accounts.models import UserApiKey
from .repositories import AsyncDjangoMessageRepository, StoredMessage

logger = logging.getLogger(__name__)


class QueryRefinementSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detected_language: Literal["polish", "english"] = Field(
        description="The primary language of the user's query"
    )
    refined_english_query: str = Field(description="Optimized query in English")
    refined_polish_query: str = Field(description="Optimized query in Polish")


@dataclass(frozen=True, slots=True)
class _GenerationPrep:
    raw_user_text: str
    user_message: str
    context_chunks: list[dict[str, Any]] | None
    api_key: str
    messages: list[StoredMessage]
    session: Conversation
    config: LLMConfig
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

    @staticmethod
    def _cleanup_attachments(attachments: list[dict] | None) -> None:
        if not attachments:
            return
        for att in attachments:
            filename = att.get("id")
            if filename and is_safe_attachment_path(filename):
                try:
                    default_storage.delete(f"attachments/{filename}")
                except Exception:
                    pass

    async def _refine_query(
        self,
        user,
        query: str,
        config: LLMConfig,
        api_key: str,
    ) -> dict[str, str]:
        system_prompt = (
            "You are a highly efficient search query translation and refinement assistant.\n"
            "Your task is to analyze a raw user query, detect its primary language (Polish or English), "
            "and output an optimized version of this query for both languages.\n\n"
            "Follow these strict guidelines for refinement:\n"
            '1. Language Detection: Detect if the input query is primarily in "polish" or "english".\n'
            "2. Typos & Grammar: Correct any typos, spelling errors, or grammatical issues in both outputs.\n"
            "3. Keyword Expansion & Synonyms:\n"
            "   - Expand the query naturally using relevant synonyms or search keywords.\n"
            "   - Keep the expanded query concise and highly focused on the user's search intent.\n"
            '   - Avoid "query drift" (do not add unrelated tech terms or generic categories that shift the original meaning).\n'
            '4. Preserve Jargon and Brands: Keep proper nouns, brand names, product models (e.g., "iPhone 15", "Kubernetes"), '
            "and domain-specific jargon intact in both languages.\n"
            "5. Translation:\n"
            "   - Translate the core intent of the query accurately.\n"
            "   - Ensure 'refined_english_query' sounds natural to native English searchers.\n"
            "   - Ensure 'refined_polish_query' sounds natural to native Polish searchers (handling proper Polish search terms)."
        )

        refine_config = replace(
            config,
            system_prompt=system_prompt,
            max_output_tokens=512,
            temperature=0.1,
        )

        refine_message = StoredMessage(role="user", content=query)

        try:
            res = await self.gateway.generate(
                api_key=api_key,
                config=refine_config,
                messages=[refine_message],
                response_schema=QueryRefinementSchema,
            )
            text = res.text.strip()
            refined_data = QueryRefinementSchema.model_validate_json(text)

            return {
                "detected_language": refined_data.detected_language,
                "refined_english_query": refined_data.refined_english_query.strip(),
                "refined_polish_query": refined_data.refined_polish_query.strip(),
            }
        except Exception as e:
            logger.warning(f"Query refinement failed, falling back to raw query: {e}")
            return {
                "detected_language": "english",
                "refined_english_query": query,
                "refined_polish_query": query,
            }

    async def _prepare_generation(
        self,
        *,
        user,
        session_id: str,
        user_text: str,
        config: LLMConfig,
        document_ids: list[str] | None = None,
        attachments: list[dict] | None = None,
        variant: str | None = None,
    ):
        raw_user_text = (user_text or "").strip()
        if not raw_user_text:
            raise InvalidInputError("user_text cannot be empty")

        api_key = await self._resolve_api_key(user, config.provider)
        compaction_api_key = await self._resolve_api_key(
            user, config.compaction_provider
        )

        user_message = raw_user_text
        context_chunks = None

        if document_ids is not None and raw_user_text:
            refinement = await self._refine_query(
                user=user,
                query=raw_user_text,
                config=config,
                api_key=api_key,
            )
            detected_language = refinement["detected_language"]
            refined_english = refinement["refined_english_query"]
            refined_polish = refinement["refined_polish_query"]

            logger.debug(
                f"Query refined - original='{raw_user_text}' detected_language={detected_language} "
                f"refined_english='{refined_english}' refined_polish='{refined_polish}'"
            )

            search_results = await self.document_service.search(
                user=user,
                query=raw_user_text,
                refined_english_query=refined_english,
                refined_polish_query=refined_polish,
                document_ids=document_ids or None,
            )
            if search_results:
                context_block = self._format_rag_context(search_results)
                user_message = f"<CONTEXT>\n{context_block}\n</CONTEXT>\n\n<QUESTION>\n{raw_user_text}\n</QUESTION>"
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

        if config.provider == "llamacpp":
            n_ctx = await ProviderGateway.discover_llamacpp_context()
            if config.max_input_tokens > n_ctx:
                config = replace(config, max_input_tokens=n_ctx)

        session = await Conversation.objects.aget(id=session_id)

        history = await self.repository.list_messages(
            session_id=session_id,
            limit=config.history_limit,
            exclude_compacted=True,
            variant=variant,
        )

        stored_attachments = []
        if attachments:
            stored_attachments = [
                {
                    "id": att["id"],
                    "name": att["name"],
                    "size": att["size"],
                    "mimeType": att["mimeType"],
                    "saved_path": f"attachments/{att['id']}",
                }
                for att in attachments
            ]

        new_msg = StoredMessage(
            role="user",
            content=user_message,
            attachments=stored_attachments,
        )

        compaction_summary = None
        compaction_msg_id = None
        compaction_tokens = None
        compaction_usage = None

        if session.mode == Conversation.Mode.SIDE_BY_SIDE:
            logger.debug(
                f"Side-by-side mode - evaluating in-memory truncation (history_len={len(history)}, variant={variant})"
            )
            history = self.compaction.chunk_truncate(
                history=history,
                new_message=new_msg,
                system_prompt=config.system_prompt,
                config=config,
            )
        elif self.compaction.should_compact(
            system_prompt=config.system_prompt,
            history=history,
            new_message=new_msg,
            config=config,
        ):
            if config.compaction_enabled:
                logger.debug(
                    f"Compaction triggered - max_input_tokens={config.max_input_tokens} threshold={config.compaction_threshold:.2f} history_len={len(history)}"
                )
            summary = ""
            tokens: list[str] = []
            summary_usage = None
            if config.compaction_enabled:
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
                    variant=variant,
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
                discarded_count = original_count - len(history)
                if discarded_count > 0:
                    await self.repository.truncate_oldest_messages(
                        session_id=session_id,
                        count=discarded_count,
                    )
                logger.warning(
                    f"Compaction summarization produced no output or was disabled - fell back to chunk_truncate (kept {len(history)}/{original_count})",
                )

        system_tokens = self.counter.estimate_system_tokens(
            config.system_prompt, config.model
        )
        history_tokens = sum(
            self.counter.estimate_message_tokens(m, config.model) for m in history
        )
        new_msg_tokens = self.counter.estimate_message_tokens(new_msg, config.model)
        total_prompt_tokens = system_tokens + history_tokens + new_msg_tokens + 24
        remaining_tokens = config.max_input_tokens - total_prompt_tokens

        if remaining_tokens < 100:
            raise InvalidInputError(
                f"The message is too long for the model's context window. "
                f"Estimated prompt tokens: {total_prompt_tokens}, limit: {config.max_input_tokens}. "
                f"Please reduce your message length or attachment size."
            )

        dynamic_max_output = max(
            16, min(config.max_output_tokens, remaining_tokens - 50)
        )
        if dynamic_max_output < config.max_output_tokens:
            config = replace(config, max_output_tokens=dynamic_max_output)
            logger.debug(
                f"Dynamically adjusted max_output_tokens to {dynamic_max_output} to fit context headroom."
            )

        return _GenerationPrep(
            raw_user_text=raw_user_text,
            user_message=user_message,
            context_chunks=context_chunks,
            api_key=api_key,
            messages=[*history, new_msg],
            session=session,
            config=config,
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
        attachments: list[dict] | None = None,
    ) -> GenerationResult:
        try:
            prep = await self._prepare_generation(
                user=user,
                session_id=session_id,
                user_text=user_text,
                config=config,
                document_ids=document_ids,
                attachments=attachments,
            )

            result = await self.gateway.generate(
                api_key=prep.api_key, config=prep.config, messages=prep.messages
            )

            user_msg, assistant_msg = await self.repository.append_message_pair(
                session_id=session_id,
                user_content=prep.user_message,
                assistant_content=result.text,
                provider=result.provider,
                model=result.model,
                usage=result.usage,
                user_raw_question=prep.raw_user_text,
                user_context=prep.context_chunks,
                user_attachments=attachments,
            )

            return replace(
                result,
                user_message_id=str(user_msg.id),
                assistant_message_id=str(assistant_msg.id),
            )
        except Exception as e:
            self._cleanup_attachments(attachments)
            if not isinstance(e, ChatServiceError):
                logger.exception(
                    "Unexpected error in generate_reply",
                    extra={
                        "session_id": str(session_id),
                        "provider": config.provider,
                        "model": config.model,
                    },
                )
            raise

    async def generate_reply_stream(
        self,
        *,
        user,
        session_id: str,
        user_text: str,
        config: LLMConfig,
        document_ids: list[str] | None = None,
        attachments: list[dict] | None = None,
    ):
        session = None
        user_msg = None
        assistant_text = ""
        usage_data = None
        prep = None
        try:
            raw_user_text = (user_text or "").strip()
            if not raw_user_text:
                raise InvalidInputError("user_text cannot be empty")

            session = await Conversation.objects.aget(id=session_id)

            if session.mode == Conversation.Mode.SIDE_BY_SIDE:
                prep_on = None
                prep_off = None
                user_msg = None
                assistant_text_on = ""
                assistant_text_off = ""
                usage_data_on = None
                usage_data_off = None
                assistant_msg_on = None

                try:
                    prep_on = await self._prepare_generation(
                        user=user,
                        session_id=session_id,
                        user_text=user_text,
                        config=config,
                        document_ids=document_ids,
                        attachments=attachments,
                        variant="rag_on",
                    )

                    prep_off = await self._prepare_generation(
                        user=user,
                        session_id=session_id,
                        user_text=user_text,
                        config=config,
                        document_ids=None,
                        attachments=attachments,
                        variant="rag_off",
                    )

                    user_msg = await self.repository.append_message(
                        session=session,
                        role="user",
                        content=prep_on.user_message,
                        provider=config.provider,
                        model=config.model,
                        raw_question=prep_on.raw_user_text,
                        context=prep_on.context_chunks,
                        attachments=attachments,
                    )

                    async for chunk in self.gateway.generate_stream(
                        api_key=prep_on.api_key,
                        config=prep_on.config,
                        messages=prep_on.messages,
                    ):
                        if chunk.text:
                            assistant_text_on += chunk.text
                            yield StreamEvent(
                                type="token", content=chunk.text, variant="rag_on"
                            )
                        if chunk.usage:
                            usage_data_on = chunk.usage

                    if usage_data_on is None:
                        usage_data_on = {
                            "prompt_tokens": self.counter.estimate_system_tokens(
                                prep_on.config.system_prompt, prep_on.config.model
                            )
                            + sum(
                                self.counter.estimate_message_tokens(
                                    m, prep_on.config.model
                                )
                                for m in prep_on.messages
                            ),
                            "completion_tokens": self.counter.estimate_text_tokens(
                                assistant_text_on, prep_on.config.model
                            ),
                        }

                    assistant_msg_on = await self.repository.append_message(
                        session=session,
                        role="assistant",
                        content=assistant_text_on,
                        provider=prep_on.config.provider,
                        model=prep_on.config.model,
                        usage=usage_data_on,
                        variant="rag_on",
                    )

                    async for chunk in self.gateway.generate_stream(
                        api_key=prep_off.api_key,
                        config=prep_off.config,
                        messages=prep_off.messages,
                    ):
                        if chunk.text:
                            assistant_text_off += chunk.text
                            yield StreamEvent(
                                type="token", content=chunk.text, variant="rag_off"
                            )
                        if chunk.usage:
                            usage_data_off = chunk.usage

                    if usage_data_off is None:
                        usage_data_off = {
                            "prompt_tokens": self.counter.estimate_system_tokens(
                                prep_off.config.system_prompt, prep_off.config.model
                            )
                            + sum(
                                self.counter.estimate_message_tokens(
                                    m, prep_off.config.model
                                )
                                for m in prep_off.messages
                            ),
                            "completion_tokens": self.counter.estimate_text_tokens(
                                assistant_text_off, prep_off.config.model
                            ),
                        }

                    await self.repository.append_message(
                        session=session,
                        role="assistant",
                        content=assistant_text_off,
                        provider=prep_off.config.provider,
                        model=prep_off.config.model,
                        usage=usage_data_off,
                        variant="rag_off",
                    )

                    title = None
                    if not session.title:
                        title = self._compute_title(prep_on.raw_user_text)
                        session.title = title
                    session.last_message_at = timezone.now()
                    fields = ["last_message_at"]
                    if title:
                        fields.append("title")
                    await session.asave(update_fields=fields)

                    yield StreamEvent(
                        type="done",
                        message_id=str(assistant_msg_on.id),
                        title=title,
                        usage=usage_data_on,
                        provider=config.provider,
                        model=config.model,
                    )
                    return

                except asyncio.CancelledError:
                    if user_msg:
                        if not assistant_msg_on:
                            if not assistant_text_on:
                                assistant_text_on = "*Generation stopped.*"
                            if usage_data_on is None:
                                try:
                                    usage_data_on = {
                                        "prompt_tokens": self.counter.estimate_system_tokens(
                                            prep_on.config.system_prompt,
                                            prep_on.config.model,
                                        )
                                        + sum(
                                            self.counter.estimate_message_tokens(
                                                m, prep_on.config.model
                                            )
                                            for m in prep_on.messages
                                        ),
                                        "completion_tokens": self.counter.estimate_text_tokens(
                                            assistant_text_on, prep_on.config.model
                                        ),
                                    }
                                except Exception:
                                    usage_data_on = {
                                        "prompt_tokens": 0,
                                        "completion_tokens": 0,
                                    }
                            try:
                                await self.repository.append_message(
                                    session=session,
                                    role="assistant",
                                    content=assistant_text_on,
                                    provider=prep_on.config.provider,
                                    model=prep_on.config.model,
                                    usage=usage_data_on,
                                    variant="rag_on",
                                )
                            except Exception:
                                pass

                        if not assistant_text_off:
                            assistant_text_off = "*Generation stopped.*"
                        if usage_data_off is None:
                            try:
                                usage_data_off = {
                                    "prompt_tokens": self.counter.estimate_system_tokens(
                                        prep_off.config.system_prompt,
                                        prep_off.config.model,
                                    )
                                    + sum(
                                        self.counter.estimate_message_tokens(
                                            m, prep_off.config.model
                                        )
                                        for m in prep_off.messages
                                    ),
                                    "completion_tokens": self.counter.estimate_text_tokens(
                                        assistant_text_off, prep_off.config.model
                                    ),
                                }
                            except Exception:
                                usage_data_off = {
                                    "prompt_tokens": 0,
                                    "completion_tokens": 0,
                                }
                        try:
                            await self.repository.append_message(
                                session=session,
                                role="assistant",
                                content=assistant_text_off,
                                provider=prep_off.config.provider,
                                model=prep_off.config.model,
                                usage=usage_data_off,
                                variant="rag_off",
                            )
                        except Exception:
                            pass

                        try:
                            session.last_message_at = timezone.now()
                            await session.asave(update_fields=["last_message_at"])
                        except Exception:
                            pass
                    raise

            prep = await self._prepare_generation(
                user=user,
                session_id=session_id,
                user_text=user_text,
                config=config,
                document_ids=document_ids,
                attachments=attachments,
            )

            if prep.compaction_summary:
                yield StreamEvent(
                    type="compaction_done",
                    message_id=prep.compaction_message_id,
                    usage=prep.compaction_usage,
                )

            session = prep.session

            user_msg = await self.repository.append_message(
                session=session,
                role="user",
                content=prep.user_message,
                provider=prep.config.provider,
                model=prep.config.model,
                raw_question=prep.raw_user_text,
                context=prep.context_chunks,
                attachments=attachments,
            )

            try:
                async for chunk in self.gateway.generate_stream(
                    api_key=prep.api_key, config=prep.config, messages=prep.messages
                ):
                    if chunk.text:
                        assistant_text += chunk.text
                        yield StreamEvent(type="token", content=chunk.text)
                    if chunk.usage:
                        usage_data = chunk.usage
            except Exception:
                await user_msg.adelete()
                raise

            if usage_data is None:
                usage_data = {
                    "prompt_tokens": self.counter.estimate_system_tokens(
                        prep.config.system_prompt, prep.config.model
                    )
                    + sum(
                        self.counter.estimate_message_tokens(m, prep.config.model)
                        for m in prep.messages
                    ),
                    "completion_tokens": self.counter.estimate_text_tokens(
                        assistant_text, prep.config.model
                    ),
                }

            assistant_msg = await self.repository.append_message(
                session=session,
                role="assistant",
                content=assistant_text,
                provider=prep.config.provider,
                model=prep.config.model,
                usage=usage_data,
            )

            title = None
            if not session.title:
                title = self._compute_title(prep.raw_user_text)
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

        except asyncio.CancelledError:
            if session and session.mode == Conversation.Mode.SIDE_BY_SIDE:
                raise
            if not session:
                try:
                    session = await Conversation.objects.aget(id=session_id)
                except Exception:
                    pass
            if session:
                if not user_msg:
                    try:
                        user_msg = await self.repository.append_message(
                            session=session,
                            role="user",
                            content=user_text,
                            provider=config.provider,
                            model=config.model,
                            raw_question=user_text,
                            attachments=attachments,
                        )
                    except Exception:
                        pass
                if user_msg:
                    if not assistant_text:
                        assistant_text = "*Generation stopped.*"
                    if usage_data is None:
                        try:
                            usage_data = {
                                "prompt_tokens": self.counter.estimate_system_tokens(
                                    config.system_prompt, config.model
                                )
                                + sum(
                                    self.counter.estimate_message_tokens(
                                        m, config.model
                                    )
                                    for m in (prep.messages if prep else [])
                                ),
                                "completion_tokens": self.counter.estimate_text_tokens(
                                    assistant_text, config.model
                                ),
                            }
                        except Exception:
                            usage_data = {"prompt_tokens": 0, "completion_tokens": 0}
                    try:
                        await self.repository.append_message(
                            session=session,
                            role="assistant",
                            content=assistant_text,
                            provider=config.provider,
                            model=config.model,
                            usage=usage_data,
                        )
                        session.last_message_at = timezone.now()
                        await session.asave(update_fields=["last_message_at"])
                    except Exception:
                        pass
            raise

        except ChatServiceError as e:
            self._cleanup_attachments(attachments)
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
            self._cleanup_attachments(attachments)
            logger.exception("Unexpected error in generate_reply_stream")
            yield StreamEvent(
                type="error",
                error_message="Internal server error",
                error_code="internal_error",
            )

    @staticmethod
    async def get_available_models() -> dict[str, list[str]]:
        models: dict[str, list[str]] = {}

        openai_models = list(getattr(settings, "OPENAI_MODELS", []))
        if openai_models:
            models["openai"] = openai_models

        gemini_models = list(getattr(settings, "GEMINI_MODELS", []))
        if gemini_models:
            models["gemini"] = gemini_models

        try:
            raw = await ProviderGateway.discover_llamacpp_models()
            llamacpp_models = [m["id"] for m in raw]
            if llamacpp_models:
                models["llamacpp"] = llamacpp_models
        except Exception:
            logger.warning("Failed to discover llama.cpp models")

        return models
