import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status

from api.models import Conversation, Message, UserApiKey
from api.repositories import StoredMessage
from api.chat_service import (
    GenerationResult,
    PermanentProviderError,
    TemporaryProviderError,
)

User = get_user_model()


def messages_url(conversation_pk):
    return f"/api/conversations/{conversation_pk}/messages/"


@pytest.fixture
def conversation_a(user_a):
    return Conversation.objects.create(user=user_a, title="Alice's chat")


@pytest.fixture
def conversation_b(user_b):
    return Conversation.objects.create(user=user_b, title="Bob's chat")


@pytest.mark.django_db
class TestMessageCreation:
    @patch("api.chat_service.OpenAI")
    @patch("api.chat_service.ProviderGateway.generate")
    def test_create_message_in_own_conversation(
        self, mock_generate, mock_openai, auth_client_a, conversation_a, user_a
    ):
        UserApiKey.objects.create(
            user=user_a, provider="openai", encrypted_key="sk-test"
        )
        mock_generate.return_value = GenerationResult(
            text="Mocked AI response",
            provider="openai",
            model="gpt-5.5",
            input_tokens=10,
            output_tokens=20,
            usage={"prompt_tokens": 10, "completion_tokens": 20},
            model_input=[StoredMessage(role="user", content="Hello")],
        )

        url = messages_url(conversation_a.id)
        response = auth_client_a.post(url, {"content": "Hello"})
        assert response.status_code == status.HTTP_201_CREATED

        assert response.data["role"] == "ai"
        assert response.data["content"] == "Mocked AI response"
        assert response.data["provider"] == "openai"
        assert "usage" in response.data

        assert Message.objects.filter(conversation=conversation_a).count() == 2

        user_msg = Message.objects.filter(
            conversation=conversation_a, role="user"
        ).first()
        assert user_msg.content == "Hello"

        ai_msg = Message.objects.filter(conversation=conversation_a, role="ai").first()
        assert ai_msg.content == "Mocked AI response"
        assert response.data["id"] == str(ai_msg.id)

    def test_create_message_empty_content_returns_400(
        self, auth_client_a, conversation_a
    ):
        url = messages_url(conversation_a.id)
        response = auth_client_a.post(url, {"content": ""})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_message_missing_content_returns_400(
        self, auth_client_a, conversation_a
    ):
        url = messages_url(conversation_a.id)
        response = auth_client_a.post(url, {})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_create_message_in_other_users_conversation(
        self, auth_client_a, conversation_b
    ):
        url = messages_url(conversation_b.id)
        response = auth_client_a.post(url, {"content": "Sneaky"})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert Message.objects.count() == 0

    def test_create_message_in_nonexistent_conversation_returns_404(
        self, auth_client_a
    ):
        fake_id = uuid.uuid4()
        url = messages_url(fake_id)
        response = auth_client_a.post(url, {"content": "Hello"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("api.chat_service.OpenAI")
    @patch("api.chat_service.ProviderGateway.generate")
    def test_ai_temporary_error_returns_503(
        self, mock_generate, mock_openai, auth_client_a, conversation_a, user_a
    ):
        UserApiKey.objects.create(
            user=user_a, provider="openai", encrypted_key="sk-test"
        )
        mock_generate.side_effect = TemporaryProviderError("rate limited")
        url = messages_url(conversation_a.id)
        response = auth_client_a.post(url, {"content": "Hello"})
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    @patch("api.chat_service.OpenAI")
    @patch("api.chat_service.ProviderGateway.generate")
    def test_ai_permanent_error_returns_502(
        self, mock_generate, mock_openai, auth_client_a, conversation_a, user_a
    ):
        UserApiKey.objects.create(
            user=user_a, provider="openai", encrypted_key="sk-test"
        )
        mock_generate.side_effect = PermanentProviderError("bad request")
        url = messages_url(conversation_a.id)
        response = auth_client_a.post(url, {"content": "Hello"})
        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    def test_missing_api_key_returns_403(self, auth_client_a, conversation_a):
        url = messages_url(conversation_a.id)
        response = auth_client_a.post(url, {"content": "Hello"})
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "No API key configured" in response.data["error"]


@pytest.mark.django_db
class TestMessageListing:
    def test_list_messages_in_own_conversation(self, auth_client_a, conversation_a):
        Message.objects.create(conversation=conversation_a, role="user", content="msg1")
        Message.objects.create(conversation=conversation_a, role="ai", content="msg2")

        url = messages_url(conversation_a.id)
        response = auth_client_a.get(url)
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 2

    def test_messages_ordered_by_created_at_asc(self, auth_client_a, conversation_a):
        Message.objects.create(
            conversation=conversation_a, role="user", content="first"
        )
        Message.objects.create(conversation=conversation_a, role="ai", content="second")

        url = messages_url(conversation_a.id)
        response = auth_client_a.get(url)
        results = response.data["results"]
        assert results[0]["content"] == "first"
        assert results[1]["content"] == "second"

    def test_cannot_list_messages_in_other_users_conversation(
        self, auth_client_a, conversation_b
    ):
        Message.objects.create(
            conversation=conversation_b, role="user", content="private"
        )
        url = messages_url(conversation_b.id)
        response = auth_client_a.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_empty_conversation_returns_empty_results(
        self, auth_client_a, conversation_a
    ):
        url = messages_url(conversation_a.id)
        response = auth_client_a.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["results"] == []


@pytest.mark.django_db
class TestMessageHTTPMethods:
    def test_update_own_message_not_allowed(self, auth_client_a, user_a):
        conv = Conversation.objects.create(user=user_a, title="Chat")
        msg = Message.objects.create(conversation=conv, role="user", content="original")
        url = f"{messages_url(conv.id)}{msg.id}/"
        response = auth_client_a.patch(url, {"content": "tampered"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_own_message_not_allowed(self, auth_client_a, user_a):
        conv = Conversation.objects.create(user=user_a, title="Chat")
        msg = Message.objects.create(conversation=conv, role="user", content="keep me")
        url = f"{messages_url(conv.id)}{msg.id}/"
        response = auth_client_a.delete(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert Message.objects.filter(pk=msg.pk).exists()

    def test_access_other_users_message_returns_404(self, auth_client_a, user_b):
        conv = Conversation.objects.create(user=user_b, title="Private")
        msg = Message.objects.create(conversation=conv, role="user", content="secret")
        url = f"{messages_url(conv.id)}{msg.id}/"
        response = auth_client_a.patch(url, {"content": "hacked"})
        assert response.status_code == status.HTTP_404_NOT_FOUND
