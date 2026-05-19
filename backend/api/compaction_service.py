import logging

from .llm_config import (
    LLMConfig,
    PermanentProviderError,
    ProviderChunk,
    TemporaryProviderError,
)
from .provider_gateway import ProviderGateway
from .repositories import StoredMessage
from .token_counter import TokenCounter

logger = logging.getLogger(__name__)


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
