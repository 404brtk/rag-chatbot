import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.db import connection, IntegrityError
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import UserApiKey

User = get_user_model()

KEYS_URL = "/api/keys/"


def key_detail_url(key_id):
    return f"{KEYS_URL}{key_id}/"


@pytest.mark.django_db
class TestEncryptedFieldRoundTrip:
    def test_value_is_encrypted_in_database(self, user_a):
        raw_key = "sk-test-key-1234567890abcdef"
        api_key = UserApiKey.objects.create(
            user=user_a, provider="openai", encrypted_key=raw_key
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT encrypted_key FROM accounts_userapikey WHERE id = %s",
                [str(api_key.id)],
            )
            db_value = cursor.fetchone()[0]
        assert db_value != raw_key
        assert db_value.startswith("gAAAAA")

    def test_value_decrypts_on_read(self, user_a):
        raw_key = "sk-test-key-1234567890abcdef"
        UserApiKey.objects.create(user=user_a, provider="openai", encrypted_key=raw_key)
        loaded = UserApiKey.objects.get(user=user_a, provider="openai")
        assert loaded.encrypted_key == raw_key

    def test_key_rotation_decrypts_with_old_key(self, user_a, settings):
        old_key = settings.FERNET_KEYS[0]
        raw_key = "sk-old-encrypted-value"
        UserApiKey.objects.create(user=user_a, provider="openai", encrypted_key=raw_key)

        new_key = Fernet.generate_key().decode()
        settings.FERNET_KEYS = [new_key, old_key]

        loaded = UserApiKey.objects.get(user=user_a, provider="openai")
        assert loaded.encrypted_key == raw_key

    def test_decrypt_fails_with_wrong_key(self, user_a, settings):
        UserApiKey.objects.create(
            user=user_a, provider="openai", encrypted_key="sk-secret"
        )
        settings.FERNET_KEYS = [Fernet.generate_key().decode()]
        with pytest.raises(ValueError, match="Failed to decrypt"):
            UserApiKey.objects.get(user=user_a, provider="openai")


@pytest.mark.django_db
class TestUserApiKeyModel:
    def test_unique_constraint_per_user_and_provider(self, user_a):
        UserApiKey.objects.create(user=user_a, provider="openai", encrypted_key="key-1")
        with pytest.raises(IntegrityError):
            UserApiKey.objects.create(
                user=user_a, provider="openai", encrypted_key="key-2"
            )

    def test_different_users_can_have_same_provider(self, user_a, user_b):
        UserApiKey.objects.create(user=user_a, provider="openai", encrypted_key="key-a")
        UserApiKey.objects.create(user=user_b, provider="openai", encrypted_key="key-b")
        assert UserApiKey.objects.count() == 2

    def test_same_user_can_have_different_providers(self, user_a):
        UserApiKey.objects.create(user=user_a, provider="openai", encrypted_key="key-1")
        UserApiKey.objects.create(
            user=user_a, provider="openrouter", encrypted_key="key-2"
        )
        assert user_a.api_keys.count() == 2

    def test_cascade_deletes_keys_when_user_deleted(self, user_a):
        UserApiKey.objects.create(user=user_a, provider="openai", encrypted_key="key-1")
        user_a.delete()
        assert UserApiKey.objects.count() == 0

    def test_masked_key_hides_middle(self, user_a):
        api_key = UserApiKey.objects.create(
            user=user_a, provider="openai", encrypted_key="sk-1234567890abcdef"
        )
        loaded = UserApiKey.objects.get(pk=api_key.pk)
        assert loaded.masked_key == "sk-...cdef"

    def test_masked_key_short_value_returns_stars(self, user_a):
        api_key = UserApiKey.objects.create(
            user=user_a, provider="openai", encrypted_key="short"
        )
        loaded = UserApiKey.objects.get(pk=api_key.pk)
        assert loaded.masked_key == "****"


@pytest.mark.django_db
class TestUserApiKeyAPI:
    def test_create_key(self, auth_client_a):
        response = auth_client_a.post(
            KEYS_URL,
            {"provider": "openai", "api_key": "sk-live-abc123xyz"},
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["provider"] == "openai"
        assert "api_key" not in response.data
        assert response.data["masked_key"] == "sk-...3xyz"

    def test_list_keys_returns_masked_values(self, auth_client_a, user_a):
        UserApiKey.objects.create(
            user=user_a, provider="openai", encrypted_key="sk-1234567890abcdef"
        )
        response = auth_client_a.get(KEYS_URL)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert "api_key" not in response.data[0]
        assert response.data[0]["masked_key"] == "sk-...cdef"

    def test_update_key_value(self, auth_client_a, user_a):
        api_key = UserApiKey.objects.create(
            user=user_a, provider="openai", encrypted_key="sk-old-key-value1"
        )
        response = auth_client_a.patch(
            key_detail_url(api_key.id),
            {"api_key": "sk-new-key-value2"},
        )
        assert response.status_code == status.HTTP_200_OK
        api_key.refresh_from_db()
        assert api_key.encrypted_key == "sk-new-key-value2"

    def test_delete_key(self, auth_client_a, user_a):
        api_key = UserApiKey.objects.create(
            user=user_a, provider="openai", encrypted_key="sk-to-delete-1234"
        )
        response = auth_client_a.delete(key_detail_url(api_key.id))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not UserApiKey.objects.filter(pk=api_key.pk).exists()

    def test_cannot_create_duplicate_provider(self, auth_client_a, user_a):
        UserApiKey.objects.create(
            user=user_a, provider="openai", encrypted_key="sk-existing-key1"
        )
        response = auth_client_a.post(
            KEYS_URL,
            {"provider": "openai", "api_key": "sk-another-key12"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_see_other_users_keys(self, auth_client_a, user_b):
        UserApiKey.objects.create(
            user=user_b, provider="openai", encrypted_key="sk-bobs-secret-key"
        )
        response = auth_client_a.get(KEYS_URL)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 0

    def test_cannot_delete_other_users_key(self, auth_client_a, user_b):
        api_key = UserApiKey.objects.create(
            user=user_b, provider="openai", encrypted_key="sk-bobs-secret-key"
        )
        response = auth_client_a.delete(key_detail_url(api_key.id))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert UserApiKey.objects.filter(pk=api_key.pk).exists()

    def test_unauthenticated_request_rejected(self):
        client = APIClient()
        response = client.get(KEYS_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
