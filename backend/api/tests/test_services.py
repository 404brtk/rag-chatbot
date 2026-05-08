from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import openai
import pytest

from api.repositories import StoredMessage
from api.services import (
    DjangoChatService,
    GenerationResult,
    HistoryWindow,
    InvalidInputError,
    LLMConfig,
    PermanentProviderError,
    ProviderGateway,
    TemporaryProviderError,
    TokenCounter,
)


def _msg(role, content, created_at=None, meta=None):
    return StoredMessage(
        role=role,
        content=content,
        created_at=created_at or datetime(2025, 1, 1, tzinfo=timezone.utc),
        meta=meta or {},
    )


DEFAULT_CONFIG = LLMConfig(
    provider="openai",
    model="gpt-5.5",
    system_prompt="You are a helpful assistant.",
)


class TestTokenCounter:
    def setup_method(self):
        self.counter = TokenCounter()

    def test_estimate_text_tokens_counts_correctly(self):
        count = self.counter.estimate_text_tokens("Hello, world!", "gpt-5.5")
        assert count > 0
        assert isinstance(count, int)

    def test_estimate_text_tokens_uses_fallback_for_unknown_model(self):
        count = self.counter.estimate_text_tokens("Hello", "nonexistent-model-xyz")
        assert count > 0

    def test_estimate_message_tokens_includes_overhead(self):
        msg = _msg("user", "Hello")
        text_tokens = self.counter.estimate_text_tokens("Hello", "gpt-5.5")
        message_tokens = self.counter.estimate_message_tokens(msg, "gpt-5.5")
        assert message_tokens == text_tokens + 3

    def test_estimate_system_tokens_with_content(self):
        count = self.counter.estimate_system_tokens(
            "You are a helpful assistant.", "gpt-5.5"
        )
        assert count > 3

    def test_estimate_system_tokens_empty_string_returns_zero(self):
        assert self.counter.estimate_system_tokens("", "gpt-5.5") == 0

    def test_estimate_system_tokens_whitespace_only_returns_zero(self):
        assert self.counter.estimate_system_tokens("   \n\t  ", "gpt-5.5") == 0

    def test_truncate_text_under_limit_returns_unchanged(self):
        text = "Hello"
        result = self.counter.truncate_text_to_max_tokens(text, "gpt-5.5", 100)
        assert result == text

    def test_truncate_text_over_limit_truncates(self):
        text = "This is a longer piece of text that should be truncated"
        result = self.counter.truncate_text_to_max_tokens(text, "gpt-5.5", 2)
        full_count = self.counter.estimate_text_tokens(text, "gpt-5.5")
        truncated_count = self.counter.estimate_text_tokens(result, "gpt-5.5")
        assert truncated_count <= 2
        assert truncated_count < full_count

    def test_truncate_text_zero_limit_returns_empty(self):
        result = self.counter.truncate_text_to_max_tokens("Hello", "gpt-5.5", 0)
        assert result == ""

    def test_truncate_text_negative_limit_returns_empty(self):
        result = self.counter.truncate_text_to_max_tokens("Hello", "gpt-5.5", -5)
        assert result == ""


class TestHistoryWindowNormalize:
    def setup_method(self):
        self.window = HistoryWindow()

    def test_merges_consecutive_same_role_messages(self):
        messages = [
            _msg("user", "Hello"),
            _msg("user", "Can you help?"),
        ]
        result = self.window.normalize(messages)
        assert len(result) == 1
        assert "Hello" in result[0].content
        assert "Can you help?" in result[0].content

    def test_strips_empty_messages(self):
        messages = [
            _msg("user", "Hello"),
            _msg("assistant", ""),
            _msg("assistant", "Hi there"),
        ]
        result = self.window.normalize(messages)
        assert len(result) == 2
        assert result[0].role == "user"
        assert result[1].role == "assistant"

    def test_strips_whitespace_only_messages(self):
        messages = [
            _msg("user", "   "),
        ]
        result = self.window.normalize(messages)
        assert len(result) == 0

    def test_preserves_alternating_roles(self):
        messages = [
            _msg("user", "Hello"),
            _msg("assistant", "Hi"),
            _msg("user", "How are you?"),
        ]
        result = self.window.normalize(messages)
        assert len(result) == 3
        assert result[0].role == "user"
        assert result[1].role == "assistant"
        assert result[2].role == "user"

    def test_preserves_none_meta_as_empty_dict(self):
        msg = StoredMessage(role="user", content="Hello", created_at=None, meta=None)
        result = self.window.normalize([msg])
        assert result[0].meta == {}

    def test_merged_message_uses_later_timestamp(self):
        messages = [
            _msg("user", "First", created_at=datetime(2025, 1, 1, tzinfo=timezone.utc)),
            _msg(
                "user", "Second", created_at=datetime(2025, 6, 1, tzinfo=timezone.utc)
            ),
        ]
        result = self.window.normalize(messages)
        assert len(result) == 1
        assert result[0].created_at == datetime(2025, 6, 1, tzinfo=timezone.utc)


