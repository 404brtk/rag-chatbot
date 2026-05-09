import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from .conftest import TOKEN_URL, VALID_PASSWORD

User = get_user_model()

REGISTER_URL = "/api/register/"
TOKEN_REFRESH_URL = "/api/token/refresh/"
TOKEN_BLACKLIST_URL = "/api/token/blacklist/"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
class TestRegistration:
    def test_register_success(self, api_client):
        response = api_client.post(
            REGISTER_URL,
            {
                "email": "new@example.com",
                "password": VALID_PASSWORD,
                "password_confirm": VALID_PASSWORD,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["email"] == "new@example.com"
        assert "password" not in response.data
        assert "password_confirm" not in response.data
        assert User.objects.filter(email="new@example.com").exists()

    def test_register_password_mismatch(self, api_client):
        response = api_client.post(
            REGISTER_URL,
            {
                "email": "new@example.com",
                "password": VALID_PASSWORD,
                "password_confirm": "DifferentPass123!",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "password_confirm" in response.data

    def test_register_weak_password_rejected(self, api_client):
        response = api_client.post(
            REGISTER_URL,
            {
                "email": "new@example.com",
                "password": "123",
                "password_confirm": "123",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_duplicate_email_rejected(self, api_client, user_a):
        response = api_client.post(
            REGISTER_URL,
            {
                "email": "alice@example.com",
                "password": VALID_PASSWORD,
                "password_confirm": VALID_PASSWORD,
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "email" in response.data

    def test_register_missing_email(self, api_client):
        response = api_client.post(
            REGISTER_URL,
            {
                "password": VALID_PASSWORD,
                "password_confirm": VALID_PASSWORD,
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_invalid_email_format(self, api_client):
        response = api_client.post(
            REGISTER_URL,
            {
                "email": "not-an-email",
                "password": VALID_PASSWORD,
                "password_confirm": VALID_PASSWORD,
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestJWTLogin:
    def test_login_with_email_returns_tokens(self, api_client, user_a):
        response = api_client.post(
            TOKEN_URL,
            {
                "email": "alice@example.com",
                "password": VALID_PASSWORD,
            },
        )
        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data

    def test_login_email_is_case_insensitive(self, api_client, user_a):
        response = api_client.post(
            TOKEN_URL,
            {
                "email": "ALICE@EXAMPLE.COM",
                "password": VALID_PASSWORD,
            },
        )
        assert response.status_code == status.HTTP_200_OK

    def test_login_wrong_password_rejected(self, api_client, user_a):
        response = api_client.post(
            TOKEN_URL,
            {
                "email": "alice@example.com",
                "password": "WrongPassword!123",
            },
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_nonexistent_user_rejected(self, api_client):
        response = api_client.post(
            TOKEN_URL,
            {
                "email": "ghost@example.com",
                "password": VALID_PASSWORD,
            },
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestJWTTokenRefresh:
    def test_refresh_returns_new_access_token(self, api_client, user_a):
        login = api_client.post(
            TOKEN_URL,
            {
                "email": "alice@example.com",
                "password": VALID_PASSWORD,
            },
        )
        refresh_token = login.data["refresh"]
        response = api_client.post(TOKEN_REFRESH_URL, {"refresh": refresh_token})
        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data

    def test_refresh_with_invalid_token_rejected(self, api_client):
        response = api_client.post(TOKEN_REFRESH_URL, {"refresh": "invalid.token.here"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestJWTTokenBlacklist:
    def test_blacklisted_refresh_token_cannot_be_reused(self, api_client, user_a):
        login = api_client.post(
            TOKEN_URL,
            {
                "email": "alice@example.com",
                "password": VALID_PASSWORD,
            },
        )
        refresh_token = login.data["refresh"]
        blacklist_response = api_client.post(
            TOKEN_BLACKLIST_URL, {"refresh": refresh_token}
        )
        assert blacklist_response.status_code == status.HTTP_200_OK

        reuse_response = api_client.post(TOKEN_REFRESH_URL, {"refresh": refresh_token})
        assert reuse_response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestAuthenticatedAccess:
    def test_unauthenticated_request_rejected(self, api_client):
        response = api_client.get("/api/conversations/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_authenticated_request_succeeds(self, api_client, user_a):
        login = api_client.post(
            TOKEN_URL,
            {
                "email": "alice@example.com",
                "password": VALID_PASSWORD,
            },
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        response = api_client.get("/api/conversations/")
        assert response.status_code == status.HTTP_200_OK
