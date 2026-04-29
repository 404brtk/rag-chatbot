import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from api.models import Conversation, Message

User = get_user_model()

TOKEN_URL = "/api/token/"

VALID_PASSWORD = "4Ah?,*d]GAx2"


def messages_url(conversation_pk):
    return f"/api/conversations/{conversation_pk}/messages/"


@pytest.fixture
def user_a():
    return User.objects.create_user(email="alice@example.com", password=VALID_PASSWORD)


@pytest.fixture
def user_b():
    return User.objects.create_user(email="bob@example.com", password=VALID_PASSWORD)


@pytest.fixture
def auth_client_a(user_a):
    client = APIClient()
    tokens = client.post(
        TOKEN_URL, {"email": "alice@example.com", "password": VALID_PASSWORD}
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens.data['access']}")
    return client


@pytest.fixture
def auth_client_b(user_b):
    client = APIClient()
    tokens = client.post(
        TOKEN_URL, {"email": "bob@example.com", "password": VALID_PASSWORD}
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens.data['access']}")
    return client


@pytest.fixture
def conversation_a(user_a):
    return Conversation.objects.create(user=user_a, title="Alice's chat")


@pytest.fixture
def conversation_b(user_b):
    return Conversation.objects.create(user=user_b, title="Bob's chat")


@pytest.mark.django_db
class TestMessageCreation:
    def test_create_message_in_own_conversation(self, auth_client_a, conversation_a):
        url = messages_url(conversation_a.id)
        response = auth_client_a.post(url, {"role": "user", "content": "Hello"})
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["role"] == "user"
        assert response.data["content"] == "Hello"
        assert "created_at" in response.data

    def test_create_ai_message(self, auth_client_a, conversation_a):
        url = messages_url(conversation_a.id)
        response = auth_client_a.post(url, {"role": "ai", "content": "Hi there!"})
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["role"] == "ai"

    def test_cannot_create_message_in_other_users_conversation(
        self, auth_client_a, conversation_b
    ):
        url = messages_url(conversation_b.id)
        response = auth_client_a.post(url, {"role": "user", "content": "Sneaky"})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert Message.objects.count() == 0

    def test_create_message_in_nonexistent_conversation_returns_404(
        self, auth_client_a
    ):
        fake_id = uuid.uuid4()
        url = messages_url(fake_id)
        response = auth_client_a.post(url, {"role": "user", "content": "Hello"})
        assert response.status_code == status.HTTP_404_NOT_FOUND


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
        assert response.data["results"] == []


@pytest.mark.django_db
class TestMessageHTTPMethods:
    def test_update_message_not_allowed(self, auth_client_a, conversation_a):
        msg = Message.objects.create(
            conversation=conversation_a, role="user", content="original"
        )
        url = f"{messages_url(conversation_a.id)}{msg.id}/"
        response = auth_client_a.patch(url, {"content": "tampered"})
        assert response.status_code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def test_delete_message_not_allowed(self, auth_client_a, conversation_a):
        msg = Message.objects.create(
            conversation=conversation_a, role="user", content="keep me"
        )
        url = f"{messages_url(conversation_a.id)}{msg.id}/"
        response = auth_client_a.delete(url)
        assert response.status_code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        assert Message.objects.filter(pk=msg.pk).exists()
