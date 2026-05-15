import logging
from dataclasses import dataclass, replace
from typing import Any, Literal

import openai
import tiktoken
from openai import OpenAI

from .document_service import DocumentService
from .models import UserApiKey
from .repositories import DjangoMessageRepository, StoredMessage

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
    def _generate_openai(
        self,
        *,
        api_key: str,
        config: LLMConfig,
        messages: list[StoredMessage],
    ) -> GenerationResult:
        client = OpenAI(api_key=api_key, timeout=30.0, max_retries=2)
        try:
            response = client.chat.completions.create(
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

    def generate(
        self,
        *,
        api_key: str,
        config: LLMConfig,
        messages: list[StoredMessage],
    ) -> GenerationResult:
        if config.provider == "openai":
            return self._generate_openai(
                api_key=api_key, config=config, messages=messages
            )
        raise PermanentProviderError(f"Unsupported provider: {config.provider}")


class ChatService:
    def __init__(self, repository: DjangoMessageRepository | None = None) -> None:
        self.repository = repository or DjangoMessageRepository()
        self.counter = TokenCounter()
        self.window = HistoryWindow()
        self.gateway = ProviderGateway()
        self.document_service = DocumentService()

    def _resolve_api_key(self, user, provider: str) -> str:
        try:
            key_record = UserApiKey.objects.get(user=user, provider=provider)
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

    def generate_reply(
        self,
        *,
        user,
        session_id: str,
        user_text: str,
        config: LLMConfig,
        document_ids: list[str] | None = None,
    ) -> GenerationResult:
        clean_user_text = (user_text or "").strip()
        if not clean_user_text:
            raise InvalidInputError("user_text cannot be empty")

        user_message = clean_user_text

        context_chunks = None

        if document_ids is not None:
            search_results = self.document_service.search(
                user=user,
                query=clean_user_text,
                document_ids=document_ids or None,
            )
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

        api_key = self._resolve_api_key(user, config.provider)

        history = self.repository.list_messages(
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

        try:
            result = self.gateway.generate(
                api_key=api_key, config=config, messages=trimmed
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

        user_meta = {
            "raw_question": clean_user_text,
            "provider_selected": config.provider,
            "model_selected": config.model,
        }
        if context_chunks:
            user_meta["context_chunks"] = context_chunks

        user_msg, assistant_msg = self.repository.append_message_pair(
            session_id=session_id,
            user_content=user_message,
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
