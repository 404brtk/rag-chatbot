from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from rest_framework import status

from api.document_service import SearchResult
from api.models import Conversation


@pytest.fixture
def mock_document_service():
    with patch("api.chat_service.DocumentService") as mock:
        instance = mock.return_value
        instance.search.return_value = []
        yield instance


def _mock_openai_response(mock_openai_class, content="Hello!", usage=None):
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=content))]
    mock_response.usage = usage
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


@pytest.mark.django_db
class TestRAGIntegration:
    @patch("api.chat_service.OpenAI")
    def test_message_without_document_ids_ignores_rag(
        self, mock_openai_class, auth_client_a, user_a, mock_document_service, api_key
    ):
        mock_client = _mock_openai_response(mock_openai_class)

        conversation = Conversation.objects.create(user=user_a, title="Test")
        url = reverse(
            "conversation-messages", kwargs={"conversation_pk": conversation.pk}
        )
        response = auth_client_a.post(
            url,
            {"content": "Hi", "provider": "openai"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        mock_document_service.search.assert_not_called()

        call_args = mock_client.chat.completions.create.call_args[1]
        user_messages = [m for m in call_args["messages"] if m["role"] == "user"]
        assert len(user_messages) == 1
        assert "<CONTEXT>" not in user_messages[-1]["content"]

    @patch("api.chat_service.OpenAI")
    def test_message_with_empty_document_ids_searches_all(
        self, mock_openai_class, auth_client_a, user_a, mock_document_service, api_key
    ):
        mock_client = _mock_openai_response(mock_openai_class)

        mock_document_service.search.return_value = [
            SearchResult(
                chunk_content="This is the context.",
                document_id="doc1",
                document_filename="test.txt",
                chunk_index=0,
                distance=0.1,
            )
        ]

        conversation = Conversation.objects.create(user=user_a, title="Test")
        url = reverse(
            "conversation-messages", kwargs={"conversation_pk": conversation.pk}
        )
        response = auth_client_a.post(
            url,
            {
                "content": "What is in the doc?",
                "provider": "openai",
                "document_ids": [],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED

        mock_document_service.search.assert_called_once()
        call_kwargs = mock_document_service.search.call_args[1]
        assert call_kwargs["query"] == "What is in the doc?"
        assert call_kwargs["document_ids"] is None

        call_args = mock_client.chat.completions.create.call_args[1]
        user_messages = [m for m in call_args["messages"] if m["role"] == "user"]
        last_content = user_messages[-1]["content"]
        assert "<CONTEXT>" in last_content
        assert "This is the context." in last_content
        assert "<QUESTION>" in last_content
        assert "What is in the doc?" in last_content

    @patch("api.chat_service.OpenAI")
    def test_message_with_specific_document_ids(
        self, mock_openai_class, auth_client_a, user_a, mock_document_service, api_key
    ):
        mock_client = _mock_openai_response(mock_openai_class)

        mock_document_service.search.return_value = [
            SearchResult(
                chunk_content="Specific context.",
                document_id="uuid-1",
                document_filename="specific.txt",
                chunk_index=0,
                distance=0.05,
            )
        ]

        conversation = Conversation.objects.create(user=user_a, title="Test")
        url = reverse(
            "conversation-messages", kwargs={"conversation_pk": conversation.pk}
        )
        response = auth_client_a.post(
            url,
            {
                "content": "What is in the doc?",
                "provider": "openai",
                "document_ids": ["uuid-1", "uuid-2"],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED

        mock_document_service.search.assert_called_once()
        call_kwargs = mock_document_service.search.call_args[1]
        assert call_kwargs["document_ids"] == ["uuid-1", "uuid-2"]

        call_args = mock_client.chat.completions.create.call_args[1]
        user_messages = [m for m in call_args["messages"] if m["role"] == "user"]
        last_content = user_messages[-1]["content"]
        assert "<CONTEXT>" in last_content
        assert "Specific context." in last_content

    def test_message_with_invalid_document_ids_type(self, auth_client_a, user_a):
        conversation = Conversation.objects.create(user=user_a, title="Test")
        url = reverse(
            "conversation-messages", kwargs={"conversation_pk": conversation.pk}
        )
        response = auth_client_a.post(
            url,
            {"content": "Hi", "document_ids": "not-a-list"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "document_ids" in response.json()
