import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.test import AsyncClient
from rest_framework.test import APIClient

from api.llm_config import StreamEvent
from api.models import Conversation

from .conftest import VALID_PASSWORD

User = get_user_model()


def stream_url(conversation_pk):
    return f"/api/conversations/{conversation_pk}/messages/stream/"


@pytest.mark.django_db(transaction=True)
class TestMessageStreamView:
    def test_unauthorized_returns_401(self):
        client = APIClient()
        response = client.post(
            stream_url(uuid.uuid4()),
            data="{}",
            content_type="application/json",
        )
        assert response.status_code == 401
        body = b"".join(list(response))
        payload = json.loads(body.decode().removeprefix("data: "))
        assert payload["type"] == "error"

    @patch("api.views.ChatService")
    async def test_stream_success(self, mock_svc_cls, user_a, api_key):
        conv = await sync_to_async(Conversation.objects.create)(user=user_a)

        mock_instance = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(type="token", content="Hi")
            yield StreamEvent(
                type="done",
                message_id="msg-1",
                title=None,
                usage={},
                provider="openai",
                model="gpt-5.5",
            )

        mock_instance.generate_reply_stream = mock_stream
        mock_svc_cls.return_value = mock_instance

        client = AsyncClient()
        token_resp = await client.post(
            "/api/token/",
            {"email": "alice@example.com", "password": VALID_PASSWORD},
        )
        token = json.loads(token_resp.content)["access"]

        response = await client.post(
            stream_url(conv.id),
            data=json.dumps({"content": "Hello"}),
            content_type="application/json",
            headers={"authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        body = b"".join([chunk async for chunk in response]).decode()
        events = []
        for raw in body.strip().split("\n\n"):
            if raw.startswith("data: "):
                events.append(json.loads(raw[6:]))

        assert len(events) == 2
        assert events[0]["type"] == "token"
        assert events[0]["content"] == "Hi"
        assert events[1]["type"] == "done"
        assert events[1]["message_id"] == "msg-1"

    def test_invalid_json_returns_400(self, auth_client_a, user_a):
        conv = Conversation.objects.create(user=user_a)
        response = auth_client_a.post(
            stream_url(conv.id),
            data="not json",
            content_type="application/json",
        )
        assert response.status_code == 400
        body = b"".join(list(response))
        payload = json.loads(body.decode().removeprefix("data: "))
        assert payload["type"] == "error"
        assert payload["code"] == "invalid_json"

    def test_missing_content_returns_400(self, auth_client_a, user_a):
        conv = Conversation.objects.create(user=user_a)
        response = auth_client_a.post(
            stream_url(conv.id),
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400
        body = b"".join(list(response))
        payload = json.loads(body.decode().removeprefix("data: "))
        assert payload["type"] == "error"
        assert payload["code"] == "missing_content"

    def test_cannot_stream_in_other_users_conversation(self, auth_client_a, user_b):
        conv = Conversation.objects.create(user=user_b)
        response = auth_client_a.post(
            stream_url(conv.id),
            data=json.dumps({"content": "Hello"}),
            content_type="application/json",
        )
        assert response.status_code == 404

    @patch("api.views.ChatService")
    async def test_auto_title_from_stream(self, mock_svc_cls, user_a, api_key):
        conv = await sync_to_async(Conversation.objects.create)(user=user_a)

        mock_instance = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(type="token", content="Answer")
            yield StreamEvent(
                type="done",
                message_id="msg-1",
                title="Hello world",
                usage={},
                provider="openai",
                model="gpt-5.5",
            )

        mock_instance.generate_reply_stream = mock_stream
        mock_svc_cls.return_value = mock_instance

        client = AsyncClient()
        token_resp = await client.post(
            "/api/token/",
            {"email": "alice@example.com", "password": VALID_PASSWORD},
        )
        token = json.loads(token_resp.content)["access"]

        response = await client.post(
            stream_url(conv.id),
            data=json.dumps({"content": "Hello world"}),
            content_type="application/json",
            headers={"authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200

    def test_invalid_document_ids_returns_400(self, auth_client_a, user_a):
        conv = Conversation.objects.create(user=user_a)
        response = auth_client_a.post(
            stream_url(conv.id),
            data=json.dumps({"content": "Hello", "document_ids": "not-a-list"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        body = b"".join(list(response))
        payload = json.loads(body.decode().removeprefix("data: "))
        assert payload["type"] == "error"
        assert payload["code"] == "invalid_document_ids"
