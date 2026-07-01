from unittest.mock import patch, AsyncMock

import pytest
from rest_framework import status

HEALTH_URL = "/api/health/"


@pytest.mark.django_db
class TestHealth:
    def test_health_public_no_auth_required(self, client):
        response = client.get(HEALTH_URL)
        assert response.status_code == status.HTTP_200_OK

    def test_health_authenticated_also_works(self, auth_client_a):
        response = auth_client_a.get(HEALTH_URL)
        assert response.status_code == status.HTTP_200_OK

    def test_health_returns_ok(self, client):
        response = client.get(HEALTH_URL)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "ok"
        assert data["database"] == "connected"

    def test_health_db_down_returns_503(self, client):
        mock_qs = AsyncMock()
        mock_qs.aexists = AsyncMock(side_effect=RuntimeError("connection failed"))
        with patch("chat.views.Conversation.objects.none", return_value=mock_qs):
            response = client.get(HEALTH_URL)
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        data = response.json()
        assert data["status"] == "unhealthy"
        assert "database" not in data
