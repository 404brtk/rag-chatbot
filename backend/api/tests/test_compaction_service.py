from dataclasses import replace
from unittest.mock import MagicMock, patch

from api.repositories import StoredMessage
from api.compaction_service import CompactionService, _clean_content_for_summary
from api.token_counter import TokenCounter
from api.llm_config import (
    ProviderChunk,
    TemporaryProviderError,
)

from .conftest import DEFAULT_CONFIG, _msg


class TestCompactionService:
    def setup_method(self):
        self.counter = TokenCounter()
        self.gateway = MagicMock()
        self.gateway.generate_stream = MagicMock()
        self.service = CompactionService(self.counter, self.gateway)

    def test_should_compact_returns_false_when_under_threshold(self):
        history = [_msg("user", "Hello")]
        new_msg = _msg("user", "How are you?")
        config = replace(DEFAULT_CONFIG, max_input_tokens=4096)
        assert not self.service.should_compact(
            system_prompt=config.system_prompt,
            history=history,
            new_message=new_msg,
            config=config,
        )

    def test_should_compact_returns_true_when_over_threshold(self):
        long_history = [
            _msg("user", "word " * 5000),
            _msg("assistant", "answer " * 5000),
        ]
        new_msg = _msg("user", "How are you?")
        config = replace(DEFAULT_CONFIG, max_input_tokens=100)
        assert self.service.should_compact(
            system_prompt=config.system_prompt,
            history=long_history,
            new_message=new_msg,
            config=config,
        )

    def test_should_compact_exact_boundary(self):
        msg = _msg("user", "Hello world")
        config = DEFAULT_CONFIG
        system_tokens = self.counter.estimate_system_tokens(
            config.system_prompt, config.model
        )
        msg_tokens = self.counter.estimate_message_tokens(msg, config.model)
        total = system_tokens + msg_tokens + 24

        exact_boundary = replace(config, max_input_tokens=2 * total)
        assert not self.service.should_compact(
            system_prompt=config.system_prompt,
            history=[],
            new_message=msg,
            config=exact_boundary,
        )

        one_over = replace(config, max_input_tokens=2 * total - 2)
        assert self.service.should_compact(
            system_prompt=config.system_prompt,
            history=[],
            new_message=msg,
            config=one_over,
        )

    async def test_compact_calls_llm_with_formatted_history(self):
        async def _fake_stream():
            yield ProviderChunk(text="Summary text.")

        self.gateway.generate_stream.return_value = _fake_stream()
        history = [_msg("user", "Hello"), _msg("assistant", "Hi there")]
        config = replace(DEFAULT_CONFIG, compaction_model="gpt")

        result = await self.service.compact(
            history=history,
            config=config,
            compaction_api_key="sk-compaction",
        )

        assert result == "Summary text."
        self.gateway.generate_stream.assert_called_once()
        call_messages = self.gateway.generate_stream.call_args[1]["messages"]
        assert len(call_messages) == 1
        assert "User: Hello" in call_messages[0].content
        assert "Assistant: Hi there" in call_messages[0].content

    async def test_compact_returns_none_on_failure(self):
        self.gateway.generate_stream.side_effect = TemporaryProviderError(
            "rate limited"
        )
        config = replace(DEFAULT_CONFIG, compaction_model="gpt")

        result = await self.service.compact(
            history=[_msg("user", "Hello")],
            config=config,
            compaction_api_key="sk-compaction",
        )

        assert result is None
        assert self.gateway.generate_stream.call_count == 1

    def test_chunk_truncate_returns_all_when_under_threshold(self):
        history = [
            _msg("user", "1"),
            _msg("assistant", "a"),
            _msg("user", "2"),
            _msg("assistant", "b"),
        ]
        new_msg = _msg("user", "3")
        config = replace(DEFAULT_CONFIG, max_input_tokens=4096)
        result = self.service.chunk_truncate(
            history=history,
            new_message=new_msg,
            system_prompt=config.system_prompt,
            config=config,
        )
        assert len(result) == 4
        assert result[0].content == "1"

    def test_chunk_truncate_halves_until_under_threshold(self):
        long_msg = _msg("user", "word " * 2000)
        history = [long_msg] * 6
        new_msg = _msg("user", "Hello")
        config = replace(
            DEFAULT_CONFIG, max_input_tokens=4096, compaction_threshold=0.5
        )
        result = self.service.chunk_truncate(
            history=history,
            new_message=new_msg,
            system_prompt=config.system_prompt,
            config=config,
        )
        assert len(result) == 1

    def test_chunk_truncate_empty_returns_empty(self):
        new_msg = _msg("user", "Hello")
        config = DEFAULT_CONFIG
        assert (
            self.service.chunk_truncate(
                history=[],
                new_message=new_msg,
                system_prompt=config.system_prompt,
                config=config,
            )
            == []
        )

    async def test_compact_stream_fails_silently_on_error(self):
        async def _failing_stream():
            yield ProviderChunk(text="Part")
            raise TemporaryProviderError("model failed")

        self.gateway.generate_stream.return_value = _failing_stream()
        config = replace(DEFAULT_CONFIG, compaction_model="gpt")

        chunks = []
        async for chunk in self.service.compact_stream(
            history=[_msg("user", "Hello")],
            config=config,
            compaction_api_key="sk-compaction",
        ):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].text == "Part"

    @patch("api.compaction_service.load_text_attachment")
    def test_clean_content_for_summary(self, mock_load):
        mock_load.return_value = "pass"

        msg = StoredMessage(
            role="user",
            content="Here is the issue:\nand code:",
            attachments=[
                {
                    "id": "screenshot.png",
                    "name": "screenshot.png",
                    "size": 500,
                    "mimeType": "image/png",
                },
                {
                    "id": "test.py",
                    "name": "test.py",
                    "size": 20,
                    "mimeType": "text/plain",
                },
            ],
        )

        cleaned = _clean_content_for_summary(msg)
        mock_load.assert_called_once_with("test.py")
        assert "[Image Attachment: screenshot.png]" in cleaned
        assert "[File Attachment: test.py]" in cleaned
        assert "pass" in cleaned
