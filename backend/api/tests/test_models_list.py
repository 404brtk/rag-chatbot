from unittest.mock import patch

import pytest
from rest_framework import status

MODELS_URL = "/api/models/"


@pytest.mark.django_db
class TestModelList:
    @patch("api.views.ChatService.get_available_models")
    def test_public_no_auth_required(self, mock_get_models, client):
        mock_get_models.return_value = {"openai": [], "llamacpp": []}
        response = client.get(MODELS_URL)
        assert response.status_code == status.HTTP_200_OK

    @patch("api.views.ChatService.get_available_models")
    def test_authenticated_also_works(self, mock_get_models, auth_client_a):
        mock_get_models.return_value = {"openai": [], "llamacpp": []}
        response = auth_client_a.get(MODELS_URL)
        assert response.status_code == status.HTTP_200_OK

    @patch("api.views.ChatService.get_available_models")
    def test_returns_data_from_service(self, mock_get_models, client):
        expected_data = {
            "openai": ["gpt-5.5", "gpt-5.4"],
            "llamacpp": ["local-model-1", "local-model-2"],
        }
        mock_get_models.return_value = expected_data

        response = client.get(MODELS_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.data == expected_data
        mock_get_models.assert_called_once()
