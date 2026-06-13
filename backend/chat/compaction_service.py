import logging

from core.exceptions import TemporaryProviderError, PermanentProviderError
from .llm_config import (
    LLMConfig,
    ProviderChunk,
)
from .provider_gateway import ProviderGateway
from .repositories import StoredMessage
from .token_counter import TokenCounter
from .attachments import load_text_attachment

logger = logging.getLogger(__name__)


def _clean_content_for_summary(msg: StoredMessage) -> str:
    parts: list[str] = [msg.content]

    if msg.attachments:
        for att in msg.attachments:
            mime = att.get("mimeType", "")
            if mime.startswith("image/"):
                parts.append(f"\n[Image Attachment: {att['name']}]")
            else:
                filename = att.get("id", "")
                file_content = load_text_attachment(filename)

                if file_content:
                    parts.append(
                        f"\n[File Attachment: {att['name']}]\n--- Content ---\n{file_content}\n---------------"
                    )
                else:
                    parts.append(f"\n[File Attachment: {att['name']}]")

    return "".join(parts)


class CompactionService:
    def __init__(self, counter: TokenCounter, gateway: ProviderGateway) -> None:
        self.counter = counter
        self.gateway = gateway

    def _format_history_for_summary(self, history: list[StoredMessage]) -> str:
        lines = []
        for msg in history:
            label = "User" if msg.role == "user" else "Assistant"
            cleaned_content = _clean_content_for_summary(msg)
            lines.append(f"{label}: {cleaned_content}")
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

    def _build_summary_config(
        self, model: str, provider: str, max_input_tokens: int
    ) -> LLMConfig:
        max_output = min(1024, max_input_tokens // 4)
        return LLMConfig(
            provider=provider,
            model=model,
            system_prompt="You are a conversation summarizer.",
            compaction_provider=provider,
            compaction_model=model,
            max_output_tokens=max_output,
        )

    async def _call_summarizer(
        self,
        history: list[StoredMessage],
        model: str,
        api_key: str,
        provider: str,
        max_input_tokens: int,
    ) -> str | None:
        chunks: list[str] = []
        async for chunk in self._call_summarizer_stream(
            history, model, api_key, provider, max_input_tokens
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
        max_input_tokens: int,
    ):
        summarization_prompt = self._build_summarization_prompt(history)
        summary_config = self._build_summary_config(model, provider, max_input_tokens)

        prompt_tokens = self.counter.estimate_text_tokens(summarization_prompt, model)
        system_tokens = self.counter.estimate_system_tokens(
            summary_config.system_prompt, model
        )
        total_request_tokens = prompt_tokens + system_tokens

        logger.debug(
            f"Calling summarizer - provider={provider}, model={model}, "
            f"prompt_tokens={prompt_tokens}, system_tokens={system_tokens}, "
            f"total_request_tokens={total_request_tokens}, max_output_tokens={summary_config.max_output_tokens}"
        )

        try:
            async for chunk in self.gateway.generate_stream(
                api_key=api_key,
                config=summary_config,
                messages=[StoredMessage(role="user", content=summarization_prompt)],
            ):
                yield ProviderChunk(
                    text=chunk.text,
                    usage=chunk.usage,
                    provider=provider,
                    model=model,
                )
        except Exception as e:
            logger.error(
                f"Summarizer API call exception - provider={provider}, model={model}: {e}",
                exc_info=True,
            )
            raise

    async def compact(
        self,
        history: list[StoredMessage],
        config: LLMConfig,
        compaction_api_key: str,
    ) -> str | None:
        try:
            return await self._call_summarizer(
                history,
                config.compaction_model,
                compaction_api_key,
                config.compaction_provider,
                max_input_tokens=config.max_input_tokens,
            )
        except (TemporaryProviderError, PermanentProviderError) as e:
            logger.warning(
                f"Compaction failed for model {config.compaction_model} on provider {config.compaction_provider}: {e}"
            )
            return None

    async def compact_stream(
        self,
        history: list[StoredMessage],
        config: LLMConfig,
        compaction_api_key: str,
    ):
        try:
            async for chunk in self._call_summarizer_stream(
                history,
                config.compaction_model,
                compaction_api_key,
                config.compaction_provider,
                max_input_tokens=config.max_input_tokens,
            ):
                yield chunk
        except (TemporaryProviderError, PermanentProviderError) as e:
            logger.warning(
                f"Compaction stream failed for model {config.compaction_model} on provider {config.compaction_provider}: {e}"
            )

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
        max_summary_output = min(1024, config.max_input_tokens // 4)
        headroom = max_summary_output + 200
        threshold = min(
            config.max_input_tokens - headroom,
            int(config.max_input_tokens * config.compaction_threshold),
        )
        threshold = max(threshold, config.max_input_tokens // 2)
        decision = total > threshold
        logger.debug(
            f"should_compact calculation - system_tokens={system_tokens}, "
            f"history_tokens={history_tokens}, new_tokens={new_tokens}, "
            f"total_estimated={total}, threshold={threshold} (limit={config.max_input_tokens}, "
            f"threshold_pct={config.compaction_threshold}), decision={decision}"
        )
        return decision

    def chunk_truncate(
        self,
        *,
        history: list[StoredMessage],
        new_message: StoredMessage,
        system_prompt: str,
        config: LLMConfig,
    ) -> list[StoredMessage]:
        orig_len = len(history)
        logger.debug(f"Starting chunk_truncate - original history length: {orig_len}")
        while len(history) > 1 and self.should_compact(
            system_prompt=system_prompt,
            history=history,
            new_message=new_message,
            config=config,
        ):
            half = len(history) // 2
            history = history[half:]
            logger.debug(
                f"Truncated history: kept last {len(history)} of {orig_len} messages"
            )
        return history
