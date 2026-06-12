from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from api.models import Conversation, UserApiKey
from api.repositories import StoredMessage
from api.chat_service import ChatService
from api.compaction_service import CompactionService
from api.provider_gateway import ProviderGateway
from api.llm_config import (
    GenerationResult,
    InvalidInputError,
    MissingApiKeyError,
    PermanentProviderError,
    ProviderChunk,
    StreamEvent,
    TemporaryProviderError,
)
from api.document_service import SearchResult

from .conftest import DEFAULT_CONFIG, _msg


class TestChatServiceStatic:
    def test_formats_single_chunk_with_label_and_source(self):
        results = [
            SearchResult(
                chunk_content="Chunk content here.",
                document_id="abc",
                document_filename="test.txt",
                chunk_index=0,
                score=0.1,
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

    @patch("api.chat_service.ProviderGateway.discover_llamacpp_models")
    async def test_returns_both_providers(self, mock_discover):
        mock_discover.return_value = [
            {"id": "local-model", "object": "model", "owned_by": "llamacpp"}
        ]

        models = await ChatService.get_available_models()

        assert "openai" in models
        assert "llamacpp" in models
        assert models["llamacpp"] == ["local-model"]

    @patch("api.chat_service.ProviderGateway.discover_llamacpp_models")
    async def test_handles_llamacpp_failure_gracefully(self, mock_discover):
        mock_discover.side_effect = Exception("Connection refused")

        models = await ChatService.get_available_models()

        assert "openai" in models
        assert "llamacpp" not in models


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
        self.mock_repo.truncate_oldest_messages = AsyncMock()
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
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
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
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    async def test_strips_whitespace_from_user_text(self, mock_resolve, mock_generate):
        mock_generate.return_value = GenerationResult(
            text="Hi!",
            provider="openai",
            model="gpt",
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
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    async def test_passes_history_and_new_message_to_window(
        self, mock_resolve, mock_generate
    ):
        mock_generate.return_value = GenerationResult(
            text="Hi!",
            provider="openai",
            model="gpt",
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
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    async def test_appends_message_pair_to_repository(
        self, mock_resolve, mock_generate
    ):
        mock_generate.return_value = GenerationResult(
            text="Response text",
            provider="openai",
            model="gpt",
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
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
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
            model="gpt",
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
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    @patch("api.chat_service.DocumentService")
    async def test_includes_context_chunks_and_raw_question_on_user_message(
        self, mock_doc_svc_cls, mock_resolve, mock_generate
    ):
        mock_doc_svc_cls.return_value.search.return_value = [
            SearchResult("Info A", "d1", "a.txt", 0, 0.1),
            SearchResult("Info B", "d2", "b.txt", 3, 0.2),
        ]
        mock_generate.return_value = GenerationResult(
            text="Answer.",
            provider="openai",
            model="gpt",
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

        call_kwargs = self.mock_repo.append_message_pair.call_args[1]
        assert call_kwargs["user_raw_question"] == "Question"
        assert len(call_kwargs["user_context"]) == 2
        assert call_kwargs["user_context"][0]["index"] == 1
        assert call_kwargs["user_context"][0]["content"] == "Info A"
        assert call_kwargs["user_context"][0]["document_filename"] == "a.txt"
        assert call_kwargs["user_context"][0]["document_id"] == "d1"
        assert call_kwargs["user_context"][0]["chunk_index"] == 0
        assert call_kwargs["user_context"][0]["score"] == 0.1
        assert call_kwargs["user_context"][1]["index"] == 2
        assert call_kwargs["user_context"][1]["content"] == "Info B"

    @patch("api.chat_service.ProviderGateway.generate", new_callable=AsyncMock)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    @patch("api.chat_service.DocumentService")
    async def test_does_not_inject_context_when_document_ids_is_none(
        self, mock_doc_svc_cls, mock_resolve, mock_generate
    ):
        mock_generate.return_value = GenerationResult(
            text="Answer.",
            provider="openai",
            model="gpt",
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
        assert call_kwargs["user_context"] is None
        assert call_kwargs["user_raw_question"] == "Hello"
        mock_doc_svc_cls.return_value.search.assert_not_called()

    @patch("api.chat_service.ProviderGateway.generate", new_callable=AsyncMock)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    @patch("api.chat_service.DocumentService")
    async def test_skips_context_injection_when_search_returns_no_results(
        self, mock_doc_svc_cls, mock_resolve, mock_generate
    ):
        mock_doc_svc_cls.return_value.search.return_value = []
        mock_generate.return_value = GenerationResult(
            text="Answer.",
            provider="openai",
            model="gpt",
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
        assert call_kwargs["user_context"] is None

    @patch("api.chat_service.UserApiKey.objects.aget")
    async def test_resolve_api_key_skips_db_for_llamacpp(self, mock_get):
        service = ChatService(repository=self.mock_repo)
        key = await service._resolve_api_key(self.mock_user, "llamacpp")
        assert key == "llamacpp"
        mock_get.assert_not_called()

    @patch("api.chat_service.UserApiKey.objects.aget")
    async def test_raises_missing_api_key_error_when_no_key_set(self, mock_get):
        mock_get.side_effect = UserApiKey.DoesNotExist
        service = ChatService(repository=self.mock_repo)
        with pytest.raises(MissingApiKeyError, match="No API key configured"):
            await service._resolve_api_key(self.mock_user, "openai")

    @patch("api.chat_service.ProviderGateway.generate", new_callable=AsyncMock)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    @patch("api.chat_service.DocumentService")
    async def test_query_refinement_success(
        self, mock_doc_svc_cls, mock_resolve, mock_generate
    ):
        refinement_result = GenerationResult(
            text='{"detected_language": "polish", "refined_english_query": "search", "refined_polish_query": "wyszukaj"}',
            provider="openai",
            model="gpt",
            input_tokens=10,
            output_tokens=5,
            usage={},
            model_input=[],
        )
        answer_result = GenerationResult(
            text="Mocked LLM Answer.",
            provider="openai",
            model="gpt",
            input_tokens=10,
            output_tokens=5,
            usage={},
            model_input=[],
        )
        mock_generate.side_effect = [refinement_result, answer_result]
        mock_doc_svc_cls.return_value.embedding_service.embed_query.return_value = [
            0.1,
            0.2,
            0.3,
        ]
        mock_doc_svc_cls.return_value.search.return_value = [
            SearchResult("Relevant info.", "doc-1", "docs.md", 0, 0.1)
        ]
        self.mock_repo.list_messages.return_value = []
        self.mock_repo.append_message_pair.return_value = (
            MagicMock(id="u-id"),
            MagicMock(id="a-id"),
        )

        service = ChatService(repository=self.mock_repo)
        await service.generate_reply(
            user=self.mock_user,
            session_id="test-session",
            user_text="wyszukaj",
            config=DEFAULT_CONFIG,
            document_ids=["doc-1"],
        )

        mock_doc_svc_cls.return_value.search.assert_called_once_with(
            user=self.mock_user,
            query="wyszukaj",
            query_embedding=[0.1, 0.2, 0.3],
            refined_english_query="search",
            refined_polish_query="wyszukaj",
            document_ids=["doc-1"],
        )

        refine_call_kwargs = mock_generate.call_args_list[0][1]
        assert "response_format" in refine_call_kwargs
        fmt = refine_call_kwargs["response_format"]
        assert fmt["type"] == "json_schema"
        assert fmt["json_schema"]["name"] == "QueryRefinement"
        assert fmt["json_schema"]["strict"] is True
        schema = fmt["json_schema"]["schema"]
        assert "title" not in schema
        assert schema["properties"]["detected_language"]["type"] == "string"
        assert schema["properties"]["refined_english_query"]["type"] == "string"
        assert schema["properties"]["refined_polish_query"]["type"] == "string"
        assert "detected_language" in schema["required"]
        assert "refined_english_query" in schema["required"]
        assert "refined_polish_query" in schema["required"]
        assert schema["additionalProperties"] is False

    @patch("api.chat_service.ProviderGateway.generate", new_callable=AsyncMock)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    @patch("api.chat_service.DocumentService")
    async def test_query_refinement_failure_fallback(
        self, mock_doc_svc_cls, mock_resolve, mock_generate
    ):
        refinement_result = GenerationResult(
            text="This is not JSON!",
            provider="openai",
            model="gpt",
            input_tokens=10,
            output_tokens=5,
            usage={},
            model_input=[],
        )
        answer_result = GenerationResult(
            text="Mocked LLM Answer.",
            provider="openai",
            model="gpt",
            input_tokens=10,
            output_tokens=5,
            usage={},
            model_input=[],
        )
        mock_generate.side_effect = [refinement_result, answer_result]
        mock_doc_svc_cls.return_value.embedding_service.embed_query.return_value = [
            0.1,
            0.2,
            0.3,
        ]
        mock_doc_svc_cls.return_value.search.return_value = []
        self.mock_repo.list_messages.return_value = []
        self.mock_repo.append_message_pair.return_value = (
            MagicMock(id="u-id"),
            MagicMock(id="a-id"),
        )

        service = ChatService(repository=self.mock_repo)
        await service.generate_reply(
            user=self.mock_user,
            session_id="test-session",
            user_text="python",
            config=DEFAULT_CONFIG,
            document_ids=["doc-1"],
        )

        mock_doc_svc_cls.return_value.search.assert_called_once_with(
            user=self.mock_user,
            query="python",
            query_embedding=[0.1, 0.2, 0.3],
            refined_english_query="python",
            refined_polish_query="python",
            document_ids=["doc-1"],
        )

    @patch("api.chat_service.ProviderGateway.generate", new_callable=AsyncMock)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    @patch("api.chat_service.DocumentService")
    async def test_query_refinement_validation_error_fallback(
        self, mock_doc_svc_cls, mock_resolve, mock_generate
    ):
        refinement_result = GenerationResult(
            text='{"detected_language": "polish", "refined_english_query": "python"}',
            provider="openai",
            model="gpt",
            input_tokens=10,
            output_tokens=5,
            usage={},
            model_input=[],
        )
        answer_result = GenerationResult(
            text="Mocked LLM Answer.",
            provider="openai",
            model="gpt",
            input_tokens=10,
            output_tokens=5,
            usage={},
            model_input=[],
        )
        mock_generate.side_effect = [refinement_result, answer_result]
        mock_doc_svc_cls.return_value.embedding_service.embed_query.return_value = [
            0.1,
            0.2,
            0.3,
        ]
        mock_doc_svc_cls.return_value.search.return_value = []
        self.mock_repo.list_messages.return_value = []
        self.mock_repo.append_message_pair.return_value = (
            MagicMock(id="u-id"),
            MagicMock(id="a-id"),
        )

        service = ChatService(repository=self.mock_repo)
        await service.generate_reply(
            user=self.mock_user,
            session_id="test-session",
            user_text="python",
            config=DEFAULT_CONFIG,
            document_ids=["doc-1"],
        )

        mock_doc_svc_cls.return_value.search.assert_called_once_with(
            user=self.mock_user,
            query="python",
            query_embedding=[0.1, 0.2, 0.3],
            refined_english_query="python",
            refined_polish_query="python",
            document_ids=["doc-1"],
        )


class TestChatServiceGenerateReplyStream:
    def setup_method(self):
        self.mock_repo = MagicMock()
        self.mock_repo.list_messages = AsyncMock(return_value=[])
        self.mock_repo.append_message = AsyncMock(
            side_effect=lambda **kwargs: MagicMock(
                id=f"msg-{kwargs['role']}", adelete=AsyncMock()
            )
        )
        self.mock_repo.apply_compaction = AsyncMock(
            return_value=MagicMock(id="summary-id")
        )
        self.mock_repo.truncate_oldest_messages = AsyncMock()
        self.mock_user = MagicMock()

    async def _collect_events(self, service, **kwargs):
        return [e async for e in service.generate_reply_stream(**kwargs)]

    @pytest.mark.django_db(transaction=True)
    @patch("api.chat_service.ProviderGateway.generate_stream")
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
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
        assert events[2].model == "gpt"
        assert events[2].sent_messages == [{"role": "user", "content": "Hello"}]

    @pytest.mark.django_db(transaction=True)
    @patch("api.chat_service.ProviderGateway.generate_stream")
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
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
        assert user_call["provider"] == "openai"
        assert user_call["model"] == "gpt"
        assert user_call["raw_question"] == "Hello"

        assistant_call = self.mock_repo.append_message.call_args_list[1][1]
        assert assistant_call["role"] == "assistant"
        assert assistant_call["content"] == "Response"
        assert assistant_call["provider"] == "openai"
        assert assistant_call["model"] == "gpt"

    @pytest.mark.django_db(transaction=True)
    @patch("api.chat_service.ProviderGateway.generate_stream")
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
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
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
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
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
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
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
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
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
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
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
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
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    async def test_unexpected_exception_yields_internal_error(
        self, mock_resolve, mock_stream, user_a
    ):
        async def gen():
            raise RuntimeError("boom")
            yield  # makes this an async generator

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

    @pytest.mark.django_db(transaction=True)
    @patch("api.chat_service.ProviderGateway.generate_stream")
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    async def test_deletes_user_message_on_stream_failure(
        self, mock_resolve, mock_stream, user_a
    ):
        async def gen():
            raise TemporaryProviderError("boom")
            yield

        mock_stream.return_value = gen()
        conversation = await Conversation.objects.acreate(user=user_a)

        mock_user_msg = AsyncMock()
        self.mock_repo.append_message = AsyncMock(return_value=mock_user_msg)

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
        mock_user_msg.adelete.assert_called_once()


class TestChatServiceCompaction:
    def setup_method(self):
        self.mock_repo = MagicMock()
        self.mock_repo.list_messages = AsyncMock(return_value=[])
        self.mock_repo.append_message = AsyncMock(
            side_effect=lambda **kwargs: MagicMock(
                id=f"msg-{kwargs['role']}", adelete=AsyncMock()
            )
        )
        self.mock_repo.apply_compaction = AsyncMock(
            return_value=MagicMock(id="summary-id")
        )
        self.mock_repo.truncate_oldest_messages = AsyncMock()
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
    @patch.object(
        ChatService, "_resolve_api_key", side_effect=["sk-chat", "sk-compaction"]
    )
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
                is_compaction_summary=True,
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
        assert apply_call["provider"] == "openai"
        assert apply_call["model"] == "gpt"
        assert self.mock_repo.list_messages.call_count == 2
        assert prep.messages[0].is_compaction_summary is True

    @patch.object(ProviderGateway, "discover_llamacpp_context", return_value=4096)
    @patch.object(CompactionService, "should_compact", return_value=True)
    @patch.object(ChatService, "_resolve_api_key", return_value="llamacpp")
    async def test_compaction_summary_records_provider_and_model_for_llamacpp(
        self, mock_resolve, mock_should, mock_discover
    ):
        async def _fake_compact_stream():
            yield ProviderChunk(
                text="Summary from llama.cpp.",
                provider="llamacpp",
                model="gemma-4-E4B-it",
            )

        mock_compact_stream = MagicMock(return_value=_fake_compact_stream())
        with patch.object(CompactionService, "compact_stream", mock_compact_stream):
            history = [_msg("user", "question one")]
            summary_msg = _msg(
                "assistant",
                "Summary from llama.cpp.",
                is_compaction_summary=True,
            )
            self.mock_repo.list_messages.side_effect = [history, [summary_msg]]
            service = ChatService(repository=self.mock_repo)
            config = replace(
                DEFAULT_CONFIG,
                provider="llamacpp",
                model="gemma-4-E4B-it",
                compaction_provider="llamacpp",
                compaction_model="gemma-4-E4B-it",
            )
            await service._prepare_generation(
                user=self.mock_user,
                session_id="test-session",
                user_text="Hello",
                config=config,
            )

        apply_call = self.mock_repo.apply_compaction.call_args[1]
        assert apply_call["provider"] == "llamacpp"
        assert apply_call["model"] == "gemma-4-E4B-it"

    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
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
        self.mock_repo.truncate_oldest_messages.assert_called_once_with(
            session_id="test-session",
            count=5,
        )
        assert len(prep.messages) == 2
        assert prep.messages[0].content.startswith("word ")

    @patch.object(CompactionService, "should_compact", return_value=False)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
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
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    async def test_prepare_generation_preserves_existing_summary_without_new_compaction(
        self, mock_resolve, mock_should
    ):
        history = [
            _msg("assistant", "Prior summary", is_compaction_summary=True),
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
        assert prep.messages[0].is_compaction_summary is True
        assert prep.messages[0].content == "Prior summary"

    @patch.object(CompactionService, "should_compact", return_value=True)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
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
            summary_msg = _msg("assistant", "Summary.", is_compaction_summary=True)
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

        assert len(events) == 3
        assert events[0].type == "compaction_done"
        assert events[0].message_id == "summary-id"
        assert events[1].type == "token"
        assert events[1].content == "Answer"
        assert events[2].type == "done"

        self.mock_repo.apply_compaction.assert_called_once()
        apply_call = self.mock_repo.apply_compaction.call_args[1]
        assert apply_call["provider"] == "openai"
        assert apply_call["model"] == "gpt"

    @patch.object(ProviderGateway, "discover_llamacpp_context", return_value=4096)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    @patch.object(CompactionService, "should_compact", return_value=True)
    async def test_prepare_generation_clamps_max_input_tokens_for_llamacpp(
        self, mock_should, mock_resolve, mock_discover
    ):
        config = replace(DEFAULT_CONFIG, provider="llamacpp", max_input_tokens=32768)
        history = [_msg("user", "Hello")]
        self.mock_repo.list_messages.return_value = history
        service = ChatService(repository=self.mock_repo)

        async def _fake_compact():
            yield ProviderChunk(text="Summary.")

        with patch.object(
            CompactionService, "compact_stream", return_value=_fake_compact()
        ):
            await service._prepare_generation(
                user=self.mock_user,
                session_id="test-session",
                user_text="Hello",
                config=config,
            )

        mock_discover.assert_called_once()
        call_config = mock_should.call_args[1]["config"]
        assert call_config.max_input_tokens == 4096

    @patch.object(
        ProviderGateway,
        "discover_llamacpp_context",
        side_effect=httpx.ConnectError("Connection refused"),
    )
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    async def test_prepare_generation_propagates_discovery_failure(
        self, mock_resolve, mock_discover
    ):
        config = replace(DEFAULT_CONFIG, provider="llamacpp", max_input_tokens=4096)
        self.mock_repo.list_messages.return_value = [_msg("user", "Hello")]
        service = ChatService(repository=self.mock_repo)

        with pytest.raises(httpx.ConnectError, match="Connection refused"):
            await service._prepare_generation(
                user=self.mock_user,
                session_id="test-session",
                user_text="Hello",
                config=config,
            )

    @patch.object(ProviderGateway, "discover_llamacpp_context", return_value=8192)
    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    @patch.object(CompactionService, "should_compact", return_value=True)
    async def test_prepare_generation_skips_clamp_when_within_context(
        self, mock_should, mock_resolve, mock_discover
    ):
        config = replace(DEFAULT_CONFIG, provider="llamacpp", max_input_tokens=4096)
        history = [_msg("user", "Hello")]
        self.mock_repo.list_messages.return_value = history
        service = ChatService(repository=self.mock_repo)

        async def _fake_compact():
            yield ProviderChunk(text="Summary.")

        with patch.object(
            CompactionService, "compact_stream", return_value=_fake_compact()
        ):
            await service._prepare_generation(
                user=self.mock_user,
                session_id="test-session",
                user_text="Hello",
                config=config,
            )

        call_config = mock_should.call_args[1]["config"]
        assert call_config.max_input_tokens == 4096

    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    @patch.object(CompactionService, "should_compact", return_value=False)
    async def test_prepare_generation_adjusts_max_output_tokens_dynamically(
        self, mock_should, mock_resolve
    ):
        config = replace(
            DEFAULT_CONFIG, model="gpt-4", max_input_tokens=600, max_output_tokens=500
        )
        history = [_msg("user", "word " * 150)]
        self.mock_repo.list_messages.return_value = history
        service = ChatService(repository=self.mock_repo)
        prep = await service._prepare_generation(
            user=self.mock_user,
            session_id="test-session",
            user_text="Hello",
            config=config,
        )
        assert prep.config.max_output_tokens == 359

    @patch.object(ChatService, "_resolve_api_key", return_value="sk-chat")
    @patch.object(CompactionService, "should_compact", return_value=True)
    async def test_prepare_generation_skips_summarization_when_compaction_disabled(
        self, mock_should, mock_resolve
    ):
        config = replace(
            DEFAULT_CONFIG,
            compaction_enabled=False,
            max_input_tokens=400,
            compaction_threshold=0.5,
        )
        long_msg = _msg("user", "word " * 400)
        history = [long_msg] * 6
        self.mock_repo.list_messages.return_value = history
        service = ChatService(repository=self.mock_repo)
        prep = await service._prepare_generation(
            user=self.mock_user,
            session_id="test-session",
            user_text="Hello",
            config=config,
        )
        assert prep.compaction_summary is None
        self.mock_repo.apply_compaction.assert_not_called()
        self.mock_repo.truncate_oldest_messages.assert_called_once_with(
            session_id="test-session",
            count=5,
        )
        assert len(prep.messages) == 2
