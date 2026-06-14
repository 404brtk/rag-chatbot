from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from chat.repositories import StoredMessage
from chat.provider_gateway import (
    ProviderGateway,
    _build_openai_messages,
    _build_gemini_messages,
)
from chat.llm_config import ProviderChunk
from core.exceptions import TemporaryProviderError, PermanentProviderError
from google.genai.errors import APIError, ClientError

from conftest import DEFAULT_CONFIG


class TestProviderGateway:
    @patch("chat.provider_gateway.AsyncOpenAI")
    async def test_routes_to_openai_for_openai_provider(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello!"
        mock_response.usage.model_dump.return_value = {
            "prompt_tokens": 5,
            "completion_tokens": 2,
        }
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        gateway = ProviderGateway()
        result = await gateway.generate(
            api_key="sk-test",
            config=DEFAULT_CONFIG,
            messages=[StoredMessage(role="user", content="Hi")],
        )

        assert result.provider == "openai"
        assert result.text == "Hello!"
        mock_client.chat.completions.create.assert_called_once()

    @patch("chat.provider_gateway.AsyncOpenAI")
    async def test_generate_passes_response_format(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello!"
        mock_response.usage.model_dump.return_value = {
            "prompt_tokens": 5,
            "completion_tokens": 2,
        }
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        gateway = ProviderGateway()
        response_format = {"type": "json_object"}
        result = await gateway.generate(
            api_key="sk-test",
            config=DEFAULT_CONFIG,
            messages=[StoredMessage(role="user", content="Hi")],
            response_format=response_format,
        )

        assert result.provider == "openai"
        assert result.text == "Hello!"
        mock_client.chat.completions.create.assert_called_once_with(
            model=DEFAULT_CONFIG.model,
            messages=[
                {"role": "system", "content": DEFAULT_CONFIG.system_prompt},
                {"role": "user", "content": "Hi"},
            ],
            max_completion_tokens=DEFAULT_CONFIG.max_output_tokens,
            temperature=DEFAULT_CONFIG.temperature,
            response_format=response_format,
        )

    async def test_raises_permanent_error_for_unsupported_provider(self):
        gateway = ProviderGateway()
        config = replace(DEFAULT_CONFIG, provider="unsupported")

        with pytest.raises(PermanentProviderError, match="Unsupported provider"):
            await gateway.generate(
                api_key="sk-test",
                config=config,
                messages=[StoredMessage(role="user", content="Hi")],
            )

    @pytest.mark.parametrize(
        "error_class,expected_exception,kwargs",
        [
            (
                openai.RateLimitError,
                TemporaryProviderError,
                {"message": "rate limited", "response": MagicMock(), "body": None},
            ),
            (
                openai.BadRequestError,
                PermanentProviderError,
                {"message": "bad request", "response": MagicMock(), "body": None},
            ),
            (
                openai.APIConnectionError,
                TemporaryProviderError,
                {"request": MagicMock()},
            ),
            (
                openai.APITimeoutError,
                TemporaryProviderError,
                {"request": MagicMock()},
            ),
            (
                openai.InternalServerError,
                TemporaryProviderError,
                {"message": "internal error", "response": MagicMock(), "body": None},
            ),
            (
                openai.AuthenticationError,
                PermanentProviderError,
                {"message": "invalid key", "response": MagicMock(), "body": None},
            ),
        ],
    )
    @patch("chat.provider_gateway.AsyncOpenAI")
    async def test_maps_openai_errors(
        self, mock_openai_cls, error_class, expected_exception, kwargs
    ):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = error_class(**kwargs)

        gateway = ProviderGateway()
        with pytest.raises(expected_exception):
            await gateway.generate(
                api_key="sk-test",
                config=DEFAULT_CONFIG,
                messages=[StoredMessage(role="user", content="Hi")],
            )

    @patch("chat.provider_gateway.AsyncOpenAI")
    async def test_stream_yields_tokens_and_usage(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        chunk_a = MagicMock(usage=None, choices=[MagicMock()])
        chunk_a.choices[0].delta.content = "Hello"
        chunk_b = MagicMock(usage=None, choices=[MagicMock()])
        chunk_b.choices[0].delta.content = " world"
        usage_chunk = MagicMock(choices=[], usage=MagicMock())
        usage_chunk.usage.model_dump.return_value = {
            "prompt_tokens": 10,
            "completion_tokens": 3,
        }

        async def fake_stream():
            for c in [chunk_a, chunk_b, usage_chunk]:
                yield c

        mock_client.chat.completions.create = AsyncMock(return_value=fake_stream())

        gateway = ProviderGateway()
        chunks = [
            c
            async for c in gateway.generate_stream(
                api_key="sk-test",
                config=DEFAULT_CONFIG,
                messages=[StoredMessage(role="user", content="Hi")],
            )
        ]

        text_chunks = [c for c in chunks if c.text]
        usage_chunks = [c for c in chunks if c.usage]
        assert len(text_chunks) == 2
        assert text_chunks[0] == ProviderChunk(text="Hello")
        assert text_chunks[1] == ProviderChunk(text=" world")
        assert len(usage_chunks) == 1
        assert usage_chunks[0].usage["prompt_tokens"] == 10

    @patch("chat.provider_gateway.AsyncOpenAI")
    async def test_stream_maps_openai_errors(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai.RateLimitError(
                message="rate limited", response=MagicMock(), body=None
            )
        )

        gateway = ProviderGateway()
        with pytest.raises(TemporaryProviderError):
            async for _ in gateway.generate_stream(
                api_key="sk-test",
                config=DEFAULT_CONFIG,
                messages=[StoredMessage(role="user", content="Hi")],
            ):
                pass

    async def test_stream_raises_for_unsupported_provider(self):
        gateway = ProviderGateway()
        config = replace(DEFAULT_CONFIG, provider="unsupported")
        with pytest.raises(PermanentProviderError, match="Unsupported provider"):
            async for _ in gateway.generate_stream(
                api_key="sk-test",
                config=config,
                messages=[StoredMessage(role="user", content="Hi")],
            ):
                pass

    @patch("chat.provider_gateway.AsyncOpenAI")
    def test_build_client_llamacpp_sets_base_url(self, mock_openai_cls):
        ProviderGateway._build_client(api_key="llamacpp", provider="llamacpp")
        mock_openai_cls.assert_called_once_with(
            base_url="http://localhost:8080/v1",
            api_key="llamacpp",
            timeout=60.0,
            max_retries=2,
        )

    @patch("chat.provider_gateway.AsyncOpenAI")
    def test_build_client_openai_uses_defaults(self, mock_openai_cls):
        ProviderGateway._build_client(api_key="sk-test", provider="openai")
        mock_openai_cls.assert_called_once_with(
            api_key="sk-test",
            timeout=30.0,
            max_retries=2,
        )

    @patch("chat.provider_gateway.httpx.AsyncClient")
    async def test_discover_llamacpp_context_fetches_n_ctx(self, mock_client_cls):
        ProviderGateway._llamacpp_context = None

        mock_client = MagicMock()
        mock_client.__aenter__.return_value = mock_client
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {"default_generation_settings": {"n_ctx": 8192}}
        mock_client.get = AsyncMock(return_value=fake_resp)
        mock_client_cls.return_value = mock_client

        n_ctx = await ProviderGateway.discover_llamacpp_context()

        assert n_ctx == 8192
        assert ProviderGateway._llamacpp_context == 8192
        mock_client.get.assert_called_once_with("http://localhost:8080/props")

    async def test_discover_llamacpp_context_returns_cached_value(self):
        ProviderGateway._llamacpp_context = 16384

        n_ctx = await ProviderGateway.discover_llamacpp_context()

        assert n_ctx == 16384

    @patch("chat.provider_gateway.httpx.AsyncClient")
    async def test_discover_llamacpp_models_fetches_data(self, mock_client_cls):
        ProviderGateway._llamacpp_models = None

        mock_client = MagicMock()
        mock_client.__aenter__.return_value = mock_client
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {
            "data": [
                {"id": "model-a", "object": "model", "owned_by": "llamacpp"},
                {"id": "model-b", "object": "model", "owned_by": "llamacpp"},
            ]
        }
        mock_client.get = AsyncMock(return_value=fake_resp)
        mock_client_cls.return_value = mock_client

        models = await ProviderGateway.discover_llamacpp_models()

        assert len(models) == 2
        assert models[0]["id"] == "model-a"
        assert models[1]["id"] == "model-b"
        assert ProviderGateway._llamacpp_models == models
        mock_client.get.assert_called_once_with("http://localhost:8080/v1/models")

    async def test_discover_llamacpp_models_returns_cached_value(self):
        ProviderGateway._llamacpp_models = [
            {"id": "cached-model", "object": "model", "owned_by": "llamacpp"}
        ]
        ProviderGateway._llamacpp_models_fetched_at = 100.0

        with patch("chat.provider_gateway.time.time", return_value=200.0):
            models = await ProviderGateway.discover_llamacpp_models()

        assert models == [
            {"id": "cached-model", "object": "model", "owned_by": "llamacpp"}
        ]

    @patch("chat.provider_gateway.httpx.AsyncClient")
    async def test_discover_llamacpp_models_fetches_fresh_after_ttl_expires(
        self, mock_client_cls
    ):
        ProviderGateway._llamacpp_models = [
            {"id": "stale-model", "object": "model", "owned_by": "llamacpp"}
        ]
        ProviderGateway._llamacpp_models_fetched_at = 100.0

        mock_client = MagicMock()
        mock_client.__aenter__.return_value = mock_client
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {
            "data": [{"id": "fresh-model", "object": "model", "owned_by": "llamacpp"}]
        }
        mock_client.get = AsyncMock(return_value=fake_resp)
        mock_client_cls.return_value = mock_client

        with patch("chat.provider_gateway.time.time", return_value=450.0):
            models = await ProviderGateway.discover_llamacpp_models()

        assert models == [
            {"id": "fresh-model", "object": "model", "owned_by": "llamacpp"}
        ]
        mock_client.get.assert_called_once()

    def test_build_openai_messages_no_attachments(self):
        msgs = [StoredMessage(role="user", content="Hello there!")]
        result = _build_openai_messages(msgs)
        assert result == [{"role": "user", "content": "Hello there!"}]

    @patch("os.path.exists", return_value=True)
    @patch("builtins.open")
    def test_build_openai_messages_with_images(self, mock_open, mock_exists):
        mock_file = MagicMock()
        mock_file.read.return_value = b"abc"
        mock_open.return_value.__enter__.return_value = mock_file

        msgs = [
            StoredMessage(
                role="user",
                content="Look at this:",
                attachments=[
                    {
                        "id": "chart.png",
                        "name": "chart.png",
                        "size": 500,
                        "mimeType": "image/png",
                    }
                ],
            )
        ]
        result = _build_openai_messages(msgs)
        assert result == [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Look at this:"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,YWJj"},
                    },
                ],
            }
        ]

    @patch("os.path.exists", return_value=True)
    @patch("builtins.open")
    def test_build_openai_messages_multiline_text(self, mock_open, mock_exists):
        mock_file = MagicMock()
        mock_file.read.return_value = b"abc"
        mock_open.return_value.__enter__.return_value = mock_file

        msgs = [
            StoredMessage(
                role="user",
                content="Look at this:\nHope it helps.",
                attachments=[
                    {
                        "id": "chart.png",
                        "name": "chart.png",
                        "size": 500,
                        "mimeType": "image/png",
                    }
                ],
            )
        ]
        result = _build_openai_messages(msgs)
        assert result == [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Look at this:\nHope it helps."},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,YWJj"},
                    },
                ],
            }
        ]

    @patch("os.path.exists", return_value=False)
    def test_build_openai_messages_media_url_fallback(self, mock_exists):
        msgs = [
            StoredMessage(
                role="user",
                content="Look at this:",
                attachments=[
                    {
                        "id": "chart-uuid.png",
                        "name": "chart.png",
                        "size": 500,
                        "mimeType": "image/png",
                    }
                ],
            )
        ]
        result = _build_openai_messages(msgs)
        assert result == [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Look at this:"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "/media/attachments/chart-uuid.png"},
                    },
                ],
            }
        ]

    def test_build_openai_messages_prevents_path_traversal(self):
        msgs = [
            StoredMessage(
                role="user",
                content="Look at this:",
                attachments=[
                    {
                        "id": "../etc/passwd",
                        "name": "passwd",
                        "size": 500,
                        "mimeType": "text/plain",
                    },
                    {
                        "id": "/absolute/path/file.txt",
                        "name": "absolute",
                        "size": 500,
                        "mimeType": "text/plain",
                    },
                    {
                        "id": "safe-file.txt",
                        "name": "safe",
                        "size": 500,
                        "mimeType": "text/plain",
                    },
                ],
            )
        ]
        with patch(
            "chat.provider_gateway.load_text_attachment", return_value="safe content"
        ) as mock_load:
            result = _build_openai_messages(msgs)
            mock_load.assert_called_once_with("safe-file.txt")

        assert result == [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Look at this:"},
                    {
                        "type": "text",
                        "text": "--- File: safe ---\nsafe content\n----------------",
                    },
                ],
            }
        ]

    @patch("chat.provider_gateway.genai.Client")
    async def test_routes_to_gemini_for_gemini_provider(self, mock_genai_client_cls):
        mock_client = MagicMock()
        mock_genai_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "Hello from Gemini!"
        mock_response.usage_metadata.prompt_token_count = 8
        mock_response.usage_metadata.candidates_token_count = 4
        mock_response.usage_metadata.total_token_count = 12

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        config = replace(
            DEFAULT_CONFIG, provider="gemini", model="gemini-3.1-flash-lite"
        )

        gateway = ProviderGateway()
        result = await gateway.generate(
            api_key="gemini-key",
            config=config,
            messages=[StoredMessage(role="user", content="Hi")],
        )

        assert result.provider == "gemini"
        assert result.model == "gemini-3.1-flash-lite"
        assert result.text == "Hello from Gemini!"
        assert result.input_tokens == 8
        assert result.output_tokens == 4
        mock_client.aio.models.generate_content.assert_called_once()

    @patch("chat.provider_gateway.genai.Client")
    async def test_gemini_stream_yields_tokens_and_usage(self, mock_genai_client_cls):
        mock_client = MagicMock()
        mock_genai_client_cls.return_value = mock_client

        chunk_a = MagicMock()
        chunk_a.text = "Hello"
        chunk_a.usage_metadata = None

        chunk_b = MagicMock()
        chunk_b.text = " Gemini"
        chunk_b.usage_metadata = MagicMock()
        chunk_b.usage_metadata.prompt_token_count = 6
        chunk_b.usage_metadata.candidates_token_count = 2
        chunk_b.usage_metadata.total_token_count = 8

        async def fake_stream():
            for chunk in [chunk_a, chunk_b]:
                yield chunk

        mock_client.aio.models.generate_content_stream = AsyncMock(
            return_value=fake_stream()
        )

        config = replace(
            DEFAULT_CONFIG, provider="gemini", model="gemini-3.1-flash-lite"
        )

        gateway = ProviderGateway()
        chunks = [
            c
            async for c in gateway.generate_stream(
                api_key="gemini-key",
                config=config,
                messages=[StoredMessage(role="user", content="Hi")],
            )
        ]

        text_chunks = [c for c in chunks if c.text]
        usage_chunks = [c for c in chunks if c.usage]
        assert len(text_chunks) == 2
        assert text_chunks[0] == ProviderChunk(text="Hello")
        assert text_chunks[1].text == " Gemini"
        assert len(usage_chunks) == 1
        assert usage_chunks[0].usage["prompt_tokens"] == 6

    def test_build_gemini_messages_no_attachments(self):
        msgs = [StoredMessage(role="user", content="Hello there!")]
        result = _build_gemini_messages(msgs)
        assert result == [{"role": "user", "parts": [{"text": "Hello there!"}]}]

    def test_build_gemini_messages_role_mapping(self):
        msgs = [
            StoredMessage(role="user", content="Hi"),
            StoredMessage(role="ai", content="Hello"),
        ]
        result = _build_gemini_messages(msgs)
        assert result == [
            {"role": "user", "parts": [{"text": "Hi"}]},
            {"role": "model", "parts": [{"text": "Hello"}]},
        ]

    @patch("os.path.exists", return_value=True)
    @patch("builtins.open")
    def test_build_gemini_messages_with_images(self, mock_open, mock_exists):
        mock_file = MagicMock()
        mock_file.read.return_value = b"abc"
        mock_open.return_value.__enter__.return_value = mock_file

        msgs = [
            StoredMessage(
                role="user",
                content="Look at this:",
                attachments=[
                    {
                        "id": "chart.png",
                        "name": "chart.png",
                        "size": 500,
                        "mimeType": "image/png",
                    }
                ],
            )
        ]
        result = _build_gemini_messages(msgs)
        assert result == [
            {
                "role": "user",
                "parts": [
                    {"text": "Look at this:"},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": b"abc",
                        }
                    },
                ],
            }
        ]

    def test_build_gemini_messages_prevents_path_traversal(self):
        msgs = [
            StoredMessage(
                role="user",
                content="Look at this:",
                attachments=[
                    {
                        "id": "../etc/passwd",
                        "name": "passwd",
                        "size": 500,
                        "mimeType": "text/plain",
                    },
                    {
                        "id": "/absolute/path/file.txt",
                        "name": "absolute",
                        "size": 500,
                        "mimeType": "text/plain",
                    },
                    {
                        "id": "safe-file.txt",
                        "name": "safe",
                        "size": 500,
                        "mimeType": "text/plain",
                    },
                ],
            )
        ]
        with patch(
            "chat.provider_gateway.load_text_attachment", return_value="safe content"
        ) as mock_load:
            result = _build_gemini_messages(msgs)
            mock_load.assert_called_once_with("safe-file.txt")

        assert result == [
            {
                "role": "user",
                "parts": [
                    {"text": "Look at this:"},
                    {"text": "--- File: safe ---\nsafe content\n----------------"},
                ],
            }
        ]

    @patch("chat.provider_gateway.genai.Client")
    async def test_routes_to_gemini_passes_response_format(self, mock_genai_client_cls):
        mock_client = MagicMock()
        mock_genai_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = '{"success": true}'
        mock_response.usage_metadata.prompt_token_count = 8
        mock_response.usage_metadata.candidates_token_count = 4
        mock_response.usage_metadata.total_token_count = 12

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        config = replace(
            DEFAULT_CONFIG, provider="gemini", model="gemini-3.1-flash-lite"
        )

        gateway = ProviderGateway()
        response_format = {
            "type": "json_object",
            "json_schema": {
                "schema": {
                    "type": "OBJECT",
                    "properties": {"success": {"type": "BOOLEAN"}},
                }
            },
        }
        result = await gateway.generate(
            api_key="gemini-key",
            config=config,
            messages=[StoredMessage(role="user", content="Hi")],
            response_format=response_format,
        )

        assert result.text == '{"success": true}'
        args, kwargs = mock_client.aio.models.generate_content.call_args
        gen_config = kwargs["config"]
        assert gen_config.response_mime_type == "application/json"
        assert gen_config.response_schema == {
            "type": "OBJECT",
            "properties": {"success": {"type": "BOOLEAN"}},
        }

    @pytest.mark.parametrize(
        "error_class,expected_exception,code",
        [
            (ClientError, PermanentProviderError, 400),
            (APIError, TemporaryProviderError, 500),
            (ValueError, TemporaryProviderError, None),
        ],
    )
    @patch("chat.provider_gateway.genai.Client")
    async def test_maps_gemini_errors(
        self, mock_genai_client_cls, error_class, expected_exception, code
    ):
        mock_client = MagicMock()
        mock_genai_client_cls.return_value = mock_client
        if code is not None:
            err = error_class(code=code, response_json={"message": "Gemini error"})
        else:
            err = error_class("Gemini error")
        mock_client.aio.models.generate_content.side_effect = err

        config = replace(
            DEFAULT_CONFIG, provider="gemini", model="gemini-3.1-flash-lite"
        )

        gateway = ProviderGateway()
        with pytest.raises(expected_exception):
            await gateway.generate(
                api_key="gemini-key",
                config=config,
                messages=[StoredMessage(role="user", content="Hi")],
            )

    @patch("chat.provider_gateway.genai.Client")
    async def test_gemini_stream_maps_errors(self, mock_genai_client_cls):
        mock_client = MagicMock()
        mock_genai_client_cls.return_value = mock_client
        mock_client.aio.models.generate_content_stream.side_effect = ClientError(
            code=400, response_json={"message": "Gemini error"}
        )

        config = replace(
            DEFAULT_CONFIG, provider="gemini", model="gemini-3.1-flash-lite"
        )

        gateway = ProviderGateway()
        with pytest.raises(PermanentProviderError):
            async for _ in gateway.generate_stream(
                api_key="gemini-key",
                config=config,
                messages=[StoredMessage(role="user", content="Hi")],
            ):
                pass
