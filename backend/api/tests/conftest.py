from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from api.llm_config import LLMConfig
from api.models import UserApiKey
from api.repositories import StoredMessage

User = get_user_model()

VALID_PASSWORD = "4Ah?,*d]GAx2"
TOKEN_URL = "/api/token/"
DEFAULT_CONFIG = LLMConfig(
    provider="openai",
    model="gpt",
    system_prompt="You are a helpful assistant.",
    compaction_provider="openai",
    compaction_model="gpt",
    compaction_enabled=True,
)


def _msg(role, content, created_at=None, is_compaction_summary=False):
    return StoredMessage(
        role=role,
        content=content,
        created_at=created_at or datetime(2025, 1, 1, tzinfo=timezone.utc),
        is_compaction_summary=is_compaction_summary,
    )


@pytest.fixture(autouse=True)
def _fernet_settings(settings):
    settings.FERNET_KEYS = [Fernet.generate_key().decode()]


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
def api_key(user_a):
    return UserApiKey.objects.create(
        user=user_a, provider="openai", encrypted_key="sk-chat"
    )


@pytest.fixture
def mock_embedding_service():
    with patch("api.document_service.EmbeddingService.get_instance") as mock:
        instance = mock.return_value
        instance.embed_texts.return_value = [[0.1] * 384 for _ in range(200)]
        instance.embed_query.return_value = [0.1] * 384
        yield instance
