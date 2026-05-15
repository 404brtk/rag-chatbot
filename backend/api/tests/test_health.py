from unittest.mock import patch

import pytest
from django.db import connection
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
        assert response.data["status"] == "ok"
        assert response.data["database"] == "connected"

    def test_health_db_down_returns_503(self, client):
        with patch.object(
            connection, "cursor", side_effect=RuntimeError("connection failed")
        ):
            response = client.get(HEALTH_URL)
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.data["status"] == "unhealthy"
        assert "database" not in response.data