class TestHistoryWindowFitToTokenLimit:
    def setup_method(self):
        self.window = HistoryWindow()
        self.counter = TokenCounter()

    def test_raises_on_empty_history(self):
        with pytest.raises(InvalidInputError, match="Empty message history"):
            self.window.fit_to_token_limit(
                system_prompt="You are helpful.",
                messages=[_msg("user", "")],
                model="gpt-5.5",
                max_input_tokens=4096,
                counter=self.counter,
            )

    def test_raises_when_no_user_first_history_after_trimming(self):
        messages = [
            _msg("assistant", "Just me here"),
        ]
        with pytest.raises(InvalidInputError, match="No valid user-first history"):
            self.window.fit_to_token_limit(
                system_prompt="You are helpful.",
                messages=messages,
                model="gpt-5.5",
                max_input_tokens=4096,
                counter=self.counter,
            )

    def test_trims_older_messages_from_start(self):
        short_prompt = "Hi"
        messages = [
            _msg("user", "first question"),
            _msg("assistant", "first answer"),
            _msg("user", "second question"),
            _msg("assistant", "second answer"),
            _msg("user", "current question"),
        ]
        system_tokens = self.counter.estimate_system_tokens(short_prompt, "gpt-5.5")
        user_msg_tokens = self.counter.estimate_message_tokens(
            _msg("user", "current question"), "gpt-5.5"
        )

        tight_limit = system_tokens + 24 + user_msg_tokens + 10

        result = self.window.fit_to_token_limit(
            system_prompt=short_prompt,
            messages=messages,
            model="gpt-5.5",
            max_input_tokens=tight_limit,
            counter=self.counter,
        )

        assert result[-1].content == "current question"
        assert result[0].role == "user"

    def test_first_kept_message_is_always_user(self):
        messages = [
            _msg("assistant", "stray assistant msg"),
            _msg("user", "real question"),
        ]
        result = self.window.fit_to_token_limit(
            system_prompt="Hi",
            messages=messages,
            model="gpt-5.5",
            max_input_tokens=4096,
            counter=self.counter,
        )
        assert result[0].role == "user"

    def test_truncates_first_message_when_it_exceeds_budget(self):
        long_content = "word " * 2000
        messages = [
            _msg("user", long_content),
        ]
        result = self.window.fit_to_token_limit(
            system_prompt="You are helpful.",
            messages=messages,
            model="gpt-5.5",
            max_input_tokens=100,
            counter=self.counter,
        )
        assert len(result) == 1
        assert result[0].role == "user"
        assert result[0].meta.get("truncated_for_model") is True

    def test_full_history_fits_within_budget(self):
        messages = [
            _msg("user", "Hi"),
            _msg("assistant", "Hello"),
            _msg("user", "How are you?"),
        ]
        result = self.window.fit_to_token_limit(
            system_prompt="You are helpful.",
            messages=messages,
            model="gpt-5.5",
            max_input_tokens=4096,
            counter=self.counter,
        )
        assert len(result) == 3
        assert result[0].content == "Hi"
        assert result[1].content == "Hello"
        assert result[2].content == "How are you?"


