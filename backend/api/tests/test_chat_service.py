from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from api.models import Conversation, UserApiKey
from api.repositories import StoredMessage
from api.chat_service import (
    ChatService,
    CompactionService,
    GenerationResult,
    InvalidInputError,
    LLMConfig,
    MissingApiKeyError,
    PermanentProviderError,
    ProviderChunk,
    ProviderGateway,
    StreamEvent,
    TemporaryProviderError,
    TokenCounter,
)
from api.document_service import SearchResult


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


class TestProviderGateway:
    @patch("api.chat_service.AsyncOpenAI")
    async def test_routes_to_openai_for_openai_provider(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello!"
        mock_response.usage.model_dump.return_value = {
            "prompt_tokens": 5,
            "completion_tokens": 2,
        }
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        gateway = ProviderGateway()
        result = await gateway.generate(
            api_key="sk-test",
            config=DEFAULT_CONFIG,
            messages=[StoredMessage(role="user", content="Hi")],
        )

        assert result.provider == "openai"
        assert result.text == "Hello!"
        mock_client.chat.completions.create.assert_called_once()

    async def test_raises_permanent_error_for_unsupported_provider(self):
        gateway = ProviderGateway()
        config = replace(DEFAULT_CONFIG, provider="unsupported")

        with pytest.raises(PermanentProviderError, match="Unsupported provider"):
            await gateway.generate(
                api_key="sk-test",
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
            (
                openai.AuthenticationError,
                PermanentProviderError,
                {"message": "invalid key", "response": MagicMock(), "body": None},
            ),
        ],
    )
    @patch("api.chat_service.AsyncOpenAI")
    async def test_maps_openai_errors(
        self, mock_openai_cls, error_class, expected_exception, kwargs
    ):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = error_class(**kwargs)

        gateway = ProviderGateway()
        with pytest.raises(expected_exception):
            await gateway.generate(
                api_key="sk-test",
                config=DEFAULT_CONFIG,
                messages=[StoredMessage(role="user", content="Hi")],
            )

    @patch("api.chat_service.AsyncOpenAI")
    async def test_stream_yields_tokens_and_usage(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        chunk_a = MagicMock(usage=None, choices=[MagicMock()])
        chunk_a.choices[0].delta.content = "Hello"
        chunk_b = MagicMock(usage=None, choices=[MagicMock()])
        chunk_b.choices[0].delta.content = " world"
        usage_chunk = MagicMock(choices=[], usage=MagicMock())
        usage_chunk.usage.model_dump.return_value = {
            "prompt_tokens": 10,
            "completion_tokens": 3,
        }

        async def fake_stream():
            for c in [chunk_a, chunk_b, usage_chunk]:
                yield c

        mock_client.chat.completions.create = AsyncMock(return_value=fake_stream())

        gateway = ProviderGateway()
        chunks = [
            c
            async for c in gateway.generate_stream(
                api_key="sk-test",
                config=DEFAULT_CONFIG,
                messages=[StoredMessage(role="user", content="Hi")],
            )
        ]

        text_chunks = [c for c in chunks if c.text]
        usage_chunks = [c for c in chunks if c.usage]
        assert len(text_chunks) == 2
        assert text_chunks[0] == ProviderChunk(text="Hello")
        assert text_chunks[1] == ProviderChunk(text=" world")
        assert len(usage_chunks) == 1
        assert usage_chunks[0].usage["prompt_tokens"] == 10

    @patch("api.chat_service.AsyncOpenAI")
    async def test_stream_maps_openai_errors(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai.RateLimitError(
                message="rate limited", response=MagicMock(), body=None
            )
        )

        gateway = ProviderGateway()
        with pytest.raises(TemporaryProviderError):
            async for _ in gateway.generate_stream(
                api_key="sk-test",
                config=DEFAULT_CONFIG,
                messages=[StoredMessage(role="user", content="Hi")],
            ):
                pass

    async def test_stream_raises_for_unsupported_provider(self):
        gateway = ProviderGateway()
        config = replace(DEFAULT_CONFIG, provider="unsupported")
        with pytest.raises(PermanentProviderError, match="Unsupported provider"):
            async for _ in gateway.generate_stream(
                api_key="sk-test",
                config=config,
                messages=[StoredMessage(role="user", content="Hi")],
            ):
                pass


class TestFormatRagContext:
    def test_formats_single_chunk_with_label_and_source(self):
        results = [
            SearchResult(
                chunk_content="Chunk content here.",
                document_id="abc",
                document_filename="test.txt",
                chunk_index=0,
                distance=0.1,
            )
        ]
        result = ChatService._format_rag_context(results)
        assert result == "[1] (source: test.txt, chunk 0)\nChunk content here."

    def test_joins_multiple_chunks_with_double_newline(self):
        results = [
            SearchResult("Chunk A", "d1", "a.txt", 0, 0.1),
            SearchResult("Chunk B", "d2", "b.txt", 3, 0.2),
        ]
        result = ChatService._format_rag_context(results)
        assert result == (
            "[1] (source: a.txt, chunk 0)\nChunk A\n\n"
            "[2] (source: b.txt, chunk 3)\nChunk B"
        )

    def test_returns_empty_string_for_empty_list(self):
        assert ChatService._format_rag_context([]) == ""


class TestComputeTitle:
    def test_short_text_returned_as_is(self):
        assert ChatService._compute_title("Hello world") == "Hello world"

    def test_exactly_50_chars_returned_as_is(self):
        text = "a" * 50
        assert ChatService._compute_title(text) == text

    def test_long_text_truncates_at_word_boundary(self):
        text = "This is a long sentence that exceeds fifty characters by a lot"
        result = ChatService._compute_title(text)
        assert result.endswith("...")
        assert len(result) <= 53
        assert not result.rstrip(".").endswith(" ")

    def test_long_text_without_spaces_truncates_at_50(self):
        text = "a" * 60
        assert ChatService._compute_title(text) == "a" * 50 + "..."

    def test_strips_whitespace(self):
        assert ChatService._compute_title("  Hello  ") == "Hello"


class TestChatServiceGenerateReply:
    def setup_method(self):
        self.mock_repo = MagicMock()
        self.mock_repo.list_messages = AsyncMock(return_value=[])
        self.mock_repo.append_message_pair = AsyncMock(
            return_value=(MagicMock(id="user-id"), MagicMock(id="assistant-id"))
        )
        self.mock_repo.apply_compaction = AsyncMock(
            return_value=MagicMock(id="summary-id")
        )
        self.mock_user = MagicMock()
        self.mock_session = MagicMock()
        self._session_patch = patch(
            "api.chat_service.Conversation.objects.aget",
            new=AsyncMock(return_value=self.mock_session),
        )
        self._session_patch.start()

    def teardown_method(self):
        self._session_patch.stop()

    @pytest.mark.parametrize("user_text", ["", "   \t\n  "])
    @patch("api.chat_service.ProviderGateway.generate", new_callable=AsyncMock)
    async def test_raises_invalid_input_on_empty_or_whitespace_text(
        self, mock_generate, user_text
    ):
        service = ChatService(repository=self.mock_repo)
        with pytest.raises(InvalidInputError, match="cannot be empty"):
            await service.generate_reply(
                user=self.mock_user,
                session_id="test-session",
                user_text=user_text,
                config=DEFAULT_CONFIG,
            )
        mock_generate.assert_not_called()

    @pytest.mark.parametrize(
        "error_class",
        [TemporaryProviderError, PermanentProviderError],
    )
    @patch("api.chat_service.ProviderGateway.generate", new_callable=AsyncMock)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_propagates_provider_errors(
        self, mock_resolve, mock_generate, error_class
    ):
        mock_generate.side_effect = error_class("service error")
        self.mock_repo.list_messages.return_value = []

        service = ChatService(repository=self.mock_repo)
        with pytest.raises(error_class):
            await service.generate_reply(
                user=self.mock_user,
                session_id="test-session",
                user_text="Hello",
                config=DEFAULT_CONFIG,
            )

    @patch("api.chat_service.ProviderGateway.generate", new_callable=AsyncMock)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_strips_whitespace_from_user_text(self, mock_resolve, mock_generate):
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

        service = ChatService(repository=self.mock_repo)
        await service.generate_reply(
            user=self.mock_user,
            session_id="test-session",
            user_text="  Hello  ",
            config=DEFAULT_CONFIG,
        )

        call_kwargs = self.mock_repo.append_message_pair.call_args[1]
        assert call_kwargs["user_content"] == "Hello"

    @patch("api.chat_service.ProviderGateway.generate", new_callable=AsyncMock)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_passes_history_and_new_message_to_window(
        self, mock_resolve, mock_generate
    ):
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

        service = ChatService(repository=self.mock_repo)
        await service.generate_reply(
            user=self.mock_user,
            session_id="test-session",
            user_text="New question",
            config=DEFAULT_CONFIG,
        )

        mock_generate.assert_called_once()
        passed_messages = mock_generate.call_args[1]["messages"]
        user_messages = [m for m in passed_messages if m.role == "user"]
        assert len(user_messages) == 1
        assert "New question" in user_messages[0].content

    @patch("api.chat_service.ProviderGateway.generate", new_callable=AsyncMock)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_appends_message_pair_to_repository(
        self, mock_resolve, mock_generate
    ):
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

        service = ChatService(repository=self.mock_repo)
        result = await service.generate_reply(
            user=self.mock_user,
            session_id="test-session",
            user_text="Hello",
            config=DEFAULT_CONFIG,
        )

        assert result.user_message_id == "user-uuid"
        assert result.assistant_message_id == "assistant-uuid"
        self.mock_repo.append_message_pair.assert_called_once()

    @patch("api.chat_service.ProviderGateway.generate", new_callable=AsyncMock)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    @patch("api.chat_service.DocumentService")
    async def test_injects_context_tags_when_search_has_results(
        self, mock_doc_svc_cls, mock_resolve, mock_generate
    ):
        mock_doc_svc_cls.return_value.search.return_value = [
            SearchResult("Relevant info.", "doc-1", "docs.md", 0, 0.1)
        ]
        mock_generate.return_value = GenerationResult(
            text="Answer.",
            provider="openai",
            model="gpt-5.5",
            input_tokens=10,
            output_tokens=5,
            usage={},
            model_input=[],
        )
        self.mock_repo.list_messages.return_value = []
        self.mock_repo.append_message_pair.return_value = (
            MagicMock(id="u-id"),
            MagicMock(id="a-id"),
        )

        service = ChatService(repository=self.mock_repo)
        await service.generate_reply(
            user=self.mock_user,
            session_id="test-session",
            user_text="Hello",
            config=DEFAULT_CONFIG,
            document_ids=[],
        )

        call_kwargs = self.mock_repo.append_message_pair.call_args[1]
        user_content = call_kwargs["user_content"]
        assert "<CONTEXT>" in user_content
        assert "[1] (source: docs.md, chunk 0)" in user_content
        assert "Relevant info." in user_content
        assert "</CONTEXT>" in user_content
        assert "<QUESTION>" in user_content
        assert "Hello" in user_content
        assert "</QUESTION>" in user_content

    @patch("api.chat_service.ProviderGateway.generate", new_callable=AsyncMock)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    @patch("api.chat_service.DocumentService")
    async def test_includes_context_chunks_and_raw_question_in_user_meta(
        self, mock_doc_svc_cls, mock_resolve, mock_generate
    ):
        mock_doc_svc_cls.return_value.search.return_value = [
            SearchResult("Info A", "d1", "a.txt", 0, 0.1),
            SearchResult("Info B", "d2", "b.txt", 3, 0.2),
        ]
        mock_generate.return_value = GenerationResult(
            text="Answer.",
            provider="openai",
            model="gpt-5.5",
            input_tokens=10,
            output_tokens=5,
            usage={},
            model_input=[],
        )
        self.mock_repo.list_messages.return_value = []
        self.mock_repo.append_message_pair.return_value = (
            MagicMock(id="u-id"),
            MagicMock(id="a-id"),
        )

        service = ChatService(repository=self.mock_repo)
        await service.generate_reply(
            user=self.mock_user,
            session_id="test-session",
            user_text="  Question  ",
            config=DEFAULT_CONFIG,
            document_ids=["doc-1"],
        )

        user_meta = self.mock_repo.append_message_pair.call_args[1]["user_meta"]
        assert user_meta["raw_question"] == "Question"
        assert len(user_meta["context_chunks"]) == 2
        assert user_meta["context_chunks"][0]["index"] == 1
        assert user_meta["context_chunks"][0]["content"] == "Info A"
        assert user_meta["context_chunks"][0]["document_filename"] == "a.txt"
        assert user_meta["context_chunks"][0]["document_id"] == "d1"
        assert user_meta["context_chunks"][0]["chunk_index"] == 0
        assert user_meta["context_chunks"][0]["distance"] == 0.1
        assert user_meta["context_chunks"][1]["index"] == 2
        assert user_meta["context_chunks"][1]["content"] == "Info B"

    @patch("api.chat_service.ProviderGateway.generate", new_callable=AsyncMock)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    @patch("api.chat_service.DocumentService")
    async def test_does_not_inject_context_when_document_ids_is_none(
        self, mock_doc_svc_cls, mock_resolve, mock_generate
    ):
        mock_generate.return_value = GenerationResult(
            text="Answer.",
            provider="openai",
            model="gpt-5.5",
            input_tokens=10,
            output_tokens=5,
            usage={},
            model_input=[],
        )
        self.mock_repo.list_messages.return_value = []
        self.mock_repo.append_message_pair.return_value = (
            MagicMock(id="u-id"),
            MagicMock(id="a-id"),
        )

        service = ChatService(repository=self.mock_repo)
        await service.generate_reply(
            user=self.mock_user,
            session_id="test-session",
            user_text="Hello",
            config=DEFAULT_CONFIG,
        )

        call_kwargs = self.mock_repo.append_message_pair.call_args[1]
        assert call_kwargs["user_content"] == "Hello"
        assert "context_chunks" not in call_kwargs["user_meta"]
        assert call_kwargs["user_meta"]["raw_question"] == "Hello"
        mock_doc_svc_cls.return_value.search.assert_not_called()

    @patch("api.chat_service.ProviderGateway.generate", new_callable=AsyncMock)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    @patch("api.chat_service.DocumentService")
    async def test_skips_context_injection_when_search_returns_no_results(
        self, mock_doc_svc_cls, mock_resolve, mock_generate
    ):
        mock_doc_svc_cls.return_value.search.return_value = []
        mock_generate.return_value = GenerationResult(
            text="Answer.",
            provider="openai",
            model="gpt-5.5",
            input_tokens=10,
            output_tokens=5,
            usage={},
            model_input=[],
        )
        self.mock_repo.list_messages.return_value = []
        self.mock_repo.append_message_pair.return_value = (
            MagicMock(id="u-id"),
            MagicMock(id="a-id"),
        )

        service = ChatService(repository=self.mock_repo)
        await service.generate_reply(
            user=self.mock_user,
            session_id="test-session",
            user_text="Hello",
            config=DEFAULT_CONFIG,
            document_ids=[],
        )

        call_kwargs = self.mock_repo.append_message_pair.call_args[1]
        assert call_kwargs["user_content"] == "Hello"
        assert "context_chunks" not in call_kwargs["user_meta"]

    @patch("api.chat_service.UserApiKey.objects.aget")
    async def test_raises_missing_api_key_error_when_no_key_set(self, mock_get):
        mock_get.side_effect = UserApiKey.DoesNotExist
        service = ChatService(repository=self.mock_repo)
        with pytest.raises(MissingApiKeyError, match="No API key configured"):
            await service._resolve_api_key(self.mock_user, "openai")


class TestChatServiceGenerateReplyStream:
    def setup_method(self):
        self.mock_repo = MagicMock()
        self.mock_repo.list_messages = AsyncMock(return_value=[])
        self.mock_repo.append_message = AsyncMock(
            side_effect=lambda **kwargs: MagicMock(id=f"msg-{kwargs['role']}")
        )
        self.mock_repo.apply_compaction = AsyncMock(
            return_value=MagicMock(id="summary-id")
        )
        self.mock_user = MagicMock()

    async def _collect_events(self, service, **kwargs):
        return [e async for e in service.generate_reply_stream(**kwargs)]

    @pytest.mark.django_db(transaction=True)
    @patch("api.chat_service.ProviderGateway.generate_stream")
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_yields_tokens_and_done_event(
        self, mock_resolve, mock_stream, user_a
    ):
        async def gen():
            yield ProviderChunk(text="Hello")
            yield ProviderChunk(text=" world")

        mock_stream.return_value = gen()
        conversation = await Conversation.objects.acreate(
            user=user_a, title="Existing title"
        )

        service = ChatService(repository=self.mock_repo)
        events = await self._collect_events(
            service,
            user=user_a,
            session_id=str(conversation.id),
            user_text="Hello",
            config=DEFAULT_CONFIG,
        )

        assert len(events) == 3
        assert events[0] == StreamEvent(type="token", content="Hello")
        assert events[1] == StreamEvent(type="token", content=" world")
        assert events[2].type == "done"
        assert events[2].message_id is not None
        assert events[2].title is None
        assert events[2].provider == "openai"
        assert events[2].model == "gpt-5.5"

    @pytest.mark.django_db(transaction=True)
    @patch("api.chat_service.ProviderGateway.generate_stream")
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_appends_user_and_assistant_messages(
        self, mock_resolve, mock_stream, user_a
    ):
        async def gen():
            yield ProviderChunk(text="Response")

        mock_stream.return_value = gen()
        conversation = await Conversation.objects.acreate(user=user_a, title="Existing")

        service = ChatService(repository=self.mock_repo)
        await self._collect_events(
            service,
            user=user_a,
            session_id=str(conversation.id),
            user_text="Hello",
            config=DEFAULT_CONFIG,
        )

        assert self.mock_repo.append_message.call_count == 2
        user_call = self.mock_repo.append_message.call_args_list[0][1]
        assert user_call["role"] == "user"
        assert user_call["content"] == "Hello"
        assert user_call["provider"] is None
        assert user_call["meta"]["raw_question"] == "Hello"

        assistant_call = self.mock_repo.append_message.call_args_list[1][1]
        assert assistant_call["role"] == "assistant"
        assert assistant_call["content"] == "Response"
        assert assistant_call["provider"] == "openai"
        assert assistant_call["model"] == "gpt-5.5"

    @pytest.mark.django_db(transaction=True)
    @patch("api.chat_service.ProviderGateway.generate_stream")
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_uses_provider_usage_over_estimate(
        self, mock_resolve, mock_stream, user_a
    ):
        provider_usage = {
            "prompt_tokens": 42,
            "completion_tokens": 10,
            "total_tokens": 52,
        }

        async def gen():
            yield ProviderChunk(text="Response")
            yield ProviderChunk(usage=provider_usage)

        mock_stream.return_value = gen()
        conversation = await Conversation.objects.acreate(user=user_a, title="Existing")

        service = ChatService(repository=self.mock_repo)
        events = await self._collect_events(
            service,
            user=user_a,
            session_id=str(conversation.id),
            user_text="Hello",
            config=DEFAULT_CONFIG,
        )

        assert events[-1].usage == provider_usage
        assistant_call = self.mock_repo.append_message.call_args_list[1][1]
        assert assistant_call["usage"] == provider_usage

    @pytest.mark.django_db(transaction=True)
    @patch("api.chat_service.ProviderGateway.generate_stream")
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_falls_back_to_estimated_usage(
        self, mock_resolve, mock_stream, user_a
    ):
        async def gen():
            yield ProviderChunk(text="Response")

        mock_stream.return_value = gen()
        conversation = await Conversation.objects.acreate(user=user_a, title="Existing")

        service = ChatService(repository=self.mock_repo)
        events = await self._collect_events(
            service,
            user=user_a,
            session_id=str(conversation.id),
            user_text="Hello",
            config=DEFAULT_CONFIG,
        )

        usage = events[-1].usage
        assert usage["prompt_tokens"] > 0
        assert usage["completion_tokens"] > 0
        assert "total_tokens" not in usage

    @pytest.mark.django_db(transaction=True)
    @patch("api.chat_service.ProviderGateway.generate_stream")
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_sets_title_on_untitled_session(
        self, mock_resolve, mock_stream, user_a
    ):
        async def gen():
            yield ProviderChunk(text="Answer")

        mock_stream.return_value = gen()
        conversation = await Conversation.objects.acreate(user=user_a)

        service = ChatService(repository=self.mock_repo)
        events = await self._collect_events(
            service,
            user=user_a,
            session_id=str(conversation.id),
            user_text="Hello world this is a test",
            config=DEFAULT_CONFIG,
        )

        assert events[-1].title == "Hello world this is a test"
        await conversation.arefresh_from_db()
        assert conversation.title == "Hello world this is a test"

    @pytest.mark.django_db(transaction=True)
    @patch("api.chat_service.ProviderGateway.generate_stream")
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_preserves_existing_title(self, mock_resolve, mock_stream, user_a):
        async def gen():
            yield ProviderChunk(text="Answer")

        mock_stream.return_value = gen()
        conversation = await Conversation.objects.acreate(user=user_a, title="Original")

        service = ChatService(repository=self.mock_repo)
        events = await self._collect_events(
            service,
            user=user_a,
            session_id=str(conversation.id),
            user_text="New question",
            config=DEFAULT_CONFIG,
        )

        assert events[-1].title is None
        await conversation.arefresh_from_db()
        assert conversation.title == "Original"

    @pytest.mark.django_db(transaction=True)
    @patch("api.chat_service.ProviderGateway.generate_stream")
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_updates_last_message_at(self, mock_resolve, mock_stream, user_a):
        async def gen():
            yield ProviderChunk(text="Answer")

        mock_stream.return_value = gen()
        conversation = await Conversation.objects.acreate(user=user_a, title="Existing")
        original_ts = conversation.last_message_at

        service = ChatService(repository=self.mock_repo)
        await self._collect_events(
            service,
            user=user_a,
            session_id=str(conversation.id),
            user_text="Hello",
            config=DEFAULT_CONFIG,
        )

        await conversation.arefresh_from_db()
        assert conversation.last_message_at > original_ts

    @patch.object(
        ChatService, "_resolve_api_key", side_effect=MissingApiKeyError("No key")
    )
    async def test_error_event_on_missing_api_key(self, mock_resolve):
        service = ChatService(repository=self.mock_repo)
        events = await self._collect_events(
            service,
            user=self.mock_user,
            session_id="test-session",
            user_text="Hello",
            config=DEFAULT_CONFIG,
        )

        assert len(events) == 1
        assert events[0].type == "error"
        assert events[0].error_code == "missing_api_key"

    async def test_error_event_on_empty_input(self):
        service = ChatService(repository=self.mock_repo)
        events = await self._collect_events(
            service,
            user=self.mock_user,
            session_id="test-session",
            user_text="",
            config=DEFAULT_CONFIG,
        )

        assert len(events) == 1
        assert events[0].type == "error"
        assert events[0].error_code == "invalid_input"

    @pytest.mark.django_db(transaction=True)
    @patch("api.chat_service.ProviderGateway.generate_stream")
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_error_event_on_provider_failure(
        self, mock_resolve, mock_stream, user_a
    ):
        async def gen():
            yield ProviderChunk(text="Hel")
            raise TemporaryProviderError("rate limited")

        mock_stream.return_value = gen()
        conversation = await Conversation.objects.acreate(user=user_a)

        service = ChatService(repository=self.mock_repo)
        events = await self._collect_events(
            service,
            user=user_a,
            session_id=str(conversation.id),
            user_text="Hello",
            config=DEFAULT_CONFIG,
        )

        assert len(events) == 2
        assert events[0] == StreamEvent(type="token", content="Hel")
        assert events[1].type == "error"
        assert events[1].error_code == "provider_temporary"

    @pytest.mark.django_db(transaction=True)
    @patch("api.chat_service.ProviderGateway.generate_stream")
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_unexpected_exception_yields_internal_error(
        self, mock_resolve, mock_stream, user_a
    ):
        async def gen():
            raise RuntimeError("boom")
            yield  # noqa: unreachable - makes this an async generator

        mock_stream.return_value = gen()
        conversation = await Conversation.objects.acreate(user=user_a)

        service = ChatService(repository=self.mock_repo)
        events = await self._collect_events(
            service,
            user=user_a,
            session_id=str(conversation.id),
            user_text="Hello",
            config=DEFAULT_CONFIG,
        )

        assert len(events) == 1
        assert events[0].type == "error"
        assert events[0].error_code == "internal_error"
        assert events[0].error_message == "Internal server error"


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
        config = replace(DEFAULT_CONFIG, compaction_threshold=1.0)
        system_tokens = self.counter.estimate_system_tokens(
            config.system_prompt, config.model
        )
        msg_tokens = self.counter.estimate_message_tokens(msg, config.model)
        total = system_tokens + msg_tokens + 24

        exact_boundary = replace(config, max_input_tokens=total)
        assert not self.service.should_compact(
            system_prompt=config.system_prompt,
            history=[],
            new_message=msg,
            config=exact_boundary,
        )

        one_over = replace(config, max_input_tokens=total - 1)
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
        config = replace(DEFAULT_CONFIG, compaction_model="gpt-5.4-mini")

        result = await self.service.compact(
            history=history,
            config=config,
            api_key="sk-test",
        )

        assert result == "Summary text."
        self.gateway.generate_stream.assert_called_once()
        call_messages = self.gateway.generate_stream.call_args[1]["messages"]
        assert len(call_messages) == 1
        assert "User: Hello" in call_messages[0].content
        assert "Assistant: Hi there" in call_messages[0].content

    async def test_compact_falls_back_to_main_model_when_compact_model_fails(self):
        async def _fake_stream():
            yield ProviderChunk(text="Fallback summary.")

        self.gateway.generate_stream.side_effect = [
            TemporaryProviderError("rate limited"),
            _fake_stream(),
        ]
        config = replace(DEFAULT_CONFIG, compaction_model="gpt-5.4-mini")

        result = await self.service.compact(
            history=[_msg("user", "Hello")],
            config=config,
            api_key="sk-test",
        )

        assert result == "Fallback summary."
        assert self.gateway.generate_stream.call_count == 2

    async def test_compact_returns_none_when_both_models_fail(self):
        self.gateway.generate_stream.side_effect = TemporaryProviderError(
            "rate limited"
        )
        config = replace(DEFAULT_CONFIG, compaction_model="gpt-5.4-mini")

        result = await self.service.compact(
            history=[_msg("user", "Hello")],
            config=config,
            api_key="sk-test",
        )

        assert result is None

    async def test_summarize_dedups_when_models_are_identical(self):
        async def _fake_stream():
            yield ProviderChunk(text="Summary.")

        self.gateway.generate_stream.return_value = _fake_stream()
        config = replace(DEFAULT_CONFIG, compaction_model="gpt-5.5")

        result = await self.service.compact(
            history=[_msg("user", "Hello")],
            config=config,
            api_key="sk-test",
        )

        assert result == "Summary."
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

    async def test_compact_stream_does_not_yield_partial_on_fallback(self):
        async def _failing_stream():
            yield ProviderChunk(text="Part")
            raise TemporaryProviderError("model 1 failed")

        async def _good_stream():
            yield ProviderChunk(text="Full summary.")

        self.gateway.generate_stream.side_effect = [
            _failing_stream(),
            _good_stream(),
        ]
        config = replace(DEFAULT_CONFIG, compaction_model="gpt-5.4-mini")

        chunks = []
        async for chunk in self.service.compact_stream(
            history=[_msg("user", "Hello")],
            config=config,
            api_key="sk-test",
        ):
            chunks.append(chunk)

        text_chunks = [c for c in chunks if c.text]
        assert len(text_chunks) == 1
        assert text_chunks[0].text == "Full summary."
        assert self.gateway.generate_stream.call_count == 2


class TestChatServiceCompaction:
    def setup_method(self):
        self.mock_repo = MagicMock()
        self.mock_repo.list_messages = AsyncMock(return_value=[])
        self.mock_repo.append_message = AsyncMock(
            side_effect=lambda **kwargs: MagicMock(id=f"msg-{kwargs['role']}")
        )
        self.mock_repo.apply_compaction = AsyncMock(
            return_value=MagicMock(id="summary-id")
        )
        self.mock_user = MagicMock()
        self.mock_session = MagicMock()
        self.mock_session.asave = AsyncMock()
        self.mock_session.arefresh_from_db = AsyncMock()
        self._session_patch = patch(
            "api.chat_service.Conversation.objects.aget",
            new=AsyncMock(return_value=self.mock_session),
        )
        self._session_patch.start()

    def teardown_method(self):
        self._session_patch.stop()

    @patch.object(CompactionService, "should_compact", return_value=True)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_prepare_generation_triggers_compaction_and_returns_summary(
        self, mock_resolve, mock_should
    ):
        async def _fake_compact_stream():
            yield ProviderChunk(text="This is the conversation summary.")

        mock_compact_stream = MagicMock(return_value=_fake_compact_stream())
        with patch.object(CompactionService, "compact_stream", mock_compact_stream):
            history = [
                _msg("user", "question one"),
                _msg("assistant", "answer one"),
                _msg("user", "question two"),
                _msg("assistant", "answer two"),
            ]
            summary_msg = _msg(
                "assistant",
                "This is the conversation summary.",
                meta={"is_compaction_summary": True},
            )
            self.mock_repo.list_messages.side_effect = [history, [summary_msg]]
            service = ChatService(repository=self.mock_repo)
            prep = await service._prepare_generation(
                user=self.mock_user,
                session_id="test-session",
                user_text="Hello",
                config=DEFAULT_CONFIG,
            )

        assert prep.compaction_summary == "This is the conversation summary."
        assert prep.compaction_message_id == "summary-id"
        assert prep.compaction_tokens == ["This is the conversation summary."]
        self.mock_repo.apply_compaction.assert_called_once()
        apply_call = self.mock_repo.apply_compaction.call_args[1]
        assert apply_call["session"] == self.mock_session
        assert apply_call["summary"] == "This is the conversation summary."
        assert self.mock_repo.list_messages.call_count == 2
        assert prep.messages[0].meta.get("is_compaction_summary") is True

    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_prepare_generation_falls_back_to_chunk_truncate(self, mock_resolve):
        async def _empty_gen():
            if False:
                yield

        mock_compact_stream = MagicMock(return_value=_empty_gen())
        with patch.object(CompactionService, "compact_stream", mock_compact_stream):
            long_msg = _msg("user", "word " * 400)
            history = [long_msg] * 6
            self.mock_repo.list_messages.return_value = history
            service = ChatService(repository=self.mock_repo)
            config = replace(
                DEFAULT_CONFIG,
                max_input_tokens=400,
                compaction_threshold=0.5,
            )
            prep = await service._prepare_generation(
                user=self.mock_user,
                session_id="test-session",
                user_text="Hello",
                config=config,
            )

        assert prep.compaction_summary is None
        assert prep.compaction_tokens is None
        self.mock_repo.apply_compaction.assert_not_called()
        assert len(prep.messages) == 2
        assert prep.messages[0].content.startswith("word ")

    @patch.object(CompactionService, "should_compact", return_value=False)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_prepare_generation_no_compaction_when_under_threshold(
        self, mock_resolve, mock_should
    ):
        history = [
            _msg("user", "question one"),
            _msg("assistant", "answer one"),
        ]
        self.mock_repo.list_messages.return_value = history
        service = ChatService(repository=self.mock_repo)
        prep = await service._prepare_generation(
            user=self.mock_user,
            session_id="test-session",
            user_text="Hello",
            config=DEFAULT_CONFIG,
        )

        assert prep.compaction_summary is None
        self.mock_repo.apply_compaction.assert_not_called()
        assert len(prep.messages) == 3
        assert prep.messages[0].content == "question one"
        assert prep.messages[1].content == "answer one"
        assert prep.messages[2].content == "Hello"

    @patch.object(CompactionService, "should_compact", return_value=False)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    async def test_prepare_generation_preserves_existing_summary_without_new_compaction(
        self, mock_resolve, mock_should
    ):
        history = [
            _msg("assistant", "Prior summary", meta={"is_compaction_summary": True}),
            _msg("user", "follow up question"),
            _msg("assistant", "follow up answer"),
        ]
        self.mock_repo.list_messages.return_value = history
        service = ChatService(repository=self.mock_repo)
        prep = await service._prepare_generation(
            user=self.mock_user,
            session_id="test-session",
            user_text="Hello",
            config=DEFAULT_CONFIG,
        )

        assert prep.compaction_summary is None
        self.mock_repo.apply_compaction.assert_not_called()
        assert len(prep.messages) == 4
        assert prep.messages[0].meta.get("is_compaction_summary") is True
        assert prep.messages[0].content == "Prior summary"

    @patch.object(CompactionService, "should_compact", return_value=True)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-test")
    @patch("api.chat_service.ProviderGateway.generate_stream")
    async def test_stream_yields_compaction_events_when_triggered(
        self, mock_stream, mock_resolve, mock_should
    ):
        async def _fake_compact_stream():
            yield ProviderChunk(text="Sum")
            yield ProviderChunk(text="mary.")

        mock_compact_stream = MagicMock(return_value=_fake_compact_stream())
        with patch.object(CompactionService, "compact_stream", mock_compact_stream):

            async def gen():
                yield ProviderChunk(text="Answer")

            mock_stream.return_value = gen()
            history = [
                _msg("user", "question one"),
                _msg("assistant", "answer one"),
            ]
            summary_msg = _msg(
                "assistant", "Summary.", meta={"is_compaction_summary": True}
            )
            self.mock_repo.list_messages.side_effect = [history, [summary_msg]]
            service = ChatService(repository=self.mock_repo)
            events = [
                e
                async for e in service.generate_reply_stream(
                    user=self.mock_user,
                    session_id="test-session",
                    user_text="Hello",
                    config=DEFAULT_CONFIG,
                )
            ]

        assert len(events) == 5
        assert events[0].type == "token"
        assert events[0].content == "Sum"
        assert events[1].type == "token"
        assert events[1].content == "mary."
        assert events[2].type == "compaction_done"
        assert events[2].message_id == "summary-id"
        assert events[3].type == "token"
        assert events[3].content == "Answer"
        assert events[4].type == "done"
