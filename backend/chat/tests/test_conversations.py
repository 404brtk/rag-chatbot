from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status

from chat.models import Conversation

User = get_user_model()

CONVERSATIONS_URL = "/api/conversations/"


@pytest.mark.django_db
class TestConversationCRUD:
    def test_create_conversation(self, auth_client_a):
        response = auth_client_a.post(CONVERSATIONS_URL, {"title": "New chat"})
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["title"] == "New chat"
        assert "id" in response.data
        assert "created_at" in response.data

    def test_create_conversation_with_blank_title(self, auth_client_a):
        response = auth_client_a.post(CONVERSATIONS_URL, {})
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["title"] == ""

    def test_list_conversations_returns_only_own(
        self, auth_client_a, auth_client_b, user_a, user_b
    ):
        Conversation.objects.create(user=user_a, title="Alice's chat")
        Conversation.objects.create(user=user_b, title="Bob's chat")

        response = auth_client_a.get(CONVERSATIONS_URL)
        assert response.status_code == status.HTTP_200_OK
        titles = [c["title"] for c in response.data["results"]]
        assert "Alice's chat" in titles
        assert "Bob's chat" not in titles

    def test_list_conversations_ordered_by_activity(self, auth_client_a, user_a):
        now = timezone.now()
        Conversation.objects.create(user=user_a, title="First", last_message_at=now)
        Conversation.objects.create(
            user=user_a, title="Second", last_message_at=now - timedelta(hours=1)
        )

        response = auth_client_a.get(CONVERSATIONS_URL)
        results = response.data["results"]
        assert results[0]["title"] == "First"
        assert results[1]["title"] == "Second"

    def test_patch_conversation_title(self, auth_client_a, user_a):
        conv = Conversation.objects.create(user=user_a, title="Old title")
        url = f"{CONVERSATIONS_URL}{conv.id}/"
        response = auth_client_a.patch(url, {"title": "New title"})
        assert response.status_code == status.HTTP_200_OK
        assert response.data["title"] == "New title"

    def test_put_not_allowed(self, auth_client_a, user_a):
        conv = Conversation.objects.create(user=user_a, title="Title")
        url = f"{CONVERSATIONS_URL}{conv.id}/"
        response = auth_client_a.put(url, {"title": "Updated"})
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_delete_conversation(self, auth_client_a, user_a):
        conv = Conversation.objects.create(user=user_a, title="Delete me")
        url = f"{CONVERSATIONS_URL}{conv.id}/"
        response = auth_client_a.delete(url)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Conversation.objects.filter(pk=conv.pk).exists()

    def test_retrieve_conversation(self, auth_client_a, user_a):
        conv = Conversation.objects.create(user=user_a, title="Detail")
        url = f"{CONVERSATIONS_URL}{conv.id}/"
        response = auth_client_a.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["title"] == "Detail"


@pytest.mark.django_db
class TestConversationIsolation:
    def test_cannot_retrieve_other_users_conversation(self, auth_client_a, user_b):
        conv = Conversation.objects.create(user=user_b, title="Bob's private chat")
        url = f"{CONVERSATIONS_URL}{conv.id}/"
        response = auth_client_a.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_patch_other_users_conversation(self, auth_client_a, user_b):
        conv = Conversation.objects.create(user=user_b, title="Bob's chat")
        url = f"{CONVERSATIONS_URL}{conv.id}/"
        response = auth_client_a.patch(url, {"title": "Hacked"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_delete_other_users_conversation(self, auth_client_a, user_b):
        conv = Conversation.objects.create(user=user_b, title="Bob's chat")
        url = f"{CONVERSATIONS_URL}{conv.id}/"
        response = auth_client_a.delete(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert Conversation.objects.filter(pk=conv.pk).exists()