class TestProviderGateway:
    @patch("api.services.OpenAI")
    def test_routes_to_openai_for_openai_provider(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello!"
        mock_response.usage.model_dump.return_value = {
            "prompt_tokens": 5,
            "completion_tokens": 2,
        }
        mock_client.chat.completions.create.return_value = mock_response

        gateway = ProviderGateway(openai_client=mock_client)
        result = gateway.generate(
            config=DEFAULT_CONFIG,
            messages=[StoredMessage(role="user", content="Hi")],
        )

        assert result.provider == "openai"
        assert result.text == "Hello!"
        mock_client.chat.completions.create.assert_called_once()

    def test_raises_permanent_error_for_unsupported_provider(self):
        gateway = ProviderGateway(openai_client=MagicMock())
        config = replace(DEFAULT_CONFIG, provider="unsupported")

        with pytest.raises(PermanentProviderError, match="Unsupported provider"):
            gateway.generate(
                config=config,
                messages=[StoredMessage(role="user", content="Hi")],
            )

    @pytest.mark.parametrize(
        "error_class,expected_exception,kwargs",
        [
            (
                openai.RateLimitError,
                TemporaryProviderError,
                {"message": "rate limited", "response": MagicMock(), "body": None},
            ),
            (
                openai.BadRequestError,
                PermanentProviderError,
                {"message": "bad request", "response": MagicMock(), "body": None},
            ),
            (
                openai.APIConnectionError,
                TemporaryProviderError,
                {"request": MagicMock()},
            ),
            (
                openai.APITimeoutError,
                TemporaryProviderError,
                {"request": MagicMock()},
            ),
            (
                openai.InternalServerError,
                TemporaryProviderError,
                {"message": "internal error", "response": MagicMock(), "body": None},
            ),
        ],
    )
    def test_maps_openai_errors(self, error_class, expected_exception, kwargs):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = error_class(**kwargs)

        gateway = ProviderGateway(openai_client=mock_client)
        with pytest.raises(expected_exception):
            gateway.generate(
                config=DEFAULT_CONFIG,
                messages=[StoredMessage(role="user", content="Hi")],
            )


class TestDjangoChatServiceGenerateReply:
    def setup_method(self):
        self.mock_repo = MagicMock()

    @pytest.mark.parametrize("user_text", ["", "   \t\n  "])
    @patch("api.services.ProviderGateway.generate")
    def test_raises_invalid_input_on_empty_or_whitespace_text(
        self, mock_generate, user_text
    ):
        service = DjangoChatService(repository=self.mock_repo)
        with pytest.raises(InvalidInputError, match="cannot be empty"):
            service.generate_reply(
                session_id="test-session",
                user_text=user_text,
                config=DEFAULT_CONFIG,
            )
        mock_generate.assert_not_called()

    @pytest.mark.parametrize(
        "error_class",
        [TemporaryProviderError, PermanentProviderError],
    )
    @patch("api.services.ProviderGateway.generate")
    def test_propagates_provider_errors(self, mock_generate, error_class):
        mock_generate.side_effect = error_class("service error")
        self.mock_repo.list_messages.return_value = []

        service = DjangoChatService(repository=self.mock_repo)
        with pytest.raises(error_class):
            service.generate_reply(
                session_id="test-session",
                user_text="Hello",
                config=DEFAULT_CONFIG,
            )

    @patch("api.services.ProviderGateway.generate")
    def test_strips_whitespace_from_user_text(self, mock_generate):
        mock_generate.return_value = GenerationResult(
            text="Hi!",
            provider="openai",
            model="gpt-5.5",
            input_tokens=1,
            output_tokens=1,
            usage={},
            model_input=[],
        )
        self.mock_repo.list_messages.return_value = []
        self.mock_repo.append_message_pair.return_value = (
            MagicMock(id="user-id"),
            MagicMock(id="assistant-id"),
        )

        service = DjangoChatService(repository=self.mock_repo)
        service.generate_reply(
            session_id="test-session",
            user_text="  Hello  ",
            config=DEFAULT_CONFIG,
        )

        call_kwargs = self.mock_repo.append_message_pair.call_args[1]
        assert call_kwargs["user_content"] == "Hello"

    @patch("api.services.ProviderGateway.generate")
    def test_passes_history_and_new_message_to_window(self, mock_generate):
        mock_generate.return_value = GenerationResult(
            text="Hi!",
            provider="openai",
            model="gpt-5.5",
            input_tokens=1,
            output_tokens=1,
            usage={},
            model_input=[],
        )
        history_msg = StoredMessage(role="assistant", content="Previous answer")
        self.mock_repo.list_messages.return_value = [history_msg]
        self.mock_repo.append_message_pair.return_value = (
            MagicMock(id="user-id"),
            MagicMock(id="assistant-id"),
        )

        service = DjangoChatService(repository=self.mock_repo)
        service.generate_reply(
            session_id="test-session",
            user_text="New question",
            config=DEFAULT_CONFIG,
        )

        mock_generate.assert_called_once()
        passed_messages = mock_generate.call_args[1]["messages"]
        user_messages = [m for m in passed_messages if m.role == "user"]
        assert len(user_messages) == 1
        assert "New question" in user_messages[0].content

    @patch("api.services.ProviderGateway.generate")
    def test_appends_message_pair_to_repository(self, mock_generate):
        mock_generate.return_value = GenerationResult(
            text="Response text",
            provider="openai",
            model="gpt-5.5",
            input_tokens=10,
            output_tokens=5,
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            model_input=[],
        )
        self.mock_repo.list_messages.return_value = []
        mock_user = MagicMock()
        mock_user.id = "user-uuid"
        mock_assistant = MagicMock()
        mock_assistant.id = "assistant-uuid"
        self.mock_repo.append_message_pair.return_value = (
            mock_user,
            mock_assistant,
        )

        service = DjangoChatService(repository=self.mock_repo)
        result = service.generate_reply(
            session_id="test-session",
            user_text="Hello",
            config=DEFAULT_CONFIG,
        )

        assert result.user_message_id == "user-uuid"
        assert result.assistant_message_id == "assistant-uuid"
        self.mock_repo.append_message_pair.assert_called_once()
